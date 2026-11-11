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
    MarketingTaskStatus,
    MarketingTaskType,
    StepApplicability,
    TaskStepKey,
    TaskStepStatus,
    resolve_step_applicability,
)
from store_operator.idempotency import begin_idempotency, complete_idempotency
from store_operator.marketing_tasks.schemas import (
    MarketingTaskCreate,
    MarketingTaskDetail,
    MarketingTaskList,
    MarketingTaskSummary,
    TaskStepRead,
)
from store_operator.models.marketing_task import (
    MarketingTask,
    TaskEvent,
    TaskStep,
)

_PENDING_STEP_STATUSES = {
    TaskStepStatus.PENDING.value,
    TaskStepStatus.RUNNING.value,
    TaskStepStatus.WAITING_FOR_USER.value,
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
        blocked_steps_count=sum(1 for step in step_rows if step.blocked_by_json),
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
