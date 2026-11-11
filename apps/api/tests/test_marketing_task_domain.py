import pytest

from store_operator.domain.marketing_task import (
    DependencyEdgeSnapshot,
    DependencyGraphCycleError,
    DependencyImpactPolicy,
    InvalidMarketingTaskTransition,
    InvalidTaskStepTransition,
    MarketingTaskStatus,
    MarketingTaskType,
    StepApplicability,
    TaskCompletionBlocked,
    TaskStepKey,
    TaskStepSnapshot,
    TaskStepStatus,
    compute_stale_downstream,
    ensure_step_transition,
    ensure_task_can_complete,
    ensure_task_transition,
    resolve_step_applicability,
    validate_dependency_graph,
)


def test_marketing_task_lifecycle_allows_only_documented_transitions() -> None:
    ensure_task_transition(MarketingTaskStatus.DRAFT, MarketingTaskStatus.ACTIVE)
    ensure_task_transition(
        MarketingTaskStatus.ACTIVE, MarketingTaskStatus.WAITING_FOR_USER
    )
    ensure_task_transition(
        MarketingTaskStatus.WAITING_FOR_USER, MarketingTaskStatus.ACTIVE
    )
    ensure_task_transition(MarketingTaskStatus.FAILED, MarketingTaskStatus.ACTIVE)
    ensure_task_transition(
        MarketingTaskStatus.COMPLETED, MarketingTaskStatus.ARCHIVED
    )

    with pytest.raises(InvalidMarketingTaskTransition):
        ensure_task_transition(
            MarketingTaskStatus.CANCELLED, MarketingTaskStatus.ACTIVE
        )
    with pytest.raises(InvalidMarketingTaskTransition):
        ensure_task_transition(
            MarketingTaskStatus.ARCHIVED, MarketingTaskStatus.DRAFT
        )


def completed_copy_only_steps() -> list[TaskStepSnapshot]:
    return [
        TaskStepSnapshot(
            key=TaskStepKey.REQUIREMENT_UNDERSTANDING.value,
            status=TaskStepStatus.SUCCEEDED,
            applicability=StepApplicability.REQUIRED,
        ),
        TaskStepSnapshot(
            key=TaskStepKey.CONTEXT_SNAPSHOT.value,
            status=TaskStepStatus.SUCCEEDED,
            applicability=StepApplicability.REQUIRED,
        ),
        TaskStepSnapshot(
            key=TaskStepKey.OPPORTUNITY_DECISION.value,
            status=TaskStepStatus.SKIPPED,
            applicability=StepApplicability.NOT_APPLICABLE,
            skip_reason="Opportunity discovery is not used for copy-only tasks",
        ),
        TaskStepSnapshot(
            key=TaskStepKey.STRATEGY_CONFIRMATION.value,
            status=TaskStepStatus.SUCCEEDED,
            applicability=StepApplicability.REQUIRED,
        ),
        TaskStepSnapshot(
            key=TaskStepKey.COPY_PRODUCTION_REVIEW.value,
            status=TaskStepStatus.SUCCEEDED,
            applicability=StepApplicability.REQUIRED,
        ),
        TaskStepSnapshot(
            key=TaskStepKey.IMAGE_PRODUCTION_REVIEW.value,
            status=TaskStepStatus.SKIPPED,
            applicability=StepApplicability.NOT_APPLICABLE,
            skip_reason="Copy-only task has no image artifact",
        ),
        TaskStepSnapshot(
            key=TaskStepKey.CHANNEL_ADAPTATION.value,
            status=TaskStepStatus.SKIPPED,
            applicability=StepApplicability.OPTIONAL,
            skip_reason="No channel selected",
        ),
        TaskStepSnapshot(
            key=TaskStepKey.QUALITY_CHECK.value,
            status=TaskStepStatus.SKIPPED,
            applicability=StepApplicability.OPTIONAL,
            skip_reason="No external delivery requested",
        ),
        TaskStepSnapshot(
            key=TaskStepKey.FINAL_CONFIRMATION.value,
            status=TaskStepStatus.SKIPPED,
            applicability=StepApplicability.OPTIONAL,
            skip_reason="No external delivery requested",
        ),
        TaskStepSnapshot(
            key=TaskStepKey.DELIVERY.value,
            status=TaskStepStatus.SKIPPED,
            applicability=StepApplicability.OPTIONAL,
            skip_reason="No external delivery requested",
        ),
    ]


