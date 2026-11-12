"""Persist idempotent receipts for Douyin authorization webhooks.

Revision ID: 0016_douyin_webhook_receipts
Revises: 0015_pubop_attempts
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016_douyin_webhook_receipts"
down_revision: str | None = "0015_pubop_attempts"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "douyin_webhook_receipts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("message_id", sa.String(160), nullable=False),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("external_user_id_hash", sa.String(64), nullable=False),
        sa.Column(
            "scopes_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "affected_account_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "provider",
            "message_id",
            name="uq_douyin_webhook_receipts_provider_message_id",
        ),
        sa.CheckConstraint("provider IN ('douyin')", name="ck_douyin_webhook_receipts_provider"),
        sa.CheckConstraint(
            "event_type IN ('unauthorize')",
            name="ck_douyin_webhook_receipts_event_type",
        ),
        sa.CheckConstraint(
            "length(message_id) > 0",
            name="ck_douyin_webhook_receipts_message_id_nonempty",
        ),
        sa.CheckConstraint(
            "length(external_user_id_hash) = 64",
            name="ck_douyin_webhook_receipts_external_user_hash_length",
        ),
        sa.CheckConstraint(
            "affected_account_count >= 0",
            name="ck_douyin_webhook_receipts_affected_account_count_nonnegative",
        ),
    )
    op.create_index(
        "ix_douyin_webhook_receipts_received_at",
        "douyin_webhook_receipts",
        ["received_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_douyin_webhook_receipts_received_at",
        table_name="douyin_webhook_receipts",
    )
    op.drop_table("douyin_webhook_receipts")
