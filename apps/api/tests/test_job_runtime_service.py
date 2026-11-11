from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from store_operator.ai_gateway.errors import SideEffectState
from store_operator.jobs import (
    SYSTEM_SCOPE_ID,
    InvalidJobTransition,
    JobIdempotencyConflict,
    LeaseLostError,
    acknowledge_job_cancellation,
    claim_job,
    complete_job,
    create_job,
    fail_job,
    heartbeat_job,
    request_job_cancellation,
    resolve_job,
    retry_failed_job,
)
from store_operator.models import Job, JobAttempt, JobEvent, OutboxEvent, Store, User


def create_actor_and_store(db_session):
    user = User(
        email_normalized="job-runtime@example.test",
        password_hash="test-password-hash",
    )
    store = Store(name="Job Runtime Test Store", timezone="Asia/Tokyo")
    db_session.add_all([user, store])
    db_session.flush()
    return user, store


def create_store_job(db_session, user, store, **overrides):
    values = {
        "job_type": "copy.generate",
        "payload_ref": {"schema_version": 1, "prompt": "Write a short promotion"},
        "idempotency_key": "job-create-1",
        "store_id": store.id,
        "actor_type": "user",
        "actor_user_id": user.id,
    }
    values.update(overrides)
    return create_job(db_session, **values)


def test_create_job_writes_job_outbox_and_event_in_one_transaction(db_session) -> None:
    user, store = create_actor_and_store(db_session)

    job = create_store_job(db_session, user, store)

    assert job.status == "queued"
    assert job.idempotency_scope_type == "store"
    assert job.idempotency_scope_id == store.id
    assert job.store_id == store.id
    assert db_session.scalar(
        select(OutboxEvent).where(OutboxEvent.aggregate_id == job.id)
    ) is not None
    event = db_session.scalar(select(JobEvent).where(JobEvent.job_id == job.id))
    assert event is not None
    assert event.event_type == "job.queued"


def test_job_creation_idempotency_replays_same_job_and_rejects_changed_payload(
    db_session,
) -> None:
    user, store = create_actor_and_store(db_session)
    first = create_store_job(db_session, user, store)
    replay = create_store_job(db_session, user, store)

    assert replay.id == first.id
    assert len(
        db_session.scalars(
            select(OutboxEvent).where(OutboxEvent.aggregate_id == first.id)
        ).all()
    ) == 1

    with pytest.raises(JobIdempotencyConflict):
        create_store_job(
            db_session,
            user,
            store,
            payload_ref={"schema_version": 1, "prompt": "A different request"},
        )


def test_system_job_uses_non_null_system_idempotency_scope(db_session) -> None:
    job = create_job(
        db_session,
        job_type="system.cleanup",
        payload_ref={"schema_version": 1},
        idempotency_key="system-cleanup-1",
        store_id=None,
        actor_type="system",
        actor_user_id=None,
    )

    assert job.store_id is None
    assert job.idempotency_scope_type == "system"
    assert job.idempotency_scope_id == SYSTEM_SCOPE_ID


def test_claim_heartbeat_complete_and_stale_lease_fencing(db_session) -> None:
    user, store = create_actor_and_store(db_session)
    job = create_store_job(db_session, user, store)
    now = datetime.now(UTC)

    claim = claim_job(
        db_session,
        job_id=job.id,
        worker_id="worker-1",
        lease_seconds=90,
        now=now,
    )
    assert claim is not None
    assert claim.job.status == "running"
    assert claim.attempt.attempt_no == 1

    heartbeat_job(
        db_session,
        job_id=job.id,
        lease_token=claim.attempt.lease_token,
        worker_id="worker-1",
        lease_seconds=120,
        progress_current=2,
        progress_total=5,
        now=now + timedelta(seconds=10),
    )
    assert job.progress_current == 2
    assert job.progress_total == 5
    completed = complete_job(
        db_session,
        job_id=job.id,
        lease_token=claim.attempt.lease_token,
        worker_id="worker-1",
        result_ref={"artifact_id": "result-1"},
        now=now + timedelta(seconds=20),
    )
    assert completed.status == "succeeded"
    assert completed.result_ref == {"artifact_id": "result-1"}

    with pytest.raises(LeaseLostError):
        complete_job(
            db_session,
            job_id=job.id,
            lease_token=claim.attempt.lease_token,
            worker_id="worker-1",
            result_ref={"artifact_id": "stale-result"},
            now=now + timedelta(seconds=21),
        )


