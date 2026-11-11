"""Persistent idempotency keys for store-scoped mutations.

Revision ID: 0004_idempotency_records
Revises: 0003_store_knowledge
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_idempotency_records"
down_revision: str | None = "0003_store_knowledge"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "idempotency_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "store_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("stores.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("operation", sa.String(120), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), server_default="in_progress", nullable=False),
        sa.Column("response_status", sa.Integer()),
        sa.Column("response_json", postgresql.JSONB()),
        sa.Column("resource_type", sa.String(60)),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "store_id",
            "idempotency_key",
            name="uq_idempotency_records_store_key",
        ),
        sa.CheckConstraint(
            "status IN ('in_progress', 'completed')",
            name="ck_idempotency_records_status",
        ),
    )
    op.create_index(
        "ix_idempotency_records_expires_at",
        "idempotency_records",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_idempotency_records_expires_at",
        table_name="idempotency_records",
    )
    op.drop_table("idempotency_records")
