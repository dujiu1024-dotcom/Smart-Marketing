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
from sqlalchemy import create_engine, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from store_operator.channels.douyin import (
    DouyinApiError,
    DouyinAppCredentials,
    DouyinOAuthClient,
)
from store_operator.channels.secret_store import AwsSecretsManagerStore, SecretStoreError
from store_operator.config import settings
from store_operator.object_storage import (
    ObjectStorageNotConfigured,
    download_object_bytes,
)
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
    Artifact,
    ArtifactVersion,
    ChannelContent,
    ChannelContentArtifactRef,
    ChannelAccount,
    Job,
    JobAttempt,
    JobEvent,
    OutboxEvent,
    PublishConfirmation,
    PublishOperation,
    PublishPackage,
    PublishPackageItem,
    MediaAsset,
    QualityReport,
    ReviewRecord,
)

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


@register_job_handler("douyin.publish_image_text")
def execute_douyin_image_text_publish(
    context: JobExecutionContext,
    payload_ref: dict[str, object],
) -> dict[str, object]:
    """Publish a frozen image-text package item; never retry an uncertain create call."""
    context.check_control()
    if context.store_id is None or payload_ref.get("schema_version") != 1:
        raise JobExecutionError(
            "DOUYIN_PUBLISH_PAYLOAD_INVALID",
            "Douyin publish job payload is invalid.",
            retryable=False,
        )
    operation_value = payload_ref.get("publish_operation_id")
    if not isinstance(operation_value, str):
        raise JobExecutionError(
            "DOUYIN_PUBLISH_PAYLOAD_INVALID",
            "Douyin publish job payload is invalid.",
            retryable=False,
        )
    try:
        operation_id = UUID(operation_value)
    except ValueError as exc:
        raise JobExecutionError(
            "DOUYIN_PUBLISH_PAYLOAD_INVALID",
            "Douyin publish job payload is invalid.",
            retryable=False,
        ) from exc

    with SessionLocal.begin() as db:
        operation = db.scalar(
            select(PublishOperation)
            .where(
                PublishOperation.id == operation_id,
                PublishOperation.store_id == context.store_id,
            )
            .with_for_update()
        )
        if operation is None:
            raise JobExecutionError(
                "DOUYIN_PUBLISH_OPERATION_NOT_FOUND",
                "The publish operation no longer exists.",
                retryable=False,
            )
        if operation.status in {"published", "cancelled", "failed"}:
            return {
                "status": operation.status,
                "publish_operation_id": str(operation.id),
                "platform_item_id": operation.platform_item_id or "",
            }
        if operation.platform_item_id is None and operation.status in {"submitting", "needs_human"}:
            operation.status = "needs_human"
            operation.last_error_code = "DOUYIN_CREATE_RESULT_UNKNOWN"
            operation.last_error_summary = (
                "The platform create result is unknown; automatic duplicate submission is blocked."
            )
            raise JobExecutionError(
                "DOUYIN_CREATE_RESULT_UNKNOWN",
                "The platform create result is unknown; manual reconciliation is required.",
                retryable=False,
                side_effect_state=SideEffectState.UNKNOWN,
            )

        package = db.scalar(
            select(PublishPackage).where(
                PublishPackage.id == operation.publish_package_id,
                PublishPackage.store_id == context.store_id,
            )
        )
        package_item = db.scalar(
            select(PublishPackageItem).where(
                PublishPackageItem.id == operation.publish_package_item_id,
                PublishPackageItem.store_id == context.store_id,
                PublishPackageItem.publish_package_id == operation.publish_package_id,
            )
        )
        confirmation = db.scalar(
            select(PublishConfirmation).where(
                PublishConfirmation.id == operation.publish_confirmation_id,
                PublishConfirmation.store_id == context.store_id,
                PublishConfirmation.publish_package_id == operation.publish_package_id,
                PublishConfirmation.package_fingerprint == operation.confirmed_package_fingerprint,
            )
        )
        account = db.scalar(
            select(ChannelAccount).where(
                ChannelAccount.id == operation.channel_account_id,
                ChannelAccount.store_id == context.store_id,
                ChannelAccount.provider == "douyin",
                ChannelAccount.status == "active",
            )
        )
        if (
            package is None
            or package_item is None
            or confirmation is None
            or account is None
            or package.package_fingerprint != operation.confirmed_package_fingerprint
            or package_item.delivery_mode != "official_api"
            or package_item.channel_key != "douyin"
            or package_item.channel_account_id != account.id
        ):
            operation.status = "needs_human"
            operation.last_error_code = "DOUYIN_PUBLISH_PREREQUISITE_CHANGED"
            operation.last_error_summary = "A frozen publish prerequisite changed or is unavailable."
            raise JobExecutionError(
                "DOUYIN_PUBLISH_PREREQUISITE_CHANGED",
                "A frozen publish prerequisite changed or is unavailable.",
                retryable=False,
            )

        channel_content = db.scalar(
            select(ChannelContent).where(
                ChannelContent.id == package_item.channel_content_id,
                ChannelContent.store_id == context.store_id,
                ChannelContent.status == "ready",
            )
        )
        copy_version = (
            db.scalar(
                select(ArtifactVersion).where(
                    ArtifactVersion.id == channel_content.copy_version_id,
                    ArtifactVersion.store_id == context.store_id,
                )
            )
            if channel_content is not None
            else None
        )
        if channel_content is None or copy_version is None or copy_version.content_json is None:
            operation.status = "failed"
            operation.last_error_code = "DOUYIN_COPY_CONTENT_MISSING"
            operation.last_error_summary = "The frozen Douyin copy is unavailable."
            raise JobExecutionError(
                "DOUYIN_COPY_CONTENT_MISSING",
                "The frozen Douyin copy is unavailable.",
                retryable=False,
            )

        copy_data = copy_version.content_json
        title = copy_data.get("title")
        body = copy_data.get("body")
        post_text = "\n\n".join(
            part.strip() for part in (title, body) if isinstance(part, str) and part.strip()
        )
        if not post_text or len(post_text) > 1000:
            operation.status = "failed"
            operation.last_error_code = "DOUYIN_COPY_TEXT_INVALID"
            operation.last_error_summary = "The frozen post text is empty or exceeds the platform limit."
            raise JobExecutionError(
                "DOUYIN_COPY_TEXT_INVALID",
                "The frozen post text is empty or exceeds the platform limit.",
                retryable=False,
            )

        image_refs = db.scalars(
            select(ChannelContentArtifactRef)
            .where(
                ChannelContentArtifactRef.store_id == context.store_id,
                ChannelContentArtifactRef.channel_content_id == channel_content.id,
            )
            .order_by(ChannelContentArtifactRef.position)
        ).all()
        if not 1 <= len(image_refs) <= 30:
            operation.status = "failed"
            operation.last_error_code = "DOUYIN_IMAGE_COUNT_INVALID"
            operation.last_error_summary = "Douyin image-text posts require between 1 and 30 images."
            raise JobExecutionError(
                "DOUYIN_IMAGE_COUNT_INVALID",
                "Douyin image-text posts require between 1 and 30 images.",
                retryable=False,
            )

        media_items: list[tuple[str, str, str]] = []
        for image_ref in image_refs:
            image_version = db.scalar(
                select(ArtifactVersion).where(
                    ArtifactVersion.id == image_ref.artifact_version_id,
                    ArtifactVersion.store_id == context.store_id,
                )
            )
            if image_version is None or not image_version.content_ref:
                operation.status = "failed"
                operation.last_error_code = "DOUYIN_IMAGE_BINARY_MISSING"
                operation.last_error_summary = "A frozen image has no private object reference."
                raise JobExecutionError(
                    "DOUYIN_IMAGE_BINARY_MISSING",
                    "A frozen image has no private object reference.",
                    retryable=False,
                )
            media_asset = db.scalar(
                select(MediaAsset).where(
                    MediaAsset.store_id == context.store_id,
                    MediaAsset.object_key == image_version.content_ref,
                    MediaAsset.status == "ready",
                    MediaAsset.usage_rights_status == "confirmed_allowed",
                )
            )
            if media_asset is None or media_asset.mime_type not in {
                "image/jpeg",
                "image/png",
                "image/webp",
            } or media_asset.byte_size > 20 * 1024 * 1024:
                operation.status = "failed"
                operation.last_error_code = "DOUYIN_IMAGE_NOT_ELIGIBLE"
                operation.last_error_summary = (
                    "A frozen image is not ready, lacks confirmed usage rights, or exceeds the image limit."
                )
                raise JobExecutionError(
                    "DOUYIN_IMAGE_NOT_ELIGIBLE",
                    "A frozen image is not eligible for Douyin image-text publishing.",
                    retryable=False,
                )
            media_items.append(
                (
                    media_asset.object_key,
                    media_asset.original_filename_sanitized or f"image-{image_ref.position}.jpg",
                    media_asset.mime_type,
                )
            )

        operation.attempt_count += 1
        if operation.platform_item_id is None:
            operation.status = "uploading"
        secret_ref = account.access_token_secret_ref
        refresh_secret_ref = account.refresh_token_secret_ref
        open_id = account.external_account_id
        access_expires_at = account.access_token_expires_at
        operation_id_value = str(operation.id)
        store_id_value = str(context.store_id)
        db.flush()

    if not (
        settings.douyin_client_key
        and settings.douyin_client_secret
        and settings.channel_secret_store_region
    ):
        raise JobExecutionError(
            "DOUYIN_CHANNEL_NOT_CONFIGURED",
            "Douyin publishing credentials or secure credential storage are not configured.",
            retryable=False,
        )

    secret_store = AwsSecretsManagerStore(region_name=settings.channel_secret_store_region)
    try:
        secrets = secret_store.get_json(secret_ref)
    except SecretStoreError as exc:
        raise JobExecutionError(
            "DOUYIN_SECRET_UNAVAILABLE",
            "Douyin credentials could not be retrieved from secure storage.",
            retryable=False,
        ) from exc
    access_token = secrets.get("access_token")
    refresh_token = secrets.get("refresh_token")
    if not isinstance(access_token, str) or not access_token:
        raise JobExecutionError(
            "DOUYIN_SECRET_INVALID",
            "Douyin access credentials are invalid.",
            retryable=False,
        )

    credentials = DouyinAppCredentials(
        client_key=settings.douyin_client_key,
        client_secret=settings.douyin_client_secret,
    )
    client = DouyinOAuthClient(credentials)
    try:
        if access_expires_at <= datetime.now(UTC) + timedelta(seconds=90):
            if not isinstance(refresh_token, str) or not refresh_token:
                raise JobExecutionError(
                    "DOUYIN_REAUTH_REQUIRED",
                    "Douyin authorization has expired; reconnect the account.",
                    retryable=False,
                )
            token_set = await_refresh = None
            try:
                token_set = asyncio.run(client.refresh_access_token(refresh_token))
            except DouyinApiError as exc:
                raise JobExecutionError(
                    "DOUYIN_REAUTH_REQUIRED",
                    "Douyin authorization could not be refreshed; reconnect the account.",
                    retryable=False,
                ) from exc
            if token_set.open_id != open_id or not {
                "user_info",
                "video.create",
                "video.list",
            }.issubset(token_set.scope):
                raise JobExecutionError(
                    "DOUYIN_REAUTH_REQUIRED",
                    "Refreshed Douyin authorization does not match the connected account.",
                    retryable=False,
                )
            digest = hashlib.sha256(open_id.encode("utf-8")).hexdigest()
            new_ref = secret_store.put_json(
                f"{settings.channel_secret_store_prefix}/{store_id_value}/douyin/{digest}",
                {
                    "access_token": token_set.access_token,
                    "refresh_token": token_set.refresh_token,
                },
            )
            with SessionLocal.begin() as db:
                current_account = db.scalar(
                    select(ChannelAccount)
                    .where(
                        ChannelAccount.id == UUID(operation_value if False else str(operation_id)),
                    )
                )
            access_token = token_set.access_token

        if operation.platform_item_id is None:
            uploaded_ids: list[str] = []
            for index, (object_key, filename, mime_type) in enumerate(media_items):
                context.check_control()
                image_bytes = download_object_bytes(
                    object_key=object_key,
                    max_bytes=20 * 1024 * 1024,
                )
                uploaded = asyncio.run(
                    client.upload_image(
                        access_token=access_token,
                        filename=filename,
                        content=image_bytes,
                        content_type=mime_type,
                    )
                )
                uploaded_ids.append(uploaded["image_id"])
                context.update_progress(current=index + 1, total=len(media_items))

            with SessionLocal.begin() as db:
                current = db.scalar(
                    select(PublishOperation)
                    .where(
                        PublishOperation.id == UUID(operation_id_value),
                        PublishOperation.store_id == context.store_id,
                    )
                    .with_for_update()
                )
                if current is None or current.platform_item_id is not None:
                    raise JobExecutionError(
                        "DOUYIN_PUBLISH_OPERATION_CHANGED",
                        "The publish operation changed before platform submission.",
                        retryable=False,
                    )
                current.status = "submitting"

            try:
                receipt = asyncio.run(
                    client.publish_images(
                        access_token=access_token,
                        open_id=open_id,
                        image_ids=uploaded_ids,
                        text=post_text,
                        merchant_confirmed=True,
                    )
                )
            except DouyinApiError as exc:
                with SessionLocal.begin() as db:
                    current = db.scalar(
                        select(PublishOperation)
                        .where(
                            PublishOperation.id == UUID(operation_id_value),
                            PublishOperation.store_id == context.store_id,
                        )
                        .with_for_update()
                    )
                    if current is not None:
                        current.status = "needs_human"
                        current.last_error_code = "DOUYIN_CREATE_RESULT_UNKNOWN"
                        current.last_error_summary = (
                            "The platform create response was not confirmed; manual reconciliation is required."
                        )
                raise JobExecutionError(
                    "DOUYIN_CREATE_RESULT_UNKNOWN",
                    "The platform create response was not confirmed; manual reconciliation is required.",
                    retryable=False,
                    side_effect_state=SideEffectState.UNKNOWN,
                ) from exc

            with SessionLocal.begin() as db:
                current = db.scalar(
                    select(PublishOperation)
                    .where(
                        PublishOperation.id == UUID(operation_id_value),
                        PublishOperation.store_id == context.store_id,
                    )
                    .with_for_update()
                )
                if current is None:
                    raise JobExecutionError(
                        "DOUYIN_PUBLISH_OPERATION_MISSING",
                        "The publish operation disappeared after platform submission.",
                        retryable=False,
                        side_effect_state=SideEffectState.UNKNOWN,
                    )
                current.platform_item_id = receipt.item_id
                current.status = "processing"
                current.submitted_at = datetime.now(UTC)
                current.last_error_code = None
                current.last_error_summary = None

        else:
            receipt = None

        context.check_control()
        with SessionLocal() as db:
            current = db.scalar(
                select(PublishOperation).where(
                    PublishOperation.id == UUID(operation_id_value),
                    PublishOperation.store_id == context.store_id,
                )
            )
            item_id = current.platform_item_id if current is not None else None
        if not item_id:
            raise JobExecutionError(
                "DOUYIN_PLATFORM_ITEM_ID_MISSING",
                "The platform item identifier is not available for readback.",
                retryable=False,
                side_effect_state=SideEffectState.UNKNOWN,
            )
        try:
            readback = asyncio.run(
                client.verify_published_item(
                    access_token=access_token,
                    open_id=open_id,
                    item_id=item_id,
                )
            )
        except DouyinApiError as exc:
            raise JobExecutionError(
                "DOUYIN_READBACK_FAILED",
                "Douyin accepted the create request, but readback is temporarily unavailable.",
                retryable=True,
                side_effect_state=SideEffectState.KNOWN,
                retry_delay_seconds=30,
            ) from exc
        if readback is None:
            with SessionLocal.begin() as db:
                current = db.scalar(
                    select(PublishOperation)
                    .where(
                        PublishOperation.id == UUID(operation_id_value),
                        PublishOperation.store_id == context.store_id,
                    )
                    .with_for_update()
                )
                if current is not None:
                    current.status = "processing"
                    current.last_readback_at = datetime.now(UTC)
                    current.next_attempt_at = datetime.now(UTC) + timedelta(seconds=30)
            raise JobExecutionError(
                "DOUYIN_READBACK_PENDING",
                "Douyin has accepted the post; its item is not yet visible in account readback.",
                retryable=True,
                side_effect_state=SideEffectState.KNOWN,
                retry_delay_seconds=30,
            )
        with SessionLocal.begin() as db:
            current = db.scalar(
                select(PublishOperation)
                .where(
                    PublishOperation.id == UUID(operation_id_value),
                    PublishOperation.store_id == context.store_id,
                )
                .with_for_update()
            )
            if current is not None:
                current.status = "processing"
                current.last_readback_at = datetime.now(UTC)
                current.next_attempt_at = None
        return {
            "status": "processing",
            "publish_operation_id": operation_id_value,
            "platform_item_id": item_id,
            "readback_verified": True,
            "platform_review_state": "pending_or_not_public",
        }
    finally:
        asyncio.run(client.aclose())
