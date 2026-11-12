from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from store_operator.models.base import Base


class HotTopicSource(Base):
    __tablename__ = "hot_topic_sources"
    __table_args__ = (
        UniqueConstraint("source_key", name="uq_hot_topic_sources_source_key"),
        CheckConstraint("source_type IN ('official_api', 'rss', 'public_feed', 'manual')",
            name="source_type"),
        CheckConstraint("health_status IN ('unknown', 'healthy', 'degraded', 'failed', 'disabled')", name="health_status"),  # noqa: E501
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    source_key: Mapped[str] = mapped_column(String(100), nullable=False)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    terms_url: Mapped[str | None] = mapped_column(String(2048))
    permitted_use: Mapped[str | None] = mapped_column(Text)
    attribution_template: Mapped[str | None] = mapped_column(String(500))
    enabled: Mapped[bool] = mapped_column(default=False, nullable=False)
    health_status: Mapped[str] = mapped_column(String(24), default="unknown", nullable=False)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
        server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
        server_default=func.now(), onupdate=func.now(), nullable=False)


class HotTopic(Base):
    __tablename__ = "hot_topics"
    __table_args__ = (
        UniqueConstraint("source_id", "source_item_id", name="uq_hot_topics_source_item"),
        UniqueConstraint("source_id", "content_fingerprint",
            name="uq_hot_topics_source_fingerprint"),
        CheckConstraint("evidence_status IN ('collected', 'partial', 'failed', 'unverified', 'expired')", name="evidence_status"),  # noqa: E501
        Index("ix_hot_topics_expiry", "expires_at"),
        Index("ix_hot_topics_published", "published_at"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    source_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True),
        ForeignKey("hot_topic_sources.id", ondelete="RESTRICT"), nullable=False)
    source_item_id: Mapped[str | None] = mapped_column(String(500))
    canonical_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    raw_excerpt: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    region: Mapped[str | None] = mapped_column(String(120))
    industry_tags_json: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    topic_tags_json: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    heat_value: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    heat_unit: Mapped[str | None] = mapped_column(String(80))
    evidence_status: Mapped[str] = mapped_column(String(24), default="unverified", nullable=False)
    content_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    normalization_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
        server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
        server_default=func.now(), onupdate=func.now(), nullable=False)


class StoreOpportunity(Base):
    __tablename__ = "store_opportunities"
    __table_args__ = (
        UniqueConstraint("store_id", "id", name="uq_store_opportunities_store_id"),
        UniqueConstraint("store_id", "hot_topic_id", "matching_version",
            name="uq_store_opportunities_match_version"),
        CheckConstraint("eligibility_status IN ('eligible', 'review_required', 'ineligible', 'unassessed')", name="eligibility_status"),  # noqa: E501
        CheckConstraint("match_method IN ('rules', 'semantic', 'hybrid', 'manual')",
            name="match_method"),
        Index("ix_store_opportunities_store_expiry", "store_id", "expires_at"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    store_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("stores.id",
        ondelete="RESTRICT"), nullable=False)
    hot_topic_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True),
        ForeignKey("hot_topics.id", ondelete="RESTRICT"), nullable=False)
    store_context_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    matching_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    relevance_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))
    match_method: Mapped[str] = mapped_column(String(16), default="rules", nullable=False)
    matched_product_ids_json: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    matched_offer_ids_json: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    matched_audience_profile_ids_json: Mapped[list[str]] = mapped_column(JSONB, default=list,
        nullable=False)
    suggested_scenario: Mapped[str | None] = mapped_column(String(500))
    content_angle: Mapped[str | None] = mapped_column(Text)
    reason_summary: Mapped[str | None] = mapped_column(Text)
    risk_flags_json: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    eligibility_status: Mapped[str] = mapped_column(String(24), default="unassessed",
        nullable=False)
    matched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stale_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
        server_default=func.now(), nullable=False)


