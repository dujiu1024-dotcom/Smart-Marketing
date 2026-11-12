"""Add published work ownership, outcome and attribution evidence.

Revision ID: 0021_work_attribution_evidence
Revises: 0020_metric_import_batches
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0021_work_attribution_evidence"
down_revision: str | None = "0020_metric_import_batches"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "published_works",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("publish_operation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("channel_account_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("channel_key", sa.String(48), nullable=False),
        sa.Column("external_work_id", sa.String(200), nullable=False),
        sa.Column("title", sa.String(300), nullable=True),
        sa.Column("permalink", sa.String(2048), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ownership_status", sa.String(32), server_default="pending_verification", nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_snapshot_json", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("store_id", "id", name="uq_published_works_store_id"),
        sa.UniqueConstraint("store_id", "channel_key", "external_work_id", name="uq_published_works_store_channel_external"),
        sa.UniqueConstraint("store_id", "publish_operation_id", name="uq_published_works_store_publish_operation"),
        sa.ForeignKeyConstraint(["store_id", "task_id"], ["marketing_tasks.store_id", "marketing_tasks.id"], name="fk_published_works_task_same_store", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["store_id", "publish_operation_id"], ["publish_operations.store_id", "publish_operations.id"], name="fk_published_works_operation_same_store", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["store_id", "channel_account_id"], ["channel_accounts.store_id", "channel_accounts.id"], name="fk_published_works_account_same_store", ondelete="RESTRICT"),
        sa.CheckConstraint("ownership_status IN ('pending_verification', 'verified_system_publish', 'verified_platform_api', 'merchant_claim', 'rejected', 'revoked')", name="ck_published_works_ownership_status"),
        sa.CheckConstraint("ownership_status NOT IN ('verified_system_publish', 'verified_platform_api') OR verified_at IS NOT NULL", name="ck_published_works_verified_ownership_requires_timestamp"),
    )
    op.create_index("ix_published_works_store_channel_published", "published_works", ["store_id", "channel_key", "published_at"])

    op.create_table(
        "work_ownership_evidence",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("published_work_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("evidence_type", sa.String(32), nullable=False),
        sa.Column("evidence_status", sa.String(16), server_default="pending", nullable=False),
        sa.Column("source_system", sa.String(80), nullable=False),
        sa.Column("evidence_ref", sa.String(2048), nullable=True),
        sa.Column("evidence_payload_json", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("verified_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["store_id", "published_work_id"], ["published_works.store_id", "published_works.id"], name="fk_work_ownership_evidence_work_same_store", ondelete="RESTRICT"),
        sa.CheckConstraint("evidence_type IN ('system_publish_readback', 'platform_api', 'merchant_attestation', 'external_import')", name="ck_work_ownership_evidence_evidence_type"),
        sa.CheckConstraint("evidence_status IN ('pending', 'verified', 'rejected', 'revoked')", name="ck_work_ownership_evidence_evidence_status"),
    )
    op.create_index("ix_work_ownership_evidence_work_status", "work_ownership_evidence", ["store_id", "published_work_id", "evidence_status"])

    op.create_table(
        "business_outcome_evidence",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("outcome_type", sa.String(32), nullable=False),
        sa.Column("value_numeric", sa.Numeric(20, 6), nullable=False),
        sa.Column("currency", sa.String(3), nullable=True),
        sa.Column("source_system", sa.String(80), nullable=False),
        sa.Column("source_record_id", sa.String(300), nullable=True),
        sa.Column("source_evidence_ref", sa.String(2048), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("authenticity_status", sa.String(24), nullable=False),
        sa.Column("integrity_status", sa.String(16), server_default="unknown", nullable=False),
        sa.Column("deduplication_key", sa.String(64), nullable=False),
        sa.Column("imported_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("store_id", "id", name="uq_business_outcome_evidence_store_id"),
        sa.UniqueConstraint("store_id", "deduplication_key", name="uq_business_outcome_evidence_store_dedupe"),
        sa.CheckConstraint("outcome_type IN ('revenue', 'orders', 'redemptions', 'store_visits', 'leads')", name="ck_business_outcome_evidence_outcome_type"),
        sa.CheckConstraint("authenticity_status IN ('official_api', 'verified_import', 'merchant_reported', 'demo_sample')", name="ck_business_outcome_evidence_authenticity_status"),
        sa.CheckConstraint("integrity_status IN ('complete', 'partial', 'anomalous', 'unknown')", name="ck_business_outcome_evidence_integrity_status"),
        sa.CheckConstraint("value_numeric >= 0", name="ck_business_outcome_evidence_value_nonnegative"),
    )
    op.create_index("ix_business_outcome_evidence_store_occurred", "business_outcome_evidence", ["store_id", "occurred_at"])

    op.create_table(
        "attribution_evidence",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("marketing_task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("published_work_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("outcome_evidence_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attribution_method", sa.String(32), nullable=False),
        sa.Column("evidence_strength", sa.String(16), nullable=False),
        sa.Column("allocation_percent", sa.Numeric(5, 2), server_default="100", nullable=False),
        sa.Column("status", sa.String(16), server_default="active", nullable=False),
        sa.Column("attribution_snapshot_json", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("store_id", "outcome_evidence_id", "marketing_task_id", name="uq_attribution_evidence_store_outcome_task"),
        sa.ForeignKeyConstraint(["store_id", "marketing_task_id"], ["marketing_tasks.store_id", "marketing_tasks.id"], name="fk_attribution_evidence_task_same_store", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["store_id", "published_work_id"], ["published_works.store_id", "published_works.id"], name="fk_attribution_evidence_work_same_store", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["store_id", "outcome_evidence_id"], ["business_outcome_evidence.store_id", "business_outcome_evidence.id"], name="fk_attribution_evidence_outcome_same_store", ondelete="RESTRICT"),
        sa.CheckConstraint("attribution_method IN ('direct_code', 'platform_reported', 'temporal_association', 'manual_claim')", name="ck_attribution_evidence_attribution_method"),
        sa.CheckConstraint("evidence_strength IN ('strong', 'medium', 'weak')", name="ck_attribution_evidence_evidence_strength"),
        sa.CheckConstraint("status IN ('active', 'superseded', 'rejected')", name="ck_attribution_evidence_status"),
        sa.CheckConstraint("allocation_percent > 0 AND allocation_percent <= 100", name="ck_attribution_evidence_allocation_percent_range"),
    )
    op.create_index("ix_attribution_evidence_store_task_status", "attribution_evidence", ["store_id", "marketing_task_id", "status"])

    op.create_table(
        "data_source_capability_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("channel_key", sa.String(48), nullable=False),
        sa.Column("capability_key", sa.String(80), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("required_scopes_json", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("granted_scopes_json", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("evidence_ref", sa.String(2048), nullable=True),
        sa.Column("snapshot_version", sa.Integer(), nullable=False),
        sa.Column("snapshot_json", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("store_id", "channel_key", "capability_key", "snapshot_version", name="uq_data_source_capability_snapshot_version"),
        sa.CheckConstraint("status IN ('unsupported', 'pending', 'available', 'reauth_required', 'failed')", name="ck_data_source_capability_snapshots_status"),
    )
    op.create_index("ix_data_source_capability_snapshots_store_checked", "data_source_capability_snapshots", ["store_id", "checked_at"])

    op.add_column(
        "metric_observations",
        sa.Column("published_work_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "metric_observations",
        sa.Column("marketing_task_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_metric_observations_published_work_same_store",
        "metric_observations",
        "published_works",
        ["store_id", "published_work_id"],
        ["store_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_metric_observations_task_same_store",
        "metric_observations",
        "marketing_tasks",
        ["store_id", "marketing_task_id"],
        ["store_id", "id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint("fk_metric_observations_task_same_store", "metric_observations", type_="foreignkey")
    op.drop_constraint("fk_metric_observations_published_work_same_store", "metric_observations", type_="foreignkey")
    op.drop_column("metric_observations", "marketing_task_id")
    op.drop_column("metric_observations", "published_work_id")
    op.drop_index("ix_data_source_capability_snapshots_store_checked", table_name="data_source_capability_snapshots")
    op.drop_table("data_source_capability_snapshots")
    op.drop_index("ix_attribution_evidence_store_task_status", table_name="attribution_evidence")
    op.drop_table("attribution_evidence")
    op.drop_index("ix_business_outcome_evidence_store_occurred", table_name="business_outcome_evidence")
    op.drop_table("business_outcome_evidence")
    op.drop_index("ix_work_ownership_evidence_work_status", table_name="work_ownership_evidence")
    op.drop_table("work_ownership_evidence")
    op.drop_index("ix_published_works_store_channel_published", table_name="published_works")
    op.drop_table("published_works")
