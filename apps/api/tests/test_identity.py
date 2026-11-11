from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import uuid4

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from store_operator.auth.context import AuthContext
from store_operator.auth.dependencies import require_store_context
from store_operator.auth.security import hash_password, session_token_verifier
from store_operator.config import settings
from store_operator.main import app
from store_operator.models.identity import (
    AuditEvent,
    AuthSession,
    PlatformAdminGrant,
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

    def mget(self, keys):
        return [
            str(self.values[key]).encode() if key in self.values else None
            for key in keys
        ]

    def incr(self, key):
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]

    def expire(self, key, seconds):
        return True

    def delete(self, *keys):
        for key in keys:
            self.values.pop(key, None)
        return len(keys)


@app.get("/_test/store-context")
def store_context_probe(
    context: Annotated[AuthContext, Depends(require_store_context)],
) -> dict[str, str | None]:
    return {
        "store_id": str(context.request_store_id),
        "role": context.role,
        "user_id": str(context.user_id),
        "capabilities": ",".join(sorted(context.capabilities)),
    }


def make_user(db: Session, email: str, password: str = "test-password-123") -> User:
    user = User(
        id=uuid4(),
        email_normalized=email.casefold(),
        password_hash=hash_password(password),
        status="active",
    )
    db.add(user)
    db.flush()
    return user


def make_store(db: Session, name: str, user: User, role: str = "owner") -> Store:
    store = Store(id=uuid4(), name=name, timezone="Asia/Tokyo", status="active")
    db.add(store)
    db.flush()
    db.add(
        StoreMembership(
            id=uuid4(),
            store_id=store.id,
            user_id=user.id,
            role=role,
            status="active",
            joined_at=datetime.now(UTC),
        )
    )
    db.flush()
    return store


def test_login_rate_limit_atomically_reserves_ip_and_account_buckets(monkeypatch):
    import store_operator.auth.router as auth_router
    from store_operator.auth.errors import ApiError

    redis = FakeRedis()
    monkeypatch.setattr(auth_router, "redis_client", redis)
    monkeypatch.setattr(auth_router.settings, "auth_login_max_attempts", 2)
    keys = ("ip-bucket", "account-bucket")

    auth_router._consume_login_attempt(keys)
    auth_router._consume_login_attempt(keys)
    with pytest.raises(ApiError) as exc_info:
        auth_router._consume_login_attempt(keys)

    assert exc_info.value.status_code == 429
    assert redis.values == {"ip-bucket": 3, "account-bucket": 3}


def fake_redis(monkeypatch):
    import store_operator.auth.router as auth_router

    redis = FakeRedis()
    monkeypatch.setattr(auth_router, "redis_client", redis)
    return redis


def login(client: TestClient, email: str, password: str = "test-password-123") -> dict:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
        headers=ORIGIN,
    )
    assert response.status_code == 200, response.text
    return response.json()


def csrf_for(client: TestClient) -> str:
    response = client.post("/api/v1/auth/csrf", headers=ORIGIN)
    assert response.status_code == 200
    return response.json()["csrf_token"]


