from __future__ import annotations

import logging
import os
import socket
from datetime import UTC, datetime, timedelta
from math import ceil
from threading import Event, Thread
from uuid import UUID, uuid4

from celery.exceptions import CeleryError  # type: ignore[import-untyped]
from kombu.exceptions import OperationalError
from sqlalchemy import create_engine, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from store_operator.ai_gateway.errors import (  # type: ignore[import-untyped]
    ProviderError,
    SideEffectState,
)
from store_operator.jobs.service import (  # type: ignore[import-untyped]
    InvalidJobTransition,
    LeaseLostError,
    acknowledge_job_cancellation,
    claim_job,
    complete_job,
    fail_job,
    heartbeat_job,
)
from store_operator.models import (  # type: ignore[import-untyped]
    Job,
    JobAttempt,
    JobEvent,
    OutboxEvent,
)

from store_operator_worker.celery_app import celery_app
from store_operator_worker.handlers import (
    JobCancelled,
    JobExecutionContext,
    JobExecutionError,
    JobLeaseLost,
    JobTimedOut,
    resolve_job_handler,
)

database_url = os.environ.get("DATABASE_URL")
if not database_url:
    raise RuntimeError("DATABASE_URL is required to start the worker")

engine = create_engine(database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(
    bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
)
WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"
LEASE_SECONDS = int(os.environ.get("WORKER_LEASE_SECONDS", "90"))
if LEASE_SECONDS < 3:
    raise RuntimeError("WORKER_LEASE_SECONDS must be at least 3")
HEARTBEAT_INTERVAL_SECONDS = max(1, LEASE_SECONDS // 3)
OUTBOX_LOCK_SECONDS = 30
logger = logging.getLogger("store_operator.worker")
OUTBOX_MAX_ATTEMPTS = 12


@celery_app.task(name="jobs.relay_outbox", ignore_result=True)  # type: ignore[untyped-decorator]
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
                raise TypeError("Outbox job_id is invalid")
            celery_app.send_task(
                "jobs.execute",
                args=[job_id],
                task_id=str(event_id),
                queue="default",
            )
        except (CeleryError, OperationalError, OSError, TypeError, ValueError):
            with SessionLocal.begin() as db:
                event = db.scalar(
                    select(OutboxEvent)
                    .where(OutboxEvent.id == event_id)
                    .with_for_update()
                )
                if (
                    event is None
                    or event.locked_by != relay_id
                    or event.locked_until is None
                    or event.locked_until <= datetime.now(UTC)
                ):
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
            if (
                event is None
                or event.locked_by != relay_id
                or event.locked_until is None
                or event.locked_until <= datetime.now(UTC)
            ):
                continue
            event.status = "published"
            event.published_at = datetime.now(UTC)
            event.locked_by = None
            event.locked_until = None
            event.last_error = None
            published += 1
    return published


@celery_app.task(name="jobs.execute", acks_late=True)  # type: ignore[untyped-decorator]
def execute_job(job_id: str) -> dict[str, str]:
    """Claim, execute and persist a Job under a fenced, renewable Worker lease."""
    parsed_job_id = UUID(job_id)
    with SessionLocal.begin() as db:
        claim = claim_job(
            db,
            job_id=parsed_job_id,
            worker_id=WORKER_ID,
            lease_seconds=LEASE_SECONDS,
        )
        if claim is None:
            return {"status": "not_claimed"}
        claimed_job_id = claim.job.id
        attempt_id = claim.attempt.id
        lease_token = claim.attempt.lease_token
        store_id = claim.job.store_id
        job_type = claim.job.job_type
        payload_ref = dict(claim.job.payload_ref)
        timeout_seconds = claim.job.timeout_seconds

    handler = resolve_job_handler(job_type)
    if handler is None:
        with SessionLocal.begin() as db:
            fail_job(
                db,
                job_id=claimed_job_id,
                lease_token=lease_token,
                worker_id=WORKER_ID,
                error_code="JOB_HANDLER_NOT_REGISTERED",
                error_summary="No domain handler is registered for this job type.",
                retryable=False,
            )
        return {"status": "failed", "reason": "handler_not_registered"}

    stop_heartbeat = Event()
    cancellation_requested = Event()
    lease_lost = Event()
    deadline_at = datetime.now(UTC) + timedelta(seconds=timeout_seconds)

    def update_progress(current: int | None, total: int | None) -> None:
        with SessionLocal.begin() as db:
            current_job = heartbeat_job(
                db,
                job_id=claimed_job_id,
                lease_token=lease_token,
                worker_id=WORKER_ID,
                lease_seconds=LEASE_SECONDS,
                progress_current=current,
                progress_total=total,
            )
            if current_job.cancel_requested_at is not None:
                cancellation_requested.set()

    def heartbeat_loop() -> None:
        while not stop_heartbeat.is_set():
            remaining = (deadline_at - datetime.now(UTC)).total_seconds()
            if remaining <= 0:
                try:
                    with SessionLocal.begin() as db:
                        fail_job(
                            db,
                            job_id=claimed_job_id,
                            lease_token=lease_token,
                            worker_id=WORKER_ID,
                            error_code="JOB_TIMEOUT",
                            error_summary=(
                                "Job exceeded its configured execution timeout."
                            ),
                            retryable=False,
                            side_effect_state=SideEffectState.UNKNOWN,
                        )
                except (InvalidJobTransition, LeaseLostError, SQLAlchemyError) as exc:
                    logger.warning(
                        "job.timeout.persist_failed",
                        extra={
                            "job_id": str(claimed_job_id),
                            "error_type": type(exc).__name__,
                        },
                    )
                lease_lost.set()
                return
            if stop_heartbeat.wait(min(HEARTBEAT_INTERVAL_SECONDS, remaining)):
                return
            try:
                update_progress(None, None)
            except (LeaseLostError, SQLAlchemyError, ValueError) as exc:
                lease_lost.set()
                logger.warning(
                    "job.heartbeat.lost",
                    extra={
                        "job_id": str(claimed_job_id),
                        "attempt_id": str(attempt_id),
                        "error_type": type(exc).__name__,
                    },
                )
                return

    heartbeat_thread = Thread(
        target=heartbeat_loop,
        name=f"job-heartbeat-{claimed_job_id}",
        daemon=True,
    )
    context = JobExecutionContext(
        job_id=claimed_job_id,
        store_id=store_id,
        attempt_id=attempt_id,
        lease_token=lease_token,
        worker_id=WORKER_ID,
        deadline_at=deadline_at,
        cancellation_requested=cancellation_requested,
        lease_lost=lease_lost,
        update_progress_callback=update_progress,
    )
    heartbeat_thread.start()
    try:
        update_progress(None, None)
        context.check_control()
        result_ref = handler(context, payload_ref)
        context.check_control()
        with SessionLocal.begin() as db:
            complete_job(
                db,
                job_id=claimed_job_id,
                lease_token=lease_token,
                worker_id=WORKER_ID,
                result_ref=result_ref,
            )
        return {"status": "succeeded"}
    except JobCancelled:
        try:
            with SessionLocal.begin() as db:
                acknowledge_job_cancellation(
                    db,
                    job_id=claimed_job_id,
                    lease_token=lease_token,
                    worker_id=WORKER_ID,
                )
        except (InvalidJobTransition, LeaseLostError, SQLAlchemyError) as exc:
            logger.warning(
                "job.cancel_acknowledgement_failed",
                extra={
                    "job_id": str(claimed_job_id),
                    "error_type": type(exc).__name__,
                },
            )
            return {"status": "lease_lost"}
        return {"status": "cancelled"}
    except JobLeaseLost:
        return {"status": "lease_lost"}
    except JobTimedOut:
        with SessionLocal.begin() as db:
            fail_job(
                db,
                job_id=claimed_job_id,
                lease_token=lease_token,
                worker_id=WORKER_ID,
                error_code="JOB_TIMEOUT",
                error_summary="Job exceeded its configured execution timeout.",
                retryable=False,
                side_effect_state=SideEffectState.UNKNOWN,
            )
        return {"status": "needs_human", "reason": "timeout"}
    except JobExecutionError as exc:
        with SessionLocal.begin() as db:
            fail_job(
                db,
                job_id=claimed_job_id,
                lease_token=lease_token,
                worker_id=WORKER_ID,
                error_code=exc.code,
                error_summary=exc.safe_summary,
                retryable=exc.retryable,
                side_effect_state=exc.side_effect_state,
                retry_delay_seconds=exc.retry_delay_seconds,
            )
        return {"status": "failed", "reason": exc.code}
    except ProviderError as exc:
        with SessionLocal.begin() as db:
            fail_job(
                db,
                job_id=claimed_job_id,
                lease_token=lease_token,
                worker_id=WORKER_ID,
                error_code=exc.code.value,
                error_summary=exc.user_safe_summary,
                retryable=exc.retryable,
                side_effect_state=exc.side_effect_state,
                retry_delay_seconds=(
                    max(0, ceil(exc.retry_after_seconds))
                    if exc.retry_after_seconds is not None
                    else 30
                ),
            )
        return {"status": "failed", "reason": exc.code.value}
    except Exception as exc:  # noqa: BLE001 - final sanitized execution boundary
        logger.error(
            "job.execution.unexpected",
            extra={
                "job_id": str(claimed_job_id),
                "attempt_id": str(attempt_id),
                "error_type": type(exc).__name__,
            },
        )
        try:
            with SessionLocal.begin() as db:
                fail_job(
                    db,
                    job_id=claimed_job_id,
                    lease_token=lease_token,
                    worker_id=WORKER_ID,
                    error_code="WORKER_UNEXPECTED_ERROR",
                    error_summary=(
                        "Job failed unexpectedly; external side-effect state requires review."
                    ),
                    retryable=False,
                    side_effect_state=SideEffectState.UNKNOWN,
                )
        except (InvalidJobTransition, LeaseLostError, SQLAlchemyError) as persist_exc:
            logger.error(
                "job.failure_persist.failed",
                extra={
                    "job_id": str(claimed_job_id),
                    "error_type": type(persist_exc).__name__,
                },
            )
        return {"status": "needs_human", "reason": "unexpected_error"}
    finally:
        stop_heartbeat.set()
        heartbeat_thread.join(timeout=HEARTBEAT_INTERVAL_SECONDS + 1)


@celery_app.task(
    name="jobs.recover_expired_leases", ignore_result=True
)  # type: ignore[untyped-decorator]
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
