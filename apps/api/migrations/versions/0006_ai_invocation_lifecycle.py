"""Align AIInvocation status lifecycle and add request fingerprint.

Revision ID: 0006_ai_invocation_lifecycle
Revises: 0005_job_runtime
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_ai_invocation_lifecycle"
down_revision: str | None = "0005_job_runtime"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ai_invocations",
        sa.Column("request_fingerprint", sa.String(64), nullable=True),
    )
    op.add_column(
        "ai_invocations",
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "ai_invocations",
        sa.Column("response_ref", postgresql.JSONB(), nullable=True),
    )
    op.alter_column(
        "ai_invocations",
        "marketing_task_id",
        new_column_name="task_id",
        existing_type=postgresql.UUID(as_uuid=True),
    )
    op.alter_column(
        "ai_invocations",
        "provider",
        new_column_name="provider_key",
        existing_type=sa.String(100),
    )
    op.alter_column(
        "ai_invocations",
        "model",
        new_column_name="model_key",
        existing_type=sa.String(150),
    )
    op.alter_column(
        "ai_invocations",
        "prompt_template_id",
        new_column_name="prompt_version_id",
        existing_type=postgresql.UUID(as_uuid=True),
    )
    op.drop_column("ai_invocations", "prompt_version")
    op.drop_constraint(
        "ck_ai_invocations_latency_nonnegative", "ai_invocations", type_="check"
    )
    op.alter_column(
        "ai_invocations",
        "latency_ms",
        new_column_name="duration_ms",
        existing_type=sa.BigInteger(),
    )
    op.create_check_constraint(
        "ck_ai_invocations_duration_nonnegative",
        "ai_invocations",
        "duration_ms IS NULL OR duration_ms >= 0",
    )
    op.drop_constraint("ck_ai_invocations_status", "ai_invocations", type_="check")
    op.execute(
        "UPDATE ai_invocations SET status = 'running' WHERE status = 'started'"
    )
    op.execute(
        "UPDATE ai_invocations SET status = 'failed', "
        "error_code = COALESCE(error_code, 'AI_INVOCATION_REQUIRES_REVIEW') "
        "WHERE status = 'needs_human'"
    )
    op.create_check_constraint(
        "ck_ai_invocations_status",
        "ai_invocations",
        "status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_ai_invocations_status", "ai_invocations", type_="check")
    op.drop_constraint(
        "ck_ai_invocations_duration_nonnegative", "ai_invocations", type_="check"
    )
    op.alter_column(
        "ai_invocations",
        "duration_ms",
        new_column_name="latency_ms",
        existing_type=sa.BigInteger(),
    )
    op.create_check_constraint(
        "ck_ai_invocations_latency_nonnegative",
        "ai_invocations",
        "latency_ms IS NULL OR latency_ms >= 0",
    )
    op.add_column(
        "ai_invocations",
        sa.Column("prompt_version", sa.String(80), nullable=True),
    )
    op.alter_column(
        "ai_invocations",
        "prompt_version_id",
        new_column_name="prompt_template_id",
        existing_type=postgresql.UUID(as_uuid=True),
    )
    op.alter_column(
        "ai_invocations",
        "model_key",
        new_column_name="model",
        existing_type=sa.String(150),
    )
    op.alter_column(
        "ai_invocations",
        "provider_key",
        new_column_name="provider",
        existing_type=sa.String(100),
    )
    op.alter_column(
        "ai_invocations",
        "task_id",
        new_column_name="marketing_task_id",
        existing_type=postgresql.UUID(as_uuid=True),
    )
    op.drop_column("ai_invocations", "response_ref")
    op.execute(
        "UPDATE ai_invocations SET status = 'started' "
        "WHERE status IN ('queued', 'running', 'cancelled')"
    )
    op.create_check_constraint(
        "ck_ai_invocations_status",
        "ai_invocations",
        "status IN ('started', 'succeeded', 'failed', 'needs_human')",
    )
    op.drop_column("ai_invocations", "finished_at")
    op.drop_column("ai_invocations", "request_fingerprint")
