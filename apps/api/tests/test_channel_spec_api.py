from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.orm import Session

from store_operator.auth.security import hash_password
from store_operator.models import Store, StoreMembership, User


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
