from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from store_operator.models.base import Base


class StoreTaskScoped:
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    store_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MarketingTask(StoreTaskScoped, Base):
    __tablename__ = "marketing_tasks"
    __table_args__ = (
        UniqueConstraint("store_id", "id", name="uq_marketing_tasks_store_id"),
        CheckConstraint(
            "task_type IN ('full_marketing', 'copy_only', 'image_only', "
            "'image_optimization', 'merchant_content')",
            name="task_type",
        ),
        CheckConstraint(
            "lifecycle_status IN ('draft', 'active', 'waiting_for_user', 'blocked', "
            "'failed', 'completed', 'cancelled', 'archived')",
            name="lifecycle_status",
        ),
        CheckConstraint("version >= 1", name="version_positive"),
        ForeignKeyConstraint(
            ["store_id", "id", "current_requirement_snapshot_id"],
            [
                "requirement_snapshots.store_id",
                "requirement_snapshots.task_id",
                "requirement_snapshots.id",
            ],
            name="fk_marketing_tasks_current_requirement",
            use_alter=True,
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["store_id", "id", "current_strategy_snapshot_id"],
            [
                "strategy_snapshots.store_id",
                "strategy_snapshots.task_id",
                "strategy_snapshots.id",
            ],
            name="fk_marketing_tasks_current_strategy",
            use_alter=True,
            deferrable=True,
            initially="DEFERRED",
        ),
        Index(
            "ix_marketing_tasks_store_status_updated",
            "store_id",
            "lifecycle_status",
            "updated_at",
        ),
        Index("ix_marketing_tasks_store_created", "store_id", "created_at"),
    )

    task_type: Mapped[str] = mapped_column(String(32), nullable=False)
    lifecycle_status: Mapped[str] = mapped_column(
        String(24), nullable=False, server_default="draft"
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    requirement_draft_json: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    strategy_draft_json: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    task_options_json: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    current_requirement_snapshot_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True)
    )
    current_strategy_snapshot_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True)
    )
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class RequirementSnapshot(StoreTaskScoped, Base):
    __tablename__ = "requirement_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "store_id", "task_id", "id", name="uq_requirement_snapshots_store_task_id"
        ),
        UniqueConstraint(
            "store_id",
            "task_id",
            "snapshot_no",
            name="uq_requirement_snapshots_task_version",
        ),
        CheckConstraint("snapshot_no >= 1", name="snapshot_no_positive"),
        CheckConstraint("schema_version >= 1", name="schema_version_positive"),
        ForeignKeyConstraint(
            ["store_id", "task_id"],
            ["marketing_tasks.store_id", "marketing_tasks.id"],
            name="fk_requirement_snapshots_task",
            ondelete="RESTRICT",
        ),
        Index("ix_requirement_snapshots_task_created", "store_id", "task_id", "created_at"),
    )

    task_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    snapshot_no: Mapped[int] = mapped_column(Integer, nullable=False)
    payload_json: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    content_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True)
    )
    confirmed_by_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True)
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class StrategySnapshot(StoreTaskScoped, Base):
    __tablename__ = "strategy_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "store_id", "task_id", "id", name="uq_strategy_snapshots_store_task_id"
        ),
        UniqueConstraint(
            "store_id",
            "task_id",
            "snapshot_no",
            name="uq_strategy_snapshots_task_version",
        ),
        CheckConstraint("snapshot_no >= 1", name="snapshot_no_positive"),
        CheckConstraint("schema_version >= 1", name="schema_version_positive"),
        ForeignKeyConstraint(
            ["store_id", "task_id"],
            ["marketing_tasks.store_id", "marketing_tasks.id"],
            name="fk_strategy_snapshots_task",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["store_id", "task_id", "requirement_snapshot_id"],
            [
                "requirement_snapshots.store_id",
                "requirement_snapshots.task_id",
                "requirement_snapshots.id",
            ],
            name="fk_strategy_snapshots_requirement",
            ondelete="RESTRICT",
        ),
        Index("ix_strategy_snapshots_task_created", "store_id", "task_id", "created_at"),
    )

    task_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    requirement_snapshot_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False
    )
    snapshot_no: Mapped[int] = mapped_column(Integer, nullable=False)
    payload_json: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    content_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True)
    )
    confirmed_by_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True)
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BusinessFactSnapshot(StoreTaskScoped, Base):
    __tablename__ = "business_fact_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "store_id", "task_id", "id", name="uq_business_fact_snapshots_store_task_id"
        ),
        UniqueConstraint(
            "store_id",
            "task_id",
            "fact_key",
            "version_no",
            name="uq_business_fact_snapshots_task_fact_version",
        ),
        CheckConstraint("version_no >= 1", name="version_no_positive"),
        CheckConstraint("schema_version >= 1", name="schema_version_positive"),
        CheckConstraint(
            "confirmation_status IN ('pending', 'confirmed', 'rejected', 'needs_review')",
            name="confirmation_status",
        ),
        ForeignKeyConstraint(
            ["store_id", "task_id"],
            ["marketing_tasks.store_id", "marketing_tasks.id"],
            name="fk_business_fact_snapshots_task",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_business_fact_snapshots_task_fact",
            "store_id",
            "task_id",
            "fact_key",
            "version_no",
        ),
    )

    task_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    fact_key: Mapped[str] = mapped_column(String(120), nullable=False)
    source_type: Mapped[str] = mapped_column(String(48), nullable=False)
    source_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    source_version: Mapped[int | None] = mapped_column(Integer)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    value_json: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    content_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    confirmation_status: Mapped[str] = mapped_column(
        String(24), nullable=False, server_default="pending"
    )
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True)
    )
    confirmed_by_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True)
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TaskStep(StoreTaskScoped, Base):
    __tablename__ = "task_steps"
    __table_args__ = (
        UniqueConstraint("store_id", "task_id", "id", name="uq_task_steps_store_task_id"),
        UniqueConstraint("store_id", "task_id", "step_key", name="uq_task_steps_task_key"),
        CheckConstraint(
            "step_key IN ('requirement_understanding', 'context_snapshot', "
            "'opportunity_decision', 'strategy_confirmation', 'copy_production_review', "
            "'image_production_review', 'channel_adaptation', 'quality_check', "
            "'final_confirmation', 'delivery')",
            name="step_key",
        ),
        CheckConstraint(
            "status IN ('pending', 'running', 'waiting_for_user', 'succeeded', "
            "'failed', 'skipped', 'stale')",
            name="status",
        ),
        CheckConstraint(
            "applicability IN ('required', 'optional', 'not_applicable')",
            name="applicability",
        ),
        CheckConstraint(
            "status != 'skipped' OR (skip_reason IS NOT NULL AND length(btrim(skip_reason)) > 0)",
            name="skipped_reason",
        ),
        CheckConstraint(
            "applicability != 'required' OR status != 'skipped'",
            name="required_not_skipped",
        ),
        CheckConstraint(
            "applicability != 'not_applicable' OR status IN ('skipped', 'stale')",
            name="not_applicable_status",
        ),
        CheckConstraint("version >= 1", name="version_positive"),
        ForeignKeyConstraint(
            ["store_id", "task_id"],
            ["marketing_tasks.store_id", "marketing_tasks.id"],
            name="fk_task_steps_task",
            ondelete="RESTRICT",
        ),
        Index("ix_task_steps_store_status", "store_id", "status"),
        Index("ix_task_steps_task_status", "store_id", "task_id", "status"),
    )

    task_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    step_key: Mapped[str] = mapped_column(String(48), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, server_default="pending")
    applicability: Mapped[str] = mapped_column(
        String(24), nullable=False, server_default="required"
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    input_fingerprint: Mapped[str | None] = mapped_column(String(64))
    output_refs_json: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    blocked_by_json: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    block_code: Mapped[str | None] = mapped_column(String(60))
    block_detail_json: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    skip_reason: Mapped[str | None] = mapped_column(Text)
    skipped_by_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    skipped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class StepDecision(StoreTaskScoped, Base):
    __tablename__ = "step_decisions"
    __table_args__ = (
        UniqueConstraint("store_id", "task_id", "id", name="uq_step_decisions_store_task_id"),
        CheckConstraint(
            "decision IN ('approve', 'reject', 'skip', 'retry', 'resume', "
            "'confirm', 'adopt', 'defer', 'dismiss')",
            name="decision",
        ),
        CheckConstraint(
            "actor_type IN ('user', 'platform_admin', 'system')", name="actor_type"
        ),
        CheckConstraint(
            "(actor_type = 'system' AND actor_user_id IS NULL) OR "
            "(actor_type IN ('user', 'platform_admin') AND actor_user_id IS NOT NULL)",
            name="actor_reference",
        ),
        ForeignKeyConstraint(
            ["store_id", "task_id"],
            ["marketing_tasks.store_id", "marketing_tasks.id"],
            name="fk_step_decisions_task",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["store_id", "task_id", "task_step_id"],
            ["task_steps.store_id", "task_steps.task_id", "task_steps.id"],
            name="fk_step_decisions_task_step",
            ondelete="RESTRICT",
        ),
        Index("ix_step_decisions_task_created", "store_id", "task_id", "created_at"),
    )

    task_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    task_step_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    decision: Mapped[str] = mapped_column(String(24), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    actor_type: Mapped[str] = mapped_column(String(24), nullable=False)
    actor_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True)
    )
    evidence_json: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    idempotency_record_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True)
    )


