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
        Index("ix_artifact_versions_store_artifact_created", "store_id", "artifact_id", "created_at"),
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
            "decision <> 'revision_requested' OR length(trim(comment)) > 0",
            name="revision_comment_required",
        ),
        Index("ix_review_records_store_version_created", "store_id", "artifact_version_id", "created_at"),
        Index("ix_review_records_store_artifact_created", "store_id", "artifact_id", "created_at"),
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