def test_task_cannot_complete_without_all_applicable_steps() -> None:
    steps = completed_copy_only_steps()
    ensure_task_can_complete(steps)
    ensure_task_transition(
        MarketingTaskStatus.ACTIVE, MarketingTaskStatus.COMPLETED, steps=steps
    )

    incomplete = [
        TaskStepSnapshot(
            key=step.key,
            status=(
                TaskStepStatus.WAITING_FOR_USER
                if step.key == TaskStepKey.COPY_PRODUCTION_REVIEW.value
                else step.status
            ),
            applicability=step.applicability,
            skip_reason=step.skip_reason,
            approval_required=step.approval_required,
        )
        for step in steps
    ]
    with pytest.raises(TaskCompletionBlocked, match="copy_production_review"):
        ensure_task_can_complete(incomplete)

    with pytest.raises(TaskCompletionBlocked, match="every task step"):
        ensure_task_can_complete(steps[:-1])


def test_task_completion_rejects_unexplained_or_approval_skips() -> None:
    steps = completed_copy_only_steps()
    unexplained = [
        TaskStepSnapshot(
            key=step.key,
            status=step.status,
            applicability=step.applicability,
            skip_reason=(
                None
                if step.key == TaskStepKey.IMAGE_PRODUCTION_REVIEW.value
                else step.skip_reason
            ),
            approval_required=step.approval_required,
        )
        for step in steps
    ]
    with pytest.raises(TaskCompletionBlocked, match="skip reason"):
        ensure_task_can_complete(unexplained)

    approval_skipped = [
        TaskStepSnapshot(
            key=step.key,
            status=(
                TaskStepStatus.SKIPPED
                if step.key == TaskStepKey.COPY_PRODUCTION_REVIEW.value
                else step.status
            ),
            applicability=step.applicability,
            skip_reason=(
                "Attempted to skip an approval"
                if step.key == TaskStepKey.COPY_PRODUCTION_REVIEW.value
                else step.skip_reason
            ),
            approval_required=(
                True
                if step.key == TaskStepKey.COPY_PRODUCTION_REVIEW.value
                else step.approval_required
            ),
        )
        for step in steps
    ]
    with pytest.raises(TaskCompletionBlocked, match="cannot be skipped"):
        ensure_task_can_complete(approval_skipped)


def test_task_step_transitions_and_skip_gates() -> None:
    ensure_step_transition(
        TaskStepStatus.PENDING,
        TaskStepStatus.RUNNING,
        applicability=StepApplicability.REQUIRED,
    )
    ensure_step_transition(
        TaskStepStatus.RUNNING,
        TaskStepStatus.WAITING_FOR_USER,
        applicability=StepApplicability.REQUIRED,
    )
    ensure_step_transition(
        TaskStepStatus.WAITING_FOR_USER,
        TaskStepStatus.RUNNING,
        applicability=StepApplicability.REQUIRED,
    )
    ensure_step_transition(
        TaskStepStatus.RUNNING,
        TaskStepStatus.SUCCEEDED,
        applicability=StepApplicability.REQUIRED,
    )
    ensure_step_transition(
        TaskStepStatus.SUCCEEDED,
        TaskStepStatus.STALE,
        applicability=StepApplicability.REQUIRED,
    )
    ensure_step_transition(
        TaskStepStatus.STALE,
        TaskStepStatus.PENDING,
        applicability=StepApplicability.REQUIRED,
    )
    ensure_step_transition(
        TaskStepStatus.PENDING,
        TaskStepStatus.SKIPPED,
        applicability=StepApplicability.NOT_APPLICABLE,
        skip_reason="Image review does not apply to copy-only tasks",
    )

    with pytest.raises(InvalidTaskStepTransition):
        ensure_step_transition(
            TaskStepStatus.PENDING,
            TaskStepStatus.SUCCEEDED,
            applicability=StepApplicability.REQUIRED,
        )
    with pytest.raises(InvalidTaskStepTransition, match="explicit skip"):
        ensure_step_transition(
            TaskStepStatus.PENDING,
            TaskStepStatus.SKIPPED,
            applicability=StepApplicability.OPTIONAL,
            skip_reason="Not selected",
        )
    with pytest.raises(InvalidTaskStepTransition, match="cannot be skipped"):
        ensure_step_transition(
            TaskStepStatus.PENDING,
            TaskStepStatus.SKIPPED,
            applicability=StepApplicability.REQUIRED,
            skip_reason="Owner approval required",
            allow_explicit_skip=True,
            approval_required=True,
        )
    with pytest.raises(InvalidTaskStepTransition, match="cannot run or succeed"):
        ensure_step_transition(
            TaskStepStatus.PENDING,
            TaskStepStatus.RUNNING,
            applicability=StepApplicability.NOT_APPLICABLE,
        )


