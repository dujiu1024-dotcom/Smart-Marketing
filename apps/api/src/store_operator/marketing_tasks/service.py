import hashlib
import json
from collections import defaultdict
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from store_operator.auth.audit import record_audit
from store_operator.auth.context import AuthContext
from store_operator.auth.dependencies import AuthenticatedSession
from store_operator.auth.errors import ApiError
from store_operator.domain.marketing_task import (
    InvalidMarketingTaskTransition,
    InvalidTaskStepTransition,
    MarketingTaskStatus,
    MarketingTaskType,
    StepApplicability,
    TaskStepKey,
    TaskStepStatus,
    ensure_step_transition,
    ensure_task_transition,
    resolve_step_applicability,
)
from store_operator.idempotency import begin_idempotency, complete_idempotency
from store_operator.jobs.service import (
    JobIdempotencyConflict,
    create_job,
    request_job_cancellation,
)
from store_operator.marketing_tasks.schemas import (
    MarketingTaskAction,
    MarketingTaskCreate,
    MarketingTaskDetail,
    MarketingTaskList,
    MarketingTaskOptions,
    MarketingTaskRecover,
    MarketingTaskRequirementConfirm,
    MarketingTaskRequirementUpdate,
    MarketingTaskStepSkip,
    MarketingTaskStrategyConfirm,
    MarketingTaskStrategyUpdate,
    MarketingTaskSummary,
    TaskStepRead,
)
from store_operator.models.job_runtime import Job
from store_operator.models.marketing_task import (
    BusinessFactSnapshot,
    DependencyEdge,
    MarketingTask,
    RequirementSnapshot,
    StepDecision,
    StrategySnapshot,
    TaskEvent,
    TaskStep,
)
from store_operator.models.store_knowledge import IdempotencyRecord, StoreRecordRevision

_PENDING_STEP_STATUSES = {
    TaskStepStatus.PENDING.value,
    TaskStepStatus.RUNNING.value,
    TaskStepStatus.WAITING_FOR_USER.value,
}
_BLOCKED_STEP_STATUSES = {
    TaskStepStatus.FAILED.value,
    TaskStepStatus.STALE.value,
}
_STEP_ORDER = {step.value: index for index, step in enumerate(TaskStepKey)}


def _require_store_id(context: AuthContext) -> UUID:
    if context.request_store_id is None:
        raise ApiError(400, "STORE_CONTEXT_REQUIRED", "Store context is required")
    return context.request_store_id


def _summary(
    task: MarketingTask,
    steps: list[TaskStep] | None = None,
) -> MarketingTaskSummary:
    step_rows = steps or []
    return MarketingTaskSummary(
        id=task.id,
        store_id=task.store_id,
        task_type=MarketingTaskType(task.task_type),
        lifecycle_status=MarketingTaskStatus(task.lifecycle_status),
        title=task.title,
        version=task.version,
        current_requirement_snapshot_id=task.current_requirement_snapshot_id,
        current_strategy_snapshot_id=task.current_strategy_snapshot_id,
        created_at=task.created_at,
        updated_at=task.updated_at,
        pending_steps_count=sum(
            1 for step in step_rows if step.status in _PENDING_STEP_STATUSES
        ),
        blocked_steps_count=sum(
            1
            for step in step_rows
            if step.status in _BLOCKED_STEP_STATUSES
            or step.block_code is not None
            or step.blocked_by_json
        ),
    )


def _detail(task: MarketingTask, steps: list[TaskStep]) -> MarketingTaskDetail:
    ordered_steps = sorted(
        steps, key=lambda step: _STEP_ORDER.get(step.step_key, len(_STEP_ORDER))
    )
    summary = _summary(task, ordered_steps)
    return MarketingTaskDetail(
        **summary.model_dump(),
        requirement_draft=task.requirement_draft_json,
        strategy_draft=task.strategy_draft_json,
        task_options=task.task_options_json,
        steps=[
            TaskStepRead(
                id=step.id,
                step_key=TaskStepKey(step.step_key),
                status=TaskStepStatus(step.status),
                applicability=StepApplicability(step.applicability),
                version=step.version,
                skip_reason=step.skip_reason,
                input_fingerprint=step.input_fingerprint,
                output_refs=step.output_refs_json,
                blocked_by=step.blocked_by_json,
                block_code=step.block_code,
                block_detail=step.block_detail_json,
                started_at=step.started_at,
                finished_at=step.finished_at,
            )
            for step in ordered_steps
        ],
    )


