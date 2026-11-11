"""Add global prompt templates, immutable published versions and activation history.

Revision ID: 0011_prompt_versioning
Revises: 0010_content_artifact_review
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011_prompt_versioning"
down_revision: str | None = "0010_content_artifact_review"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB


def upgrade() -> None:
    op.create_table(
        "prompt_templates",
        sa.Column("id", UUID, nullable=False),
        sa.Column("template_key", sa.String(length=120), nullable=False),
        sa.Column("display_name", sa.String(length=160), nullable=False),
        sa.Column("industry_key", sa.String(length=80), nullable=False),
        sa.Column("task_type", sa.String(length=80), nullable=False),
        sa.Column("capability", sa.String(length=16), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="active", nullable=False),
        sa.Column("current_published_version_id", UUID, nullable=True),
        sa.Column("created_by_user_id", UUID, nullable=True),
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
        sa.PrimaryKeyConstraint("id", name="pk_prompt_templates"),
        sa.UniqueConstraint(
            "industry_key", "task_type", "capability", "template_key",
            name="uq_prompt_templates_scope_key",
        ),
        sa.UniqueConstraint(
            "id", "current_published_version_id",
            name="uq_prompt_templates_current_version",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"],
            name="fk_prompt_templates_created_by_user",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'archived')",
            name="ck_prompt_templates_status",
        ),
        sa.CheckConstraint(
            "capability IN ('text', 'image', 'vision', 'ocr')",
            name="ck_prompt_templates_capability",
        ),
    )
    op.create_index(
        "ix_prompt_templates_status_industry",
        "prompt_templates",
        ["status", "industry_key", "task_type"],
    )

    op.create_table(
        "prompt_versions",
        sa.Column("id", UUID, nullable=False),
        sa.Column("prompt_template_id", UUID, nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=False),
        sa.Column("user_prompt_template", sa.Text(), nullable=False),
        sa.Column("variables_schema_json", JSONB, nullable=False),
        sa.Column("output_schema_json", JSONB, nullable=False),
        sa.Column("schema_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("input_policy_json", JSONB, nullable=False),
        sa.Column("changelog", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="draft", nullable=False),
        sa.Column("created_by_user_id", UUID, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("published_by_user_id", UUID, nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_prompt_versions"),
        sa.UniqueConstraint(
            "prompt_template_id", "version_no",
            name="uq_prompt_versions_template_version",
        ),
        sa.UniqueConstraint(
            "prompt_template_id", "id",
            name="uq_prompt_versions_template_id",
        ),
        sa.ForeignKeyConstraint(
            ["prompt_template_id"], ["prompt_templates.id"],
            name="fk_prompt_versions_template",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"],
            name="fk_prompt_versions_created_by_user",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["published_by_user_id"], ["users.id"],
            name="fk_prompt_versions_published_by_user",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("version_no >= 1", name="ck_prompt_versions_version_no_positive"),
        sa.CheckConstraint(
            "schema_version >= 1",
            name="ck_prompt_versions_schema_version_positive",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'published')",
            name="ck_prompt_versions_status",
        ),
        sa.CheckConstraint(
            "status <> 'published' OR "
            "(published_by_user_id IS NOT NULL AND published_at IS NOT NULL)",
            name="ck_prompt_versions_published_metadata_required",
        ),
        sa.CheckConstraint(
            "length(trim(changelog)) > 0",
            name="ck_prompt_versions_changelog_required",
        ),
    )
    op.create_index(
        "ix_prompt_versions_template_status",
        "prompt_versions",
        ["prompt_template_id", "status", "version_no"],
    )
    op.create_foreign_key(
        "fk_prompt_templates_current_version_same_template",
        "prompt_templates",
        "prompt_versions",
        ["id", "current_published_version_id"],
        ["prompt_template_id", "id"],
        deferrable=True,
        initially="DEFERRED",
    )

    op.create_table(
        "prompt_activations",
        sa.Column("id", UUID, nullable=False),
        sa.Column("prompt_template_id", UUID, nullable=False),
        sa.Column("activated_version_id", UUID, nullable=False),
        sa.Column("previous_version_id", UUID, nullable=True),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("actor_user_id", UUID, nullable=True),
        sa.Column("idempotency_key_hash", sa.String(length=64), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_prompt_activations"),
        sa.UniqueConstraint(
            "idempotency_key_hash",
            name="uq_prompt_activations_idempotency_hash",
        ),
        sa.ForeignKeyConstraint(
            ["prompt_template_id", "activated_version_id"],
            ["prompt_versions.prompt_template_id", "prompt_versions.id"],
            name="fk_prompt_activations_activated_version_same_template",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["prompt_template_id", "previous_version_id"],
            ["prompt_versions.prompt_template_id", "prompt_versions.id"],
            name="fk_prompt_activations_previous_version_same_template",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"], ["users.id"],
            name="fk_prompt_activations_actor_user",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "action IN ('publish', 'rollback')",
            name="ck_prompt_activations_action",
        ),
        sa.CheckConstraint(
            "length(trim(reason)) > 0",
            name="ck_prompt_activations_reason_required",
        ),
        sa.CheckConstraint(
            "idempotency_key_hash ~ '^[0-9a-f]{64}$' AND request_hash ~ '^[0-9a-f]{64}$'",
            name="ck_prompt_activations_hashes",
        ),
    )
    op.create_index(
        "ix_prompt_activations_template_created",
        "prompt_activations",
        ["prompt_template_id", "created_at"],
    )

    op.execute(
        """
        CREATE FUNCTION prevent_published_prompt_version_mutation() RETURNS trigger AS $$
        BEGIN
            IF OLD.status = 'published' THEN
                RAISE EXCEPTION 'published prompt versions are immutable';
            END IF;
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_prompt_versions_published_immutable
        BEFORE UPDATE OR DELETE ON prompt_versions
        FOR EACH ROW EXECUTE FUNCTION prevent_published_prompt_version_mutation();
        """
    )
    op.execute(
        """
        CREATE FUNCTION prevent_prompt_activation_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'prompt activation history is append-only';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_prompt_activations_append_only
        BEFORE UPDATE OR DELETE ON prompt_activations
        FOR EACH ROW EXECUTE FUNCTION prevent_prompt_activation_mutation();
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_prompt_activation_published_versions() RETURNS trigger AS $$
        DECLARE
            activated_status text;
            previous_status text;
        BEGIN
            SELECT status INTO activated_status
            FROM prompt_versions
            WHERE prompt_template_id = NEW.prompt_template_id
              AND id = NEW.activated_version_id;
            IF activated_status IS DISTINCT FROM 'published' THEN
                RAISE EXCEPTION 'only published prompt versions can be activated';
            END IF;
            IF NEW.previous_version_id IS NOT NULL THEN
                SELECT status INTO previous_status
                FROM prompt_versions
                WHERE prompt_template_id = NEW.prompt_template_id
                  AND id = NEW.previous_version_id;
                IF previous_status IS DISTINCT FROM 'published' THEN
                    RAISE EXCEPTION 'previous prompt version must be published';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_prompt_activations_require_published
        BEFORE INSERT ON prompt_activations
        FOR EACH ROW EXECUTE FUNCTION enforce_prompt_activation_published_versions();
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_prompt_template_published_pointer() RETURNS trigger AS $$
        DECLARE
            version_status text;
        BEGIN
            IF NEW.current_published_version_id IS NULL THEN
                RETURN NEW;
            END IF;
            SELECT status INTO version_status
            FROM prompt_versions
            WHERE prompt_template_id = NEW.id
              AND id = NEW.current_published_version_id;
            IF version_status IS DISTINCT FROM 'published' THEN
                RAISE EXCEPTION 'current prompt version must be published';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_prompt_templates_published_pointer
        BEFORE INSERT OR UPDATE OF current_published_version_id ON prompt_templates
        FOR EACH ROW EXECUTE FUNCTION enforce_prompt_template_published_pointer();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_prompt_templates_published_pointer ON prompt_templates")
    op.execute("DROP FUNCTION IF EXISTS enforce_prompt_template_published_pointer()")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_prompt_activations_require_published "
        "ON prompt_activations"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_prompt_activation_published_versions()")
    op.execute("DROP TRIGGER IF EXISTS trg_prompt_activations_append_only ON prompt_activations")
    op.execute("DROP FUNCTION IF EXISTS prevent_prompt_activation_mutation()")
    op.execute("DROP TRIGGER IF EXISTS trg_prompt_versions_published_immutable ON prompt_versions")
    op.execute("DROP FUNCTION IF EXISTS prevent_published_prompt_version_mutation()")
    op.drop_index("ix_prompt_activations_template_created", table_name="prompt_activations")
    op.drop_table("prompt_activations")
    op.drop_constraint(
        "fk_prompt_templates_current_version_same_template",
        "prompt_templates",
        type_="foreignkey",
    )
    op.drop_index("ix_prompt_versions_template_status", table_name="prompt_versions")
    op.drop_table("prompt_versions")
    op.drop_index("ix_prompt_templates_status_industry", table_name="prompt_templates")
    op.drop_table("prompt_templates")
