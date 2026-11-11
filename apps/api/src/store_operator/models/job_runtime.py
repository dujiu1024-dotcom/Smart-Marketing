from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from store_operator.models.base import Base


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint(
            "idempotency_scope_type",
            "idempotency_scope_id",
            "idempotency_key",
            name="uq_jobs_idempotency_scope_key",
        ),
        CheckConstraint(
            "(idempotency_scope_type = 'store' AND store_id IS NOT NULL "
            "AND idempotency_scope_id = store_id) OR "
            "(idempotency_scope_type = 'system' AND store_id IS NULL)",
            name="idempotency_scope",
        ),
        CheckConstraint(
            "status IN ('queued', 'running', 'retry_wait', 'succeeded', "
            "'failed', 'cancelled', 'needs_human')",
            name="status",
        ),
        CheckConstraint(
            "actor_type IN ('user', 'platform_admin', 'system')", name="actor_type"
        ),
        CheckConstraint("priority BETWEEN -100 AND 100", name="priority_bounds"),
        CheckConstraint(
            "status <> 'running' OR (lease_owner IS NOT NULL AND lease_token IS NOT NULL "
            "AND lease_expires_at IS NOT NULL)",
            name="running_lease_required",
        ),
        CheckConstraint("attempt_count >= 0", name="attempt_count_nonnegative"),
        CheckConstraint("max_attempts >= 1", name="max_attempts_positive"),
        CheckConstraint("timeout_seconds > 0", name="timeout_positive"),
        CheckConstraint(
            "progress_current IS NULL OR progress_current >= 0",
            name="progress_current_nonnegative",
        ),
        CheckConstraint(
            "progress_total IS NULL OR progress_total >= 0",
            name="progress_total_nonnegative",
        ),
        CheckConstraint(
            "progress_current IS NULL OR progress_total IS NULL "
            "OR progress_current <= progress_total",
            name="progress_within_total",
        ),
        Index("ix_jobs_status_available_priority", "status", "available_at", "priority", "created_at"),
        Index("ix_jobs_store_created", "store_id", "created_at"),
        Index("ix_jobs_marketing_task", "marketing_task_id"),
        Index("ix_jobs_lease_expires", "lease_expires_at"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    store_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("stores.id", ondelete="RESTRICT")
    )
    idempotency_scope_type: Mapped[str] = mapped_column(String(20), nullable=False)
    idempotency_scope_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    marketing_task_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    job_type: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="queued")
    priority: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_ref: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    result_ref: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    queue_name: Mapped[str] = mapped_column(String(100), nullable=False, server_default="default")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="3")
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, server_default="300")
    lease_owner: Mapped[str | None] = mapped_column(String(200))
    lease_token: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    progress_current: Mapped[int | None] = mapped_column(BigInteger)
    progress_total: Mapped[int | None] = mapped_column(BigInteger)
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_summary: Mapped[str | None] = mapped_column(String(500))
    actor_type: Mapped[str] = mapped_column(String(24), nullable=False, server_default="user")
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class JobAttempt(Base):
    __tablename__ = "job_attempts"
    __table_args__ = (
        UniqueConstraint("job_id", "attempt_no", name="uq_job_attempts_job_attempt_no"),
        CheckConstraint("attempt_no >= 1", name="attempt_no_positive"),
        CheckConstraint(
            "status IN ('running', 'succeeded', 'failed', 'lease_expired', 'cancelled')",
            name="status",
        ),
        Index("ix_job_attempts_job_started", "job_id", "started_at"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    job_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("jobs.id", ondelete="RESTRICT"), nullable=False
    )
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    lease_token: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    worker_id: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, server_default="running")
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(BigInteger)
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_summary: Mapped[str | None] = mapped_column(String(500))
    provider: Mapped[str | None] = mapped_column(String(100))
    model: Mapped[str | None] = mapped_column(String(150))


