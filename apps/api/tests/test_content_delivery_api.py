import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from store_operator.auth.security import hash_password
from store_operator.models import (
    ArtifactVersion,
    Job,
    MarketingTask,
    MediaAsset,
    OutboxEvent,
    RequirementSnapshot,
    ReviewRecord,
    Store,
    StoreMembership,
    StrategySnapshot,
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


def image_task_payload() -> dict[str, object]:
    return {
        "task_type": "full_marketing",
        "title": "Content image API test",
        "requirement_draft": {"goal": "Create an approved store image"},
        "task_options": {
            "includes_copy": True,
            "includes_image": True,
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

    detail = identity_client.get(
        f"/api/v1/marketing-tasks/{task_id}",
        headers={**ORIGIN, "X-Store-ID": str(store.id)},
    )
    assert detail.status_code == 200, detail.text
    copy_step = next(
        step
        for step in detail.json()["steps"]
        if step["step_key"] == "copy_production_review"
    )
    assert copy_step["status"] == "succeeded"
    assert copy_step["output_refs"] == [{
        "type": "artifact_version",
        "artifact_id": artifact_id,
        "artifact_version_id": second_version_id,
    }]

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



def test_artifact_version_id_substitution_across_stores_is_rejected(
    identity_client, db_session: Session, monkeypatch
) -> None:
    import store_operator.auth.router as auth_router

    monkeypatch.setattr(auth_router, "redis_client", FakeRedis())
    user = create_user(db_session, "content-version-swap@example.com")
    store_a = create_store(db_session, user)
    store_b = create_store(db_session, user)
    login = identity_client.post(
        "/api/v1/auth/login",
        json={"email": "content-version-swap@example.com", "password": "test-password-123"},
        headers=ORIGIN,
    )
    assert login.status_code == 200, login.text
    csrf = login.json()["csrf_token"]
    headers_a = {**ORIGIN, "X-CSRF-Token": csrf, "X-Store-ID": str(store_a.id)}
    headers_b = {**ORIGIN, "X-CSRF-Token": csrf, "X-Store-ID": str(store_b.id)}

    task_ids: list[str] = []
    artifact_ids: list[str] = []
    version_ids: list[str] = []
    for store_headers, key in ((headers_a, "store-a"), (headers_b, "store-b")):
        task = identity_client.post(
            "/api/v1/marketing-tasks",
            headers={**store_headers, "Idempotency-Key": f"version-swap-task-{key}"},
            json=task_payload(),
        )
        assert task.status_code == 201, task.text
        task_id = task.json()["id"]
        artifact = identity_client.post(
            f"/api/v1/marketing-tasks/{task_id}/artifacts",
            headers={**store_headers, "Idempotency-Key": f"version-swap-artifact-{key}"},
            json={
                "artifact_type": "copy",
                "version": {
                    "source_type": "manual_edit",
                    "content_json": {"title": key, "body": "Private store copy"},
                },
            },
        )
        assert artifact.status_code == 201, artifact.text
        task_ids.append(task_id)
        artifact_ids.append(artifact.json()["id"])
        version_ids.append(artifact.json()["current_version_id"])

    version_count = db_session.query(ArtifactVersion).count()
    review_count = db_session.query(ReviewRecord).count()
    outbox_count = db_session.query(OutboxEvent).filter(
        OutboxEvent.event_type == "content.review_recorded"
    ).count()

    # Keep Store B's task and artifact IDs, but substitute Store A's version ID.
    swapped_version = identity_client.post(
        (
            f"/api/v1/marketing-tasks/{task_ids[1]}/artifacts/"
            f"{artifact_ids[1]}/versions/{version_ids[0]}/reviews"
        ),
        headers={**headers_b, "Idempotency-Key": "version-swap-review"},
        json={"expected_version": 1, "review_type": "copy", "decision": "approved"},
    )
    assert swapped_version.status_code == 404, swapped_version.text

    # Also reject an artifact ID and version ID from Store A under Store B's task.
    swapped_artifact = identity_client.post(
        (
            f"/api/v1/marketing-tasks/{task_ids[1]}/artifacts/"
            f"{artifact_ids[0]}/versions/{version_ids[0]}/reviews"
        ),
        headers={**headers_b, "Idempotency-Key": "artifact-swap-review"},
        json={"expected_version": 1, "review_type": "copy", "decision": "approved"},
    )
    assert swapped_artifact.status_code == 404, swapped_artifact.text
    assert db_session.query(ArtifactVersion).count() == version_count
    assert db_session.query(ReviewRecord).count() == review_count
    assert db_session.query(OutboxEvent).filter(
        OutboxEvent.event_type == "content.review_recorded"
    ).count() == outbox_count


def _image_review_fixture(
    identity_client, db_session: Session, monkeypatch, email: str
):
    import store_operator.auth.router as auth_router

    monkeypatch.setattr(auth_router, "redis_client", FakeRedis())
    user = create_user(db_session, email)
    store = create_store(db_session, user)
    login = identity_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "test-password-123"},
        headers=ORIGIN,
    )
    assert login.status_code == 200, login.text
    headers = {
        **ORIGIN,
        "X-CSRF-Token": login.json()["csrf_token"],
        "X-Store-ID": str(store.id),
    }
    task = identity_client.post(
        "/api/v1/marketing-tasks",
        headers={**headers, "Idempotency-Key": f"{email}-image-task"},
        json=image_task_payload(),
    )
    assert task.status_code == 201, task.text
    task_id = task.json()["id"]
    media = MediaAsset(
        id=uuid4(),
        store_id=store.id,
        object_key=f"stores/{store.id}/media/{email}.png",
        sha256="c" * 64,
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
    artifact = identity_client.post(
        f"/api/v1/marketing-tasks/{task_id}/artifacts",
        headers={**headers, "Idempotency-Key": f"{email}-image-artifact"},
        json={
            "artifact_type": "image",
            "version": {
                "source_type": "merchant_upload",
                "media_asset_id": str(media.id),
            },
        },
    )
    assert artifact.status_code == 201, artifact.text
    return (
        user,
        store,
        headers,
        task_id,
        artifact.json()["id"],
        artifact.json()["current_version_id"],
    )


def test_image_approval_completes_image_production_step(
    identity_client, db_session: Session, monkeypatch
) -> None:
    _, _, headers, task_id, artifact_id, version_id = _image_review_fixture(
        identity_client, db_session, monkeypatch, "content-image-approve@example.com"
    )

    approved = identity_client.post(
        (
            f"/api/v1/marketing-tasks/{task_id}/artifacts/"
            f"{artifact_id}/versions/{version_id}/reviews"
        ),
        headers={**headers, "Idempotency-Key": "image-approve"},
        json={"expected_version": 1, "review_type": "image", "decision": "approved"},
    )
    assert approved.status_code == 201, approved.text
    detail = identity_client.get(
        f"/api/v1/marketing-tasks/{task_id}",
        headers={**ORIGIN, "X-Store-ID": headers["X-Store-ID"]},
    )
    assert detail.status_code == 200, detail.text
    image_step = next(
        step
        for step in detail.json()["steps"]
        if step["step_key"] == "image_production_review"
    )
    assert image_step["status"] == "succeeded"
    assert image_step["block_code"] is None
    assert image_step["output_refs"] == [{
        "type": "artifact_version",
        "artifact_id": artifact_id,
        "artifact_version_id": version_id,
    }]


def test_image_revision_request_dispatches_regeneration_job(
    identity_client, db_session: Session, monkeypatch
) -> None:
    (
        user,
        store,
        headers,
        task_id,
        artifact_id,
        version_id,
    ) = _image_review_fixture(
        identity_client, db_session, monkeypatch, "content-image-revise@example.com"
    )
    task_row = db_session.get(MarketingTask, UUID(task_id))
    requirement = RequirementSnapshot(
        id=uuid4(),
        store_id=store.id,
        task_id=task_row.id,
        snapshot_no=1,
        payload_json={"requirement": {"goal": "Image revision"}},
        content_fingerprint="a" * 64,
        confirmed_by_user_id=user.id,
        confirmed_at=datetime.now(UTC),
    )
    db_session.add(requirement)
    db_session.flush()
    strategy = StrategySnapshot(
        id=uuid4(),
        store_id=store.id,
        task_id=task_row.id,
        requirement_snapshot_id=requirement.id,
        snapshot_no=1,
        payload_json={"strategy": {"strategy_summary": "Image revision"}},
        content_fingerprint="b" * 64,
        confirmed_by_user_id=user.id,
        confirmed_at=datetime.now(UTC),
    )
    db_session.add(strategy)
    db_session.flush()
    task_row.current_requirement_snapshot_id = requirement.id
    task_row.current_strategy_snapshot_id = strategy.id
    db_session.commit()

    revision = identity_client.post(
        (
            f"/api/v1/marketing-tasks/{task_id}/artifacts/"
            f"{artifact_id}/versions/{version_id}/reviews"
        ),
        headers={**headers, "Idempotency-Key": "image-revision"},
        json={
            "expected_version": 1,
            "review_type": "image",
            "decision": "revision_requested",
            "comment": "请去掉右下角水印并调整构图",
        },
    )
    assert revision.status_code == 201, revision.text
    job_id = revision.json()["image_revision_job_id"]
    assert isinstance(job_id, str) and job_id

    db_session.expire_all()
    job = db_session.get(Job, UUID(job_id))
    assert job is not None
    assert job.job_type == "marketing_task.generate_image"
    assert job.marketing_task_id == task_row.id
    assert job.payload_ref["revision_instruction"] == "请去掉右下角水印并调整构图"
    detail = identity_client.get(
        f"/api/v1/marketing-tasks/{task_id}",
        headers={**ORIGIN, "X-Store-ID": headers["X-Store-ID"]},
    )
    image_step = next(
        step
        for step in detail.json()["steps"]
        if step["step_key"] == "image_production_review"
    )
    assert image_step["status"] == "running"
