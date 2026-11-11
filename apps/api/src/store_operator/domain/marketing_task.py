from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum


class MarketingTaskType(StrEnum):
    FULL_MARKETING = "full_marketing"
    COPY_ONLY = "copy_only"
    IMAGE_ONLY = "image_only"
    IMAGE_OPTIMIZATION = "image_optimization"
    MERCHANT_CONTENT = "merchant_content"


class MarketingTaskStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    WAITING_FOR_USER = "waiting_for_user"
    BLOCKED = "blocked"
    FAILED = "failed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ARCHIVED = "archived"


class TaskStepKey(StrEnum):
    REQUIREMENT_UNDERSTANDING = "requirement_understanding"
    CONTEXT_SNAPSHOT = "context_snapshot"
    OPPORTUNITY_DECISION = "opportunity_decision"
    STRATEGY_CONFIRMATION = "strategy_confirmation"
    COPY_PRODUCTION_REVIEW = "copy_production_review"
    IMAGE_PRODUCTION_REVIEW = "image_production_review"
    CHANNEL_ADAPTATION = "channel_adaptation"
    QUALITY_CHECK = "quality_check"
    FINAL_CONFIRMATION = "final_confirmation"
    DELIVERY = "delivery"


class TaskStepStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_FOR_USER = "waiting_for_user"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    STALE = "stale"


class StepApplicability(StrEnum):
    REQUIRED = "required"
    OPTIONAL = "optional"
    NOT_APPLICABLE = "not_applicable"


class InvalidMarketingTaskTransition(ValueError):
    pass


class InvalidTaskStepTransition(ValueError):
    pass