def test_retry_budget_and_uncertain_side_effect_require_human(db_session) -> None:
    user, store = create_actor_and_store(db_session)
    job = create_store_job(
        db_session,
        user,
        store,
        idempotency_key="retry-job",
        max_attempts=2,
    )
    now = datetime.now(UTC)

    first = claim_job(
        db_session, job_id=job.id, worker_id="worker-1", now=now
    )
    assert first is not None
    waiting = fail_job(
        db_session,
        job_id=job.id,
        lease_token=first.attempt.lease_token,
        worker_id="worker-1",
        error_code="PROVIDER_TIMEOUT",
        error_summary="Temporary provider timeout",
        retryable=True,
        now=now + timedelta(seconds=1),
    )
    assert waiting.status == "retry_wait"
    retry_outbox = db_session.scalars(
        select(OutboxEvent)
        .where(OutboxEvent.aggregate_id == job.id)
        .order_by(OutboxEvent.created_at, OutboxEvent.id)
    ).all()
    assert len(retry_outbox) == 2
    retry_dispatch = next(
        event for event in retry_outbox if event.dedupe_key.endswith(":attempt:2")
    )
    assert retry_dispatch.status == "pending"
    assert retry_dispatch.available_at == waiting.available_at

    second = claim_job(
        db_session,
        job_id=job.id,
        worker_id="worker-2",
        now=now + timedelta(seconds=32),
    )
    assert second is not None
    failed = fail_job(
        db_session,
        job_id=job.id,
        lease_token=second.attempt.lease_token,
        worker_id="worker-2",
        error_code="PROVIDER_TIMEOUT",
        error_summary="Retry budget exhausted",
        retryable=True,
        now=now + timedelta(seconds=33),
    )
    assert failed.status == "failed"

    uncertain = create_store_job(
        db_session,
        user,
        store,
        idempotency_key="uncertain-side-effect-job",
    )
    third = claim_job(
        db_session,
        job_id=uncertain.id,
        worker_id="worker-3",
        now=now + timedelta(seconds=40),
    )
    assert third is not None
    needs_human = fail_job(
        db_session,
        job_id=uncertain.id,
        lease_token=third.attempt.lease_token,
        worker_id="worker-3",
        error_code="PUBLISH_RESULT_UNKNOWN",
        error_summary="The external result could not be confirmed",
        retryable=True,
        side_effect_state=SideEffectState.UNKNOWN,
        now=now + timedelta(seconds=41),
    )
    assert needs_human.status == "needs_human"


def test_running_cancellation_is_a_request_until_worker_acknowledges(db_session) -> None:
    user, store = create_actor_and_store(db_session)
    job = create_store_job(db_session, user, store)
    now = datetime.now(UTC)
    claim = claim_job(db_session, job_id=job.id, worker_id="worker-1", now=now)
    assert claim is not None

    requested = request_job_cancellation(
        db_session,
        job_id=job.id,
        store_id=store.id,
        actor_user_id=user.id,
        now=now + timedelta(seconds=1),
    )
    assert requested.status == "running"
    assert requested.cancel_requested_at is not None

    cancelled = acknowledge_job_cancellation(
        db_session,
        job_id=job.id,
        lease_token=claim.attempt.lease_token,
        worker_id="worker-1",
        now=now + timedelta(seconds=2),
    )
    assert cancelled.status == "cancelled"
    assert cancelled.cancelled_at is not None


def test_queued_cancellation_is_immediate_and_store_scoped(db_session) -> None:
    user, store = create_actor_and_store(db_session)
    job = create_store_job(db_session, user, store, idempotency_key="cancel-queued")
    cancelled = request_job_cancellation(
        db_session,
        job_id=job.id,
        store_id=store.id,
        actor_user_id=user.id,
    )

    assert cancelled.status == "cancelled"
    assert cancelled.finished_at is not None