class JobEvent(Base):
    __tablename__ = "job_events"
    __table_args__ = (
        CheckConstraint(
            "actor_type IN ('user', 'platform_admin', 'system')",
            name="actor_type",
        ),
        Index("ix_job_events_job_created", "job_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    job_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("jobs.id", ondelete="RESTRICT"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(150), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(24), nullable=False, server_default="system")
    actor_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    attempt_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("job_attempts.id", ondelete="SET NULL")
    )
    lease_token: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    data_json: Mapped[dict[str, object]] = mapped_column(
        "data", JSONB, nullable=False, server_default="{}"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_outbox_events_dedupe_key"),
        CheckConstraint(
            "status IN ('pending', 'publishing', 'published', 'dead')",
            name="status",
        ),
        CheckConstraint(
            "status <> 'publishing' OR (locked_by IS NOT NULL AND locked_until IS NOT NULL)",
            name="publishing_lock_required",
        ),
        CheckConstraint(
            "status <> 'published' OR published_at IS NOT NULL",
            name="published_timestamp_required",
        ),
        CheckConstraint("schema_version >= 1", name="schema_version_positive"),
        CheckConstraint("publish_attempts >= 0", name="publish_attempts_nonnegative"),
        Index("ix_outbox_events_status_available", "status", "available_at"),
        Index("ix_outbox_events_lock_expiry", "locked_until"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    aggregate_type: Mapped[str] = mapped_column(String(100), nullable=False)
    aggregate_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(150), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    payload_json: Mapped[dict[str, object]] = mapped_column(
        "payload", JSONB, nullable=False
    )
    dedupe_key: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pending")
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    publish_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    locked_by: Mapped[str | None] = mapped_column(String(200))
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AIInvocation(Base):
    __tablename__ = "ai_invocations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('started', 'succeeded', 'failed', 'needs_human')",
            name="status",
        ),
        CheckConstraint("latency_ms IS NULL OR latency_ms >= 0", name="latency_nonnegative"),
        CheckConstraint("input_schema_version >= 1", name="input_schema_version_positive"),
        CheckConstraint("output_schema_version >= 1", name="output_schema_version_positive"),
        Index("ix_ai_invocations_store_created", "store_id", "created_at"),
        Index("ix_ai_invocations_job", "job_id"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    store_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("stores.id", ondelete="RESTRICT")
    )
    marketing_task_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    job_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("jobs.id", ondelete="SET NULL")
    )
    attempt_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("job_attempts.id", ondelete="SET NULL")
    )
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    model: Mapped[str] = mapped_column(String(150), nullable=False)
    capability: Mapped[str] = mapped_column(String(24), nullable=False)
    prompt_template_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    prompt_version: Mapped[str | None] = mapped_column(String(80))
    parameter_snapshot_json: Mapped[dict[str, object]] = mapped_column(
        "parameter_snapshot", JSONB, nullable=False, server_default="{}"
    )
    input_schema_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    output_schema_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    provider_request_id: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(BigInteger)
    error_code: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AIUsageRecord(Base):
    __tablename__ = "ai_usage_records"
    __table_args__ = (
        CheckConstraint("input_tokens IS NULL OR input_tokens >= 0", name="input_tokens_nonnegative"),
        CheckConstraint("output_tokens IS NULL OR output_tokens >= 0", name="output_tokens_nonnegative"),
        CheckConstraint("image_units IS NULL OR image_units >= 0", name="image_units_nonnegative"),
        CheckConstraint("cost_amount IS NULL OR cost_amount >= 0", name="cost_nonnegative"),
        CheckConstraint(
            "(cost_amount IS NULL AND currency IS NULL) OR "
            "(cost_amount IS NOT NULL AND currency IS NOT NULL)",
            name="cost_currency_pair",
        ),
    )

    invocation_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("ai_invocations.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    input_tokens: Mapped[int | None] = mapped_column(BigInteger)
    output_tokens: Mapped[int | None] = mapped_column(BigInteger)
    image_units: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    cost_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    currency: Mapped[str | None] = mapped_column(String(3))
    metering_source: Mapped[str] = mapped_column(String(40), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
