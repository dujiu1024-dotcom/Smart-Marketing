from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from store_operator.auth.security import hash_password
from store_operator.models import (
    BusinessFactSnapshot,
    MarketingTask,
    RequirementSnapshot,
    StepDecision,
    Store,
    StoreMembership,
    StrategySnapshot,
    TaskEvent,
    TaskStep,
    User,
)
from store_operator.models.store_knowledge import IdempotencyRecord, StoreRecordRevision

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



def test_full_marketing_requires_copy_and_image_scope(
    identity_client, db_session, monkeypatch
):
    user = create_user(db_session, "full-marketing-scope@example.com")
    store = create_store(db_session, user, "Full Marketing Scope Store")
    csrf = login(identity_client, monkeypatch, "full-marketing-scope@example.com")
    response = identity_client.post(
        "/api/v1/marketing-tasks",
        headers={
            **ORIGIN,
            "X-CSRF-Token": csrf,
            "X-Store-ID": str(store.id),
            "Idempotency-Key": "full-marketing-scope-1",
        },
        json={
            "task_type": "full_marketing",
            "title": "Complete campaign",
            "task_options": {"includes_copy": False, "includes_image": True},
        },
    )
    assert response.status_code == 422



def test_requirement_and_strategy_confirmation_freeze_exact_source_versions(
    identity_client, db_session, monkeypatch
):
    user = create_user(db_session, "task-snapshots@example.com")
    store = create_store(db_session, user, "Task Snapshot Store")
    csrf = login(identity_client, monkeypatch, "task-snapshots@example.com")
    create_headers = {
        **ORIGIN,
        "X-CSRF-Token": csrf,
        "X-Store-ID": str(store.id),
        "Idempotency-Key": "task-snapshots-create",
    }
    created = identity_client.post(
        "/api/v1/marketing-tasks",
        headers=create_headers,
        json=task_payload(),
    )
    assert created.status_code == 201, created.text
    task_id = UUID(created.json()["id"])

    updated = identity_client.patch(
        f"/api/v1/marketing-tasks/{task_id}/requirement",
        headers={
            **ORIGIN,
            "X-CSRF-Token": csrf,
            "X-Store-ID": str(store.id),
            "Idempotency-Key": "task-requirement-update",
        },
        json={
            "expected_version": 1,
            "requirement_draft": {
                "goal": "Increase weekday visits",
                "audience": "Nearby office workers",
            },
            "task_options": {
                "includes_copy": True,
                "includes_image": False,
                "opportunity_applicable": False,
                "selected_channel_keys": ["wechat"],
                "requires_external_delivery": False,
            },
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["version"] == 2
    channel_step = next(
        step
        for step in updated.json()["steps"]
        if step["step_key"] == "channel_adaptation"
    )
    assert channel_step["applicability"] == "required"
    assert channel_step["status"] == "pending"

    source_id = uuid4()
    revision = StoreRecordRevision(
        id=uuid4(),
        store_id=store.id,
        record_type="store_profile",
        record_id=source_id,
        version_no=3,
        snapshot_json={"store_name": "Task Snapshot Store", "area": "Central"},
        schema_version=1,
        content_fingerprint="b" * 64,
        fact_status="confirmed",
        created_by_user_id=user.id,
        confirmed_by_user_id=user.id,
        confirmed_at=datetime.now(UTC),
    )
    db_session.add(revision)
    db_session.flush()

    confirm_payload = {
        "expected_version": 2,
        "business_facts": [
            {
                "fact_key": "store_profile",
                "record_type": "store_profile",
                "record_id": str(source_id),
                "expected_version_no": 3,
            }
        ],
    }
    confirm_headers = {
        **ORIGIN,
        "X-CSRF-Token": csrf,
        "X-Store-ID": str(store.id),
        "Idempotency-Key": "task-requirement-confirm",
    }
    confirmed = identity_client.post(
        f"/api/v1/marketing-tasks/{task_id}/requirement/confirm",
        headers=confirm_headers,
        json=confirm_payload,
    )
    assert confirmed.status_code == 200, confirmed.text
    confirmed_result = confirmed.json()
    assert confirmed_result["lifecycle_status"] == "active"
    assert confirmed_result["version"] == 3
    assert confirmed_result["current_requirement_snapshot_id"]

    requirement_step = next(
        step
        for step in confirmed_result["steps"]
        if step["step_key"] == "requirement_understanding"
    )
    context_step = next(
        step
        for step in confirmed_result["steps"]
        if step["step_key"] == "context_snapshot"
    )
    assert requirement_step["status"] == "succeeded"
    assert context_step["status"] == "succeeded"

    replay = identity_client.post(
        f"/api/v1/marketing-tasks/{task_id}/requirement/confirm",
        headers=confirm_headers,
        json=confirm_payload,
    )
    assert replay.status_code == 200
    assert replay.json()["version"] == 3

    requirement_snapshot = db_session.scalar(
        select(RequirementSnapshot).where(
            RequirementSnapshot.task_id == task_id
        )
    )
    business_fact = db_session.scalar(
        select(BusinessFactSnapshot).where(BusinessFactSnapshot.task_id == task_id)
    )
    assert requirement_snapshot is not None
    assert business_fact is not None
    assert business_fact.source_version == 3
    assert business_fact.content_fingerprint == "b" * 64
    assert business_fact.confirmation_status == "confirmed"

    strategy = identity_client.post(
        f"/api/v1/marketing-tasks/{task_id}/strategy/confirm",
        headers={
            **ORIGIN,
            "X-CSRF-Token": csrf,
            "X-Store-ID": str(store.id),
            "Idempotency-Key": "task-strategy-confirm",
        },
        json={
            "expected_version": 3,
            "strategy": {
                "positioning": "Weekday convenience",
                "offer": "Lunch set promotion",
            },
        },
    )
    assert strategy.status_code == 200, strategy.text
    assert strategy.json()["version"] == 4
    assert strategy.json()["current_strategy_snapshot_id"]

    strategy_snapshot = db_session.scalar(
        select(StrategySnapshot).where(StrategySnapshot.task_id == task_id)
    )
    assert strategy_snapshot is not None
    assert strategy_snapshot.requirement_snapshot_id == requirement_snapshot.id
    strategy_step = next(
        step
        for step in strategy.json()["steps"]
        if step["step_key"] == "strategy_confirmation"
    )
    assert strategy_step["status"] == "succeeded"


def test_requirement_confirmation_rejects_unconfirmed_business_facts(
    identity_client, db_session, monkeypatch
):
    user = create_user(db_session, "task-unconfirmed-fact@example.com")
    store = create_store(db_session, user, "Unconfirmed Fact Store")
    csrf = login(identity_client, monkeypatch, "task-unconfirmed-fact@example.com")
    created = identity_client.post(
        "/api/v1/marketing-tasks",
        headers={
            **ORIGIN,
            "X-CSRF-Token": csrf,
            "X-Store-ID": str(store.id),
            "Idempotency-Key": "task-unconfirmed-create",
        },
        json=task_payload(),
    )
    assert created.status_code == 201, created.text
    task_id = created.json()["id"]

    source_id = uuid4()
    db_session.add(
        StoreRecordRevision(
            id=uuid4(),
            store_id=store.id,
            record_type="store_profile",
            record_id=source_id,
            version_no=1,
            snapshot_json={"store_name": "Unconfirmed Fact Store"},
            schema_version=1,
            content_fingerprint="c" * 64,
            fact_status="pending_confirmation",
        )
    )
    db_session.flush()

    response = identity_client.post(
        f"/api/v1/marketing-tasks/{task_id}/requirement/confirm",
        headers={
            **ORIGIN,
            "X-CSRF-Token": csrf,
            "X-Store-ID": str(store.id),
            "Idempotency-Key": "task-unconfirmed-confirm",
        },
        json={
            "expected_version": 1,
            "business_facts": [
                {
                    "fact_key": "store_profile",
                    "record_type": "store_profile",
                    "record_id": str(source_id),
                }
            ],
        },
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "BUSINESS_FACT_NOT_CONFIRMED"
    assert db_session.scalar(
        select(func.count())
        .select_from(BusinessFactSnapshot)
        .where(BusinessFactSnapshot.task_id == UUID(task_id))
    ) == 0


def test_optional_step_can_be_skipped_but_required_review_cannot(
    identity_client, db_session, monkeypatch
):
    user = create_user(db_session, "task-step-skip@example.com")
    store = create_store(db_session, user, "Task Step Skip Store")
    csrf = login(identity_client, monkeypatch, "task-step-skip@example.com")
    payload = task_payload()
    payload["task_options"] = {
        "includes_copy": True,
        "includes_image": False,
        "selected_channel_keys": [],
        "requires_external_delivery": False,
    }
    created = identity_client.post(
        "/api/v1/marketing-tasks",
        headers={
            **ORIGIN,
            "X-CSRF-Token": csrf,
            "X-Store-ID": str(store.id),
            "Idempotency-Key": "task-step-skip-create",
        },
        json=payload,
    )
    assert created.status_code == 201, created.text
    task_id = created.json()["id"]
    source_id = uuid4()
    db_session.add(
        StoreRecordRevision(
            id=uuid4(),
            store_id=store.id,
            record_type="store_profile",
            record_id=source_id,
            version_no=1,
            snapshot_json={"store_name": "Task Step Skip Store"},
            schema_version=1,
            content_fingerprint="d" * 64,
            fact_status="confirmed",
            created_by_user_id=user.id,
            confirmed_by_user_id=user.id,
            confirmed_at=datetime.now(UTC),
        )
    )
    db_session.flush()
    confirmed = identity_client.post(
        f"/api/v1/marketing-tasks/{task_id}/requirement/confirm",
        headers={
            **ORIGIN,
            "X-CSRF-Token": csrf,
            "X-Store-ID": str(store.id),
            "Idempotency-Key": "task-step-skip-confirm",
        },
        json={
            "expected_version": 1,
            "business_facts": [
                {
                    "fact_key": "store_profile",
                    "record_type": "store_profile",
                    "record_id": str(source_id),
                }
            ],
        },
    )
    assert confirmed.status_code == 200, confirmed.text

    skipped = identity_client.post(
        f"/api/v1/marketing-tasks/{task_id}/steps/opportunity_decision/skip",
        headers={
            **ORIGIN,
            "X-CSRF-Token": csrf,
            "X-Store-ID": str(store.id),
            "Idempotency-Key": "task-opportunity-skip",
        },
        json={
            "expected_version": 2,
            "reason": "No timely opportunity fits this task",
        },
    )
    assert skipped.status_code == 200, skipped.text
    assert skipped.json()["version"] == 3
    opportunity_step = next(
        step
        for step in skipped.json()["steps"]
        if step["step_key"] == "opportunity_decision"
    )
    assert opportunity_step["status"] == "skipped"
    assert opportunity_step["skip_reason"] == "No timely opportunity fits this task"
    assert db_session.scalar(
        select(StepDecision).where(StepDecision.task_id == UUID(task_id))
    ) is not None

    required_skip = identity_client.post(
        f"/api/v1/marketing-tasks/{task_id}/steps/copy_production_review/skip",
        headers={
            **ORIGIN,
            "X-CSRF-Token": csrf,
            "X-Store-ID": str(store.id),
            "Idempotency-Key": "task-required-step-skip",
        },
        json={
            "expected_version": 3,
            "reason": "Trying to bypass copy review",
        },
    )
    assert required_skip.status_code == 409
    assert required_skip.json()["error"]["code"] == "INVALID_TASK_STEP_TRANSITION"


def test_failed_step_recovery_cancel_and_archive_transitions(
    identity_client, db_session, monkeypatch
):
    user = create_user(db_session, "task-recovery@example.com")
    store = create_store(db_session, user, "Task Recovery Store")
    csrf = login(identity_client, monkeypatch, "task-recovery@example.com")
    created = identity_client.post(
        "/api/v1/marketing-tasks",
        headers={
            **ORIGIN,
            "X-CSRF-Token": csrf,
            "X-Store-ID": str(store.id),
            "Idempotency-Key": "task-recovery-create",
        },
        json=task_payload(),
    )
    assert created.status_code == 201, created.text
    task_id = UUID(created.json()["id"])
    task = db_session.get(MarketingTask, task_id)
    step = db_session.scalar(
        select(TaskStep).where(
            TaskStep.task_id == task_id,
            TaskStep.step_key == "copy_production_review",
        )
    )
    assert task is not None
    assert step is not None
    task.lifecycle_status = "failed"
    task.version = 2
    step.status = "failed"
    step.version = 2
    db_session.flush()

    recovered = identity_client.post(
        f"/api/v1/marketing-tasks/{task_id}/recover",
        headers={
            **ORIGIN,
            "X-CSRF-Token": csrf,
            "X-Store-ID": str(store.id),
            "Idempotency-Key": "task-recovery-retry",
        },
        json={
            "expected_version": 2,
            "step_key": "copy_production_review",
            "reason": "Provider timeout has been resolved",
        },
    )
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["lifecycle_status"] == "active"
    assert recovered.json()["version"] == 3
    recovered_step = next(
        item
        for item in recovered.json()["steps"]
        if item["step_key"] == "copy_production_review"
    )
    assert recovered_step["status"] == "running"

    cancelled = identity_client.post(
        f"/api/v1/marketing-tasks/{task_id}/cancel",
        headers={
            **ORIGIN,
            "X-CSRF-Token": csrf,
            "X-Store-ID": str(store.id),
            "Idempotency-Key": "task-recovery-cancel",
        },
        json={
            "expected_version": 3,
            "reason": "Campaign timing is no longer relevant",
        },
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["lifecycle_status"] == "cancelled"
    assert cancelled.json()["version"] == 4

    archived = identity_client.post(
        f"/api/v1/marketing-tasks/{task_id}/archive",
        headers={
            **ORIGIN,
            "X-CSRF-Token": csrf,
            "X-Store-ID": str(store.id),
            "Idempotency-Key": "task-recovery-archive",
        },
        json={
            "expected_version": 4,
            "reason": "Cancelled task retained for audit",
        },
    )
    assert archived.status_code == 200, archived.text
    assert archived.json()["lifecycle_status"] == "archived"
    assert archived.json()["version"] == 5
