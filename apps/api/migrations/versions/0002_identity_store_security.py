"""Identity, StoreMembership, Session, PlatformAdminGrant and AuditEvent.

Revision ID: 0002_identity_store_security
Revises: 0001_initial_baseline
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_identity_store_security"
down_revision: str | None = "0001_initial_baseline"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("email_normalized", sa.String(320), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("status", sa.String(16), server_default="active", nullable=False),
        sa.Column("email_verified_at", sa.DateTime(timezone=True)),
        sa.Column(
            "password_changed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("auth_version", sa.Integer(), server_default="1", nullable=False),
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
        sa.UniqueConstraint("email_normalized", name="uq_users_email_normalized"),
        sa.CheckConstraint("status IN ('active', 'locked', 'disabled')", name="ck_users_status"),
        sa.CheckConstraint(
            "email_normalized = lower(email_normalized)",
            name="ck_users_email_normalized_lower",
        ),
    )
    op.create_table(
        "stores",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), server_default="active", nullable=False),
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
        sa.CheckConstraint("status IN ('active', 'suspended', 'closed')", name="ck_stores_status"),
    )
    op.create_table(
        "store_memberships",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "store_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("stores.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), server_default="invited", nullable=False),
        sa.Column(
            "invited_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column("joined_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
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
        sa.UniqueConstraint("store_id", "user_id", name="uq_store_memberships_store_user"),
        sa.CheckConstraint("role IN ('owner', 'member')", name="ck_store_memberships_role"),
        sa.CheckConstraint(
            "status IN ('invited', 'active', 'suspended', 'removed')",
            name="ck_store_memberships_status",
        ),
    )
    op.create_index("ix_store_memberships_user_status", "store_memberships", ["user_id", "status"])
    op.create_index(
        "ix_store_memberships_store_status",
        "store_memberships",
        ["store_id", "status"],
    )

    op.create_table(
        "sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("csrf_token_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("auth_version", sa.Integer(), nullable=False),
        sa.Column(
            "active_store_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("stores.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("idle_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "rotated_from_session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sessions.id", ondelete="SET NULL"),
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("revoke_reason", sa.String(64)),
        sa.Column("ip_fingerprint", sa.String(64)),
        sa.Column("user_agent", sa.String(512)),
        sa.UniqueConstraint("token_hash", name="uq_sessions_token_hash"),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])
    op.create_index("ix_sessions_expires_at", "sessions", ["expires_at"])

    op.create_table(
        "platform_admin_grants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", sa.String(16), server_default="active", nullable=False),
        sa.Column(
            "granted_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "granted_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("reason_code", sa.String(120), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("user_id", name="uq_platform_admin_grants_user_id"),
        sa.CheckConstraint(
            "status IN ('active', 'revoked')",
            name="ck_platform_admin_grants_status",
        ),
    )

    op.create_table(
        "audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("actor_type", sa.String(24), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True)),
        sa.Column(
            "actor_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "store_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("stores.id", ondelete="SET NULL"),
        ),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("target_type", sa.String(80), nullable=False),
        sa.Column("target_id", sa.String(128)),
        sa.Column("result", sa.String(16), nullable=False),
        sa.Column("request_id", sa.String(128), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "actor_type IN ('user', 'platform_admin', 'system')",
            name="ck_audit_events_actor_type",
        ),
        sa.CheckConstraint(
            "result IN ('success', 'denied', 'failed')",
            name="ck_audit_events_result",
        ),
    )
    op.create_index("ix_audit_events_store_occurred", "audit_events", ["store_id", "occurred_at"])
    op.create_index("ix_audit_events_actor_occurred", "audit_events", ["actor_id", "occurred_at"])

    op.execute("""
        CREATE FUNCTION reject_audit_event_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'audit_events are append-only';
        END;
        $$;
    """)
    op.execute("""
        CREATE TRIGGER audit_events_no_update_delete
        BEFORE UPDATE OR DELETE ON audit_events
        FOR EACH ROW EXECUTE FUNCTION reject_audit_event_mutation();
    """)
    op.execute("""
        CREATE TRIGGER audit_events_no_truncate
        BEFORE TRUNCATE ON audit_events
        FOR EACH STATEMENT EXECUTE FUNCTION reject_audit_event_mutation();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_events_no_truncate ON audit_events")
    op.execute("DROP TRIGGER IF EXISTS audit_events_no_update_delete ON audit_events")
    op.execute("DROP FUNCTION IF EXISTS reject_audit_event_mutation()")
    op.drop_index("ix_audit_events_actor_occurred", table_name="audit_events")
    op.drop_index("ix_audit_events_store_occurred", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_table("platform_admin_grants")
    op.drop_index("ix_sessions_expires_at", table_name="sessions")
    op.drop_index("ix_sessions_user_id", table_name="sessions")
    op.drop_table("sessions")
    op.drop_index("ix_store_memberships_store_status", table_name="store_memberships")
    op.drop_index("ix_store_memberships_user_status", table_name="store_memberships")
    op.drop_table("store_memberships")
    op.drop_table("stores")
    op.drop_table("users")
