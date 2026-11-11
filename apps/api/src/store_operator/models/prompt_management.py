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
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from store_operator.models.base import Base


class PromptTemplate(Base):
    __tablename__ = "prompt_templates"
    __table_args__ = (
        UniqueConstraint(
            "industry_key",
            "task_type",
            "capability",
            "template_key",
            name="uq_prompt_templates_scope_key",
        ),
        UniqueConstraint("id", "current_published_version_id", name="uq_prompt_templates_current_version"),
        ForeignKeyConstraint(
            ["id", "current_published_version_id"],
            ["prompt_versions.prompt_template_id", "prompt_versions.id"],
            name="fk_prompt_templates_current_version_same_template",
            use_alter=True,
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint("status IN ('active', 'archived')", name="status"),
        CheckConstraint("capability IN ('text', 'image', 'vision', 'ocr')", name="capability"),
        Index("ix_prompt_templates_status_industry", "status", "industry_key", "task_type"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    template_key: Mapped[str] = mapped_column(String(120), nullable=False)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    industry_key: Mapped[str] = mapped_column(String(80), nullable=False)
    task_type: Mapped[str] = mapped_column(String(80), nullable=False)
    capability: Mapped[str] = mapped_column(String(16), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="active")
    current_published_version_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class PromptVersion(Base):
    __tablename__ = "prompt_versions"
    __table_args__ = (
        UniqueConstraint(
            "prompt_template_id", "version_no",
            name="uq_prompt_versions_template_version",
        ),
        UniqueConstraint(
            "prompt_template_id", "id",
            name="uq_prompt_versions_template_id",
        ),
        ForeignKeyConstraint(
            ["prompt_template_id"],
            ["prompt_templates.id"],
            name="fk_prompt_versions_template",
            ondelete="RESTRICT",
        ),
        CheckConstraint("version_no >= 1", name="version_no_positive"),
        CheckConstraint("schema_version >= 1", name="schema_version_positive"),
        CheckConstraint("status IN ('draft', 'published')", name="status"),
        CheckConstraint(
            "status <> 'published' OR "
            "(published_by_user_id IS NOT NULL AND published_at IS NOT NULL)",
            name="published_metadata_required",
        ),
        CheckConstraint("length(trim(changelog)) > 0", name="changelog_required"),
        Index("ix_prompt_versions_template_status", "prompt_template_id", "status", "version_no"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    prompt_template_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    user_prompt_template: Mapped[str] = mapped_column(Text, nullable=False)
    variables_schema_json: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    output_schema_json: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    input_policy_json: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    changelog: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="draft")
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    published_by_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PromptActivation(Base):
    __tablename__ = "prompt_activations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["prompt_template_id", "activated_version_id"],
            ["prompt_versions.prompt_template_id", "prompt_versions.id"],
            name="fk_prompt_activations_activated_version_same_template",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["prompt_template_id", "previous_version_id"],
            ["prompt_versions.prompt_template_id", "prompt_versions.id"],
            name="fk_prompt_activations_previous_version_same_template",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["actor_user_id"], ["users.id"],
            name="fk_prompt_activations_actor_user",
            ondelete="SET NULL",
        ),
        CheckConstraint("action IN ('publish', 'rollback')", name="action"),
        CheckConstraint("length(trim(reason)) > 0", name="reason_required"),
        UniqueConstraint("idempotency_key_hash", name="uq_prompt_activations_idempotency_hash"),
        Index("ix_prompt_activations_template_created", "prompt_template_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    prompt_template_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    activated_version_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    previous_version_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    actor_user_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    idempotency_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