def test_job_attempt_history_is_preserved_after_retry(db_session) -> None:
    user, store = create_actor_and_store(db_session)
    job = create_store_job(
        db_session, user, store, idempotency_key="attempt-history", max_attempts=2
    )
    now = datetime.now(UTC)
    first = claim_job(db_session, job_id=job.id, worker_id="worker-1", now=now)
    assert first is not None
    fail_job(
        db_session,
        job_id=job.id,
        lease_token=first.attempt.lease_token,
        worker_id="worker-1",
        error_code="TEMPORARY",
        error_summary="Temporary failure",
        retryable=True,
        now=now + timedelta(seconds=1),
    )
    second = claim_job(
        db_session,
        job_id=job.id,
        worker_id="worker-2",
        now=now + timedelta(seconds=32),
    )
    assert second is not None

    attempts = db_session.scalars(
        select(JobAttempt).where(JobAttempt.job_id == job.id).order_by(JobAttempt.attempt_no)
    ).all()
    assert [attempt.attempt_no for attempt in attempts] == [1, 2]
    assert attempts[0].status == "failed"
    assert attempts[1].status == "running"
    assert db_session.get(Job, job.id) is not None


def test_manual_retry_is_idempotent_and_requires_side_effect_confirmation(
    db_session,
) -> None:
    user, store = create_actor_and_store(db_session)
    job = create_store_job(
        db_session, user, store, idempotency_key="manual-retry", max_attempts=1
    )
    now = datetime.now(UTC)
    claim = claim_job(db_session, job_id=job.id, worker_id="worker-1", now=now)
    assert claim is not None
    failed = fail_job(
        db_session,
        job_id=job.id,
        lease_token=claim.attempt.lease_token,
        worker_id="worker-1",
        error_code="TEMPORARY",
        error_summary="Retry budget exhausted",
        retryable=False,
        now=now + timedelta(seconds=1),
    )
    assert failed.status == "failed"

    with pytest.raises(InvalidJobTransition):
        retry_failed_job(
            db_session,
            job_id=job.id,
            store_id=store.id,
            actor_user_id=user.id,
            idempotency_key="retry-key-1",
            reason="Need operator confirmation",
            side_effects_confirmed_absent=False,
        )

    retried = retry_failed_job(
        db_session,
        job_id=job.id,
        store_id=store.id,
        actor_user_id=user.id,
        idempotency_key="retry-key-1",
        reason="Provider confirms no external side effect",
        side_effects_confirmed_absent=True,
        now=now + timedelta(seconds=2),
    )
    assert retried.status == "queued"
    assert retried.max_attempts == 2
    outbox = db_session.scalars(
        select(OutboxEvent).where(OutboxEvent.aggregate_id == job.id)
    ).all()
    assert len(outbox) == 2

    replay = retry_failed_job(
        db_session,
        job_id=job.id,
        store_id=store.id,
        actor_user_id=user.id,
        idempotency_key="retry-key-1",
        reason="Provider confirms no external side effect",
        side_effects_confirmed_absent=True,
        now=now + timedelta(seconds=3),
    )
    assert replay.id == job.id
    assert len(
        db_session.scalars(
            select(OutboxEvent).where(OutboxEvent.aggregate_id == job.id)
        ).all()
    ) == 2

    with pytest.raises(JobIdempotencyConflict):
        retry_failed_job(
            db_session,
            job_id=job.id,
            store_id=store.id,
            actor_user_id=user.id,
            idempotency_key="retry-key-1",
            reason="A different decision",
            side_effects_confirmed_absent=True,
        )


