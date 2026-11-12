from datetime import UTC, datetime
from uuid import UUID, uuid4

from store_operator.auth.security import hash_password
from store_operator.models import MediaAsset, QualityReport, Store, StoreMembership, User

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


def test_channel_content_requires_approved_current_copy_and_is_idempotent(
    identity_client, db_session, monkeypatch
) -> None:
    import store_operator.auth.router as auth_router

    monkeypatch.setattr(auth_router, "redis_client", FakeRedis())
    user = User(
        id=uuid4(),
        email_normalized="channel-content@example.com",
        password_hash=hash_password("test-password-123"),
        status="active",
    )
    db_session.add(user)
    db_session.flush()
    store = Store(
        id=uuid4(),
        name="Channel Content Test",
        timezone="Asia/Tokyo",
        status="active",
    )
    db_session.add(store)
    db_session.flush()
    db_session.add(
        StoreMembership(
            id=uuid4(),
            store_id=store.id,
            user_id=user.id,
            role="owner",
            status="active",
            joined_at=datetime.now(UTC),
        )
    )
    db_session.commit()

    login = identity_client.post(
        "/api/v1/auth/login",
        json={"email": "channel-content@example.com", "password": "test-password-123"},
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
        headers={**headers, "Idempotency-Key": "channel-content-task"},
        json={
            "task_type": "copy_only",
            "title": "Channel content test",
            "requirement_draft": {"goal": "Create a channel post"},
            "task_options": {
                "includes_copy": True,
                "includes_image": False,
                "opportunity_applicable": False,
                "selected_channel_keys": [],
                "requires_external_delivery": False,
            },
        },
    )
    assert task.status_code == 201, task.text
    task_id = task.json()["id"]

    artifact = identity_client.post(
        f"/api/v1/marketing-tasks/{task_id}/artifacts",
        headers={**headers, "Idempotency-Key": "channel-copy-artifact"},
        json={
            "artifact_type": "copy",
            "version": {
                "source_type": "manual_edit",
                "content_json": {
                    "title": "Lunch offer",
                    "body": "Visit us for lunch this week.",
                },
            },
        },
    )
    assert artifact.status_code == 201, artifact.text
    artifact_id = artifact.json()["id"]
    version_id = artifact.json()["current_version_id"]
    content_url = f"/api/v1/marketing-tasks/{task_id}/channel-contents"
    spec_version = (
        db_session.query(ChannelSpecVersion)
        .join(ChannelSpec, ChannelSpec.id == ChannelSpecVersion.channel_spec_id)
        .filter(ChannelSpec.channel_key == "douyin")
        .one()
    )
    spec_version.verification_status = "verified"
    spec_version.source_document_ref = "test-fixture://verified-channel-spec"
    db_session.flush()
    content_payload = {
        "channel_key": "douyin",
        "copy_version_id": version_id,
        "channel_spec_version_id": str(
            db_session.query(ChannelSpecVersion)
            .join(ChannelSpec, ChannelSpec.id == ChannelSpecVersion.channel_spec_id)
            .filter(ChannelSpec.channel_key == "douyin")
            .one()
            .id
        ),
        "payload": {"title": "Lunch offer", "body": "Visit us for lunch this week."},
        "image_version_ids": [],
    }

    unreviewed = identity_client.post(
        content_url,
        headers={**headers, "Idempotency-Key": "channel-content-unreviewed"},
        json=content_payload,
    )
    assert unreviewed.status_code == 409, unreviewed.text
    assert unreviewed.json()["error"]["code"] == "COPY_REVIEW_REQUIRED"

    review = identity_client.post(
        (
            f"/api/v1/marketing-tasks/{task_id}/artifacts/{artifact_id}/"
            f"versions/{version_id}/reviews"
        ),
        headers={**headers, "Idempotency-Key": "channel-copy-review"},
        json={
            "expected_version": 1,
            "review_type": "copy",
            "decision": "approved",
        },
    )
    assert review.status_code == 201, review.text

    media = MediaAsset(
        id=uuid4(),
        store_id=store.id,
        object_key=f"stores/{store.id}/media/channel-image.png",
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
    image_artifact = identity_client.post(
        f"/api/v1/marketing-tasks/{task_id}/artifacts",
        headers={**headers, "Idempotency-Key": "channel-image-artifact"},
        json={
            "artifact_type": "image",
            "version": {
                "source_type": "merchant_upload",
                "media_asset_id": str(media.id),
            },
        },
    )
    assert image_artifact.status_code == 201, image_artifact.text
    image_version_id = image_artifact.json()["current_version_id"]
    image_content_payload = {
        **content_payload,
        "image_version_ids": [image_version_id],
    }
    unreviewed_image = identity_client.post(
        content_url,
        headers={**headers, "Idempotency-Key": "channel-content-unreviewed-image"},
        json=image_content_payload,
    )
    assert unreviewed_image.status_code == 409, unreviewed_image.text
    assert unreviewed_image.json()["error"]["code"] == "IMAGE_REVIEW_REQUIRED"

    image_review = identity_client.post(
        (
            f"/api/v1/marketing-tasks/{task_id}/artifacts/{image_artifact.json()['id']}/"
            f"versions/{image_version_id}/reviews"
        ),
        headers={**headers, "Idempotency-Key": "channel-image-review"},
        json={
            "expected_version": 1,
            "review_type": "image",
            "decision": "approved",
        },
    )
    assert image_review.status_code == 201, image_review.text

    image_created = identity_client.post(
        content_url,
        headers={**headers, "Idempotency-Key": "channel-content-with-image"},
        json=image_content_payload,
    )
    assert image_created.status_code == 201, image_created.text
    assert image_created.json()["image_version_ids"] == [image_version_id]

    created = identity_client.post(
        content_url,
        headers={**headers, "Idempotency-Key": "channel-content-create"},
        json=content_payload,
    )
    assert created.status_code == 201, created.text
    assert created.json()["status"] == "ready"
    assert created.json()["copy_version_id"] == version_id
    assert created.json()["image_version_ids"] == []
    assert len(created.json()["input_fingerprint"]) == 64

    replay = identity_client.post(
        content_url,
        headers={**headers, "Idempotency-Key": "channel-content-create"},
        json=content_payload,
    )
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == created.json()["id"]

    quality_url = (
        f"/api/v1/marketing-tasks/{task_id}/channel-contents/"
        f"{created.json()['id']}/quality-reports/run"
    )
    quality_payload = {
        "rule_version": "content-structure-v1",
        "expected_fingerprint": created.json()["input_fingerprint"],
    }
    quality_headers = {**headers, "Idempotency-Key": "quality-run-1"}
    quality_job = identity_client.post(
        quality_url,
        headers=quality_headers,
        json=quality_payload,
    )
    assert quality_job.status_code == 202, quality_job.text
    assert quality_job.json()["job_status"] == "queued"
    quality_replay = identity_client.post(
        quality_url,
        headers=quality_headers,
        json=quality_payload,
    )
    assert quality_replay.status_code == 202, quality_replay.text
    assert quality_replay.json()["job_id"] == quality_job.json()["job_id"]

    stale_quality = identity_client.post(
        quality_url,
        headers={**headers, "Idempotency-Key": "quality-run-stale"},
        json={**quality_payload, "expected_fingerprint": "0" * 64},
    )
    assert stale_quality.status_code == 409, stale_quality.text
    assert stale_quality.json()["error"]["code"] == "CHANNEL_CONTENT_STALE"

    unsupported_rule = identity_client.post(
        quality_url,
        headers={**headers, "Idempotency-Key": "quality-run-unsupported"},
        json={**quality_payload, "rule_version": "uninstalled-rule-v99"},
    )
    assert unsupported_rule.status_code == 422, unsupported_rule.text
    assert (
        unsupported_rule.json()["error"]["code"] == "QUALITY_RULE_VERSION_UNSUPPORTED"
    )

    needs_human_report = QualityReport(
        id=uuid4(),
        store_id=store.id,
        task_id=UUID(task_id),
        channel_content_id=UUID(created.json()["id"]),
        rule_version="content-structure-v1",
        input_fingerprint="b" * 64,
        result="needs_human",
        issues_json=[{"code": "BUSINESS_FACTS_REQUIRE_HUMAN_CHECK", "severity": "review"}],
    )
    db_session.add(needs_human_report)
    db_session.flush()
    resolution_url = (
        f"/api/v1/marketing-tasks/quality-reports/{needs_human_report.id}/resolutions"
    )
    resolution_payload = {
        "decision": "accepted",
        "reason": "Verified the promotion details against confirmed store facts.",
        "expected_fingerprint": needs_human_report.input_fingerprint,
    }
    resolution_headers = {**headers, "Idempotency-Key": "quality-resolution-1"}
    resolved = identity_client.post(
        resolution_url,
        headers=resolution_headers,
        json=resolution_payload,
    )
    assert resolved.status_code == 201, resolved.text
    assert resolved.json()["decision"] == "accepted"
    resolution_replay = identity_client.post(
        resolution_url,
        headers=resolution_headers,
        json=resolution_payload,
    )
    assert resolution_replay.status_code == 201, resolution_replay.text
    assert resolution_replay.json()["id"] == resolved.json()["id"]

    hard_fail_report = QualityReport(
        id=uuid4(),
        store_id=store.id,
        task_id=needs_human_report.task_id,
        channel_content_id=needs_human_report.channel_content_id,
        rule_version="content-structure-v1",
        input_fingerprint="c" * 64,
        result="fail",
        issues_json=[{"code": "PLACEHOLDER_TEXT", "severity": "hard"}],
    )
    db_session.add(hard_fail_report)
    db_session.flush()
    blocked_resolution = identity_client.post(
        f"/api/v1/marketing-tasks/quality-reports/{hard_fail_report.id}/resolutions",
        headers={**headers, "Idempotency-Key": "quality-resolution-hard-fail"},
        json={
            "decision": "accepted",
            "reason": "Attempted override",
            "expected_fingerprint": hard_fail_report.input_fingerprint,
        },
    )
    assert blocked_resolution.status_code == 422, blocked_resolution.text
    assert (
        blocked_resolution.json()["error"]["code"] == "QUALITY_RESOLUTION_NOT_ALLOWED"
    )

    listed = identity_client.get(content_url, headers=headers)
    assert listed.status_code == 200, listed.text
    listed_created = next(
        item for item in listed.json() if item["id"] == created.json()["id"]
    )
    listed_report = next(
        item
        for item in listed_created["quality_reports"]
        if item["id"] == str(needs_human_report.id)
    )
    assert listed_report["resolutions"][0]["decision"] == "accepted"
    assert {item["id"] for item in listed.json()} == {
        image_created.json()["id"],
        created.json()["id"],
    }
