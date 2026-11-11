"""Persist external Douyin publish API attempts.

Revision ID: 0014_publish_operation_attempts
Revises: 0013_douyin_channel_delivery
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014_publish_operation_attempts"
down_revision: str | None = "0013_douyin_channel_delivery"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "publish_operation_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("publish_operation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("adapter_version", sa.String(80), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("external_request_id", sa.String(160)),
        sa.Column("response_evidence_ref", sa.String(2048)),
        sa.Column("normalized_status", sa.String(24), nullable=False),
        sa.Column("error_code", sa.String(100)),
        sa.Column("retryable", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "store_id",
            "publish_operation_id",
            "attempt_no",
            name="uq_publish_operation_attempts_operation_no",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "publish_operation_id"],
            ["publish_operations.store_id", "publish_operations.id"],
            name="fk_publish_operation_attempts_operation_same_store",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "attempt_no >= 1",
            name="ck_publish_operation_attempts_attempt_no_positive",
        ),
        sa.CheckConstraint(
            "action IN ('upload_image', 'publish_image_text', 'readback')",
            name="ck_publish_operation_attempts_action",
        ),
        sa.CheckConstraint(
            (
                "normalized_status IN ('started', 'accepted', 'verified', "
                "'not_found', 'failed', 'unknown')"
            ),
            name="ck_publish_operation_attempts_normalized_status",
        ),
    )
    op.create_index(
        "ix_publish_operation_attempts_operation_created",
        "publish_operation_attempts",
        ["store_id", "publish_operation_id", "started_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_publish_operation_attempts_operation_created",
        table_name="publish_operation_attempts",
    )
    op.drop_table("publish_operation_attempts")
