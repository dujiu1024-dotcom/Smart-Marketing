from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from store_operator.auth.security import hash_password
from store_operator.models.identity import Store, StoreMembership, User
from store_operator.models.store_knowledge import BrandGuideline, MediaAsset, UploadIntent

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
    hidden_profile = identity_client.get("/api/v1/store/profile", headers=headers_b)
    assert hidden_profile.status_code == 404

    updated_profile = identity_client.patch(
        "/api/v1/store/profile",
        headers={**headers_a, "If-Match": '"1"'},
        json={"city": "Osaka"},
    )
    assert updated_profile.status_code == 200, updated_profile.text
    assert updated_profile.json()["current_version"] == 2
    assert updated_profile.json()["city"] == "Osaka"
    hidden_profile_update = identity_client.patch(
        "/api/v1/store/profile",
        headers={**headers_a, "X-Store-ID": str(store_b.id), "If-Match": '"2"'},
        json={"city": "Cross-store write"},
    )
    assert hidden_profile_update.status_code == 404

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
    hidden_product_update = identity_client.patch(
        f"/api/v1/store/products/{product['id']}",
        headers={**headers_a, "X-Store-ID": str(store_b.id), "If-Match": '"1"'},
        json={"description": "Cross-store write must fail"},
    )
    assert hidden_product_update.status_code == 404
    hidden_product_delete = identity_client.delete(
        f"/api/v1/store/products/{product['id']}",
        headers={**headers_a, "X-Store-ID": str(store_b.id), "If-Match": '"1"'},
    )
    assert hidden_product_delete.status_code == 404

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


