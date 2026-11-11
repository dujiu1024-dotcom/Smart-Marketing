from sqlalchemy import ForeignKeyConstraint, UniqueConstraint

from store_operator.models import (
    BusinessFactSnapshot,
    DependencyEdge,
    MarketingTask,
    RequirementSnapshot,
    StepDecision,
    StrategySnapshot,
    TaskEvent,
    TaskStep,
)
from store_operator.models.base import Base


def _unique_columns(table, constraint_name: str) -> tuple[str, ...]:
    constraint = next(
        item
        for item in table.constraints
        if isinstance(item, UniqueConstraint) and item.name == constraint_name
    )
    return tuple(column.name for column in constraint.columns)


def _foreign_key(table, constraint_name: str) -> ForeignKeyConstraint:
    return next(
        item
        for item in table.foreign_key_constraints
        if item.name == constraint_name
    )


def test_marketing_task_tables_are_registered_in_metadata() -> None:
    expected = {
        "marketing_tasks",
        "requirement_snapshots",
        "strategy_snapshots",
        "business_fact_snapshots",
        "task_steps",
        "step_decisions",
        "dependency_edges",
        "task_events",
    }
    assert expected.issubset(Base.metadata.tables)


def test_marketing_task_uses_store_scoped_current_snapshot_references() -> None:
    table = MarketingTask.__table__
    assert _unique_columns(table, "uq_marketing_tasks_store_id") == (
        "store_id",
        "id",
    )

    requirement_fk = _foreign_key(
        table, "fk_marketing_tasks_current_requirement"
    )
    assert tuple(column.name for column in requirement_fk.columns) == (
        "store_id",
        "id",
        "current_requirement_snapshot_id",
    )
    assert requirement_fk.deferrable is True
    assert requirement_fk.initially == "DEFERRED"

    strategy_fk = _foreign_key(table, "fk_marketing_tasks_current_strategy")
    assert tuple(column.name for column in strategy_fk.columns) == (
        "store_id",
        "id",
        "current_strategy_snapshot_id",
    )


def test_snapshot_and_step_foreign_keys_preserve_task_ownership() -> None:
    requirement_fk = _foreign_key(
        RequirementSnapshot.__table__, "fk_requirement_snapshots_task"
    )
    assert tuple(column.name for column in requirement_fk.columns) == (
        "store_id",
        "task_id",
    )

    strategy_fk = _foreign_key(
        StrategySnapshot.__table__, "fk_strategy_snapshots_requirement"
    )
    assert tuple(column.name for column in strategy_fk.columns) == (
        "store_id",
        "task_id",
        "requirement_snapshot_id",
    )

    step_fk = _foreign_key(TaskStep.__table__, "fk_task_steps_task")
    assert tuple(column.name for column in step_fk.columns) == ("store_id", "task_id")

    decision_fk = _foreign_key(
        StepDecision.__table__, "fk_step_decisions_task_step"
    )
    assert tuple(column.name for column in decision_fk.columns) == (
        "store_id",
        "task_id",
        "task_step_id",
    )


def test_task_event_and_dependency_constraints_are_versioned() -> None:
    assert _unique_columns(
        TaskEvent.__table__, "uq_task_events_aggregate_version"
    ) == ("store_id", "task_id", "aggregate_version")

    assert _unique_columns(
        DependencyEdge.__table__, "uq_dependency_edges_version_pair"
    ) == (
        "store_id",
        "task_id",
        "upstream_type",
        "upstream_id",
        "upstream_fingerprint",
        "downstream_type",
        "downstream_id",
        "downstream_fingerprint",
    )

    assert _unique_columns(
        BusinessFactSnapshot.__table__,
        "uq_business_fact_snapshots_task_fact_version",
    ) == ("store_id", "task_id", "fact_key", "version_no")
