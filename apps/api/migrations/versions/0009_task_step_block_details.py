"""Add structured block diagnostics to task steps.

Revision ID: 0009_task_step_block_details
Revises: 0008_marketing_task_core
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_task_step_block_details"
down_revision: str | None = "0008_marketing_task_core"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "task_steps",
        sa.Column("block_code", sa.String(length=60), nullable=True),
    )
    op.add_column(
        "task_steps",
        sa.Column(
            "block_detail_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("task_steps", "block_detail_json")
    op.drop_column("task_steps", "block_code")
