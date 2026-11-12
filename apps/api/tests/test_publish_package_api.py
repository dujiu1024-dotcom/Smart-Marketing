from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from store_operator.auth.security import hash_password
from store_operator.models import (
    Artifact,
    ArtifactVersion,
    BusinessFactSnapshot,
    ChannelAccount,
    ChannelContent,
    ChannelSpec,
    ChannelSpecVersion,
    MarketingTask,
    PublishConfirmation,
    PublishOperation,
    PublishPackage,
    PublishPackageItem,
    QualityReport,
    QualityResolution,
    RequirementSnapshot,
    ReviewRecord,
    Store,
    StoreMembership,
    StrategySnapshot,
    User,
)
from store_operator.models.store_knowledge import StoreRecordRevision

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
        email_normalized="publish-package@example.com",
        password_hash=hash_password("test-password-123"),
        status="active",
    )
    db.add(user)
    db.flush()
    return user


def create_store(db: Session, user: User) -> Store:
    store = Store(
        id=uuid4(),
        name="Publish Package Store",
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
        json={
            "email": "publish-package@example.com",
            "password": "test-password-123",
        },
        headers=ORIGIN,
    )
    assert response.status_code == 200, response.text
    return response.json()["csrf_token"]


def create_package_inputs(
    db: Session, identity_client, user: User, store: Store, csrf: str
):
    task_response = identity_client.post(
        "/api/v1/marketing-tasks",
        headers={
            **ORIGIN,
            "X-Store-ID": str(store.id),
            "X-CSRF-Token": csrf,
            "Idempotency-Key": "package-task-create",
        },
        json={
            "task_type": "copy_only",
            "title": "Freeze approved content",
            "requirement_draft": {"goal": "Prepare a store post"},
            "task_options": {
                "includes_copy": True,
                "includes_image": False,
                "opportunity_applicable": False,
                "selected_channel_keys": ["douyin"],
                "requires_external_delivery": True,
            },
        },
    )
    assert task_response.status_code == 201, task_response.text
    task_id = UUID(task_response.json()["id"])
    task = db.get(MarketingTask, task_id)
    assert task is not None
    now = datetime.now(UTC)

    requirement = RequirementSnapshot(
        id=uuid4(),
        store_id=store.id,
        task_id=task.id,
        snapshot_no=1,
        payload_json={"goal": "Prepare a store post"},
        schema_version=1,
        content_fingerprint="1" * 64,
        created_by_user_id=user.id,
        confirmed_by_user_id=user.id,
        confirmed_at=now,
    )
    db.add(requirement)
    db.flush()
    strategy = StrategySnapshot(
        id=uuid4(),
        store_id=store.id,
        task_id=task.id,
        requirement_snapshot_id=requirement.id,
        snapshot_no=1,
        payload_json={"positioning": "Convenient local store"},
        schema_version=1,
        content_fingerprint="2" * 64,
        created_by_user_id=user.id,
        confirmed_by_user_id=user.id,
        confirmed_at=now,
    )
    db.add(strategy)
    db.flush()
    task.current_requirement_snapshot_id = requirement.id
    task.current_strategy_snapshot_id = strategy.id
    task.version = 2
    task.lifecycle_status = "active"
    db.flush()

    record_id = uuid4()
    revision = StoreRecordRevision(
        id=uuid4(),
        store_id=store.id,
        record_type="store_profile",
        record_id=record_id,
        version_no=1,
        snapshot_json={"store_name": store.name, "address": "1 Example Street"},
        schema_version=1,
        content_fingerprint="3" * 64,
        fact_status="confirmed",
        created_by_user_id=user.id,
        confirmed_by_user_id=user.id,
        confirmed_at=now,
    )
    db.add(revision)
    db.flush()
    fact = BusinessFactSnapshot(
        id=uuid4(),
        store_id=store.id,
        task_id=task.id,
        fact_key="store_profile",
        source_type="store_profile",
        source_id=record_id,
        source_version=1,
        version_no=1,
        value_json=revision.snapshot_json,
        schema_version=1,
        content_fingerprint=revision.content_fingerprint,
        confirmation_status="confirmed",
        created_by_user_id=user.id,
        confirmed_by_user_id=user.id,
        confirmed_at=now,
    )
    db.add(fact)
    db.flush()

    artifact_id = uuid4()
    version_id = uuid4()
    artifact = Artifact(
        id=artifact_id,
        store_id=store.id,
        task_id=task.id,
        artifact_type="copy",
        current_version_id=None,
    )
    db.add(artifact)
    db.flush()
    version = ArtifactVersion(
        id=version_id,
        store_id=store.id,
        artifact_id=artifact.id,
        version_no=1,
        source_type="manual_edit",
        content_json={"title": "Local store update", "body": "Visit us this week."},
        content_hash="4" * 64,
        input_fingerprint="5" * 64,
        created_by_user_id=user.id,
    )
    db.add(version)
    db.flush()
    artifact.current_version_id = version.id
    db.add(
        ReviewRecord(
            id=uuid4(),
            store_id=store.id,
            artifact_id=artifact.id,
            artifact_version_id=version.id,
            review_type="copy",
            decision="approved",
            reviewer_user_id=user.id,
        )
    )
    db.flush()

    content = ChannelContent(
        id=uuid4(),
        store_id=store.id,
        task_id=task.id,
        channel_key="douyin",
        copy_version_id=version.id,
        payload_json={"title": "Local store update", "body": "Visit us this week."},
        channel_spec_version_id=db.query(ChannelSpecVersion)
        .join(ChannelSpec, ChannelSpec.id == ChannelSpecVersion.channel_spec_id)
        .filter(ChannelSpec.channel_key == "douyin")
        .one()
        .id,
        input_fingerprint="6" * 64,
        status="ready",
    )
    db.add(content)
    db.flush()
    return task, fact, content


