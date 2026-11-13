"""hot topic content hash and incremental match state

Revision ID: 0028_hot_topic_match
Revises: 0027_hot_topic_retention
Create Date: 2026-11-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0028_hot_topic_match"
down_revision = "0027_hot_topic_retention"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "hot_topics",
        sa.Column("content_hash", sa.String(64), server_default="", nullable=False),
    )
    # 历史热点按标题+摘要生成一次性哈希；新采集会写入与匹配器一致的 sha256。
    op.execute(
        sa.text(
            """
            UPDATE hot_topics
            SET content_hash = md5(title || '|' || coalesce(summary, ''))
            """
        )
    )

    op.create_table(
        "hot_topic_match_state",
        sa.Column(
            "store_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("stores.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "hot_topic_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hot_topics.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("topic_content_hash", sa.String(64), nullable=False),
        sa.Column("store_context_hash", sa.String(64), nullable=False),
        sa.Column("matched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("match_version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "match_version > 0", name="ck_hot_topic_match_state_match_version_positive"
        ),
    )
    op.create_index(
        "ix_hot_topic_match_state_store_context",
        "hot_topic_match_state",
        ["store_id", "store_context_hash"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_hot_topic_match_state_store_context",
        table_name="hot_topic_match_state",
    )
    op.drop_table("hot_topic_match_state")
    op.drop_column("hot_topics", "content_hash")
