from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy.orm import Session

from store_operator.auth.security import hash_password
from store_operator.models import (
    AuditEvent,
    ChannelAccount,
    ChannelCapabilitySnapshot,
    ChannelSpec,
    ChannelSpecVersion,
    PlatformAdminGrant,
    Store,
    StoreMembership,
    User,
)


class FakeRedis:
    def __init__(self):
        self.values: dict[str, int] = {}

    def eval(self, script, numkeys, *args):
        keys = args[:numkeys]
        result = []
        for key in keys:
            self.values[key] = self.values.get(key, 0) + 1
            result.append(self.values[key])
        return result

    def incr(self, key):
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]

    def expire(self, key, seconds):
        return True

    def delete(self, *keys):
        for key in keys:
            self.values.pop(key, None)
        return len(keys)


def test_channel_specs_are_store_authenticated_and_unverified_by_default(
    identity_client, db_session: Session, monkeypatch
) -> None:
    import store_operator.auth.router as auth_router

    monkeypatch.setattr(auth_router, "redis_client", FakeRedis())
    user = User(
        id=uuid4(),
        email_normalized="channel-spec@example.com",
        password_hash=hash_password("test-password-123"),
        status="active",
    )
    store = Store(
        id=uuid4(),
        name="Channel Spec Store",
        timezone="Asia/Tokyo",
        status="active",
    )
    db_session.add_all([user, store])
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
    db_session.flush()

    login = identity_client.post(
        "/api/v1/auth/login",
        json={"email": "channel-spec@example.com", "password": "test-password-123"},
        headers={"Origin": "http://localhost:5173"},
    )
    assert login.status_code == 200, login.text
    headers = {
        "Origin": "http://localhost:5173",
        "X-CSRF-Token": login.json()["csrf_token"],
        "X-Store-ID": str(store.id),
    }

    specs = identity_client.get("/api/v1/channels/specs", headers=headers)
    assert specs.status_code == 200, specs.text
    douyin = next(item for item in specs.json() if item["channel_key"] == "douyin")
    assert douyin["current_version"]["spec_version"] == 1
    assert douyin["current_version"]["verification_status"] == "pending_verification"
    assert douyin["current_version"]["draft_supported"] is False
    assert douyin["current_version"]["publish_supported"] is False

    versions = identity_client.get(
        "/api/v1/channels/specs/douyin/versions",
        headers=headers,
    )
    assert versions.status_code == 200, versions.text
    assert versions.json()[0]["id"] == douyin["current_version"]["id"]

    missing = identity_client.get(
        "/api/v1/channels/specs/not-a-channel/versions",
        headers=headers,
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "CHANNEL_SPEC_NOT_FOUND"

    spec_version = (
        db_session.query(ChannelSpecVersion)
        .join(ChannelSpec, ChannelSpec.id == ChannelSpecVersion.channel_spec_id)
        .filter(ChannelSpec.channel_key == "douyin")
        .one()
    )
    account = ChannelAccount(
        id=uuid4(),
        store_id=store.id,
        provider="douyin",
        external_account_id="open-id-1",
        access_token_secret_ref="secret://access",
        refresh_token_secret_ref="secret://refresh",
        access_token_expires_at=datetime.now(UTC) + timedelta(days=1),
        connected_by_user_id=user.id,
        status="active",
    )
    db_session.add(account)
    db_session.flush()
    db_session.add(
        ChannelCapabilitySnapshot(
            id=uuid4(),
            store_id=store.id,
            channel_account_id=account.id,
            channel_spec_version_id=spec_version.id,
            capability_key="publish_image_text",
            support_status="pending_verification",
            checked_at=datetime.now(UTC),
        )
    )
    db_session.flush()
    capabilities = identity_client.get(
        f"/api/v1/channels/douyin/accounts/{account.id}/capabilities",
        headers=headers,
    )
    assert capabilities.status_code == 200, capabilities.text
    assert capabilities.json()[0]["capability_key"] == "publish_image_text"
    assert capabilities.json()[0]["support_status"] == "pending_verification"


def test_platform_admin_publishes_a_new_verified_channel_spec_version(
    identity_client, db_session: Session, monkeypatch
) -> None:
    import store_operator.auth.router as auth_router

    monkeypatch.setattr(auth_router, "redis_client", FakeRedis())
    user = User(
        id=uuid4(),
        email_normalized="channel-spec-admin@example.com",
        password_hash=hash_password("test-password-123"),
        status="active",
    )
    db_session.add(user)
    db_session.flush()
    db_session.add(
        PlatformAdminGrant(
            id=uuid4(),
            user_id=user.id,
            status="active",
            reason_code="test_fixture",
        )
    )
    db_session.flush()
    spec = db_session.query(ChannelSpec).filter_by(channel_key="douyin").one()
    previous_version_id = spec.current_version_id

    login = identity_client.post(
        "/api/v1/auth/login",
        json={"email": "channel-spec-admin@example.com", "password": "test-password-123"},
        headers={"Origin": "http://localhost:5173"},
    )
    assert login.status_code == 200, login.text
    headers = {
        "Origin": "http://localhost:5173",
        "X-CSRF-Token": login.json()["csrf_token"],
    }
    response = identity_client.post(
        "/api/v1/admin/channel-specs/douyin/versions",
        headers={**headers, "Idempotency-Key": "publish-douyin-spec-v2"},
        json={
            "expected_current_version_id": str(previous_version_id),
            "source_document_ref": "https://open.douyin.com/platform/resource/docs",
            "text_constraints": {"max_length": 2000},
            "media_constraints": {"max_images": 9},
            "hashtag_constraints": {"max_count": 10},
            "link_constraints": {},
            "schedule_constraints": {},
            "draft_supported": True,
            "publish_supported": False,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["spec_version"] == 2
    assert response.json()["verification_status"] == "verified"
    assert response.json()["draft_supported"] is True
    assert response.json()["publish_supported"] is False
    db_session.refresh(spec)
    assert str(spec.current_version_id) == response.json()["id"]
    audit = db_session.query(AuditEvent).filter_by(action="channel.spec_version.published").one()
    assert str(audit.target_id) == response.json()["id"]

    stale = identity_client.post(
        "/api/v1/admin/channel-specs/douyin/versions",
        headers={**headers, "Idempotency-Key": "publish-douyin-spec-stale"},
        json={
            "expected_current_version_id": str(previous_version_id),
            "source_document_ref": "https://open.douyin.com/platform/resource/docs",
        },
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "STALE_CHANNEL_SPEC_VERSION"

    untrusted_source = identity_client.post(
        "/api/v1/admin/channel-specs/douyin/versions",
        headers={**headers, "Idempotency-Key": "publish-douyin-spec-untrusted-source"},
        json={
            "expected_current_version_id": response.json()["id"],
            "source_document_ref": "https://open.douyin.com.attacker.example/docs",
        },
    )
    assert untrusted_source.status_code == 422
    assert untrusted_source.json()["error"]["code"] == "CHANNEL_SPEC_SOURCE_REQUIRED"



def test_channel_account_capabilities_are_store_scoped(
    identity_client, db_session: Session, monkeypatch
) -> None:
    import store_operator.auth.router as auth_router

    monkeypatch.setattr(auth_router, "redis_client", FakeRedis())
    user = User(
        id=uuid4(),
        email_normalized="channel-idor@example.com",
        password_hash=hash_password("test-password-123"),
        status="active",
    )
    store_a = Store(id=uuid4(), name="Channel A", timezone="Asia/Tokyo", status="active")
    store_b = Store(id=uuid4(), name="Channel B", timezone="Asia/Tokyo", status="active")
    db_session.add_all([user, store_a, store_b])
    db_session.flush()
    db_session.add_all(
        [
            StoreMembership(
                id=uuid4(), store_id=store_a.id, user_id=user.id,
                role="owner", status="active", joined_at=datetime.now(UTC),
            ),
            StoreMembership(
                id=uuid4(), store_id=store_b.id, user_id=user.id,
                role="owner", status="active", joined_at=datetime.now(UTC),
            ),
        ]
    )
    db_session.flush()

    login = identity_client.post(
        "/api/v1/auth/login",
        json={"email": "channel-idor@example.com", "password": "test-password-123"},
        headers={"Origin": "http://localhost:5173"},
    )
    assert login.status_code == 200, login.text
    headers_a = {
        "Origin": "http://localhost:5173",
        "X-CSRF-Token": login.json()["csrf_token"],
        "X-Store-ID": str(store_a.id),
    }
    headers_b = {**headers_a, "X-Store-ID": str(store_b.id)}

    spec_version = (
        db_session.query(ChannelSpecVersion)
        .join(ChannelSpec, ChannelSpec.id == ChannelSpecVersion.channel_spec_id)
        .filter(ChannelSpec.channel_key == "douyin")
        .one()
    )
    account = ChannelAccount(
        id=uuid4(),
        store_id=store_a.id,
        provider="douyin",
        external_account_id="store-a-open-id",
        access_token_secret_ref="secret://store-a/access",
        refresh_token_secret_ref="secret://store-a/refresh",
        access_token_expires_at=datetime.now(UTC) + timedelta(days=1),
        connected_by_user_id=user.id,
        status="active",
    )
    db_session.add(account)
    db_session.flush()
    db_session.add(
        ChannelCapabilitySnapshot(
            id=uuid4(),
            store_id=store_a.id,
            channel_account_id=account.id,
            channel_spec_version_id=spec_version.id,
            capability_key="publish_image_text",
            support_status="pending_verification",
            checked_at=datetime.now(UTC),
        )
    )
    db_session.flush()

    own = identity_client.get(
        f"/api/v1/channels/douyin/accounts/{account.id}/capabilities",
        headers=headers_a,
    )
    assert own.status_code == 200, own.text

    hidden = identity_client.get(
        f"/api/v1/channels/douyin/accounts/{account.id}/capabilities",
        headers=headers_b,
    )
    assert hidden.status_code == 404
    assert "store-a-open-id" not in hidden.text
