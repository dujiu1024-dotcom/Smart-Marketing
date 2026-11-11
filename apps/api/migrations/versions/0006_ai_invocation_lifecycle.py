"""Align AIInvocation status lifecycle and add request fingerprint.

Revision ID: 0006_ai_invocation_lifecycle
Revises: 0005_job_runtime
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

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