def create_marketing_task(
    db: Session,
    request: Request,
    auth: AuthenticatedSession,
    context: AuthContext,
    payload: MarketingTaskCreate,
    idempotency_key: str,
) -> MarketingTaskDetail:
    store_id = _require_store_id(context)
    idempotency_record, replay = begin_idempotency(
        db,
        store_id=store_id,
        actor_user_id=auth.user.id,
        key=idempotency_key,
        operation="marketing_task.create",
        payload=payload,
    )
    if replay is not None:
        return MarketingTaskDetail.model_validate(replay)

    now = datetime.now(UTC)
    task_options = payload.task_options.model_dump(mode="json")
    task = MarketingTask(
        id=uuid4(),
        store_id=store_id,
        task_type=payload.task_type.value,
        lifecycle_status=MarketingTaskStatus.DRAFT.value,
        title=payload.title.strip(),
        version=1,
        requirement_draft_json=payload.requirement_draft,
        strategy_draft_json={},
        task_options_json=task_options,
        created_by_user_id=auth.user.id,
    )
    db.add(task)
    db.flush()

    steps: list[TaskStep] = []
    for step_key in TaskStepKey:
        applicability = resolve_step_applicability(
            payload.task_type,
            step_key,
            includes_copy=payload.task_options.includes_copy,
            includes_image=payload.task_options.includes_image,
            opportunity_applicable=payload.task_options.opportunity_applicable,
            selected_channels=bool(payload.task_options.selected_channel_keys),
            requires_external_delivery=payload.task_options.requires_external_delivery,
        )
        not_applicable = applicability is StepApplicability.NOT_APPLICABLE
        step = TaskStep(
            id=uuid4(),
            store_id=store_id,
            task_id=task.id,
            step_key=step_key.value,
            status=(
                TaskStepStatus.SKIPPED.value
                if not_applicable
                else TaskStepStatus.PENDING.value
            ),
            applicability=applicability.value,
            version=1,
            output_refs_json=[],
            blocked_by_json=[],
            skip_reason=(
                f"Not applicable to {payload.task_type.value} task scope"
                if not_applicable
                else None
            ),
            skipped_at=now if not_applicable else None,
        )
        db.add(step)
        steps.append(step)

    db.add(
        TaskEvent(
            id=uuid4(),
            store_id=store_id,
            task_id=task.id,
            event_type="task.created",
            aggregate_version=1,
            actor_type="user",
            actor_user_id=auth.user.id,
            correlation_id=context.request_id,
            payload_json={
                "task_type": payload.task_type.value,
                "title": payload.title.strip(),
                "step_count": len(steps),
            },
        )
    )
    record_audit(
        db,
        request,
        action="marketing_task.created",
        target_type="marketing_task",
        target_id=task.id,
        actor_user_id=auth.user.id,
        store_id=store_id,
        metadata={"task_type": payload.task_type.value},
    )
    db.flush()
    db.refresh(task)
    result = _detail(task, steps)
    complete_idempotency(
        idempotency_record,
        response=result.model_dump(mode="json"),
        resource_type="marketing_task",
        resource_id=task.id,
    )
    db.commit()
    return result