def test_media_asset_upload_is_verified_and_quarantined_before_use(
    identity_client, db_session, monkeypatch
):
    import store_operator.auth.router as auth_router
    import store_operator.store_knowledge_router as knowledge_router

    monkeypatch.setattr(auth_router, "redis_client", FakeRedis())
    user = create_user(db_session, "asset-upload@example.com")
    store = create_store(db_session, user, "Asset Upload Store")
    login = identity_client.post(
        "/api/v1/auth/login",
        json={"email": "asset-upload@example.com", "password": "test-password-123"},
        headers=ORIGIN,
    )
    assert login.status_code == 200, login.text
    csrf = login.json()["csrf_token"]
    headers = {
        **ORIGIN,
        "X-CSRF-Token": csrf,
        "X-Store-ID": str(store.id),
        "Idempotency-Key": "asset-upload-intent-1",
    }
    sha256 = "a" * 64
    monkeypatch.setattr(
        knowledge_router,
        "create_upload_url",
        lambda **kwargs: "https://private-storage.invalid/upload",
    )
    created = identity_client.post(
        "/api/v1/store/assets/upload-intents",
        headers=headers,
        json={
            "expected_mime_type": "image/png",
            "expected_byte_size": 1024,
            "expected_sha256": sha256,
            "original_filename": "../../menu.png",
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["method"] == "PUT"
    assert created.json()["required_headers"]["Content-Type"] == "image/png"
    assert created.json()["required_headers"]["If-None-Match"] == "*"
    assert "x-amz-meta-sha256" in created.json()["required_headers"]

    intent = db_session.get(UploadIntent, UUID(created.json()["id"]))
    assert intent is not None
    assert intent.store_id == store.id
    assert intent.object_key.startswith(f"stores/{store.id}/quarantine/")
    assert ".." not in intent.object_key

    monkeypatch.setattr(
        knowledge_router,
        "head_object",
        lambda **kwargs: {
            "ContentLength": 1024,
            "ContentType": "image/png",
            "Metadata": {"sha256": "0" * 64},
        },
    )
    monkeypatch.setattr(
        knowledge_router, "calculate_object_sha256", lambda **kwargs: sha256
    )
    completed = identity_client.post(
        f"/api/v1/store/assets/upload-intents/{intent.id}/complete",
        headers={**headers, "Idempotency-Key": "asset-upload-complete-1"},
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["status"] == "scanning"
    assert completed.json()["asset"]["status"] == "quarantined"
    assert completed.json()["asset"]["original_filename_sanitized"] == "menu.png"
    asset = db_session.get(MediaAsset, UUID(completed.json()["asset"]["id"]))
    assert asset is not None
    assert asset.usage_rights_status == "unknown"

    download = identity_client.get(
        f"/api/v1/store/assets/{asset.id}/download-url",
        headers={"X-Store-ID": str(store.id)},
    )
    assert download.status_code == 409
    assert download.json()["error"]["code"] == "MEDIA_ASSET_NOT_READY"


def test_media_asset_upload_rejects_server_metadata_mismatch(
    identity_client, db_session, monkeypatch
):
    import store_operator.auth.router as auth_router
    import store_operator.store_knowledge_router as knowledge_router

    monkeypatch.setattr(auth_router, "redis_client", FakeRedis())
    user = create_user(db_session, "asset-mismatch@example.com")
    store = create_store(db_session, user, "Asset Mismatch Store")
    login = identity_client.post(
        "/api/v1/auth/login",
        json={"email": "asset-mismatch@example.com", "password": "test-password-123"},
        headers=ORIGIN,
    )
    assert login.status_code == 200, login.text
    headers = {
        **ORIGIN,
        "X-CSRF-Token": login.json()["csrf_token"],
        "X-Store-ID": str(store.id),
        "Idempotency-Key": "asset-mismatch-intent-1",
    }
    monkeypatch.setattr(
        knowledge_router,
        "create_upload_url",
        lambda **kwargs: "https://private-storage.invalid/upload",
    )
    created = identity_client.post(
        "/api/v1/store/assets/upload-intents",
        headers=headers,
        json={
            "expected_mime_type": "image/jpeg",
            "expected_byte_size": 512,
            "expected_sha256": "b" * 64,
            "original_filename": "photo.jpg",
        },
    )
    assert created.status_code == 201, created.text
    intent_id = UUID(created.json()["id"])
    monkeypatch.setattr(
        knowledge_router,
        "head_object",
        lambda **kwargs: {
            "ContentLength": 512,
            "ContentType": "image/jpeg",
            "Metadata": {"sha256": "b" * 64},
        },
    )
    monkeypatch.setattr(
        knowledge_router, "calculate_object_sha256", lambda **kwargs: "c" * 64
    )
    rejected = identity_client.post(
        f"/api/v1/store/assets/upload-intents/{intent_id}/complete",
        headers={**headers, "Idempotency-Key": "asset-mismatch-complete-1"},
    )
    assert rejected.status_code == 422
    assert rejected.json()["error"]["code"] == "UPLOAD_OBJECT_MISMATCH"
    db_session.refresh(db_session.get(UploadIntent, intent_id))
    assert db_session.get(UploadIntent, intent_id).status == "rejected"



def test_media_asset_usage_rights_are_version_bound_and_idempotent(
    identity_client, db_session, monkeypatch
):
    import store_operator.auth.router as auth_router
    import store_operator.store_knowledge_router as knowledge_router

    monkeypatch.setattr(auth_router, "redis_client", FakeRedis())
    monkeypatch.setattr(
        knowledge_router,
        "create_download_url",
        lambda **kwargs: "https://private-storage.invalid/download",
    )
    user = create_user(db_session, "asset-rights@example.com")
    store = create_store(db_session, user, "Asset Rights Store")
    login = identity_client.post(
        "/api/v1/auth/login",
        json={"email": "asset-rights@example.com", "password": "test-password-123"},
        headers=ORIGIN,
    )
    assert login.status_code == 200, login.text
    headers = {
        **ORIGIN,
        "X-CSRF-Token": login.json()["csrf_token"],
        "X-Store-ID": str(store.id),
    }
    asset = MediaAsset(
        id=uuid4(),
        store_id=store.id,
        object_key=f"stores/{store.id}/quarantine/test/menu.png",
        sha256="a" * 64,
        mime_type="image/png",
        byte_size=1024,
        asset_type="image",
        source_type="merchant_upload",
        usage_rights_status="unknown",
        status="ready",
        version_no=1,
        created_by_user_id=user.id,
    )
    db_session.add(asset)
    db_session.flush()

    url = f"/api/v1/store/assets/{asset.id}/confirm-usage-rights"
    payload = {
        "expected_version": 1,
        "expected_sha256": asset.sha256,
        "usage_rights_status": "confirmed_allowed",
        "license_note": "Merchant confirms ownership or permission for store marketing use.",
    }
    request_headers = {**headers, "Idempotency-Key": "asset-rights-confirm-1"}
    confirmed = identity_client.post(url, headers=request_headers, json=payload)
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["usage_rights_status"] == "confirmed_allowed"

    replay = identity_client.post(url, headers=request_headers, json=payload)
    assert replay.status_code == 200, replay.text
    assert replay.json()["id"] == confirmed.json()["id"]

    stale = identity_client.post(
        url,
        headers={**headers, "Idempotency-Key": "asset-rights-confirm-2"},
        json={**payload, "expected_version": 2},
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "VERSION_CONFLICT"

    download = identity_client.get(
        f"/api/v1/store/assets/{asset.id}/download-url",
        headers={"X-Store-ID": str(store.id)},
    )
    assert download.status_code == 200, download.text
    assert download.json()["url"] == "https://private-storage.invalid/download"


def test_media_asset_archive_checks_references_and_is_audited(
    identity_client, db_session, monkeypatch
):
    import store_operator.auth.router as auth_router

    monkeypatch.setattr(auth_router, "redis_client", FakeRedis())
    user = create_user(db_session, "asset-archive@example.com")
    store = create_store(db_session, user, "Asset Archive Store")
    login = identity_client.post(
        "/api/v1/auth/login",
        json={"email": "asset-archive@example.com", "password": "test-password-123"},
        headers=ORIGIN,
    )
    assert login.status_code == 200, login.text
    headers = {
        **ORIGIN,
        "X-CSRF-Token": login.json()["csrf_token"],
        "X-Store-ID": str(store.id),
    }
    asset = MediaAsset(
        id=uuid4(),
        store_id=store.id,
        object_key=f"stores/{store.id}/quarantine/archive/menu.png",
        sha256="b" * 64,
        mime_type="image/png",
        byte_size=2048,
        asset_type="image",
        source_type="merchant_upload",
        usage_rights_status="confirmed_allowed",
        license_note="Merchant-owned original image.",
        status="ready",
        version_no=1,
        created_by_user_id=user.id,
    )
    db_session.add(asset)
    db_session.flush()
    guideline = BrandGuideline(
        id=uuid4(),
        store_id=store.id,
        logo_asset_id=asset.id,
    )
    db_session.add(guideline)
    db_session.flush()

    url = f"/api/v1/store/assets/{asset.id}/archive"
    blocked = identity_client.post(
        url,
        headers={
            **headers,
            "If-Match": '"1"',
            "Idempotency-Key": "asset-archive-blocked",
        },
    )
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["error"]["code"] == "MEDIA_ASSET_IN_USE"

    guideline.logo_asset_id = None
    db_session.flush()
    archived = identity_client.post(
        url,
        headers={
            **headers,
            "If-Match": '"1"',
            "Idempotency-Key": "asset-archive-1",
        },
    )
    assert archived.status_code == 200, archived.text
    assert archived.json()["status"] == "archived"
    assert db_session.get(MediaAsset, asset.id).status == "archived"



def test_offer_knowledge_audience_and_asset_download_are_store_scoped(
    identity_client, db_session: Session, monkeypatch
) -> None:
    import store_operator.auth.router as auth_router

    monkeypatch.setattr(auth_router, "redis_client", FakeRedis())
    user = create_user(db_session, "store-resource-idor@example.com")
    store_a = create_store(db_session, user, "Resource Store A")
    store_b = create_store(db_session, user, "Resource Store B")
    login = identity_client.post(
        "/api/v1/auth/login",
        json={"email": "store-resource-idor@example.com", "password": "test-password-123"},
        headers=ORIGIN,
    )
    assert login.status_code == 200, login.text
    headers_a = {
        **ORIGIN,
        "X-CSRF-Token": login.json()["csrf_token"],
        "X-Store-ID": str(store_a.id),
    }
    headers_b = {**headers_a, "X-Store-ID": str(store_b.id)}

    offer = identity_client.post(
        "/api/v1/store/offers",
        headers={**headers_a, "Idempotency-Key": "resource-idor-offer"},
        json={
            "title": "Store A only offer",
            "offer_type": "bundle",
            "terms_json": {"discount": "10%"},
            "status": "draft",
        },
    )
    assert offer.status_code == 201, offer.text
    offer_id = offer.json()["id"]
    assert identity_client.get(
        f"/api/v1/store/offers/{offer_id}", headers=headers_b
    ).status_code == 404
    assert identity_client.patch(
        f"/api/v1/store/offers/{offer_id}",
        headers={**headers_b, "If-Match": '"1"'},
        json={"title": "Store B injection"},
    ).status_code == 404

    knowledge = identity_client.post(
        "/api/v1/store/knowledge",
        headers={**headers_a, "Idempotency-Key": "resource-idor-knowledge"},
        json={
            "title": "Store A policy",
            "category": "policy",
            "content_text": "Private Store A operating note",
            "source_type": "merchant_input",
        },
    )
    assert knowledge.status_code == 201, knowledge.text
    assert identity_client.get(
        f"/api/v1/store/knowledge/{knowledge.json()['id']}", headers=headers_b
    ).status_code == 404

    audience = identity_client.post(
        "/api/v1/store/audiences",
        headers={**headers_a, "Idempotency-Key": "resource-idor-audience"},
        json={
            "name": "Store A customers",
            "segment_type": "core",
            "audience_description": "Store A only audience",
        },
    )
    assert audience.status_code == 201, audience.text
    assert identity_client.get(
        f"/api/v1/store/audiences/{audience.json()['id']}", headers=headers_b
    ).status_code == 404

    asset = MediaAsset(
        id=uuid4(),
        store_id=store_a.id,
        object_key=f"stores/{store_a.id}/quarantine/idor-test.png",
        sha256="c" * 64,
        mime_type="image/png",
        byte_size=1024,
        asset_type="product_image",
        source_type="merchant_upload",
        usage_rights_status="unknown",
        status="quarantined",
        created_by_user_id=user.id,
    )
    db_session.add(asset)
    db_session.flush()
    hidden_download = identity_client.get(
        f"/api/v1/store/assets/{asset.id}/download-url",
        headers={"X-Store-ID": str(store_b.id)},
    )
    assert hidden_download.status_code == 404
    own_download = identity_client.get(
        f"/api/v1/store/assets/{asset.id}/download-url",
        headers={"X-Store-ID": str(store_a.id)},
    )
    assert own_download.status_code == 409
    assert own_download.json()["error"]["code"] == "MEDIA_ASSET_NOT_READY"
