"""Add immutable channel specifications and capability snapshots.

Revision ID: 0016_channel_specs
Revises: 0015_pubop_attempts
"""

from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016_channel_specs"
down_revision: str | None = "0015_pubop_attempts"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "channel_specs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("channel_key", sa.String(80), nullable=False),
        sa.Column("current_version_id", postgresql.UUID(as_uuid=True)),
        sa.Column("status", sa.String(16), server_default="active", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("channel_key", name="uq_channel_specs_channel_key"),
        sa.UniqueConstraint("id", "current_version_id", name="uq_channel_specs_current_version"),
        sa.CheckConstraint("status IN ('active', 'archived')", name="ck_channel_specs_status"),
        sa.CheckConstraint("length(trim(channel_key)) > 0", name="ck_channel_specs_channel_key_required"),
    )
    op.create_table(
        "channel_spec_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("channel_spec_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("spec_version", sa.Integer(), nullable=False),
        sa.Column("text_constraints_json", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("media_constraints_json", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("hashtag_constraints_json", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("link_constraints_json", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("schedule_constraints_json", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("draft_supported", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("publish_supported", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("verification_status", sa.String(32), server_default="pending_verification", nullable=False),
        sa.Column("source_document_ref", sa.Text()),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("channel_spec_id", "spec_version", name="uq_channel_spec_versions_spec_version"),
        sa.UniqueConstraint("channel_spec_id", "id", name="uq_channel_spec_versions_spec_id"),
        sa.ForeignKeyConstraint(["channel_spec_id"], ["channel_specs.id"], name="fk_channel_spec_versions_spec", ondelete="RESTRICT"),
        sa.CheckConstraint("spec_version >= 1", name="ck_channel_spec_versions_spec_version_positive"),
        sa.CheckConstraint("verification_status IN ('pending_verification', 'verified', 'deprecated')", name="ck_channel_spec_versions_verification_status"),
    )
    op.create_index(
        "ix_channel_spec_versions_spec_created",
        "channel_spec_versions",
        ["channel_spec_id", "created_at"],
    )

    # Preserve historical channel_spec_version_id values already referenced by content.
    op.execute(
        """
        INSERT INTO channel_specs (id, channel_key, status)
        SELECT gen_random_uuid(), channel_key, 'active'
        FROM (SELECT DISTINCT channel_key FROM channel_contents) AS existing
        ON CONFLICT (channel_key) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO channel_spec_versions (
            id, channel_spec_id, spec_version, verification_status,
            text_constraints_json, media_constraints_json,
            hashtag_constraints_json, link_constraints_json, schedule_constraints_json,
            draft_supported, publish_supported, created_at
        )
        SELECT
            existing.channel_spec_version_id,
            spec.id,
            ROW_NUMBER() OVER (
                PARTITION BY spec.id ORDER BY existing.channel_spec_version_id
            )::integer,
            'pending_verification',
            '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, '{}'::jsonb,
            false, false, now()
        FROM (
            SELECT DISTINCT channel_key, channel_spec_version_id
            FROM channel_contents
        ) AS existing
        JOIN channel_specs AS spec ON spec.channel_key = existing.channel_key
        ON CONFLICT (id) DO NOTHING
        """
    )
    op.execute(
        """
        UPDATE channel_specs AS spec
        SET current_version_id = latest.id,
            updated_at = now()
        FROM LATERAL (
            SELECT version.id
            FROM channel_spec_versions AS version
            WHERE version.channel_spec_id = spec.id
            ORDER BY version.spec_version DESC
            LIMIT 1
        ) AS latest
        """
    )

    # Seed a deliberately unverified Douyin baseline; it cannot be used to claim
    # official validation until source evidence and constraints are reviewed.
    connection = op.get_bind()
    existing_douyin = connection.execute(
        sa.text("SELECT id FROM channel_specs WHERE channel_key = 'douyin'")
    ).scalar_one_or_none()
    if existing_douyin is None:
        spec_id, version_id = uuid4(), uuid4()
        connection.execute(
            sa.text(
                "INSERT INTO channel_specs (id, channel_key, current_version_id, status) "
                "VALUES (:id, 'douyin', :version_id, 'active')"
            ),
            {"id": spec_id, "version_id": version_id},
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO channel_spec_versions (
                    id, channel_spec_id, spec_version, verification_status,
                    text_constraints_json, media_constraints_json,
                    hashtag_constraints_json, link_constraints_json, schedule_constraints_json,
                    draft_supported, publish_supported, source_document_ref
                ) VALUES (
                    :id, :spec_id, 1, 'pending_verification',
                    '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, '{}'::jsonb,
                    false, false, NULL
                )
                """
            ),
            {"id": version_id, "spec_id": spec_id},
        )

    op.create_foreign_key(
        "fk_channel_specs_current_version_same_spec",
        "channel_specs",
        "channel_spec_versions",
        ["id", "current_version_id"],
        ["channel_spec_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_channel_contents_spec_version",
        "channel_contents",
        "channel_spec_versions",
        ["channel_spec_version_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.create_table(
        "channel_capability_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("channel_account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("channel_spec_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("capability_key", sa.String(100), nullable=False),
        sa.Column("support_status", sa.String(32), server_default="pending_verification", nullable=False),
        sa.Column("evidence_ref", sa.String(2048)),
        sa.Column("reason", sa.String(1000)),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["store_id", "channel_account_id"],
            ["channel_accounts.store_id", "channel_accounts.id"],
            name="fk_channel_capability_snapshots_account_same_store",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["channel_spec_version_id"],
            ["channel_spec_versions.id"],
            name="fk_channel_capability_snapshots_spec_version",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "support_status IN ('supported', 'unsupported', 'pending_verification')",
            name="ck_channel_capability_snapshots_support_status",
        ),
        sa.CheckConstraint(
            "length(trim(capability_key)) > 0",
            name="ck_channel_capability_snapshots_capability_key_required",
        ),
    )
    op.create_index(
        "ix_channel_capability_snapshots_account_checked",
        "channel_capability_snapshots",
        ["store_id", "channel_account_id", "checked_at"],
    )
    op.create_index(
        "ix_channel_capability_snapshots_expiry",
        "channel_capability_snapshots",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_channel_capability_snapshots_expiry", table_name="channel_capability_snapshots")
    op.drop_index("ix_channel_capability_snapshots_account_checked", table_name="channel_capability_snapshots")
    op.drop_table("channel_capability_snapshots")
    op.drop_constraint("fk_channel_contents_spec_version", "channel_contents", type_="foreignkey")
    op.drop_constraint("fk_channel_specs_current_version_same_spec", "channel_specs", type_="foreignkey")
    op.drop_index("ix_channel_spec_versions_spec_created", table_name="channel_spec_versions")
    op.drop_table("channel_spec_versions")
    op.drop_table("channel_specs")
