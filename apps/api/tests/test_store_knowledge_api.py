from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.orm import Session

from store_operator.auth.security import hash_password
from store_operator.models.identity import Store, StoreMembership, User

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
        email_normalized="knowledge@example.com",
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


def test_store_profile_and_product_api_are_tenant_scoped_and_versioned(
    identity_client, db_session, monkeypatch
):
    import store_operator.auth.router as auth_router

    monkeypatch.setattr(auth_router, "redis_client", FakeRedis())
    user = create_user(db_session)
    store_a = create_store(db_session, user, "Knowledge A")
    store_b = create_store(db_session, user, "Knowledge B")

    login = identity_client.post(
        "/api/v1/auth/login",
        json={"email": "knowledge@example.com", "password": "test-password-123"},
        headers=ORIGIN,
    )
    assert login.status_code == 200, login.text
    csrf = login.json()["csrf_token"]

    headers_a = {
        **ORIGIN,
        "X-CSRF-Token": csrf,
        "X-Store-ID": str(store_a.id),
    }
    headers_b = {"X-Store-ID": str(store_b.id)}

    created_profile = identity_client.post(
        "/api/v1/store/profile",
        headers=headers_a,
        json={"display_name": "Knowledge A Shop", "city": "Tokyo"},
    )
    assert created_profile.status_code == 201, created_profile.text
    assert created_profile.json()["fact_status"] == "pending_confirmation"
    assert created_profile.json()["current_version"] == 1

    updated_profile = identity_client.patch(
        "/api/v1/store/profile",
        headers={**headers_a, "If-Match": '"1"'},
        json={"city": "Osaka"},
    )
    assert updated_profile.status_code == 200, updated_profile.text
    assert updated_profile.json()["current_version"] == 2
    assert updated_profile.json()["city"] == "Osaka"

    stale_profile = identity_client.patch(
        "/api/v1/store/profile",
        headers={**headers_a, "If-Match": '"1"'},
        json={"city": "Kyoto"},
    )
    assert stale_profile.status_code == 409
    assert stale_profile.json()["error"]["code"] == "VERSION_CONFLICT"

    created_product = identity_client.post(
        "/api/v1/store/products",
        headers=headers_a,
        json={
            "name": "Seasonal tea",
            "price_amount": "680.00",
            "currency": "JPY",
            "availability_status": "available",
        },
    )
    assert created_product.status_code == 201, created_product.text
    product = created_product.json()
    assert product["fact_status"] == "pending_confirmation"
    assert product["current_version"] == 1

    hidden_from_other_store = identity_client.get(
        f"/api/v1/store/products/{product['id']}",
        headers=headers_b,
    )
    assert hidden_from_other_store.status_code == 404
    assert hidden_from_other_store.json()["error"]["code"] == "RESOURCE_NOT_FOUND"

    updated_product = identity_client.patch(
        f"/api/v1/store/products/{product['id']}",
        headers={**headers_a, "If-Match": '"1"'},
        json={"description": "Brewed in store"},
    )
    assert updated_product.status_code == 200, updated_product.text
    assert updated_product.json()["current_version"] == 2

    stale_product = identity_client.patch(
        f"/api/v1/store/products/{product['id']}",
        headers={**headers_a, "If-Match": '"1"'},
        json={"description": "Stale update"},
    )
    assert stale_product.status_code == 409
    assert stale_product.json()["error"]["code"] == "VERSION_CONFLICT"


def test_store_knowledge_api_rejects_missing_store_context(
    identity_client, db_session, monkeypatch
):
    import store_operator.auth.router as auth_router

    monkeypatch.setattr(auth_router, "redis_client", FakeRedis())
    user = create_user(db_session)
    create_store(db_session, user, "Context Required")
    identity_client.post(
        "/api/v1/auth/login",
        json={"email": "knowledge@example.com", "password": "test-password-123"},
        headers=ORIGIN,
    )

    response = identity_client.get("/api/v1/store/products")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "STORE_CONTEXT_REQUIRED"
