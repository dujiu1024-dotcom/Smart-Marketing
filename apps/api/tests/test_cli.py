from uuid import uuid4

import pytest
from sqlalchemy import select

from store_operator.cli import replay_dead_letter_outbox_event
from store_operator.jobs.service import create_job
from store_operator.models import AuditEvent, OutboxEvent, Store, User


def create_dead_letter(db_session, *, job_status: str = "queued"):
    user = User(
        email_normalized=f"outbox-{uuid4()}@example.test",
        password_hash="test-password-hash",
    )
    store = Store(name="Outbox Recovery Store", timezone="Asia/Tokyo")
    db_session.add_all([user, store])
    db_session.flush()
    job = create_job(
        db_session,
        job_type="copy.generate",
        payload_ref={"schema_version": 1},
        idempotency_key=f"outbox-recovery-{uuid4()}",
        store_id=store.id,
        actor_type="user",
        actor_user_id=user.id,
    )
    job.status = job_status
    event = db_session.scalar(
        select(OutboxEvent).where(OutboxEvent.aggregate_id == job.id)
    )
    assert event is not None
    event.status = "dead"
    event.publish_attempts = 12
    event.last_error = "Broker unavailable"
    db_session.flush()
    return job, event


def test_dead_letter_replay_is_explicit_audited_and_resets_dispatch_budget(db_session):
    job, event = create_dead_letter(db_session)

    replayed = replay_dead_letter_outbox_event(
        db_session,
        event_id=event.id,
        reason="Broker recovered; verify job remains queued",
        confirmation=str(event.id),
    )

    assert replayed.id == event.id
    assert replayed.status == "pending"
    assert replayed.publish_attempts == 0
    assert replayed.locked_by is None
    assert replayed.locked_until is None
    assert replayed.last_error is None
    assert replayed.available_at is not None

    audit = db_session.scalar(
        select(AuditEvent).where(
            AuditEvent.action == "outbox.dead_letter.replayed",
            AuditEvent.target_id == str(event.id),
        )
    )
    assert audit is not None
    assert audit.store_id == job.store_id
    assert audit.metadata_json["job_id"] == str(job.id)
    assert audit.metadata_json["previous_publish_attempts"] == 12
    assert audit.metadata_json["reason"] == "Broker recovered; verify job remains queued"


def test_dead_letter_replay_rejects_missing_confirmation_and_terminal_job(db_session):
    job, event = create_dead_letter(db_session)

    with pytest.raises(SystemExit, match="Confirmation"):
        replay_dead_letter_outbox_event(
            db_session,
            event_id=event.id,
            reason="Operator checked broker",
            confirmation="wrong-event-id",
        )
    assert event.status == "dead"

    job.status = "succeeded"
    db_session.flush()
    with pytest.raises(SystemExit, match="queued or retry-wait"):
        replay_dead_letter_outbox_event(
            db_session,
            event_id=event.id,
            reason="Do not replay completed work",
            confirmation=str(event.id),
        )
    assert event.status == "dead"



def test_dead_letter_replay_rejects_non_object_payload(db_session):
    _, event = create_dead_letter(db_session)
    event.payload_json = []
    db_session.flush()

    with pytest.raises(SystemExit, match="invalid payload"):
        replay_dead_letter_outbox_event(
            db_session,
            event_id=event.id,
            reason="Malformed event requires investigation",
            confirmation=str(event.id),
        )

    assert event.status == "dead"


def test_dead_letter_replay_rejects_mismatched_aggregate_reference(db_session):
    _, event = create_dead_letter(db_session)
    event.aggregate_id = uuid4()
    db_session.flush()

    with pytest.raises(SystemExit, match="aggregate does not match"):
        replay_dead_letter_outbox_event(
            db_session,
            event_id=event.id,
            reason="Reject mismatched aggregate identity",
            confirmation=str(event.id),
        )

    assert event.status == "dead"
