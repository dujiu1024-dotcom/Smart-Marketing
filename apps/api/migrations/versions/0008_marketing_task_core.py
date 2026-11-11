"""Create the MarketingTask domain persistence model.

Revision ID: 0008_marketing_task_core
Revises: 0007_idempotency_actor_binding
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_marketing_task_core"
down_revision: str | None = "0007_idempotency_actor_binding"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB


def upgrade() -> None:
    op.create_table(
        "marketing_tasks",
        sa.Column("id", UUID, nullable=False),
        sa.Column("store_id", UUID, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("task_type", sa.String(length=32), nullable=False),
        sa.Column("lifecycle_status", sa.String(length=24), server_default="draft", nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "requirement_draft_json",
            JSONB,
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "strategy_draft_json",
            JSONB,
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "task_options_json",
            JSONB,
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("current_requirement_snapshot_id", UUID, nullable=True),
        sa.Column("current_strategy_snapshot_id", UUID, nullable=True),
        sa.Column("created_by_user_id", UUID, nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "task_type IN ('full_marketing', 'copy_only', 'image_only', "
            "'image_optimization', 'merchant_content')",
            name="ck_marketing_tasks_task_type",
        ),
        sa.CheckConstraint(
            "lifecycle_status IN ('draft', 'active', 'waiting_for_user', 'blocked', "
            "'failed', 'completed', 'cancelled', 'archived')",
            name="ck_marketing_tasks_lifecycle_status",
        ),
        sa.CheckConstraint("version >= 1", name="ck_marketing_tasks_version_positive"),
        sa.ForeignKeyConstraint(
            ["store_id"],
            ["stores.id"],
            name="fk_marketing_tasks_store_id_stores",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name="fk_marketing_tasks_created_by_user_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_marketing_tasks"),
        sa.UniqueConstraint("store_id", "id", name="uq_marketing_tasks_store_id"),
    )
    op.create_index(
        "ix_marketing_tasks_store_status_updated",
        "marketing_tasks",
        ["store_id", "lifecycle_status", "updated_at"],
    )
    op.create_index(
        "ix_marketing_tasks_store_created",
        "marketing_tasks",
        ["store_id", "created_at"],
    )

    op.create_table(
        "requirement_snapshots",
        sa.Column("id", UUID, nullable=False),
        sa.Column("store_id", UUID, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("task_id", UUID, nullable=False),
        sa.Column("snapshot_no", sa.Integer(), nullable=False),
        sa.Column("payload_json", JSONB, nullable=False),
        sa.Column("schema_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("content_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("created_by_user_id", UUID, nullable=True),
        sa.Column("confirmed_by_user_id", UUID, nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "snapshot_no >= 1",
            name="ck_requirement_snapshots_snapshot_no_positive",
        ),
        sa.CheckConstraint(
            "schema_version >= 1",
            name="ck_requirement_snapshots_schema_version_positive",
        ),
        sa.ForeignKeyConstraint(
            ["store_id"],
            ["stores.id"],
            name="fk_requirement_snapshots_store_id_stores",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["confirmed_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "task_id"],
            ["marketing_tasks.store_id", "marketing_tasks.id"],
            name="fk_requirement_snapshots_task",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_requirement_snapshots"),
        sa.UniqueConstraint(
            "store_id",
            "task_id",
            "id",
            name="uq_requirement_snapshots_store_task_id",
        ),
        sa.UniqueConstraint(
            "store_id",
            "task_id",
            "snapshot_no",
            name="uq_requirement_snapshots_task_version",
        ),
    )
    op.create_index(
        "ix_requirement_snapshots_task_created",
        "requirement_snapshots",
        ["store_id", "task_id", "created_at"],
    )

    op.create_table(
        "strategy_snapshots",
        sa.Column("id", UUID, nullable=False),
        sa.Column("store_id", UUID, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("task_id", UUID, nullable=False),
        sa.Column("requirement_snapshot_id", UUID, nullable=False),
        sa.Column("snapshot_no", sa.Integer(), nullable=False),
        sa.Column("payload_json", JSONB, nullable=False),
        sa.Column("schema_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("content_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("created_by_user_id", UUID, nullable=True),
        sa.Column("confirmed_by_user_id", UUID, nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("snapshot_no >= 1", name="ck_strategy_snapshots_snapshot_no_positive"),
        sa.CheckConstraint(
            "schema_version >= 1",
            name="ck_strategy_snapshots_schema_version_positive",
        ),
        sa.ForeignKeyConstraint(
            ["store_id"],
            ["stores.id"],
            name="fk_strategy_snapshots_store_id_stores",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["confirmed_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "task_id"],
            ["marketing_tasks.store_id", "marketing_tasks.id"],
            name="fk_strategy_snapshots_task",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "task_id", "requirement_snapshot_id"],
            [
                "requirement_snapshots.store_id",
                "requirement_snapshots.task_id",
                "requirement_snapshots.id",
            ],
            name="fk_strategy_snapshots_requirement",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_strategy_snapshots"),
        sa.UniqueConstraint(
            "store_id",
            "task_id",
            "id",
            name="uq_strategy_snapshots_store_task_id",
        ),
        sa.UniqueConstraint(
            "store_id",
            "task_id",
            "snapshot_no",
            name="uq_strategy_snapshots_task_version",
        ),
    )
    op.create_index(
        "ix_strategy_snapshots_task_created",
        "strategy_snapshots",
        ["store_id", "task_id", "created_at"],
    )

    op.create_table(
        "business_fact_snapshots",
        sa.Column("id", UUID, nullable=False),
        sa.Column("store_id", UUID, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("task_id", UUID, nullable=False),
        sa.Column("fact_key", sa.String(length=120), nullable=False),
        sa.Column("source_type", sa.String(length=48), nullable=False),
        sa.Column("source_id", UUID, nullable=True),
        sa.Column("source_version", sa.Integer(), nullable=True),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("value_json", JSONB, nullable=False),
        sa.Column("schema_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("content_fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "confirmation_status",
            sa.String(length=24),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("created_by_user_id", UUID, nullable=True),
        sa.Column("confirmed_by_user_id", UUID, nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "version_no >= 1",
            name="ck_business_fact_snapshots_version_no_positive",
        ),
        sa.CheckConstraint(
            "schema_version >= 1",
            name="ck_business_fact_snapshots_schema_version_positive",
        ),
        sa.CheckConstraint(
            "confirmation_status IN ('pending', 'confirmed', 'rejected', 'needs_review')",
            name="ck_business_fact_snapshots_confirmation_status",
        ),
        sa.ForeignKeyConstraint(
            ["store_id"],
            ["stores.id"],
            name="fk_business_fact_snapshots_store_id_stores",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["confirmed_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "task_id"],
            ["marketing_tasks.store_id", "marketing_tasks.id"],
            name="fk_business_fact_snapshots_task",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_business_fact_snapshots"),
        sa.UniqueConstraint(
            "store_id",
            "task_id",
            "id",
            name="uq_business_fact_snapshots_store_task_id",
        ),
        sa.UniqueConstraint(
            "store_id",
            "task_id",
            "fact_key",
            "version_no",
            name="uq_business_fact_snapshots_task_fact_version",
        ),
    )
    op.create_index(
        "ix_business_fact_snapshots_task_fact",
        "business_fact_snapshots",
        ["store_id", "task_id", "fact_key", "version_no"],
    )

    op.create_table(
        "task_steps",
        sa.Column("id", UUID, nullable=False),
        sa.Column("store_id", UUID, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("task_id", UUID, nullable=False),
        sa.Column("step_key", sa.String(length=48), nullable=False),
        sa.Column("status", sa.String(length=24), server_default="pending", nullable=False),
        sa.Column("applicability", sa.String(length=24), server_default="required", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("output_refs_json", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("blocked_by_json", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("skip_reason", sa.Text(), nullable=True),
        sa.Column("skipped_by_user_id", UUID, nullable=True),
        sa.Column("skipped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "step_key IN ('requirement_understanding', 'context_snapshot', "
            "'opportunity_decision', 'strategy_confirmation', 'copy_production_review', "
            "'image_production_review', 'channel_adaptation', 'quality_check', "
            "'final_confirmation', 'delivery')",
            name="ck_task_steps_step_key",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'waiting_for_user', 'succeeded', "
            "'failed', 'skipped', 'stale')",
            name="ck_task_steps_status",
        ),
        sa.CheckConstraint(
            "applicability IN ('required', 'optional', 'not_applicable')",
            name="ck_task_steps_applicability",
        ),
        sa.CheckConstraint("version >= 1", name="ck_task_steps_version_positive"),
        sa.ForeignKeyConstraint(
            ["store_id"],
            ["stores.id"],
            name="fk_task_steps_store_id_stores",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["skipped_by_user_id"],
            ["users.id"],
            name="fk_task_steps_skipped_by_user_id_users",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "task_id"],
            ["marketing_tasks.store_id", "marketing_tasks.id"],
            name="fk_task_steps_task",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_task_steps"),
        sa.UniqueConstraint("store_id", "task_id", "id", name="uq_task_steps_store_task_id"),
        sa.UniqueConstraint("store_id", "task_id", "step_key", name="uq_task_steps_task_key"),
    )
    op.create_index("ix_task_steps_store_status", "task_steps", ["store_id", "status"])
    op.create_index("ix_task_steps_task_status", "task_steps", ["store_id", "task_id", "status"])

    op.create_table(
        "step_decisions",
        sa.Column("id", UUID, nullable=False),
        sa.Column("store_id", UUID, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("task_id", UUID, nullable=False),
        sa.Column("task_step_id", UUID, nullable=False),
        sa.Column("decision", sa.String(length=24), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("actor_type", sa.String(length=24), nullable=False),
        sa.Column("actor_user_id", UUID, nullable=True),
        sa.Column("evidence_json", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("idempotency_record_id", UUID, nullable=True),
        sa.CheckConstraint(
            "decision IN ('approve', 'reject', 'skip', 'retry', 'resume', "
            "'confirm', 'adopt', 'defer', 'dismiss')",
            name="ck_step_decisions_decision",
        ),
        sa.CheckConstraint(
            "actor_type IN ('user', 'platform_admin', 'system')",
            name="ck_step_decisions_actor_type",
        ),
        sa.CheckConstraint(
            "(actor_type = 'system' AND actor_user_id IS NULL) OR "
            "(actor_type IN ('user', 'platform_admin') AND actor_user_id IS NOT NULL)",
            name="ck_step_decisions_actor_reference",
        ),
        sa.ForeignKeyConstraint(
            ["store_id"],
            ["stores.id"],
            name="fk_step_decisions_store_id_stores",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["idempotency_record_id"],
            ["idempotency_records.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "task_id"],
            ["marketing_tasks.store_id", "marketing_tasks.id"],
            name="fk_step_decisions_task",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "task_id", "task_step_id"],
            ["task_steps.store_id", "task_steps.task_id", "task_steps.id"],
            name="fk_step_decisions_task_step",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_step_decisions"),
        sa.UniqueConstraint("store_id", "task_id", "id", name="uq_step_decisions_store_task_id"),
    )
    op.create_index(
        "ix_step_decisions_task_created",
        "step_decisions",
        ["store_id", "task_id", "created_at"],
    )

    op.create_table(
        "dependency_edges",
        sa.Column("id", UUID, nullable=False),
        sa.Column("store_id", UUID, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("task_id", UUID, nullable=False),
        sa.Column("upstream_type", sa.String(length=48), nullable=False),
        sa.Column("upstream_id", UUID, nullable=False),
        sa.Column("upstream_version_id", UUID, nullable=True),
        sa.Column("upstream_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("downstream_type", sa.String(length=48), nullable=False),
        sa.Column("downstream_id", UUID, nullable=False),
        sa.Column("downstream_version_id", UUID, nullable=True),
        sa.Column("downstream_fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "impact_policy",
            sa.String(length=24),
            server_default="invalidate",
            nullable=False,
        ),
        sa.CheckConstraint(
            "impact_policy IN ('invalidate', 'recheck', 'ignore')",
            name="ck_dependency_edges_impact_policy",
        ),
        sa.ForeignKeyConstraint(
            ["store_id"],
            ["stores.id"],
            name="fk_dependency_edges_store_id_stores",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "task_id"],
            ["marketing_tasks.store_id", "marketing_tasks.id"],
            name="fk_dependency_edges_task",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_dependency_edges"),
        sa.UniqueConstraint(
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
    )
    op.create_index(
        "ix_dependency_edges_upstream",
        "dependency_edges",
        ["store_id", "task_id", "upstream_type", "upstream_id"],
    )
    op.create_index(
        "ix_dependency_edges_downstream",
        "dependency_edges",
        ["store_id", "task_id", "downstream_type", "downstream_id"],
    )

    op.create_table(
        "task_events",
        sa.Column("id", UUID, nullable=False),
        sa.Column("store_id", UUID, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("task_id", UUID, nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("aggregate_version", sa.Integer(), nullable=False),
        sa.Column("actor_type", sa.String(length=24), nullable=False),
        sa.Column("actor_user_id", UUID, nullable=True),
        sa.Column("correlation_id", sa.String(length=128), nullable=True),
        sa.Column("causation_id", UUID, nullable=True),
        sa.Column("payload_json", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("schema_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "aggregate_version >= 1",
            name="ck_task_events_aggregate_version_positive",
        ),
        sa.CheckConstraint("schema_version >= 1", name="ck_task_events_schema_version_positive"),
        sa.CheckConstraint(
            "actor_type IN ('user', 'platform_admin', 'system')",
            name="ck_task_events_actor_type",
        ),
        sa.CheckConstraint(
            "(actor_type = 'system' AND actor_user_id IS NULL) OR "
            "(actor_type IN ('user', 'platform_admin') AND actor_user_id IS NOT NULL)",
            name="ck_task_events_actor_reference",
        ),
        sa.ForeignKeyConstraint(
            ["store_id"],
            ["stores.id"],
            name="fk_task_events_store_id_stores",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "task_id"],
            ["marketing_tasks.store_id", "marketing_tasks.id"],
            name="fk_task_events_task",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_task_events"),
        sa.UniqueConstraint(
            "store_id",
            "task_id",
            "aggregate_version",
            name="uq_task_events_aggregate_version",
        ),
    )
    op.create_index(
        "ix_task_events_task_occurred",
        "task_events",
        ["store_id", "task_id", "created_at"],
    )

    op.create_foreign_key(
        "fk_marketing_tasks_current_requirement",
        "marketing_tasks",
        "requirement_snapshots",
        ["store_id", "id", "current_requirement_snapshot_id"],
        ["store_id", "task_id", "id"],
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_foreign_key(
        "fk_marketing_tasks_current_strategy",
        "marketing_tasks",
        "strategy_snapshots",
        ["store_id", "id", "current_strategy_snapshot_id"],
        ["store_id", "task_id", "id"],
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION reject_marketing_task_immutable_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'marketing task snapshots and decisions are append-only';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    for table_name in (
        "requirement_snapshots",
        "strategy_snapshots",
        "business_fact_snapshots",
        "step_decisions",
        "dependency_edges",
        "task_events",
    ):
        op.execute(
            f"""
            CREATE TRIGGER trg_{table_name}_append_only
            BEFORE UPDATE OR DELETE ON {table_name}
            FOR EACH ROW
            EXECUTE FUNCTION reject_marketing_task_immutable_mutation();
            """
        )


def downgrade() -> None:
    for table_name in (
        "requirement_snapshots",
        "strategy_snapshots",
        "business_fact_snapshots",
        "step_decisions",
        "dependency_edges",
        "task_events",
    ):
        op.execute(
            f"DROP TRIGGER IF EXISTS trg_{table_name}_append_only ON {table_name}"
        )
    op.execute("DROP FUNCTION IF EXISTS reject_marketing_task_immutable_mutation()")

    op.drop_constraint(
        "fk_marketing_tasks_current_strategy", "marketing_tasks", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_marketing_tasks_current_requirement", "marketing_tasks", type_="foreignkey"
    )
    op.drop_table("task_events")
    op.drop_table("dependency_edges")
    op.drop_table("step_decisions")
    op.drop_table("task_steps")
    op.drop_table("business_fact_snapshots")
    op.drop_table("strategy_snapshots")
    op.drop_table("requirement_snapshots")
    op.drop_table("marketing_tasks")
