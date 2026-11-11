from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from store_operator.auth.security import hash_password
from store_operator.jobs import create_job
from store_operator.models import AuditEvent, OutboxEvent, PlatformAdminGrant, Store, User

ORIGIN = {"Origin": "http://localhost:5173"}


class FakeRedis:
    def eval(self, script, numkeys, *args):
        return [1 for _ in args[:numkeys]]

    def delete(self, *keys):
        return len(keys)


def create_user(db: Session, email: str) -> User:
    user = User(
        id=uuid4(),
        email_normalized=email,
        password_hash=hash_password("test-password-123"),
        status="active",
    )
    db.add(user)
    db.flush()
    return user


def create_dead_outbox_event(
    db: Session,
    user: User,
    *,
    key: str,
) -> tuple[Store, OutboxEvent]:
    store = Store(
        id=uuid4(),
        name="Outbox operations",
        timezone="Asia/Tokyo",
        status="active",
    )
    db.add(store)
    db.flush()
    job = create_job(
        db,
        job_type="copy.generate",
        payload_ref={"schema_version": 1},
        idempotency_key=key,
        store_id=store.id,
        actor_type="platform_admin",
        actor_user_id=user.id,
    )
    event = db.scalar(
        select(OutboxEvent).where(OutboxEvent.aggregate_id == job.id)
    )
    assert event is not None
    event.status = "dead"
    event.publish_attempts = 12
    event.last_error = "Broker unavailable"
    event.locked_by = None
    event.locked_until = None
    db.flush()
    return store, event


def login(identity_client, monkeypatch, email: str) -> str:
    import store_operator.auth.router as auth_router

    monkeypatch.setattr(auth_router, "redis_client", FakeRedis())
    response = identity_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "test-password-123"},
        headers=ORIGIN,
    )
    assert response.status_code == 200, response.text
    return response.json()["csrf_token"]


def test_platform_admin_can_requeue_dead_outbox_event_with_audit(
    identity_client, db_session, monkeypatch
):
    admin = create_user(db_session, "outbox-admin@example.com")
    db_session.add(
        PlatformAdminGrant(
            id=uuid4(),
            user_id=admin.id,
            status="active",
            reason_code="test",
        )
    )
    db_session.flush()
    _, event = create_dead_outbox_event(
        db_session, admin, key="outbox-admin-requeue-1"
    )
    csrf = login(identity_client, monkeypatch, "outbox-admin@example.com")

    response = identity_client.post(
        f"/api/v1/admin/outbox-events/{event.id}/requeue",
        headers={**ORIGIN, "X-CSRF-Token": csrf},
        json={"reason": "Broker recovered; re-dispatch the queued Job"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "pending"
    assert response.json()["previous_publish_attempts"] == 12

    db_session.refresh(event)
    assert event.status == "pending"
    assert event.publish_attempts == 0
    assert event.last_error is None
    assert event.locked_by is None
    assert event.locked_until is None
    assert event.available_at <= datetime.now(UTC)

    audit = db_session.scalar(
        select(AuditEvent).where(
            AuditEvent.action == "outbox.event.requeued",
            AuditEvent.target_id == str(event.id),
        )
    )
    assert audit is not None
    assert audit.actor_type == "platform_admin"
    assert audit.actor_id == admin.id
    assert audit.metadata_json["previous_publish_attempts"] == 12


def test_non_admin_cannot_requeue_dead_outbox_event(
    identity_client, db_session, monkeypatch
):
    user = create_user(db_session, "outbox-member@example.com")
    _, event = create_dead_outbox_event(
        db_session, user, key="outbox-non-admin-requeue-1"
    )
    csrf = login(identity_client, monkeypatch, "outbox-member@example.com")

    response = identity_client.post(
        f"/api/v1/admin/outbox-events/{event.id}/requeue",
        headers={**ORIGIN, "X-CSRF-Token": csrf},
        json={"reason": "Attempt to requeue from a non-admin account"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"

    db_session.refresh(event)
    assert event.status == "dead"
    assert event.publish_attempts == 12


def test_only_dead_job_dispatch_events_can_be_requeued(
    identity_client, db_session, monkeypatch
):
    admin = create_user(db_session, "outbox-admin-state@example.com")
    db_session.add(
        PlatformAdminGrant(
            id=uuid4(),
            user_id=admin.id,
            status="active",
            reason_code="test",
        )
    )
    db_session.flush()
    _, event = create_dead_outbox_event(
        db_session, admin, key="outbox-not-dead-1"
    )
    event.status = "pending"
    db_session.flush()
    csrf = login(identity_client, monkeypatch, "outbox-admin-state@example.com")

    response = identity_client.post(
        f"/api/v1/admin/outbox-events/{event.id}/requeue",
        headers={**ORIGIN, "X-CSRF-Token": csrf},
        json={"reason": "This event should not be requeued"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "OUTBOX_EVENT_NOT_DEAD"
