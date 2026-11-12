"""Persist hot-topic matching algorithm version.

Revision ID: 0023_hot_topic_matcher_version
Revises: 0022_attribution_reversals
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023_hot_topic_matcher_version"
down_revision: str | None = "0022_attribution_reversals"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "store_opportunities",
        sa.Column(
            "matching_algorithm_version",
            sa.Integer(),
            server_default="2",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("store_opportunities", "matching_algorithm_version")
