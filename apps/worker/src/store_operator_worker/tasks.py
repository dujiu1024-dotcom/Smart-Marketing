from __future__ import annotations

import os
import socket
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import create_engine, or_, select
from sqlalchemy.orm import sessionmaker

from store_operator.jobs.service import claim_job, fail_job
from store_operator.models import Job, JobAttempt, JobEvent, OutboxEvent
from store_operator_worker.celery_app import celery_app

database_url = os.environ.get("DATABASE_URL")
if not database_url:
    raise RuntimeError("DATABASE_URL is required to start the worker")

engine = create_engine(database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(
    bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
)
WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"
OUTBOX_LOCK_SECONDS = 30
OUTBOX_MAX_ATTEMPTS = 12


@celery_app.task(name="jobs.relay_outbox", ignore_result=True)
def relay_outbox(batch_size: int = 50) -> int:
    """Publish committed Outbox rows; a crash after publish can cause safe redelivery."""
    now = datetime.now(UTC)
    relay_id = f"{WORKER_ID}:{uuid4()}"
    with SessionLocal.begin() as db:
        events = db.scalars(
            select(OutboxEvent)
            .where(
                OutboxEvent.available_at <= now,
                or_(
                    OutboxEvent.status == "pending",
                    (
                        (OutboxEvent.status == "publishing")
                        & (OutboxEvent.locked_until < now)
                    ),
                ),
            )
            .order_by(OutboxEvent.created_at, OutboxEvent.id)
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        ).all()
        for event in events:
            event.status = "publishing"
            event.locked_by = relay_id
            event.locked_until = now + timedelta(seconds=OUTBOX_LOCK_SECONDS)
            event.publish_attempts += 1
        event_ids = [event.id for event in events]

    published = 0
    for event_id in event_ids:
        with SessionLocal() as db:
            event = db.get(OutboxEvent, event_id)
            if (
                event is None
                or event.status != "publishing"
                or event.locked_by != relay_id
            ):
                continue
            event_type = event.event_type
            payload = dict(event.payload_json)
        try:
            if event_type != "job.dispatch_requested":
                raise ValueError("Unsupported Outbox event type")
            job_id = payload.get("job_id")
            if not isinstance(job_id, str):
                raise ValueError("Outbox job_id is invalid")
            celery_app.send_task(
                "jobs.execute",
                args=[job_id],
                task_id=str(event_id),
                queue="default",
            )
        except Exception:
            with SessionLocal.begin() as db:
                event = db.scalar(
                    select(OutboxEvent)
                    .where(OutboxEvent.id == event_id)
                    .with_for_update()
                )
                if event is None or event.locked_by != relay_id:
                    continue
                event.last_error = "Outbox dispatch failed; inspect sanitized worker logs"
                event.locked_by = None
                event.locked_until = None
                if event.publish_attempts >= OUTBOX_MAX_ATTEMPTS:
                    event.status = "dead"
                else:
                    event.status = "pending"
                    event.available_at = datetime.now(UTC) + timedelta(
                        seconds=min(300, 2 ** min(event.publish_attempts, 8))
                    )
            continue

        with SessionLocal.begin() as db:
            event = db.scalar(
                select(OutboxEvent)
                .where(OutboxEvent.id == event_id)
                .with_for_update()
            )
            if event is None or event.locked_by != relay_id:
                continue
            event.status = "published"
            event.published_at = datetime.now(UTC)
            event.locked_by = None
            event.locked_until = None
            event.last_error = None
            published += 1
    return published


@celery_app.task(name="jobs.execute", acks_late=True)
def execute_job(job_id: str) -> dict[str, str]:
    """Claim a durable Job; domain handlers are registered in a later capability slice."""
    parsed_job_id = UUID(job_id)
    with SessionLocal.begin() as db:
        claim = claim_job(
            db,
            job_id=parsed_job_id,
            worker_id=WORKER_ID,
        )
    if claim is None:
        return {"status": "not_claimed"}

    # Never acknowledge work as successful until a domain handler actually runs.
    with SessionLocal.begin() as db:
        fail_job(
            db,
            job_id=claim.job.id,
            lease_token=claim.attempt.lease_token,
            worker_id=WORKER_ID,
            error_code="JOB_HANDLER_NOT_REGISTERED",
            error_summary="No domain handler is registered for this job type.",
            retryable=False,
        )
    return {"status": "failed", "reason": "handler_not_registered"}


@celery_app.task(name="jobs.recover_expired_leases", ignore_result=True)
def recover_expired_leases(batch_size: int = 100) -> int:
    """Fence expired Workers and require review because external side effects may be unknown."""
    now = datetime.now(UTC)
    recovered = 0
    with SessionLocal.begin() as db:
        jobs = db.scalars(
            select(Job)
            .where(Job.status == "running", Job.lease_expires_at < now)
            .order_by(Job.lease_expires_at, Job.id)
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        ).all()
        for job in jobs:
            token = job.lease_token
            attempt = db.scalar(
                select(JobAttempt)
                .where(
                    JobAttempt.job_id == job.id,
                    JobAttempt.lease_token == token,
                    JobAttempt.status == "running",
                )
                .with_for_update()
            )
            if attempt is not None:
                attempt.status = "lease_expired"
                attempt.finished_at = now
                attempt.error_code = "WORKER_LEASE_EXPIRED"
                attempt.error_summary = "Worker lease expired before a terminal result."
                attempt.duration_ms = max(
                    0, int((now - attempt.started_at).total_seconds() * 1000)
                )
            job.status = "needs_human"
            job.error_code = "WORKER_LEASE_EXPIRED"
            job.error_summary = (
                "Worker lease expired; external side-effect state requires reconciliation."
            )
            job.finished_at = now
            job.lease_owner = None
            job.lease_token = None
            job.lease_expires_at = None
            job.heartbeat_at = None
            db.add(
                JobEvent(
                    job_id=job.id,
                    event_type="job.lease_expired",
                    actor_type="system",
                    attempt_id=attempt.id if attempt else None,
                    lease_token=token,
                    data_json={"recovery": "needs_human"},
                )
            )
            recovered += 1
    return recovered
