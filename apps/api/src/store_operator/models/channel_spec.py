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
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from store_operator.models.base import Base


class ChannelSpec(Base):
    __tablename__ = "channel_specs"
    __table_args__ = (
        UniqueConstraint("channel_key", name="uq_channel_specs_channel_key"),
        UniqueConstraint("id", "current_version_id", name="uq_channel_specs_current_version"),
        ForeignKeyConstraint(
            ["id", "current_version_id"],
            ["channel_spec_versions.channel_spec_id", "channel_spec_versions.id"],
            name="fk_channel_specs_current_version_same_spec",
            use_alter=True,
            ondelete="RESTRICT",
        ),
        CheckConstraint("status IN ('active', 'archived')", name="status"),
        CheckConstraint("length(trim(channel_key)) > 0", name="channel_key_required"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    channel_key: Mapped[str] = mapped_column(String(80), nullable=False)
    current_version_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ChannelSpecVersion(Base):
    __tablename__ = "channel_spec_versions"
    __table_args__ = (
        UniqueConstraint(
            "channel_spec_id", "spec_version", name="uq_channel_spec_versions_spec_version"
        ),
        UniqueConstraint(
            "channel_spec_id", "id", name="uq_channel_spec_versions_spec_id"
        ),
        ForeignKeyConstraint(
            ["channel_spec_id"],
            ["channel_specs.id"],
            name="fk_channel_spec_versions_spec",
            ondelete="RESTRICT",
        ),
        CheckConstraint("spec_version >= 1", name="spec_version_positive"),
        CheckConstraint(
            "verification_status IN ('pending_verification', 'verified', 'deprecated')",
            name="verification_status",
        ),
        Index("ix_channel_spec_versions_spec_created", "channel_spec_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    channel_spec_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    spec_version: Mapped[int] = mapped_column(Integer, nullable=False)
    text_constraints_json: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    media_constraints_json: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    hashtag_constraints_json: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    link_constraints_json: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    schedule_constraints_json: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    draft_supported: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    publish_supported: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    verification_status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="pending_verification"
    )
    source_document_ref: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ChannelCapabilitySnapshot(Base):
    __tablename__ = "channel_capability_snapshots"
    __table_args__ = (
        ForeignKeyConstraint(
            ["store_id", "channel_account_id"],
            ["channel_accounts.store_id", "channel_accounts.id"],
            name="fk_channel_capability_snapshots_account_same_store",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["channel_spec_version_id"],
            ["channel_spec_versions.id"],
            name="fk_channel_capability_snapshots_spec_version",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "support_status IN ('supported', 'unsupported', 'pending_verification')",
            name="support_status",
        ),
        CheckConstraint("length(trim(capability_key)) > 0", name="capability_key_required"),
        Index(
            "ix_channel_capability_snapshots_account_checked",
            "store_id",
            "channel_account_id",
            "checked_at",
        ),
        Index(
            "ix_channel_capability_snapshots_expiry",
            "expires_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    store_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    channel_account_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    channel_spec_version_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    capability_key: Mapped[str] = mapped_column(String(100), nullable=False)
    support_status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="pending_verification"
    )
    evidence_ref: Mapped[str | None] = mapped_column(String(2048))
    reason: Mapped[str | None] = mapped_column(String(1000))
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
