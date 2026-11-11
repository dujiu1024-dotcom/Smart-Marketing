"""Add channel content, quality and immutable multi-channel package snapshots.

Revision ID: 0012_content_quality_packages
Revises: 0011_prompt_versioning
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012_content_quality_packages"
down_revision: str | None = "0011_prompt_versioning"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_artifact_versions_store_id",
        "artifact_versions",
        ["store_id", "id"],
    )
    op.create_foreign_key(
        "fk_artifact_versions_prompt_version",
        "artifact_versions",
        "prompt_versions",
        ["prompt_version_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.create_table(
        "channel_contents",
        sa.Column("id", UUID, nullable=False),
        sa.Column("store_id", UUID, nullable=False),
        sa.Column("task_id", UUID, nullable=False),
        sa.Column("channel_key", sa.String(length=80), nullable=False),
        sa.Column("copy_version_id", UUID, nullable=False),
        sa.Column("payload_json", JSONB, nullable=False),
        sa.Column("channel_spec_version_id", UUID, nullable=False),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="ready", nullable=False),
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
        sa.PrimaryKeyConstraint("id", name="pk_channel_contents"),
        sa.UniqueConstraint("store_id", "id", name="uq_channel_contents_store_id"),
        sa.UniqueConstraint(
            "store_id", "task_id", "id",
            name="uq_channel_contents_store_task_id",
        ),
        sa.UniqueConstraint(
            "store_id", "id", "channel_key",
            name="uq_channel_contents_store_id_channel",
        ),
        sa.UniqueConstraint(
            "store_id", "channel_key", "input_fingerprint",
            name="uq_channel_contents_input_fingerprint",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "task_id"],
            ["marketing_tasks.store_id", "marketing_tasks.id"],
            name="fk_channel_contents_task_same_store",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "copy_version_id"],
            ["artifact_versions.store_id", "artifact_versions.id"],
            name="fk_channel_contents_copy_version_same_store",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "status IN ('ready', 'stale', 'blocked')",
            name="ck_channel_contents_status",
        ),
        sa.CheckConstraint(
            "length(trim(channel_key)) > 0",
            name="ck_channel_contents_channel_key_required",
        ),
        sa.CheckConstraint(
            "input_fingerprint ~ '^[0-9a-f]{64}
        sa.CheckConstraint(
            "input_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_channel_contents_input_fingerprint_sha256",
        ),
    )
    op.create_index(
        "ix_channel_contents_store_task_channel",
        "channel_contents",
        ["store_id", "task_id", "channel_key", "created_at"],
    )

    op.create_table(
        "channel_content_artifact_refs",
        sa.Column("id", UUID, nullable=False),
        sa.Column("store_id", UUID, nullable=False),
        sa.Column("channel_content_id", UUID, nullable=False),
        sa.Column("artifact_version_id", UUID, nullable=False),
        sa.Column("role", sa.String(length=16), server_default="image", nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_channel_content_artifact_refs"),
        sa.UniqueConstraint(
            "store_id", "channel_content_id", "position",
            name="uq_channel_content_artifact_refs_position",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "channel_content_id"],
            ["channel_contents.store_id", "channel_contents.id"],
            name="fk_channel_content_artifact_refs_content_same_store",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "artifact_version_id"],
            ["artifact_versions.store_id", "artifact_versions.id"],
            name="fk_channel_content_artifact_refs_version_same_store",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "role = 'image'",
            name="ck_channel_content_artifact_refs_role_image_only",
        ),
        sa.CheckConstraint(
            "position >= 0",
            name="ck_channel_content_artifact_refs_position_nonnegative",
        ),
    )
    op.create_index(
        "ix_channel_content_artifact_refs_content",
        "channel_content_artifact_refs",
        ["store_id", "channel_content_id", "position"],
    )

    op.create_table(
        "quality_reports",
        sa.Column("id", UUID, nullable=False),
        sa.Column("store_id", UUID, nullable=False),
        sa.Column("task_id", UUID, nullable=False),
        sa.Column("channel_content_id", UUID, nullable=False),
        sa.Column("rule_version", sa.String(length=80), nullable=False),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("result", sa.String(length=16), nullable=False),
        sa.Column("issues_json", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_quality_reports"),
        sa.UniqueConstraint("store_id", "id", name="uq_quality_reports_store_id"),
        sa.UniqueConstraint(
            "store_id", "id", "input_fingerprint",
            name="uq_quality_reports_store_id_fingerprint",
        ),
        sa.UniqueConstraint(
            "store_id", "channel_content_id", "id",
            name="uq_quality_reports_content_id",
        ),
        sa.UniqueConstraint(
            "store_id", "channel_content_id", "rule_version", "input_fingerprint",
            name="uq_quality_reports_content_rule_fingerprint",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "task_id", "channel_content_id"],
            ["channel_contents.store_id", "channel_contents.task_id", "channel_contents.id"],
            name="fk_quality_reports_channel_content_same_task_store",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "result IN ('pass', 'fail', 'needs_human')",
            name="ck_quality_reports_result",
        ),
        sa.CheckConstraint(
            "length(trim(rule_version)) > 0",
            name="ck_quality_reports_rule_version_required",
        ),
        sa.CheckConstraint(
            "input_fingerprint ~ '^[0-9a-f]{64}
        sa.CheckConstraint(
            "input_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_quality_reports_input_fingerprint_sha256",
        ),
    )
    op.create_index(
        "ix_quality_reports_store_content_created",
        "quality_reports",
        ["store_id", "channel_content_id", "created_at"],
    )

    op.create_table(
        "quality_resolutions",
        sa.Column("id", UUID, nullable=False),
        sa.Column("store_id", UUID, nullable=False),
        sa.Column("quality_report_id", UUID, nullable=False),
        sa.Column("quality_report_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("reviewer_user_id", UUID, nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_quality_resolutions"),
        sa.UniqueConstraint(
            "store_id", "quality_report_id", "quality_report_fingerprint",
            name="uq_quality_resolutions_report_fingerprint",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "quality_report_id", "quality_report_fingerprint"],
            ["quality_reports.store_id", "quality_reports.id", "quality_reports.input_fingerprint"],
            name="fk_quality_resolutions_report_fingerprint_same_store",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reviewer_user_id"], ["users.id"],
            name="fk_quality_resolutions_reviewer",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "decision IN ('accepted', 'rejected')",
            name="ck_quality_resolutions_decision",
        ),
        sa.CheckConstraint(
            "length(trim(reason)) > 0",
            name="ck_quality_resolutions_reason_required",
        ),
    )
    op.create_index(
        "ix_quality_resolutions_store_report_created",
        "quality_resolutions",
        ["store_id", "quality_report_id", "created_at"],
    )

    op.create_table(
        "publish_packages",
        sa.Column("id", UUID, nullable=False),
        sa.Column("store_id", UUID, nullable=False),
        sa.Column("task_id", UUID, nullable=False),
        sa.Column("package_version", sa.Integer(), nullable=False),
        sa.Column("package_fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "frozen_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("frozen_by_user_id", UUID, nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_publish_packages"),
        sa.UniqueConstraint(
            "store_id", "task_id", "package_version",
            name="uq_publish_packages_task_version",
        ),
        sa.UniqueConstraint(
            "store_id", "id",
            name="uq_publish_packages_store_id",
        ),
        sa.UniqueConstraint(
            "store_id", "id", "package_fingerprint",
            name="uq_publish_packages_store_id_fingerprint",
        ),
        sa.UniqueConstraint(
            "store_id", "task_id", "id",
            name="uq_publish_packages_store_task_id",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "task_id"],
            ["marketing_tasks.store_id", "marketing_tasks.id"],
            name="fk_publish_packages_task_same_store",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["frozen_by_user_id"], ["users.id"],
            name="fk_publish_packages_frozen_by_user",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "package_version >= 1",
            name="ck_publish_packages_package_version_positive",
        ),
        sa.CheckConstraint(
            "package_fingerprint ~ '^[0-9a-f]{64}
    )
    op.create_index(
        "ix_publish_packages_store_task_frozen",
        "publish_packages",
        ["store_id", "task_id", "frozen_at"],
    )

    op.create_table(
        "publish_package_items",
        sa.Column("id", UUID, nullable=False),
        sa.Column("store_id", UUID, nullable=False),
        sa.Column("publish_package_id", UUID, nullable=False),
        sa.Column("channel_key", sa.String(length=80), nullable=False),
        sa.Column("channel_content_id", UUID, nullable=False),
        sa.Column("quality_report_id", UUID, nullable=False),
        sa.Column("channel_account_id", UUID, nullable=True),
        sa.Column("delivery_mode", sa.String(length=24), nullable=False),
        sa.Column("planned_publish_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("item_fingerprint", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_publish_package_items"),
        sa.UniqueConstraint(
            "store_id", "publish_package_id", "channel_key",
            name="uq_publish_package_items_channel",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "publish_package_id"],
            ["publish_packages.store_id", "publish_packages.id"],
            name="fk_publish_package_items_package_same_store",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "channel_content_id", "channel_key"],
            ["channel_contents.store_id", "channel_contents.id", "channel_contents.channel_key"],
            name="fk_publish_package_items_channel_content_same_store",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "channel_content_id", "quality_report_id"],
            [
                "quality_reports.store_id",
                "quality_reports.channel_content_id",
                "quality_reports.id",
            ],
            name="fk_publish_package_items_quality_report_same_content",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "delivery_mode IN ('official_api', 'manual_handoff')",
            name="ck_publish_package_items_delivery_mode",
        ),
        sa.CheckConstraint(
            "(delivery_mode = 'official_api' AND channel_account_id IS NOT NULL) OR "
            "(delivery_mode = 'manual_handoff' AND channel_account_id IS NULL)",
            name="ck_publish_package_items_channel_account_matches_delivery_mode",
        ),
        sa.CheckConstraint(
            "item_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_publish_package_items_item_fingerprint_sha256",
        ),
    )
    op.create_index(
        "ix_publish_package_items_store_package",
        "publish_package_items",
        ["store_id", "publish_package_id"],
    )

    op.create_table(
        "publish_package_fact_refs",
        sa.Column("id", UUID, nullable=False),
        sa.Column("store_id", UUID, nullable=False),
        sa.Column("task_id", UUID, nullable=False),
        sa.Column("publish_package_id", UUID, nullable=False),
        sa.Column("business_fact_snapshot_id", UUID, nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_publish_package_fact_refs"),
        sa.UniqueConstraint(
            "store_id", "publish_package_id", "position",
            name="uq_publish_package_fact_refs_position",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "task_id", "publish_package_id"],
            ["publish_packages.store_id", "publish_packages.task_id", "publish_packages.id"],
            name="fk_publish_package_fact_refs_package_same_task",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "task_id", "business_fact_snapshot_id"],
            [
                "business_fact_snapshots.store_id",
                "business_fact_snapshots.task_id",
                "business_fact_snapshots.id",
            ],
            name="fk_publish_package_fact_refs_fact_same_task",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "position >= 0",
            name="ck_publish_package_fact_refs_position_nonnegative",
        ),
    )
    op.create_index(
        "ix_publish_package_fact_refs_store_package",
        "publish_package_fact_refs",
        ["store_id", "publish_package_id"],
    )

    op.create_table(
        "publish_confirmations",
        sa.Column("id", UUID, nullable=False),
        sa.Column("store_id", UUID, nullable=False),
        sa.Column("publish_package_id", UUID, nullable=False),
        sa.Column("package_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("confirmed_by_user_id", UUID, nullable=False),
        sa.Column(
            "confirmed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("confirmation_note", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_publish_confirmations"),
        sa.UniqueConstraint(
            "store_id", "publish_package_id", "package_fingerprint",
            name="uq_publish_confirmations_package_fingerprint",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "publish_package_id", "package_fingerprint"],
            [
                "publish_packages.store_id",
                "publish_packages.id",
                "publish_packages.package_fingerprint",
            ],
            name="fk_publish_confirmations_package_fingerprint_same_store",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["confirmed_by_user_id"], ["users.id"],
            name="fk_publish_confirmations_user",
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_publish_confirmations_store_package_created",
        "publish_confirmations",
        ["store_id", "publish_package_id", "confirmed_at"],
    )

    op.execute(
        """
        CREATE FUNCTION prevent_content_delivery_append_only_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    append_only_tables = (
        "artifact_versions",
        "review_records",
        "channel_content_artifact_refs",
        "quality_reports",
        "quality_resolutions",
        "publish_packages",
        "publish_package_items",
        "publish_package_fact_refs",
        "publish_confirmations",
    )
    for table in append_only_tables:
        op.execute(
            f"CREATE TRIGGER trg_{table}_append_only "
            f"BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION "
            "prevent_content_delivery_append_only_mutation()"
        )

    op.execute(
        """
        CREATE FUNCTION protect_channel_content_snapshot() RETURNS trigger AS $$
        BEGIN
            IF (to_jsonb(NEW) - ARRAY['status', 'updated_at'])
               IS DISTINCT FROM
               (to_jsonb(OLD) - ARRAY['status', 'updated_at']) THEN
                RAISE EXCEPTION 'channel content snapshot fields are immutable';
            END IF;
            IF OLD.status IN ('stale', 'blocked') AND NEW.status <> OLD.status THEN
                RAISE EXCEPTION 'stale or blocked channel content cannot be reactivated';
            END IF;
            IF NEW.status NOT IN ('ready', 'stale', 'blocked') THEN
                RAISE EXCEPTION 'invalid channel content status';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_channel_contents_snapshot_protected
        BEFORE UPDATE ON channel_contents
        FOR EACH ROW EXECUTE FUNCTION protect_channel_content_snapshot();
        """
    )

    op.execute(
        """
        CREATE FUNCTION enforce_channel_content_reviewed_versions() RETURNS trigger AS $$
        DECLARE
            artifact_type text;
        BEGIN
            SELECT a.artifact_type INTO artifact_type
            FROM artifact_versions av
            JOIN artifacts a
              ON a.store_id = av.store_id AND a.id = av.artifact_id
            WHERE av.store_id = NEW.store_id
              AND av.id = NEW.copy_version_id;
            IF artifact_type IS DISTINCT FROM 'copy' THEN
                RAISE EXCEPTION 'channel content requires a copy artifact version';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM review_records rr
                WHERE rr.store_id = NEW.store_id
                  AND rr.artifact_version_id = NEW.copy_version_id
                  AND rr.review_type = 'copy'
                  AND rr.decision = 'approved'
            ) THEN
                RAISE EXCEPTION 'channel content requires an approved copy version';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_channel_contents_require_approved_copy
        BEFORE INSERT ON channel_contents
        FOR EACH ROW EXECUTE FUNCTION enforce_channel_content_reviewed_versions();
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_channel_content_image_refs() RETURNS trigger AS $$
        DECLARE
            artifact_type text;
        BEGIN
            SELECT a.artifact_type INTO artifact_type
            FROM artifact_versions av
            JOIN artifacts a
              ON a.store_id = av.store_id AND a.id = av.artifact_id
            WHERE av.store_id = NEW.store_id
              AND av.id = NEW.artifact_version_id;
            IF artifact_type IS DISTINCT FROM 'image' THEN
                RAISE EXCEPTION
                    'channel content image reference requires an image artifact version';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM review_records rr
                WHERE rr.store_id = NEW.store_id
                  AND rr.artifact_version_id = NEW.artifact_version_id
                  AND rr.review_type = 'image'
                  AND rr.decision = 'approved'
            ) THEN
                RAISE EXCEPTION
                    'channel content image reference requires an approved image version';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_channel_content_artifact_refs_require_approved_image
        BEFORE INSERT ON channel_content_artifact_refs
        FOR EACH ROW EXECUTE FUNCTION enforce_channel_content_image_refs();
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_quality_resolution_needs_human() RETURNS trigger AS $$
        DECLARE
            report_result text;
        BEGIN
            SELECT result INTO report_result
            FROM quality_reports
            WHERE store_id = NEW.store_id
              AND id = NEW.quality_report_id
              AND input_fingerprint = NEW.quality_report_fingerprint;
            IF report_result IS DISTINCT FROM 'needs_human' THEN
                RAISE EXCEPTION 'only needs_human quality reports can be resolved';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_quality_resolutions_needs_human_only
        BEFORE INSERT ON quality_resolutions
        FOR EACH ROW EXECUTE FUNCTION enforce_quality_resolution_needs_human();
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_publish_package_item_quality_gate() RETURNS trigger AS $$
        DECLARE
            report_result text;
            report_fingerprint text;
        BEGIN
            SELECT result, input_fingerprint
              INTO report_result, report_fingerprint
            FROM quality_reports
            WHERE store_id = NEW.store_id
              AND channel_content_id = NEW.channel_content_id
              AND id = NEW.quality_report_id;
            IF report_result = 'fail' OR report_result IS NULL THEN
                RAISE EXCEPTION 'publish package requires a passing or accepted quality report';
            END IF;
            IF report_result = 'needs_human' AND NOT EXISTS (
                SELECT 1 FROM quality_resolutions qr
                WHERE qr.store_id = NEW.store_id
                  AND qr.quality_report_id = NEW.quality_report_id
                  AND qr.quality_report_fingerprint = report_fingerprint
                  AND qr.decision = 'accepted'
            ) THEN
                RAISE EXCEPTION 'quality report requires an accepted human resolution';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_publish_package_items_quality_gate
        BEFORE INSERT ON publish_package_items
        FOR EACH ROW EXECUTE FUNCTION enforce_publish_package_item_quality_gate();
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_publish_package_confirmed_facts() RETURNS trigger AS $$
        DECLARE
            fact_status text;
        BEGIN
            SELECT confirmation_status INTO fact_status
            FROM business_fact_snapshots
            WHERE store_id = NEW.store_id
              AND task_id = NEW.task_id
              AND id = NEW.business_fact_snapshot_id;
            IF fact_status IS DISTINCT FROM 'confirmed' THEN
                RAISE EXCEPTION 'publish package facts must be confirmed';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_publish_package_fact_refs_confirmed_only
        BEFORE INSERT ON publish_package_fact_refs
        FOR EACH ROW EXECUTE FUNCTION enforce_publish_package_confirmed_facts();
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_publish_package_complete() RETURNS trigger AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM publish_package_items
                WHERE store_id = NEW.store_id
                  AND publish_package_id = NEW.id
            ) THEN
                RAISE EXCEPTION 'publish package requires at least one item';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM publish_package_fact_refs
                WHERE store_id = NEW.store_id
                  AND publish_package_id = NEW.id
            ) THEN
                RAISE EXCEPTION 'publish package requires confirmed business facts';
            END IF;
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER trg_publish_packages_complete
        AFTER INSERT ON publish_packages
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION enforce_publish_package_complete();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_publish_packages_complete ON publish_packages")
    op.execute("DROP FUNCTION IF EXISTS enforce_publish_package_complete()")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_publish_package_fact_refs_confirmed_only "
        "ON publish_package_fact_refs"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_publish_package_confirmed_facts()")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_publish_package_items_quality_gate "
        "ON publish_package_items"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_publish_package_item_quality_gate()")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_quality_resolutions_needs_human_only "
        "ON quality_resolutions"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_quality_resolution_needs_human()")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_channel_content_artifact_refs_require_approved_image "
        "ON channel_content_artifact_refs"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_channel_content_image_refs()")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_channel_contents_require_approved_copy "
        "ON channel_contents"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_channel_content_reviewed_versions()")
    op.execute("DROP TRIGGER IF EXISTS trg_channel_contents_snapshot_protected ON channel_contents")
    op.execute("DROP FUNCTION IF EXISTS protect_channel_content_snapshot()")
    for table in (
        "artifact_versions",
        "review_records",
        "channel_content_artifact_refs",
        "quality_reports",
        "quality_resolutions",
        "publish_packages",
        "publish_package_items",
        "publish_package_fact_refs",
        "publish_confirmations",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_append_only ON {table}")
    op.execute("DROP FUNCTION IF EXISTS prevent_content_delivery_append_only_mutation()")

    op.drop_index(
        "ix_publish_confirmations_store_package_created",
        table_name="publish_confirmations",
    )
    op.drop_table("publish_confirmations")
    op.drop_index(
        "ix_publish_package_fact_refs_store_package",
        table_name="publish_package_fact_refs",
    )
    op.drop_table("publish_package_fact_refs")
    op.drop_index("ix_publish_package_items_store_package", table_name="publish_package_items")
    op.drop_table("publish_package_items")
    op.drop_index("ix_publish_packages_store_task_frozen", table_name="publish_packages")
    op.drop_table("publish_packages")
    op.drop_index("ix_quality_resolutions_store_report_created", table_name="quality_resolutions")
    op.drop_table("quality_resolutions")
    op.drop_index("ix_quality_reports_store_content_created", table_name="quality_reports")
    op.drop_table("quality_reports")
    op.drop_index(
        "ix_channel_content_artifact_refs_content",
        table_name="channel_content_artifact_refs",
    )
    op.drop_table("channel_content_artifact_refs")
    op.drop_index("ix_channel_contents_store_task_channel", table_name="channel_contents")
    op.drop_table("channel_contents")
    op.drop_constraint(
        "fk_artifact_versions_prompt_version",
        "artifact_versions",
        type_="foreignkey",
    )
    op.drop_constraint(
        "uq_publish_packages_store_id",
        "publish_packages",
        type_="unique",
    )
    op.drop_constraint(
        "uq_artifact_versions_store_id",
        "artifact_versions",
        type_="unique",
    )
",
            name="ck_channel_contents_input_fingerprint_sha256",
        ),
        sa.CheckConstraint(
            "input_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_channel_contents_input_fingerprint_sha256",
        ),
    )
    op.create_index(
        "ix_channel_contents_store_task_channel",
        "channel_contents",
        ["store_id", "task_id", "channel_key", "created_at"],
    )

    op.create_table(
        "channel_content_artifact_refs",
        sa.Column("id", UUID, nullable=False),
        sa.Column("store_id", UUID, nullable=False),
        sa.Column("channel_content_id", UUID, nullable=False),
        sa.Column("artifact_version_id", UUID, nullable=False),
        sa.Column("role", sa.String(length=16), server_default="image", nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_channel_content_artifact_refs"),
        sa.UniqueConstraint(
            "store_id", "channel_content_id", "position",
            name="uq_channel_content_artifact_refs_position",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "channel_content_id"],
            ["channel_contents.store_id", "channel_contents.id"],
            name="fk_channel_content_artifact_refs_content_same_store",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "artifact_version_id"],
            ["artifact_versions.store_id", "artifact_versions.id"],
            name="fk_channel_content_artifact_refs_version_same_store",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("role = 'image'", name="ck_channel_content_artifact_refs_role_image_only"),
        sa.CheckConstraint("position >= 0", name="ck_channel_content_artifact_refs_position_nonnegative"),
    )
    op.create_index(
        "ix_channel_content_artifact_refs_content",
        "channel_content_artifact_refs",
        ["store_id", "channel_content_id", "position"],
    )

    op.create_table(
        "quality_reports",
        sa.Column("id", UUID, nullable=False),
        sa.Column("store_id", UUID, nullable=False),
        sa.Column("task_id", UUID, nullable=False),
        sa.Column("channel_content_id", UUID, nullable=False),
        sa.Column("rule_version", sa.String(length=80), nullable=False),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("result", sa.String(length=16), nullable=False),
        sa.Column("issues_json", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_quality_reports"),
        sa.UniqueConstraint("store_id", "id", name="uq_quality_reports_store_id"),
        sa.UniqueConstraint(
            "store_id", "id", "input_fingerprint",
            name="uq_quality_reports_store_id_fingerprint",
        ),
        sa.UniqueConstraint(
            "store_id", "channel_content_id", "id",
            name="uq_quality_reports_content_id",
        ),
        sa.UniqueConstraint(
            "store_id", "channel_content_id", "rule_version", "input_fingerprint",
            name="uq_quality_reports_content_rule_fingerprint",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "task_id", "channel_content_id"],
            ["channel_contents.store_id", "channel_contents.task_id", "channel_contents.id"],
            name="fk_quality_reports_channel_content_same_task_store",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "result IN ('pass', 'fail', 'needs_human')",
            name="ck_quality_reports_result",
        ),
        sa.CheckConstraint(
            "length(trim(rule_version)) > 0",
            name="ck_quality_reports_rule_version_required",
        ),
        sa.CheckConstraint(
            "input_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_quality_reports_input_fingerprint_sha256",
        ),
    )
    op.create_index(
        "ix_quality_reports_store_content_created",
        "quality_reports",
        ["store_id", "channel_content_id", "created_at"],
    )

    op.create_table(
        "quality_resolutions",
        sa.Column("id", UUID, nullable=False),
        sa.Column("store_id", UUID, nullable=False),
        sa.Column("quality_report_id", UUID, nullable=False),
        sa.Column("quality_report_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("reviewer_user_id", UUID, nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_quality_resolutions"),
        sa.UniqueConstraint(
            "store_id", "quality_report_id", "quality_report_fingerprint",
            name="uq_quality_resolutions_report_fingerprint",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "quality_report_id", "quality_report_fingerprint"],
            ["quality_reports.store_id", "quality_reports.id", "quality_reports.input_fingerprint"],
            name="fk_quality_resolutions_report_fingerprint_same_store",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reviewer_user_id"], ["users.id"],
            name="fk_quality_resolutions_reviewer",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "decision IN ('accepted', 'rejected')",
            name="ck_quality_resolutions_decision",
        ),
        sa.CheckConstraint(
            "length(trim(reason)) > 0",
            name="ck_quality_resolutions_reason_required",
        ),
    )
    op.create_index(
        "ix_quality_resolutions_store_report_created",
        "quality_resolutions",
        ["store_id", "quality_report_id", "created_at"],
    )

    op.create_table(
        "publish_packages",
        sa.Column("id", UUID, nullable=False),
        sa.Column("store_id", UUID, nullable=False),
        sa.Column("task_id", UUID, nullable=False),
        sa.Column("package_version", sa.Integer(), nullable=False),
        sa.Column("package_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("frozen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("frozen_by_user_id", UUID, nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_publish_packages"),
        sa.UniqueConstraint(
            "store_id", "task_id", "package_version",
            name="uq_publish_packages_task_version",
        ),
        sa.UniqueConstraint(
            "store_id", "id", "package_fingerprint",
            name="uq_publish_packages_store_id_fingerprint",
        ),
        sa.UniqueConstraint(
            "store_id", "task_id", "id",
            name="uq_publish_packages_store_task_id",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "task_id"],
            ["marketing_tasks.store_id", "marketing_tasks.id"],
            name="fk_publish_packages_task_same_store",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["frozen_by_user_id"], ["users.id"],
            name="fk_publish_packages_frozen_by_user",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint("package_version >= 1", name="ck_publish_packages_package_version_positive"),
        sa.CheckConstraint(
            "package_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_publish_packages_fingerprint_sha256",
        ),
    )
    op.create_index(
        "ix_publish_packages_store_task_frozen",
        "publish_packages",
        ["store_id", "task_id", "frozen_at"],
    )

    op.create_table(
        "publish_package_items",
        sa.Column("id", UUID, nullable=False),
        sa.Column("store_id", UUID, nullable=False),
        sa.Column("publish_package_id", UUID, nullable=False),
        sa.Column("channel_key", sa.String(length=80), nullable=False),
        sa.Column("channel_content_id", UUID, nullable=False),
        sa.Column("quality_report_id", UUID, nullable=False),
        sa.Column("channel_account_id", UUID, nullable=True),
        sa.Column("delivery_mode", sa.String(length=24), nullable=False),
        sa.Column("planned_publish_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("item_fingerprint", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_publish_package_items"),
        sa.UniqueConstraint(
            "store_id", "publish_package_id", "channel_key",
            name="uq_publish_package_items_channel",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "publish_package_id"],
            ["publish_packages.store_id", "publish_packages.id"],
            name="fk_publish_package_items_package_same_store",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "channel_content_id", "channel_key"],
            ["channel_contents.store_id", "channel_contents.id", "channel_contents.channel_key"],
            name="fk_publish_package_items_channel_content_same_store",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "channel_content_id", "quality_report_id"],
            ["quality_reports.store_id", "quality_reports.channel_content_id", "quality_reports.id"],
            name="fk_publish_package_items_quality_report_same_content",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "delivery_mode IN ('official_api', 'manual_handoff')",
            name="ck_publish_package_items_delivery_mode",
        ),
        sa.CheckConstraint(
            "(delivery_mode = 'official_api' AND channel_account_id IS NOT NULL) OR "
            "(delivery_mode = 'manual_handoff' AND channel_account_id IS NULL)",
            name="ck_publish_package_items_channel_account_matches_delivery_mode",
        ),
        sa.CheckConstraint(
            "item_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_publish_package_items_item_fingerprint_sha256",
        ),
    )
    op.create_index(
        "ix_publish_package_items_store_package",
        "publish_package_items",
        ["store_id", "publish_package_id"],
    )

    op.create_table(
        "publish_package_fact_refs",
        sa.Column("id", UUID, nullable=False),
        sa.Column("store_id", UUID, nullable=False),
        sa.Column("task_id", UUID, nullable=False),
        sa.Column("publish_package_id", UUID, nullable=False),
        sa.Column("business_fact_snapshot_id", UUID, nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_publish_package_fact_refs"),
        sa.UniqueConstraint(
            "store_id", "publish_package_id", "position",
            name="uq_publish_package_fact_refs_position",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "task_id", "publish_package_id"],
            ["publish_packages.store_id", "publish_packages.task_id", "publish_packages.id"],
            name="fk_publish_package_fact_refs_package_same_task",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "task_id", "business_fact_snapshot_id"],
            ["business_fact_snapshots.store_id", "business_fact_snapshots.task_id", "business_fact_snapshots.id"],
            name="fk_publish_package_fact_refs_fact_same_task",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("position >= 0", name="ck_publish_package_fact_refs_position_nonnegative"),
    )
    op.create_index(
        "ix_publish_package_fact_refs_store_package",
        "publish_package_fact_refs",
        ["store_id", "publish_package_id"],
    )

    op.create_table(
        "publish_confirmations",
        sa.Column("id", UUID, nullable=False),
        sa.Column("store_id", UUID, nullable=False),
        sa.Column("publish_package_id", UUID, nullable=False),
        sa.Column("package_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("confirmed_by_user_id", UUID, nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("confirmation_note", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_publish_confirmations"),
        sa.UniqueConstraint(
            "store_id", "publish_package_id", "package_fingerprint",
            name="uq_publish_confirmations_package_fingerprint",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "publish_package_id", "package_fingerprint"],
            ["publish_packages.store_id", "publish_packages.id", "publish_packages.package_fingerprint"],
            name="fk_publish_confirmations_package_fingerprint_same_store",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["confirmed_by_user_id"], ["users.id"],
            name="fk_publish_confirmations_user",
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_publish_confirmations_store_package_created",
        "publish_confirmations",
        ["store_id", "publish_package_id", "confirmed_at"],
    )

    op.execute(
        """
        CREATE FUNCTION prevent_content_delivery_append_only_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    append_only_tables = (
        "artifact_versions",
        "review_records",
        "channel_content_artifact_refs",
        "quality_reports",
        "quality_resolutions",
        "publish_packages",
        "publish_package_items",
        "publish_package_fact_refs",
        "publish_confirmations",
    )
    for table in append_only_tables:
        op.execute(
            f"CREATE TRIGGER trg_{table}_append_only "
            f"BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION "
            "prevent_content_delivery_append_only_mutation()"
        )

    op.execute(
        """
        CREATE FUNCTION protect_channel_content_snapshot() RETURNS trigger AS $$
        BEGIN
            IF (to_jsonb(NEW) - ARRAY['status', 'updated_at'])
               IS DISTINCT FROM
               (to_jsonb(OLD) - ARRAY['status', 'updated_at']) THEN
                RAISE EXCEPTION 'channel content snapshot fields are immutable';
            END IF;
            IF OLD.status IN ('stale', 'blocked') AND NEW.status <> OLD.status THEN
                RAISE EXCEPTION 'stale or blocked channel content cannot be reactivated';
            END IF;
            IF NEW.status NOT IN ('ready', 'stale', 'blocked') THEN
                RAISE EXCEPTION 'invalid channel content status';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_channel_contents_snapshot_protected
        BEFORE UPDATE ON channel_contents
        FOR EACH ROW EXECUTE FUNCTION protect_channel_content_snapshot();
        """
    )

    op.execute(
        """
        CREATE FUNCTION enforce_channel_content_reviewed_versions() RETURNS trigger AS $$
        DECLARE
            artifact_type text;
        BEGIN
            SELECT a.artifact_type INTO artifact_type
            FROM artifact_versions av
            JOIN artifacts a
              ON a.store_id = av.store_id AND a.id = av.artifact_id
            WHERE av.store_id = NEW.store_id
              AND av.id = NEW.copy_version_id;
            IF artifact_type IS DISTINCT FROM 'copy' THEN
                RAISE EXCEPTION 'channel content requires a copy artifact version';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM review_records rr
                WHERE rr.store_id = NEW.store_id
                  AND rr.artifact_version_id = NEW.copy_version_id
                  AND rr.review_type = 'copy'
                  AND rr.decision = 'approved'
            ) THEN
                RAISE EXCEPTION 'channel content requires an approved copy version';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_channel_contents_require_approved_copy
        BEFORE INSERT ON channel_contents
        FOR EACH ROW EXECUTE FUNCTION enforce_channel_content_reviewed_versions();
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_channel_content_image_refs() RETURNS trigger AS $$
        DECLARE
            artifact_type text;
        BEGIN
            SELECT a.artifact_type INTO artifact_type
            FROM artifact_versions av
            JOIN artifacts a
              ON a.store_id = av.store_id AND a.id = av.artifact_id
            WHERE av.store_id = NEW.store_id
              AND av.id = NEW.artifact_version_id;
            IF artifact_type IS DISTINCT FROM 'image' THEN
                RAISE EXCEPTION 'channel content image reference requires an image artifact version';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM review_records rr
                WHERE rr.store_id = NEW.store_id
                  AND rr.artifact_version_id = NEW.artifact_version_id
                  AND rr.review_type = 'image'
                  AND rr.decision = 'approved'
            ) THEN
                RAISE EXCEPTION 'channel content image reference requires an approved image version';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_channel_content_artifact_refs_require_approved_image
        BEFORE INSERT ON channel_content_artifact_refs
        FOR EACH ROW EXECUTE FUNCTION enforce_channel_content_image_refs();
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_quality_resolution_needs_human() RETURNS trigger AS $$
        DECLARE
            report_result text;
        BEGIN
            SELECT result INTO report_result
            FROM quality_reports
            WHERE store_id = NEW.store_id
              AND id = NEW.quality_report_id
              AND input_fingerprint = NEW.quality_report_fingerprint;
            IF report_result IS DISTINCT FROM 'needs_human' THEN
                RAISE EXCEPTION 'only needs_human quality reports can be resolved';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_quality_resolutions_needs_human_only
        BEFORE INSERT ON quality_resolutions
        FOR EACH ROW EXECUTE FUNCTION enforce_quality_resolution_needs_human();
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_publish_package_item_quality_gate() RETURNS trigger AS $$
        DECLARE
            report_result text;
            report_fingerprint text;
        BEGIN
            SELECT result, input_fingerprint
              INTO report_result, report_fingerprint
            FROM quality_reports
            WHERE store_id = NEW.store_id
              AND channel_content_id = NEW.channel_content_id
              AND id = NEW.quality_report_id;
            IF report_result = 'fail' OR report_result IS NULL THEN
                RAISE EXCEPTION 'publish package requires a passing or accepted quality report';
            END IF;
            IF report_result = 'needs_human' AND NOT EXISTS (
                SELECT 1 FROM quality_resolutions qr
                WHERE qr.store_id = NEW.store_id
                  AND qr.quality_report_id = NEW.quality_report_id
                  AND qr.quality_report_fingerprint = report_fingerprint
                  AND qr.decision = 'accepted'
            ) THEN
                RAISE EXCEPTION 'quality report requires an accepted human resolution';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_publish_package_items_quality_gate
        BEFORE INSERT ON publish_package_items
        FOR EACH ROW EXECUTE FUNCTION enforce_publish_package_item_quality_gate();
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_publish_package_confirmed_facts() RETURNS trigger AS $$
        DECLARE
            fact_status text;
        BEGIN
            SELECT confirmation_status INTO fact_status
            FROM business_fact_snapshots
            WHERE store_id = NEW.store_id
              AND task_id = NEW.task_id
              AND id = NEW.business_fact_snapshot_id;
            IF fact_status IS DISTINCT FROM 'confirmed' THEN
                RAISE EXCEPTION 'publish package facts must be confirmed';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_publish_package_fact_refs_confirmed_only
        BEFORE INSERT ON publish_package_fact_refs
        FOR EACH ROW EXECUTE FUNCTION enforce_publish_package_confirmed_facts();
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_publish_package_complete() RETURNS trigger AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM publish_package_items
                WHERE store_id = NEW.store_id
                  AND publish_package_id = NEW.id
            ) THEN
                RAISE EXCEPTION 'publish package requires at least one item';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM publish_package_fact_refs
                WHERE store_id = NEW.store_id
                  AND publish_package_id = NEW.id
            ) THEN
                RAISE EXCEPTION 'publish package requires confirmed business facts';
            END IF;
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER trg_publish_packages_complete
        AFTER INSERT ON publish_packages
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION enforce_publish_package_complete();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_publish_packages_complete ON publish_packages")
    op.execute("DROP FUNCTION IF EXISTS enforce_publish_package_complete()")
    op.execute("DROP TRIGGER IF EXISTS trg_publish_package_fact_refs_confirmed_only ON publish_package_fact_refs")
    op.execute("DROP FUNCTION IF EXISTS enforce_publish_package_confirmed_facts()")
    op.execute("DROP TRIGGER IF EXISTS trg_publish_package_items_quality_gate ON publish_package_items")
    op.execute("DROP FUNCTION IF EXISTS enforce_publish_package_item_quality_gate()")
    op.execute("DROP TRIGGER IF EXISTS trg_quality_resolutions_needs_human_only ON quality_resolutions")
    op.execute("DROP FUNCTION IF EXISTS enforce_quality_resolution_needs_human()")
    op.execute("DROP TRIGGER IF EXISTS trg_channel_content_artifact_refs_require_approved_image ON channel_content_artifact_refs")
    op.execute("DROP FUNCTION IF EXISTS enforce_channel_content_image_refs()")
    op.execute("DROP TRIGGER IF EXISTS trg_channel_contents_require_approved_copy ON channel_contents")
    op.execute("DROP FUNCTION IF EXISTS enforce_channel_content_reviewed_versions()")
    op.execute("DROP TRIGGER IF EXISTS trg_channel_contents_snapshot_protected ON channel_contents")
    op.execute("DROP FUNCTION IF EXISTS protect_channel_content_snapshot()")
    for table in (
        "artifact_versions",
        "review_records",
        "channel_content_artifact_refs",
        "quality_reports",
        "quality_resolutions",
        "publish_packages",
        "publish_package_items",
        "publish_package_fact_refs",
        "publish_confirmations",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_append_only ON {table}")
    op.execute("DROP FUNCTION IF EXISTS prevent_content_delivery_append_only_mutation()")

    op.drop_index("ix_publish_confirmations_store_package_created", table_name="publish_confirmations")
    op.drop_table("publish_confirmations")
    op.drop_index("ix_publish_package_fact_refs_store_package", table_name="publish_package_fact_refs")
    op.drop_table("publish_package_fact_refs")
    op.drop_index("ix_publish_package_items_store_package", table_name="publish_package_items")
    op.drop_table("publish_package_items")
    op.drop_index("ix_publish_packages_store_task_frozen", table_name="publish_packages")
    op.drop_table("publish_packages")
    op.drop_index("ix_quality_resolutions_store_report_created", table_name="quality_resolutions")
    op.drop_table("quality_resolutions")
    op.drop_index("ix_quality_reports_store_content_created", table_name="quality_reports")
    op.drop_table("quality_reports")
    op.drop_index("ix_channel_content_artifact_refs_content", table_name="channel_content_artifact_refs")
    op.drop_table("channel_content_artifact_refs")
    op.drop_index("ix_channel_contents_store_task_channel", table_name="channel_contents")
    op.drop_table("channel_contents")
    op.drop_constraint(
        "fk_artifact_versions_prompt_version",
        "artifact_versions",
        type_="foreignkey",
    )
    op.drop_constraint(
        "uq_artifact_versions_store_id",
        "artifact_versions",
        type_="unique",
    )
",
            name="ck_quality_reports_input_fingerprint_sha256",
        ),
        sa.CheckConstraint(
            "input_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_quality_reports_input_fingerprint_sha256",
        ),
    )
    op.create_index(
        "ix_quality_reports_store_content_created",
        "quality_reports",
        ["store_id", "channel_content_id", "created_at"],
    )

    op.create_table(
        "quality_resolutions",
        sa.Column("id", UUID, nullable=False),
        sa.Column("store_id", UUID, nullable=False),
        sa.Column("quality_report_id", UUID, nullable=False),
        sa.Column("quality_report_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("reviewer_user_id", UUID, nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_quality_resolutions"),
        sa.UniqueConstraint(
            "store_id", "quality_report_id", "quality_report_fingerprint",
            name="uq_quality_resolutions_report_fingerprint",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "quality_report_id", "quality_report_fingerprint"],
            ["quality_reports.store_id", "quality_reports.id", "quality_reports.input_fingerprint"],
            name="fk_quality_resolutions_report_fingerprint_same_store",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reviewer_user_id"], ["users.id"],
            name="fk_quality_resolutions_reviewer",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "decision IN ('accepted', 'rejected')",
            name="ck_quality_resolutions_decision",
        ),
        sa.CheckConstraint(
            "length(trim(reason)) > 0",
            name="ck_quality_resolutions_reason_required",
        ),
    )
    op.create_index(
        "ix_quality_resolutions_store_report_created",
        "quality_resolutions",
        ["store_id", "quality_report_id", "created_at"],
    )

    op.create_table(
        "publish_packages",
        sa.Column("id", UUID, nullable=False),
        sa.Column("store_id", UUID, nullable=False),
        sa.Column("task_id", UUID, nullable=False),
        sa.Column("package_version", sa.Integer(), nullable=False),
        sa.Column("package_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("frozen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("frozen_by_user_id", UUID, nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_publish_packages"),
        sa.UniqueConstraint(
            "store_id", "task_id", "package_version",
            name="uq_publish_packages_task_version",
        ),
        sa.UniqueConstraint(
            "store_id", "id", "package_fingerprint",
            name="uq_publish_packages_store_id_fingerprint",
        ),
        sa.UniqueConstraint(
            "store_id", "task_id", "id",
            name="uq_publish_packages_store_task_id",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "task_id"],
            ["marketing_tasks.store_id", "marketing_tasks.id"],
            name="fk_publish_packages_task_same_store",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["frozen_by_user_id"], ["users.id"],
            name="fk_publish_packages_frozen_by_user",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint("package_version >= 1", name="ck_publish_packages_package_version_positive"),
        sa.CheckConstraint(
            "package_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_publish_packages_fingerprint_sha256",
        ),
    )
    op.create_index(
        "ix_publish_packages_store_task_frozen",
        "publish_packages",
        ["store_id", "task_id", "frozen_at"],
    )

    op.create_table(
        "publish_package_items",
        sa.Column("id", UUID, nullable=False),
        sa.Column("store_id", UUID, nullable=False),
        sa.Column("publish_package_id", UUID, nullable=False),
        sa.Column("channel_key", sa.String(length=80), nullable=False),
        sa.Column("channel_content_id", UUID, nullable=False),
        sa.Column("quality_report_id", UUID, nullable=False),
        sa.Column("channel_account_id", UUID, nullable=True),
        sa.Column("delivery_mode", sa.String(length=24), nullable=False),
        sa.Column("planned_publish_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("item_fingerprint", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_publish_package_items"),
        sa.UniqueConstraint(
            "store_id", "publish_package_id", "channel_key",
            name="uq_publish_package_items_channel",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "publish_package_id"],
            ["publish_packages.store_id", "publish_packages.id"],
            name="fk_publish_package_items_package_same_store",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "channel_content_id", "channel_key"],
            ["channel_contents.store_id", "channel_contents.id", "channel_contents.channel_key"],
            name="fk_publish_package_items_channel_content_same_store",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "channel_content_id", "quality_report_id"],
            ["quality_reports.store_id", "quality_reports.channel_content_id", "quality_reports.id"],
            name="fk_publish_package_items_quality_report_same_content",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "delivery_mode IN ('official_api', 'manual_handoff')",
            name="ck_publish_package_items_delivery_mode",
        ),
        sa.CheckConstraint(
            "(delivery_mode = 'official_api' AND channel_account_id IS NOT NULL) OR "
            "(delivery_mode = 'manual_handoff' AND channel_account_id IS NULL)",
            name="ck_publish_package_items_channel_account_matches_delivery_mode",
        ),
        sa.CheckConstraint(
            "item_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_publish_package_items_item_fingerprint_sha256",
        ),
    )
    op.create_index(
        "ix_publish_package_items_store_package",
        "publish_package_items",
        ["store_id", "publish_package_id"],
    )

    op.create_table(
        "publish_package_fact_refs",
        sa.Column("id", UUID, nullable=False),
        sa.Column("store_id", UUID, nullable=False),
        sa.Column("task_id", UUID, nullable=False),
        sa.Column("publish_package_id", UUID, nullable=False),
        sa.Column("business_fact_snapshot_id", UUID, nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_publish_package_fact_refs"),
        sa.UniqueConstraint(
            "store_id", "publish_package_id", "position",
            name="uq_publish_package_fact_refs_position",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "task_id", "publish_package_id"],
            ["publish_packages.store_id", "publish_packages.task_id", "publish_packages.id"],
            name="fk_publish_package_fact_refs_package_same_task",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "task_id", "business_fact_snapshot_id"],
            ["business_fact_snapshots.store_id", "business_fact_snapshots.task_id", "business_fact_snapshots.id"],
            name="fk_publish_package_fact_refs_fact_same_task",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("position >= 0", name="ck_publish_package_fact_refs_position_nonnegative"),
    )
    op.create_index(
        "ix_publish_package_fact_refs_store_package",
        "publish_package_fact_refs",
        ["store_id", "publish_package_id"],
    )

    op.create_table(
        "publish_confirmations",
        sa.Column("id", UUID, nullable=False),
        sa.Column("store_id", UUID, nullable=False),
        sa.Column("publish_package_id", UUID, nullable=False),
        sa.Column("package_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("confirmed_by_user_id", UUID, nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("confirmation_note", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_publish_confirmations"),
        sa.UniqueConstraint(
            "store_id", "publish_package_id", "package_fingerprint",
            name="uq_publish_confirmations_package_fingerprint",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "publish_package_id", "package_fingerprint"],
            ["publish_packages.store_id", "publish_packages.id", "publish_packages.package_fingerprint"],
            name="fk_publish_confirmations_package_fingerprint_same_store",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["confirmed_by_user_id"], ["users.id"],
            name="fk_publish_confirmations_user",
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_publish_confirmations_store_package_created",
        "publish_confirmations",
        ["store_id", "publish_package_id", "confirmed_at"],
    )

    op.execute(
        """
        CREATE FUNCTION prevent_content_delivery_append_only_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    append_only_tables = (
        "artifact_versions",
        "review_records",
        "channel_content_artifact_refs",
        "quality_reports",
        "quality_resolutions",
        "publish_packages",
        "publish_package_items",
        "publish_package_fact_refs",
        "publish_confirmations",
    )
    for table in append_only_tables:
        op.execute(
            f"CREATE TRIGGER trg_{table}_append_only "
            f"BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION "
            "prevent_content_delivery_append_only_mutation()"
        )

    op.execute(
        """
        CREATE FUNCTION protect_channel_content_snapshot() RETURNS trigger AS $$
        BEGIN
            IF (to_jsonb(NEW) - ARRAY['status', 'updated_at'])
               IS DISTINCT FROM
               (to_jsonb(OLD) - ARRAY['status', 'updated_at']) THEN
                RAISE EXCEPTION 'channel content snapshot fields are immutable';
            END IF;
            IF OLD.status IN ('stale', 'blocked') AND NEW.status <> OLD.status THEN
                RAISE EXCEPTION 'stale or blocked channel content cannot be reactivated';
            END IF;
            IF NEW.status NOT IN ('ready', 'stale', 'blocked') THEN
                RAISE EXCEPTION 'invalid channel content status';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_channel_contents_snapshot_protected
        BEFORE UPDATE ON channel_contents
        FOR EACH ROW EXECUTE FUNCTION protect_channel_content_snapshot();
        """
    )

    op.execute(
        """
        CREATE FUNCTION enforce_channel_content_reviewed_versions() RETURNS trigger AS $$
        DECLARE
            artifact_type text;
        BEGIN
            SELECT a.artifact_type INTO artifact_type
            FROM artifact_versions av
            JOIN artifacts a
              ON a.store_id = av.store_id AND a.id = av.artifact_id
            WHERE av.store_id = NEW.store_id
              AND av.id = NEW.copy_version_id;
            IF artifact_type IS DISTINCT FROM 'copy' THEN
                RAISE EXCEPTION 'channel content requires a copy artifact version';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM review_records rr
                WHERE rr.store_id = NEW.store_id
                  AND rr.artifact_version_id = NEW.copy_version_id
                  AND rr.review_type = 'copy'
                  AND rr.decision = 'approved'
            ) THEN
                RAISE EXCEPTION 'channel content requires an approved copy version';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_channel_contents_require_approved_copy
        BEFORE INSERT ON channel_contents
        FOR EACH ROW EXECUTE FUNCTION enforce_channel_content_reviewed_versions();
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_channel_content_image_refs() RETURNS trigger AS $$
        DECLARE
            artifact_type text;
        BEGIN
            SELECT a.artifact_type INTO artifact_type
            FROM artifact_versions av
            JOIN artifacts a
              ON a.store_id = av.store_id AND a.id = av.artifact_id
            WHERE av.store_id = NEW.store_id
              AND av.id = NEW.artifact_version_id;
            IF artifact_type IS DISTINCT FROM 'image' THEN
                RAISE EXCEPTION 'channel content image reference requires an image artifact version';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM review_records rr
                WHERE rr.store_id = NEW.store_id
                  AND rr.artifact_version_id = NEW.artifact_version_id
                  AND rr.review_type = 'image'
                  AND rr.decision = 'approved'
            ) THEN
                RAISE EXCEPTION 'channel content image reference requires an approved image version';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_channel_content_artifact_refs_require_approved_image
        BEFORE INSERT ON channel_content_artifact_refs
        FOR EACH ROW EXECUTE FUNCTION enforce_channel_content_image_refs();
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_quality_resolution_needs_human() RETURNS trigger AS $$
        DECLARE
            report_result text;
        BEGIN
            SELECT result INTO report_result
            FROM quality_reports
            WHERE store_id = NEW.store_id
              AND id = NEW.quality_report_id
              AND input_fingerprint = NEW.quality_report_fingerprint;
            IF report_result IS DISTINCT FROM 'needs_human' THEN
                RAISE EXCEPTION 'only needs_human quality reports can be resolved';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_quality_resolutions_needs_human_only
        BEFORE INSERT ON quality_resolutions
        FOR EACH ROW EXECUTE FUNCTION enforce_quality_resolution_needs_human();
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_publish_package_item_quality_gate() RETURNS trigger AS $$
        DECLARE
            report_result text;
            report_fingerprint text;
        BEGIN
            SELECT result, input_fingerprint
              INTO report_result, report_fingerprint
            FROM quality_reports
            WHERE store_id = NEW.store_id
              AND channel_content_id = NEW.channel_content_id
              AND id = NEW.quality_report_id;
            IF report_result = 'fail' OR report_result IS NULL THEN
                RAISE EXCEPTION 'publish package requires a passing or accepted quality report';
            END IF;
            IF report_result = 'needs_human' AND NOT EXISTS (
                SELECT 1 FROM quality_resolutions qr
                WHERE qr.store_id = NEW.store_id
                  AND qr.quality_report_id = NEW.quality_report_id
                  AND qr.quality_report_fingerprint = report_fingerprint
                  AND qr.decision = 'accepted'
            ) THEN
                RAISE EXCEPTION 'quality report requires an accepted human resolution';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_publish_package_items_quality_gate
        BEFORE INSERT ON publish_package_items
        FOR EACH ROW EXECUTE FUNCTION enforce_publish_package_item_quality_gate();
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_publish_package_confirmed_facts() RETURNS trigger AS $$
        DECLARE
            fact_status text;
        BEGIN
            SELECT confirmation_status INTO fact_status
            FROM business_fact_snapshots
            WHERE store_id = NEW.store_id
              AND task_id = NEW.task_id
              AND id = NEW.business_fact_snapshot_id;
            IF fact_status IS DISTINCT FROM 'confirmed' THEN
                RAISE EXCEPTION 'publish package facts must be confirmed';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_publish_package_fact_refs_confirmed_only
        BEFORE INSERT ON publish_package_fact_refs
        FOR EACH ROW EXECUTE FUNCTION enforce_publish_package_confirmed_facts();
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_publish_package_complete() RETURNS trigger AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM publish_package_items
                WHERE store_id = NEW.store_id
                  AND publish_package_id = NEW.id
            ) THEN
                RAISE EXCEPTION 'publish package requires at least one item';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM publish_package_fact_refs
                WHERE store_id = NEW.store_id
                  AND publish_package_id = NEW.id
            ) THEN
                RAISE EXCEPTION 'publish package requires confirmed business facts';
            END IF;
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER trg_publish_packages_complete
        AFTER INSERT ON publish_packages
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION enforce_publish_package_complete();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_publish_packages_complete ON publish_packages")
    op.execute("DROP FUNCTION IF EXISTS enforce_publish_package_complete()")
    op.execute("DROP TRIGGER IF EXISTS trg_publish_package_fact_refs_confirmed_only ON publish_package_fact_refs")
    op.execute("DROP FUNCTION IF EXISTS enforce_publish_package_confirmed_facts()")
    op.execute("DROP TRIGGER IF EXISTS trg_publish_package_items_quality_gate ON publish_package_items")
    op.execute("DROP FUNCTION IF EXISTS enforce_publish_package_item_quality_gate()")
    op.execute("DROP TRIGGER IF EXISTS trg_quality_resolutions_needs_human_only ON quality_resolutions")
    op.execute("DROP FUNCTION IF EXISTS enforce_quality_resolution_needs_human()")
    op.execute("DROP TRIGGER IF EXISTS trg_channel_content_artifact_refs_require_approved_image ON channel_content_artifact_refs")
    op.execute("DROP FUNCTION IF EXISTS enforce_channel_content_image_refs()")
    op.execute("DROP TRIGGER IF EXISTS trg_channel_contents_require_approved_copy ON channel_contents")
    op.execute("DROP FUNCTION IF EXISTS enforce_channel_content_reviewed_versions()")
    op.execute("DROP TRIGGER IF EXISTS trg_channel_contents_snapshot_protected ON channel_contents")
    op.execute("DROP FUNCTION IF EXISTS protect_channel_content_snapshot()")
    for table in (
        "artifact_versions",
        "review_records",
        "channel_content_artifact_refs",
        "quality_reports",
        "quality_resolutions",
        "publish_packages",
        "publish_package_items",
        "publish_package_fact_refs",
        "publish_confirmations",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_append_only ON {table}")
    op.execute("DROP FUNCTION IF EXISTS prevent_content_delivery_append_only_mutation()")

    op.drop_index("ix_publish_confirmations_store_package_created", table_name="publish_confirmations")
    op.drop_table("publish_confirmations")
    op.drop_index("ix_publish_package_fact_refs_store_package", table_name="publish_package_fact_refs")
    op.drop_table("publish_package_fact_refs")
    op.drop_index("ix_publish_package_items_store_package", table_name="publish_package_items")
    op.drop_table("publish_package_items")
    op.drop_index("ix_publish_packages_store_task_frozen", table_name="publish_packages")
    op.drop_table("publish_packages")
    op.drop_index("ix_quality_resolutions_store_report_created", table_name="quality_resolutions")
    op.drop_table("quality_resolutions")
    op.drop_index("ix_quality_reports_store_content_created", table_name="quality_reports")
    op.drop_table("quality_reports")
    op.drop_index("ix_channel_content_artifact_refs_content", table_name="channel_content_artifact_refs")
    op.drop_table("channel_content_artifact_refs")
    op.drop_index("ix_channel_contents_store_task_channel", table_name="channel_contents")
    op.drop_table("channel_contents")
    op.drop_constraint(
        "fk_artifact_versions_prompt_version",
        "artifact_versions",
        type_="foreignkey",
    )
    op.drop_constraint(
        "uq_artifact_versions_store_id",
        "artifact_versions",
        type_="unique",
    )
",
            name="ck_channel_contents_input_fingerprint_sha256",
        ),
        sa.CheckConstraint(
            "input_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_channel_contents_input_fingerprint_sha256",
        ),
    )
    op.create_index(
        "ix_channel_contents_store_task_channel",
        "channel_contents",
        ["store_id", "task_id", "channel_key", "created_at"],
    )

    op.create_table(
        "channel_content_artifact_refs",
        sa.Column("id", UUID, nullable=False),
        sa.Column("store_id", UUID, nullable=False),
        sa.Column("channel_content_id", UUID, nullable=False),
        sa.Column("artifact_version_id", UUID, nullable=False),
        sa.Column("role", sa.String(length=16), server_default="image", nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_channel_content_artifact_refs"),
        sa.UniqueConstraint(
            "store_id", "channel_content_id", "position",
            name="uq_channel_content_artifact_refs_position",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "channel_content_id"],
            ["channel_contents.store_id", "channel_contents.id"],
            name="fk_channel_content_artifact_refs_content_same_store",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "artifact_version_id"],
            ["artifact_versions.store_id", "artifact_versions.id"],
            name="fk_channel_content_artifact_refs_version_same_store",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("role = 'image'", name="ck_channel_content_artifact_refs_role_image_only"),
        sa.CheckConstraint("position >= 0", name="ck_channel_content_artifact_refs_position_nonnegative"),
    )
    op.create_index(
        "ix_channel_content_artifact_refs_content",
        "channel_content_artifact_refs",
        ["store_id", "channel_content_id", "position"],
    )

    op.create_table(
        "quality_reports",
        sa.Column("id", UUID, nullable=False),
        sa.Column("store_id", UUID, nullable=False),
        sa.Column("task_id", UUID, nullable=False),
        sa.Column("channel_content_id", UUID, nullable=False),
        sa.Column("rule_version", sa.String(length=80), nullable=False),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("result", sa.String(length=16), nullable=False),
        sa.Column("issues_json", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_quality_reports"),
        sa.UniqueConstraint("store_id", "id", name="uq_quality_reports_store_id"),
        sa.UniqueConstraint(
            "store_id", "id", "input_fingerprint",
            name="uq_quality_reports_store_id_fingerprint",
        ),
        sa.UniqueConstraint(
            "store_id", "channel_content_id", "id",
            name="uq_quality_reports_content_id",
        ),
        sa.UniqueConstraint(
            "store_id", "channel_content_id", "rule_version", "input_fingerprint",
            name="uq_quality_reports_content_rule_fingerprint",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "task_id", "channel_content_id"],
            ["channel_contents.store_id", "channel_contents.task_id", "channel_contents.id"],
            name="fk_quality_reports_channel_content_same_task_store",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "result IN ('pass', 'fail', 'needs_human')",
            name="ck_quality_reports_result",
        ),
        sa.CheckConstraint(
            "length(trim(rule_version)) > 0",
            name="ck_quality_reports_rule_version_required",
        ),
        sa.CheckConstraint(
            "input_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_quality_reports_input_fingerprint_sha256",
        ),
    )
    op.create_index(
        "ix_quality_reports_store_content_created",
        "quality_reports",
        ["store_id", "channel_content_id", "created_at"],
    )

    op.create_table(
        "quality_resolutions",
        sa.Column("id", UUID, nullable=False),
        sa.Column("store_id", UUID, nullable=False),
        sa.Column("quality_report_id", UUID, nullable=False),
        sa.Column("quality_report_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("reviewer_user_id", UUID, nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_quality_resolutions"),
        sa.UniqueConstraint(
            "store_id", "quality_report_id", "quality_report_fingerprint",
            name="uq_quality_resolutions_report_fingerprint",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "quality_report_id", "quality_report_fingerprint"],
            ["quality_reports.store_id", "quality_reports.id", "quality_reports.input_fingerprint"],
            name="fk_quality_resolutions_report_fingerprint_same_store",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reviewer_user_id"], ["users.id"],
            name="fk_quality_resolutions_reviewer",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "decision IN ('accepted', 'rejected')",
            name="ck_quality_resolutions_decision",
        ),
        sa.CheckConstraint(
            "length(trim(reason)) > 0",
            name="ck_quality_resolutions_reason_required",
        ),
    )
    op.create_index(
        "ix_quality_resolutions_store_report_created",
        "quality_resolutions",
        ["store_id", "quality_report_id", "created_at"],
    )

    op.create_table(
        "publish_packages",
        sa.Column("id", UUID, nullable=False),
        sa.Column("store_id", UUID, nullable=False),
        sa.Column("task_id", UUID, nullable=False),
        sa.Column("package_version", sa.Integer(), nullable=False),
        sa.Column("package_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("frozen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("frozen_by_user_id", UUID, nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_publish_packages"),
        sa.UniqueConstraint(
            "store_id", "task_id", "package_version",
            name="uq_publish_packages_task_version",
        ),
        sa.UniqueConstraint(
            "store_id", "id", "package_fingerprint",
            name="uq_publish_packages_store_id_fingerprint",
        ),
        sa.UniqueConstraint(
            "store_id", "task_id", "id",
            name="uq_publish_packages_store_task_id",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "task_id"],
            ["marketing_tasks.store_id", "marketing_tasks.id"],
            name="fk_publish_packages_task_same_store",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["frozen_by_user_id"], ["users.id"],
            name="fk_publish_packages_frozen_by_user",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint("package_version >= 1", name="ck_publish_packages_package_version_positive"),
        sa.CheckConstraint(
            "package_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_publish_packages_fingerprint_sha256",
        ),
    )
    op.create_index(
        "ix_publish_packages_store_task_frozen",
        "publish_packages",
        ["store_id", "task_id", "frozen_at"],
    )

    op.create_table(
        "publish_package_items",
        sa.Column("id", UUID, nullable=False),
        sa.Column("store_id", UUID, nullable=False),
        sa.Column("publish_package_id", UUID, nullable=False),
        sa.Column("channel_key", sa.String(length=80), nullable=False),
        sa.Column("channel_content_id", UUID, nullable=False),
        sa.Column("quality_report_id", UUID, nullable=False),
        sa.Column("channel_account_id", UUID, nullable=True),
        sa.Column("delivery_mode", sa.String(length=24), nullable=False),
        sa.Column("planned_publish_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("item_fingerprint", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_publish_package_items"),
        sa.UniqueConstraint(
            "store_id", "publish_package_id", "channel_key",
            name="uq_publish_package_items_channel",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "publish_package_id"],
            ["publish_packages.store_id", "publish_packages.id"],
            name="fk_publish_package_items_package_same_store",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "channel_content_id", "channel_key"],
            ["channel_contents.store_id", "channel_contents.id", "channel_contents.channel_key"],
            name="fk_publish_package_items_channel_content_same_store",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "channel_content_id", "quality_report_id"],
            ["quality_reports.store_id", "quality_reports.channel_content_id", "quality_reports.id"],
            name="fk_publish_package_items_quality_report_same_content",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "delivery_mode IN ('official_api', 'manual_handoff')",
            name="ck_publish_package_items_delivery_mode",
        ),
        sa.CheckConstraint(
            "(delivery_mode = 'official_api' AND channel_account_id IS NOT NULL) OR "
            "(delivery_mode = 'manual_handoff' AND channel_account_id IS NULL)",
            name="ck_publish_package_items_channel_account_matches_delivery_mode",
        ),
        sa.CheckConstraint(
            "item_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_publish_package_items_item_fingerprint_sha256",
        ),
    )
    op.create_index(
        "ix_publish_package_items_store_package",
        "publish_package_items",
        ["store_id", "publish_package_id"],
    )

    op.create_table(
        "publish_package_fact_refs",
        sa.Column("id", UUID, nullable=False),
        sa.Column("store_id", UUID, nullable=False),
        sa.Column("task_id", UUID, nullable=False),
        sa.Column("publish_package_id", UUID, nullable=False),
        sa.Column("business_fact_snapshot_id", UUID, nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_publish_package_fact_refs"),
        sa.UniqueConstraint(
            "store_id", "publish_package_id", "position",
            name="uq_publish_package_fact_refs_position",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "task_id", "publish_package_id"],
            ["publish_packages.store_id", "publish_packages.task_id", "publish_packages.id"],
            name="fk_publish_package_fact_refs_package_same_task",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "task_id", "business_fact_snapshot_id"],
            ["business_fact_snapshots.store_id", "business_fact_snapshots.task_id", "business_fact_snapshots.id"],
            name="fk_publish_package_fact_refs_fact_same_task",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("position >= 0", name="ck_publish_package_fact_refs_position_nonnegative"),
    )
    op.create_index(
        "ix_publish_package_fact_refs_store_package",
        "publish_package_fact_refs",
        ["store_id", "publish_package_id"],
    )

    op.create_table(
        "publish_confirmations",
        sa.Column("id", UUID, nullable=False),
        sa.Column("store_id", UUID, nullable=False),
        sa.Column("publish_package_id", UUID, nullable=False),
        sa.Column("package_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("confirmed_by_user_id", UUID, nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("confirmation_note", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_publish_confirmations"),
        sa.UniqueConstraint(
            "store_id", "publish_package_id", "package_fingerprint",
            name="uq_publish_confirmations_package_fingerprint",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "publish_package_id", "package_fingerprint"],
            ["publish_packages.store_id", "publish_packages.id", "publish_packages.package_fingerprint"],
            name="fk_publish_confirmations_package_fingerprint_same_store",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["confirmed_by_user_id"], ["users.id"],
            name="fk_publish_confirmations_user",
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_publish_confirmations_store_package_created",
        "publish_confirmations",
        ["store_id", "publish_package_id", "confirmed_at"],
    )

    op.execute(
        """
        CREATE FUNCTION prevent_content_delivery_append_only_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    append_only_tables = (
        "artifact_versions",
        "review_records",
        "channel_content_artifact_refs",
        "quality_reports",
        "quality_resolutions",
        "publish_packages",
        "publish_package_items",
        "publish_package_fact_refs",
        "publish_confirmations",
    )
    for table in append_only_tables:
        op.execute(
            f"CREATE TRIGGER trg_{table}_append_only "
            f"BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION "
            "prevent_content_delivery_append_only_mutation()"
        )

    op.execute(
        """
        CREATE FUNCTION protect_channel_content_snapshot() RETURNS trigger AS $$
        BEGIN
            IF (to_jsonb(NEW) - ARRAY['status', 'updated_at'])
               IS DISTINCT FROM
               (to_jsonb(OLD) - ARRAY['status', 'updated_at']) THEN
                RAISE EXCEPTION 'channel content snapshot fields are immutable';
            END IF;
            IF OLD.status IN ('stale', 'blocked') AND NEW.status <> OLD.status THEN
                RAISE EXCEPTION 'stale or blocked channel content cannot be reactivated';
            END IF;
            IF NEW.status NOT IN ('ready', 'stale', 'blocked') THEN
                RAISE EXCEPTION 'invalid channel content status';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_channel_contents_snapshot_protected
        BEFORE UPDATE ON channel_contents
        FOR EACH ROW EXECUTE FUNCTION protect_channel_content_snapshot();
        """
    )

    op.execute(
        """
        CREATE FUNCTION enforce_channel_content_reviewed_versions() RETURNS trigger AS $$
        DECLARE
            artifact_type text;
        BEGIN
            SELECT a.artifact_type INTO artifact_type
            FROM artifact_versions av
            JOIN artifacts a
              ON a.store_id = av.store_id AND a.id = av.artifact_id
            WHERE av.store_id = NEW.store_id
              AND av.id = NEW.copy_version_id;
            IF artifact_type IS DISTINCT FROM 'copy' THEN
                RAISE EXCEPTION 'channel content requires a copy artifact version';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM review_records rr
                WHERE rr.store_id = NEW.store_id
                  AND rr.artifact_version_id = NEW.copy_version_id
                  AND rr.review_type = 'copy'
                  AND rr.decision = 'approved'
            ) THEN
                RAISE EXCEPTION 'channel content requires an approved copy version';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_channel_contents_require_approved_copy
        BEFORE INSERT ON channel_contents
        FOR EACH ROW EXECUTE FUNCTION enforce_channel_content_reviewed_versions();
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_channel_content_image_refs() RETURNS trigger AS $$
        DECLARE
            artifact_type text;
        BEGIN
            SELECT a.artifact_type INTO artifact_type
            FROM artifact_versions av
            JOIN artifacts a
              ON a.store_id = av.store_id AND a.id = av.artifact_id
            WHERE av.store_id = NEW.store_id
              AND av.id = NEW.artifact_version_id;
            IF artifact_type IS DISTINCT FROM 'image' THEN
                RAISE EXCEPTION 'channel content image reference requires an image artifact version';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM review_records rr
                WHERE rr.store_id = NEW.store_id
                  AND rr.artifact_version_id = NEW.artifact_version_id
                  AND rr.review_type = 'image'
                  AND rr.decision = 'approved'
            ) THEN
                RAISE EXCEPTION 'channel content image reference requires an approved image version';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_channel_content_artifact_refs_require_approved_image
        BEFORE INSERT ON channel_content_artifact_refs
        FOR EACH ROW EXECUTE FUNCTION enforce_channel_content_image_refs();
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_quality_resolution_needs_human() RETURNS trigger AS $$
        DECLARE
            report_result text;
        BEGIN
            SELECT result INTO report_result
            FROM quality_reports
            WHERE store_id = NEW.store_id
              AND id = NEW.quality_report_id
              AND input_fingerprint = NEW.quality_report_fingerprint;
            IF report_result IS DISTINCT FROM 'needs_human' THEN
                RAISE EXCEPTION 'only needs_human quality reports can be resolved';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_quality_resolutions_needs_human_only
        BEFORE INSERT ON quality_resolutions
        FOR EACH ROW EXECUTE FUNCTION enforce_quality_resolution_needs_human();
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_publish_package_item_quality_gate() RETURNS trigger AS $$
        DECLARE
            report_result text;
            report_fingerprint text;
        BEGIN
            SELECT result, input_fingerprint
              INTO report_result, report_fingerprint
            FROM quality_reports
            WHERE store_id = NEW.store_id
              AND channel_content_id = NEW.channel_content_id
              AND id = NEW.quality_report_id;
            IF report_result = 'fail' OR report_result IS NULL THEN
                RAISE EXCEPTION 'publish package requires a passing or accepted quality report';
            END IF;
            IF report_result = 'needs_human' AND NOT EXISTS (
                SELECT 1 FROM quality_resolutions qr
                WHERE qr.store_id = NEW.store_id
                  AND qr.quality_report_id = NEW.quality_report_id
                  AND qr.quality_report_fingerprint = report_fingerprint
                  AND qr.decision = 'accepted'
            ) THEN
                RAISE EXCEPTION 'quality report requires an accepted human resolution';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_publish_package_items_quality_gate
        BEFORE INSERT ON publish_package_items
        FOR EACH ROW EXECUTE FUNCTION enforce_publish_package_item_quality_gate();
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_publish_package_confirmed_facts() RETURNS trigger AS $$
        DECLARE
            fact_status text;
        BEGIN
            SELECT confirmation_status INTO fact_status
            FROM business_fact_snapshots
            WHERE store_id = NEW.store_id
              AND task_id = NEW.task_id
              AND id = NEW.business_fact_snapshot_id;
            IF fact_status IS DISTINCT FROM 'confirmed' THEN
                RAISE EXCEPTION 'publish package facts must be confirmed';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_publish_package_fact_refs_confirmed_only
        BEFORE INSERT ON publish_package_fact_refs
        FOR EACH ROW EXECUTE FUNCTION enforce_publish_package_confirmed_facts();
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_publish_package_complete() RETURNS trigger AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM publish_package_items
                WHERE store_id = NEW.store_id
                  AND publish_package_id = NEW.id
            ) THEN
                RAISE EXCEPTION 'publish package requires at least one item';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM publish_package_fact_refs
                WHERE store_id = NEW.store_id
                  AND publish_package_id = NEW.id
            ) THEN
                RAISE EXCEPTION 'publish package requires confirmed business facts';
            END IF;
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER trg_publish_packages_complete
        AFTER INSERT ON publish_packages
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION enforce_publish_package_complete();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_publish_packages_complete ON publish_packages")
    op.execute("DROP FUNCTION IF EXISTS enforce_publish_package_complete()")
    op.execute("DROP TRIGGER IF EXISTS trg_publish_package_fact_refs_confirmed_only ON publish_package_fact_refs")
    op.execute("DROP FUNCTION IF EXISTS enforce_publish_package_confirmed_facts()")
    op.execute("DROP TRIGGER IF EXISTS trg_publish_package_items_quality_gate ON publish_package_items")
    op.execute("DROP FUNCTION IF EXISTS enforce_publish_package_item_quality_gate()")
    op.execute("DROP TRIGGER IF EXISTS trg_quality_resolutions_needs_human_only ON quality_resolutions")
    op.execute("DROP FUNCTION IF EXISTS enforce_quality_resolution_needs_human()")
    op.execute("DROP TRIGGER IF EXISTS trg_channel_content_artifact_refs_require_approved_image ON channel_content_artifact_refs")
    op.execute("DROP FUNCTION IF EXISTS enforce_channel_content_image_refs()")
    op.execute("DROP TRIGGER IF EXISTS trg_channel_contents_require_approved_copy ON channel_contents")
    op.execute("DROP FUNCTION IF EXISTS enforce_channel_content_reviewed_versions()")
    op.execute("DROP TRIGGER IF EXISTS trg_channel_contents_snapshot_protected ON channel_contents")
    op.execute("DROP FUNCTION IF EXISTS protect_channel_content_snapshot()")
    for table in (
        "artifact_versions",
        "review_records",
        "channel_content_artifact_refs",
        "quality_reports",
        "quality_resolutions",
        "publish_packages",
        "publish_package_items",
        "publish_package_fact_refs",
        "publish_confirmations",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_append_only ON {table}")
    op.execute("DROP FUNCTION IF EXISTS prevent_content_delivery_append_only_mutation()")

    op.drop_index("ix_publish_confirmations_store_package_created", table_name="publish_confirmations")
    op.drop_table("publish_confirmations")
    op.drop_index("ix_publish_package_fact_refs_store_package", table_name="publish_package_fact_refs")
    op.drop_table("publish_package_fact_refs")
    op.drop_index("ix_publish_package_items_store_package", table_name="publish_package_items")
    op.drop_table("publish_package_items")
    op.drop_index("ix_publish_packages_store_task_frozen", table_name="publish_packages")
    op.drop_table("publish_packages")
    op.drop_index("ix_quality_resolutions_store_report_created", table_name="quality_resolutions")
    op.drop_table("quality_resolutions")
    op.drop_index("ix_quality_reports_store_content_created", table_name="quality_reports")
    op.drop_table("quality_reports")
    op.drop_index("ix_channel_content_artifact_refs_content", table_name="channel_content_artifact_refs")
    op.drop_table("channel_content_artifact_refs")
    op.drop_index("ix_channel_contents_store_task_channel", table_name="channel_contents")
    op.drop_table("channel_contents")
    op.drop_constraint(
        "fk_artifact_versions_prompt_version",
        "artifact_versions",
        type_="foreignkey",
    )
    op.drop_constraint(
        "uq_artifact_versions_store_id",
        "artifact_versions",
        type_="unique",
    )
",
            name="ck_publish_packages_fingerprint_sha256",
        ),
    )
    op.create_index(
        "ix_publish_packages_store_task_frozen",
        "publish_packages",
        ["store_id", "task_id", "frozen_at"],
    )

    op.create_table(
        "publish_package_items",
        sa.Column("id", UUID, nullable=False),
        sa.Column("store_id", UUID, nullable=False),
        sa.Column("publish_package_id", UUID, nullable=False),
        sa.Column("channel_key", sa.String(length=80), nullable=False),
        sa.Column("channel_content_id", UUID, nullable=False),
        sa.Column("quality_report_id", UUID, nullable=False),
        sa.Column("channel_account_id", UUID, nullable=True),
        sa.Column("delivery_mode", sa.String(length=24), nullable=False),
        sa.Column("planned_publish_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("item_fingerprint", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_publish_package_items"),
        sa.UniqueConstraint(
            "store_id", "publish_package_id", "channel_key",
            name="uq_publish_package_items_channel",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "publish_package_id"],
            ["publish_packages.store_id", "publish_packages.id"],
            name="fk_publish_package_items_package_same_store",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "channel_content_id", "channel_key"],
            ["channel_contents.store_id", "channel_contents.id", "channel_contents.channel_key"],
            name="fk_publish_package_items_channel_content_same_store",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "channel_content_id", "quality_report_id"],
            ["quality_reports.store_id", "quality_reports.channel_content_id", "quality_reports.id"],
            name="fk_publish_package_items_quality_report_same_content",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "delivery_mode IN ('official_api', 'manual_handoff')",
            name="ck_publish_package_items_delivery_mode",
        ),
        sa.CheckConstraint(
            "(delivery_mode = 'official_api' AND channel_account_id IS NOT NULL) OR "
            "(delivery_mode = 'manual_handoff' AND channel_account_id IS NULL)",
            name="ck_publish_package_items_channel_account_matches_delivery_mode",
        ),
        sa.CheckConstraint(
            "item_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_publish_package_items_item_fingerprint_sha256",
        ),
    )
    op.create_index(
        "ix_publish_package_items_store_package",
        "publish_package_items",
        ["store_id", "publish_package_id"],
    )

    op.create_table(
        "publish_package_fact_refs",
        sa.Column("id", UUID, nullable=False),
        sa.Column("store_id", UUID, nullable=False),
        sa.Column("task_id", UUID, nullable=False),
        sa.Column("publish_package_id", UUID, nullable=False),
        sa.Column("business_fact_snapshot_id", UUID, nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_publish_package_fact_refs"),
        sa.UniqueConstraint(
            "store_id", "publish_package_id", "position",
            name="uq_publish_package_fact_refs_position",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "task_id", "publish_package_id"],
            ["publish_packages.store_id", "publish_packages.task_id", "publish_packages.id"],
            name="fk_publish_package_fact_refs_package_same_task",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "task_id", "business_fact_snapshot_id"],
            ["business_fact_snapshots.store_id", "business_fact_snapshots.task_id", "business_fact_snapshots.id"],
            name="fk_publish_package_fact_refs_fact_same_task",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("position >= 0", name="ck_publish_package_fact_refs_position_nonnegative"),
    )
    op.create_index(
        "ix_publish_package_fact_refs_store_package",
        "publish_package_fact_refs",
        ["store_id", "publish_package_id"],
    )

    op.create_table(
        "publish_confirmations",
        sa.Column("id", UUID, nullable=False),
        sa.Column("store_id", UUID, nullable=False),
        sa.Column("publish_package_id", UUID, nullable=False),
        sa.Column("package_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("confirmed_by_user_id", UUID, nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("confirmation_note", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_publish_confirmations"),
        sa.UniqueConstraint(
            "store_id", "publish_package_id", "package_fingerprint",
            name="uq_publish_confirmations_package_fingerprint",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "publish_package_id", "package_fingerprint"],
            ["publish_packages.store_id", "publish_packages.id", "publish_packages.package_fingerprint"],
            name="fk_publish_confirmations_package_fingerprint_same_store",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["confirmed_by_user_id"], ["users.id"],
            name="fk_publish_confirmations_user",
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_publish_confirmations_store_package_created",
        "publish_confirmations",
        ["store_id", "publish_package_id", "confirmed_at"],
    )

    op.execute(
        """
        CREATE FUNCTION prevent_content_delivery_append_only_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    append_only_tables = (
        "artifact_versions",
        "review_records",
        "channel_content_artifact_refs",
        "quality_reports",
        "quality_resolutions",
        "publish_packages",
        "publish_package_items",
        "publish_package_fact_refs",
        "publish_confirmations",
    )
    for table in append_only_tables:
        op.execute(
            f"CREATE TRIGGER trg_{table}_append_only "
            f"BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION "
            "prevent_content_delivery_append_only_mutation()"
        )

    op.execute(
        """
        CREATE FUNCTION protect_channel_content_snapshot() RETURNS trigger AS $$
        BEGIN
            IF (to_jsonb(NEW) - ARRAY['status', 'updated_at'])
               IS DISTINCT FROM
               (to_jsonb(OLD) - ARRAY['status', 'updated_at']) THEN
                RAISE EXCEPTION 'channel content snapshot fields are immutable';
            END IF;
            IF OLD.status IN ('stale', 'blocked') AND NEW.status <> OLD.status THEN
                RAISE EXCEPTION 'stale or blocked channel content cannot be reactivated';
            END IF;
            IF NEW.status NOT IN ('ready', 'stale', 'blocked') THEN
                RAISE EXCEPTION 'invalid channel content status';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_channel_contents_snapshot_protected
        BEFORE UPDATE ON channel_contents
        FOR EACH ROW EXECUTE FUNCTION protect_channel_content_snapshot();
        """
    )

    op.execute(
        """
        CREATE FUNCTION enforce_channel_content_reviewed_versions() RETURNS trigger AS $$
        DECLARE
            artifact_type text;
        BEGIN
            SELECT a.artifact_type INTO artifact_type
            FROM artifact_versions av
            JOIN artifacts a
              ON a.store_id = av.store_id AND a.id = av.artifact_id
            WHERE av.store_id = NEW.store_id
              AND av.id = NEW.copy_version_id;
            IF artifact_type IS DISTINCT FROM 'copy' THEN
                RAISE EXCEPTION 'channel content requires a copy artifact version';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM review_records rr
                WHERE rr.store_id = NEW.store_id
                  AND rr.artifact_version_id = NEW.copy_version_id
                  AND rr.review_type = 'copy'
                  AND rr.decision = 'approved'
            ) THEN
                RAISE EXCEPTION 'channel content requires an approved copy version';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_channel_contents_require_approved_copy
        BEFORE INSERT ON channel_contents
        FOR EACH ROW EXECUTE FUNCTION enforce_channel_content_reviewed_versions();
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_channel_content_image_refs() RETURNS trigger AS $$
        DECLARE
            artifact_type text;
        BEGIN
            SELECT a.artifact_type INTO artifact_type
            FROM artifact_versions av
            JOIN artifacts a
              ON a.store_id = av.store_id AND a.id = av.artifact_id
            WHERE av.store_id = NEW.store_id
              AND av.id = NEW.artifact_version_id;
            IF artifact_type IS DISTINCT FROM 'image' THEN
                RAISE EXCEPTION 'channel content image reference requires an image artifact version';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM review_records rr
                WHERE rr.store_id = NEW.store_id
                  AND rr.artifact_version_id = NEW.artifact_version_id
                  AND rr.review_type = 'image'
                  AND rr.decision = 'approved'
            ) THEN
                RAISE EXCEPTION 'channel content image reference requires an approved image version';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_channel_content_artifact_refs_require_approved_image
        BEFORE INSERT ON channel_content_artifact_refs
        FOR EACH ROW EXECUTE FUNCTION enforce_channel_content_image_refs();
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_quality_resolution_needs_human() RETURNS trigger AS $$
        DECLARE
            report_result text;
        BEGIN
            SELECT result INTO report_result
            FROM quality_reports
            WHERE store_id = NEW.store_id
              AND id = NEW.quality_report_id
              AND input_fingerprint = NEW.quality_report_fingerprint;
            IF report_result IS DISTINCT FROM 'needs_human' THEN
                RAISE EXCEPTION 'only needs_human quality reports can be resolved';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_quality_resolutions_needs_human_only
        BEFORE INSERT ON quality_resolutions
        FOR EACH ROW EXECUTE FUNCTION enforce_quality_resolution_needs_human();
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_publish_package_item_quality_gate() RETURNS trigger AS $$
        DECLARE
            report_result text;
            report_fingerprint text;
        BEGIN
            SELECT result, input_fingerprint
              INTO report_result, report_fingerprint
            FROM quality_reports
            WHERE store_id = NEW.store_id
              AND channel_content_id = NEW.channel_content_id
              AND id = NEW.quality_report_id;
            IF report_result = 'fail' OR report_result IS NULL THEN
                RAISE EXCEPTION 'publish package requires a passing or accepted quality report';
            END IF;
            IF report_result = 'needs_human' AND NOT EXISTS (
                SELECT 1 FROM quality_resolutions qr
                WHERE qr.store_id = NEW.store_id
                  AND qr.quality_report_id = NEW.quality_report_id
                  AND qr.quality_report_fingerprint = report_fingerprint
                  AND qr.decision = 'accepted'
            ) THEN
                RAISE EXCEPTION 'quality report requires an accepted human resolution';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_publish_package_items_quality_gate
        BEFORE INSERT ON publish_package_items
        FOR EACH ROW EXECUTE FUNCTION enforce_publish_package_item_quality_gate();
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_publish_package_confirmed_facts() RETURNS trigger AS $$
        DECLARE
            fact_status text;
        BEGIN
            SELECT confirmation_status INTO fact_status
            FROM business_fact_snapshots
            WHERE store_id = NEW.store_id
              AND task_id = NEW.task_id
              AND id = NEW.business_fact_snapshot_id;
            IF fact_status IS DISTINCT FROM 'confirmed' THEN
                RAISE EXCEPTION 'publish package facts must be confirmed';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_publish_package_fact_refs_confirmed_only
        BEFORE INSERT ON publish_package_fact_refs
        FOR EACH ROW EXECUTE FUNCTION enforce_publish_package_confirmed_facts();
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_publish_package_complete() RETURNS trigger AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM publish_package_items
                WHERE store_id = NEW.store_id
                  AND publish_package_id = NEW.id
            ) THEN
                RAISE EXCEPTION 'publish package requires at least one item';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM publish_package_fact_refs
                WHERE store_id = NEW.store_id
                  AND publish_package_id = NEW.id
            ) THEN
                RAISE EXCEPTION 'publish package requires confirmed business facts';
            END IF;
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER trg_publish_packages_complete
        AFTER INSERT ON publish_packages
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION enforce_publish_package_complete();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_publish_packages_complete ON publish_packages")
    op.execute("DROP FUNCTION IF EXISTS enforce_publish_package_complete()")
    op.execute("DROP TRIGGER IF EXISTS trg_publish_package_fact_refs_confirmed_only ON publish_package_fact_refs")
    op.execute("DROP FUNCTION IF EXISTS enforce_publish_package_confirmed_facts()")
    op.execute("DROP TRIGGER IF EXISTS trg_publish_package_items_quality_gate ON publish_package_items")
    op.execute("DROP FUNCTION IF EXISTS enforce_publish_package_item_quality_gate()")
    op.execute("DROP TRIGGER IF EXISTS trg_quality_resolutions_needs_human_only ON quality_resolutions")
    op.execute("DROP FUNCTION IF EXISTS enforce_quality_resolution_needs_human()")
    op.execute("DROP TRIGGER IF EXISTS trg_channel_content_artifact_refs_require_approved_image ON channel_content_artifact_refs")
    op.execute("DROP FUNCTION IF EXISTS enforce_channel_content_image_refs()")
    op.execute("DROP TRIGGER IF EXISTS trg_channel_contents_require_approved_copy ON channel_contents")
    op.execute("DROP FUNCTION IF EXISTS enforce_channel_content_reviewed_versions()")
    op.execute("DROP TRIGGER IF EXISTS trg_channel_contents_snapshot_protected ON channel_contents")
    op.execute("DROP FUNCTION IF EXISTS protect_channel_content_snapshot()")
    for table in (
        "artifact_versions",
        "review_records",
        "channel_content_artifact_refs",
        "quality_reports",
        "quality_resolutions",
        "publish_packages",
        "publish_package_items",
        "publish_package_fact_refs",
        "publish_confirmations",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_append_only ON {table}")
    op.execute("DROP FUNCTION IF EXISTS prevent_content_delivery_append_only_mutation()")

    op.drop_index("ix_publish_confirmations_store_package_created", table_name="publish_confirmations")
    op.drop_table("publish_confirmations")
    op.drop_index("ix_publish_package_fact_refs_store_package", table_name="publish_package_fact_refs")
    op.drop_table("publish_package_fact_refs")
    op.drop_index("ix_publish_package_items_store_package", table_name="publish_package_items")
    op.drop_table("publish_package_items")
    op.drop_index("ix_publish_packages_store_task_frozen", table_name="publish_packages")
    op.drop_table("publish_packages")
    op.drop_index("ix_quality_resolutions_store_report_created", table_name="quality_resolutions")
    op.drop_table("quality_resolutions")
    op.drop_index("ix_quality_reports_store_content_created", table_name="quality_reports")
    op.drop_table("quality_reports")
    op.drop_index("ix_channel_content_artifact_refs_content", table_name="channel_content_artifact_refs")
    op.drop_table("channel_content_artifact_refs")
    op.drop_index("ix_channel_contents_store_task_channel", table_name="channel_contents")
    op.drop_table("channel_contents")
    op.drop_constraint(
        "fk_artifact_versions_prompt_version",
        "artifact_versions",
        type_="foreignkey",
    )
    op.drop_constraint(
        "uq_artifact_versions_store_id",
        "artifact_versions",
        type_="unique",
    )
",
            name="ck_channel_contents_input_fingerprint_sha256",
        ),
        sa.CheckConstraint(
            "input_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_channel_contents_input_fingerprint_sha256",
        ),
    )
    op.create_index(
        "ix_channel_contents_store_task_channel",
        "channel_contents",
        ["store_id", "task_id", "channel_key", "created_at"],
    )

    op.create_table(
        "channel_content_artifact_refs",
        sa.Column("id", UUID, nullable=False),
        sa.Column("store_id", UUID, nullable=False),
        sa.Column("channel_content_id", UUID, nullable=False),
        sa.Column("artifact_version_id", UUID, nullable=False),
        sa.Column("role", sa.String(length=16), server_default="image", nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_channel_content_artifact_refs"),
        sa.UniqueConstraint(
            "store_id", "channel_content_id", "position",
            name="uq_channel_content_artifact_refs_position",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "channel_content_id"],
            ["channel_contents.store_id", "channel_contents.id"],
            name="fk_channel_content_artifact_refs_content_same_store",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "artifact_version_id"],
            ["artifact_versions.store_id", "artifact_versions.id"],
            name="fk_channel_content_artifact_refs_version_same_store",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("role = 'image'", name="ck_channel_content_artifact_refs_role_image_only"),
        sa.CheckConstraint("position >= 0", name="ck_channel_content_artifact_refs_position_nonnegative"),
    )
    op.create_index(
        "ix_channel_content_artifact_refs_content",
        "channel_content_artifact_refs",
        ["store_id", "channel_content_id", "position"],
    )

    op.create_table(
        "quality_reports",
        sa.Column("id", UUID, nullable=False),
        sa.Column("store_id", UUID, nullable=False),
        sa.Column("task_id", UUID, nullable=False),
        sa.Column("channel_content_id", UUID, nullable=False),
        sa.Column("rule_version", sa.String(length=80), nullable=False),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("result", sa.String(length=16), nullable=False),
        sa.Column("issues_json", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_quality_reports"),
        sa.UniqueConstraint("store_id", "id", name="uq_quality_reports_store_id"),
        sa.UniqueConstraint(
            "store_id", "id", "input_fingerprint",
            name="uq_quality_reports_store_id_fingerprint",
        ),
        sa.UniqueConstraint(
            "store_id", "channel_content_id", "id",
            name="uq_quality_reports_content_id",
        ),
        sa.UniqueConstraint(
            "store_id", "channel_content_id", "rule_version", "input_fingerprint",
            name="uq_quality_reports_content_rule_fingerprint",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "task_id", "channel_content_id"],
            ["channel_contents.store_id", "channel_contents.task_id", "channel_contents.id"],
            name="fk_quality_reports_channel_content_same_task_store",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "result IN ('pass', 'fail', 'needs_human')",
            name="ck_quality_reports_result",
        ),
        sa.CheckConstraint(
            "length(trim(rule_version)) > 0",
            name="ck_quality_reports_rule_version_required",
        ),
        sa.CheckConstraint(
            "input_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_quality_reports_input_fingerprint_sha256",
        ),
    )
    op.create_index(
        "ix_quality_reports_store_content_created",
        "quality_reports",
        ["store_id", "channel_content_id", "created_at"],
    )

    op.create_table(
        "quality_resolutions",
        sa.Column("id", UUID, nullable=False),
        sa.Column("store_id", UUID, nullable=False),
        sa.Column("quality_report_id", UUID, nullable=False),
        sa.Column("quality_report_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("reviewer_user_id", UUID, nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_quality_resolutions"),
        sa.UniqueConstraint(
            "store_id", "quality_report_id", "quality_report_fingerprint",
            name="uq_quality_resolutions_report_fingerprint",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "quality_report_id", "quality_report_fingerprint"],
            ["quality_reports.store_id", "quality_reports.id", "quality_reports.input_fingerprint"],
            name="fk_quality_resolutions_report_fingerprint_same_store",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reviewer_user_id"], ["users.id"],
            name="fk_quality_resolutions_reviewer",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "decision IN ('accepted', 'rejected')",
            name="ck_quality_resolutions_decision",
        ),
        sa.CheckConstraint(
            "length(trim(reason)) > 0",
            name="ck_quality_resolutions_reason_required",
        ),
    )
    op.create_index(
        "ix_quality_resolutions_store_report_created",
        "quality_resolutions",
        ["store_id", "quality_report_id", "created_at"],
    )

    op.create_table(
        "publish_packages",
        sa.Column("id", UUID, nullable=False),
        sa.Column("store_id", UUID, nullable=False),
        sa.Column("task_id", UUID, nullable=False),
        sa.Column("package_version", sa.Integer(), nullable=False),
        sa.Column("package_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("frozen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("frozen_by_user_id", UUID, nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_publish_packages"),
        sa.UniqueConstraint(
            "store_id", "task_id", "package_version",
            name="uq_publish_packages_task_version",
        ),
        sa.UniqueConstraint(
            "store_id", "id", "package_fingerprint",
            name="uq_publish_packages_store_id_fingerprint",
        ),
        sa.UniqueConstraint(
            "store_id", "task_id", "id",
            name="uq_publish_packages_store_task_id",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "task_id"],
            ["marketing_tasks.store_id", "marketing_tasks.id"],
            name="fk_publish_packages_task_same_store",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["frozen_by_user_id"], ["users.id"],
            name="fk_publish_packages_frozen_by_user",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint("package_version >= 1", name="ck_publish_packages_package_version_positive"),
        sa.CheckConstraint(
            "package_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_publish_packages_fingerprint_sha256",
        ),
    )
    op.create_index(
        "ix_publish_packages_store_task_frozen",
        "publish_packages",
        ["store_id", "task_id", "frozen_at"],
    )

    op.create_table(
        "publish_package_items",
        sa.Column("id", UUID, nullable=False),
        sa.Column("store_id", UUID, nullable=False),
        sa.Column("publish_package_id", UUID, nullable=False),
        sa.Column("channel_key", sa.String(length=80), nullable=False),
        sa.Column("channel_content_id", UUID, nullable=False),
        sa.Column("quality_report_id", UUID, nullable=False),
        sa.Column("channel_account_id", UUID, nullable=True),
        sa.Column("delivery_mode", sa.String(length=24), nullable=False),
        sa.Column("planned_publish_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("item_fingerprint", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_publish_package_items"),
        sa.UniqueConstraint(
            "store_id", "publish_package_id", "channel_key",
            name="uq_publish_package_items_channel",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "publish_package_id"],
            ["publish_packages.store_id", "publish_packages.id"],
            name="fk_publish_package_items_package_same_store",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "channel_content_id", "channel_key"],
            ["channel_contents.store_id", "channel_contents.id", "channel_contents.channel_key"],
            name="fk_publish_package_items_channel_content_same_store",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "channel_content_id", "quality_report_id"],
            ["quality_reports.store_id", "quality_reports.channel_content_id", "quality_reports.id"],
            name="fk_publish_package_items_quality_report_same_content",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "delivery_mode IN ('official_api', 'manual_handoff')",
            name="ck_publish_package_items_delivery_mode",
        ),
        sa.CheckConstraint(
            "(delivery_mode = 'official_api' AND channel_account_id IS NOT NULL) OR "
            "(delivery_mode = 'manual_handoff' AND channel_account_id IS NULL)",
            name="ck_publish_package_items_channel_account_matches_delivery_mode",
        ),
        sa.CheckConstraint(
            "item_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_publish_package_items_item_fingerprint_sha256",
        ),
    )
    op.create_index(
        "ix_publish_package_items_store_package",
        "publish_package_items",
        ["store_id", "publish_package_id"],
    )

    op.create_table(
        "publish_package_fact_refs",
        sa.Column("id", UUID, nullable=False),
        sa.Column("store_id", UUID, nullable=False),
        sa.Column("task_id", UUID, nullable=False),
        sa.Column("publish_package_id", UUID, nullable=False),
        sa.Column("business_fact_snapshot_id", UUID, nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_publish_package_fact_refs"),
        sa.UniqueConstraint(
            "store_id", "publish_package_id", "position",
            name="uq_publish_package_fact_refs_position",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "task_id", "publish_package_id"],
            ["publish_packages.store_id", "publish_packages.task_id", "publish_packages.id"],
            name="fk_publish_package_fact_refs_package_same_task",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "task_id", "business_fact_snapshot_id"],
            ["business_fact_snapshots.store_id", "business_fact_snapshots.task_id", "business_fact_snapshots.id"],
            name="fk_publish_package_fact_refs_fact_same_task",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("position >= 0", name="ck_publish_package_fact_refs_position_nonnegative"),
    )
    op.create_index(
        "ix_publish_package_fact_refs_store_package",
        "publish_package_fact_refs",
        ["store_id", "publish_package_id"],
    )

    op.create_table(
        "publish_confirmations",
        sa.Column("id", UUID, nullable=False),
        sa.Column("store_id", UUID, nullable=False),
        sa.Column("publish_package_id", UUID, nullable=False),
        sa.Column("package_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("confirmed_by_user_id", UUID, nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("confirmation_note", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_publish_confirmations"),
        sa.UniqueConstraint(
            "store_id", "publish_package_id", "package_fingerprint",
            name="uq_publish_confirmations_package_fingerprint",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "publish_package_id", "package_fingerprint"],
            ["publish_packages.store_id", "publish_packages.id", "publish_packages.package_fingerprint"],
            name="fk_publish_confirmations_package_fingerprint_same_store",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["confirmed_by_user_id"], ["users.id"],
            name="fk_publish_confirmations_user",
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_publish_confirmations_store_package_created",
        "publish_confirmations",
        ["store_id", "publish_package_id", "confirmed_at"],
    )

    op.execute(
        """
        CREATE FUNCTION prevent_content_delivery_append_only_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    append_only_tables = (
        "artifact_versions",
        "review_records",
        "channel_content_artifact_refs",
        "quality_reports",
        "quality_resolutions",
        "publish_packages",
        "publish_package_items",
        "publish_package_fact_refs",
        "publish_confirmations",
    )
    for table in append_only_tables:
        op.execute(
            f"CREATE TRIGGER trg_{table}_append_only "
            f"BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION "
            "prevent_content_delivery_append_only_mutation()"
        )

    op.execute(
        """
        CREATE FUNCTION protect_channel_content_snapshot() RETURNS trigger AS $$
        BEGIN
            IF (to_jsonb(NEW) - ARRAY['status', 'updated_at'])
               IS DISTINCT FROM
               (to_jsonb(OLD) - ARRAY['status', 'updated_at']) THEN
                RAISE EXCEPTION 'channel content snapshot fields are immutable';
            END IF;
            IF OLD.status IN ('stale', 'blocked') AND NEW.status <> OLD.status THEN
                RAISE EXCEPTION 'stale or blocked channel content cannot be reactivated';
            END IF;
            IF NEW.status NOT IN ('ready', 'stale', 'blocked') THEN
                RAISE EXCEPTION 'invalid channel content status';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_channel_contents_snapshot_protected
        BEFORE UPDATE ON channel_contents
        FOR EACH ROW EXECUTE FUNCTION protect_channel_content_snapshot();
        """
    )

    op.execute(
        """
        CREATE FUNCTION enforce_channel_content_reviewed_versions() RETURNS trigger AS $$
        DECLARE
            artifact_type text;
        BEGIN
            SELECT a.artifact_type INTO artifact_type
            FROM artifact_versions av
            JOIN artifacts a
              ON a.store_id = av.store_id AND a.id = av.artifact_id
            WHERE av.store_id = NEW.store_id
              AND av.id = NEW.copy_version_id;
            IF artifact_type IS DISTINCT FROM 'copy' THEN
                RAISE EXCEPTION 'channel content requires a copy artifact version';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM review_records rr
                WHERE rr.store_id = NEW.store_id
                  AND rr.artifact_version_id = NEW.copy_version_id
                  AND rr.review_type = 'copy'
                  AND rr.decision = 'approved'
            ) THEN
                RAISE EXCEPTION 'channel content requires an approved copy version';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_channel_contents_require_approved_copy
        BEFORE INSERT ON channel_contents
        FOR EACH ROW EXECUTE FUNCTION enforce_channel_content_reviewed_versions();
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_channel_content_image_refs() RETURNS trigger AS $$
        DECLARE
            artifact_type text;
        BEGIN
            SELECT a.artifact_type INTO artifact_type
            FROM artifact_versions av
            JOIN artifacts a
              ON a.store_id = av.store_id AND a.id = av.artifact_id
            WHERE av.store_id = NEW.store_id
              AND av.id = NEW.artifact_version_id;
            IF artifact_type IS DISTINCT FROM 'image' THEN
                RAISE EXCEPTION 'channel content image reference requires an image artifact version';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM review_records rr
                WHERE rr.store_id = NEW.store_id
                  AND rr.artifact_version_id = NEW.artifact_version_id
                  AND rr.review_type = 'image'
                  AND rr.decision = 'approved'
            ) THEN
                RAISE EXCEPTION 'channel content image reference requires an approved image version';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_channel_content_artifact_refs_require_approved_image
        BEFORE INSERT ON channel_content_artifact_refs
        FOR EACH ROW EXECUTE FUNCTION enforce_channel_content_image_refs();
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_quality_resolution_needs_human() RETURNS trigger AS $$
        DECLARE
            report_result text;
        BEGIN
            SELECT result INTO report_result
            FROM quality_reports
            WHERE store_id = NEW.store_id
              AND id = NEW.quality_report_id
              AND input_fingerprint = NEW.quality_report_fingerprint;
            IF report_result IS DISTINCT FROM 'needs_human' THEN
                RAISE EXCEPTION 'only needs_human quality reports can be resolved';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_quality_resolutions_needs_human_only
        BEFORE INSERT ON quality_resolutions
        FOR EACH ROW EXECUTE FUNCTION enforce_quality_resolution_needs_human();
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_publish_package_item_quality_gate() RETURNS trigger AS $$
        DECLARE
            report_result text;
            report_fingerprint text;
        BEGIN
            SELECT result, input_fingerprint
              INTO report_result, report_fingerprint
            FROM quality_reports
            WHERE store_id = NEW.store_id
              AND channel_content_id = NEW.channel_content_id
              AND id = NEW.quality_report_id;
            IF report_result = 'fail' OR report_result IS NULL THEN
                RAISE EXCEPTION 'publish package requires a passing or accepted quality report';
            END IF;
            IF report_result = 'needs_human' AND NOT EXISTS (
                SELECT 1 FROM quality_resolutions qr
                WHERE qr.store_id = NEW.store_id
                  AND qr.quality_report_id = NEW.quality_report_id
                  AND qr.quality_report_fingerprint = report_fingerprint
                  AND qr.decision = 'accepted'
            ) THEN
                RAISE EXCEPTION 'quality report requires an accepted human resolution';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_publish_package_items_quality_gate
        BEFORE INSERT ON publish_package_items
        FOR EACH ROW EXECUTE FUNCTION enforce_publish_package_item_quality_gate();
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_publish_package_confirmed_facts() RETURNS trigger AS $$
        DECLARE
            fact_status text;
        BEGIN
            SELECT confirmation_status INTO fact_status
            FROM business_fact_snapshots
            WHERE store_id = NEW.store_id
              AND task_id = NEW.task_id
              AND id = NEW.business_fact_snapshot_id;
            IF fact_status IS DISTINCT FROM 'confirmed' THEN
                RAISE EXCEPTION 'publish package facts must be confirmed';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_publish_package_fact_refs_confirmed_only
        BEFORE INSERT ON publish_package_fact_refs
        FOR EACH ROW EXECUTE FUNCTION enforce_publish_package_confirmed_facts();
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_publish_package_complete() RETURNS trigger AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM publish_package_items
                WHERE store_id = NEW.store_id
                  AND publish_package_id = NEW.id
            ) THEN
                RAISE EXCEPTION 'publish package requires at least one item';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM publish_package_fact_refs
                WHERE store_id = NEW.store_id
                  AND publish_package_id = NEW.id
            ) THEN
                RAISE EXCEPTION 'publish package requires confirmed business facts';
            END IF;
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER trg_publish_packages_complete
        AFTER INSERT ON publish_packages
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION enforce_publish_package_complete();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_publish_packages_complete ON publish_packages")
    op.execute("DROP FUNCTION IF EXISTS enforce_publish_package_complete()")
    op.execute("DROP TRIGGER IF EXISTS trg_publish_package_fact_refs_confirmed_only ON publish_package_fact_refs")
    op.execute("DROP FUNCTION IF EXISTS enforce_publish_package_confirmed_facts()")
    op.execute("DROP TRIGGER IF EXISTS trg_publish_package_items_quality_gate ON publish_package_items")
    op.execute("DROP FUNCTION IF EXISTS enforce_publish_package_item_quality_gate()")
    op.execute("DROP TRIGGER IF EXISTS trg_quality_resolutions_needs_human_only ON quality_resolutions")
    op.execute("DROP FUNCTION IF EXISTS enforce_quality_resolution_needs_human()")
    op.execute("DROP TRIGGER IF EXISTS trg_channel_content_artifact_refs_require_approved_image ON channel_content_artifact_refs")
    op.execute("DROP FUNCTION IF EXISTS enforce_channel_content_image_refs()")
    op.execute("DROP TRIGGER IF EXISTS trg_channel_contents_require_approved_copy ON channel_contents")
    op.execute("DROP FUNCTION IF EXISTS enforce_channel_content_reviewed_versions()")
    op.execute("DROP TRIGGER IF EXISTS trg_channel_contents_snapshot_protected ON channel_contents")
    op.execute("DROP FUNCTION IF EXISTS protect_channel_content_snapshot()")
    for table in (
        "artifact_versions",
        "review_records",
        "channel_content_artifact_refs",
        "quality_reports",
        "quality_resolutions",
        "publish_packages",
        "publish_package_items",
        "publish_package_fact_refs",
        "publish_confirmations",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_append_only ON {table}")
    op.execute("DROP FUNCTION IF EXISTS prevent_content_delivery_append_only_mutation()")

    op.drop_index("ix_publish_confirmations_store_package_created", table_name="publish_confirmations")
    op.drop_table("publish_confirmations")
    op.drop_index("ix_publish_package_fact_refs_store_package", table_name="publish_package_fact_refs")
    op.drop_table("publish_package_fact_refs")
    op.drop_index("ix_publish_package_items_store_package", table_name="publish_package_items")
    op.drop_table("publish_package_items")
    op.drop_index("ix_publish_packages_store_task_frozen", table_name="publish_packages")
    op.drop_table("publish_packages")
    op.drop_index("ix_quality_resolutions_store_report_created", table_name="quality_resolutions")
    op.drop_table("quality_resolutions")
    op.drop_index("ix_quality_reports_store_content_created", table_name="quality_reports")
    op.drop_table("quality_reports")
    op.drop_index("ix_channel_content_artifact_refs_content", table_name="channel_content_artifact_refs")
    op.drop_table("channel_content_artifact_refs")
    op.drop_index("ix_channel_contents_store_task_channel", table_name="channel_contents")
    op.drop_table("channel_contents")
    op.drop_constraint(
        "fk_artifact_versions_prompt_version",
        "artifact_versions",
        type_="foreignkey",
    )
    op.drop_constraint(
        "uq_artifact_versions_store_id",
        "artifact_versions",
        type_="unique",
    )
",
            name="ck_quality_reports_input_fingerprint_sha256",
        ),
        sa.CheckConstraint(
            "input_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_quality_reports_input_fingerprint_sha256",
        ),
    )
    op.create_index(
        "ix_quality_reports_store_content_created",
        "quality_reports",
        ["store_id", "channel_content_id", "created_at"],
    )

    op.create_table(
        "quality_resolutions",
        sa.Column("id", UUID, nullable=False),
        sa.Column("store_id", UUID, nullable=False),
        sa.Column("quality_report_id", UUID, nullable=False),
        sa.Column("quality_report_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("reviewer_user_id", UUID, nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_quality_resolutions"),
        sa.UniqueConstraint(
            "store_id", "quality_report_id", "quality_report_fingerprint",
            name="uq_quality_resolutions_report_fingerprint",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "quality_report_id", "quality_report_fingerprint"],
            ["quality_reports.store_id", "quality_reports.id", "quality_reports.input_fingerprint"],
            name="fk_quality_resolutions_report_fingerprint_same_store",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reviewer_user_id"], ["users.id"],
            name="fk_quality_resolutions_reviewer",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "decision IN ('accepted', 'rejected')",
            name="ck_quality_resolutions_decision",
        ),
        sa.CheckConstraint(
            "length(trim(reason)) > 0",
            name="ck_quality_resolutions_reason_required",
        ),
    )
    op.create_index(
        "ix_quality_resolutions_store_report_created",
        "quality_resolutions",
        ["store_id", "quality_report_id", "created_at"],
    )

    op.create_table(
        "publish_packages",
        sa.Column("id", UUID, nullable=False),
        sa.Column("store_id", UUID, nullable=False),
        sa.Column("task_id", UUID, nullable=False),
        sa.Column("package_version", sa.Integer(), nullable=False),
        sa.Column("package_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("frozen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("frozen_by_user_id", UUID, nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_publish_packages"),
        sa.UniqueConstraint(
            "store_id", "task_id", "package_version",
            name="uq_publish_packages_task_version",
        ),
        sa.UniqueConstraint(
            "store_id", "id", "package_fingerprint",
            name="uq_publish_packages_store_id_fingerprint",
        ),
        sa.UniqueConstraint(
            "store_id", "task_id", "id",
            name="uq_publish_packages_store_task_id",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "task_id"],
            ["marketing_tasks.store_id", "marketing_tasks.id"],
            name="fk_publish_packages_task_same_store",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["frozen_by_user_id"], ["users.id"],
            name="fk_publish_packages_frozen_by_user",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint("package_version >= 1", name="ck_publish_packages_package_version_positive"),
        sa.CheckConstraint(
            "package_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_publish_packages_fingerprint_sha256",
        ),
    )
    op.create_index(
        "ix_publish_packages_store_task_frozen",
        "publish_packages",
        ["store_id", "task_id", "frozen_at"],
    )

    op.create_table(
        "publish_package_items",
        sa.Column("id", UUID, nullable=False),
        sa.Column("store_id", UUID, nullable=False),
        sa.Column("publish_package_id", UUID, nullable=False),
        sa.Column("channel_key", sa.String(length=80), nullable=False),
        sa.Column("channel_content_id", UUID, nullable=False),
        sa.Column("quality_report_id", UUID, nullable=False),
        sa.Column("channel_account_id", UUID, nullable=True),
        sa.Column("delivery_mode", sa.String(length=24), nullable=False),
        sa.Column("planned_publish_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("item_fingerprint", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_publish_package_items"),
        sa.UniqueConstraint(
            "store_id", "publish_package_id", "channel_key",
            name="uq_publish_package_items_channel",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "publish_package_id"],
            ["publish_packages.store_id", "publish_packages.id"],
            name="fk_publish_package_items_package_same_store",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "channel_content_id", "channel_key"],
            ["channel_contents.store_id", "channel_contents.id", "channel_contents.channel_key"],
            name="fk_publish_package_items_channel_content_same_store",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "channel_content_id", "quality_report_id"],
            ["quality_reports.store_id", "quality_reports.channel_content_id", "quality_reports.id"],
            name="fk_publish_package_items_quality_report_same_content",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "delivery_mode IN ('official_api', 'manual_handoff')",
            name="ck_publish_package_items_delivery_mode",
        ),
        sa.CheckConstraint(
            "(delivery_mode = 'official_api' AND channel_account_id IS NOT NULL) OR "
            "(delivery_mode = 'manual_handoff' AND channel_account_id IS NULL)",
            name="ck_publish_package_items_channel_account_matches_delivery_mode",
        ),
        sa.CheckConstraint(
            "item_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_publish_package_items_item_fingerprint_sha256",
        ),
    )
    op.create_index(
        "ix_publish_package_items_store_package",
        "publish_package_items",
        ["store_id", "publish_package_id"],
    )

    op.create_table(
        "publish_package_fact_refs",
        sa.Column("id", UUID, nullable=False),
        sa.Column("store_id", UUID, nullable=False),
        sa.Column("task_id", UUID, nullable=False),
        sa.Column("publish_package_id", UUID, nullable=False),
        sa.Column("business_fact_snapshot_id", UUID, nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_publish_package_fact_refs"),
        sa.UniqueConstraint(
            "store_id", "publish_package_id", "position",
            name="uq_publish_package_fact_refs_position",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "task_id", "publish_package_id"],
            ["publish_packages.store_id", "publish_packages.task_id", "publish_packages.id"],
            name="fk_publish_package_fact_refs_package_same_task",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "task_id", "business_fact_snapshot_id"],
            ["business_fact_snapshots.store_id", "business_fact_snapshots.task_id", "business_fact_snapshots.id"],
            name="fk_publish_package_fact_refs_fact_same_task",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("position >= 0", name="ck_publish_package_fact_refs_position_nonnegative"),
    )
    op.create_index(
        "ix_publish_package_fact_refs_store_package",
        "publish_package_fact_refs",
        ["store_id", "publish_package_id"],
    )

    op.create_table(
        "publish_confirmations",
        sa.Column("id", UUID, nullable=False),
        sa.Column("store_id", UUID, nullable=False),
        sa.Column("publish_package_id", UUID, nullable=False),
        sa.Column("package_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("confirmed_by_user_id", UUID, nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("confirmation_note", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_publish_confirmations"),
        sa.UniqueConstraint(
            "store_id", "publish_package_id", "package_fingerprint",
            name="uq_publish_confirmations_package_fingerprint",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "publish_package_id", "package_fingerprint"],
            ["publish_packages.store_id", "publish_packages.id", "publish_packages.package_fingerprint"],
            name="fk_publish_confirmations_package_fingerprint_same_store",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["confirmed_by_user_id"], ["users.id"],
            name="fk_publish_confirmations_user",
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_publish_confirmations_store_package_created",
        "publish_confirmations",
        ["store_id", "publish_package_id", "confirmed_at"],
    )

    op.execute(
        """
        CREATE FUNCTION prevent_content_delivery_append_only_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    append_only_tables = (
        "artifact_versions",
        "review_records",
        "channel_content_artifact_refs",
        "quality_reports",
        "quality_resolutions",
        "publish_packages",
        "publish_package_items",
        "publish_package_fact_refs",
        "publish_confirmations",
    )
    for table in append_only_tables:
        op.execute(
            f"CREATE TRIGGER trg_{table}_append_only "
            f"BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION "
            "prevent_content_delivery_append_only_mutation()"
        )

    op.execute(
        """
        CREATE FUNCTION protect_channel_content_snapshot() RETURNS trigger AS $$
        BEGIN
            IF (to_jsonb(NEW) - ARRAY['status', 'updated_at'])
               IS DISTINCT FROM
               (to_jsonb(OLD) - ARRAY['status', 'updated_at']) THEN
                RAISE EXCEPTION 'channel content snapshot fields are immutable';
            END IF;
            IF OLD.status IN ('stale', 'blocked') AND NEW.status <> OLD.status THEN
                RAISE EXCEPTION 'stale or blocked channel content cannot be reactivated';
            END IF;
            IF NEW.status NOT IN ('ready', 'stale', 'blocked') THEN
                RAISE EXCEPTION 'invalid channel content status';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_channel_contents_snapshot_protected
        BEFORE UPDATE ON channel_contents
        FOR EACH ROW EXECUTE FUNCTION protect_channel_content_snapshot();
        """
    )

    op.execute(
        """
        CREATE FUNCTION enforce_channel_content_reviewed_versions() RETURNS trigger AS $$
        DECLARE
            artifact_type text;
        BEGIN
            SELECT a.artifact_type INTO artifact_type
            FROM artifact_versions av
            JOIN artifacts a
              ON a.store_id = av.store_id AND a.id = av.artifact_id
            WHERE av.store_id = NEW.store_id
              AND av.id = NEW.copy_version_id;
            IF artifact_type IS DISTINCT FROM 'copy' THEN
                RAISE EXCEPTION 'channel content requires a copy artifact version';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM review_records rr
                WHERE rr.store_id = NEW.store_id
                  AND rr.artifact_version_id = NEW.copy_version_id
                  AND rr.review_type = 'copy'
                  AND rr.decision = 'approved'
            ) THEN
                RAISE EXCEPTION 'channel content requires an approved copy version';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_channel_contents_require_approved_copy
        BEFORE INSERT ON channel_contents
        FOR EACH ROW EXECUTE FUNCTION enforce_channel_content_reviewed_versions();
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_channel_content_image_refs() RETURNS trigger AS $$
        DECLARE
            artifact_type text;
        BEGIN
            SELECT a.artifact_type INTO artifact_type
            FROM artifact_versions av
            JOIN artifacts a
              ON a.store_id = av.store_id AND a.id = av.artifact_id
            WHERE av.store_id = NEW.store_id
              AND av.id = NEW.artifact_version_id;
            IF artifact_type IS DISTINCT FROM 'image' THEN
                RAISE EXCEPTION 'channel content image reference requires an image artifact version';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM review_records rr
                WHERE rr.store_id = NEW.store_id
                  AND rr.artifact_version_id = NEW.artifact_version_id
                  AND rr.review_type = 'image'
                  AND rr.decision = 'approved'
            ) THEN
                RAISE EXCEPTION 'channel content image reference requires an approved image version';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_channel_content_artifact_refs_require_approved_image
        BEFORE INSERT ON channel_content_artifact_refs
        FOR EACH ROW EXECUTE FUNCTION enforce_channel_content_image_refs();
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_quality_resolution_needs_human() RETURNS trigger AS $$
        DECLARE
            report_result text;
        BEGIN
            SELECT result INTO report_result
            FROM quality_reports
            WHERE store_id = NEW.store_id
              AND id = NEW.quality_report_id
              AND input_fingerprint = NEW.quality_report_fingerprint;
            IF report_result IS DISTINCT FROM 'needs_human' THEN
                RAISE EXCEPTION 'only needs_human quality reports can be resolved';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_quality_resolutions_needs_human_only
        BEFORE INSERT ON quality_resolutions
        FOR EACH ROW EXECUTE FUNCTION enforce_quality_resolution_needs_human();
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_publish_package_item_quality_gate() RETURNS trigger AS $$
        DECLARE
            report_result text;
            report_fingerprint text;
        BEGIN
            SELECT result, input_fingerprint
              INTO report_result, report_fingerprint
            FROM quality_reports
            WHERE store_id = NEW.store_id
              AND channel_content_id = NEW.channel_content_id
              AND id = NEW.quality_report_id;
            IF report_result = 'fail' OR report_result IS NULL THEN
                RAISE EXCEPTION 'publish package requires a passing or accepted quality report';
            END IF;
            IF report_result = 'needs_human' AND NOT EXISTS (
                SELECT 1 FROM quality_resolutions qr
                WHERE qr.store_id = NEW.store_id
                  AND qr.quality_report_id = NEW.quality_report_id
                  AND qr.quality_report_fingerprint = report_fingerprint
                  AND qr.decision = 'accepted'
            ) THEN
                RAISE EXCEPTION 'quality report requires an accepted human resolution';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_publish_package_items_quality_gate
        BEFORE INSERT ON publish_package_items
        FOR EACH ROW EXECUTE FUNCTION enforce_publish_package_item_quality_gate();
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_publish_package_confirmed_facts() RETURNS trigger AS $$
        DECLARE
            fact_status text;
        BEGIN
            SELECT confirmation_status INTO fact_status
            FROM business_fact_snapshots
            WHERE store_id = NEW.store_id
              AND task_id = NEW.task_id
              AND id = NEW.business_fact_snapshot_id;
            IF fact_status IS DISTINCT FROM 'confirmed' THEN
                RAISE EXCEPTION 'publish package facts must be confirmed';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_publish_package_fact_refs_confirmed_only
        BEFORE INSERT ON publish_package_fact_refs
        FOR EACH ROW EXECUTE FUNCTION enforce_publish_package_confirmed_facts();
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_publish_package_complete() RETURNS trigger AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM publish_package_items
                WHERE store_id = NEW.store_id
                  AND publish_package_id = NEW.id
            ) THEN
                RAISE EXCEPTION 'publish package requires at least one item';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM publish_package_fact_refs
                WHERE store_id = NEW.store_id
                  AND publish_package_id = NEW.id
            ) THEN
                RAISE EXCEPTION 'publish package requires confirmed business facts';
            END IF;
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER trg_publish_packages_complete
        AFTER INSERT ON publish_packages
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION enforce_publish_package_complete();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_publish_packages_complete ON publish_packages")
    op.execute("DROP FUNCTION IF EXISTS enforce_publish_package_complete()")
    op.execute("DROP TRIGGER IF EXISTS trg_publish_package_fact_refs_confirmed_only ON publish_package_fact_refs")
    op.execute("DROP FUNCTION IF EXISTS enforce_publish_package_confirmed_facts()")
    op.execute("DROP TRIGGER IF EXISTS trg_publish_package_items_quality_gate ON publish_package_items")
    op.execute("DROP FUNCTION IF EXISTS enforce_publish_package_item_quality_gate()")
    op.execute("DROP TRIGGER IF EXISTS trg_quality_resolutions_needs_human_only ON quality_resolutions")
    op.execute("DROP FUNCTION IF EXISTS enforce_quality_resolution_needs_human()")
    op.execute("DROP TRIGGER IF EXISTS trg_channel_content_artifact_refs_require_approved_image ON channel_content_artifact_refs")
    op.execute("DROP FUNCTION IF EXISTS enforce_channel_content_image_refs()")
    op.execute("DROP TRIGGER IF EXISTS trg_channel_contents_require_approved_copy ON channel_contents")
    op.execute("DROP FUNCTION IF EXISTS enforce_channel_content_reviewed_versions()")
    op.execute("DROP TRIGGER IF EXISTS trg_channel_contents_snapshot_protected ON channel_contents")
    op.execute("DROP FUNCTION IF EXISTS protect_channel_content_snapshot()")
    for table in (
        "artifact_versions",
        "review_records",
        "channel_content_artifact_refs",
        "quality_reports",
        "quality_resolutions",
        "publish_packages",
        "publish_package_items",
        "publish_package_fact_refs",
        "publish_confirmations",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_append_only ON {table}")
    op.execute("DROP FUNCTION IF EXISTS prevent_content_delivery_append_only_mutation()")

    op.drop_index("ix_publish_confirmations_store_package_created", table_name="publish_confirmations")
    op.drop_table("publish_confirmations")
    op.drop_index("ix_publish_package_fact_refs_store_package", table_name="publish_package_fact_refs")
    op.drop_table("publish_package_fact_refs")
    op.drop_index("ix_publish_package_items_store_package", table_name="publish_package_items")
    op.drop_table("publish_package_items")
    op.drop_index("ix_publish_packages_store_task_frozen", table_name="publish_packages")
    op.drop_table("publish_packages")
    op.drop_index("ix_quality_resolutions_store_report_created", table_name="quality_resolutions")
    op.drop_table("quality_resolutions")
    op.drop_index("ix_quality_reports_store_content_created", table_name="quality_reports")
    op.drop_table("quality_reports")
    op.drop_index("ix_channel_content_artifact_refs_content", table_name="channel_content_artifact_refs")
    op.drop_table("channel_content_artifact_refs")
    op.drop_index("ix_channel_contents_store_task_channel", table_name="channel_contents")
    op.drop_table("channel_contents")
    op.drop_constraint(
        "fk_artifact_versions_prompt_version",
        "artifact_versions",
        type_="foreignkey",
    )
    op.drop_constraint(
        "uq_artifact_versions_store_id",
        "artifact_versions",
        type_="unique",
    )
",
            name="ck_channel_contents_input_fingerprint_sha256",
        ),
        sa.CheckConstraint(
            "input_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_channel_contents_input_fingerprint_sha256",
        ),
    )
    op.create_index(
        "ix_channel_contents_store_task_channel",
        "channel_contents",
        ["store_id", "task_id", "channel_key", "created_at"],
    )

    op.create_table(
        "channel_content_artifact_refs",
        sa.Column("id", UUID, nullable=False),
        sa.Column("store_id", UUID, nullable=False),
        sa.Column("channel_content_id", UUID, nullable=False),
        sa.Column("artifact_version_id", UUID, nullable=False),
        sa.Column("role", sa.String(length=16), server_default="image", nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_channel_content_artifact_refs"),
        sa.UniqueConstraint(
            "store_id", "channel_content_id", "position",
            name="uq_channel_content_artifact_refs_position",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "channel_content_id"],
            ["channel_contents.store_id", "channel_contents.id"],
            name="fk_channel_content_artifact_refs_content_same_store",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "artifact_version_id"],
            ["artifact_versions.store_id", "artifact_versions.id"],
            name="fk_channel_content_artifact_refs_version_same_store",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("role = 'image'", name="ck_channel_content_artifact_refs_role_image_only"),
        sa.CheckConstraint("position >= 0", name="ck_channel_content_artifact_refs_position_nonnegative"),
    )
    op.create_index(
        "ix_channel_content_artifact_refs_content",
        "channel_content_artifact_refs",
        ["store_id", "channel_content_id", "position"],
    )

    op.create_table(
        "quality_reports",
        sa.Column("id", UUID, nullable=False),
        sa.Column("store_id", UUID, nullable=False),
        sa.Column("task_id", UUID, nullable=False),
        sa.Column("channel_content_id", UUID, nullable=False),
        sa.Column("rule_version", sa.String(length=80), nullable=False),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("result", sa.String(length=16), nullable=False),
        sa.Column("issues_json", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_quality_reports"),
        sa.UniqueConstraint("store_id", "id", name="uq_quality_reports_store_id"),
        sa.UniqueConstraint(
            "store_id", "id", "input_fingerprint",
            name="uq_quality_reports_store_id_fingerprint",
        ),
        sa.UniqueConstraint(
            "store_id", "channel_content_id", "id",
            name="uq_quality_reports_content_id",
        ),
        sa.UniqueConstraint(
            "store_id", "channel_content_id", "rule_version", "input_fingerprint",
            name="uq_quality_reports_content_rule_fingerprint",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "task_id", "channel_content_id"],
            ["channel_contents.store_id", "channel_contents.task_id", "channel_contents.id"],
            name="fk_quality_reports_channel_content_same_task_store",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "result IN ('pass', 'fail', 'needs_human')",
            name="ck_quality_reports_result",
        ),
        sa.CheckConstraint(
            "length(trim(rule_version)) > 0",
            name="ck_quality_reports_rule_version_required",
        ),
        sa.CheckConstraint(
            "input_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_quality_reports_input_fingerprint_sha256",
        ),
    )
    op.create_index(
        "ix_quality_reports_store_content_created",
        "quality_reports",
        ["store_id", "channel_content_id", "created_at"],
    )

    op.create_table(
        "quality_resolutions",
        sa.Column("id", UUID, nullable=False),
        sa.Column("store_id", UUID, nullable=False),
        sa.Column("quality_report_id", UUID, nullable=False),
        sa.Column("quality_report_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("reviewer_user_id", UUID, nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_quality_resolutions"),
        sa.UniqueConstraint(
            "store_id", "quality_report_id", "quality_report_fingerprint",
            name="uq_quality_resolutions_report_fingerprint",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "quality_report_id", "quality_report_fingerprint"],
            ["quality_reports.store_id", "quality_reports.id", "quality_reports.input_fingerprint"],
            name="fk_quality_resolutions_report_fingerprint_same_store",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reviewer_user_id"], ["users.id"],
            name="fk_quality_resolutions_reviewer",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "decision IN ('accepted', 'rejected')",
            name="ck_quality_resolutions_decision",
        ),
        sa.CheckConstraint(
            "length(trim(reason)) > 0",
            name="ck_quality_resolutions_reason_required",
        ),
    )
    op.create_index(
        "ix_quality_resolutions_store_report_created",
        "quality_resolutions",
        ["store_id", "quality_report_id", "created_at"],
    )

    op.create_table(
        "publish_packages",
        sa.Column("id", UUID, nullable=False),
        sa.Column("store_id", UUID, nullable=False),
        sa.Column("task_id", UUID, nullable=False),
        sa.Column("package_version", sa.Integer(), nullable=False),
        sa.Column("package_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("frozen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("frozen_by_user_id", UUID, nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_publish_packages"),
        sa.UniqueConstraint(
            "store_id", "task_id", "package_version",
            name="uq_publish_packages_task_version",
        ),
        sa.UniqueConstraint(
            "store_id", "id", "package_fingerprint",
            name="uq_publish_packages_store_id_fingerprint",
        ),
        sa.UniqueConstraint(
            "store_id", "task_id", "id",
            name="uq_publish_packages_store_task_id",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "task_id"],
            ["marketing_tasks.store_id", "marketing_tasks.id"],
            name="fk_publish_packages_task_same_store",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["frozen_by_user_id"], ["users.id"],
            name="fk_publish_packages_frozen_by_user",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint("package_version >= 1", name="ck_publish_packages_package_version_positive"),
        sa.CheckConstraint(
            "package_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_publish_packages_fingerprint_sha256",
        ),
    )
    op.create_index(
        "ix_publish_packages_store_task_frozen",
        "publish_packages",
        ["store_id", "task_id", "frozen_at"],
    )

    op.create_table(
        "publish_package_items",
        sa.Column("id", UUID, nullable=False),
        sa.Column("store_id", UUID, nullable=False),
        sa.Column("publish_package_id", UUID, nullable=False),
        sa.Column("channel_key", sa.String(length=80), nullable=False),
        sa.Column("channel_content_id", UUID, nullable=False),
        sa.Column("quality_report_id", UUID, nullable=False),
        sa.Column("channel_account_id", UUID, nullable=True),
        sa.Column("delivery_mode", sa.String(length=24), nullable=False),
        sa.Column("planned_publish_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("item_fingerprint", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_publish_package_items"),
        sa.UniqueConstraint(
            "store_id", "publish_package_id", "channel_key",
            name="uq_publish_package_items_channel",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "publish_package_id"],
            ["publish_packages.store_id", "publish_packages.id"],
            name="fk_publish_package_items_package_same_store",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "channel_content_id", "channel_key"],
            ["channel_contents.store_id", "channel_contents.id", "channel_contents.channel_key"],
            name="fk_publish_package_items_channel_content_same_store",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "channel_content_id", "quality_report_id"],
            ["quality_reports.store_id", "quality_reports.channel_content_id", "quality_reports.id"],
            name="fk_publish_package_items_quality_report_same_content",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "delivery_mode IN ('official_api', 'manual_handoff')",
            name="ck_publish_package_items_delivery_mode",
        ),
        sa.CheckConstraint(
            "(delivery_mode = 'official_api' AND channel_account_id IS NOT NULL) OR "
            "(delivery_mode = 'manual_handoff' AND channel_account_id IS NULL)",
            name="ck_publish_package_items_channel_account_matches_delivery_mode",
        ),
        sa.CheckConstraint(
            "item_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_publish_package_items_item_fingerprint_sha256",
        ),
    )
    op.create_index(
        "ix_publish_package_items_store_package",
        "publish_package_items",
        ["store_id", "publish_package_id"],
    )

    op.create_table(
        "publish_package_fact_refs",
        sa.Column("id", UUID, nullable=False),
        sa.Column("store_id", UUID, nullable=False),
        sa.Column("task_id", UUID, nullable=False),
        sa.Column("publish_package_id", UUID, nullable=False),
        sa.Column("business_fact_snapshot_id", UUID, nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_publish_package_fact_refs"),
        sa.UniqueConstraint(
            "store_id", "publish_package_id", "position",
            name="uq_publish_package_fact_refs_position",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "task_id", "publish_package_id"],
            ["publish_packages.store_id", "publish_packages.task_id", "publish_packages.id"],
            name="fk_publish_package_fact_refs_package_same_task",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "task_id", "business_fact_snapshot_id"],
            ["business_fact_snapshots.store_id", "business_fact_snapshots.task_id", "business_fact_snapshots.id"],
            name="fk_publish_package_fact_refs_fact_same_task",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("position >= 0", name="ck_publish_package_fact_refs_position_nonnegative"),
    )
    op.create_index(
        "ix_publish_package_fact_refs_store_package",
        "publish_package_fact_refs",
        ["store_id", "publish_package_id"],
    )

    op.create_table(
        "publish_confirmations",
        sa.Column("id", UUID, nullable=False),
        sa.Column("store_id", UUID, nullable=False),
        sa.Column("publish_package_id", UUID, nullable=False),
        sa.Column("package_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("confirmed_by_user_id", UUID, nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("confirmation_note", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_publish_confirmations"),
        sa.UniqueConstraint(
            "store_id", "publish_package_id", "package_fingerprint",
            name="uq_publish_confirmations_package_fingerprint",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "publish_package_id", "package_fingerprint"],
            ["publish_packages.store_id", "publish_packages.id", "publish_packages.package_fingerprint"],
            name="fk_publish_confirmations_package_fingerprint_same_store",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["confirmed_by_user_id"], ["users.id"],
            name="fk_publish_confirmations_user",
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_publish_confirmations_store_package_created",
        "publish_confirmations",
        ["store_id", "publish_package_id", "confirmed_at"],
    )

    op.execute(
        """
        CREATE FUNCTION prevent_content_delivery_append_only_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    append_only_tables = (
        "artifact_versions",
        "review_records",
        "channel_content_artifact_refs",
        "quality_reports",
        "quality_resolutions",
        "publish_packages",
        "publish_package_items",
        "publish_package_fact_refs",
        "publish_confirmations",
    )
    for table in append_only_tables:
        op.execute(
            f"CREATE TRIGGER trg_{table}_append_only "
            f"BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION "
            "prevent_content_delivery_append_only_mutation()"
        )

    op.execute(
        """
        CREATE FUNCTION protect_channel_content_snapshot() RETURNS trigger AS $$
        BEGIN
            IF (to_jsonb(NEW) - ARRAY['status', 'updated_at'])
               IS DISTINCT FROM
               (to_jsonb(OLD) - ARRAY['status', 'updated_at']) THEN
                RAISE EXCEPTION 'channel content snapshot fields are immutable';
            END IF;
            IF OLD.status IN ('stale', 'blocked') AND NEW.status <> OLD.status THEN
                RAISE EXCEPTION 'stale or blocked channel content cannot be reactivated';
            END IF;
            IF NEW.status NOT IN ('ready', 'stale', 'blocked') THEN
                RAISE EXCEPTION 'invalid channel content status';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_channel_contents_snapshot_protected
        BEFORE UPDATE ON channel_contents
        FOR EACH ROW EXECUTE FUNCTION protect_channel_content_snapshot();
        """
    )

    op.execute(
        """
        CREATE FUNCTION enforce_channel_content_reviewed_versions() RETURNS trigger AS $$
        DECLARE
            artifact_type text;
        BEGIN
            SELECT a.artifact_type INTO artifact_type
            FROM artifact_versions av
            JOIN artifacts a
              ON a.store_id = av.store_id AND a.id = av.artifact_id
            WHERE av.store_id = NEW.store_id
              AND av.id = NEW.copy_version_id;
            IF artifact_type IS DISTINCT FROM 'copy' THEN
                RAISE EXCEPTION 'channel content requires a copy artifact version';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM review_records rr
                WHERE rr.store_id = NEW.store_id
                  AND rr.artifact_version_id = NEW.copy_version_id
                  AND rr.review_type = 'copy'
                  AND rr.decision = 'approved'
            ) THEN
                RAISE EXCEPTION 'channel content requires an approved copy version';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_channel_contents_require_approved_copy
        BEFORE INSERT ON channel_contents
        FOR EACH ROW EXECUTE FUNCTION enforce_channel_content_reviewed_versions();
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_channel_content_image_refs() RETURNS trigger AS $$
        DECLARE
            artifact_type text;
        BEGIN
            SELECT a.artifact_type INTO artifact_type
            FROM artifact_versions av
            JOIN artifacts a
              ON a.store_id = av.store_id AND a.id = av.artifact_id
            WHERE av.store_id = NEW.store_id
              AND av.id = NEW.artifact_version_id;
            IF artifact_type IS DISTINCT FROM 'image' THEN
                RAISE EXCEPTION 'channel content image reference requires an image artifact version';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM review_records rr
                WHERE rr.store_id = NEW.store_id
                  AND rr.artifact_version_id = NEW.artifact_version_id
                  AND rr.review_type = 'image'
                  AND rr.decision = 'approved'
            ) THEN
                RAISE EXCEPTION 'channel content image reference requires an approved image version';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_channel_content_artifact_refs_require_approved_image
        BEFORE INSERT ON channel_content_artifact_refs
        FOR EACH ROW EXECUTE FUNCTION enforce_channel_content_image_refs();
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_quality_resolution_needs_human() RETURNS trigger AS $$
        DECLARE
            report_result text;
        BEGIN
            SELECT result INTO report_result
            FROM quality_reports
            WHERE store_id = NEW.store_id
              AND id = NEW.quality_report_id
              AND input_fingerprint = NEW.quality_report_fingerprint;
            IF report_result IS DISTINCT FROM 'needs_human' THEN
                RAISE EXCEPTION 'only needs_human quality reports can be resolved';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_quality_resolutions_needs_human_only
        BEFORE INSERT ON quality_resolutions
        FOR EACH ROW EXECUTE FUNCTION enforce_quality_resolution_needs_human();
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_publish_package_item_quality_gate() RETURNS trigger AS $$
        DECLARE
            report_result text;
            report_fingerprint text;
        BEGIN
            SELECT result, input_fingerprint
              INTO report_result, report_fingerprint
            FROM quality_reports
            WHERE store_id = NEW.store_id
              AND channel_content_id = NEW.channel_content_id
              AND id = NEW.quality_report_id;
            IF report_result = 'fail' OR report_result IS NULL THEN
                RAISE EXCEPTION 'publish package requires a passing or accepted quality report';
            END IF;
            IF report_result = 'needs_human' AND NOT EXISTS (
                SELECT 1 FROM quality_resolutions qr
                WHERE qr.store_id = NEW.store_id
                  AND qr.quality_report_id = NEW.quality_report_id
                  AND qr.quality_report_fingerprint = report_fingerprint
                  AND qr.decision = 'accepted'
            ) THEN
                RAISE EXCEPTION 'quality report requires an accepted human resolution';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_publish_package_items_quality_gate
        BEFORE INSERT ON publish_package_items
        FOR EACH ROW EXECUTE FUNCTION enforce_publish_package_item_quality_gate();
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_publish_package_confirmed_facts() RETURNS trigger AS $$
        DECLARE
            fact_status text;
        BEGIN
            SELECT confirmation_status INTO fact_status
            FROM business_fact_snapshots
            WHERE store_id = NEW.store_id
              AND task_id = NEW.task_id
              AND id = NEW.business_fact_snapshot_id;
            IF fact_status IS DISTINCT FROM 'confirmed' THEN
                RAISE EXCEPTION 'publish package facts must be confirmed';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_publish_package_fact_refs_confirmed_only
        BEFORE INSERT ON publish_package_fact_refs
        FOR EACH ROW EXECUTE FUNCTION enforce_publish_package_confirmed_facts();
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_publish_package_complete() RETURNS trigger AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM publish_package_items
                WHERE store_id = NEW.store_id
                  AND publish_package_id = NEW.id
            ) THEN
                RAISE EXCEPTION 'publish package requires at least one item';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM publish_package_fact_refs
                WHERE store_id = NEW.store_id
                  AND publish_package_id = NEW.id
            ) THEN
                RAISE EXCEPTION 'publish package requires confirmed business facts';
            END IF;
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER trg_publish_packages_complete
        AFTER INSERT ON publish_packages
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION enforce_publish_package_complete();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_publish_packages_complete ON publish_packages")
    op.execute("DROP FUNCTION IF EXISTS enforce_publish_package_complete()")
    op.execute("DROP TRIGGER IF EXISTS trg_publish_package_fact_refs_confirmed_only ON publish_package_fact_refs")
    op.execute("DROP FUNCTION IF EXISTS enforce_publish_package_confirmed_facts()")
    op.execute("DROP TRIGGER IF EXISTS trg_publish_package_items_quality_gate ON publish_package_items")
    op.execute("DROP FUNCTION IF EXISTS enforce_publish_package_item_quality_gate()")
    op.execute("DROP TRIGGER IF EXISTS trg_quality_resolutions_needs_human_only ON quality_resolutions")
    op.execute("DROP FUNCTION IF EXISTS enforce_quality_resolution_needs_human()")
    op.execute("DROP TRIGGER IF EXISTS trg_channel_content_artifact_refs_require_approved_image ON channel_content_artifact_refs")
    op.execute("DROP FUNCTION IF EXISTS enforce_channel_content_image_refs()")
    op.execute("DROP TRIGGER IF EXISTS trg_channel_contents_require_approved_copy ON channel_contents")
    op.execute("DROP FUNCTION IF EXISTS enforce_channel_content_reviewed_versions()")
    op.execute("DROP TRIGGER IF EXISTS trg_channel_contents_snapshot_protected ON channel_contents")
    op.execute("DROP FUNCTION IF EXISTS protect_channel_content_snapshot()")
    for table in (
        "artifact_versions",
        "review_records",
        "channel_content_artifact_refs",
        "quality_reports",
        "quality_resolutions",
        "publish_packages",
        "publish_package_items",
        "publish_package_fact_refs",
        "publish_confirmations",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_append_only ON {table}")
    op.execute("DROP FUNCTION IF EXISTS prevent_content_delivery_append_only_mutation()")

    op.drop_index("ix_publish_confirmations_store_package_created", table_name="publish_confirmations")
    op.drop_table("publish_confirmations")
    op.drop_index("ix_publish_package_fact_refs_store_package", table_name="publish_package_fact_refs")
    op.drop_table("publish_package_fact_refs")
    op.drop_index("ix_publish_package_items_store_package", table_name="publish_package_items")
    op.drop_table("publish_package_items")
    op.drop_index("ix_publish_packages_store_task_frozen", table_name="publish_packages")
    op.drop_table("publish_packages")
    op.drop_index("ix_quality_resolutions_store_report_created", table_name="quality_resolutions")
    op.drop_table("quality_resolutions")
    op.drop_index("ix_quality_reports_store_content_created", table_name="quality_reports")
    op.drop_table("quality_reports")
    op.drop_index("ix_channel_content_artifact_refs_content", table_name="channel_content_artifact_refs")
    op.drop_table("channel_content_artifact_refs")
    op.drop_index("ix_channel_contents_store_task_channel", table_name="channel_contents")
    op.drop_table("channel_contents")
    op.drop_constraint(
        "fk_artifact_versions_prompt_version",
        "artifact_versions",
        type_="foreignkey",
    )
    op.drop_constraint(
        "uq_artifact_versions_store_id",
        "artifact_versions",
        type_="unique",
    )