def report_fingerprint(content: ChannelContent, rule_version: str) -> str:
    import hashlib
    import json

    canonical = json.dumps(
        {
            "channel_content_id": str(content.id),
            "channel_content_fingerprint": content.input_fingerprint,
            "rule_version": rule_version,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def test_publish_package_requires_accepted_quality_and_confirmed_facts(
    identity_client, db_session: Session, monkeypatch
) -> None:
    user = create_user(db_session)
    store = create_store(db_session, user)
    store_b = create_store(db_session, user)
    csrf = login(identity_client, monkeypatch)
    task, fact, content = create_package_inputs(db_session, identity_client, user, store, csrf)

    report = QualityReport(
        id=uuid4(),
        store_id=store.id,
        task_id=task.id,
        channel_content_id=content.id,
        rule_version="content-structure-v1",
        input_fingerprint=report_fingerprint(content, "content-structure-v1"),
        result="needs_human",
        issues_json=[{"code": "BUSINESS_FACTS_REQUIRE_HUMAN_CHECK", "severity": "review"}],
    )
    db_session.add(report)
    db_session.flush()

    headers = {
        **ORIGIN,
        "X-CSRF-Token": csrf,
        "X-Store-ID": str(store.id),
    }
    freeze_url = f"/api/v1/marketing-tasks/{task.id}/publish-packages/freeze"
    freeze_payload = {
        "expected_task_version": task.version,
        "fact_snapshot_ids": [str(fact.id)],
        "items": [
            {
                "channel_content_id": str(content.id),
                "quality_report_id": str(report.id),
                "delivery_mode": "manual_handoff",
            }
        ],
    }
    blocked = identity_client.post(
        freeze_url,
        headers={**headers, "Idempotency-Key": "package-freeze-blocked"},
        json=freeze_payload,
    )
    assert blocked.status_code == 422, blocked.text
    assert blocked.json()["error"]["code"] == "QUALITY_RESOLUTION_REQUIRED"

    resolution = QualityResolution(
        id=uuid4(),
        store_id=store.id,
        quality_report_id=report.id,
        quality_report_fingerprint=report.input_fingerprint,
        decision="accepted",
        reviewer_user_id=user.id,
        reason="Verified the fact against the confirmed store profile.",
    )
    db_session.add(resolution)
    db_session.flush()

    frozen_headers = {**headers, "Idempotency-Key": "package-freeze-accepted"}
    frozen = identity_client.post(
        freeze_url,
        headers=frozen_headers,
        json=freeze_payload,
    )
    assert frozen.status_code == 201, frozen.text
    package = frozen.json()
    assert package["package_version"] == 1
    assert package["items"][0]["delivery_mode"] == "manual_handoff"
    assert package["fact_snapshot_ids"] == [str(fact.id)]
    assert len(package["package_fingerprint"]) == 64

    replay = identity_client.post(
        freeze_url,
        headers=frozen_headers,
        json=freeze_payload,
    )
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == package["id"]

    confirm_url = f"/api/v1/marketing-tasks/publish-packages/{package['id']}/confirm"
    confirm_headers = {**headers, "Idempotency-Key": "package-confirm-1"}
    confirm_payload = {
        "package_fingerprint": package["package_fingerprint"],
        "confirmation_note": "Confirmed the frozen manual handoff package.",
    }
    confirmed = identity_client.post(
        confirm_url,
        headers=confirm_headers,
        json=confirm_payload,
    )
    assert confirmed.status_code == 201, confirmed.text
    assert confirmed.json()["published"] is False
    assert confirmed.json()["delivery_mode"] == "manual_handoff"

    confirmation_replay = identity_client.post(
        confirm_url,
        headers=confirm_headers,
        json=confirm_payload,
    )
    assert confirmation_replay.status_code == 201, confirmation_replay.text
    assert confirmation_replay.json()["id"] == confirmed.json()["id"]

    # Seed a persisted operation tied to the confirmed frozen package, then
    # verify its read endpoint remains scoped to the request's selected store.
    account = ChannelAccount(
        id=uuid4(),
        store_id=store.id,
        provider="douyin",
        external_account_id="publish-operation-readback",
        granted_scopes=["user_info", "video.create", "video.list"],
        access_token_secret_ref="secret://publish-operation/access",
        refresh_token_secret_ref="secret://publish-operation/refresh",
        access_token_expires_at=datetime.now(UTC),
        status="active",
        connected_by_user_id=user.id,
    )
    db_session.add(account)
    db_session.flush()
    package_row = db_session.query(PublishPackage).filter(
        PublishPackage.id == package["id"]
    ).one()
    package_item = db_session.query(PublishPackageItem).filter(
        PublishPackageItem.publish_package_id == package_row.id
    ).one()
    package_item.delivery_mode = "official_api"
    package_item.channel_account_id = account.id
    db_session.flush()
    operation = PublishOperation(
        id=uuid4(),
        store_id=store.id,
        publish_package_id=package_row.id,
        publish_package_item_id=package_item.id,
        publish_confirmation_id=UUID(confirmed.json()["id"]),
        channel_account_id=account.id,
        idempotency_key="publish-operation-readback",
        request_fingerprint="7" * 64,
        status="queued",
        attempt_count=0,
        confirmed_by_user_id=user.id,
        confirmed_package_fingerprint=package_row.package_fingerprint,
        next_attempt_at=datetime.now(UTC),
    )
    db_session.add(operation)
    db_session.flush()

    hidden_operation = identity_client.get(
        f"/api/v1/marketing-tasks/publish-operations/{operation.id}",
        headers={"X-Store-ID": str(store_b.id)},
    )
    assert hidden_operation.status_code == 404, hidden_operation.text
    visible_operation = identity_client.get(
        f"/api/v1/marketing-tasks/publish-operations/{operation.id}",
        headers={"X-Store-ID": str(store.id)},
    )
    assert visible_operation.status_code == 200, visible_operation.text
    assert visible_operation.json()["id"] == str(operation.id)

    packages = identity_client.get(
        f"/api/v1/marketing-tasks/{task.id}/publish-packages",
        headers=headers,
    )
    assert packages.status_code == 200, packages.text
    assert packages.json()[0]["confirmation"]["id"] == confirmed.json()["id"]
    assert db_session.query(PublishPackage).count() == 1
    assert db_session.query(PublishConfirmation).count() == 1

    # The same actor is a member of both stores; the request-scoped store still
    # must not expose or mutate Store A's frozen package while scoped to Store B.
    other_store_headers = {**headers, "X-Store-ID": str(store_b.id)}
    hidden_list = identity_client.get(
        f"/api/v1/marketing-tasks/{task.id}/publish-packages",
        headers=other_store_headers,
    )
    assert hidden_list.status_code == 404

    hidden_freeze = identity_client.post(
        freeze_url,
        headers={**other_store_headers, "Idempotency-Key": "package-cross-store-freeze"},
        json=freeze_payload,
    )
    assert hidden_freeze.status_code == 404

    hidden_confirm = identity_client.post(
        confirm_url,
        headers={**other_store_headers, "Idempotency-Key": "package-cross-store-confirm"},
        json=confirm_payload,
    )
    assert hidden_confirm.status_code == 404
    assert db_session.query(PublishPackage).count() == 1
    assert db_session.query(PublishConfirmation).count() == 1


def test_publish_package_rejects_hard_fail(
    identity_client, db_session: Session, monkeypatch
) -> None:
    user = create_user(db_session)
    store = create_store(db_session, user)
    csrf = login(identity_client, monkeypatch)
    task, fact, content = create_package_inputs(db_session, identity_client, user, store, csrf)
    report = QualityReport(
        id=uuid4(),
        store_id=store.id,
        task_id=task.id,
        channel_content_id=content.id,
        rule_version="content-structure-v1",
        input_fingerprint=report_fingerprint(content, "content-structure-v1"),
        result="fail",
        issues_json=[{"code": "PLACEHOLDER_TEXT", "severity": "hard"}],
    )
    db_session.add(report)
    db_session.flush()

    response = identity_client.post(
        f"/api/v1/marketing-tasks/{task.id}/publish-packages/freeze",
        headers={
            **ORIGIN,
            "X-CSRF-Token": csrf,
            "X-Store-ID": str(store.id),
            "Idempotency-Key": "package-hard-fail",
        },
        json={
            "expected_task_version": task.version,
            "fact_snapshot_ids": [str(fact.id)],
            "items": [
                {
                    "channel_content_id": str(content.id),
                    "quality_report_id": str(report.id),
                    "delivery_mode": "manual_handoff",
                }
            ],
        },
    )
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "QUALITY_BLOCKED"



def test_publish_freeze_rejects_cross_store_associated_ids(
    identity_client, db_session: Session, monkeypatch
) -> None:
    user = create_user(db_session)
    store_a = create_store(db_session, user)
    store_b = create_store(db_session, user)
    csrf = login(identity_client, monkeypatch)
    task_a, fact_a, content_a = create_package_inputs(
        db_session, identity_client, user, store_a, csrf
    )
    task_b, fact_b, content_b = create_package_inputs(
        db_session, identity_client, user, store_b, csrf
    )
    report_a = QualityReport(
        id=uuid4(),
        store_id=store_a.id,
        task_id=task_a.id,
        channel_content_id=content_a.id,
        rule_version="content-structure-v1",
        input_fingerprint=report_fingerprint(content_a, "content-structure-v1"),
        result="pass",
        issues_json=[],
    )
    report_b = QualityReport(
        id=uuid4(),
        store_id=store_b.id,
        task_id=task_b.id,
        channel_content_id=content_b.id,
        rule_version="content-structure-v1",
        input_fingerprint=report_fingerprint(content_b, "content-structure-v1"),
        result="pass",
        issues_json=[],
    )
    db_session.add_all([report_a, report_b])
    db_session.flush()

    headers_b = {
        **ORIGIN,
        "X-CSRF-Token": csrf,
        "X-Store-ID": str(store_b.id),
    }
    freeze_url = f"/api/v1/marketing-tasks/{task_b.id}/publish-packages/freeze"

    def freeze(key: str, fact_id, content_id, report_id, delivery_mode="manual_handoff",
               channel_account_id=None):
        return identity_client.post(
            freeze_url,
            headers={**headers_b, "Idempotency-Key": key},
            json={
                "expected_task_version": task_b.version,
                "fact_snapshot_ids": [str(fact_id)],
                "items": [{
                    "channel_content_id": str(content_id),
                    "quality_report_id": str(report_id),
                    "delivery_mode": delivery_mode,
                    "channel_account_id": (
                        str(channel_account_id) if channel_account_id is not None else None
                    ),
                }],
            },
        )

    # A foreign business-fact ID cannot be attached to Store B's task.
    foreign_fact = freeze(
        "freeze-foreign-fact", fact_a.id, content_b.id, report_b.id
    )
    assert foreign_fact.status_code == 404, foreign_fact.text
    assert foreign_fact.json()["error"]["code"] == "BUSINESS_FACT_NOT_FOUND"

    # A foreign channel-content ID cannot be attached to Store B's package.
    foreign_content = freeze(
        "freeze-foreign-content", fact_b.id, content_a.id, report_a.id
    )
    assert foreign_content.status_code == 404, foreign_content.text
    assert foreign_content.json()["error"]["code"] == "CHANNEL_CONTENT_NOT_FOUND"

    # A Store A quality report cannot be paired with Store B's content.
    foreign_report = freeze(
        "freeze-foreign-report", fact_b.id, content_b.id, report_a.id
    )
    assert foreign_report.status_code == 404, foreign_report.text
    assert foreign_report.json()["error"]["code"] == "QUALITY_REPORT_NOT_FOUND"

    # A Store A channel account cannot be bound to Store B's official delivery item.
    account_a = ChannelAccount(
        id=uuid4(),
        store_id=store_a.id,
        provider="douyin",
        external_account_id="store-a-douyin",
        granted_scopes=["user_info", "video.create", "video.list"],
        access_token_secret_ref="secret://store-a/access",
        refresh_token_secret_ref="secret://store-a/refresh",
        access_token_expires_at=datetime.now(UTC),
        status="active",
        connected_by_user_id=user.id,
    )
    db_session.add(account_a)
    db_session.flush()
    foreign_account = freeze(
        "freeze-foreign-account",
        fact_b.id,
        content_b.id,
        report_b.id,
        delivery_mode="official_api",
        channel_account_id=account_a.id,
    )
    assert foreign_account.status_code == 409, foreign_account.text
    assert foreign_account.json()["error"]["code"] == "CHANNEL_ACCOUNT_UNAVAILABLE"

    assert db_session.query(PublishPackage).count() == 0
    assert db_session.query(PublishConfirmation).count() == 0
