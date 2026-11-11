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


def create_user(
    db: Session,
    email: str = "knowledge@example.com",
) -> User:
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
        headers={**headers_a, "Idempotency-Key": "profile-create-1"},
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
        headers={**headers_a, "Idempotency-Key": "product-create-1"},
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

    replay = identity_client.post(
        "/api/v1/store/products",
        headers={**headers_a, "Idempotency-Key": "product-create-1"},
        json={
            "name": "Seasonal tea",
            "price_amount": "680.00",
            "currency": "JPY",
            "availability_status": "available",
        },
    )
    assert replay.status_code == 201
    assert replay.json()["id"] == product["id"]

    key_conflict = identity_client.post(
        "/api/v1/store/products",
        headers={**headers_a, "Idempotency-Key": "product-create-1"},
        json={"name": "Different payload"},
    )
    assert key_conflict.status_code == 409
    assert key_conflict.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"

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

    second_user = create_user(db_session, "second-knowledge@example.com")
    db_session.add(
        StoreMembership(
            id=uuid4(),
            store_id=store_a.id,
            user_id=second_user.id,
            role="owner",
            status="active",
            joined_at=datetime.now(UTC),
        )
    )
    db_session.flush()
    second_login = identity_client.post(
        "/api/v1/auth/login",
        json={
            "email": "second-knowledge@example.com",
            "password": "test-password-123",
        },
        headers=ORIGIN,
    )
    assert second_login.status_code == 200, second_login.text
    second_headers = {
        **ORIGIN,
        "X-CSRF-Token": second_login.json()["csrf_token"],
        "X-Store-ID": str(store_a.id),
        "Idempotency-Key": "product-create-1",
    }
    cross_actor_replay = identity_client.post(
        "/api/v1/store/products",
        headers=second_headers,
        json={
            "name": "Seasonal tea",
            "price_amount": "680.00",
            "currency": "JPY",
            "availability_status": "available",
        },
    )
    assert cross_actor_replay.status_code == 409
    assert (
        cross_actor_replay.json()["error"]["code"]
        == "IDEMPOTENCY_KEY_SCOPE_MISMATCH"
    )
    assert product["id"] not in cross_actor_replay.text


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


def test_offer_knowledge_brand_and_audience_apis_support_fact_confirmation(
    identity_client, db_session, monkeypatch
):
    import store_operator.auth.router as auth_router

    monkeypatch.setattr(auth_router, "redis_client", FakeRedis())
    user = create_user(db_session)
    store = create_store(db_session, user, "Knowledge Lifecycle")
    login = identity_client.post(
        "/api/v1/auth/login",
        json={"email": "knowledge@example.com", "password": "test-password-123"},
        headers=ORIGIN,
    )
    assert login.status_code == 200
    headers = {
        **ORIGIN,
        "X-CSRF-Token": login.json()["csrf_token"],
        "X-Store-ID": str(store.id),
    }

    offer_response = identity_client.post(
        "/api/v1/store/offers",
        headers={**headers, "Idempotency-Key": "offer-create-1"},
        json={
            "title": "Lunch set",
            "offer_type": "bundle",
            "terms_json": {"discount": "10%"},
            "status": "draft",
        },
    )
    assert offer_response.status_code == 201, offer_response.text
    offer = offer_response.json()
    confirmed = identity_client.post(
        f"/api/v1/store/offers/{offer['id']}/confirm-facts",
        headers={**headers, "If-Match": '"1"'},
        json={"source_type": "merchant_confirmation", "confirmation_note": "Checked by owner"},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["fact_status"] == "confirmed"
    assert confirmed.json()["current_version"] == 2

    stale_update = identity_client.patch(
        f"/api/v1/store/offers/{offer['id']}",
        headers={**headers, "If-Match": '"1"'},
        json={"title": "Changed lunch set"},
    )
    assert stale_update.status_code == 409

    knowledge_response = identity_client.post(
        "/api/v1/store/knowledge",
        headers={**headers, "Idempotency-Key": "knowledge-create-1"},
        json={
            "title": "Store opening policy",
            "category": "policy",
            "content_text": "Open daily from 10:00 to 20:00",
            "source_type": "merchant_input",
        },
    )
    assert knowledge_response.status_code == 201, knowledge_response.text
    assert knowledge_response.json()["fact_status"] == "pending_confirmation"

    audience_response = identity_client.post(
        "/api/v1/store/audiences",
        headers={**headers, "Idempotency-Key": "audience-create-1"},
        json={
            "name": "Nearby office workers",
            "segment_type": "core",
            "audience_description": "Lunch customers within walking distance",
        },
    )
    assert audience_response.status_code == 201, audience_response.text

    brand_response = identity_client.post(
        "/api/v1/store/brand-guideline",
        headers={**headers, "Idempotency-Key": "brand-create-1"},
        json={"tone_of_voice": "Clear, practical and restrained"},
    )
    assert brand_response.status_code == 201, brand_response.text
    assert brand_response.json()["current_version"] == 1
