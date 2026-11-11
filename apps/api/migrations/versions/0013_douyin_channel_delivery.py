"""Persist tenant-scoped channel OAuth grants and publish operations.

Revision ID: 0013_douyin_channel_delivery
Revises: 0012_content_quality_packages
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013_douyin_channel_delivery"
down_revision: str | None = "0012_content_quality_packages"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_publish_package_items_store_id", "publish_package_items", ["store_id", "id"]
    )
    op.create_table(
        "oauth_authorization_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False),  # noqa: E501
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),  # noqa: E501
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sessions.id", ondelete="RESTRICT"), nullable=False),  # noqa: E501
        sa.Column("state_hash", sa.LargeBinary(32), nullable=False),
        sa.Column("redirect_uri", sa.String(2048), nullable=False),
        sa.Column("requested_scopes", postgresql.JSONB(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),  # noqa: E501
        sa.UniqueConstraint("state_hash", name="uq_oauth_authorization_attempts_state_hash"),
        sa.CheckConstraint("provider IN ('douyin')", name="ck_oauth_authorization_attempts_provider"),  # noqa: E501
        sa.CheckConstraint("expires_at > created_at", name="ck_oauth_authorization_attempts_expiry_after_creation"),  # noqa: E501
    )
    op.create_index("ix_oauth_authorization_attempts_expiry", "oauth_authorization_attempts", ["expires_at"])  # noqa: E501
    op.create_index(
        "ix_oauth_authorization_attempts_store_user_created",
        "oauth_authorization_attempts",
        ["store_id", "user_id", "created_at"],
    )

    op.create_table(
        "channel_accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False),  # noqa: E501
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("external_account_id", sa.String(160), nullable=False),
        sa.Column("display_name", sa.String(160)),
        sa.Column("avatar_url", sa.String(2048)),
        sa.Column("granted_scopes", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),  # noqa: E501
        sa.Column("access_token_secret_ref", sa.String(512), nullable=False),
        sa.Column("refresh_token_secret_ref", sa.String(512), nullable=False),
        sa.Column("access_token_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("refresh_token_expires_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(24), server_default="active", nullable=False),
        sa.Column("connected_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),  # noqa: E501
        sa.Column("connected_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),  # noqa: E501
        sa.Column("last_verified_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),  # noqa: E501
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),  # noqa: E501
        sa.UniqueConstraint("store_id", "provider", "external_account_id", name="uq_channel_accounts_store_provider_external_id"),  # noqa: E501
        sa.UniqueConstraint("store_id", "id", name="uq_channel_accounts_store_id"),
        sa.CheckConstraint("provider IN ('douyin')", name="ck_channel_accounts_provider"),
        sa.CheckConstraint("status IN ('active', 'reauth_required', 'revoked', 'error')", name="ck_channel_accounts_status"),  # noqa: E501
        sa.CheckConstraint("length(external_account_id) > 0", name="ck_channel_accounts_external_account_id_nonempty"),  # noqa: E501
    )
    op.create_index("ix_channel_accounts_store_provider_status", "channel_accounts", ["store_id", "provider", "status"])  # noqa: E501
    op.create_foreign_key(
        "fk_publish_package_items_channel_account_same_store",
        "publish_package_items",
        "channel_accounts",
        ["store_id", "channel_account_id"],
        ["store_id", "id"],
        ondelete="RESTRICT",
    )

    op.create_table(
        "publish_operations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False),  # noqa: E501
        sa.Column("publish_package_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("publish_package_item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("publish_confirmation_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("publish_confirmations.id", ondelete="RESTRICT"), nullable=False),  # noqa: E501
        sa.Column("channel_account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), server_default="queued", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("platform_item_id", sa.String(160)),
        sa.Column("last_readback_at", sa.DateTime(timezone=True)),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("last_error_code", sa.String(100)),
        sa.Column("last_error_summary", sa.String(500)),
        sa.Column("confirmed_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),  # noqa: E501
        sa.Column("confirmed_package_fingerprint", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),  # noqa: E501
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),  # noqa: E501
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("store_id", "idempotency_key", name="uq_publish_operations_store_key"),
        sa.UniqueConstraint("store_id", "id", name="uq_publish_operations_store_id"),
        sa.ForeignKeyConstraint(
            ["store_id", "publish_package_id"],
            ["publish_packages.store_id", "publish_packages.id"],
            name="fk_publish_operations_package_same_store",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "publish_package_item_id"],
            ["publish_package_items.store_id", "publish_package_items.id"],
            name="fk_publish_operations_package_item_same_store",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "publish_package_id", "confirmed_package_fingerprint"],
            [
                "publish_confirmations.store_id",
                "publish_confirmations.publish_package_id",
                "publish_confirmations.package_fingerprint",
            ],
            name="fk_publish_operations_confirmation_same_package",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "channel_account_id"],
            ["channel_accounts.store_id", "channel_accounts.id"],
            name="fk_publish_operations_channel_account_same_store",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'uploading', 'submitting', 'processing', 'published', 'failed', 'needs_human', 'cancelled')",  # noqa: E501
            name="ck_publish_operations_status",
        ),
        sa.CheckConstraint("attempt_count >= 0", name="ck_publish_operations_attempt_count_nonnegative"),  # noqa: E501
    )
    op.create_index("ix_publish_operations_status_available", "publish_operations", ["status", "next_attempt_at"])  # noqa: E501
    op.create_index("ix_publish_operations_store_created", "publish_operations", ["store_id", "created_at"])  # noqa: E501


def downgrade() -> None:
    op.drop_index("ix_publish_operations_store_created", table_name="publish_operations")
    op.drop_index("ix_publish_operations_status_available", table_name="publish_operations")
    op.drop_table("publish_operations")
    op.drop_constraint(
        "fk_publish_package_items_channel_account_same_store",
        "publish_package_items",
        type_="foreignkey",
    )
    op.drop_constraint("uq_publish_package_items_store_id", "publish_package_items", type_="unique")
    op.drop_index("ix_channel_accounts_store_provider_status", table_name="channel_accounts")
    op.drop_table("channel_accounts")
    op.drop_index("ix_oauth_authorization_attempts_store_user_created", table_name="oauth_authorization_attempts")  # noqa: E501
    op.drop_index("ix_oauth_authorization_attempts_expiry", table_name="oauth_authorization_attempts")  # noqa: E501
    op.drop_table("oauth_authorization_attempts")
