"""Persistent asynchronous jobs, outbox events and AI invocation usage.

Revision ID: 0005_job_runtime
Revises: 0004_idempotency_records
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_job_runtime"
down_revision: str | None = "0004_idempotency_records"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "store_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("stores.id", ondelete="RESTRICT"),
        ),
        sa.Column("idempotency_scope_type", sa.String(20), nullable=False),
        sa.Column("idempotency_scope_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("marketing_task_id", postgresql.UUID(as_uuid=True)),
        sa.Column("job_type", sa.String(100), nullable=False),
        sa.Column("status", sa.String(20), server_default="queued", nullable=False),
        sa.Column("priority", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("payload_ref", postgresql.JSONB(), nullable=False),
        sa.Column("result_ref", postgresql.JSONB()),
        sa.Column("queue_name", sa.String(100), server_default="default", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="3", nullable=False),
        sa.Column(
            "available_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("timeout_seconds", sa.Integer(), server_default="300", nullable=False),
        sa.Column("lease_owner", sa.String(200)),
        sa.Column("lease_token", postgresql.UUID(as_uuid=True)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True)),
        sa.Column("progress_current", sa.BigInteger()),
        sa.Column("progress_total", sa.BigInteger()),
        sa.Column("error_code", sa.String(100)),
        sa.Column("error_summary", sa.String(500)),
        sa.Column("actor_type", sa.String(24), server_default="user", nullable=False),
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True)),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "idempotency_scope_type",
            "idempotency_scope_id",
            "idempotency_key",
            name="uq_jobs_idempotency_scope_key",
        ),
        sa.CheckConstraint(
            "(idempotency_scope_type = 'store' AND store_id IS NOT NULL "
            "AND idempotency_scope_id = store_id) OR "
            "(idempotency_scope_type = 'system' AND store_id IS NULL)",
            name="ck_jobs_idempotency_scope",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'retry_wait', 'succeeded', "
            "'failed', 'cancelled', 'needs_human')",
            name="ck_jobs_status",
        ),
        sa.CheckConstraint(
            "actor_type IN ('user', 'platform_admin', 'system')",
            name="ck_jobs_actor_type",
        ),
        sa.CheckConstraint("priority BETWEEN -100 AND 100", name="ck_jobs_priority_bounds"),
        sa.CheckConstraint("attempt_count >= 0", name="ck_jobs_attempt_count_nonnegative"),
        sa.CheckConstraint("max_attempts >= 1", name="ck_jobs_max_attempts_positive"),
        sa.CheckConstraint("timeout_seconds > 0", name="ck_jobs_timeout_positive"),
        sa.CheckConstraint(
            "progress_current IS NULL OR progress_current >= 0",
            name="ck_jobs_progress_current_nonnegative",
        ),
        sa.CheckConstraint(
            "progress_total IS NULL OR progress_total >= 0",
            name="ck_jobs_progress_total_nonnegative",
        ),
        sa.CheckConstraint(
            "progress_current IS NULL OR progress_total IS NULL "
            "OR progress_current <= progress_total",
            name="ck_jobs_progress_within_total",
        ),
        sa.CheckConstraint(
            "status <> 'running' OR (lease_owner IS NOT NULL AND lease_token IS NOT NULL "
            "AND lease_expires_at IS NOT NULL)",
            name="ck_jobs_running_lease_required",
        ),
    )
    op.create_index(
        "ix_jobs_status_available_priority",
        "jobs",
        ["status", "available_at", "priority", "created_at"],
    )
    op.create_index("ix_jobs_store_created", "jobs", ["store_id", "created_at"])
    op.create_index("ix_jobs_marketing_task", "jobs", ["marketing_task_id"])
    op.create_index("ix_jobs_lease_expires", "jobs", ["lease_expires_at"])

    op.create_table(
        "job_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("jobs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("lease_token", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("worker_id", sa.String(200), nullable=False),
        sa.Column("status", sa.String(30), server_default="running", nullable=False),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("duration_ms", sa.BigInteger()),
        sa.Column("error_code", sa.String(100)),
        sa.Column("error_summary", sa.String(500)),
        sa.Column("provider", sa.String(100)),
        sa.Column("model", sa.String(150)),
        sa.UniqueConstraint("job_id", "attempt_no", name="uq_job_attempts_job_attempt_no"),
        sa.CheckConstraint("attempt_no >= 1", name="ck_job_attempts_attempt_no_positive"),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'failed', 'lease_expired', 'cancelled')",
            name="ck_job_attempts_status",
        ),
    )
    op.create_index("ix_job_attempts_job_started", "job_attempts", ["job_id", "started_at"])

    op.create_table(
        "job_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("jobs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(150), nullable=False),
        sa.Column("actor_type", sa.String(24), server_default="system", nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True)),
        sa.Column(
            "attempt_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("job_attempts.id", ondelete="SET NULL"),
        ),
        sa.Column("lease_token", postgresql.UUID(as_uuid=True)),
        sa.Column("data", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "actor_type IN ('user', 'platform_admin', 'system')",
            name="ck_job_events_actor_type",
        ),
    )
    op.create_index("ix_job_events_job_created", "job_events", ["job_id", "created_at"])

    op.create_table(
        "outbox_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("aggregate_type", sa.String(100), nullable=False),
        sa.Column("aggregate_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(150), nullable=False),
        sa.Column("schema_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("dedupe_key", sa.String(200), nullable=False),
        sa.Column("status", sa.String(20), server_default="pending", nullable=False),
        sa.Column(
            "available_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("publish_attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("locked_by", sa.String(200)),
        sa.Column("locked_until", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.String(500)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("dedupe_key", name="uq_outbox_events_dedupe_key"),
        sa.CheckConstraint(
            "status IN ('pending', 'publishing', 'published', 'dead')",
            name="ck_outbox_events_status",
        ),
        sa.CheckConstraint("schema_version >= 1", name="ck_outbox_events_schema_version_positive"),
        sa.CheckConstraint(
            "publish_attempts >= 0", name="ck_outbox_events_publish_attempts_nonnegative"
        ),
        sa.CheckConstraint(
            "status <> 'publishing' OR (locked_by IS NOT NULL AND locked_until IS NOT NULL)",
            name="ck_outbox_events_publishing_lock_required",
        ),
        sa.CheckConstraint(
            "status <> 'published' OR published_at IS NOT NULL",
            name="ck_outbox_events_published_timestamp_required",
        ),
    )
    op.create_index(
        "ix_outbox_events_status_available", "outbox_events", ["status", "available_at"]
    )
    op.create_index("ix_outbox_events_lock_expiry", "outbox_events", ["locked_until"])

    op.create_table(
        "ai_invocations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "store_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("stores.id", ondelete="RESTRICT"),
        ),
        sa.Column("marketing_task_id", postgresql.UUID(as_uuid=True)),
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("jobs.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "attempt_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("job_attempts.id", ondelete="SET NULL"),
        ),
        sa.Column("provider", sa.String(100), nullable=False),
        sa.Column("model", sa.String(150), nullable=False),
        sa.Column("capability", sa.String(24), nullable=False),
        sa.Column("prompt_template_id", postgresql.UUID(as_uuid=True)),
        sa.Column("prompt_version", sa.String(80)),
        sa.Column("parameter_snapshot", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("input_schema_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("output_schema_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("provider_request_id", sa.String(200)),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("latency_ms", sa.BigInteger()),
        sa.Column("error_code", sa.String(100)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('started', 'succeeded', 'failed', 'needs_human')",
            name="ck_ai_invocations_status",
        ),
        sa.CheckConstraint(
            "latency_ms IS NULL OR latency_ms >= 0",
            name="ck_ai_invocations_latency_nonnegative",
        ),
        sa.CheckConstraint(
            "input_schema_version >= 1",
            name="ck_ai_invocations_input_schema_version_positive",
        ),
        sa.CheckConstraint(
            "output_schema_version >= 1",
            name="ck_ai_invocations_output_schema_version_positive",
        ),
    )
    op.create_index("ix_ai_invocations_store_created", "ai_invocations", ["store_id", "created_at"])
    op.create_index("ix_ai_invocations_job", "ai_invocations", ["job_id"])

    op.create_table(
        "ai_usage_records",
        sa.Column(
            "invocation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ai_invocations.id", ondelete="RESTRICT"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("input_tokens", sa.BigInteger()),
        sa.Column("output_tokens", sa.BigInteger()),
        sa.Column("image_units", sa.Numeric(14, 4)),
        sa.Column("cost_amount", sa.Numeric(18, 6)),
        sa.Column("currency", sa.String(3)),
        sa.Column("metering_source", sa.String(40), nullable=False),
        sa.Column(
            "recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "input_tokens IS NULL OR input_tokens >= 0",
            name="ck_ai_usage_records_input_tokens_nonnegative",
        ),
        sa.CheckConstraint(
            "output_tokens IS NULL OR output_tokens >= 0",
            name="ck_ai_usage_records_output_tokens_nonnegative",
        ),
        sa.CheckConstraint(
            "image_units IS NULL OR image_units >= 0",
            name="ck_ai_usage_records_image_units_nonnegative",
        ),
        sa.CheckConstraint(
            "cost_amount IS NULL OR cost_amount >= 0",
            name="ck_ai_usage_records_cost_nonnegative",
        ),
        sa.CheckConstraint(
            "(cost_amount IS NULL AND currency IS NULL) OR "
            "(cost_amount IS NOT NULL AND currency IS NOT NULL)",
            name="ck_ai_usage_records_cost_currency_pair",
        ),
    )


def downgrade() -> None:
    op.drop_table("ai_usage_records")
    op.drop_index("ix_ai_invocations_job", table_name="ai_invocations")
    op.drop_index("ix_ai_invocations_store_created", table_name="ai_invocations")
    op.drop_table("ai_invocations")
    op.drop_index("ix_outbox_events_lock_expiry", table_name="outbox_events")
    op.drop_index("ix_outbox_events_status_available", table_name="outbox_events")
    op.drop_table("outbox_events")
    op.drop_index("ix_job_events_job_created", table_name="job_events")
    op.drop_table("job_events")
    op.drop_index("ix_job_attempts_job_started", table_name="job_attempts")
    op.drop_table("job_attempts")
    op.drop_index("ix_jobs_lease_expires", table_name="jobs")
    op.drop_index("ix_jobs_marketing_task", table_name="jobs")
    op.drop_index("ix_jobs_store_created", table_name="jobs")
    op.drop_index("ix_jobs_status_available_priority", table_name="jobs")
    op.drop_table("jobs")