def test_login_cookie_csrf_and_me(identity_client, db_session, monkeypatch):
    fake_redis(monkeypatch)
    user = make_user(db_session, "owner@example.com")
    store = make_store(db_session, "Store A", user)

    response = identity_client.post(
        "/api/v1/auth/login",
        json={"email": " OWNER@example.com ", "password": "test-password-123"},
        headers=ORIGIN,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["user"]["id"] == str(user.id)
    assert payload["csrf_token"]
    cookie = response.headers["set-cookie"]
    assert "__Host-ai_store_session=" in cookie
    assert "Secure" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Path=/" in cookie
    assert "Domain=" not in cookie

    me = identity_client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["active_store"] is None

    stores = identity_client.get("/api/v1/me/stores")
    assert stores.status_code == 200
    assert stores.json()["items"] == [
        {"id": str(store.id), "name": "Store A", "role": "owner"}
    ]

    switched = identity_client.post(
        "/api/v1/session/active-store",
        json={"store_id": str(store.id)},
        headers={**ORIGIN, "X-CSRF-Token": payload["csrf_token"]},
    )
    assert switched.status_code == 200
    assert switched.json()["active_store"]["id"] == str(store.id)
    assert identity_client.get("/api/v1/auth/me").json()["active_store"]["id"] == str(store.id)


def test_csrf_and_origin_are_required_for_store_switch(identity_client, db_session, monkeypatch):
    fake_redis(monkeypatch)
    user = make_user(db_session, "csrf@example.com")
    store = make_store(db_session, "CSRF Store", user)
    payload = login(identity_client, "csrf@example.com")

    missing = identity_client.post(
        "/api/v1/session/active-store",
        json={"store_id": str(store.id)},
        headers=ORIGIN,
    )
    assert missing.status_code == 403
    assert missing.json()["error"]["code"] == "CSRF_INVALID"

    wrong_origin = identity_client.post(
        "/api/v1/session/active-store",
        json={"store_id": str(store.id)},
        headers={"Origin": "https://attacker.example", "X-CSRF-Token": payload["csrf_token"]},
    )
    assert wrong_origin.status_code == 403
    assert wrong_origin.json()["error"]["code"] == "CSRF_INVALID"


def test_store_selector_is_request_scoped_and_never_authorizes_by_active_store(
    identity_client, db_session, monkeypatch
):
    fake_redis(monkeypatch)
    user = make_user(db_session, "scope@example.com")
    store_a = make_store(db_session, "Store A", user)
    outsider = make_user(db_session, "outsider@example.com")
    store_b = make_store(db_session, "Store B", outsider)
    login(identity_client, "scope@example.com")

    missing = identity_client.get("/_test/store-context")
    assert missing.status_code == 400
    assert missing.json()["error"]["code"] == "STORE_CONTEXT_REQUIRED"

    allowed = identity_client.get(
        "/_test/store-context", headers={"X-Store-ID": str(store_a.id)}
    )
    assert allowed.status_code == 200
    assert allowed.json()["store_id"] == str(store_a.id)
    assert allowed.json()["role"] == "owner"

    raw_cookie = identity_client.cookies.get("__Host-ai_store_session")
    from store_operator.config import settings

    auth_session = db_session.scalar(
        select(AuthSession).where(
            AuthSession.token_hash == session_token_verifier(
                raw_cookie, settings.session_token_pepper
            )
        )
    )
    assert auth_session is not None
    auth_session.active_store_id = store_b.id
    db_session.commit()

    denied = identity_client.get(
        "/_test/store-context", headers={"X-Store-ID": str(store_b.id)}
    )
    assert denied.status_code == 404
    assert denied.json()["error"]["code"] == "STORE_NOT_FOUND"


def test_platform_admin_only_can_manage_members_and_last_owner_is_protected(
    identity_client, db_session, monkeypatch
):
    fake_redis(monkeypatch)
    owner = make_user(db_session, "owner2@example.com")
    store = make_store(db_session, "Managed Store", owner)
    admin = make_user(db_session, "admin@example.com")
    db_session.add(
        PlatformAdminGrant(
            id=uuid4(),
            user_id=admin.id,
            status="active",
            reason_code="bootstrap-test",
        )
    )
    db_session.flush()

    login(identity_client, "owner2@example.com")
    forbidden = identity_client.get(f"/api/v1/admin/stores/{store.id}/members")
    assert forbidden.status_code == 403

    identity_client.cookies.clear()
    login(identity_client, "admin@example.com")
    members = identity_client.get(f"/api/v1/admin/stores/{store.id}/members")
    assert members.status_code == 200
    assert len(members.json()) == 1
    # A platform-admin grant does not create a StoreMembership or bypass store authorization.
    store_content = identity_client.get(
        "/_test/store-context", headers={"X-Store-ID": str(store.id)}
    )
    assert store_content.status_code == 404
    membership_id = members.json()[0]["membership_id"]

    last_owner = identity_client.patch(
        f"/api/v1/admin/stores/{store.id}/members/{membership_id}",
        json={"role": "member"},
        headers={**ORIGIN, "X-CSRF-Token": csrf_for(identity_client)},
    )
    assert last_owner.status_code == 409
    assert last_owner.json()["error"]["code"] == "LAST_OWNER_REQUIRED"


def test_member_removal_takes_effect_on_the_next_request(
    identity_client, db_session, monkeypatch
):
    fake_redis(monkeypatch)
    owner = make_user(db_session, "owner3@example.com")
    member = make_user(db_session, "member@example.com")
    store = make_store(db_session, "Revocation Store", owner)
    membership = StoreMembership(
        id=uuid4(),
        store_id=store.id,
        user_id=member.id,
        role="member",
        status="active",
        joined_at=datetime.now(UTC),
    )
    admin = make_user(db_session, "admin2@example.com")
    db_session.add(membership)
    db_session.add(
        PlatformAdminGrant(id=uuid4(), user_id=admin.id, status="active", reason_code="test")
    )
    db_session.flush()

    member_client = TestClient(app, base_url="https://testserver")
    login(member_client, "member@example.com")
    login(identity_client, "admin2@example.com")
    removed = identity_client.patch(
        f"/api/v1/admin/stores/{store.id}/members/{membership.id}",
        json={"status": "removed"},
        headers={**ORIGIN, "X-CSRF-Token": csrf_for(identity_client)},
    )
    assert removed.status_code == 200
    denied = member_client.get(
        "/_test/store-context", headers={"X-Store-ID": str(store.id)}
    )
    assert denied.status_code == 404
    member_client.close()


def test_logout_all_revokes_all_existing_sessions(identity_client, db_session, monkeypatch):
    fake_redis(monkeypatch)
    user = make_user(db_session, "logout-all@example.com")
    make_store(db_session, "Logout Store", user)
    payload = login(identity_client, "logout-all@example.com")
    response = identity_client.post(
        "/api/v1/auth/logout-all",
        json={"password": "test-password-123"},
        headers={**ORIGIN, "X-CSRF-Token": payload["csrf_token"]},
    )
    assert response.status_code == 204
    assert identity_client.get("/api/v1/auth/me").status_code == 401


def test_invalid_credentials_are_generic_and_rate_limited(identity_client, db_session, monkeypatch):
    fake_redis(monkeypatch)
    make_user(db_session, "known@example.com")

    unknown = identity_client.post(
        "/api/v1/auth/login",
        json={"email": "missing@example.com", "password": "wrong-password"},
        headers=ORIGIN,
    )
    wrong = identity_client.post(
        "/api/v1/auth/login",
        json={"email": "known@example.com", "password": "wrong-password"},
        headers=ORIGIN,
    )
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["error"]["code"] == wrong.json()["error"]["code"] == "INVALID_CREDENTIALS"
    assert unknown.json()["error"]["message"] == wrong.json()["error"]["message"]

    for _ in range(8):
        identity_client.post(
            "/api/v1/auth/login",
            json={"email": "known@example.com", "password": "wrong-password"},
            headers=ORIGIN,
        )
    limited = identity_client.post(
        "/api/v1/auth/login",
        json={"email": "known@example.com", "password": "wrong-password"},
        headers=ORIGIN,
    )
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "RATE_LIMITED"


def test_audit_events_are_append_only(identity_client, db_session, monkeypatch):
    fake_redis(monkeypatch)
    user = make_user(db_session, "audit@example.com")
    make_store(db_session, "Audit Store", user)
    login(identity_client, "audit@example.com")
    event = db_session.scalar(select(AuditEvent).limit(1))
    assert event is not None
    event.action = "tampered"
    with pytest.raises(DBAPIError):
        db_session.flush()
    db_session.rollback()



def test_expired_session_is_rejected_and_cookie_is_cleared(
    identity_client, db_session, monkeypatch
):
    fake_redis(monkeypatch)
    user = make_user(db_session, "expired@example.com")
    make_store(db_session, "Expired Store", user)
    login(identity_client, "expired@example.com")
    raw_cookie = identity_client.cookies.get("__Host-ai_store_session")
    from store_operator.config import settings

    auth_session = db_session.scalar(
        select(AuthSession).where(
            AuthSession.token_hash == session_token_verifier(
                raw_cookie, settings.session_token_pepper
            )
        )
    )
    assert auth_session is not None
    auth_session.idle_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.commit()

    response = identity_client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"
    assert "Max-Age=0" in response.headers.get("set-cookie", "")


def test_logout_revokes_session_and_is_idempotent(identity_client, db_session, monkeypatch):
    fake_redis(monkeypatch)
    user = make_user(db_session, "logout@example.com")
    make_store(db_session, "Logout Store", user)
    payload = login(identity_client, "logout@example.com")

    logged_out = identity_client.post(
        "/api/v1/auth/logout",
        headers={**ORIGIN, "X-CSRF-Token": payload["csrf_token"]},
    )
    assert logged_out.status_code == 204
    assert identity_client.get("/api/v1/auth/me").status_code == 401

    second_logout = identity_client.post("/api/v1/auth/logout", headers=ORIGIN)
    assert second_logout.status_code == 204


def test_two_tabs_use_their_own_store_selector(identity_client, db_session, monkeypatch):
    fake_redis(monkeypatch)
    user = make_user(db_session, "multistore@example.com")
    store_a = make_store(db_session, "Tab A", user)
    store_b = make_store(db_session, "Tab B", user, role="member")
    login(identity_client, "multistore@example.com")

    tab_a = identity_client.get(
        "/_test/store-context", headers={"X-Store-ID": str(store_a.id)}
    )
    tab_b = identity_client.get(
        "/_test/store-context", headers={"X-Store-ID": str(store_b.id)}
    )
    assert tab_a.status_code == tab_b.status_code == 200
    assert tab_a.json()["store_id"] == str(store_a.id)
    assert tab_a.json()["role"] == "owner"
    assert tab_b.json()["store_id"] == str(store_b.id)
    assert tab_b.json()["role"] == "member"
    assert tab_a.json()["capabilities"] == tab_b.json()["capabilities"] == "store.business.use"


def test_password_change_rotates_current_session_and_revokes_other_sessions(
    identity_client, db_session, monkeypatch
):
    fake_redis(monkeypatch)
    user = make_user(db_session, "password-change@example.com")
    store = make_store(db_session, "Password Change Store", user)
    first_login = login(identity_client, "password-change@example.com")
    other_client = TestClient(app, base_url="https://testserver")
    login(other_client, "password-change@example.com")

    old_token = identity_client.cookies.get("__Host-ai_store_session")
    assert old_token
    old_verifier = session_token_verifier(old_token, settings.session_token_pepper)

    changed = identity_client.post(
        "/api/v1/auth/password/change",
        json={
            "current_password": "test-password-123",
            "new_password": "new-secure-password-456",
        },
        headers={**ORIGIN, "X-CSRF-Token": first_login["csrf_token"]},
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["csrf_token"]
    assert identity_client.get("/api/v1/auth/me").status_code == 200
    assert identity_client.get("/api/v1/auth/me").json()["active_store"]["id"] == str(store.id)

    revoked = db_session.scalar(
        select(AuthSession).where(AuthSession.token_hash == old_verifier)
    )
    assert revoked is not None
    assert revoked.revoked_at is not None
    assert revoked.revoke_reason == "password_changed"
    assert other_client.get("/api/v1/auth/me").status_code == 401

    old_password_login = other_client.post(
        "/api/v1/auth/login",
        json={"email": "password-change@example.com", "password": "test-password-123"},
        headers=ORIGIN,
    )
    assert old_password_login.status_code == 401
    new_password_login = other_client.post(
        "/api/v1/auth/login",
        json={"email": "password-change@example.com", "password": "new-secure-password-456"},
        headers=ORIGIN,
    )
    assert new_password_login.status_code == 200
    other_client.close()


def test_password_change_requires_current_password_without_revoking_session(
    identity_client, db_session, monkeypatch
):
    fake_redis(monkeypatch)
    make_user(db_session, "password-change-invalid@example.com")
    first_login = login(identity_client, "password-change-invalid@example.com")

    changed = identity_client.post(
        "/api/v1/auth/password/change",
        json={
            "current_password": "incorrect-current-password",
            "new_password": "new-secure-password-456",
        },
        headers={**ORIGIN, "X-CSRF-Token": first_login["csrf_token"]},
    )
    assert changed.status_code == 401
    assert changed.json()["error"]["code"] == "REAUTHENTICATION_REQUIRED"
    assert identity_client.get("/api/v1/auth/me").status_code == 200
