from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from store_operator.auth.security import hash_password
from store_operator.models.identity import Store, StoreMembership, User
from store_operator.models.opportunity_effects import HotTopic, HotTopicSource, MetricDefinition, StoreOpportunity

ORIGIN = {"Origin": "http://localhost:5173"}

class FakeRedis:
    def __init__(self):
        self.values: dict[str, int] = {}
    def eval(self, script, numkeys, *args):
        counts = []
        for key in args[:numkeys]:
            self.values[key] = self.values.get(key, 0) + 1
            counts.append(self.values[key])
        return counts
    def delete(self, *keys):
        for key in keys:
            self.values.pop(key, None)
        return len(keys)

def _identity(db, email: str, store_name: str):
    user = User(id=uuid4(), email_normalized=email,
        password_hash=hash_password("test-password-123"), status="active")
    db.add(user); db.flush()
    store = Store(id=uuid4(), name=store_name, timezone="Asia/Tokyo", status="active")
    db.add(store); db.flush()
    db.add(StoreMembership(id=uuid4(), store_id=store.id, user_id=user.id,
        role="owner", status="active", joined_at=datetime.now(UTC)))
    db.flush()
    return user, store

def _login(client, email: str, store_id):
    response = client.post("/api/v1/auth/login",
        json={"email": email, "password": "test-password-123"}, headers=ORIGIN)
    assert response.status_code == 200, response.text
    return {**ORIGIN, "X-CSRF-Token": response.json()["csrf_token"], "X-Store-ID": str(store_id)}

def test_opportunity_decision_is_store_scoped_and_idempotent(identity_client, db_session, monkeypatch):
    import store_operator.auth.router as auth_router
    monkeypatch.setattr(auth_router, "redis_client", FakeRedis())
    _, store_a = _identity(db_session, "opportunity@example.com", "Opportunity A")
    _, store_b = _identity(db_session, "opportunity-b@example.com", "Opportunity B")
    source = HotTopicSource(id=uuid4(), source_key="approved-rss", display_name="Approved RSS",
        source_type="rss", enabled=True, health_status="healthy")
    db_session.add(source); db_session.flush()
    topic = HotTopic(id=uuid4(), source_id=source.id, source_item_id="item-1",
        canonical_url="https://example.test/topic/1", title="Local seasonal trend",
        discovered_at=datetime.now(UTC), last_seen_at=datetime.now(UTC),
        evidence_status="collected", content_fingerprint="a" * 64)
    db_session.add(topic); db_session.flush()
    opportunity = StoreOpportunity(id=uuid4(), store_id=store_a.id, hot_topic_id=topic.id,
        store_context_fingerprint="b" * 64, matching_version=1, relevance_score=Decimal("82.5"),
        match_method="rules", eligibility_status="eligible", matched_at=datetime.now(UTC),
        reason_summary="Matches a confirmed product category.")
    db_session.add(opportunity); db_session.flush()
    headers = _login(identity_client, "opportunity@example.com", store_a.id)
    visible = identity_client.get("/api/v1/opportunities", headers={"X-Store-ID": str(store_a.id)})
    assert visible.status_code == 200, visible.text
    assert visible.json()["items"][0]["id"] == str(opportunity.id)
    hidden = identity_client.get(f"/api/v1/opportunities/{opportunity.id}", headers={"X-Store-ID": str(store_b.id)})
    assert hidden.status_code == 404
    decision_headers = {**headers, "Idempotency-Key": "adopt-1"}
    first = identity_client.post(f"/api/v1/opportunities/{opportunity.id}/decisions",
        headers=decision_headers, json={"decision": "adopt", "reason": "Relevant this week"})
    assert first.status_code == 200, first.text
    replay = identity_client.post(f"/api/v1/opportunities/{opportunity.id}/decisions",
        headers=decision_headers, json={"decision": "adopt", "reason": "Relevant this week"})
    assert replay.status_code == 200
    assert replay.json()["id"] == first.json()["id"]
    assert replay.json()["replayed"] is True
    conflict = identity_client.post(f"/api/v1/opportunities/{opportunity.id}/decisions",
        headers=decision_headers, json={"decision": "ignore"})
    assert conflict.status_code == 409

def test_manual_metric_is_not_verified_or_roi_evidence(identity_client, db_session, monkeypatch):
    import store_operator.auth.router as auth_router
    monkeypatch.setattr(auth_router, "redis_client", FakeRedis())
    _, store = _identity(db_session, "effects@example.com", "Effects Shop")
    db_session.add(MetricDefinition(id=uuid4(), source_system="manual", metric_key="views",
        metric_tier="content_performance", display_name="播放/浏览", value_type="count",
        definition="Views within a period", aggregation_rule="sum", period_semantics="period_delta",
        definition_version=1, status="active"))
    db_session.flush()
    headers = _login(identity_client, "effects@example.com", store.id)
    response = identity_client.post("/api/v1/effects/observations", headers=headers, json={
        "metric_key": "views", "value_numeric": "125",
        "period_start": "2026-11-01T00:00:00+09:00", "period_end": "2026-11-02T00:00:00+09:00",
        "period_timezone": "Asia/Tokyo", "source_record_id": "manual-report-1",
        "source_evidence_ref": "merchant statement"})
    assert response.status_code == 200, response.text
    assert response.json()["item"]["authenticity_status"] == "merchant_reported"
    overview = identity_client.get("/api/v1/effects/overview", headers={"X-Store-ID": str(store.id)})
    assert overview.status_code == 200, overview.text
    assert overview.json()["data_status"] == "unavailable"
    assert overview.json()["business_outcomes"]["roi"] is None
    assert overview.json()["items"][0]["value"] is None

def test_csv_import_is_idempotent_and_labeled_as_merchant_reported(identity_client, db_session, monkeypatch):
    import store_operator.auth.router as auth_router
    monkeypatch.setattr(auth_router, "redis_client", FakeRedis())
    _, store = _identity(db_session, "import@example.com", "Import Shop")
    db_session.add(MetricDefinition(id=uuid4(), source_system="manual", metric_key="likes",
        metric_tier="content_performance", display_name="点赞", value_type="count",
        definition="Likes", aggregation_rule="sum", period_semantics="period_delta",
        definition_version=1, status="active"))
    db_session.flush()
    headers = _login(identity_client, "import@example.com", store.id)
    csv_text = ("metric_key,value_numeric,period_timezone,period_start,period_end,source_record_id\n"
        "likes,15,Asia/Tokyo,2026-11-01T00:00:00+09:00,2026-11-02T00:00:00+09:00,post-1\n")
    first = identity_client.post("/api/v1/effects/import", headers=headers, json={"csv_text": csv_text})
    assert first.status_code == 200, first.text
    assert first.json()["created"] == 1
    second = identity_client.post("/api/v1/effects/import", headers=headers, json={"csv_text": csv_text})
    assert second.status_code == 200, second.text
    assert second.json()["created"] == 0
    assert second.json()["duplicates_skipped"] == 1
