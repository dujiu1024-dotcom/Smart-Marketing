"""Add immutable attribution snapshot version lineage.

Revision ID: 0024_attribution_snapshot_versions
Revises: 0023_hot_topic_matcher_version
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0024_attribution_snap_versions"
down_revision: str | None = "0023_hot_topic_matcher_version"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "attribution_evidence",
        sa.Column("attribution_version", sa.Integer(), server_default="1", nullable=False),
    )
    op.add_column(
        "attribution_evidence",
        sa.Column("supersedes_attribution_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_unique_constraint(
        "uq_attribution_evidence_store_id",
        "attribution_evidence",
        ["store_id", "id"],
    )
    op.create_unique_constraint(
        "uq_attribution_evidence_version",
        "attribution_evidence",
        ["store_id", "outcome_evidence_id", "marketing_task_id", "attribution_version"],
    )
    op.create_foreign_key(
        "fk_attribution_evidence_supersedes_same_store",
        "attribution_evidence",
        "attribution_evidence",
        ["store_id", "supersedes_attribution_id"],
        ["store_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_attribution_evidence_attribution_version_positive",
        "attribution_evidence",
        "attribution_version >= 1",
    )
    op.create_check_constraint(
        "ck_attribution_evidence_attribution_cannot_supersede_itself",
        "attribution_evidence",
        "supersedes_attribution_id IS NULL OR supersedes_attribution_id != id",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_attribution_evidence_attribution_cannot_supersede_itself",
        "attribution_evidence",
        type_="check",
    )
    op.drop_constraint(
        "ck_attribution_evidence_attribution_version_positive",
        "attribution_evidence",
        type_="check",
    )
    op.drop_constraint(
        "fk_attribution_evidence_supersedes_same_store",
        "attribution_evidence",
        type_="foreignkey",
    )
    op.drop_constraint(
        "uq_attribution_evidence_version",
        "attribution_evidence",
        type_="unique",
    )
    op.drop_constraint(
        "uq_attribution_evidence_store_id",
        "attribution_evidence",
        type_="unique",
    )
    op.drop_column("attribution_evidence", "supersedes_attribution_id")
    op.drop_column("attribution_evidence", "attribution_version")