def test_needs_human_resolution_is_audited_and_idempotent(db_session) -> None:
    user, store = create_actor_and_store(db_session)
    job = create_store_job(
        db_session, user, store, idempotency_key="manual-resolution"
    )
    now = datetime.now(UTC)
    claim = claim_job(db_session, job_id=job.id, worker_id="worker-1", now=now)
    assert claim is not None
    needs_human = fail_job(
        db_session,
        job_id=job.id,
        lease_token=claim.attempt.lease_token,
        worker_id="worker-1",
        error_code="SIDE_EFFECT_UNKNOWN",
        error_summary="Provider result is uncertain",
        retryable=True,
        side_effect_state=SideEffectState.UNKNOWN,
        now=now + timedelta(seconds=1),
    )
    assert needs_human.status == "needs_human"

    resolved = resolve_job(
        db_session,
        job_id=job.id,
        store_id=store.id,
        actor_user_id=user.id,
        idempotency_key="resolve-key-1",
        resolution="fail",
        reason="Operator checked provider console; operation did not complete",
        now=now + timedelta(seconds=2),
    )
    assert resolved.status == "failed"
    replay = resolve_job(
        db_session,
        job_id=job.id,
        store_id=store.id,
        actor_user_id=user.id,
        idempotency_key="resolve-key-1",
        resolution="fail",
        reason="Operator checked provider console; operation did not complete",
        now=now + timedelta(seconds=3),
    )
    assert replay.status == "failed"
    event = db_session.scalar(
        select(JobEvent).where(
            JobEvent.job_id == job.id,
            JobEvent.event_type == "job.manual_resolution_failed",
        )
    )
    assert event is not None
    assert event.actor_id == user.id
    assert event.data_json["reason"].startswith("Operator checked")


def test_expired_worker_lease_fences_heartbeat_and_completion(db_session) -> None:
    user, store = create_actor_and_store(db_session)
    job = create_store_job(
        db_session, user, store, idempotency_key="expired-lease", timeout_seconds=30
    )
    now = datetime.now(UTC)
    claim = claim_job(
        db_session,
        job_id=job.id,
        worker_id="worker-stale",
        lease_seconds=5,
        now=now,
    )
    assert claim is not None
    expired_at = now + timedelta(seconds=6)

    with pytest.raises(LeaseLostError):
        heartbeat_job(
            db_session,
            job_id=job.id,
            lease_token=claim.attempt.lease_token,
            worker_id="worker-stale",
            now=expired_at,
        )
    with pytest.raises(LeaseLostError):
        complete_job(
            db_session,
            job_id=job.id,
            lease_token=claim.attempt.lease_token,
            worker_id="worker-stale",
            result_ref={"artifact_id": "late-result"},
            now=expired_at,
        )


def test_store_concurrency_limit_defers_without_consuming_attempt_and_requeues(
    db_session,
) -> None:
    user, store = create_actor_and_store(db_session)
    first = create_store_job(
        db_session, user, store, idempotency_key="store-capacity-first"
    )
    second = create_store_job(
        db_session, user, store, idempotency_key="store-capacity-second"
    )
    now = datetime.now(UTC)

    first_claim = claim_job(
        db_session,
        job_id=first.id,
        worker_id="worker-1",
        max_running_per_store=1,
        now=now,
    )
    assert first_claim is not None

    deferred = claim_job(
        db_session,
        job_id=second.id,
        worker_id="worker-2",
        max_running_per_store=1,
        concurrency_defer_seconds=15,
        now=now + timedelta(seconds=1),
    )
    assert deferred is None
    db_session.refresh(second)
    assert second.status == "queued"
    assert second.attempt_count == 0
    assert second.available_at == now + timedelta(seconds=16)
    assert db_session.scalars(
        select(JobAttempt).where(JobAttempt.job_id == second.id)
    ).all() == []

    dispatch = db_session.scalar(
        select(OutboxEvent).where(
            OutboxEvent.aggregate_id == second.id,
            OutboxEvent.dedupe_key.like("job.dispatch.defer:%"),
        )
    )
    assert dispatch is not None
    assert dispatch.status == "pending"
    assert dispatch.available_at == second.available_at

    deferred_event = db_session.scalar(
        select(JobEvent).where(
            JobEvent.job_id == second.id,
            JobEvent.event_type == "job.deferred_for_concurrency",
        )
    )
    assert deferred_event is not None
    assert deferred_event.data_json["running_limit"] == 1

    complete_job(
        db_session,
        job_id=first.id,
        lease_token=first_claim.attempt.lease_token,
        worker_id="worker-1",
        result_ref={"schema_version": 1},
        now=now + timedelta(seconds=2),
    )
    second_claim = claim_job(
        db_session,
        job_id=second.id,
        worker_id="worker-2",
        max_running_per_store=1,
        now=now + timedelta(seconds=16),
    )
    assert second_claim is not None
    assert second_claim.job.status == "running"
    assert second_claim.attempt.attempt_no == 1
