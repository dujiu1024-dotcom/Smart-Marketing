"""Track CSV metric import batches and file hashes.

Revision ID: 0020_metric_import_batches
Revises: 0019_metric_observation_corrections
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0020_metric_import_batches"
down_revision: str | None = "0019_metric_observation_corrections"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "metric_import_batches",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "store_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("stores.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("source_format", sa.String(16), nullable=False),
        sa.Column(
            "imported_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("created_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("skipped_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "store_id",
            "content_sha256",
            name="uq_metric_import_batches_store_hash",
        ),
        sa.CheckConstraint("row_count >= 0", name="ck_metric_import_batches_row_count_nonnegative"),
        sa.CheckConstraint("created_count >= 0", name="ck_metric_import_batches_created_count_nonnegative"),
        sa.CheckConstraint("skipped_count >= 0", name="ck_metric_import_batches_skipped_count_nonnegative"),
    )
    op.create_index(
        "ix_metric_import_batches_store_created",
        "metric_import_batches",
        ["store_id", "created_at"],
    )
    op.add_column(
        "metric_observations",
        sa.Column(
            "import_batch_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("metric_import_batches.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("metric_observations", "import_batch_id")
    op.drop_index(
        "ix_metric_import_batches_store_created",
        table_name="metric_import_batches",
    )
    op.drop_table("metric_import_batches")