class TaskCompletionBlocked(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class TaskStepSnapshot:
    key: str
    status: TaskStepStatus | str
    applicability: StepApplicability | str
    skip_reason: str | None = None
    approval_required: bool = False


_TASK_TRANSITIONS: dict[MarketingTaskStatus, frozenset[MarketingTaskStatus]] = {
    MarketingTaskStatus.DRAFT: frozenset(
        {MarketingTaskStatus.ACTIVE, MarketingTaskStatus.CANCELLED}
    ),
    MarketingTaskStatus.ACTIVE: frozenset(
        {
            MarketingTaskStatus.WAITING_FOR_USER,
            MarketingTaskStatus.BLOCKED,
            MarketingTaskStatus.FAILED,
            MarketingTaskStatus.COMPLETED,
            MarketingTaskStatus.CANCELLED,
        }
    ),
    MarketingTaskStatus.WAITING_FOR_USER: frozenset(
        {
            MarketingTaskStatus.ACTIVE,
            MarketingTaskStatus.BLOCKED,
            MarketingTaskStatus.FAILED,
            MarketingTaskStatus.CANCELLED,
        }
    ),
    MarketingTaskStatus.BLOCKED: frozenset(
        {MarketingTaskStatus.ACTIVE, MarketingTaskStatus.CANCELLED}
    ),
    MarketingTaskStatus.FAILED: frozenset(
        {MarketingTaskStatus.ACTIVE, MarketingTaskStatus.CANCELLED}
    ),
    MarketingTaskStatus.COMPLETED: frozenset({MarketingTaskStatus.ARCHIVED}),
    MarketingTaskStatus.CANCELLED: frozenset({MarketingTaskStatus.ARCHIVED}),
    MarketingTaskStatus.ARCHIVED: frozenset(),
}


_STEP_TRANSITIONS: dict[TaskStepStatus, frozenset[TaskStepStatus]] = {
    TaskStepStatus.PENDING: frozenset(
        {TaskStepStatus.RUNNING, TaskStepStatus.SKIPPED}
    ),
    TaskStepStatus.RUNNING: frozenset(
        {
            TaskStepStatus.WAITING_FOR_USER,
            TaskStepStatus.SUCCEEDED,
            TaskStepStatus.FAILED,
            TaskStepStatus.STALE,
        }
    ),
    TaskStepStatus.WAITING_FOR_USER: frozenset(
        {
            TaskStepStatus.RUNNING,
            TaskStepStatus.FAILED,
            TaskStepStatus.STALE,
        }
    ),
    TaskStepStatus.SUCCEEDED: frozenset({TaskStepStatus.STALE}),
    TaskStepStatus.FAILED: frozenset(
        {TaskStepStatus.RUNNING, TaskStepStatus.STALE}
    ),
    TaskStepStatus.SKIPPED: frozenset({TaskStepStatus.STALE}),
    TaskStepStatus.STALE: frozenset({TaskStepStatus.PENDING}),
}


_DEFAULT_APPLICABILITY: dict[
    MarketingTaskType, dict[TaskStepKey, StepApplicability]
] = {
    MarketingTaskType.FULL_MARKETING: {
        TaskStepKey.REQUIREMENT_UNDERSTANDING: StepApplicability.REQUIRED,
        TaskStepKey.CONTEXT_SNAPSHOT: StepApplicability.REQUIRED,
        TaskStepKey.OPPORTUNITY_DECISION: StepApplicability.OPTIONAL,
        TaskStepKey.STRATEGY_CONFIRMATION: StepApplicability.REQUIRED,
        TaskStepKey.COPY_PRODUCTION_REVIEW: StepApplicability.REQUIRED,
        TaskStepKey.IMAGE_PRODUCTION_REVIEW: StepApplicability.REQUIRED,
        TaskStepKey.CHANNEL_ADAPTATION: StepApplicability.OPTIONAL,
        TaskStepKey.QUALITY_CHECK: StepApplicability.REQUIRED,
        TaskStepKey.FINAL_CONFIRMATION: StepApplicability.OPTIONAL,
        TaskStepKey.DELIVERY: StepApplicability.OPTIONAL,
    },
    MarketingTaskType.COPY_ONLY: {
        TaskStepKey.REQUIREMENT_UNDERSTANDING: StepApplicability.REQUIRED,
        TaskStepKey.CONTEXT_SNAPSHOT: StepApplicability.REQUIRED,
        TaskStepKey.OPPORTUNITY_DECISION: StepApplicability.NOT_APPLICABLE,
        TaskStepKey.STRATEGY_CONFIRMATION: StepApplicability.REQUIRED,
        TaskStepKey.COPY_PRODUCTION_REVIEW: StepApplicability.REQUIRED,
        TaskStepKey.IMAGE_PRODUCTION_REVIEW: StepApplicability.NOT_APPLICABLE,
        TaskStepKey.CHANNEL_ADAPTATION: StepApplicability.OPTIONAL,
        TaskStepKey.QUALITY_CHECK: StepApplicability.OPTIONAL,
        TaskStepKey.FINAL_CONFIRMATION: StepApplicability.OPTIONAL,
        TaskStepKey.DELIVERY: StepApplicability.OPTIONAL,
    },
    MarketingTaskType.IMAGE_ONLY: {
        TaskStepKey.REQUIREMENT_UNDERSTANDING: StepApplicability.REQUIRED,
        TaskStepKey.CONTEXT_SNAPSHOT: StepApplicability.REQUIRED,
        TaskStepKey.OPPORTUNITY_DECISION: StepApplicability.NOT_APPLICABLE,
        TaskStepKey.STRATEGY_CONFIRMATION: StepApplicability.REQUIRED,
        TaskStepKey.COPY_PRODUCTION_REVIEW: StepApplicability.NOT_APPLICABLE,
        TaskStepKey.IMAGE_PRODUCTION_REVIEW: StepApplicability.REQUIRED,
        TaskStepKey.CHANNEL_ADAPTATION: StepApplicability.OPTIONAL,
        TaskStepKey.QUALITY_CHECK: StepApplicability.OPTIONAL,
        TaskStepKey.FINAL_CONFIRMATION: StepApplicability.OPTIONAL,
        TaskStepKey.DELIVERY: StepApplicability.OPTIONAL,
    },
    MarketingTaskType.IMAGE_OPTIMIZATION: {
        TaskStepKey.REQUIREMENT_UNDERSTANDING: StepApplicability.REQUIRED,
        TaskStepKey.CONTEXT_SNAPSHOT: StepApplicability.REQUIRED,
        TaskStepKey.OPPORTUNITY_DECISION: StepApplicability.NOT_APPLICABLE,
        TaskStepKey.STRATEGY_CONFIRMATION: StepApplicability.REQUIRED,
        TaskStepKey.COPY_PRODUCTION_REVIEW: StepApplicability.NOT_APPLICABLE,
        TaskStepKey.IMAGE_PRODUCTION_REVIEW: StepApplicability.REQUIRED,
        TaskStepKey.CHANNEL_ADAPTATION: StepApplicability.OPTIONAL,
        TaskStepKey.QUALITY_CHECK: StepApplicability.OPTIONAL,
        TaskStepKey.FINAL_CONFIRMATION: StepApplicability.OPTIONAL,
        TaskStepKey.DELIVERY: StepApplicability.OPTIONAL,
    },
    MarketingTaskType.MERCHANT_CONTENT: {
        TaskStepKey.REQUIREMENT_UNDERSTANDING: StepApplicability.REQUIRED,
        TaskStepKey.CONTEXT_SNAPSHOT: StepApplicability.REQUIRED,
        TaskStepKey.OPPORTUNITY_DECISION: StepApplicability.OPTIONAL,
        TaskStepKey.STRATEGY_CONFIRMATION: StepApplicability.OPTIONAL,
        TaskStepKey.COPY_PRODUCTION_REVIEW: StepApplicability.OPTIONAL,
        TaskStepKey.IMAGE_PRODUCTION_REVIEW: StepApplicability.OPTIONAL,
        TaskStepKey.CHANNEL_ADAPTATION: StepApplicability.OPTIONAL,
        TaskStepKey.QUALITY_CHECK: StepApplicability.OPTIONAL,
        TaskStepKey.FINAL_CONFIRMATION: StepApplicability.OPTIONAL,
        TaskStepKey.DELIVERY: StepApplicability.OPTIONAL,
    },
}


def resolve_step_applicability(
    task_type: MarketingTaskType | str,
    step_key: TaskStepKey | str,
    *,
    includes_copy: bool | None = None,
    includes_image: bool | None = None,
    selected_channels: bool | None = None,
    requires_external_delivery: bool | None = None,
) -> StepApplicability:
    try:
        normalized_type = MarketingTaskType(task_type)
    except ValueError as exc:
        raise ValueError(f"Unknown marketing task type: {task_type}") from exc

    try:
        normalized_step = TaskStepKey(step_key)
    except ValueError as exc:
        raise ValueError(f"Unknown marketing task step: {step_key}") from exc

    applicability = _DEFAULT_APPLICABILITY[normalized_type][normalized_step]

    if normalized_type is MarketingTaskType.MERCHANT_CONTENT:
        if includes_copy is False and includes_image is False:
            raise ValueError("Merchant content must include copy, image, or both")

    if normalized_step is TaskStepKey.COPY_PRODUCTION_REVIEW and includes_copy is not None:
        return (
            StepApplicability.NOT_APPLICABLE
            if not includes_copy
            else applicability
        )

    if normalized_step is TaskStepKey.IMAGE_PRODUCTION_REVIEW and includes_image is not None:
        return (
            StepApplicability.NOT_APPLICABLE
            if not includes_image
            else applicability
        )

    if normalized_step is TaskStepKey.CHANNEL_ADAPTATION and selected_channels is not None:
        return (
            StepApplicability.REQUIRED
            if selected_channels
            else StepApplicability.NOT_APPLICABLE
        )

    if normalized_step in {
        TaskStepKey.QUALITY_CHECK,
        TaskStepKey.FINAL_CONFIRMATION,
        TaskStepKey.DELIVERY,
    } and requires_external_delivery is not None:
        if requires_external_delivery:
            return StepApplicability.REQUIRED
        if normalized_step is not TaskStepKey.QUALITY_CHECK:
            return StepApplicability.NOT_APPLICABLE
        if normalized_type is not MarketingTaskType.FULL_MARKETING:
            return StepApplicability.NOT_APPLICABLE

    return applicability


def ensure_task_transition(
    current: MarketingTaskStatus | str,
    target: MarketingTaskStatus | str,
    *,
    steps: Iterable[TaskStepSnapshot] | None = None,
) -> None:
    try:
        current_status = MarketingTaskStatus(current)
        target_status = MarketingTaskStatus(target)
    except ValueError as exc:
        raise InvalidMarketingTaskTransition(
            f"Unknown task status transition: {current} -> {target}"
        ) from exc

    if target_status not in _TASK_TRANSITIONS[current_status]:
        raise InvalidMarketingTaskTransition(
            f"Task status transition is not allowed: {current_status} -> {target_status}"
        )

    if target_status is MarketingTaskStatus.COMPLETED:
        if steps is None:
            raise TaskCompletionBlocked(
                "Task completion requires the current applicable step snapshots"
            )
        ensure_task_can_complete(steps)


def ensure_task_can_complete(steps: Iterable[TaskStepSnapshot]) -> None:
    snapshots = tuple(steps)
    expected_keys = {step.value for step in TaskStepKey}
    actual_keys = [step.key for step in snapshots]
    if len(actual_keys) != len(expected_keys) or set(actual_keys) != expected_keys:
        raise TaskCompletionBlocked(
            "Task completion requires exactly one snapshot for every task step"
        )

    for step in snapshots:
        try:
            status = TaskStepStatus(step.status)
            applicability = StepApplicability(step.applicability)
        except ValueError as exc:
            raise TaskCompletionBlocked(
                f"Task step {step.key} has an unknown status or applicability"
            ) from exc

        if status is TaskStepStatus.SKIPPED and step.approval_required:
            raise TaskCompletionBlocked(
                f"Approval task step {step.key} cannot be skipped"
            )

        if applicability is StepApplicability.REQUIRED:
            if status is not TaskStepStatus.SUCCEEDED:
                raise TaskCompletionBlocked(
                    f"Required task step {step.key} must succeed before task completion"
                )
            continue

        if applicability is StepApplicability.NOT_APPLICABLE:
            if status is not TaskStepStatus.SKIPPED:
                raise TaskCompletionBlocked(
                    f"Not-applicable task step {step.key} must be explicitly skipped"
                )
            if not step.skip_reason:
                raise TaskCompletionBlocked(
                    f"Not-applicable task step {step.key} requires a skip reason"
                )
            continue

        if status not in {TaskStepStatus.SUCCEEDED, TaskStepStatus.SKIPPED}:
            raise TaskCompletionBlocked(
                f"Optional task step {step.key} must succeed or be explicitly skipped"
            )
        if status is TaskStepStatus.SKIPPED:
            if step.approval_required:
                raise TaskCompletionBlocked(
                    f"Approval task step {step.key} cannot be skipped"
                )
            if not step.skip_reason:
                raise TaskCompletionBlocked(
                    f"Skipped optional task step {step.key} requires a reason"
                )


def ensure_step_transition(
    current: TaskStepStatus | str,
    target: TaskStepStatus | str,
    *,
    applicability: StepApplicability | str,
    skip_reason: str | None = None,
    allow_explicit_skip: bool = False,
    approval_required: bool = False,
) -> None:
    try:
        current_status = TaskStepStatus(current)
        target_status = TaskStepStatus(target)
        step_applicability = StepApplicability(applicability)
    except ValueError as exc:
        raise InvalidTaskStepTransition(
            f"Unknown task step transition or applicability: {current} -> {target}"
        ) from exc

    if target_status not in _STEP_TRANSITIONS[current_status]:
        raise InvalidTaskStepTransition(
            f"Task step transition is not allowed: {current_status} -> {target_status}"
        )

    if step_applicability is StepApplicability.NOT_APPLICABLE and target_status not in {
        TaskStepStatus.SKIPPED,
        TaskStepStatus.STALE,
    }:
        raise InvalidTaskStepTransition(
            "A not-applicable task step cannot run or succeed"
        )

    if target_status is TaskStepStatus.SKIPPED:
        if approval_required:
            raise InvalidTaskStepTransition("Approval task steps cannot be skipped")
        if not skip_reason or not skip_reason.strip():
            raise InvalidTaskStepTransition("Skipping a task step requires a reason")
        if (
            step_applicability is not StepApplicability.NOT_APPLICABLE
            and not allow_explicit_skip
        ):
            raise InvalidTaskStepTransition(
                "An applicable task step requires an explicit skip decision"
            )
