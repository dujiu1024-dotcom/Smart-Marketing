from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select

from store_operator.ai_gateway.invocations import (
    AIInvocationTransitionError,
    cancel_ai_invocation,
    complete_ai_invocation,
    fail_ai_invocation,
    start_ai_invocation,
)
from store_operator.models import AIInvocation, AIUsageRecord


def start_invocation(db_session, **overrides) -> AIInvocation:
    values = {
        "store_id": None,
        "job_id": None,
        "attempt_id": None,
        "provider_key": "provider-test",
        "model_key": "model-test",
        "capability": "text_generate",
        "request_fingerprint": "a" * 64,
        "prompt_version_id": None,
        "parameter_snapshot": {
            "temperature": 0.4,
            "max_output_tokens": 512,
            "prompt": "never persist raw prompt",
        },
    }
    values.update(overrides)
    return start_ai_invocation(db_session, **values)


def test_ai_invocation_start_filters_sensitive_parameters_and_records_usage(
    db_session,
) -> None:
    invocation = start_invocation(db_session)

    assert invocation.status == "running"
    assert invocation.request_fingerprint == "a" * 64
    assert invocation.parameter_snapshot_json == {
        "temperature": 0.4,
        "max_output_tokens": 512,
    }
    assert "prompt" not in invocation.parameter_snapshot_json

    now = datetime.now(UTC)
    completed = complete_ai_invocation(
        db_session,
        invocation_id=invocation.id,
        input_tokens=100,
        output_tokens=50,
        cost_amount=Decimal("0.001250"),
        currency="USD",
        metering_source="provider_reported",
        provider_request_id="provider-request-1",
        now=now,
    )
    assert completed.status == "succeeded"
    assert completed.finished_at == now
    assert completed.provider_request_id == "provider-request-1"

    usage = db_session.get(AIUsageRecord, invocation.id)
    assert usage is not None
    assert usage.input_tokens == 100
    assert usage.output_tokens == 50
    assert usage.cost_amount == Decimal("0.001250")
    assert usage.currency == "USD"

    replay = complete_ai_invocation(
        db_session,
        invocation_id=invocation.id,
        input_tokens=100,
        output_tokens=50,
        cost_amount=Decimal("0.001250"),
        currency="USD",
        metering_source="provider_reported",
        provider_request_id="provider-request-1",
        now=now,
    )
    assert replay.id == invocation.id
    assert len(
        db_session.scalars(
            select(AIUsageRecord).where(AIUsageRecord.invocation_id == invocation.id)
        ).all()
    ) == 1


def test_ai_invocation_completion_rejects_conflicting_usage(db_session) -> None:
    invocation = start_invocation(db_session)
    complete_ai_invocation(
        db_session,
        invocation_id=invocation.id,
        input_tokens=10,
        output_tokens=20,
        now=datetime.now(UTC),
    )

    with pytest.raises(AIInvocationTransitionError):
        complete_ai_invocation(
            db_session,
            invocation_id=invocation.id,
            input_tokens=11,
            output_tokens=20,
        )


def test_ai_invocation_failure_and_cancellation_are_terminal_and_idempotent(
    db_session,
) -> None:
    failed = start_invocation(db_session)
    first_failure = fail_ai_invocation(
        db_session,
        invocation_id=failed.id,
        error_code="PROVIDER_TIMEOUT",
    )
    replay_failure = fail_ai_invocation(
        db_session,
        invocation_id=failed.id,
        error_code="PROVIDER_TIMEOUT",
    )
    assert first_failure.status == "failed"
    assert replay_failure.error_code == "PROVIDER_TIMEOUT"

    cancelled = start_invocation(db_session, request_fingerprint="b" * 64)
    first_cancel = cancel_ai_invocation(db_session, invocation_id=cancelled.id)
    replay_cancel = cancel_ai_invocation(db_session, invocation_id=cancelled.id)
    assert first_cancel.status == "cancelled"
    assert replay_cancel.status == "cancelled"

    with pytest.raises(AIInvocationTransitionError):
        fail_ai_invocation(
            db_session,
            invocation_id=cancelled.id,
            error_code="LATE_FAILURE",
        )


def test_ai_invocation_cannot_reference_a_job_from_another_store(db_session) -> None:
    from store_operator.jobs import create_job
    from store_operator.models import Store, User

    user = User(
        email_normalized="ai-invocation-owner@example.test",
        password_hash="test-password-hash",
    )
    store = Store(name="Invocation Owner Store", timezone="Asia/Tokyo")
    other_store = Store(name="Other Invocation Store", timezone="Asia/Tokyo")
    db_session.add_all([user, store, other_store])
    db_session.flush()
    job = create_job(
        db_session,
        job_type="copy.generate",
        payload_ref={"schema_version": 1},
        idempotency_key="ai-invocation-job",
        store_id=store.id,
        actor_type="user",
        actor_user_id=user.id,
    )

    with pytest.raises(LookupError):
        start_invocation(
            db_session,
            store_id=other_store.id,
            job_id=job.id,
            request_fingerprint="c" * 64,
        )
