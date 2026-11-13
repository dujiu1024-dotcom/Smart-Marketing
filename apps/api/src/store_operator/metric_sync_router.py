"""指标同步接口：只创建 Job，不在请求内同步调用外部采集。"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from store_operator.auth.audit import record_audit
from store_operator.auth.context import AuthContext
from store_operator.auth.dependencies import (
    AuthenticatedSession,
    require_csrf,
    require_store_context,
)
from store_operator.auth.errors import ApiError
from store_operator.config import settings
from store_operator.db import get_db
from store_operator.jobs.service import JobIdempotencyConflict, create_job
from store_operator.models.channel_delivery import ChannelAccount
from store_operator.models.job_runtime import Job
from store_operator.models.opportunity_effects import MetricSyncCursor

router = APIRouter(tags=["effects"])

JOB_TYPE = "metrics.sync_channel_account.v1"
VALID_SCOPES = ("account", "work", "store")
ACTIVE_JOB_STATUSES = ("queued", "running", "retry_wait")


def _store_id(context: AuthContext) -> UUID:
    if context.request_store_id is None:
        raise ApiError(400, "STORE_CONTEXT_REQUIRED", "Store context is required")
    return context.request_store_id


class MetricSyncRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel_account_id: UUID
    scopes: list[str] = Field(default_factory=lambda: ["account", "work"], max_length=3)

    @field_validator("scopes")
    @classmethod
    def _validate_scopes(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("scopes cannot be empty")
        unknown = [item for item in value if item not in VALID_SCOPES]
        if unknown:
            raise ValueError(f"unknown scopes: {', '.join(unknown)}")
        return list(dict.fromkeys(value))


def _cursor_read(item: MetricSyncCursor) -> dict[str, object]:
    return {
        "channel_account_id": str(item.channel_account_id),
        "scope": item.scope,
        "status": item.status,
        "cursor_version": item.cursor_version,
        "consecutive_failures": item.consecutive_failures,
        "last_attempt_at": item.last_attempt_at.isoformat() if item.last_attempt_at else None,
        "last_success_at": item.last_success_at.isoformat() if item.last_success_at else None,
        "last_failure_at": item.last_failure_at.isoformat() if item.last_failure_at else None,
        "last_error_code": item.last_error_code,
        "last_error_summary": item.last_error_summary,
    }


def _job_read(item: Job) -> dict[str, object]:
    return {
        "id": str(item.id),
        "status": item.status,
        "job_type": item.job_type,
        "progress_current": item.progress_current,
        "progress_total": item.progress_total,
        "error_code": item.error_code,
        "error_summary": item.error_summary,
        "created_at": item.created_at.isoformat(),
        "started_at": item.started_at.isoformat() if item.started_at else None,
        "finished_at": item.finished_at.isoformat() if item.finished_at else None,
    }


@router.post("/effects/sync")
def request_metric_sync(
    payload: MetricSyncRequest,
    request: Request,
    auth: Annotated[AuthenticatedSession, Depends(require_csrf)],
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> dict[str, object]:
    store_id = _store_id(context)
    account = db.scalar(
        select(ChannelAccount).where(
            ChannelAccount.id == payload.channel_account_id,
            ChannelAccount.store_id == store_id,
        )
    )
    if account is None:
        raise ApiError(404, "RESOURCE_NOT_FOUND", "Channel account not found")
    if account.status != "active":
        raise ApiError(
            409,
            "CHANNEL_ACCOUNT_NOT_ACTIVE",
            "渠道账号授权已失效，请重新授权后再同步。",
        )
    running = db.scalar(
        select(Job.id).where(
            Job.store_id == store_id,
            Job.job_type == JOB_TYPE,
            Job.status.in_(ACTIVE_JOB_STATUSES),
            Job.payload_ref["channel_account_id"].astext == str(account.id),
        ).limit(1)
    )
    if running is not None:
        raise ApiError(
            409,
            "METRIC_SYNC_ALREADY_RUNNING",
            "该账号已有同步任务在执行，请稍后再试。",
        )
    try:
        job = create_job(
            db,
            job_type=JOB_TYPE,
            payload_ref={
                "schema_version": 1,
                "channel_account_id": str(account.id),
                "scopes": payload.scopes,
            },
            idempotency_key=idempotency_key,
            store_id=store_id,
            actor_type="user",
            actor_user_id=auth.user.id,
            queue_name="default",
            priority=0,
            max_attempts=3,
            timeout_seconds=300,
        )
    except JobIdempotencyConflict as exc:
        raise ApiError(
            409, "IDEMPOTENCY_KEY_REUSED", "该幂等键已用于其他同步请求"
        ) from exc
    record_audit(
        db,
        request,
        action="effects.metric_sync.requested",
        target_type="job",
        target_id=job.id,
        actor_user_id=auth.user.id,
        store_id=store_id,
        metadata={
            "channel_account_id": str(account.id),
            "scopes": payload.scopes,
        },
    )
    db.commit()
    return {
        "status": job.status,
        "job": _job_read(job),
        "channel_account_id": str(account.id),
        "scopes": payload.scopes,
    }


@router.get("/effects/sync/status")
def get_metric_sync_status(
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)],
    channel_account_id: UUID | None = None,
) -> dict[str, object]:
    store_id = _store_id(context)
    if channel_account_id is not None:
        owned = db.scalar(
            select(ChannelAccount.id).where(
                ChannelAccount.id == channel_account_id,
                ChannelAccount.store_id == store_id,
            )
        )
        if owned is None:
            raise ApiError(404, "RESOURCE_NOT_FOUND", "Channel account not found")
    statement = select(MetricSyncCursor).where(MetricSyncCursor.store_id == store_id)
    if channel_account_id is not None:
        statement = statement.where(
            MetricSyncCursor.channel_account_id == channel_account_id
        )
    cursors = db.scalars(
        statement.order_by(
            MetricSyncCursor.channel_account_id, MetricSyncCursor.scope
        )
    ).all()
    job_statement = select(Job).where(
        Job.store_id == store_id, Job.job_type == JOB_TYPE
    )
    if channel_account_id is not None:
        job_statement = job_statement.where(
            Job.payload_ref["channel_account_id"].astext == str(channel_account_id)
        )
    latest_job = db.scalar(job_statement.order_by(Job.created_at.desc()).limit(1))
    last_success_at = max(
        (item.last_success_at for item in cursors if item.last_success_at is not None),
        default=None,
    )
    running = latest_job is not None and latest_job.status in ACTIVE_JOB_STATUSES
    return {
        "channel_account_id": str(channel_account_id) if channel_account_id else None,
        "cursors": [_cursor_read(item) for item in cursors],
        "latest_job": _job_read(latest_job) if latest_job else None,
        "last_success_at": last_success_at.isoformat() if last_success_at else None,
        "collector_configured": bool(
            settings.metric_sync_enabled and settings.metric_collector_base_url
        ),
        "sync_in_progress": running,
        "scopes": list(VALID_SCOPES),
        "observations_query": {
            "path": "/api/v1/effects/observations",
            "params": ["channel_account_id", "observation_scope", "authenticity_status"],
        },
    }
