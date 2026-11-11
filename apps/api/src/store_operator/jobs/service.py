from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from store_operator.ai_gateway.errors import SideEffectState
from store_operator.models.job_runtime import Job, JobAttempt, JobEvent, OutboxEvent

SYSTEM_SCOPE_ID = UUID("00000000-0000-0000-0000-000000000001")


class JobIdempotencyConflict(Exception):
    """An idempotency key was reused with a different request."""


class LeaseLostError(Exception):
    """The Worker no longer owns a valid execution lease."""


class InvalidJobTransition(Exception):
    """The requested state transition is not allowed."""


@dataclass(frozen=True, slots=True)
class JobClaim:
    job: Job
    attempt: JobAttempt


def _request_hash(
    *,
    job_type: str,
    payload_ref: dict[str, object],
    marketing_task_id: UUID | None,
    queue_name: str,
    priority: int,
    max_attempts: int,
    timeout_seconds: int,
) -> str:
    request = {
        "job_type": job_type,
        "payload_ref": payload_ref,
        "marketing_task_id": str(marketing_task_id) if marketing_task_id else None,
        "queue_name": queue_name,
        "priority": priority,
        "max_attempts": max_attempts,
        "timeout_seconds": timeout_seconds,
    }
    canonical = json.dumps(
        request, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _append_event(
    db: Session,
    job: Job,
    event_type: str,
    *,
    actor_type: str = "system",
    actor_id: UUID | None = None,
    attempt_id: UUID | None = None,
    lease_token: UUID | None = None,
    data: dict[str, object] | None = None,
) -> None:
    db.add(
        JobEvent(
            id=uuid4(),
            job_id=job.id,
            event_type=event_type,
            actor_type=actor_type,
            actor_id=actor_id,
            attempt_id=attempt_id,
            lease_token=lease_token,
            data_json=data or {},
        )
    )


def _clear_lease(job: Job) -> None:
    job.lease_owner = None
    job.lease_token = None
    job.lease_expires_at = None
    job.heartbeat_at = None


def create_job(
    db: Session,
    *,
    job_type: str,
    payload_ref: dict[str, object],
    idempotency_key: str,
    store_id: UUID | None,
    actor_type: str,
    actor_user_id: UUID | None,
    queue_name: str = "default",
    priority: int = 0,
    max_attempts: int = 3,
    timeout_seconds: int = 300,
    marketing_task_id: UUID | None = None,
) -> Job:
    """Create a Job and its dispatch Outbox event in the caller's transaction.

    Store-scoped idempotency keys must already be derived from the authorized
    actor/operation request scope. This service never trusts a client store ID.
    """
    normalized_key = idempotency_key.strip()
    if not normalized_key or len(normalized_key) > 200:
        raise ValueError("idempotency_key must contain 1-200 characters")
    if not job_type or len(job_type) > 100:
        raise ValueError("job_type must contain 1-100 characters")
    if not queue_name or len(queue_name) > 100:
        raise ValueError("queue_name must contain 1-100 characters")
    schema_version = payload_ref.get("schema_version")
    if not isinstance(schema_version, int) or isinstance(schema_version, bool):
        raise ValueError("payload_ref must contain an integer schema_version")
    if schema_version < 1:
        raise ValueError("payload schema_version must be positive")
    if not -100 <= priority <= 100:
        raise ValueError("priority must be between -100 and 100")
    if max_attempts < 1 or timeout_seconds < 1:
        raise ValueError("max_attempts and timeout_seconds must be positive")

    if store_id is None:
        if actor_type != "system" or actor_user_id is not None:
            raise ValueError("System-scoped jobs require actor_type=system and no user ID")
        scope_type = "system"
        scope_id = SYSTEM_SCOPE_ID
    else:
        if actor_type not in {"user", "platform_admin"} or actor_user_id is None:
            raise ValueError("Store-scoped jobs require an authenticated user actor")
        scope_type = "store"
        scope_id = store_id

    request_hash = _request_hash(
        job_type=job_type,
        payload_ref=payload_ref,
        marketing_task_id=marketing_task_id,
        queue_name=queue_name,
        priority=priority,
        max_attempts=max_attempts,
        timeout_seconds=timeout_seconds,
    )
    existing = db.scalar(
        select(Job)
        .where(
            Job.idempotency_scope_type == scope_type,
            Job.idempotency_scope_id == scope_id,
            Job.idempotency_key == normalized_key,
        )
        .with_for_update()
    )
    if existing is not None:
        if existing.request_hash != request_hash:
            raise JobIdempotencyConflict("Idempotency key was used for another request")
        return existing

    now = datetime.now(UTC)
    job = Job(
        id=uuid4(),
        store_id=store_id,
        idempotency_scope_type=scope_type,
        idempotency_scope_id=scope_id,
        marketing_task_id=marketing_task_id,
        job_type=job_type,
        status="queued",
        priority=priority,
        idempotency_key=normalized_key,
        request_hash=request_hash,
        payload_ref=payload_ref,
        queue_name=queue_name,
        attempt_count=0,
        max_attempts=max_attempts,
        available_at=now,
        timeout_seconds=timeout_seconds,
        actor_type=actor_type,
        created_by_user_id=actor_user_id,
    )
    try:
        with db.begin_nested():
            db.add(job)
            db.flush()
    except IntegrityError as exc:
        winner = db.scalar(
            select(Job).where(
                Job.idempotency_scope_type == scope_type,
                Job.idempotency_scope_id == scope_id,
                Job.idempotency_key == normalized_key,
            )
        )
        if winner is None:
            raise
        if winner.request_hash != request_hash:
            raise JobIdempotencyConflict(
                "Idempotency key was used for another request"
            ) from exc
        return winner

    outbox_id = uuid4()
    db.add(
        OutboxEvent(
            id=outbox_id,
            aggregate_type="job",
            aggregate_id=job.id,
            event_type="job.dispatch_requested",
            schema_version=1,
            payload_json={
                "job_id": str(job.id),
                "dispatch_event_id": str(outbox_id),
                "schema_version": 1,
            },
            dedupe_key=f"job.dispatch:{job.id}",
            status="pending",
            available_at=now,
            publish_attempts=0,
        )
    )
    _append_event(
        db,
        job,
        "job.queued",
        actor_type=actor_type,
        actor_id=actor_user_id,
        data={"job_type": job_type, "queue_name": queue_name},
    )
    db.flush()
    return job


def claim_job(
    db: Session,
    *,
    job_id: UUID,
    worker_id: str,
    lease_seconds: int = 90,
    now: datetime | None = None,
) -> JobClaim | None:
    if not worker_id or len(worker_id) > 200:
        raise ValueError("worker_id must contain 1-200 characters")
    if lease_seconds < 1:
        raise ValueError("lease_seconds must be positive")
    current_time = now or datetime.now(UTC)
    job = db.scalar(
        select(Job)
        .where(
            Job.id == job_id,
            Job.status.in_({"queued", "retry_wait"}),
            Job.available_at <= current_time,
        )
        .with_for_update(skip_locked=True)
    )
    if job is None:
        return None
    if job.attempt_count >= job.max_attempts:
        job.status = "failed"
        job.error_code = "MAX_ATTEMPTS_EXCEEDED"
        job.error_summary = "The job exhausted its execution attempts."
        job.finished_at = current_time
        _clear_lease(job)
        _append_event(job=job, db=db, event_type="job.failed", data={"reason": "max_attempts"})
        db.flush()
        return None

    lease_token = uuid4()
    attempt_no = job.attempt_count + 1
    job.status = "running"
    job.attempt_count = attempt_no
    job.lease_owner = worker_id
    job.lease_token = lease_token
    job.lease_expires_at = current_time + timedelta(seconds=lease_seconds)
    job.heartbeat_at = current_time
    if job.started_at is None:
        job.started_at = current_time

    attempt = JobAttempt(
        id=uuid4(),
        job_id=job.id,
        attempt_no=attempt_no,
        lease_token=lease_token,
        worker_id=worker_id,
        status="running",
        started_at=current_time,
        heartbeat_at=current_time,
    )
    db.add(attempt)
    _append_event(
        db,
        job,
        "job.claimed",
        attempt_id=attempt.id,
        lease_token=lease_token,
        data={"attempt_no": attempt_no, "worker_id": worker_id},
    )
    db.flush()
    return JobClaim(job=job, attempt=attempt)


def _get_owned_job(
    db: Session,
    *,
    job_id: UUID,
    lease_token: UUID,
    worker_id: str,
    now: datetime,
) -> Job:
    job = db.scalar(
        select(Job)
        .where(
            Job.id == job_id,
            Job.status == "running",
            Job.lease_token == lease_token,
            Job.lease_owner == worker_id,
            Job.lease_expires_at > now,
        )
        .with_for_update()
    )
    if job is None:
        raise LeaseLostError("Worker lease is missing, expired or fenced by a newer attempt")
    return job


def _get_running_attempt(db: Session, job: Job, lease_token: UUID) -> JobAttempt:
    attempt = db.scalar(
        select(JobAttempt)
        .where(
            JobAttempt.job_id == job.id,
            JobAttempt.lease_token == lease_token,
            JobAttempt.status == "running",
        )
        .with_for_update()
    )
    if attempt is None:
        raise LeaseLostError("No running attempt owns the supplied lease token")
    return attempt


def heartbeat_job(
    db: Session,
    *,
    job_id: UUID,
    lease_token: UUID,
    worker_id: str,
    lease_seconds: int = 90,
    now: datetime | None = None,
) -> Job:
    if lease_seconds < 1:
        raise ValueError("lease_seconds must be positive")
    current_time = now or datetime.now(UTC)
    job = _get_owned_job(
        db, job_id=job_id, lease_token=lease_token, worker_id=worker_id, now=current_time
    )
    attempt = _get_running_attempt(db, job, lease_token)
    job.heartbeat_at = current_time
    job.lease_expires_at = current_time + timedelta(seconds=lease_seconds)
    attempt.heartbeat_at = current_time
    db.flush()
    return job


def complete_job(
    db: Session,
    *,
    job_id: UUID,
    lease_token: UUID,
    worker_id: str,
    result_ref: dict[str, object],
    now: datetime | None = None,
) -> Job:
    current_time = now or datetime.now(UTC)
    job = _get_owned_job(
        db, job_id=job_id, lease_token=lease_token, worker_id=worker_id, now=current_time
    )
    attempt = _get_running_attempt(db, job, lease_token)
    job.status = "succeeded"
    job.result_ref = result_ref
    job.finished_at = current_time
    _clear_lease(job)
    attempt.status = "succeeded"
    attempt.finished_at = current_time
    attempt.duration_ms = max(
        0, int((current_time - attempt.started_at).total_seconds() * 1000)
    )
    _append_event(
        db,
        job,
        "job.succeeded",
        attempt_id=attempt.id,
        lease_token=lease_token,
    )
    db.flush()
    return job


def fail_job(
    db: Session,
    *,
    job_id: UUID,
    lease_token: UUID,
    worker_id: str,
    error_code: str,
    error_summary: str,
    retryable: bool,
    side_effect_state: SideEffectState = SideEffectState.NONE,
    retry_delay_seconds: int = 30,
    now: datetime | None = None,
) -> Job:
    if not error_code or len(error_code) > 100:
        raise ValueError("error_code must contain 1-100 characters")
    if retry_delay_seconds < 0:
        raise ValueError("retry_delay_seconds cannot be negative")
    current_time = now or datetime.now(UTC)
    job = _get_owned_job(
        db, job_id=job_id, lease_token=lease_token, worker_id=worker_id, now=current_time
    )
    attempt = _get_running_attempt(db, job, lease_token)
    safe_summary = " ".join(error_summary.split())[:500] or "The job failed."
    job.error_code = error_code
    job.error_summary = safe_summary
    attempt.error_code = error_code
    attempt.error_summary = safe_summary
    attempt.status = "failed"
    attempt.finished_at = current_time
    attempt.duration_ms = max(
        0, int((current_time - attempt.started_at).total_seconds() * 1000)
    )

    if side_effect_state is SideEffectState.UNKNOWN:
        job.status = "needs_human"
        job.finished_at = current_time
        event_type = "job.needs_human"
    elif retryable and job.attempt_count < job.max_attempts:
        job.status = "retry_wait"
        job.available_at = current_time + timedelta(seconds=retry_delay_seconds)
        dispatch_event_id = uuid4()
        db.add(
            OutboxEvent(
                id=dispatch_event_id,
                aggregate_type="job",
                aggregate_id=job.id,
                event_type="job.dispatch_requested",
                schema_version=1,
                payload_json={
                    "job_id": str(job.id),
                    "dispatch_event_id": str(dispatch_event_id),
                    "schema_version": 1,
                },
                dedupe_key=f"job.dispatch:{job.id}:attempt:{job.attempt_count + 1}",
                status="pending",
                available_at=job.available_at,
                publish_attempts=0,
            )
        )
        event_type = "job.retry_scheduled"
    else:
        job.status = "failed"
        job.finished_at = current_time
        event_type = "job.failed"

    _clear_lease(job)
    _append_event(
        db,
        job,
        event_type,
        attempt_id=attempt.id,
        lease_token=lease_token,
        data={"error_code": error_code, "retryable": retryable},
    )
    db.flush()
    return job


def request_job_cancellation(
    db: Session,
    *,
    job_id: UUID,
    store_id: UUID,
    actor_user_id: UUID,
    now: datetime | None = None,
) -> Job:
    current_time = now or datetime.now(UTC)
    job = db.scalar(
        select(Job)
        .where(Job.id == job_id, Job.store_id == store_id)
        .with_for_update()
    )
    if job is None:
        raise LookupError("Job not found")
    if job.status in {"succeeded", "failed", "cancelled", "needs_human"}:
        if job.status == "cancelled":
            return job
        raise InvalidJobTransition("A terminal job cannot be cancelled")
    if job.status == "running":
        if job.cancel_requested_at is None:
            job.cancel_requested_at = current_time
            _append_event(
                db,
                job,
                "job.cancel_requested",
                actor_type="user",
                actor_id=actor_user_id,
            )
    else:
        job.status = "cancelled"
        job.cancelled_at = current_time
        job.finished_at = current_time
        _clear_lease(job)
        _append_event(
            db,
            job,
            "job.cancelled",
            actor_type="user",
            actor_id=actor_user_id,
        )
    db.flush()
    return job


def acknowledge_job_cancellation(
    db: Session,
    *,
    job_id: UUID,
    lease_token: UUID,
    worker_id: str,
    now: datetime | None = None,
) -> Job:
    current_time = now or datetime.now(UTC)
    job = _get_owned_job(
        db, job_id=job_id, lease_token=lease_token, worker_id=worker_id, now=current_time
    )
    if job.cancel_requested_at is None:
        raise InvalidJobTransition("No cancellation has been requested")
    attempt = _get_running_attempt(db, job, lease_token)
    job.status = "cancelled"
    job.cancelled_at = current_time
    job.finished_at = current_time
    _clear_lease(job)
    attempt.status = "cancelled"
    attempt.finished_at = current_time
    attempt.duration_ms = max(
        0, int((current_time - attempt.started_at).total_seconds() * 1000)
    )
    _append_event(
        db,
        job,
        "job.cancelled",
        attempt_id=attempt.id,
        lease_token=lease_token,
    )
    db.flush()
    return job
