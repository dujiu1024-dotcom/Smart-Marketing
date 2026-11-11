from typing import Annotated, NoReturn
from uuid import UUID

from fastapi import APIRouter, Depends, Header
from sqlalchemy import select
from sqlalchemy.orm import Session

from store_operator.auth.context import AuthContext
from store_operator.auth.dependencies import (
    AuthenticatedSession,
    require_csrf,
    require_store_context,
)
from store_operator.auth.errors import ApiError
from store_operator.db import get_db
from store_operator.jobs.schemas import (
    AIInvocationRead,
    AIUsageRead,
    JobDetailRead,
    JobEventRead,
    JobRead,
    JobResolveRequest,
    JobRetryRequest,
)
from store_operator.jobs.service import (
    InvalidJobTransition,
    JobIdempotencyConflict,
    request_job_cancellation,
    resolve_job,
    retry_failed_job,
)
from store_operator.models import AIInvocation, AIUsageRecord, Job, JobEvent

router = APIRouter(tags=["jobs"])


def _store_id(context: AuthContext) -> UUID:
    if context.request_store_id is None:
        raise ApiError(400, "STORE_CONTEXT_REQUIRED", "Store context is required")
    return context.request_store_id


def _idempotency_key(value: str | None) -> str:
    if value is None or not value.strip() or len(value.strip()) > 200:
        raise ApiError(400, "IDEMPOTENCY_KEY_REQUIRED", "A valid Idempotency-Key is required")
    return value.strip()


def _get_scoped_job(db: Session, job_id: UUID, store_id: UUID) -> Job:
    job = db.scalar(
        select(Job).where(Job.id == job_id, Job.store_id == store_id)
    )
    if job is None:
        raise ApiError(404, "JOB_NOT_FOUND", "Job not found")
    return job


def _raise_job_error(exc: Exception) -> NoReturn:
    if isinstance(exc, LookupError):
        raise ApiError(404, "JOB_NOT_FOUND", "Job not found") from exc
    if isinstance(exc, (InvalidJobTransition, JobIdempotencyConflict)):
        raise ApiError(409, "JOB_STATE_CONFLICT", str(exc)) from exc
    if isinstance(exc, ValueError):
        raise ApiError(422, "INVALID_JOB_REQUEST", str(exc)) from exc
    raise exc


@router.get("/jobs/{job_id}", response_model=JobDetailRead)
def get_job(
    job_id: UUID,
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)],
) -> JobDetailRead:
    job = _get_scoped_job(db, job_id, _store_id(context))
    events = db.scalars(
        select(JobEvent)
        .where(JobEvent.job_id == job.id)
        .order_by(JobEvent.created_at.desc(), JobEvent.id.desc())
        .limit(100)
    ).all()
    return JobDetailRead(
        **JobRead.model_validate(job).model_dump(),
        events=[
            JobEventRead(event_type=event.event_type, created_at=event.created_at)
            for event in events
        ],
    )


@router.post("/jobs/{job_id}/retry", response_model=JobRead)
def retry_job(
    job_id: UUID,
    payload: JobRetryRequest,
    auth: Annotated[AuthenticatedSession, Depends(require_csrf)],
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> JobRead:
    try:
        job = retry_failed_job(
            db,
            job_id=job_id,
            store_id=_store_id(context),
            actor_user_id=auth.user.id,
            idempotency_key=_idempotency_key(idempotency_key),
            reason=payload.reason,
            side_effects_confirmed_absent=payload.side_effects_confirmed_absent,
        )
        db.commit()
        db.refresh(job)
    except (LookupError, InvalidJobTransition, JobIdempotencyConflict, ValueError) as exc:
        db.rollback()
        _raise_job_error(exc)
    return JobRead.model_validate(job)


@router.post("/jobs/{job_id}/cancel", response_model=JobRead)
def cancel_job(
    job_id: UUID,
    auth: Annotated[AuthenticatedSession, Depends(require_csrf)],
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> JobRead:
    _idempotency_key(idempotency_key)
    try:
        job = request_job_cancellation(
            db,
            job_id=job_id,
            store_id=_store_id(context),
            actor_user_id=auth.user.id,
            idempotency_key=_idempotency_key(idempotency_key),
        )
        db.commit()
        db.refresh(job)
    except (LookupError, InvalidJobTransition, ValueError) as exc:
        db.rollback()
        _raise_job_error(exc)
    return JobRead.model_validate(job)


@router.post("/jobs/{job_id}/resolve", response_model=JobRead)
def resolve_human_job(
    job_id: UUID,
    payload: JobResolveRequest,
    auth: Annotated[AuthenticatedSession, Depends(require_csrf)],
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> JobRead:
    try:
        job = resolve_job(
            db,
            job_id=job_id,
            store_id=_store_id(context),
            actor_user_id=auth.user.id,
            idempotency_key=_idempotency_key(idempotency_key),
            resolution=payload.resolution,
            reason=payload.reason,
            side_effects_confirmed_absent=payload.side_effects_confirmed_absent,
        )
        db.commit()
        db.refresh(job)
    except (LookupError, InvalidJobTransition, JobIdempotencyConflict, ValueError) as exc:
        db.rollback()
        _raise_job_error(exc)
    return JobRead.model_validate(job)


@router.get("/ai/invocations/{invocation_id}", response_model=AIInvocationRead)
def get_ai_invocation(
    invocation_id: UUID,
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)],
) -> AIInvocationRead:
    invocation = db.scalar(
        select(AIInvocation).where(
            AIInvocation.id == invocation_id,
            AIInvocation.store_id == _store_id(context),
        )
    )
    if invocation is None:
        raise ApiError(404, "AI_INVOCATION_NOT_FOUND", "AI invocation not found")
    usage = db.get(AIUsageRecord, invocation.id)
    return AIInvocationRead(
        id=invocation.id,
        marketing_task_id=invocation.marketing_task_id,
        job_id=invocation.job_id,
        provider=invocation.provider,
        model=invocation.model,
        capability=invocation.capability,
        prompt_version=invocation.prompt_version,
        provider_request_id=invocation.provider_request_id,
        request_fingerprint=invocation.request_fingerprint,
        status=invocation.status,
        latency_ms=invocation.latency_ms,
        error_code=invocation.error_code,
        created_at=invocation.created_at,
        finished_at=invocation.finished_at,
        usage=AIUsageRead.model_validate(usage) if usage is not None else None,
    )
