from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
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
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from store_operator.models.base import Base


class Artifact(Base):
    __tablename__ = "artifacts"
    __table_args__ = (
        UniqueConstraint("store_id", "id", name="uq_artifacts_store_id"),
        ForeignKeyConstraint(
            ["store_id", "task_id"],
            ["marketing_tasks.store_id", "marketing_tasks.id"],
            name="fk_artifacts_task_same_store",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["store_id", "id", "current_version_id"],
            [
                "artifact_versions.store_id",
                "artifact_versions.artifact_id",
                "artifact_versions.id",
            ],
            name="fk_artifacts_current_version_same_artifact",
            use_alter=True,
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint("artifact_type IN ('copy', 'image')", name="artifact_type"),
        Index("ix_artifacts_store_task_type", "store_id", "task_id", "artifact_type"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    store_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    task_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    artifact_type: Mapped[str] = mapped_column(String(16), nullable=False)
    current_version_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ArtifactVersion(Base):
    __tablename__ = "artifact_versions"
    __table_args__ = (
        UniqueConstraint(
            "store_id", "artifact_id", "version_no",
            name="uq_artifact_versions_artifact_version",
        ),
        UniqueConstraint(
            "store_id", "artifact_id", "id",
            name="uq_artifact_versions_store_artifact_id",
        ),
        UniqueConstraint("store_id", "id", name="uq_artifact_versions_store_id"),
        ForeignKeyConstraint(
            ["prompt_version_id"],
            ["prompt_versions.id"],
            name="fk_artifact_versions_prompt_version",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["store_id", "artifact_id"],
            ["artifacts.store_id", "artifacts.id"],
            name="fk_artifact_versions_artifact_same_store",
            ondelete="RESTRICT",
        ),
        CheckConstraint("version_no >= 1", name="version_no_positive"),
        CheckConstraint(
            "source_type IN ('ai_generated', 'merchant_upload', 'manual_edit')",
            name="source_type",
        ),
        CheckConstraint(
            "(content_json IS NOT NULL) OR (content_ref IS NOT NULL)",
            name="content_required",
        ),
        Index(
            "ix_artifact_versions_store_artifact_created",
            "store_id",
            "artifact_id",
            "created_at",
        ),
        Index("ix_artifact_versions_input_fingerprint", "store_id", "input_fingerprint"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    store_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    artifact_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    source_type: Mapped[str] = mapped_column(String(24), nullable=False)
    source_refs_json: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    instruction: Mapped[str | None] = mapped_column(Text)
    content_json: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    content_ref: Mapped[str | None] = mapped_column(String(700))
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_id: Mapped[str | None] = mapped_column(String(100))
    model_id: Mapped[str | None] = mapped_column(String(160))
    prompt_version_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ReviewRecord(Base):
    __tablename__ = "review_records"
    __table_args__ = (
        UniqueConstraint("store_id", "id", name="uq_review_records_store_id"),
        ForeignKeyConstraint(
            ["store_id", "artifact_id", "artifact_version_id"],
            [
                "artifact_versions.store_id",
                "artifact_versions.artifact_id",
                "artifact_versions.id",
            ],
            name="fk_review_records_version_same_artifact",
            ondelete="RESTRICT",
        ),
        CheckConstraint("review_type IN ('copy', 'image')", name="review_type"),
        CheckConstraint(
            "decision IN ('approved', 'revision_requested', 'rejected')",
            name="decision",
        ),
        CheckConstraint(
            (
                "decision <> 'revision_requested' OR "
                "(comment IS NOT NULL AND length(trim(comment)) > 0)"
            ),
            name="revision_comment_required",
        ),
        Index(
            "ix_review_records_store_version_created",
            "store_id",
            "artifact_version_id",
            "created_at",
        ),
        Index(
            "ix_review_records_store_artifact_created",
            "store_id",
            "artifact_id",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    store_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    artifact_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    artifact_version_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    review_type: Mapped[str] = mapped_column(String(16), nullable=False)
    decision: Mapped[str] = mapped_column(String(24), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)
    target_json: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    reviewer_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )




class ChannelContent(Base):
    __tablename__ = "channel_contents"
    __table_args__ = (
        UniqueConstraint("store_id", "id", name="uq_channel_contents_store_id"),
        UniqueConstraint(
            "store_id", "task_id", "id", name="uq_channel_contents_store_task_id"
        ),
        UniqueConstraint(
            "store_id", "id", "channel_key",
            name="uq_channel_contents_store_id_channel",
        ),
        UniqueConstraint(
            "store_id", "channel_key", "input_fingerprint",
            name="uq_channel_contents_input_fingerprint",
        ),
        ForeignKeyConstraint(
            ["store_id", "task_id"],
            ["marketing_tasks.store_id", "marketing_tasks.id"],
            name="fk_channel_contents_task_same_store",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["store_id", "copy_version_id"],
            ["artifact_versions.store_id", "artifact_versions.id"],
            name="fk_channel_contents_copy_version_same_store",
            ondelete="RESTRICT",
        ),
        CheckConstraint("status IN ('ready', 'stale', 'blocked')", name="status"),
        CheckConstraint("length(trim(channel_key)) > 0", name="channel_key_required"),
        CheckConstraint(
            "input_fingerprint ~ '^[0-9a-f]{64}$'",
            name="input_fingerprint_sha256",
        ),
        Index(
            "ix_channel_contents_store_task_channel",
            "store_id",
            "task_id",
            "channel_key",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    store_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    task_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    channel_key: Mapped[str] = mapped_column(String(80), nullable=False)
    copy_version_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    payload_json: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    channel_spec_version_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="ready")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ChannelContentArtifactRef(Base):
    __tablename__ = "channel_content_artifact_refs"
    __table_args__ = (
        UniqueConstraint(
            "store_id", "channel_content_id", "position",
            name="uq_channel_content_artifact_refs_position",
        ),
        ForeignKeyConstraint(
            ["store_id", "channel_content_id"],
            ["channel_contents.store_id", "channel_contents.id"],
            name="fk_channel_content_artifact_refs_content_same_store",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["store_id", "artifact_version_id"],
            ["artifact_versions.store_id", "artifact_versions.id"],
            name="fk_channel_content_artifact_refs_version_same_store",
            ondelete="RESTRICT",
        ),
        CheckConstraint("role = 'image'", name="role_image_only"),
        CheckConstraint("position >= 0", name="position_nonnegative"),
        Index(
            "ix_channel_content_artifact_refs_content",
            "store_id",
            "channel_content_id",
            "position",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    store_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    channel_content_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    artifact_version_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, server_default="image")
    position: Mapped[int] = mapped_column(Integer, nullable=False)


class QualityReport(Base):
    __tablename__ = "quality_reports"
    __table_args__ = (
        UniqueConstraint("store_id", "id", name="uq_quality_reports_store_id"),
        UniqueConstraint(
            "store_id", "id", "input_fingerprint",
            name="uq_quality_reports_store_id_fingerprint",
        ),
        UniqueConstraint(
            "store_id", "channel_content_id", "id",
            name="uq_quality_reports_content_id",
        ),
        UniqueConstraint(
            "store_id", "channel_content_id", "rule_version", "input_fingerprint",
            name="uq_quality_reports_content_rule_fingerprint",
        ),
        ForeignKeyConstraint(
            ["store_id", "task_id", "channel_content_id"],
            [
                "channel_contents.store_id",
                "channel_contents.task_id",
                "channel_contents.id",
            ],
            name="fk_quality_reports_channel_content_same_task_store",
            ondelete="RESTRICT",
        ),
        CheckConstraint("result IN ('pass', 'fail', 'needs_human')", name="result"),
        CheckConstraint("length(trim(rule_version)) > 0", name="rule_version_required"),
        CheckConstraint(
            "input_fingerprint ~ '^[0-9a-f]{64}$'",
            name="input_fingerprint_sha256",
        ),
        Index(
            "ix_quality_reports_store_content_created",
            "store_id",
            "channel_content_id",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    store_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    task_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    channel_content_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    rule_version: Mapped[str] = mapped_column(String(80), nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    result: Mapped[str] = mapped_column(String(16), nullable=False)
    issues_json: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class QualityResolution(Base):
    __tablename__ = "quality_resolutions"
    __table_args__ = (
        UniqueConstraint(
            "store_id", "quality_report_id", "quality_report_fingerprint",
            name="uq_quality_resolutions_report_fingerprint",
        ),
        ForeignKeyConstraint(
            ["store_id", "quality_report_id", "quality_report_fingerprint"],
            [
                "quality_reports.store_id",
                "quality_reports.id",
                "quality_reports.input_fingerprint",
            ],
            name="fk_quality_resolutions_report_fingerprint_same_store",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["reviewer_user_id"],
            ["users.id"],
            name="fk_quality_resolutions_reviewer",
            ondelete="SET NULL",
        ),
        CheckConstraint("decision IN ('accepted', 'rejected')", name="decision"),
        CheckConstraint("length(trim(reason)) > 0", name="reason_required"),
        Index(
            "ix_quality_resolutions_store_report_created",
            "store_id",
            "quality_report_id",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    store_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    quality_report_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    quality_report_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    reviewer_user_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PublishPackage(Base):
    __tablename__ = "publish_packages"
    __table_args__ = (
        UniqueConstraint(
            "store_id", "task_id", "package_version",
            name="uq_publish_packages_task_version",
        ),
        UniqueConstraint("store_id", "id", name="uq_publish_packages_store_id"),
        UniqueConstraint(
            "store_id", "id", "package_fingerprint",
            name="uq_publish_packages_store_id_fingerprint",
        ),
        UniqueConstraint(
            "store_id", "task_id", "id",
            name="uq_publish_packages_store_task_id",
        ),
        ForeignKeyConstraint(
            ["store_id", "task_id"],
            ["marketing_tasks.store_id", "marketing_tasks.id"],
            name="fk_publish_packages_task_same_store",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["frozen_by_user_id"],
            ["users.id"],
            name="fk_publish_packages_frozen_by_user",
            ondelete="SET NULL",
        ),
        CheckConstraint("package_version >= 1", name="package_version_positive"),
        CheckConstraint(
            "package_fingerprint ~ '^[0-9a-f]{64}$'",
            name="fingerprint_sha256",
        ),
        Index(
            "ix_publish_packages_store_task_frozen",
            "store_id",
            "task_id",
            "frozen_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    store_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    task_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    package_version: Mapped[int] = mapped_column(Integer, nullable=False)
    package_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    frozen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    frozen_by_user_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))


class PublishPackageItem(Base):
    __tablename__ = "publish_package_items"
    __table_args__ = (
        UniqueConstraint(
            "store_id", "publish_package_id", "channel_key",
            name="uq_publish_package_items_channel",
        ),
        ForeignKeyConstraint(
            ["store_id", "publish_package_id"],
            ["publish_packages.store_id", "publish_packages.id"],
            name="fk_publish_package_items_package_same_store",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["store_id", "channel_content_id", "channel_key"],
            [
                "channel_contents.store_id",
                "channel_contents.id",
                "channel_contents.channel_key",
            ],
            name="fk_publish_package_items_channel_content_same_store",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["store_id", "channel_content_id", "quality_report_id"],
            [
                "quality_reports.store_id",
                "quality_reports.channel_content_id",
                "quality_reports.id",
            ],
            name="fk_publish_package_items_quality_report_same_content",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "delivery_mode IN ('official_api', 'manual_handoff')",
            name="delivery_mode",
        ),
        CheckConstraint(
            "(delivery_mode = 'official_api' AND channel_account_id IS NOT NULL) OR "
            "(delivery_mode = 'manual_handoff' AND channel_account_id IS NULL)",
            name="channel_account_matches_delivery_mode",
        ),
        CheckConstraint(
            "item_fingerprint ~ '^[0-9a-f]{64}$'",
            name="item_fingerprint_sha256",
        ),
        Index(
            "ix_publish_package_items_store_package",
            "store_id",
            "publish_package_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    store_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    publish_package_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    channel_key: Mapped[str] = mapped_column(String(80), nullable=False)
    channel_content_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    quality_report_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    channel_account_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    delivery_mode: Mapped[str] = mapped_column(String(24), nullable=False)
    planned_publish_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    item_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)


class PublishPackageFactRef(Base):
    __tablename__ = "publish_package_fact_refs"
    __table_args__ = (
        UniqueConstraint(
            "store_id", "publish_package_id", "position",
            name="uq_publish_package_fact_refs_position",
        ),
        ForeignKeyConstraint(
            ["store_id", "task_id", "publish_package_id"],
            [
                "publish_packages.store_id",
                "publish_packages.task_id",
                "publish_packages.id",
            ],
            name="fk_publish_package_fact_refs_package_same_task",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["store_id", "task_id", "business_fact_snapshot_id"],
            [
                "business_fact_snapshots.store_id",
                "business_fact_snapshots.task_id",
                "business_fact_snapshots.id",
            ],
            name="fk_publish_package_fact_refs_fact_same_task",
            ondelete="RESTRICT",
        ),
        CheckConstraint("position >= 0", name="position_nonnegative"),
        Index(
            "ix_publish_package_fact_refs_store_package",
            "store_id",
            "publish_package_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    store_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    task_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    publish_package_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    business_fact_snapshot_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)


class PublishConfirmation(Base):
    __tablename__ = "publish_confirmations"
    __table_args__ = (
        UniqueConstraint(
            "store_id", "publish_package_id", "package_fingerprint",
            name="uq_publish_confirmations_package_fingerprint",
        ),
        ForeignKeyConstraint(
            ["store_id", "publish_package_id", "package_fingerprint"],
            [
                "publish_packages.store_id",
                "publish_packages.id",
                "publish_packages.package_fingerprint",
            ],
            name="fk_publish_confirmations_package_fingerprint_same_store",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["confirmed_by_user_id"],
            ["users.id"],
            name="fk_publish_confirmations_user",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_publish_confirmations_store_package_created",
            "store_id",
            "publish_package_id",
            "confirmed_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    store_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    publish_package_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    package_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    confirmed_by_user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    confirmed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    confirmation_note: Mapped[str | None] = mapped_column(Text)
