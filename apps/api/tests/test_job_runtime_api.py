from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from store_operator.ai_gateway.errors import SideEffectState
from store_operator.auth.security import hash_password
from store_operator.jobs import claim_job, create_job, fail_job
from store_operator.jobs.service import (
    JobIdempotencyConflict,
    LeaseLostError,
    complete_job,
    recover_expired_jobs,
)
from store_operator.models import (
    AIInvocation,
    AIUsageRecord,
    Job,
    Store,
    StoreMembership,
    User,
)
from store_operator.models.job_runtime import OutboxEvent

ORIGIN = {"Origin": "http://localhost:5173"}


class FakeRedis:
    def __init__(self):
        self.values: dict[str, int] = {}

    def eval(self, script, numkeys, *args):
        keys = args[:numkeys]
        counts = []
        for key in keys:
            self.values[key] = self.values.get(key, 0) + 1
            counts.append(self.values[key])
        return counts

    def delete(self, *keys):
        for key in keys:
            self.values.pop(key, None)
        return len(keys)


def create_user(db: Session) -> User:
    user = User(
        id=uuid4(),
        email_normalized="jobs@example.com",
        password_hash=hash_password("test-password-123"),
        status="active",
    )
    db.add(user)
    db.flush()
    return user


def create_store(db: Session, user: User, name: str) -> Store:
    store = Store(
        id=uuid4(),
        name=name,
        timezone="Asia/Tokyo",
        status="active",
    )
    db.add(store)
    db.flush()
    db.add(
        StoreMembership(
            id=uuid4(),
            store_id=store.id,
            user_id=user.id,
            role="owner",
            status="active",
            joined_at=datetime.now(UTC),
        )
    )
    db.flush()
    return store


def login(identity_client, monkeypatch) -> str:
    import store_operator.auth.router as auth_router

    monkeypatch.setattr(auth_router, "redis_client", FakeRedis())
    response = identity_client.post(
        "/api/v1/auth/login",
        json={"email": "jobs@example.com", "password": "test-password-123"},
        headers=ORIGIN,
    )
    assert response.status_code == 200, response.text
    return response.json()["csrf_token"]


def create_job_for_store(db: Session, user: User, store: Store, key: str) -> Job:
    return create_job(
        db,
        job_type="copy.generate",
        payload_ref={"schema_version": 1, "secret_prompt": "must not be returned"},
        idempotency_key=key,
        store_id=store.id,
        actor_type="user",
        actor_user_id=user.id,
    )


