from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from store_operator.models.base import Base


class OAuthAuthorizationAttempt(Base):
    __tablename__ = "oauth_authorization_attempts"
    __table_args__ = (
        UniqueConstraint("state_hash", name="uq_oauth_authorization_attempts_state_hash"),
        Index("ix_oauth_authorization_attempts_expiry", "expires_at"),
        Index(
            "ix_oauth_authorization_attempts_store_user_created",
            "store_id",
            "user_id",
            "created_at",
        ),
        CheckConstraint("provider IN ('douyin')", name="provider"),
        CheckConstraint("expires_at > created_at", name="expiry_after_creation"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    store_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    session_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("sessions.id", ondelete="RESTRICT"), nullable=False
    )
    state_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    redirect_uri: Mapped[str] = mapped_column(String(2048), nullable=False)
    requested_scopes: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ChannelAccount(Base):
    __tablename__ = "channel_accounts"
    __table_args__ = (
        UniqueConstraint(
            "store_id", "provider", "external_account_id",
            name="uq_channel_accounts_store_provider_external_id",
        ),
        UniqueConstraint("store_id", "id", name="uq_channel_accounts_store_id"),
        Index("ix_channel_accounts_store_provider_status", "store_id", "provider", "status"),
        CheckConstraint("provider IN ('douyin')", name="provider"),
        CheckConstraint(
            "status IN ('active', 'reauth_required', 'revoked', 'error')", name="status"
        ),
        CheckConstraint("length(external_account_id) > 0", name="external_account_id_nonempty"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    store_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    external_account_id: Mapped[str] = mapped_column(String(160), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(160))
    avatar_url: Mapped[str | None] = mapped_column(String(2048))
    granted_scopes: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default="[]")
    access_token_secret_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    refresh_token_secret_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    access_token_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)  # noqa: E501
    refresh_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(24), nullable=False, server_default="active")
    connected_by_user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    connected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class PublishOperation(Base):
    __tablename__ = "publish_operations"
    __table_args__ = (
        UniqueConstraint("store_id", "idempotency_key", name="uq_publish_operations_store_key"),
        UniqueConstraint("store_id", "id", name="uq_publish_operations_store_id"),
        ForeignKeyConstraint(
            ["store_id", "publish_package_id"],
            ["publish_packages.store_id", "publish_packages.id"],
            name="fk_publish_operations_package_same_store",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["store_id", "publish_package_item_id"],
            ["publish_package_items.store_id", "publish_package_items.id"],
            name="fk_publish_operations_package_item_same_store",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["store_id", "publish_package_id", "confirmed_package_fingerprint"],
            [
                "publish_confirmations.store_id",
                "publish_confirmations.publish_package_id",
                "publish_confirmations.package_fingerprint",
            ],
            name="fk_publish_operations_confirmation_same_package",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["store_id", "channel_account_id"],
            ["channel_accounts.store_id", "channel_accounts.id"],
            name="fk_publish_operations_channel_account_same_store",
            ondelete="RESTRICT",
        ),
        Index("ix_publish_operations_status_available", "status", "next_attempt_at"),
        Index("ix_publish_operations_store_created", "store_id", "created_at"),
        CheckConstraint(
            "status IN ('queued', 'uploading', 'submitting', 'processing', "
            "'published', 'failed', 'needs_human', 'cancelled')",
            name="status",
        ),
        CheckConstraint("attempt_count >= 0", name="attempt_count_nonnegative"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    store_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False
    )
    publish_package_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False
    )
    publish_package_item_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        nullable=False,
    )
    publish_confirmation_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("publish_confirmations.id", ondelete="RESTRICT"), nullable=False  # noqa: E501
    )
    channel_account_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, server_default="queued")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    platform_item_id: Mapped[str | None] = mapped_column(String(160))
    last_readback_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(100))
    last_error_summary: Mapped[str | None] = mapped_column(String(500))
    confirmed_by_user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    confirmed_package_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))



class PublishOperationAttempt(Base):
    __tablename__ = "publish_operation_attempts"
    __table_args__ = (
        UniqueConstraint(
            "store_id",
            "publish_operation_id",
            "attempt_no",
            name="uq_publish_operation_attempts_operation_no",
        ),
        ForeignKeyConstraint(
            ["store_id", "publish_operation_id"],
            ["publish_operations.store_id", "publish_operations.id"],
            name="fk_publish_operation_attempts_operation_same_store",
            ondelete="RESTRICT",
        ),
        CheckConstraint("attempt_no >= 1", name="attempt_no_positive"),
        CheckConstraint(
            "action IN ('upload_image', 'publish_image_text', 'readback')",
            name="action",
        ),
        CheckConstraint(
            "normalized_status IN ('started', 'accepted', 'verified', 'not_found', 'failed', 'unknown')",
            name="normalized_status",
        ),
        Index(
            "ix_publish_operation_attempts_operation_created",
            "store_id",
            "publish_operation_id",
            "started_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    store_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    publish_operation_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    adapter_version: Mapped[str] = mapped_column(String(80), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    external_request_id: Mapped[str | None] = mapped_column(String(160))
    response_evidence_ref: Mapped[str | None] = mapped_column(String(2048))
    normalized_status: Mapped[str] = mapped_column(String(24), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(100))
    retryable: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
