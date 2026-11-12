import hashlib
import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import delete, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from store_operator.auth.security import hash_password
from store_operator.models import (
    ArtifactVersion,
    MediaAsset,
    OutboxEvent,
    ReviewRecord,
    Store,
    StoreMembership,
    User,
)

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

    def incr(self, key):
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]

    def expire(self, key, seconds):
        return True

    def delete(self, *keys):
        for key in keys:
            self.values.pop(key, None)
        return len(keys)


def create_user(db: Session, email: str) -> User:
    user = User(
        id=uuid4(),
        email_normalized=email.casefold(),
        password_hash=hash_password("test-password-123"),
        status="active",
    )
    db.add(user)
    db.flush()
    return user


def create_store(db: Session, user: User) -> Store:
    store = Store(id=uuid4(), name="Content Test Store", timezone="Asia/Tokyo", status="active")
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


def task_payload() -> dict[str, object]:
    return {
        "task_type": "copy_only",
        "title": "Content API test",
        "requirement_draft": {"goal": "Create an approved store post"},
        "task_options": {
            "includes_copy": True,
            "includes_image": False,
            "opportunity_applicable": False,
            "selected_channel_keys": [],
            "requires_external_delivery": False,
        },
    }


def test_artifact_versions_and_reviews_are_version_bound(
    identity_client, db_session: Session, monkeypatch
) -> None:
    import store_operator.auth.router as auth_router

    monkeypatch.setattr(auth_router, "redis_client", FakeRedis())
    user = create_user(db_session, "content-api@example.com")
    store = create_store(db_session, user)
    login = identity_client.post(
        "/api/v1/auth/login",
        json={"email": "content-api@example.com", "password": "test-password-123"},
        headers=ORIGIN,
    )
    assert login.status_code == 200, login.text
    csrf = login.json()["csrf_token"]
    headers = {
        **ORIGIN,
        "X-CSRF-Token": csrf,
        "X-Store-ID": str(store.id),
    }

    task = identity_client.post(
        "/api/v1/marketing-tasks",
        headers={**headers, "Idempotency-Key": "content-task-create"},
        json=task_payload(),
    )
    assert task.status_code == 201, task.text
    task_id = task.json()["id"]

    first_payload = {
        "artifact_type": "copy",
        "version": {
            "source_type": "manual_edit",
            "content_json": {
                "title": "Weekday special",
                "body": "Visit our store this week.",
            },
        },
    }
    created = identity_client.post(
        f"/api/v1/marketing-tasks/{task_id}/artifacts",
        headers={**headers, "Idempotency-Key": "content-artifact-create"},
        json=first_payload,
    )
    assert created.status_code == 201, created.text
    artifact_id = created.json()["id"]
    first_version_id = created.json()["current_version_id"]
    canonical = json.dumps(
        first_payload["version"]["content_json"],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    assert created.json()["versions"][0]["content_hash"] == hashlib.sha256(canonical).hexdigest()

    replay = identity_client.post(
        f"/api/v1/marketing-tasks/{task_id}/artifacts",
        headers={**headers, "Idempotency-Key": "content-artifact-create"},
        json=first_payload,
    )
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == artifact_id

    second = identity_client.post(
        f"/api/v1/marketing-tasks/{task_id}/artifacts/{artifact_id}/versions",
        headers={**headers, "Idempotency-Key": "content-version-create"},
        json={
            "expected_version": 1,
            "source_type": "manual_edit",
            "content_json": {
                "title": "Updated weekday special",
                "body": "Visit our store and enjoy the offer.",
            },
        },
    )
    assert second.status_code == 201, second.text
    second_version_id = second.json()["id"]
    assert second.json()["version_no"] == 2

    stale_review = identity_client.post(
        (
            f"/api/v1/marketing-tasks/{task_id}/artifacts/"
            f"{artifact_id}/versions/{first_version_id}/reviews"
        ),
        headers={**headers, "Idempotency-Key": "content-review-stale"},
        json={"expected_version": 1, "review_type": "copy", "decision": "approved"},
    )
    assert stale_review.status_code == 409
    assert stale_review.json()["error"]["code"] == "STALE_ARTIFACT_VERSION"

    approved = identity_client.post(
        (
            f"/api/v1/marketing-tasks/{task_id}/artifacts/"
            f"{artifact_id}/versions/{second_version_id}/reviews"
        ),
        headers={**headers, "Idempotency-Key": "content-review-approved"},
        json={"expected_version": 2, "review_type": "copy", "decision": "approved"},
    )
    assert approved.status_code == 201, approved.text
    assert approved.json()["decision"] == "approved"

    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(
                update(ArtifactVersion)
                .where(ArtifactVersion.id == second_version_id)
                .values(content_hash="f" * 64)
            )
    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(
                delete(ReviewRecord).where(ReviewRecord.id == approved.json()["id"])
            )

    artifacts = identity_client.get(
        f"/api/v1/marketing-tasks/{task_id}/artifacts",
        headers={**ORIGIN, "X-Store-ID": str(store.id)},
    )
    assert artifacts.status_code == 200, artifacts.text
    assert artifacts.json()[0]["current_version_id"] == second_version_id
    assert [version["version_no"] for version in artifacts.json()[0]["versions"]] == [1, 2]
    reviewed_version = next(
        version for version in artifacts.json()[0]["versions"]
        if version["id"] == second_version_id
    )
    assert reviewed_version["reviews"][0]["decision"] == "approved"
    assert reviewed_version["reviews"][0]["comment"] is None

    media = MediaAsset(
        id=uuid4(),
        store_id=store.id,
        object_key=f"stores/{store.id}/media/test-image.png",
        sha256="a" * 64,
        mime_type="image/png",
        byte_size=2048,
        asset_type="product_image",
        source_type="merchant_upload",
        usage_rights_status="confirmed_allowed",
        status="ready",
        created_by_user_id=user.id,
    )
    db_session.add(media)
    db_session.flush()
    image = identity_client.post(
        f"/api/v1/marketing-tasks/{task_id}/artifacts",
        headers={**headers, "Idempotency-Key": "content-image-artifact"},
        json={
            "artifact_type": "image",
            "version": {
                "source_type": "merchant_upload",
                "media_asset_id": str(media.id),
            },
        },
    )
    assert image.status_code == 201, image.text
    assert image.json()["versions"][0]["content_hash"] == "a" * 64
    assert image.json()["versions"][0]["source_refs"][-1] == {
        "type": "media_asset",
        "id": str(media.id),
    }
    assert (
        db_session.query(OutboxEvent)
        .filter(OutboxEvent.event_type == "content.artifact_version_created")
        .count()
        == 3
    )
    assert (
        db_session.query(OutboxEvent)
        .filter(OutboxEvent.event_type == "content.review_recorded")
        .count()
        == 1
    )

    restricted = MediaAsset(
        id=uuid4(),
        store_id=store.id,
        object_key=f"stores/{store.id}/media/restricted.png",
        sha256="b" * 64,
        mime_type="image/png",
        byte_size=1024,
        asset_type="product_image",
        source_type="merchant_upload",
        usage_rights_status="restricted",
        status="ready",
        created_by_user_id=user.id,
    )
    db_session.add(restricted)
    db_session.flush()
    rejected = identity_client.post(
        f"/api/v1/marketing-tasks/{task_id}/artifacts",
        headers={**headers, "Idempotency-Key": "content-image-restricted"},
        json={
            "artifact_type": "image",
            "version": {
                "source_type": "merchant_upload",
                "media_asset_id": str(restricted.id),
            },
        },
    )
    assert rejected.status_code == 422
    assert rejected.json()["error"]["code"] == "MEDIA_ASSET_NOT_USABLE"


def test_artifact_list_version_and_review_are_store_scoped(
    identity_client, db_session: Session, monkeypatch
) -> None:
    import store_operator.auth.router as auth_router

    monkeypatch.setattr(auth_router, "redis_client", FakeRedis())
    user = create_user(db_session, "content-idor@example.com")
    store_a = create_store(db_session, user)
    store_b = create_store(db_session, user)
    login = identity_client.post(
        "/api/v1/auth/login",
        json={"email": "content-idor@example.com", "password": "test-password-123"},
        headers=ORIGIN,
    )
    assert login.status_code == 200, login.text
    csrf = login.json()["csrf_token"]
    headers_a = {**ORIGIN, "X-CSRF-Token": csrf, "X-Store-ID": str(store_a.id)}
    headers_b = {**ORIGIN, "X-CSRF-Token": csrf, "X-Store-ID": str(store_b.id)}

    task = identity_client.post(
        "/api/v1/marketing-tasks",
        headers={**headers_a, "Idempotency-Key": "content-idor-task"},
        json=task_payload(),
    )
    assert task.status_code == 201, task.text
    task_id = task.json()["id"]
    artifact = identity_client.post(
        f"/api/v1/marketing-tasks/{task_id}/artifacts",
        headers={**headers_a, "Idempotency-Key": "content-idor-artifact"},
        json={
            "artifact_type": "copy",
            "version": {
                "source_type": "manual_edit",
                "content_json": {"title": "Private copy", "body": "Store A only"},
            },
        },
    )
    assert artifact.status_code == 201, artifact.text
    artifact_id = artifact.json()["id"]
    version_id = artifact.json()["current_version_id"]

    hidden_list = identity_client.get(
        f"/api/v1/marketing-tasks/{task_id}/artifacts",
        headers={"X-Store-ID": str(store_b.id)},
    )
    assert hidden_list.status_code == 404

    hidden_version_write = identity_client.post(
        f"/api/v1/marketing-tasks/{task_id}/artifacts/{artifact_id}/versions",
        headers={**headers_b, "Idempotency-Key": "content-idor-version"},
        json={
            "expected_version": 1,
            "source_type": "manual_edit",
            "content_json": {"title": "Injected", "body": "Must not be written"},
        },
    )
    assert hidden_version_write.status_code == 404

    hidden_review_write = identity_client.post(
        (
            f"/api/v1/marketing-tasks/{task_id}/artifacts/"
            f"{artifact_id}/versions/{version_id}/reviews"
        ),
        headers={**headers_b, "Idempotency-Key": "content-idor-review"},
        json={"expected_version": 1, "review_type": "copy", "decision": "approved"},
    )
    assert hidden_review_write.status_code == 404
    assert db_session.query(ArtifactVersion).filter(
        ArtifactVersion.artifact_id == artifact_id
    ).count() == 1
    assert db_session.query(ReviewRecord).filter(
        ReviewRecord.artifact_id == artifact_id
    ).count() == 0
