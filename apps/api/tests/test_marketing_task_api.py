from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from store_operator.auth.security import hash_password
from store_operator.models import MarketingTask, Store, StoreMembership, TaskEvent, User
from store_operator.models.store_knowledge import IdempotencyRecord

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


def task_payload(title: str = "Weekday promotion copy") -> dict[str, object]:
    return {
        "task_type": "copy_only",
        "title": title,
        "requirement_draft": {"goal": "Increase weekday store visits"},
        "task_options": {
            "includes_copy": True,
            "includes_image": False,
            "opportunity_applicable": False,
            "selected_channel_keys": [],
            "requires_external_delivery": False,
        },
    }


def test_create_marketing_task_initializes_fixed_steps_and_event(
    identity_client, db_session, monkeypatch
):
    user = create_user(db_session, "marketing-task@example.com")
    store = create_store(db_session, user, "Marketing Task Store")
    csrf = login(identity_client, monkeypatch, "marketing-task@example.com")
    headers = {
        **ORIGIN,
        "X-CSRF-Token": csrf,
        "X-Store-ID": str(store.id),
        "Idempotency-Key": "marketing-task-create-1",
    }

    response = identity_client.post(
        "/api/v1/marketing-tasks",
        headers=headers,
        json=task_payload(),
    )
    assert response.status_code == 201, response.text
    result = response.json()
    assert result["task_type"] == "copy_only"
    assert result["lifecycle_status"] == "draft"
    assert result["version"] == 1
    assert result["requirement_draft"]["goal"] == "Increase weekday store visits"
    assert len(result["steps"]) == 10

    steps = {step["step_key"]: step for step in result["steps"]}
    assert steps["copy_production_review"]["status"] == "pending"
    assert steps["copy_production_review"]["applicability"] == "required"
    assert steps["image_production_review"]["status"] == "skipped"
    assert steps["image_production_review"]["applicability"] == "not_applicable"
    assert steps["opportunity_decision"]["status"] == "skipped"
    assert steps["channel_adaptation"]["status"] == "skipped"
    assert steps["quality_check"]["status"] == "skipped"
    assert steps["delivery"]["status"] == "skipped"

    task_id = UUID(result["id"])
    task = db_session.get(MarketingTask, task_id)
    assert task is not None
    assert task.store_id == store.id
    assert task.created_by_user_id == user.id

    event = db_session.scalar(
        select(TaskEvent).where(
            TaskEvent.task_id == task.id,
            TaskEvent.event_type == "task.created",
        )
    )
    assert event is not None
    assert event.aggregate_version == 1
    assert event.actor_type == "user"
    assert event.actor_user_id == user.id

    idem = db_session.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.store_id == store.id,
            IdempotencyRecord.idempotency_key == "marketing-task-create-1",
        )
    )
    assert idem is not None
    assert idem.actor_user_id == user.id
    assert idem.status == "completed"


def test_marketing_task_creation_is_idempotent_and_actor_bound(
    identity_client, db_session, monkeypatch
):
    first_user = create_user(db_session, "marketing-owner@example.com")
    second_user = create_user(db_session, "marketing-member@example.com")
    store = create_store(db_session, first_user, "Idempotency Store")
    db_session.add(
        StoreMembership(
            id=uuid4(),
            store_id=store.id,
            user_id=second_user.id,
            role="owner",
            status="active",
            joined_at=datetime.now(UTC),
        )
    )
    db_session.flush()

    first_csrf = login(identity_client, monkeypatch, "marketing-owner@example.com")
    headers = {
        **ORIGIN,
        "X-CSRF-Token": first_csrf,
        "X-Store-ID": str(store.id),
        "Idempotency-Key": "marketing-task-idempotency-1",
    }
    first = identity_client.post(
        "/api/v1/marketing-tasks", headers=headers, json=task_payload()
    )
    assert first.status_code == 201, first.text

    replay = identity_client.post(
        "/api/v1/marketing-tasks", headers=headers, json=task_payload()
    )
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == first.json()["id"]

    changed_payload = task_payload("Different task title")
    reused = identity_client.post(
        "/api/v1/marketing-tasks", headers=headers, json=changed_payload
    )
    assert reused.status_code == 409
    assert reused.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"

    second_csrf = login(identity_client, monkeypatch, "marketing-member@example.com")
    second_headers = {
        **ORIGIN,
        "X-CSRF-Token": second_csrf,
        "X-Store-ID": str(store.id),
        "Idempotency-Key": "marketing-task-idempotency-1",
    }
    cross_actor = identity_client.post(
        "/api/v1/marketing-tasks",
        headers=second_headers,
        json=task_payload(),
    )
    assert cross_actor.status_code == 409
    assert cross_actor.json()["error"]["code"] == "IDEMPOTENCY_KEY_SCOPE_MISMATCH"

    count = db_session.scalar(
        select(func.count())
        .select_from(MarketingTask)
        .where(MarketingTask.store_id == store.id)
    )
    assert count == 1


def test_marketing_task_detail_and_list_are_store_scoped(
    identity_client, db_session, monkeypatch
):
    user = create_user(db_session, "marketing-store-scope@example.com")
    store_a = create_store(db_session, user, "Marketing A")
    store_b = create_store(db_session, user, "Marketing B")
    csrf = login(identity_client, monkeypatch, "marketing-store-scope@example.com")

    headers_a = {
        **ORIGIN,
        "X-CSRF-Token": csrf,
        "X-Store-ID": str(store_a.id),
        "Idempotency-Key": "marketing-task-store-scope-1",
    }
    created = identity_client.post(
        "/api/v1/marketing-tasks",
        headers=headers_a,
        json=task_payload(),
    )
    assert created.status_code == 201, created.text
    task_id = created.json()["id"]

    headers_b = {
        **ORIGIN,
        "X-CSRF-Token": csrf,
        "X-Store-ID": str(store_b.id),
    }
    detail = identity_client.get(
        f"/api/v1/marketing-tasks/{task_id}", headers=headers_b
    )
    assert detail.status_code == 404
    assert detail.json()["error"]["code"] == "MARKETING_TASK_NOT_FOUND"

    listing = identity_client.get("/api/v1/marketing-tasks", headers=headers_b)
    assert listing.status_code == 200
    assert listing.json()["total"] == 0
    assert listing.json()["items"] == []


def test_merchant_content_requires_explicit_content_scope(
    identity_client, db_session, monkeypatch
):
    user = create_user(db_session, "merchant-content@example.com")
    store = create_store(db_session, user, "Merchant Content Store")
    csrf = login(identity_client, monkeypatch, "merchant-content@example.com")
    headers = {
        **ORIGIN,
        "X-CSRF-Token": csrf,
        "X-Store-ID": str(store.id),
        "Idempotency-Key": "merchant-content-create-1",
    }

    missing_scope = identity_client.post(
        "/api/v1/marketing-tasks",
        headers=headers,
        json={
            "task_type": "merchant_content",
            "title": "Merchant supplied content",
            "requirement_draft": {},
        },
    )
    assert missing_scope.status_code == 422

    empty_scope = identity_client.post(
        "/api/v1/marketing-tasks",
        headers=headers,
        json={
            "task_type": "merchant_content",
            "title": "Merchant supplied content",
            "requirement_draft": {},
            "task_options": {"includes_copy": False, "includes_image": False},
        },
    )
    assert empty_scope.status_code == 422