def list_marketing_tasks(
    db: Session,
    context: AuthContext,
    *,
    lifecycle_status: MarketingTaskStatus | None = None,
    task_type: MarketingTaskType | None = None,
    limit: int = 50,
    offset: int = 0,
) -> MarketingTaskList:
    store_id = _require_store_id(context)
    filters = [MarketingTask.store_id == store_id]
    if lifecycle_status is not None:
        filters.append(MarketingTask.lifecycle_status == lifecycle_status.value)
    if task_type is not None:
        filters.append(MarketingTask.task_type == task_type.value)

    total = db.scalar(
        select(func.count()).select_from(MarketingTask).where(*filters)
    ) or 0
    tasks = db.scalars(
        select(MarketingTask)
        .where(*filters)
        .order_by(MarketingTask.created_at.desc(), MarketingTask.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    task_ids = [task.id for task in tasks]
    steps_by_task: dict[UUID, list[TaskStep]] = defaultdict(list)
    if task_ids:
        step_rows = db.scalars(
            select(TaskStep)
            .where(TaskStep.store_id == store_id, TaskStep.task_id.in_(task_ids))
        ).all()
        for step in step_rows:
            steps_by_task[step.task_id].append(step)

    return MarketingTaskList(
        items=[_summary(task, steps_by_task[task.id]) for task in tasks],
        total=total,
    )


def get_marketing_task(
    db: Session,
    context: AuthContext,
    task_id: UUID,
) -> MarketingTaskDetail:
    store_id = _require_store_id(context)
    task = db.scalar(
        select(MarketingTask).where(
            MarketingTask.id == task_id,
            MarketingTask.store_id == store_id,
        )
    )
    if task is None:
        raise ApiError(404, "MARKETING_TASK_NOT_FOUND", "Marketing task not found")
    steps = db.scalars(
        select(TaskStep).where(
            TaskStep.store_id == store_id,
            TaskStep.task_id == task.id,
        )
    ).all()
    return _detail(task, list(steps))


def _task_for_update(db: Session, store_id: UUID, task_id: UUID) -> MarketingTask:
    task = db.scalar(
        select(MarketingTask)
        .where(MarketingTask.id == task_id, MarketingTask.store_id == store_id)
        .with_for_update()
    )
    if task is None:
        raise ApiError(404, "MARKETING_TASK_NOT_FOUND", "Marketing task not found")
    return task


def _task_steps_for_update(
    db: Session, store_id: UUID, task_id: UUID
) -> list[TaskStep]:
    return list(
        db.scalars(
            select(TaskStep)
            .where(TaskStep.store_id == store_id, TaskStep.task_id == task_id)
            .with_for_update()
        ).all()
    )


def _check_expected_version(task: MarketingTask, expected_version: int) -> None:
    if task.version != expected_version:
        raise ApiError(
            409,
            "MARKETING_TASK_VERSION_CONFLICT",
            "Marketing task has changed; reload and retry with the current version",
        )


def _fingerprint(value: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _ensure_task_transition(
    current: MarketingTaskStatus,
    target: MarketingTaskStatus,
) -> None:
    try:
        ensure_task_transition(current, target)
    except InvalidMarketingTaskTransition as exc:
        raise ApiError(409, "INVALID_TASK_TRANSITION", str(exc)) from exc


def _ensure_step_transition(
    current: TaskStepStatus,
    target: TaskStepStatus,
    *,
    applicability: StepApplicability,
    skip_reason: str | None = None,
    allow_explicit_skip: bool = False,
    approval_required: bool = False,
) -> None:
    try:
        ensure_step_transition(
            current,
            target,
            applicability=applicability,
            skip_reason=skip_reason,
            allow_explicit_skip=allow_explicit_skip,
            approval_required=approval_required,
        )
    except InvalidTaskStepTransition as exc:
        raise ApiError(409, "INVALID_TASK_STEP_TRANSITION", str(exc)) from exc


def _finish_task_write(
    db: Session,
    request: Request,
    auth: AuthenticatedSession,
    context: AuthContext,
    task: MarketingTask,
    idempotency_record: IdempotencyRecord | None,
    *,
    event_type: str,
    event_payload: dict[str, object],
    audit_action: str,
    audit_metadata: dict[str, object],
) -> MarketingTaskDetail:
    db.add(
        TaskEvent(
            id=uuid4(),
            store_id=task.store_id,
            task_id=task.id,
            event_type=event_type,
            aggregate_version=task.version,
            actor_type="user",
            actor_user_id=auth.user.id,
            correlation_id=context.request_id,
            payload_json=event_payload,
        )
    )
    record_audit(
        db,
        request,
        action=audit_action,
        target_type="marketing_task",
        target_id=task.id,
        actor_user_id=auth.user.id,
        store_id=task.store_id,
        metadata=audit_metadata,
    )
    db.flush()
    db.refresh(task)
    steps = _task_steps_for_update(db, task.store_id, task.id)
    result = _detail(task, steps)
    complete_idempotency(
        idempotency_record,
        response=result.model_dump(mode="json"),
        resource_type="marketing_task",
        resource_id=task.id,
        response_status=200,
    )
    db.commit()
    return result


def update_requirement_draft(
    db: Session,
    request: Request,
    auth: AuthenticatedSession,
    context: AuthContext,
    task_id: UUID,
    payload: MarketingTaskRequirementUpdate,
    idempotency_key: str,
) -> MarketingTaskDetail:
    store_id = _require_store_id(context)
    idempotency_record, replay = begin_idempotency(
        db,
        store_id=store_id,
        actor_user_id=auth.user.id,
        key=idempotency_key,
        operation="marketing_task.requirement.update",
        payload=payload,
    )
    if replay is not None:
        return MarketingTaskDetail.model_validate(replay)

    task = _task_for_update(db, store_id, task_id)
    _check_expected_version(task, payload.expected_version)
    if (
        task.lifecycle_status != MarketingTaskStatus.DRAFT.value
        or task.current_requirement_snapshot_id is not None
    ):
        raise ApiError(
            409,
            "REQUIREMENT_ALREADY_CONFIRMED",
            "Requirement draft cannot be changed after confirmation",
        )

    options = payload.task_options or MarketingTaskOptions.model_validate(
        task.task_options_json
    )
    validated = MarketingTaskCreate(
        task_type=MarketingTaskType(task.task_type),
        title=task.title,
        requirement_draft=payload.requirement_draft,
        task_options=options,
    )
    options_json = options.model_dump(mode="json")
    now = datetime.now(UTC)
    steps = _task_steps_for_update(db, store_id, task.id)
    for step in steps:
        old_applicability = StepApplicability(step.applicability)
        new_applicability = resolve_step_applicability(
            validated.task_type,
            TaskStepKey(step.step_key),
            includes_copy=options.includes_copy,
            includes_image=options.includes_image,
            opportunity_applicable=options.opportunity_applicable,
            selected_channels=bool(options.selected_channel_keys),
            requires_external_delivery=options.requires_external_delivery,
        )
        if new_applicability is old_applicability:
            continue
        current_status = TaskStepStatus(step.status)
        if current_status not in {
            TaskStepStatus.PENDING,
            TaskStepStatus.SKIPPED,
        }:
            raise ApiError(
                409,
                "TASK_STEP_ALREADY_STARTED",
                "Task step applicability cannot change after execution starts",
            )

        if new_applicability is StepApplicability.NOT_APPLICABLE:
            reason = f"Not applicable to {validated.task_type.value} task scope"
            if current_status is TaskStepStatus.PENDING:
                _ensure_step_transition(
                    current_status,
                    TaskStepStatus.SKIPPED,
                    applicability=new_applicability,
                    skip_reason=reason,
                )
            step.status = TaskStepStatus.SKIPPED.value
            step.skip_reason = reason
            step.skipped_at = now
            step.skipped_by_user_id = None
        elif current_status is TaskStepStatus.SKIPPED:
            _ensure_step_transition(
                current_status,
                TaskStepStatus.STALE,
                applicability=old_applicability,
            )
            _ensure_step_transition(
                TaskStepStatus.STALE,
                TaskStepStatus.PENDING,
                applicability=new_applicability,
            )
            step.status = TaskStepStatus.PENDING.value
            step.skip_reason = None
            step.skipped_at = None
            step.skipped_by_user_id = None
        step.applicability = new_applicability.value
        step.version += 1
        step.input_fingerprint = None
        step.output_refs_json = []
        step.blocked_by_json = []
        step.block_code = None
        step.block_detail_json = None

    task.requirement_draft_json = validated.requirement_draft
    task.task_options_json = options_json
    task.version += 1
    return _finish_task_write(
        db,
        request,
        auth,
        context,
        task,
        idempotency_record,
        event_type="requirement.draft_updated",
        event_payload={
            "expected_version": payload.expected_version,
            "new_version": task.version,
        },
        audit_action="marketing_task.requirement.draft_updated",
        audit_metadata={"task_type": task.task_type},
    )


def confirm_requirement(
    db: Session,
    request: Request,
    auth: AuthenticatedSession,
    context: AuthContext,
    task_id: UUID,
    payload: MarketingTaskRequirementConfirm,
    idempotency_key: str,
) -> MarketingTaskDetail:
    store_id = _require_store_id(context)
    idempotency_record, replay = begin_idempotency(
        db,
        store_id=store_id,
        actor_user_id=auth.user.id,
        key=idempotency_key,
        operation="marketing_task.requirement.confirm",
        payload=payload,
    )
    if replay is not None:
        return MarketingTaskDetail.model_validate(replay)

    task = _task_for_update(db, store_id, task_id)
    _check_expected_version(task, payload.expected_version)
    if task.lifecycle_status != MarketingTaskStatus.DRAFT.value:
        raise ApiError(409, "TASK_NOT_DRAFT", "Only draft tasks can confirm requirements")
    if task.current_requirement_snapshot_id is not None:
        raise ApiError(
            409,
            "REQUIREMENT_ALREADY_CONFIRMED",
            "Requirement snapshot already exists",
        )
    if not task.requirement_draft_json:
        raise ApiError(
            422, "REQUIREMENT_DRAFT_EMPTY", "Requirement draft must not be empty"
        )

    now = datetime.now(UTC)
    fact_snapshots: list[BusinessFactSnapshot] = []
    fact_revisions: list[StoreRecordRevision] = []
    fact_refs: list[dict[str, object]] = []
    for fact_ref in payload.business_facts:
        revision = db.scalar(
            select(StoreRecordRevision)
            .where(
                StoreRecordRevision.store_id == store_id,
                StoreRecordRevision.record_type == fact_ref.record_type,
                StoreRecordRevision.record_id == fact_ref.record_id,
            )
            .order_by(StoreRecordRevision.version_no.desc())
            .limit(1)
            .with_for_update()
        )
        if revision is None:
            raise ApiError(
                404,
                "BUSINESS_FACT_NOT_FOUND",
                f"Business fact {fact_ref.fact_key} was not found in this store",
            )
        if (
            fact_ref.expected_version_no is not None
            and fact_ref.expected_version_no != revision.version_no
        ):
            raise ApiError(
                409,
                "BUSINESS_FACT_VERSION_CONFLICT",
                f"Business fact {fact_ref.fact_key} has a newer version",
            )
        if revision.fact_status != "confirmed":
            raise ApiError(
                409,
                "BUSINESS_FACT_NOT_CONFIRMED",
                f"Business fact {fact_ref.fact_key} must be confirmed before task use",
            )
        if revision.valid_from is not None and revision.valid_from > now:
            raise ApiError(
                409,
                "BUSINESS_FACT_NOT_YET_VALID",
                f"Business fact {fact_ref.fact_key} is not yet valid",
            )
        if revision.valid_until is not None and revision.valid_until <= now:
            raise ApiError(
                409,
                "BUSINESS_FACT_EXPIRED",
                f"Business fact {fact_ref.fact_key} has expired",
            )

        fact_version = (
            db.scalar(
                select(func.max(BusinessFactSnapshot.version_no)).where(
                    BusinessFactSnapshot.store_id == store_id,
                    BusinessFactSnapshot.task_id == task.id,
                    BusinessFactSnapshot.fact_key == fact_ref.fact_key,
                )
            )
            or 0
        ) + 1
        snapshot = BusinessFactSnapshot(
            id=uuid4(),
            store_id=store_id,
            task_id=task.id,
            fact_key=fact_ref.fact_key,
            source_type=fact_ref.record_type,
            source_id=fact_ref.record_id,
            source_version=revision.version_no,
            version_no=fact_version,
            value_json=revision.snapshot_json,
            schema_version=revision.schema_version,
            content_fingerprint=revision.content_fingerprint,
            confirmation_status="confirmed",
            created_by_user_id=auth.user.id,
            confirmed_by_user_id=auth.user.id,
            confirmed_at=now,
        )
        db.add(snapshot)
        fact_snapshots.append(snapshot)
        fact_revisions.append(revision)
        fact_refs.append(
            {
                "fact_key": fact_ref.fact_key,
                "record_type": fact_ref.record_type,
                "record_id": str(fact_ref.record_id),
                "source_version": revision.version_no,
                "content_fingerprint": revision.content_fingerprint,
                "business_fact_snapshot_id": str(snapshot.id),
            }
        )

    requirement_payload: dict[str, object] = {
        "schema_version": 1,
        "requirement": task.requirement_draft_json,
        "business_facts": fact_refs,
    }
    requirement_fingerprint = _fingerprint(requirement_payload)
    snapshot_no = (
        db.scalar(
            select(func.max(RequirementSnapshot.snapshot_no)).where(
                RequirementSnapshot.store_id == store_id,
                RequirementSnapshot.task_id == task.id,
            )
        )
        or 0
    ) + 1
    requirement_snapshot = RequirementSnapshot(
        id=uuid4(),
        store_id=store_id,
        task_id=task.id,
        snapshot_no=snapshot_no,
        payload_json=requirement_payload,
        schema_version=1,
        content_fingerprint=requirement_fingerprint,
        created_by_user_id=auth.user.id,
        confirmed_by_user_id=auth.user.id,
        confirmed_at=now,
    )
    db.add(requirement_snapshot)
    for revision, fact_snapshot in zip(fact_revisions, fact_snapshots, strict=True):
        db.add(
            DependencyEdge(
                id=uuid4(),
                store_id=store_id,
                task_id=task.id,
                upstream_type="store_record_revision",
                upstream_id=revision.id,
                upstream_version_id=revision.id,
                upstream_fingerprint=revision.content_fingerprint,
                downstream_type="business_fact_snapshot",
                downstream_id=fact_snapshot.id,
                downstream_version_id=fact_snapshot.id,
                downstream_fingerprint=fact_snapshot.content_fingerprint,
                impact_policy="invalidate",
            )
        )
        db.add(
            DependencyEdge(
                id=uuid4(),
                store_id=store_id,
                task_id=task.id,
                upstream_type="business_fact_snapshot",
                upstream_id=fact_snapshot.id,
                upstream_version_id=fact_snapshot.id,
                upstream_fingerprint=fact_snapshot.content_fingerprint,
                downstream_type="requirement_snapshot",
                downstream_id=requirement_snapshot.id,
                downstream_version_id=requirement_snapshot.id,
                downstream_fingerprint=requirement_fingerprint,
                impact_policy="invalidate",
            )
        )

    steps = {step.step_key: step for step in _task_steps_for_update(db, store_id, task.id)}
    for step_key, output_refs in (
        (
            TaskStepKey.REQUIREMENT_UNDERSTANDING,
            [{"type": "requirement_snapshot", "id": str(requirement_snapshot.id)}],
        ),
        (
            TaskStepKey.CONTEXT_SNAPSHOT,
            [
                {
                    "type": "business_fact_snapshot",
                    "id": str(snapshot.id),
                    "fact_key": snapshot.fact_key,
                }
                for snapshot in fact_snapshots
            ],
        ),
    ):
        step = steps[step_key.value]
        if TaskStepStatus(step.status) is not TaskStepStatus.PENDING:
            raise ApiError(
                409,
                "REQUIREMENT_STEP_NOT_PENDING",
                f"Step {step_key.value} is not pending",
            )
        applicability = StepApplicability(step.applicability)
        _ensure_step_transition(
            TaskStepStatus.PENDING,
            TaskStepStatus.RUNNING,
            applicability=applicability,
        )
        _ensure_step_transition(
            TaskStepStatus.RUNNING,
            TaskStepStatus.SUCCEEDED,
            applicability=applicability,
        )
        step.status = TaskStepStatus.SUCCEEDED.value
        step.version += 1
        step.started_at = now
        step.finished_at = now
        step.input_fingerprint = requirement_fingerprint
        step.output_refs_json = output_refs
        step.blocked_by_json = []
        step.skip_reason = None

    _ensure_task_transition(
        MarketingTaskStatus.DRAFT, MarketingTaskStatus.ACTIVE
    )
    strategy_step = steps[TaskStepKey.STRATEGY_CONFIRMATION.value]
    if TaskStepStatus(strategy_step.status) is not TaskStepStatus.PENDING:
        raise ApiError(
            409,
            "STRATEGY_STEP_NOT_PENDING",
            "Strategy generation step is not pending",
        )
    strategy_applicability = StepApplicability(strategy_step.applicability)
    _ensure_step_transition(
        TaskStepStatus.PENDING,
        TaskStepStatus.RUNNING,
        applicability=strategy_applicability,
    )
    strategy_step.status = TaskStepStatus.RUNNING.value
    strategy_step.version += 1
    strategy_step.started_at = now
    strategy_step.finished_at = None
    strategy_step.input_fingerprint = requirement_fingerprint
    strategy_step.output_refs_json = []
    strategy_step.blocked_by_json = []
    strategy_step.block_code = None
    strategy_step.block_detail_json = None
    strategy_step.skip_reason = None

    task.current_requirement_snapshot_id = requirement_snapshot.id
    task.lifecycle_status = MarketingTaskStatus.ACTIVE.value
    task.activated_at = now
    task.version += 1
    try:
        strategy_job = create_job(
            db,
            job_type="marketing_task.generate_strategy",
            payload_ref={
                "schema_version": 1,
                "marketing_task_id": str(task.id),
                "requirement_snapshot_id": str(requirement_snapshot.id),
                "requirement_fingerprint": requirement_fingerprint,
            },
            idempotency_key=(
                f"marketing-task:{task.id}:strategy:{requirement_snapshot.id}"
            ),
            store_id=store_id,
            actor_type="user",
            actor_user_id=auth.user.id,
            marketing_task_id=task.id,
            max_attempts=3,
            timeout_seconds=600,
        )
    except JobIdempotencyConflict as exc:
        raise ApiError(
            409,
            "STRATEGY_JOB_IDEMPOTENCY_CONFLICT",
            "A conflicting strategy generation job already exists",
        ) from exc
    return _finish_task_write(
        db,
        request,
        auth,
        context,
        task,
        idempotency_record,
        event_type="requirement.confirmed",
        event_payload={
            "requirement_snapshot_id": str(requirement_snapshot.id),
            "business_fact_snapshot_ids": [str(item.id) for item in fact_snapshots],
            "strategy_job_id": str(strategy_job.id),
            "snapshot_no": snapshot_no,
        },
        audit_action="marketing_task.requirement.confirmed",
        audit_metadata={
            "requirement_snapshot_id": str(requirement_snapshot.id),
            "business_fact_count": len(fact_snapshots),
            "strategy_job_id": str(strategy_job.id),
        },
    )


def update_strategy_draft(
    db: Session,
    request: Request,
    auth: AuthenticatedSession,
    context: AuthContext,
    task_id: UUID,
    payload: MarketingTaskStrategyUpdate,
    idempotency_key: str,
) -> MarketingTaskDetail:
    store_id = _require_store_id(context)
    idempotency_record, replay = begin_idempotency(
        db,
        store_id=store_id,
        actor_user_id=auth.user.id,
        key=idempotency_key,
        operation="marketing_task.strategy.update",
        payload=payload,
    )
    if replay is not None:
        return MarketingTaskDetail.model_validate(replay)

    task = _task_for_update(db, store_id, task_id)
    _check_expected_version(task, payload.expected_version)
    if task.lifecycle_status != MarketingTaskStatus.WAITING_FOR_USER.value:
        raise ApiError(
            409,
            "STRATEGY_NOT_AWAITING_REVIEW",
            "Strategy can only be edited while awaiting user review",
        )
    steps = _task_steps_for_update(db, store_id, task.id)
    strategy_step = next(
        (item for item in steps if item.step_key == TaskStepKey.STRATEGY_CONFIRMATION.value),
        None,
    )
    if (
        strategy_step is None
        or TaskStepStatus(strategy_step.status) is not TaskStepStatus.WAITING_FOR_USER
    ):
        raise ApiError(
            409,
            "STRATEGY_STEP_NOT_AWAITING_REVIEW",
            "Strategy generation has not produced a reviewable draft",
        )

    task.strategy_draft_json = payload.strategy
    task.version += 1
    return _finish_task_write(
        db,
        request,
        auth,
        context,
        task,
        idempotency_record,
        event_type="strategy.draft_updated",
        event_payload={"strategy_fingerprint": _fingerprint(payload.strategy)},
        audit_action="marketing_task.strategy.draft_updated",
        audit_metadata={"strategy_fingerprint": _fingerprint(payload.strategy)},
    )


def confirm_strategy(
    db: Session,
    request: Request,
    auth: AuthenticatedSession,
    context: AuthContext,
    task_id: UUID,
    payload: MarketingTaskStrategyConfirm,
    idempotency_key: str,
) -> MarketingTaskDetail:
    store_id = _require_store_id(context)
    idempotency_record, replay = begin_idempotency(
        db,
        store_id=store_id,
        actor_user_id=auth.user.id,
        key=idempotency_key,
        operation="marketing_task.strategy.confirm",
        payload=payload,
    )
    if replay is not None:
        return MarketingTaskDetail.model_validate(replay)

    task = _task_for_update(db, store_id, task_id)
    _check_expected_version(task, payload.expected_version)
    if task.lifecycle_status != MarketingTaskStatus.WAITING_FOR_USER.value:
        raise ApiError(
            409,
            "STRATEGY_NOT_AWAITING_REVIEW",
            "Strategy can only be confirmed while awaiting user review",
        )
    if task.current_requirement_snapshot_id is None:
        raise ApiError(
            409,
            "REQUIREMENT_NOT_CONFIRMED",
            "Requirement must be confirmed before strategy",
        )
    if task.current_strategy_snapshot_id is not None:
        raise ApiError(
            409,
            "STRATEGY_ALREADY_CONFIRMED",
            "Strategy snapshot already exists",
        )
    if not task.strategy_draft_json:
        raise ApiError(
            409,
            "STRATEGY_DRAFT_NOT_READY",
            "A generated strategy draft is required before confirmation",
        )

    now = datetime.now(UTC)
    requirement_snapshot = db.scalar(
        select(RequirementSnapshot).where(
            RequirementSnapshot.id == task.current_requirement_snapshot_id,
            RequirementSnapshot.store_id == store_id,
            RequirementSnapshot.task_id == task.id,
        )
    )
    if requirement_snapshot is None:
        raise ApiError(
            409,
            "REQUIREMENT_SNAPSHOT_NOT_FOUND",
            "Current requirement snapshot is unavailable",
        )
    strategy_payload: dict[str, object] = {
        "schema_version": 1,
        "strategy": task.strategy_draft_json,
        "requirement_snapshot_id": str(requirement_snapshot.id),
    }
    fingerprint = _fingerprint(strategy_payload)
    snapshot_no = (
        db.scalar(
            select(func.max(StrategySnapshot.snapshot_no)).where(
                StrategySnapshot.store_id == store_id,
                StrategySnapshot.task_id == task.id,
            )
        )
        or 0
    ) + 1
    strategy_snapshot = StrategySnapshot(
        id=uuid4(),
        store_id=store_id,
        task_id=task.id,
        requirement_snapshot_id=requirement_snapshot.id,
        snapshot_no=snapshot_no,
        payload_json=strategy_payload,
        schema_version=1,
        content_fingerprint=fingerprint,
        created_by_user_id=auth.user.id,
        confirmed_by_user_id=auth.user.id,
        confirmed_at=now,
    )
    db.add(strategy_snapshot)
    db.add(
        DependencyEdge(
            id=uuid4(),
            store_id=store_id,
            task_id=task.id,
            upstream_type="requirement_snapshot",
            upstream_id=requirement_snapshot.id,
            upstream_version_id=requirement_snapshot.id,
            upstream_fingerprint=requirement_snapshot.content_fingerprint,
            downstream_type="strategy_snapshot",
            downstream_id=strategy_snapshot.id,
            downstream_version_id=strategy_snapshot.id,
            downstream_fingerprint=strategy_snapshot.content_fingerprint,
            impact_policy="invalidate",
        )
    )

    steps = _task_steps_for_update(db, store_id, task.id)
    strategy_step = next(
        (item for item in steps if item.step_key == TaskStepKey.STRATEGY_CONFIRMATION.value),
        None,
    )
    if (
        strategy_step is None
        or TaskStepStatus(strategy_step.status) is not TaskStepStatus.WAITING_FOR_USER
    ):
        raise ApiError(
            409,
            "STRATEGY_STEP_NOT_AWAITING_REVIEW",
            "Strategy confirmation step is not awaiting review",
        )
    strategy_applicability = StepApplicability(strategy_step.applicability)
    _ensure_step_transition(
        TaskStepStatus.WAITING_FOR_USER,
        TaskStepStatus.RUNNING,
        applicability=strategy_applicability,
    )
    _ensure_step_transition(
        TaskStepStatus.RUNNING,
        TaskStepStatus.SUCCEEDED,
        applicability=strategy_applicability,
    )
    strategy_step.status = TaskStepStatus.SUCCEEDED.value
    strategy_step.version += 1
    strategy_step.started_at = strategy_step.started_at or now
    strategy_step.finished_at = now
    strategy_step.input_fingerprint = fingerprint
    strategy_step.output_refs_json = [
        {"type": "strategy_snapshot", "id": str(strategy_snapshot.id)}
    ]
    strategy_step.blocked_by_json = []
    strategy_step.block_code = None
    strategy_step.block_detail_json = None
    strategy_step.skip_reason = None

    content_job_ids: list[str] = []
    for step_key, job_type in (
        (TaskStepKey.COPY_PRODUCTION_REVIEW, "marketing_task.generate_copy"),
        (TaskStepKey.IMAGE_PRODUCTION_REVIEW, "marketing_task.generate_image"),
    ):
        content_step = next(
            (item for item in steps if item.step_key == step_key.value),
            None,
        )
        if content_step is None:
            continue
        applicability = StepApplicability(content_step.applicability)
        if applicability is StepApplicability.NOT_APPLICABLE:
            continue
        if TaskStepStatus(content_step.status) is not TaskStepStatus.PENDING:
            raise ApiError(
                409,
                "CONTENT_STEP_NOT_PENDING",
                f"Content step {step_key.value} is not pending",
            )
        _ensure_step_transition(
            TaskStepStatus.PENDING,
            TaskStepStatus.RUNNING,
            applicability=applicability,
        )
        content_step.status = TaskStepStatus.RUNNING.value
        content_step.version += 1
        content_step.started_at = now
        content_step.finished_at = None
        content_step.input_fingerprint = fingerprint
        content_step.output_refs_json = []
        content_step.blocked_by_json = []
        content_step.block_code = None
        content_step.block_detail_json = None
        content_step.skip_reason = None
        try:
            content_job = create_job(
                db,
                job_type=job_type,
                payload_ref={
                    "schema_version": 1,
                    "marketing_task_id": str(task.id),
                    "requirement_snapshot_id": str(requirement_snapshot.id),
                    "strategy_snapshot_id": str(strategy_snapshot.id),
                    "step_key": step_key.value,
                    "strategy_fingerprint": fingerprint,
                },
                idempotency_key=(
                    f"marketing-task:{task.id}:strategy:{strategy_snapshot.id}:"
                    f"{step_key.value}"
                ),
                store_id=store_id,
                actor_type="user",
                actor_user_id=auth.user.id,
                marketing_task_id=task.id,
                max_attempts=3,
                timeout_seconds=900,
            )
        except JobIdempotencyConflict as exc:
            raise ApiError(
                409,
                "CONTENT_JOB_IDEMPOTENCY_CONFLICT",
                f"A conflicting {step_key.value} job already exists",
            ) from exc
        content_job_ids.append(str(content_job.id))

    _ensure_task_transition(
        MarketingTaskStatus.WAITING_FOR_USER, MarketingTaskStatus.ACTIVE
    )
    task.current_strategy_snapshot_id = strategy_snapshot.id
    task.lifecycle_status = MarketingTaskStatus.ACTIVE.value
    task.version += 1
    return _finish_task_write(
        db,
        request,
        auth,
        context,
        task,
        idempotency_record,
        event_type="strategy.confirmed",
        event_payload={
            "strategy_snapshot_id": str(strategy_snapshot.id),
            "requirement_snapshot_id": str(requirement_snapshot.id),
            "content_job_ids": content_job_ids,
            "snapshot_no": snapshot_no,
        },
        audit_action="marketing_task.strategy.confirmed",
        audit_metadata={
            "strategy_snapshot_id": str(strategy_snapshot.id),
            "content_job_ids": content_job_ids,
        },
    )


_APPROVAL_STEP_KEYS = {
    TaskStepKey.STRATEGY_CONFIRMATION,
    TaskStepKey.COPY_PRODUCTION_REVIEW,
    TaskStepKey.IMAGE_PRODUCTION_REVIEW,
    TaskStepKey.FINAL_CONFIRMATION,
}


def skip_task_step(
    db: Session,
    request: Request,
    auth: AuthenticatedSession,
    context: AuthContext,
    task_id: UUID,
    step_key: TaskStepKey,
    payload: MarketingTaskStepSkip,
    idempotency_key: str,
) -> MarketingTaskDetail:
    store_id = _require_store_id(context)
    idempotency_record, replay = begin_idempotency(
        db,
        store_id=store_id,
        actor_user_id=auth.user.id,
        key=idempotency_key,
        operation="marketing_task.step.skip",
        payload=payload,
    )
    if replay is not None:
        return MarketingTaskDetail.model_validate(replay)

    task = _task_for_update(db, store_id, task_id)
    _check_expected_version(task, payload.expected_version)
    if task.lifecycle_status not in {
        MarketingTaskStatus.ACTIVE.value,
        MarketingTaskStatus.WAITING_FOR_USER.value,
    }:
        raise ApiError(
            409,
            "TASK_NOT_ACTIONABLE",
            "Only active or waiting tasks accept step decisions",
        )

    steps = _task_steps_for_update(db, store_id, task.id)
    step = next((item for item in steps if item.step_key == step_key.value), None)
    if step is None:
        raise ApiError(404, "TASK_STEP_NOT_FOUND", "Task step not found")
    applicability = StepApplicability(step.applicability)
    _ensure_step_transition(
        TaskStepStatus(step.status),
        TaskStepStatus.SKIPPED,
        applicability=applicability,
        skip_reason=payload.reason,
        allow_explicit_skip=True,
        approval_required=step_key in _APPROVAL_STEP_KEYS,
    )

    now = datetime.now(UTC)
    step.status = TaskStepStatus.SKIPPED.value
    step.skip_reason = payload.reason
    step.skipped_by_user_id = auth.user.id
    step.skipped_at = now
    step.finished_at = now
    step.version += 1
    decision = StepDecision(
        id=uuid4(),
        store_id=store_id,
        task_id=task.id,
        task_step_id=step.id,
        decision="skip",
        reason=payload.reason,
        actor_type="user",
        actor_user_id=auth.user.id,
        evidence_json={
            "step_key": step_key.value,
            "applicability": applicability.value,
        },
        idempotency_record_id=idempotency_record.id if idempotency_record else None,
    )
    db.add(decision)
    task.version += 1
    return _finish_task_write(
        db,
        request,
        auth,
        context,
        task,
        idempotency_record,
        event_type="task_step.skipped",
        event_payload={
            "step_key": step_key.value,
            "decision_id": str(decision.id),
            "reason": payload.reason,
        },
        audit_action="marketing_task.step.skipped",
        audit_metadata={
            "step_key": step_key.value,
            "decision_id": str(decision.id),
        },
    )


def recover_marketing_task(
    db: Session,
    request: Request,
    auth: AuthenticatedSession,
    context: AuthContext,
    task_id: UUID,
    payload: MarketingTaskRecover,
    idempotency_key: str,
) -> MarketingTaskDetail:
    store_id = _require_store_id(context)
    idempotency_record, replay = begin_idempotency(
        db,
        store_id=store_id,
        actor_user_id=auth.user.id,
        key=idempotency_key,
        operation="marketing_task.recover",
        payload=payload,
    )
    if replay is not None:
        return MarketingTaskDetail.model_validate(replay)

    task = _task_for_update(db, store_id, task_id)
    _check_expected_version(task, payload.expected_version)
    current_task_status = MarketingTaskStatus(task.lifecycle_status)
    if current_task_status not in {
        MarketingTaskStatus.ACTIVE,
        MarketingTaskStatus.WAITING_FOR_USER,
        MarketingTaskStatus.BLOCKED,
        MarketingTaskStatus.FAILED,
    }:
        raise ApiError(
            409,
            "TASK_NOT_RECOVERABLE",
            "Task must be active, waiting, blocked or failed to recover a step",
        )

    steps = _task_steps_for_update(db, store_id, task.id)
    step = next(
        (item for item in steps if item.step_key == payload.step_key.value),
        None,
    )
    if step is None:
        raise ApiError(404, "TASK_STEP_NOT_FOUND", "Task step not found")
    applicability = StepApplicability(step.applicability)
    if applicability is StepApplicability.NOT_APPLICABLE:
        raise ApiError(
            409,
            "TASK_STEP_NOT_APPLICABLE",
            "A not-applicable task step cannot be recovered",
        )

    current_step_status = TaskStepStatus(step.status)
    if current_step_status in {
        TaskStepStatus.FAILED,
        TaskStepStatus.WAITING_FOR_USER,
    }:
        target_step_status = TaskStepStatus.RUNNING
    elif current_step_status is TaskStepStatus.STALE:
        target_step_status = TaskStepStatus.PENDING
    else:
        raise ApiError(
            409,
            "TASK_STEP_NOT_RECOVERABLE",
            "Only failed, stale or waiting task steps can be recovered",
        )
    _ensure_step_transition(
        current_step_status,
        target_step_status,
        applicability=applicability,
    )
    if current_task_status is not MarketingTaskStatus.ACTIVE:
        _ensure_task_transition(current_task_status, MarketingTaskStatus.ACTIVE)

    now = datetime.now(UTC)
    step.status = target_step_status.value
    step.version += 1
    step.started_at = now if target_step_status is TaskStepStatus.RUNNING else None
    step.finished_at = None
    step.skip_reason = None
    step.skipped_at = None
    step.skipped_by_user_id = None
    step.input_fingerprint = None
    step.output_refs_json = []
    step.blocked_by_json = []
    step.block_code = None
    step.block_detail_json = None

    decision = StepDecision(
        id=uuid4(),
        store_id=store_id,
        task_id=task.id,
        task_step_id=step.id,
        decision="retry",
        reason=payload.reason,
        actor_type="user",
        actor_user_id=auth.user.id,
        evidence_json={
            "step_key": payload.step_key.value,
            "from_status": current_step_status.value,
            "to_status": target_step_status.value,
        },
        idempotency_record_id=idempotency_record.id if idempotency_record else None,
    )
    db.add(decision)
    if current_task_status is not MarketingTaskStatus.ACTIVE:
        task.lifecycle_status = MarketingTaskStatus.ACTIVE.value
    task.version += 1
    return _finish_task_write(
        db,
        request,
        auth,
        context,
        task,
        idempotency_record,
        event_type="task.recovered",
        event_payload={
            "step_key": payload.step_key.value,
            "decision_id": str(decision.id),
            "from_status": current_step_status.value,
            "to_status": target_step_status.value,
        },
        audit_action="marketing_task.recovered",
        audit_metadata={
            "step_key": payload.step_key.value,
            "decision_id": str(decision.id),
        },
    )


def cancel_marketing_task(
    db: Session,
    request: Request,
    auth: AuthenticatedSession,
    context: AuthContext,
    task_id: UUID,
    payload: MarketingTaskAction,
    idempotency_key: str,
) -> MarketingTaskDetail:
    store_id = _require_store_id(context)
    idempotency_record, replay = begin_idempotency(
        db,
        store_id=store_id,
        actor_user_id=auth.user.id,
        key=idempotency_key,
        operation="marketing_task.cancel",
        payload=payload,
    )
    if replay is not None:
        return MarketingTaskDetail.model_validate(replay)

    task = _task_for_update(db, store_id, task_id)
    _check_expected_version(task, payload.expected_version)
    current_status = MarketingTaskStatus(task.lifecycle_status)
    _ensure_task_transition(current_status, MarketingTaskStatus.CANCELLED)
    now = datetime.now(UTC)
    active_jobs = db.scalars(
        select(Job)
        .where(
            Job.store_id == store_id,
            Job.marketing_task_id == task.id,
            Job.status.in_({"queued", "running", "retry_wait"}),
        )
        .order_by(Job.created_at, Job.id)
        .with_for_update()
    ).all()
    for job in active_jobs:
        request_job_cancellation(
            db,
            job_id=job.id,
            store_id=store_id,
            actor_user_id=auth.user.id,
            now=now,
        )
    task.lifecycle_status = MarketingTaskStatus.CANCELLED.value
    task.cancelled_at = now
    task.version += 1
    return _finish_task_write(
        db,
        request,
        auth,
        context,
        task,
        idempotency_record,
        event_type="task.cancelled",
        event_payload={"reason": payload.reason},
        audit_action="marketing_task.cancelled",
        audit_metadata={"reason": payload.reason},
    )


def archive_marketing_task(
    db: Session,
    request: Request,
    auth: AuthenticatedSession,
    context: AuthContext,
    task_id: UUID,
    payload: MarketingTaskAction,
    idempotency_key: str,
) -> MarketingTaskDetail:
    store_id = _require_store_id(context)
    idempotency_record, replay = begin_idempotency(
        db,
        store_id=store_id,
        actor_user_id=auth.user.id,
        key=idempotency_key,
        operation="marketing_task.archive",
        payload=payload,
    )
    if replay is not None:
        return MarketingTaskDetail.model_validate(replay)

    task = _task_for_update(db, store_id, task_id)
    _check_expected_version(task, payload.expected_version)
    current_status = MarketingTaskStatus(task.lifecycle_status)
    _ensure_task_transition(current_status, MarketingTaskStatus.ARCHIVED)
    task.lifecycle_status = MarketingTaskStatus.ARCHIVED.value
    task.archived_at = datetime.now(UTC)
    task.version += 1
    return _finish_task_write(
        db,
        request,
        auth,
        context,
        task,
        idempotency_record,
        event_type="task.archived",
        event_payload={"reason": payload.reason},
        audit_action="marketing_task.archived",
        audit_metadata={"reason": payload.reason},
    )