def test_task_type_applicability_matrix_matches_product_scope() -> None:
    assert (
        resolve_step_applicability(
            MarketingTaskType.FULL_MARKETING,
            TaskStepKey.OPPORTUNITY_DECISION,
        )
        is StepApplicability.OPTIONAL
    )
    assert (
        resolve_step_applicability(
            MarketingTaskType.COPY_ONLY,
            TaskStepKey.COPY_PRODUCTION_REVIEW,
        )
        is StepApplicability.REQUIRED
    )
    assert (
        resolve_step_applicability(
            MarketingTaskType.COPY_ONLY,
            TaskStepKey.IMAGE_PRODUCTION_REVIEW,
        )
        is StepApplicability.NOT_APPLICABLE
    )
    assert (
        resolve_step_applicability(
            MarketingTaskType.IMAGE_OPTIMIZATION,
            TaskStepKey.IMAGE_PRODUCTION_REVIEW,
        )
        is StepApplicability.REQUIRED
    )
    assert (
        resolve_step_applicability(
            MarketingTaskType.MERCHANT_CONTENT,
            TaskStepKey.COPY_PRODUCTION_REVIEW,
            includes_copy=True,
            includes_image=False,
        )
        is StepApplicability.OPTIONAL
    )


def test_dynamic_applicability_follows_selected_outputs_and_delivery_scope() -> None:
    assert (
        resolve_step_applicability(
            MarketingTaskType.FULL_MARKETING,
            TaskStepKey.OPPORTUNITY_DECISION,
            opportunity_applicable=True,
        )
        is StepApplicability.REQUIRED
    )
    assert (
        resolve_step_applicability(
            MarketingTaskType.FULL_MARKETING,
            TaskStepKey.OPPORTUNITY_DECISION,
            opportunity_applicable=False,
        )
        is StepApplicability.NOT_APPLICABLE
    )
    assert (
        resolve_step_applicability(
            MarketingTaskType.FULL_MARKETING,
            TaskStepKey.COPY_PRODUCTION_REVIEW,
            includes_copy=False,
        )
        is StepApplicability.NOT_APPLICABLE
    )
    assert (
        resolve_step_applicability(
            MarketingTaskType.MERCHANT_CONTENT,
            TaskStepKey.IMAGE_PRODUCTION_REVIEW,
            includes_copy=False,
            includes_image=True,
        )
        is StepApplicability.OPTIONAL
    )
    assert (
        resolve_step_applicability(
            MarketingTaskType.COPY_ONLY,
            TaskStepKey.CHANNEL_ADAPTATION,
            selected_channels=True,
        )
        is StepApplicability.REQUIRED
    )
    assert (
        resolve_step_applicability(
            MarketingTaskType.COPY_ONLY,
            TaskStepKey.CHANNEL_ADAPTATION,
            selected_channels=False,
        )
        is StepApplicability.NOT_APPLICABLE
    )
    assert (
        resolve_step_applicability(
            MarketingTaskType.IMAGE_ONLY,
            TaskStepKey.QUALITY_CHECK,
            requires_external_delivery=True,
        )
        is StepApplicability.REQUIRED
    )
    assert (
        resolve_step_applicability(
            MarketingTaskType.IMAGE_ONLY,
            TaskStepKey.FINAL_CONFIRMATION,
            requires_external_delivery=False,
        )
        is StepApplicability.NOT_APPLICABLE
    )


def test_invalid_task_types_and_empty_merchant_content_are_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown marketing task type"):
        resolve_step_applicability("unknown", TaskStepKey.CONTEXT_SNAPSHOT)

    with pytest.raises(ValueError, match="explicit copy and image applicability"):
        resolve_step_applicability(
            MarketingTaskType.MERCHANT_CONTENT,
            TaskStepKey.CONTEXT_SNAPSHOT,
        )

    with pytest.raises(ValueError, match="must include copy, image"):
        resolve_step_applicability(
            MarketingTaskType.MERCHANT_CONTENT,
            TaskStepKey.CONTEXT_SNAPSHOT,
            includes_copy=False,
            includes_image=False,
        )



def test_dependency_invalidation_respects_impact_policy() -> None:
    edges = [
        DependencyEdgeSnapshot("requirement", "strategy"),
        DependencyEdgeSnapshot("strategy", "copy"),
        DependencyEdgeSnapshot(
            "copy", "channel", DependencyImpactPolicy.RECHECK
        ),
        DependencyEdgeSnapshot("channel", "publish_package"),
        DependencyEdgeSnapshot(
            "strategy", "independent_image", DependencyImpactPolicy.IGNORE
        ),
    ]

    assert compute_stale_downstream({"requirement"}, edges) == frozenset(
        {"strategy", "copy", "channel"}
    )


def test_dependency_graph_rejects_cycles_and_invalid_policies() -> None:
    with pytest.raises(DependencyGraphCycleError, match="acyclic"):
        validate_dependency_graph(
            [
                DependencyEdgeSnapshot("requirement", "strategy"),
                DependencyEdgeSnapshot("strategy", "requirement"),
            ]
        )

    with pytest.raises(DependencyGraphCycleError, match="itself"):
        validate_dependency_graph([DependencyEdgeSnapshot("copy", "copy")])

    with pytest.raises(ValueError, match="Unknown dependency impact policy"):
        validate_dependency_graph(
            [DependencyEdgeSnapshot("copy", "channel", "unknown")]
        )
