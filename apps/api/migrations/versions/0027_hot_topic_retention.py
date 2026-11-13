"""hot topic heat samples and retention runs

Revision ID: 0027_hot_topic_retention
Revises: 0026_hot_topic_source_fallback
Create Date: 2026-11-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0027_hot_topic_retention"
down_revision = "0026_hot_topic_source_fallback"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "hot_topics",
        sa.Column("first_heat_value", sa.Numeric(20, 6), nullable=True),
    )
    op.add_column(
        "hot_topics",
        sa.Column("last_heat_value", sa.Numeric(20, 6), nullable=True),
    )
    op.add_column(
        "hot_topics",
        sa.Column(
            "heat_sample_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )
    # 已有热点回填：把当前快照同时视为首次/末次热度。
    op.execute(
        sa.text(
            """
            UPDATE hot_topics
            SET first_heat_value = heat_value,
                last_heat_value = heat_value,
                heat_sample_count = CASE WHEN heat_value IS NULL THEN 0 ELSE 1 END
            """
        )
    )

    op.create_table(
        "hot_topic_heat_samples",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "hot_topic_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hot_topics.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("heat_value", sa.Numeric(20, 6), nullable=False),
    )
    op.create_index(
        "ix_hot_topic_heat_samples_topic_observed",
        "hot_topic_heat_samples",
        ["hot_topic_id", "observed_at"],
    )

    op.create_table(
        "hot_topic_retention_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("scanned", sa.Integer(), server_default="0", nullable=False),
        sa.Column("deleted", sa.Integer(), server_default="0", nullable=False),
        sa.Column("retired", sa.Integer(), server_default="0", nullable=False),
        sa.Column("kept", sa.Integer(), server_default="0", nullable=False),
        sa.Column("deleted_stale", sa.Integer(), server_default="0", nullable=False),
        sa.Column("deleted_trend", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_code", sa.String(64)),
        sa.Column("error_summary", sa.String(500)),
        sa.CheckConstraint(
            "status IN ('succeeded', 'failed')",
            name="ck_hot_topic_retention_runs_status",
        ),
    )


def downgrade() -> None:
    op.drop_table("hot_topic_retention_runs")
    op.drop_index(
        "ix_hot_topic_heat_samples_topic_observed",
        table_name="hot_topic_heat_samples",
    )
    op.drop_table("hot_topic_heat_samples")
    op.drop_column("hot_topics", "heat_sample_count")
    op.drop_column("hot_topics", "last_heat_value")
    op.drop_column("hot_topics", "first_heat_value")
