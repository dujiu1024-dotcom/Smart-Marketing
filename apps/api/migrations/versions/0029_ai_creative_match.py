"""AI creative rematch for hot topic opportunities

Revision ID: 0029_ai_creative_match
Revises: 0028_hot_topic_match
Create Date: 2026-11-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0029_ai_creative_match"
down_revision = "0028_hot_topic_match"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "store_opportunities",
        sa.Column("match_source", sa.String(16), server_default="rules", nullable=False),
    )
    op.add_column(
        "store_opportunities",
        sa.Column("ai_creative_json", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "store_opportunities",
        sa.Column("ai_confidence", sa.Numeric(4, 3), nullable=True),
    )
    op.add_column(
        "store_opportunities",
        sa.Column("ai_prompt_version", sa.String(40), nullable=True),
    )
    op.create_check_constraint(
        "match_source",
        "store_opportunities",
        "match_source IN ('rules', 'ai_creative')",
    )

    op.create_table(
        "hot_topic_ai_creative_cache",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "hot_topic_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hot_topics.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "store_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("stores.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("store_context_hash", sa.String(64), nullable=False),
        sa.Column("topic_content_hash", sa.String(64), nullable=False),
        sa.Column("prompt_version", sa.String(40), nullable=False),
        sa.Column("payload_json", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "hot_topic_id",
            "store_context_hash",
            "prompt_version",
            name="uq_hot_topic_ai_creative_cache_key",
        ),
    )
    op.create_index(
        "ix_hot_topic_ai_creative_cache_store",
        "hot_topic_ai_creative_cache",
        ["store_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_hot_topic_ai_creative_cache_store",
        table_name="hot_topic_ai_creative_cache",
    )
    op.drop_table("hot_topic_ai_creative_cache")
    op.drop_constraint("match_source", "store_opportunities", type_="check")
    op.drop_column("store_opportunities", "ai_prompt_version")
    op.drop_column("store_opportunities", "ai_confidence")
    op.drop_column("store_opportunities", "ai_creative_json")
    op.drop_column("store_opportunities", "match_source")
