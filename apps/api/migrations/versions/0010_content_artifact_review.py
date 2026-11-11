"""Create immutable content artifact versions and review history.

Revision ID: 0010_content_artifact_review
Revises: 0009_task_step_block_details
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_content_artifact_review"
down_revision: str | None = "0009_task_step_block_details"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB


def upgrade() -> None:
    op.create_table(
        "artifacts",
        sa.Column("id", UUID, nullable=False),
        sa.Column("store_id", UUID, nullable=False),
        sa.Column("task_id", UUID, nullable=False),
        sa.Column("artifact_type", sa.String(length=16), nullable=False),
        sa.Column("current_version_id", UUID, nullable=True),
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
        sa.PrimaryKeyConstraint("id", name="pk_artifacts"),
        sa.UniqueConstraint("store_id", "id", name="uq_artifacts_store_id"),
        sa.ForeignKeyConstraint(
            ["store_id", "task_id"],
            ["marketing_tasks.store_id", "marketing_tasks.id"],
            name="fk_artifacts_task_same_store",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("artifact_type IN ('copy', 'image')", name="ck_artifacts_artifact_type"),
    )
    op.create_index(
        "ix_artifacts_store_task_type",
        "artifacts",
        ["store_id", "task_id", "artifact_type"],
    )

    op.create_table(
        "artifact_versions",
        sa.Column("id", UUID, nullable=False),
        sa.Column("store_id", UUID, nullable=False),
        sa.Column("artifact_id", UUID, nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(length=24), nullable=False),
        sa.Column("source_refs_json", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("instruction", sa.Text(), nullable=True),
        sa.Column("content_json", JSONB, nullable=True),
        sa.Column("content_ref", sa.String(length=700), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("provider_id", sa.String(length=100), nullable=True),
        sa.Column("model_id", sa.String(length=160), nullable=True),
        sa.Column("prompt_version_id", UUID, nullable=True),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("created_by_user_id", UUID, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_artifact_versions"),
        sa.UniqueConstraint(
            "store_id", "artifact_id", "version_no",
            name="uq_artifact_versions_artifact_version",
        ),
        sa.UniqueConstraint(
            "store_id", "artifact_id", "id",
            name="uq_artifact_versions_store_artifact_id",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "artifact_id"],
            ["artifacts.store_id", "artifacts.id"],
            name="fk_artifact_versions_artifact_same_store",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"],
            name="fk_artifact_versions_created_by_user_id_users",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint("version_no >= 1", name="ck_artifact_versions_version_no_positive"),
        sa.CheckConstraint(
            "source_type IN ('ai_generated', 'merchant_upload', 'manual_edit')",
            name="ck_artifact_versions_source_type",
        ),
        sa.CheckConstraint(
            "content_json IS NOT NULL OR content_ref IS NOT NULL",
            name="ck_artifact_versions_content_required",
        ),
    )
    op.create_index(
        "ix_artifact_versions_store_artifact_created",
        "artifact_versions",
        ["store_id", "artifact_id", "created_at"],
    )
    op.create_index(
        "ix_artifact_versions_input_fingerprint",
        "artifact_versions",
        ["store_id", "input_fingerprint"],
    )
    op.create_foreign_key(
        "fk_artifacts_current_version_same_artifact",
        "artifacts",
        "artifact_versions",
        ["store_id", "id", "current_version_id"],
        ["store_id", "artifact_id", "id"],
        deferrable=True,
        initially="DEFERRED",
    )

    op.create_table(
        "review_records",
        sa.Column("id", UUID, nullable=False),
        sa.Column("store_id", UUID, nullable=False),
        sa.Column("artifact_id", UUID, nullable=False),
        sa.Column("artifact_version_id", UUID, nullable=False),
        sa.Column("review_type", sa.String(length=16), nullable=False),
        sa.Column("decision", sa.String(length=24), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("target_json", JSONB, nullable=True),
        sa.Column("reviewer_user_id", UUID, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_review_records"),
        sa.UniqueConstraint("store_id", "id", name="uq_review_records_store_id"),
        sa.ForeignKeyConstraint(
            ["store_id", "artifact_id", "artifact_version_id"],
            ["artifact_versions.store_id", "artifact_versions.artifact_id", "artifact_versions.id"],
            name="fk_review_records_version_same_artifact",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reviewer_user_id"], ["users.id"],
            name="fk_review_records_reviewer_user_id_users",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "review_type IN ('copy', 'image')",
            name="ck_review_records_review_type",
        ),
        sa.CheckConstraint(
            "decision IN ('approved', 'revision_requested', 'rejected')",
            name="ck_review_records_decision",
        ),
        sa.CheckConstraint(
            (
                "decision <> 'revision_requested' OR "
                "(comment IS NOT NULL AND length(trim(comment)) > 0)"
            ),
            name="ck_review_records_revision_comment_required",
        ),
    )
    op.create_index(
        "ix_review_records_store_version_created",
        "review_records",
        ["store_id", "artifact_version_id", "created_at"],
    )
    op.create_index(
        "ix_review_records_store_artifact_created",
        "review_records",
        ["store_id", "artifact_id", "created_at"],
    )

    op.execute(
        """
        CREATE FUNCTION prevent_content_history_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'content history rows are append-only';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    for table in ("artifact_versions", "review_records"):
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_append_only
            BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION prevent_content_history_mutation();
            """
        )


def downgrade() -> None:
    for table in ("review_records", "artifact_versions"):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_append_only ON {table}")
    op.execute("DROP FUNCTION IF EXISTS prevent_content_history_mutation()")
    op.drop_index("ix_review_records_store_artifact_created", table_name="review_records")
    op.drop_index("ix_review_records_store_version_created", table_name="review_records")
    op.drop_table("review_records")
    op.drop_constraint(
        "fk_artifacts_current_version_same_artifact",
        "artifacts",
        type_="foreignkey",
    )
    op.drop_index("ix_artifact_versions_input_fingerprint", table_name="artifact_versions")
    op.drop_index("ix_artifact_versions_store_artifact_created", table_name="artifact_versions")
    op.drop_table("artifact_versions")
    op.drop_index("ix_artifacts_store_task_type", table_name="artifacts")
    op.drop_table("artifacts")