def test_job_api_is_store_scoped_and_does_not_return_payload_or_lease_data(
    identity_client, db_session, monkeypatch
):
    user = create_user(db_session)
    store_a = create_store(db_session, user, "Jobs A")
    store_b = create_store(db_session, user, "Jobs B")
    job = create_job_for_store(db_session, user, store_a, "job-api-read-1")
    login(identity_client, monkeypatch)

    response = identity_client.get(
        f"/api/v1/jobs/{job.id}",
        headers={"X-Store-ID": str(store_a.id)},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == str(job.id)
    assert body["status"] == "queued"
    assert "payload_ref" not in body
    assert "result_ref" not in body
    assert "lease_token" not in body
    assert "secret_prompt" not in response.text

    hidden = identity_client.get(
        f"/api/v1/jobs/{job.id}",
        headers={"X-Store-ID": str(store_b.id)},
    )
    assert hidden.status_code == 404
    assert hidden.json()["error"]["code"] == "JOB_NOT_FOUND"


def test_job_cancel_and_manual_retry_api_require_csrf_and_idempotency(
    identity_client, db_session, monkeypatch
):
    user = create_user(db_session)
    store = create_store(db_session, user, "Jobs Mutations")
    store_b = create_store(db_session, user, "Other Jobs Mutations")
    csrf = login(identity_client, monkeypatch)
    headers = {
        **ORIGIN,
        "X-CSRF-Token": csrf,
        "X-Store-ID": str(store.id),
        "Idempotency-Key": "cancel-job-key-1",
    }

    headers_b = {**headers, "X-Store-ID": str(store_b.id)}
    queued = create_job_for_store(db_session, user, store, "queued-cancel-1")
    cancelled = identity_client.post(
        f"/api/v1/jobs/{queued.id}/cancel",
        headers=headers,
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"

    hidden_cancel = identity_client.post(
        f"/api/v1/jobs/{queued.id}/cancel",
        headers={**headers_b, "Idempotency-Key": "cross-store-job-cancel"},
    )
    assert hidden_cancel.status_code == 404
    visible_after_cross_store_attempt = identity_client.get(
        f"/api/v1/jobs/{queued.id}",
        headers={"X-Store-ID": str(store.id)},
    )
    assert visible_after_cross_store_attempt.status_code == 200
    assert visible_after_cross_store_attempt.json()["status"] == "cancelled"

    retry = create_job_for_store(
        db_session, user, store, "failed-retry-api-1"
    )
    now = datetime.now(UTC)
    claim = claim_job(
        db_session,
        job_id=retry.id,
        worker_id="api-test-worker",
        now=now,
    )
    assert claim is not None
    fail_job(
        db_session,
        job_id=retry.id,
        lease_token=claim.attempt.lease_token,
        worker_id="api-test-worker",
        error_code="TEMPORARY",
        error_summary="Execution failed",
        retryable=False,
        now=now,
    )
    db_session.flush()

    retry_headers = {
        **headers,
        "Idempotency-Key": "manual-retry-api-1",
    }
    retried = identity_client.post(
        f"/api/v1/jobs/{retry.id}/retry",
        headers=retry_headers,
        json={
            "reason": "Provider confirmed no side effect",
            "side_effects_confirmed_absent": True,
        },
    )
    assert retried.status_code == 200, retried.text
    assert retried.json()["status"] == "queued"

    replay = identity_client.post(
        f"/api/v1/jobs/{retry.id}/retry",
        headers=retry_headers,
        json={
            "reason": "Provider confirmed no side effect",
            "side_effects_confirmed_absent": True,
        },
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["status"] == "queued"

    hidden_retry = identity_client.post(
        f"/api/v1/jobs/{retry.id}/retry",
        headers={**headers_b, "Idempotency-Key": "cross-store-job-retry"},
        json={
            "reason": "Provider confirmed no side effect",
            "side_effects_confirmed_absent": True,
        },
    )
    assert hidden_retry.status_code == 404

    missing_csrf = identity_client.post(
        f"/api/v1/jobs/{retry.id}/retry",
        headers={"X-Store-ID": str(store.id), "Idempotency-Key": "no-csrf"},
        json={
            "reason": "No side effect",
            "side_effects_confirmed_absent": True,
        },
    )
    assert missing_csrf.status_code == 403


def test_job_resolve_and_ai_invocation_are_store_scoped(
    identity_client, db_session, monkeypatch
):
    user = create_user(db_session)
    store_a = create_store(db_session, user, "Jobs Resolve A")
    store_b = create_store(db_session, user, "Jobs Resolve B")
    csrf = login(identity_client, monkeypatch)
    headers = {
        **ORIGIN,
        "X-CSRF-Token": csrf,
        "X-Store-ID": str(store_a.id),
        "Idempotency-Key": "resolve-job-key-1",
    }

    job = create_job_for_store(db_session, user, store_a, "resolve-job-1")
    now = datetime.now(UTC)
    claim = claim_job(
        db_session,
        job_id=job.id,
        worker_id="resolve-test-worker",
        now=now,
    )
    assert claim is not None
    fail_job(
        db_session,
        job_id=job.id,
        lease_token=claim.attempt.lease_token,
        worker_id="resolve-test-worker",
        error_code="SIDE_EFFECT_UNKNOWN",
        error_summary="Provider response was lost",
        retryable=True,
        side_effect_state=SideEffectState.UNKNOWN,
        now=now,
    )
    db_session.flush()

    resolved = identity_client.post(
        f"/api/v1/jobs/{job.id}/resolve",
        headers=headers,
        json={
            "resolution": "fail",
            "reason": "Operator reconciled provider status; operation did not complete",
        },
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["status"] == "failed"
    hidden_resolve = identity_client.post(
        f"/api/v1/jobs/{job.id}/resolve",
        headers={
            **headers,
            "X-Store-ID": str(store_b.id),
            "Idempotency-Key": "cross-store-job-resolve",
        },
        json={
            "resolution": "fail",
            "reason": "Store B must not resolve Store A job",
        },
    )
    assert hidden_resolve.status_code == 404

    invocation = AIInvocation(
        id=uuid4(),
        store_id=store_a.id,
        provider_key="test-provider",
        model_key="test-model",
        capability="text_generate",
        status="succeeded",
        prompt_version_id=None,
    )
    db_session.add(invocation)
    db_session.flush()
    db_session.add(
        AIUsageRecord(
            invocation_id=invocation.id,
            input_tokens=12,
            output_tokens=34,
            cost_amount=Decimal("0.001200"),
            currency="USD",
            metering_source="provider_reported",
        )
    )
    db_session.flush()

    usage = identity_client.get(
        f"/api/v1/ai/invocations/{invocation.id}",
        headers={"X-Store-ID": str(store_a.id)},
    )
    assert usage.status_code == 200, usage.text
    assert usage.json()["provider_key"] == "test-provider"
    assert usage.json()["usage"]["input_tokens"] == 12
    assert "secret_prompt" not in usage.text

    hidden = identity_client.get(
        f"/api/v1/ai/invocations/{invocation.id}",
        headers={"X-Store-ID": str(store_b.id)},
    )
    assert hidden.status_code == 404
    assert hidden.json()["error"]["code"] == "AI_INVOCATION_NOT_FOUND"



def test_job_creation_idempotency_creates_only_one_outbox_event(
    db_session: Session,
) -> None:
    user = create_user(db_session)
    store = create_store(db_session, user, "Idempotent Job Store")

    first = create_job_for_store(db_session, user, store, "same-job-request")
    replay = create_job_for_store(db_session, user, store, "same-job-request")

    assert replay.id == first.id
    events = (
        db_session.query(OutboxEvent)
        .filter(OutboxEvent.aggregate_id == first.id)
        .all()
    )
    assert len(events) == 1
    assert events[0].event_type == "job.dispatch_requested"

    with pytest.raises(JobIdempotencyConflict):
        create_job(
            db_session,
            job_type="copy.generate",
            payload_ref={"schema_version": 1, "different": True},
            idempotency_key="same-job-request",
            store_id=store.id,
            actor_type="user",
            actor_user_id=user.id,
        )


def test_revoked_store_membership_cancels_job_before_worker_claim(
    db_session: Session,
) -> None:
    user = create_user(db_session)
    store = create_store(db_session, user, "Revoked Membership Store")
    job = create_job_for_store(db_session, user, store, "membership-revoked-job")
    membership = (
        db_session.query(StoreMembership)
        .filter(
            StoreMembership.store_id == store.id,
            StoreMembership.user_id == user.id,
        )
        .one()
    )
    membership.status = "removed"
    db_session.flush()

    claim = claim_job(
        db_session,
        job_id=job.id,
        worker_id="revoked-membership-worker",
        now=datetime.now(UTC),
    )

    assert claim is None
    db_session.refresh(job)
    assert job.status == "cancelled"
    assert job.error_code == "ACTOR_MEMBERSHIP_REVOKED"
    assert job.lease_token is None


def test_expired_worker_lease_is_fenced_and_requires_reconciliation(
    db_session: Session,
) -> None:
    user = create_user(db_session)
    store = create_store(db_session, user, "Expired Lease Store")
    job = create_job_for_store(db_session, user, store, "expired-lease-job")
    claimed_at = datetime.now(UTC)
    claim = claim_job(
        db_session,
        job_id=job.id,
        worker_id="worker-before-restart",
        lease_seconds=1,
        now=claimed_at,
    )
    assert claim is not None

    recovered_at = claimed_at + timedelta(seconds=2)
    assert recover_expired_jobs(db_session, now=recovered_at) == 1
    db_session.refresh(job)
    db_session.refresh(claim.attempt)

    assert job.status == "needs_human"
    assert job.error_code == "WORKER_LEASE_EXPIRED"
    assert job.lease_token is None
    assert claim.attempt.status == "lease_expired"

    with pytest.raises(LeaseLostError):
        complete_job(
            db_session,
            job_id=job.id,
            lease_token=claim.attempt.lease_token,
            worker_id="worker-before-restart",
            result_ref={"should_not_commit": True},
            now=recovered_at + timedelta(seconds=1),
        )
