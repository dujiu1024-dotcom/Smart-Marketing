"""hot topic source fallback and last error

Revision ID: 0026_hot_topic_source_fallback
Revises: 0025_metric_sync_cursors
Create Date: 2026-11-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0026_hot_topic_source_fallback"
down_revision = "0025_metric_sync_cursors"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "hot_topic_sources",
        sa.Column("fallback_url", sa.String(length=2048), nullable=True),
    )
    op.add_column(
        "hot_topic_sources",
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "hot_topic_sources",
        sa.Column("last_error_summary", sa.String(length=500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("hot_topic_sources", "last_error_summary")
    op.drop_column("hot_topic_sources", "last_error_code")
    op.drop_column("hot_topic_sources", "fallback_url")