class DependencyEdge(StoreTaskScoped, Base):
    __tablename__ = "dependency_edges"
    __table_args__ = (
        UniqueConstraint(
            "store_id",
            "task_id",
            "upstream_type",
            "upstream_id",
            "upstream_fingerprint",
            "downstream_type",
            "downstream_id",
            "downstream_fingerprint",
            name="uq_dependency_edges_version_pair",
        ),
        CheckConstraint(
            "impact_policy IN ('invalidate', 'recheck', 'ignore')",
            name="impact_policy",
        ),
        ForeignKeyConstraint(
            ["store_id", "task_id"],
            ["marketing_tasks.store_id", "marketing_tasks.id"],
            name="fk_dependency_edges_task",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_dependency_edges_upstream",
            "store_id",
            "task_id",
            "upstream_type",
            "upstream_id",
        ),
        Index(
            "ix_dependency_edges_downstream",
            "store_id",
            "task_id",
            "downstream_type",
            "downstream_id",
        ),
    )

    task_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    upstream_type: Mapped[str] = mapped_column(String(48), nullable=False)
    upstream_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    upstream_version_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    upstream_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    downstream_type: Mapped[str] = mapped_column(String(48), nullable=False)
    downstream_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    downstream_version_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    downstream_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    impact_policy: Mapped[str] = mapped_column(
        String(24), nullable=False, server_default="invalidate"
    )


class TaskEvent(StoreTaskScoped, Base):
    __tablename__ = "task_events"
    __table_args__ = (
        UniqueConstraint(
            "store_id",
            "task_id",
            "aggregate_version",
            name="uq_task_events_aggregate_version",
        ),
        CheckConstraint("aggregate_version >= 1", name="aggregate_version_positive"),
        CheckConstraint("schema_version >= 1", name="schema_version_positive"),
        CheckConstraint(
            "actor_type IN ('user', 'platform_admin', 'system')", name="actor_type"
        ),
        ForeignKeyConstraint(
            ["store_id", "task_id"],
            ["marketing_tasks.store_id", "marketing_tasks.id"],
            name="fk_task_events_task",
            ondelete="RESTRICT",
        ),
        Index("ix_task_events_task_occurred", "store_id", "task_id", "created_at"),
    )

    task_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    aggregate_version: Mapped[int] = mapped_column(Integer, nullable=False)
    actor_type: Mapped[str] = mapped_column(String(24), nullable=False)
    actor_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True)
    )
    correlation_id: Mapped[str | None] = mapped_column(String(128))
    causation_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    payload_json: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
