"""Add auditable attribution reversal fields and active-only uniqueness.

Revision ID: 0022_attribution_reversals
Revises: 0021_work_attribution_evidence
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0022_attribution_reversals"
down_revision: str | None = "0021_work_attribution_evidence"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("attribution_evidence", sa.Column("reversal_reason", sa.String(500)))
    op.add_column(
        "attribution_evidence",
        sa.Column("reversed_at", sa.DateTime(timezone=True)),
    )
    op.add_column(
        "attribution_evidence",
        sa.Column(
            "reversed_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
        ),
    )
    op.drop_constraint(
        "uq_attribution_evidence_store_outcome_task",
        "attribution_evidence",
        type_="unique",
    )
    op.create_index(
        "uq_attribution_evidence_active_outcome_task",
        "attribution_evidence",
        ["store_id", "outcome_evidence_id", "marketing_task_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_attribution_evidence_active_outcome_task",
        table_name="attribution_evidence",
    )
    op.create_unique_constraint(
        "uq_attribution_evidence_store_outcome_task",
        "attribution_evidence",
        ["store_id", "outcome_evidence_id", "marketing_task_id"],
    )
    op.drop_column("attribution_evidence", "reversed_by_user_id")
    op.drop_column("attribution_evidence", "reversed_at")
    op.drop_column("attribution_evidence", "reversal_reason")
