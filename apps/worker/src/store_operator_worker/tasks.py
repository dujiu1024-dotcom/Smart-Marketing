from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import socket
from datetime import UTC, datetime, timedelta
from math import ceil
from threading import Event, Thread
from uuid import UUID, uuid4

from celery.exceptions import CeleryError  # type: ignore[import-untyped]
from kombu.exceptions import OperationalError
from sqlalchemy import create_engine, func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from store_operator.ai_gateway.errors import (  # type: ignore[import-untyped]
    ProviderError,
    SideEffectState,
)
from store_operator.jobs.service import (  # type: ignore[import-untyped]
    InvalidJobTransition,
    create_job,
    LeaseLostError,
    acknowledge_job_cancellation,
    claim_job,
    complete_job,
    fail_job,
    heartbeat_job,
)
from store_operator.models import (  # type: ignore[import-untyped]
    Artifact,
    ChannelAccount,
    ArtifactVersion,
    ChannelContent,
    ChannelContentArtifactRef,
    Job,
    JobAttempt,
    JobEvent,
    OutboxEvent,
    PublishOperation,
    PublishPackage,
    PublishPackageItem,
    PublishConfirmation,
    MediaAsset,
    QualityReport,
    ReviewRecord,
)

from store_operator.channels.douyin import (
    DouyinApiError,
    DouyinAppCredentials,
    DouyinOAuthClient,
)
from store_operator.channels.secret_store import AwsSecretsManagerStore, SecretStoreError
from store_operator.config import settings
from store_operator.object_storage import read_object_bytes
from store_operator_worker.celery_app import celery_app
from store_operator_worker.handlers import (
    JobCancelled,
    JobExecutionContext,
    JobExecutionError,
    JobLeaseLost,
    JobTimedOut,
    register_job_handler,
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
MAX_RUNNING_JOBS_PER_STORE = int(os.environ.get("WORKER_MAX_RUNNING_JOBS_PER_STORE", "3"))
CONCURRENCY_DEFER_SECONDS = int(os.environ.get("WORKER_CONCURRENCY_DEFER_SECONDS", "10"))
if MAX_RUNNING_JOBS_PER_STORE < 1 or CONCURRENCY_DEFER_SECONDS < 1:
    raise RuntimeError("Worker store concurrency settings must be positive")


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
            max_running_per_store=MAX_RUNNING_JOBS_PER_STORE,
            concurrency_defer_seconds=CONCURRENCY_DEFER_SECONDS,
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



@register_job_handler("content.quality_check")
def execute_content_quality_check(
    context: JobExecutionContext,
    payload_ref: dict[str, object],
) -> dict[str, object]:
    """Persist an immutable, fingerprint-bound deterministic content quality report."""
    from store_operator_worker.quality_rules import RULE_VERSION, evaluate_content

    context.check_control()
    if context.store_id is None:
        raise JobExecutionError(
            "QUALITY_STORE_REQUIRED",
            "Quality checks require a store-scoped job.",
            retryable=False,
        )
    if payload_ref.get("schema_version") != 1:
        raise JobExecutionError(
            "QUALITY_SCHEMA_UNSUPPORTED",
            "Quality check payload schema is unsupported.",
            retryable=False,
        )
    content_id_value = payload_ref.get("channel_content_id")
    expected_fingerprint = payload_ref.get("expected_fingerprint")
    rule_version = payload_ref.get("rule_version")
    if not isinstance(content_id_value, str) or not isinstance(expected_fingerprint, str):
        raise JobExecutionError(
            "QUALITY_PAYLOAD_INVALID",
            "Quality check payload is invalid.",
            retryable=False,
        )
    if rule_version != RULE_VERSION:
        raise JobExecutionError(
            "QUALITY_RULE_VERSION_UNSUPPORTED",
            "Requested quality rule version is not installed.",
            retryable=False,
        )

    try:
        content_id = UUID(content_id_value)
    except ValueError as exc:
        raise JobExecutionError(
            "QUALITY_PAYLOAD_INVALID",
            "Quality check payload is invalid.",
            retryable=False,
        ) from exc

    with SessionLocal.begin() as db:
        channel_content = db.scalar(
            select(ChannelContent)
            .where(
                ChannelContent.id == content_id,
                ChannelContent.store_id == context.store_id,
            )
            .with_for_update()
        )
        if (
            channel_content is None
            or channel_content.input_fingerprint != expected_fingerprint
        ):
            raise JobExecutionError(
                "CHANNEL_CONTENT_STALE",
                "Channel content changed before quality checking.",
                retryable=False,
            )

        copy_version = db.scalar(
            select(ArtifactVersion)
            .join(Artifact, Artifact.id == ArtifactVersion.artifact_id)
            .where(
                ArtifactVersion.id == channel_content.copy_version_id,
                ArtifactVersion.store_id == context.store_id,
                Artifact.store_id == context.store_id,
                Artifact.current_version_id == ArtifactVersion.id,
                Artifact.artifact_type == "copy",
            )
        )
        if copy_version is None:
            raise JobExecutionError(
                "COPY_VERSION_STALE",
                "The approved copy version is no longer current.",
                retryable=False,
            )
        approved_copy = db.scalar(
            select(ReviewRecord.id).where(
                ReviewRecord.store_id == context.store_id,
                ReviewRecord.artifact_id == copy_version.artifact_id,
                ReviewRecord.artifact_version_id == copy_version.id,
                ReviewRecord.review_type == "copy",
                ReviewRecord.decision == "approved",
            )
        )
        if approved_copy is None:
            raise JobExecutionError(
                "COPY_REVIEW_REQUIRED",
                "The copy version is not approved.",
                retryable=False,
            )

        image_refs = db.scalars(
            select(ChannelContentArtifactRef).where(
                ChannelContentArtifactRef.store_id == context.store_id,
                ChannelContentArtifactRef.channel_content_id == channel_content.id,
            )
        ).all()
        for image_ref in image_refs:
            image_version = db.scalar(
                select(ArtifactVersion)
                .join(Artifact, Artifact.id == ArtifactVersion.artifact_id)
                .where(
                    ArtifactVersion.id == image_ref.artifact_version_id,
                    ArtifactVersion.store_id == context.store_id,
                    Artifact.store_id == context.store_id,
                    Artifact.current_version_id == ArtifactVersion.id,
                    Artifact.artifact_type == "image",
                )
            )
            approved_image = (
                db.scalar(
                    select(ReviewRecord.id).where(
                        ReviewRecord.store_id == context.store_id,
                        ReviewRecord.artifact_id == image_version.artifact_id,
                        ReviewRecord.artifact_version_id == image_version.id,
                        ReviewRecord.review_type == "image",
                        ReviewRecord.decision == "approved",
                    )
                )
                if image_version is not None
                else None
            )
            if approved_image is None:
                raise JobExecutionError(
                    "IMAGE_REVIEW_REQUIRED",
                    "A referenced image version is no longer approved and current.",
                    retryable=False,
                )

        fingerprint_payload = {
            "channel_content_id": str(channel_content.id),
            "channel_content_fingerprint": channel_content.input_fingerprint,
            "rule_version": RULE_VERSION,
        }
        canonical = json.dumps(
            fingerprint_payload, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        report_fingerprint = hashlib.sha256(canonical).hexdigest()
        report = db.scalar(
            select(QualityReport).where(
                QualityReport.store_id == context.store_id,
                QualityReport.channel_content_id == channel_content.id,
                QualityReport.rule_version == RULE_VERSION,
                QualityReport.input_fingerprint == report_fingerprint,
            )
        )
        if report is None:
            merged_content = dict(copy_version.content_json or {})
            merged_content.update(channel_content.payload_json)
            result, issues = evaluate_content(merged_content)
            report = QualityReport(
                id=uuid4(),
                store_id=context.store_id,
                task_id=channel_content.task_id,
                channel_content_id=channel_content.id,
                rule_version=RULE_VERSION,
                input_fingerprint=report_fingerprint,
                result=result,
                issues_json=issues,
            )
            db.add(report)
            db.flush()
        report_id = report.id
        report_result = report.result
        report_fingerprint = report.input_fingerprint

    context.check_control()
    return {
        "schema_version": 1,
        "quality_report_id": str(report_id),
        "result": report_result,
        "input_fingerprint": report_fingerprint,
        "rule_version": RULE_VERSION,
    }


DOUYIN_IMAGE_MAX_BYTES = 20 * 1024 * 1024
DOUYIN_READBACK_MAX_ATTEMPTS = 12


def _schedule_douyin_readback(
    operation_id: UUID,
    *,
    readback_attempt: int,
) -> None:
    if not 1 <= readback_attempt <= DOUYIN_READBACK_MAX_ATTEMPTS:
        raise ValueError("Invalid Douyin readback attempt")
    now = datetime.now(UTC)
    delay_seconds = min(60 * (2 ** (readback_attempt - 1)), 3600)
    available_at = now + timedelta(seconds=delay_seconds)
    with SessionLocal.begin() as db:
        operation = db.scalar(
            select(PublishOperation)
            .where(PublishOperation.id == operation_id)
            .with_for_update()
        )
        if operation is None or operation.status != "processing":
            return
        package = db.scalar(
            select(PublishPackage).where(
                PublishPackage.id == operation.publish_package_id,
                PublishPackage.store_id == operation.store_id,
            )
        )
        if package is None:
            raise RuntimeError("Publish package is missing for a readback operation")
        job = create_job(
            db,
            job_type="channel.douyin.readback",
            payload_ref={
                "schema_version": 1,
                "publish_operation_id": str(operation.id),
                "readback_attempt": readback_attempt,
            },
            idempotency_key=f"douyin-readback:{operation.id}:{readback_attempt}",
            store_id=operation.store_id,
            actor_type="user",
            actor_user_id=operation.confirmed_by_user_id,
            marketing_task_id=package.task_id,
            max_attempts=3,
            timeout_seconds=180,
        )
        job.available_at = available_at
        dispatch = db.scalar(
            select(OutboxEvent).where(
                OutboxEvent.aggregate_id == job.id,
                OutboxEvent.event_type == "job.dispatch_requested",
            )
        )
        if dispatch is None:
            raise RuntimeError("Readback job has no durable Outbox dispatch event")
        dispatch.available_at = available_at
        operation.next_attempt_at = available_at
        operation.updated_at = now
        db.flush()


def _load_douyin_publish_context(
    *, operation_id: UUID, store_id: UUID
) -> dict[str, object]:
    with SessionLocal.begin() as db:
        operation = db.scalar(
            select(PublishOperation)
            .where(
                PublishOperation.id == operation_id,
                PublishOperation.store_id == store_id,
            )
            .with_for_update()
        )
        if operation is None:
            raise JobExecutionError(
                "PUBLISH_OPERATION_NOT_FOUND",
                "The publish operation is not available for this store.",
                retryable=False,
            )
        package = db.scalar(
            select(PublishPackage).where(
                PublishPackage.id == operation.publish_package_id,
                PublishPackage.store_id == store_id,
            )
        )
        item = db.scalar(
            select(PublishPackageItem).where(
                PublishPackageItem.id == operation.publish_package_item_id,
                PublishPackageItem.store_id == store_id,
                PublishPackageItem.publish_package_id == operation.publish_package_id,
            )
        )
        confirmation = db.scalar(
            select(PublishConfirmation).where(
                PublishConfirmation.id == operation.publish_confirmation_id,
                PublishConfirmation.store_id == store_id,
                PublishConfirmation.publish_package_id == operation.publish_package_id,
                PublishConfirmation.package_fingerprint
                == operation.confirmed_package_fingerprint,
            )
        )
        account = db.scalar(
            select(ChannelAccount).where(
                ChannelAccount.id == operation.channel_account_id,
                ChannelAccount.store_id == store_id,
                ChannelAccount.provider == "douyin",
                ChannelAccount.status == "active",
            )
        )
        if package is None or item is None or confirmation is None or account is None:
            operation.status = "needs_human"
            operation.last_error_code = "PUBLISH_PREREQUISITE_CHANGED"
            operation.last_error_summary = (
                "The confirmed package, account or confirmation is no longer valid."
            )
            operation.updated_at = datetime.now(UTC)
            raise JobExecutionError(
                "PUBLISH_PREREQUISITE_CHANGED",
                "The confirmed package or Douyin account is no longer valid.",
                retryable=False,
            )
        if (
            package.package_fingerprint != operation.confirmed_package_fingerprint
            or item.delivery_mode != "official_api"
            or item.channel_key != "douyin"
            or item.channel_account_id != account.id
        ):
            operation.status = "needs_human"
            operation.last_error_code = "PUBLISH_PACKAGE_BINDING_INVALID"
            operation.last_error_summary = "The frozen package binding is invalid."
            operation.updated_at = datetime.now(UTC)
            raise JobExecutionError(
                "PUBLISH_PACKAGE_BINDING_INVALID",
                "The frozen package is not bound to the confirmed Douyin account.",
                retryable=False,
            )
        latest_version = db.scalar(
            select(func.max(PublishPackage.package_version)).where(
                PublishPackage.store_id == store_id,
                PublishPackage.task_id == package.task_id,
            )
        )
        if latest_version != package.package_version:
            operation.status = "needs_human"
            operation.last_error_code = "PUBLISH_PACKAGE_SUPERSEDED"
            operation.last_error_summary = "A newer package version exists."
            operation.updated_at = datetime.now(UTC)
            raise JobExecutionError(
                "PUBLISH_PACKAGE_SUPERSEDED",
                "A newer publish package exists; create and confirm a new package.",
                retryable=False,
            )
        if operation.status == "published":
            return {"already_published": True, "operation_id": str(operation.id)}
        if operation.status == "needs_human":
            raise JobExecutionError(
                "PUBLISH_NEEDS_HUMAN",
                "The publish operation requires manual verification.",
                retryable=False,
                side_effect_state=SideEffectState.UNKNOWN,
            )
        if operation.status == "submitting" and not operation.platform_item_id:
            operation.status = "needs_human"
            operation.last_error_code = "PUBLISH_RESULT_UNKNOWN"
            operation.last_error_summary = (
                "The platform submission result is unknown; blind resubmission is disabled."
            )
            operation.updated_at = datetime.now(UTC)
            raise JobExecutionError(
                "PUBLISH_RESULT_UNKNOWN",
                "The platform submission result is unknown; manual verification is required.",
                retryable=False,
                side_effect_state=SideEffectState.UNKNOWN,
            )
        if operation.status == "processing" and operation.platform_item_id:
            return {
                "operation_id": str(operation.id),
                "store_id": str(store_id),
                "account_id": str(account.id),
                "open_id": account.external_account_id,
                "access_token_secret_ref": account.access_token_secret_ref,
                "access_token_expires_at": account.access_token_expires_at.isoformat(),
                "platform_item_id": operation.platform_item_id,
                "already_submitted": True,
            }
        if operation.status not in {"queued", "uploading"}:
            raise JobExecutionError(
                "PUBLISH_OPERATION_NOT_READY",
                "The publish operation is not in a publishable state.",
                retryable=False,
            )
        content = db.scalar(
            select(ChannelContent).where(
                ChannelContent.id == item.channel_content_id,
                ChannelContent.store_id == store_id,
                ChannelContent.task_id == package.task_id,
                ChannelContent.channel_key == "douyin",
                ChannelContent.status == "ready",
            )
        )
        if content is None:
            operation.status = "needs_human"
            operation.last_error_code = "CHANNEL_CONTENT_NOT_READY"
            operation.last_error_summary = "The frozen Douyin content is no longer ready."
            operation.updated_at = datetime.now(UTC)
            raise JobExecutionError(
                "CHANNEL_CONTENT_NOT_READY",
                "The frozen Douyin content is no longer ready.",
                retryable=False,
            )
        refs = db.scalars(
            select(ChannelContentArtifactRef)
            .where(
                ChannelContentArtifactRef.store_id == store_id,
                ChannelContentArtifactRef.channel_content_id == content.id,
            )
            .order_by(ChannelContentArtifactRef.position)
        ).all()
        if not refs or len(refs) > 30:
            raise JobExecutionError(
                "DOUYIN_IMAGE_COUNT_INVALID",
                "Douyin image-text publishing requires 1 to 30 approved images.",
                retryable=False,
            )
        images: list[dict[str, object]] = []
        for ref in refs:
            row = db.execute(
                select(ArtifactVersion, Artifact)
                .join(Artifact, Artifact.id == ArtifactVersion.artifact_id)
                .where(
                    ArtifactVersion.id == ref.artifact_version_id,
                    ArtifactVersion.store_id == store_id,
                    Artifact.store_id == store_id,
                    Artifact.artifact_type == "image",
                )
            ).first()
            if row is None:
                raise JobExecutionError(
                    "DOUYIN_IMAGE_VERSION_MISSING",
                    "An approved image version is no longer available.",
                    retryable=False,
                )
            version, artifact = row
            if not version.content_ref:
                raise JobExecutionError(
                    "DOUYIN_IMAGE_OBJECT_REQUIRED",
                    "An image must be stored as a private object before publishing.",
                    retryable=False,
                )
            if not version.content_ref.startswith(f"stores/{store_id}/"):
                raise JobExecutionError(
                    "DOUYIN_IMAGE_OBJECT_SCOPE_INVALID",
                    "An image object is outside the authorized store namespace.",
                    retryable=False,
                )
            media_asset_id = next(
                (
                    source.get("id")
                    for source in version.source_refs_json
                    if isinstance(source, dict) and source.get("type") == "media_asset"
                ),
                None,
            )
            if media_asset_id:
                media_asset = db.scalar(
                    select(MediaAsset).where(
                        MediaAsset.id == UUID(str(media_asset_id)),
                        MediaAsset.store_id == store_id,
                    )
                )
                if (
                    media_asset is None
                    or media_asset.status != "ready"
                    or media_asset.usage_rights_status != "confirmed_allowed"
                ):
                    raise JobExecutionError(
                        "DOUYIN_MEDIA_ASSET_NOT_USABLE",
                        "A referenced source image is no longer approved for use.",
                        retryable=False,
                    )
            images.append(
                {
                    "object_key": version.content_ref,
                    "content_hash": version.content_hash,
                    "artifact_version_id": str(version.id),
                }
            )
        payload = content.payload_json
        title = payload.get("title", "")
        body = payload.get("body", "")
        if not isinstance(title, str) or not isinstance(body, str):
            raise JobExecutionError(
                "DOUYIN_CONTENT_TEXT_INVALID",
                "Douyin post title and body must be text.",
                retryable=False,
            )
        post_text = "\\n".join(part.strip() for part in (title, body) if part.strip())
        if not post_text or len(post_text) > 1000:
            raise JobExecutionError(
                "DOUYIN_CONTENT_TEXT_INVALID",
                "Douyin post text must contain 1 to 1000 characters.",
                retryable=False,
            )
        if "video.create" not in set(account.granted_scopes):
            raise JobExecutionError(
                "DOUYIN_PUBLISH_SCOPE_MISSING",
                "The connected Douyin account lacks the required publishing permission.",
                retryable=False,
            )
        if account.access_token_expires_at <= datetime.now(UTC):
            raise JobExecutionError(
                "DOUYIN_TOKEN_EXPIRED",
                "The Douyin account token has expired; refresh authorization before publishing.",
                retryable=False,
            )
        operation.status = "uploading"
        operation.attempt_count += 1
        operation.updated_at = datetime.now(UTC)
        db.flush()
        return {
            "operation_id": str(operation.id),
            "store_id": str(store_id),
            "account_id": str(account.id),
            "open_id": account.external_account_id,
            "access_token_secret_ref": account.access_token_secret_ref,
            "access_token_expires_at": account.access_token_expires_at.isoformat(),
            "images": images,
            "text": post_text,
            "already_submitted": False,
        }


def _mark_douyin_operation(
    operation_id: UUID,
    *,
    status: str,
    platform_item_id: str | None = None,
    error_code: str | None = None,
    error_summary: str | None = None,
    next_attempt_at: datetime | None = None,
) -> None:
    with SessionLocal.begin() as db:
        operation = db.scalar(
            select(PublishOperation)
            .where(PublishOperation.id == operation_id)
            .with_for_update()
        )
        if operation is None:
            raise RuntimeError("Publish operation disappeared")
        operation.status = status
        if platform_item_id is not None:
            operation.platform_item_id = platform_item_id
        if status == "processing":
            operation.submitted_at = operation.submitted_at or datetime.now(UTC)
        if status == "published":
            operation.published_at = datetime.now(UTC)
            operation.last_readback_at = datetime.now(UTC)
            operation.next_attempt_at = None
        if error_code is not None:
            operation.last_error_code = error_code
        if error_summary is not None:
            operation.last_error_summary = error_summary
        if next_attempt_at is not None:
            operation.next_attempt_at = next_attempt_at
        operation.updated_at = datetime.now(UTC)


def _load_douyin_access_token(secret_ref: str) -> str:
    if not settings.channel_secret_store_region:
        raise SecretStoreError("Channel credential storage is not configured")
    store = AwsSecretsManagerStore(region_name=settings.channel_secret_store_region)
    secret = store.get_json(secret_ref)
    token = secret.get("access_token")
    if not token:
        raise SecretStoreError("Douyin access token is missing")
    return token


async def _douyin_publish_images(
    *,
    access_token: str,
    open_id: str,
    images: list[dict[str, object]],
    text: str,
) -> str:
    if not settings.douyin_client_key or not settings.douyin_client_secret:
        raise ValueError("Douyin application credentials are not configured")
    client = DouyinOAuthClient(
        DouyinAppCredentials(
            client_key=settings.douyin_client_key,
            client_secret=settings.douyin_client_secret,
        )
    )
    try:
        uploaded_ids: list[str] = []
        for image in images:
            object_key = str(image["object_key"])
            content, content_type = read_object_bytes(
                object_key=object_key,
                max_bytes=DOUYIN_IMAGE_MAX_BYTES,
            )
            if hashlib.sha256(content).hexdigest() != image["content_hash"]:
                raise ValueError("Stored image hash does not match its immutable artifact version")
            uploaded = await client.upload_image(
                access_token=access_token,
                filename=object_key.rsplit("/", 1)[-1],
                content=content,
                content_type=content_type,
            )
            uploaded_ids.append(str(uploaded["image_id"]))
        receipt = await client.publish_images(
            access_token=access_token,
            open_id=open_id,
            image_ids=uploaded_ids,
            text=text,
            merchant_confirmed=True,
        )
        return receipt.item_id
    finally:
        await client.aclose()


async def _douyin_readback(
    *, access_token: str, open_id: str, item_id: str
) -> dict[str, object] | None:
    if not settings.douyin_client_key or not settings.douyin_client_secret:
        raise ValueError("Douyin application credentials are not configured")
    client = DouyinOAuthClient(
        DouyinAppCredentials(
            client_key=settings.douyin_client_key,
            client_secret=settings.douyin_client_secret,
        )
    )
    try:
        return await client.verify_published_item(
            access_token=access_token,
            open_id=open_id,
            item_id=item_id,
        )
    finally:
        await client.aclose()


@register_job_handler("channel.douyin.publish")
def execute_douyin_publish(
    context: JobExecutionContext,
    payload_ref: dict[str, object],
) -> dict[str, object]:
    context.check_control()
    if context.store_id is None or payload_ref.get("schema_version") != 1:
        raise JobExecutionError(
            "DOUYIN_PUBLISH_PAYLOAD_INVALID",
            "Douyin publish job payload is invalid.",
            retryable=False,
        )
    try:
        operation_id = UUID(str(payload_ref.get("publish_operation_id")))
    except (ValueError, TypeError) as exc:
        raise JobExecutionError(
            "DOUYIN_PUBLISH_PAYLOAD_INVALID",
            "Douyin publish job payload is invalid.",
            retryable=False,
        ) from exc
    data = _load_douyin_publish_context(operation_id=operation_id, store_id=context.store_id)
    if data.get("already_published"):
        return {"status": "published", "publish_operation_id": str(operation_id)}
    if data.get("already_submitted"):
        _schedule_douyin_readback(operation_id, readback_attempt=1)
        return {"status": "processing", "publish_operation_id": str(operation_id)}
    try:
        access_token = _load_douyin_access_token(str(data["access_token_secret_ref"]))
    except SecretStoreError as exc:
        raise JobExecutionError(
            "DOUYIN_SECRET_STORE_UNAVAILABLE",
            "Douyin credentials could not be retrieved securely.",
            retryable=True,
            retry_delay_seconds=60,
        ) from exc

    context.check_control()
    with SessionLocal.begin() as db:
        operation = db.scalar(
            select(PublishOperation)
            .where(PublishOperation.id == operation_id)
            .with_for_update()
        )
        if operation is None:
            raise JobExecutionError(
                "PUBLISH_OPERATION_NOT_FOUND",
                "The publish operation is no longer available.",
                retryable=False,
            )
        operation.status = "uploading"
        operation.updated_at = datetime.now(UTC)
    try:
        item_id = asyncio.run(
            _douyin_publish_images(
                access_token=access_token,
                open_id=str(data["open_id"]),
                images=data["images"],  # type: ignore[arg-type]
                text=str(data["text"]),
            )
        )
    except (ValueError, DouyinApiError) as exc:
        # The upload phase is safe to retry; no public item has been submitted yet.
        raise JobExecutionError(
            "DOUYIN_UPLOAD_FAILED",
            "Douyin image upload failed before public submission.",
            retryable=True,
            retry_delay_seconds=60,
        ) from exc
    context.check_control()
    with SessionLocal.begin() as db:
        operation = db.scalar(
            select(PublishOperation)
            .where(PublishOperation.id == operation_id)
            .with_for_update()
        )
        if operation is None:
            raise JobExecutionError(
                "PUBLISH_OPERATION_NOT_FOUND",
                "The publish operation is no longer available.",
                retryable=False,
            )
        operation.status = "submitting"
        operation.updated_at = datetime.now(UTC)
    try:
        # This call has an external side effect. Any transport error is treated as
        # uncertain; never retry create blindly.
        item_id = asyncio.run(
            _douyin_publish_images(
                access_token=access_token,
                open_id=str(data["open_id"]),
                images=[],  # uploaded IDs are not retained across this boundary
                text=str(data["text"]),
            )
        )
    except Exception as exc:
        _mark_douyin_operation(
            operation_id,
            status="needs_human",
            error_code="DOUYIN_PUBLISH_RESULT_UNKNOWN",
            error_summary="The platform submission result is unknown; manual verification is required.",
        )
        raise JobExecutionError(
            "DOUYIN_PUBLISH_RESULT_UNKNOWN",
            "The platform submission result is unknown; manual verification is required.",
            retryable=False,
            side_effect_state=SideEffectState.UNKNOWN,
        ) from exc
    _mark_douyin_operation(operation_id, status="processing", platform_item_id=item_id)
    context.check_control()
    try:
        found = asyncio.run(
            _douyin_readback(
                access_token=access_token,
                open_id=str(data["open_id"]),
                item_id=item_id,
            )
        )
    except Exception:
        found = None
    if found is not None:
        _mark_douyin_operation(operation_id, status="published")
        return {
            "status": "published",
            "publish_operation_id": str(operation_id),
            "platform_item_id": item_id,
        }
    _schedule_douyin_readback(operation_id, readback_attempt=1)
    return {
        "status": "processing",
        "publish_operation_id": str(operation_id),
        "platform_item_id": item_id,
    }


@register_job_handler("channel.douyin.readback")
def execute_douyin_readback(
    context: JobExecutionContext,
    payload_ref: dict[str, object],
) -> dict[str, object]:
    context.check_control()
    if context.store_id is None or payload_ref.get("schema_version") != 1:
        raise JobExecutionError(
            "DOUYIN_READBACK_PAYLOAD_INVALID",
            "Douyin readback job payload is invalid.",
            retryable=False,
        )
    try:
        operation_id = UUID(str(payload_ref.get("publish_operation_id")))
        attempt = int(payload_ref.get("readback_attempt", 0))
    except (ValueError, TypeError) as exc:
        raise JobExecutionError(
            "DOUYIN_READBACK_PAYLOAD_INVALID",
            "Douyin readback job payload is invalid.",
            retryable=False,
        ) from exc
    if not 1 <= attempt <= DOUYIN_READBACK_MAX_ATTEMPTS:
        raise JobExecutionError(
            "DOUYIN_READBACK_ATTEMPT_INVALID",
            "Douyin readback attempt is invalid.",
            retryable=False,
        )
    with SessionLocal.begin() as db:
        operation = db.scalar(
            select(PublishOperation)
            .where(
                PublishOperation.id == operation_id,
                PublishOperation.store_id == context.store_id,
            )
            .with_for_update()
        )
        if operation is None or operation.status != "processing" or not operation.platform_item_id:
            raise JobExecutionError(
                "DOUYIN_READBACK_NOT_AVAILABLE",
                "The publish operation is not awaiting readback.",
                retryable=False,
            )
        account = db.scalar(
            select(ChannelAccount).where(
                ChannelAccount.id == operation.channel_account_id,
                ChannelAccount.store_id == context.store_id,
                ChannelAccount.status == "active",
            )
        )
        if account is None or account.access_token_expires_at <= datetime.now(UTC):
            operation.status = "needs_human"
            operation.last_error_code = "DOUYIN_ACCOUNT_REAUTH_REQUIRED"
            operation.last_error_summary = "The Douyin account requires reauthorization."
            raise JobExecutionError(
                "DOUYIN_ACCOUNT_REAUTH_REQUIRED",
                "The Douyin account requires reauthorization before readback.",
                retryable=False,
            )
        token_ref = account.access_token_secret_ref
        open_id = account.external_account_id
        item_id = operation.platform_item_id
    try:
        access_token = _load_douyin_access_token(token_ref)
        found = asyncio.run(
            _douyin_readback(access_token=access_token, open_id=open_id, item_id=item_id)
        )
    except (SecretStoreError, ValueError, DouyinApiError) as exc:
        raise JobExecutionError(
            "DOUYIN_READBACK_FAILED",
            "Douyin readback could not be completed; the read-only check can be retried.",
            retryable=True,
            retry_delay_seconds=60,
        ) from exc
    context.check_control()
    if found is not None:
        _mark_douyin_operation(operation_id, status="published")
        return {
            "status": "published",
            "publish_operation_id": str(operation_id),
            "platform_item_id": item_id,
        }
    if attempt >= DOUYIN_READBACK_MAX_ATTEMPTS:
        _mark_douyin_operation(
            operation_id,
            status="needs_human",
            error_code="DOUYIN_READBACK_NOT_OBSERVED",
            error_summary="The platform item was not visible after repeated readback checks.",
        )
        return {"status": "needs_human", "publish_operation_id": str(operation_id)}
    _schedule_douyin_readback(operation_id, readback_attempt=attempt + 1)
    return {"status": "processing", "publish_operation_id": str(operation_id)}