class OpportunityDecision(Base):
    __tablename__ = "opportunity_decisions"
    __table_args__ = (
        ForeignKeyConstraint(["store_id", "opportunity_id"], ["store_opportunities.store_id",
            "store_opportunities.id"], ondelete="RESTRICT"),
        CheckConstraint("decision IN ('adopt', 'ignore', 'snooze')", name="decision"),
        UniqueConstraint("store_id", "actor_user_id", "idempotency_key",
            name="uq_opportunity_decisions_idempotency"),
        Index("ix_opportunity_decisions_store_created", "store_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    store_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("stores.id",
        ondelete="RESTRICT"), nullable=False)
    opportunity_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    actor_user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id",
        ondelete="RESTRICT"), nullable=False)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(1000))
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
        server_default=func.now(), nullable=False)


class MetricDefinition(Base):
    __tablename__ = "metric_definitions"
    __table_args__ = (
        UniqueConstraint("source_system", "metric_key", "definition_version",
            name="uq_metric_definitions_source_key_version"),
        CheckConstraint("metric_tier IN ('content_performance', 'intent', 'business_outcome')",
            name="metric_tier"),
        CheckConstraint("value_type IN ('count', 'decimal', 'duration', 'rate', 'currency')",
            name="value_type"),
        CheckConstraint("status IN ('active', 'deprecated')", name="status"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    source_system: Mapped[str] = mapped_column(String(80), nullable=False)
    channel_key: Mapped[str | None] = mapped_column(String(80))
    metric_key: Mapped[str] = mapped_column(String(120), nullable=False)
    metric_tier: Mapped[str] = mapped_column(String(32), nullable=False)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    value_type: Mapped[str] = mapped_column(String(24), nullable=False)
    unit: Mapped[str | None] = mapped_column(String(40))
    definition: Mapped[str] = mapped_column(Text, nullable=False)
    aggregation_rule: Mapped[str] = mapped_column(String(40), default="sum", nullable=False)
    period_semantics: Mapped[str] = mapped_column(String(40), default="period_delta",
        nullable=False)
    definition_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True),
        server_default=func.now(), nullable=False)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
        server_default=func.now(), nullable=False)


class MetricObservation(Base):
    __tablename__ = "metric_observations"
    __table_args__ = (
        UniqueConstraint("store_id", "deduplication_key",
            name="uq_metric_observations_store_dedupe"),
        CheckConstraint("integrity_status IN ('complete', 'partial', 'anomalous', 'unknown')",
            name="integrity_status"),
        CheckConstraint("authenticity_status IN ('official_api', 'verified_import', 'merchant_reported', 'demo_sample')", name="authenticity_status"),  # noqa: E501
        CheckConstraint("sync_status IN ('current', 'delayed', 'failed', 'unavailable')",
            name="sync_status"),
        CheckConstraint("value_numeric IS NULL OR value_numeric >= 0", name="value_nonnegative"),
        CheckConstraint("period_end IS NULL OR period_start IS NULL OR period_end > period_start", name="period_valid"),  # noqa: E501
        Index("ix_metric_observations_store_collected", "store_id", "collected_at"),
        Index("ix_metric_observations_store_metric_period", "store_id", "metric_key", "period_end"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    store_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("stores.id",
        ondelete="RESTRICT"), nullable=False)
    metric_definition_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True),
        ForeignKey("metric_definitions.id", ondelete="RESTRICT"), nullable=False)
    metric_key: Mapped[str] = mapped_column(String(120), nullable=False)
    metric_tier: Mapped[str] = mapped_column(String(32), nullable=False)
    value_numeric: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    unit: Mapped[str | None] = mapped_column(String(40))
    currency: Mapped[str | None] = mapped_column(String(3))
    source_system: Mapped[str] = mapped_column(String(80), nullable=False)
    source_record_id: Mapped[str | None] = mapped_column(String(300))
    source_evidence_ref: Mapped[str | None] = mapped_column(String(2048))
    period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    period_timezone: Mapped[str] = mapped_column(String(80), nullable=False)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    definition_version: Mapped[int] = mapped_column(Integer, nullable=False)
    integrity_status: Mapped[str] = mapped_column(String(16), default="unknown", nullable=False)
    authenticity_status: Mapped[str] = mapped_column(String(24), nullable=False)
    sync_status: Mapped[str] = mapped_column(String(16), default="current", nullable=False)
    deduplication_key: Mapped[str] = mapped_column(String(64), nullable=False)
    supersedes_observation_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True),
        ForeignKey("metric_observations.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
        server_default=func.now(), nullable=False)
