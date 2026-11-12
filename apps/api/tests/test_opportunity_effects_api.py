import base64
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from io import BytesIO
from uuid import UUID, uuid4
from zipfile import ZipFile

from sqlalchemy import select

from store_operator.auth.security import hash_password
from store_operator.models.identity import Store, StoreMembership, User
from store_operator.models.marketing_task import MarketingTask
from store_operator.models.opportunity_effects import (
    BusinessOutcomeEvidence,
    HotTopic,
    HotTopicSource,
    MetricDefinition,
    MetricImportBatch,
    MetricObservation,
    PublishedWork,
    StoreOpportunity,
    WorkOwnershipEvidence,
)

ORIGIN = {"Origin": "http://localhost:5173"}



def _ensure_manual_metric_definition(
    db_session,
    *,
    metric_key: str,
    metric_tier: str,
    display_name: str,
    definition: str,
) -> MetricDefinition:
    existing = db_session.scalar(
        select(MetricDefinition).where(
            MetricDefinition.source_system == "manual",
            MetricDefinition.metric_key == metric_key,
            MetricDefinition.definition_version == 1,
        )
    )
    if existing is not None:
        return existing
    item = MetricDefinition(
        id=uuid4(),
        source_system="manual",
        metric_key=metric_key,
        metric_tier=metric_tier,
        display_name=display_name,
        value_type="count",
        definition=definition,
        aggregation_rule="sum",
        period_semantics="period_delta",
        definition_version=1,
        status="active",
    )
    db_session.add(item)
    db_session.flush()
    return item

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
    db.add(user)
    db.flush()
    store = Store(id=uuid4(), name=store_name, timezone="Asia/Tokyo", status="active")
    db.add(store)
    db.flush()
    db.add(StoreMembership(id=uuid4(), store_id=store.id, user_id=user.id,
        role="owner", status="active", joined_at=datetime.now(UTC)))
    db.flush()
    return user, store

def _login(client, email: str, store_id):
    response = client.post("/api/v1/auth/login",
        json={"email": email, "password": "test-password-123"}, headers=ORIGIN)
    assert response.status_code == 200, response.text
    return {**ORIGIN, "X-CSRF-Token": response.json()["csrf_token"], "X-Store-ID": str(store_id)}

def test_opportunity_decision_is_store_scoped_and_idempotent(identity_client, db_session,
    monkeypatch):
    import store_operator.auth.router as auth_router
    monkeypatch.setattr(auth_router, "redis_client", FakeRedis())
    _, store_a = _identity(db_session, "opportunity@example.com", "Opportunity A")
    _, store_b = _identity(db_session, "opportunity-b@example.com", "Opportunity B")
    source = HotTopicSource(id=uuid4(), source_key="approved-rss", display_name="Approved RSS",
        source_type="rss", source_url="https://news.example.test/rss", enabled=True,
            health_status="healthy")
    db_session.add(source)
    db_session.flush()
    topic = HotTopic(id=uuid4(), source_id=source.id, source_item_id="item-1",
        canonical_url="https://example.test/topic/1", title="Local seasonal trend",
        discovered_at=datetime.now(UTC), last_seen_at=datetime.now(UTC),
        evidence_status="collected", content_fingerprint="a" * 64)
    db_session.add(topic)
    db_session.flush()
    opportunity = StoreOpportunity(id=uuid4(), store_id=store_a.id, hot_topic_id=topic.id,
        store_context_fingerprint="b" * 64, matching_version=1, relevance_score=Decimal("82.5"),
        match_method="rules", eligibility_status="eligible", matched_at=datetime.now(UTC),
        reason_summary="Matches a confirmed product category.")
    db_session.add(opportunity)
    db_session.flush()
    headers = _login(identity_client, "opportunity@example.com", store_a.id)
    visible = identity_client.get("/api/v1/opportunities", headers={"X-Store-ID": str(store_a.id)})
    assert visible.status_code == 200, visible.text
    assert visible.json()["items"][0]["id"] == str(opportunity.id)
    assert visible.json()["items"][0]["matching_algorithm_version"] == 2
    hidden = identity_client.get(f"/api/v1/opportunities/{opportunity.id}",
        headers={"X-Store-ID": str(store_b.id)})
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
    _ensure_manual_metric_definition(
        db_session,
        metric_key="views",
        metric_tier="content_performance",
        display_name="播放/浏览",
        definition="Views within a period",
    )
    headers = _login(identity_client, "effects@example.com", store.id)
    response = identity_client.post("/api/v1/effects/observations", headers=headers, json={
        "metric_key": "views", "value_numeric": "125",
        "period_start": "2026-11-01T00:00:00+09:00", "period_end": "2026-11-02T00:00:00+09:00",
        "period_timezone": "Asia/Tokyo", "source_record_id": "manual-report-1",
        "source_evidence_ref": "merchant statement"})
    assert response.status_code == 200, response.text
    assert response.json()["item"]["authenticity_status"] == "merchant_reported"
    overview = identity_client.get("/api/v1/effects/overview",
        headers={"X-Store-ID": str(store.id)})
    assert overview.status_code == 200, overview.text
    assert overview.json()["data_status"] == "unavailable"
    assert overview.json()["business_outcomes"]["roi"] is None
    assert overview.json()["items"][0]["value"] is None

def test_csv_import_is_idempotent_and_labeled_as_merchant_reported(identity_client, db_session,
    monkeypatch):
    import store_operator.auth.router as auth_router
    monkeypatch.setattr(auth_router, "redis_client", FakeRedis())
    _, store = _identity(db_session, "import@example.com", "Import Shop")
    _ensure_manual_metric_definition(
        db_session,
        metric_key="likes",
        metric_tier="content_performance",
        display_name="点赞",
        definition="Likes",
    )
    headers = _login(identity_client, "import@example.com", store.id)
    csv_text = (
        "metric_key,value_numeric,period_timezone,period_start,period_end,source_record_id\n"
        "likes,15,Asia/Tokyo,2026-11-01T00:00:00+09:00,2026-11-02T00:00:00+09:00,post-1\n"
    )
    first = identity_client.post("/api/v1/effects/import", headers=headers,
        json={"csv_text": csv_text})
    assert first.status_code == 200, first.text
    assert first.json()["created"] == 1
    assert len(first.json()["content_sha256"]) == 64
    assert first.json()["import_batch_id"]
    second = identity_client.post("/api/v1/effects/import", headers=headers,
        json={"csv_text": csv_text})
    assert second.status_code == 200, second.text
    assert second.json()["created"] == 0
    assert second.json()["duplicates_skipped"] == 1
    assert second.json()["import_batch_id"] == first.json()["import_batch_id"]


def test_adopted_opportunity_handoff_creates_store_scoped_immutable_snapshot(
    identity_client, db_session, monkeypatch
):
    import store_operator.auth.router as auth_router

    monkeypatch.setattr(auth_router, "redis_client", FakeRedis())
    _, store = _identity(db_session, "handoff@example.com", "Handoff Shop")
    source = HotTopicSource(
        id=uuid4(),
        source_key="handoff-rss",
        display_name="Handoff RSS",
        source_type="rss",
        source_url="https://news.example.test/rss",
        enabled=True,
        health_status="healthy",
    )
    db_session.add(source)
    db_session.flush()
    topic = HotTopic(
        id=uuid4(),
        source_id=source.id,
        source_item_id="handoff-item",
        canonical_url="https://news.example.test/story/handoff",
        title="Seasonal local menu trend",
        summary="Local demand for seasonal drinks",
        discovered_at=datetime.now(UTC),
        last_seen_at=datetime.now(UTC),
        evidence_status="collected",
        content_fingerprint="c" * 64,
    )
    db_session.add(topic)
    db_session.flush()
    opportunity = StoreOpportunity(
        id=uuid4(),
        store_id=store.id,
        hot_topic_id=topic.id,
        store_context_fingerprint="d" * 64,
        matching_version=2,
        relevance_score=Decimal("78.5"),
        match_method="rules",
        eligibility_status="eligible",
        matched_at=datetime.now(UTC),
        reason_summary="A confirmed product is relevant to this trend.",
        suggested_scenario="Promote the seasonal drink",
        content_angle="Explain the seasonal ingredients",
        matched_product_ids_json=["product-1"],
    )
    db_session.add(opportunity)
    db_session.flush()
    headers = _login(identity_client, "handoff@example.com", store.id)

    create_payload = {
        "task_type": "full_marketing",
        "title": "Seasonal opportunity content",
        "opportunity_id": str(opportunity.id),
        "requirement_draft": {"goal": "Promote the seasonal drink"},
        "task_options": {
            "includes_copy": True,
            "includes_image": True,
            "opportunity_applicable": True,
            "selected_channel_keys": [],
            "requires_external_delivery": False,
        },
    }
    not_adopted = identity_client.post(
        "/api/v1/marketing-tasks",
        headers={**headers, "Idempotency-Key": "handoff-before-adopt"},
        json=create_payload,
    )
    assert not_adopted.status_code == 409

    adopted = identity_client.post(
        f"/api/v1/opportunities/{opportunity.id}/decisions",
        headers={**headers, "Idempotency-Key": "handoff-adopt"},
        json={"decision": "adopt"},
    )
    assert adopted.status_code == 200, adopted.text

    created = identity_client.post(
        "/api/v1/marketing-tasks",
        headers={**headers, "Idempotency-Key": "handoff-create"},
        json=create_payload,
    )
    assert created.status_code == 201, created.text
    task = created.json()
    snapshot = task["task_options"]["opportunity_snapshot"]
    assert snapshot["opportunity_id"] == str(opportunity.id)
    assert snapshot["matching_version"] == 2
    assert snapshot["source"]["url"] == topic.canonical_url
    assert snapshot["source"]["title"] == topic.title

    updated = identity_client.patch(
        f"/api/v1/marketing-tasks/{task['id']}/requirement",
        headers={**headers, "Idempotency-Key": "handoff-update"},
        json={
            "expected_version": 1,
            "requirement_draft": {"goal": "Refined seasonal promotion"},
            "task_options": {
                "includes_copy": True,
                "includes_image": True,
                "opportunity_applicable": False,
                "opportunity_snapshot": {"forged": True},
                "selected_channel_keys": [],
                "requires_external_delivery": False,
            },
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["task_options"]["opportunity_snapshot"] == snapshot
    assert updated.json()["task_options"]["opportunity_applicable"] is True


def test_manual_observation_correction_appends_without_mutating_original(
    identity_client, db_session, monkeypatch
):
    import store_operator.auth.router as auth_router

    monkeypatch.setattr(auth_router, "redis_client", FakeRedis())
    _, store = _identity(db_session, "correction@example.com", "Correction Shop")
    _ensure_manual_metric_definition(
        db_session,
        metric_key="views",
        metric_tier="content_performance",
        display_name="播放/浏览",
        definition="Views within a period",
    )
    headers = _login(identity_client, "correction@example.com", store.id)
    original_response = identity_client.post(
        "/api/v1/effects/observations",
        headers=headers,
        json={
            "metric_key": "views",
            "value_numeric": "125",
            "period_start": "2026-11-01T00:00:00+09:00",
            "period_end": "2026-11-02T00:00:00+09:00",
            "period_timezone": "Asia/Tokyo",
            "source_record_id": "merchant-report-1",
        },
    )
    assert original_response.status_code == 200, original_response.text
    original = original_response.json()["item"]

    correction = identity_client.post(
        f"/api/v1/effects/observations/{original['id']}/corrections",
        headers=headers,
        json={
            "metric_key": "views",
            "value_numeric": "140",
            "period_start": "2026-11-01T00:00:00+09:00",
            "period_end": "2026-11-02T00:00:00+09:00",
            "period_timezone": "Asia/Tokyo",
            "source_record_id": "merchant-report-1-corrected",
            "source_evidence_ref": "merchant correction note",
        },
    )
    assert correction.status_code == 200, correction.text
    corrected = correction.json()["item"]
    assert corrected["supersedes_observation_id"] == original["id"]
    assert corrected["value_numeric"] == "140"
    assert corrected["authenticity_status"] == "merchant_reported"

    history = identity_client.get("/api/v1/effects/observations", headers=headers)
    assert history.status_code == 200, history.text
    by_id = {item["id"]: item for item in history.json()["items"]}
    assert by_id[original["id"]]["value_numeric"] == "125"
    assert by_id[corrected["id"]]["value_numeric"] == "140"

    duplicate = identity_client.post(
        f"/api/v1/effects/observations/{original['id']}/corrections",
        headers=headers,
        json={
            "metric_key": "views",
            "value_numeric": "150",
            "period_timezone": "Asia/Tokyo",
        },
    )
    assert duplicate.status_code == 409


def test_effects_overview_aggregates_verified_equal_periods_and_computes_change(
    identity_client, db_session, monkeypatch
):
    import store_operator.auth.router as auth_router

    monkeypatch.setattr(auth_router, "redis_client", FakeRedis())
    _, store = _identity(db_session, "trend@example.com", "Trend Shop")
    definition = MetricDefinition(
        id=uuid4(),
        source_system="official_api",
        metric_key="views",
        metric_tier="content_performance",
        display_name="播放/浏览",
        value_type="count",
        definition="Verified views in a period",
        aggregation_rule="sum",
        period_semantics="period_delta",
        definition_version=1,
        status="active",
    )
    click_definition = MetricDefinition(
        id=uuid4(),
        source_system="official_api",
        metric_key="clicks",
        metric_tier="intent",
        display_name="点击",
        value_type="count",
        definition="Verified clicks in a period",
        aggregation_rule="sum",
        period_semantics="period_delta",
        definition_version=2,
        status="active",
    )
    db_session.add_all([definition, click_definition])
    db_session.flush()
    periods = [
        (
            datetime.fromisoformat("2026-11-01T00:00:00+09:00"),
            datetime.fromisoformat("2026-11-02T00:00:00+09:00"),
            Decimal("100"),
        ),
        (
            datetime.fromisoformat("2026-11-02T00:00:00+09:00"),
            datetime.fromisoformat("2026-11-03T00:00:00+09:00"),
            Decimal("125"),
        ),
    ]
    for index, (period_start, period_end, value) in enumerate(periods):
        for metric_definition, metric_key, metric_tier, metric_value, source_id in (
            (definition, "views", "content_performance", value, f"post-{index}"),
            (
                click_definition,
                "clicks",
                "intent",
                Decimal("10") if index == 0 else Decimal("20"),
                f"click-{index}",
            ),
        ):
            db_session.add(
                MetricObservation(
                    id=uuid4(),
                    store_id=store.id,
                    metric_definition_id=metric_definition.id,
                    metric_key=metric_key,
                    metric_tier=metric_tier,
                    value_numeric=metric_value,
                    unit="count",
                    source_system="official_api",
                    source_record_id=source_id,
                    period_start=period_start,
                    period_end=period_end,
                    period_timezone="Asia/Tokyo",
                    collected_at=datetime(2026, 11, 4 + index, tzinfo=UTC),
                    definition_version=metric_definition.definition_version,
                    integrity_status="complete",
                    authenticity_status="official_api",
                    sync_status="current",
                    deduplication_key=source_id.ljust(64, "0"),
                )
            )
    db_session.flush()
    headers = _login(identity_client, "trend@example.com", store.id)

    response = identity_client.get("/api/v1/effects/overview", headers=headers)

    assert response.status_code == 200, response.text
    overview = response.json()
    assert overview["data_status"] == "available"
    views_card = next(
        item for item in overview["items"] if item["metric_key"] == "views"
    )
    assert views_card["value"] == "125"
    assert overview["data_quality"]["verified_observations"] == 4
    trend = next(item for item in overview["trends"] if item["metric_key"] == "views")
    assert len(trend["points"]) == 2
    assert trend["comparison"]["status"] == "available"
    assert trend["comparison"]["change_percent"] == "25.00"
    conversion = overview["conversion_rates"]
    assert len(conversion) == 2
    assert [item["value_percent"] for item in conversion] == ["10.00", "16.00"]
    assert len(overview["insights"]) == 2
    assert all(item["next_action"] for item in overview["insights"])


def test_attribution_rejects_merchant_claimed_work_and_unverified_outcome(
    identity_client, db_session, monkeypatch
):
    import store_operator.auth.router as auth_router

    monkeypatch.setattr(auth_router, "redis_client", FakeRedis())
    _, store = _identity(db_session, "attribution@example.com", "Attribution Shop")
    headers = _login(identity_client, "attribution@example.com", store.id)
    task_response = identity_client.post(
        "/api/v1/marketing-tasks",
        headers={**headers, "Idempotency-Key": "attribution-task"},
        json={
            "task_type": "full_marketing",
            "title": "Attribution evidence task",
            "requirement_draft": {"goal": "Test attribution evidence"},
            "task_options": {
                "includes_copy": True,
                "includes_image": True,
                "selected_channel_keys": [],
                "requires_external_delivery": False,
            },
        },
    )
    assert task_response.status_code == 201, task_response.text
    task_id = UUID(task_response.json()["id"])

    work = PublishedWork(
        id=uuid4(),
        store_id=store.id,
        task_id=task_id,
        channel_key="douyin",
        external_work_id="merchant-claimed-work",
        ownership_status="merchant_claim",
    )
    outcome = BusinessOutcomeEvidence(
        id=uuid4(),
        store_id=store.id,
        outcome_type="orders",
        value_numeric=Decimal("8"),
        source_system="manual",
        source_record_id="merchant-order-report",
        source_evidence_ref="merchant supplied report",
        occurred_at=datetime.now(UTC),
        authenticity_status="merchant_reported",
        integrity_status="unknown",
        deduplication_key="e" * 64,
    )
    db_session.add_all([work, outcome])
    db_session.flush()

    response = identity_client.post(
        "/api/v1/effects/attributions",
        headers=headers,
        json={
            "marketing_task_id": str(task_id),
            "published_work_id": str(work.id),
            "outcome_evidence_id": str(outcome.id),
            "attribution_method": "direct_code",
            "evidence_strength": "strong",
            "allocation_percent": "100",
        },
    )
    assert response.status_code == 409


def test_manual_business_outcome_is_retained_as_unverified_evidence(
    identity_client, db_session, monkeypatch
):
    import store_operator.auth.router as auth_router

    monkeypatch.setattr(auth_router, "redis_client", FakeRedis())
    _, store = _identity(db_session, "outcome@example.com", "Outcome Shop")
    headers = _login(identity_client, "outcome@example.com", store.id)

    response = identity_client.post(
        "/api/v1/effects/business-outcomes",
        headers=headers,
        json={
            "outcome_type": "orders",
            "value_numeric": "12",
            "source_record_id": "manual-order-report",
            "source_evidence_ref": "Merchant-provided daily report",
            "occurred_at": "2026-11-10T18:00:00+08:00",
        },
    )
    assert response.status_code == 200, response.text
    item = response.json()["item"]
    assert item["authenticity_status"] == "merchant_reported"
    assert item["integrity_status"] == "unknown"

    history = identity_client.get("/api/v1/effects/business-outcomes", headers=headers)
    assert history.status_code == 200
    assert history.json()["items"][0]["id"] == item["id"]

    readbacks = identity_client.get("/api/v1/effects/publish-readbacks", headers=headers)
    capabilities = identity_client.get("/api/v1/effects/data-source-capabilities", headers=headers)
    assert readbacks.status_code == 200
    assert readbacks.json()["items"] == []
    assert capabilities.status_code == 200
    assert capabilities.json()["items"] == []


def test_effects_overview_breaks_down_verified_content_metrics_by_published_work(
    identity_client, db_session, monkeypatch
):
    import store_operator.auth.router as auth_router

    monkeypatch.setattr(auth_router, "redis_client", FakeRedis())
    user, store = _identity(db_session, "work-trend@example.com", "Work Trend Shop")
    task = MarketingTask(
        id=uuid4(),
        store_id=store.id,
        task_type="full_marketing",
        lifecycle_status="draft",
        title="Verified content performance task",
        version=1,
        requirement_draft_json={"goal": "Track verified work performance"},
        strategy_draft_json={},
        task_options_json={},
        created_by_user_id=user.id,
    )
    db_session.add(task)
    db_session.flush()

    work = PublishedWork(
        id=uuid4(),
        store_id=store.id,
        task_id=task.id,
        channel_key="douyin",
        external_work_id="verified-work-001",
        ownership_status="verified_platform_api",
        verified_at=datetime(2026, 11, 4, tzinfo=UTC),
        source_snapshot_json={"verification": "official platform API"},
    )
    db_session.add(work)
    db_session.flush()
    db_session.add(
        WorkOwnershipEvidence(
            id=uuid4(),
            store_id=store.id,
            published_work_id=work.id,
            evidence_type="platform_api",
            evidence_status="verified",
            source_system="douyin",
            evidence_ref="https://platform.example.test/works/verified-work-001",
            evidence_payload_json={"verified": True},
            verified_by_user_id=user.id,
            verified_at=datetime(2026, 11, 4, tzinfo=UTC),
        )
    )
    definition = MetricDefinition(
        id=uuid4(),
        source_system="official_api",
        metric_key="work_views",
        metric_tier="content_performance",
        display_name="作品播放量",
        value_type="count",
        definition="Verified view count for one published work",
        aggregation_rule="sum",
        period_semantics="period_delta",
        definition_version=1,
        status="active",
    )
    db_session.add(definition)
    db_session.flush()
    for index, (start, end, value) in enumerate(
        [
            ("2026-11-01T00:00:00+00:00", "2026-11-02T00:00:00+00:00", "20"),
            ("2026-11-02T00:00:00+00:00", "2026-11-03T00:00:00+00:00", "30"),
        ]
    ):
        db_session.add(
            MetricObservation(
                id=uuid4(),
                store_id=store.id,
                metric_definition_id=definition.id,
                metric_key="work_views",
                metric_tier="content_performance",
                value_numeric=Decimal(value),
                unit="count",
                source_system="official_api",
                source_record_id=f"verified-work-001-{index}",
                period_start=datetime.fromisoformat(start),
                period_end=datetime.fromisoformat(end),
                period_timezone="UTC",
                collected_at=datetime(2026, 11, 4 + index, tzinfo=UTC),
                definition_version=1,
                integrity_status="complete",
                authenticity_status="official_api",
                sync_status="current",
                deduplication_key=f"w{index}" * 32,
                published_work_id=work.id,
                marketing_task_id=task.id,
            )
        )
    db_session.flush()
    headers = _login(identity_client, "work-trend@example.com", store.id)

    response = identity_client.get("/api/v1/effects/overview", headers=headers)

    assert response.status_code == 200, response.text
    breakdown = response.json()["content_performance"]
    assert len(breakdown) == 1
    assert breakdown[0]["published_work_id"] == str(work.id)
    assert breakdown[0]["marketing_task_id"] == str(task.id)
    assert breakdown[0]["comparison"]["status"] == "available"
    assert breakdown[0]["comparison"]["change_percent"] == "50.00"
    assert [point["value"] for point in breakdown[0]["points"]] == ["20", "30"]


def test_attribution_reversal_preserves_snapshot_and_allows_replacement(
    identity_client, db_session, monkeypatch
):
    import store_operator.auth.router as auth_router

    monkeypatch.setattr(auth_router, "redis_client", FakeRedis())
    user, store = _identity(db_session, "reversal@example.com", "Reversal Shop")
    task = MarketingTask(
        id=uuid4(),
        store_id=store.id,
        task_type="full_marketing",
        lifecycle_status="draft",
        title="Attribution reversal task",
        version=1,
        requirement_draft_json={"goal": "Test reversal"},
        strategy_draft_json={},
        task_options_json={},
        created_by_user_id=user.id,
    )
    db_session.add(task)
    db_session.flush()
    work = PublishedWork(
        id=uuid4(),
        store_id=store.id,
        task_id=task.id,
        channel_key="douyin",
        external_work_id="verified-work-reversal",
        ownership_status="verified_platform_api",
        verified_at=datetime.now(UTC),
    )
    db_session.add(work)
    db_session.flush()
    db_session.add(
        WorkOwnershipEvidence(
            id=uuid4(),
            store_id=store.id,
            published_work_id=work.id,
            evidence_type="platform_api",
            evidence_status="verified",
            source_system="douyin",
            evidence_ref="https://platform.example.test/works/verified-work-reversal",
            evidence_payload_json={"verified": True},
            verified_by_user_id=user.id,
            verified_at=datetime.now(UTC),
        )
    )
    outcome = BusinessOutcomeEvidence(
        id=uuid4(),
        store_id=store.id,
        outcome_type="orders",
        value_numeric=Decimal("5"),
        source_system="douyin",
        source_record_id="order-report-reversal",
        source_evidence_ref="https://platform.example.test/orders/report-1",
        occurred_at=datetime.now(UTC),
        authenticity_status="official_api",
        integrity_status="complete",
        deduplication_key="r" * 64,
    )
    db_session.add(outcome)
    db_session.flush()
    headers = _login(identity_client, "reversal@example.com", store.id)
    payload = {
        "marketing_task_id": str(task.id),
        "published_work_id": str(work.id),
        "outcome_evidence_id": str(outcome.id),
        "attribution_method": "platform_reported",
        "evidence_strength": "strong",
        "allocation_percent": "100",
    }
    first = identity_client.post("/api/v1/effects/attributions", headers=headers, json=payload)
    assert first.status_code == 200, first.text
    first_item = first.json()["item"]
    original_snapshot = first_item["snapshot"]
    assert first_item["attribution_version"] == 1

    replay = identity_client.post("/api/v1/effects/attributions", headers=headers, json=payload)
    assert replay.status_code == 200, replay.text
    assert replay.json()["replayed"] is True
    assert replay.json()["item"]["id"] == first_item["id"]

    changed_payload = {**payload, "evidence_strength": "medium", "allocation_percent": "80"}
    changed = identity_client.post(
        "/api/v1/effects/attributions", headers=headers, json=changed_payload
    )
    assert changed.status_code == 200, changed.text
    changed_item = changed.json()["item"]
    assert changed_item["attribution_version"] == 2
    assert changed_item["supersedes_attribution_id"] == first_item["id"]

    reversed_response = identity_client.post(
        f"/api/v1/effects/attributions/{changed_item['id']}/reversal",
        headers=headers,
        json={"reason": "平台订单归属核对后发现关联错误"},
    )
    assert reversed_response.status_code == 200, reversed_response.text
    reversed_item = reversed_response.json()["item"]
    assert reversed_item["status"] == "rejected"
    assert reversed_item["reversal_reason"] == "平台订单归属核对后发现关联错误"
    assert reversed_item["snapshot"] == changed_item["snapshot"]
    assert reversed_item["snapshot"] != original_snapshot

    replacement = identity_client.post(
        "/api/v1/effects/attributions", headers=headers, json=changed_payload
    )
    assert replacement.status_code == 200, replacement.text
    replacement_item = replacement.json()["item"]
    assert replacement_item["status"] == "active"
    assert replacement_item["attribution_version"] == 3
    assert replacement_item["supersedes_attribution_id"] == changed_item["id"]


def test_metric_observation_cannot_reference_another_stores_published_work(
    identity_client, db_session, monkeypatch
):
    import store_operator.auth.router as auth_router

    monkeypatch.setattr(auth_router, "redis_client", FakeRedis())
    _, store_a = _identity(db_session, "work-scope-a@example.com", "Work Scope A")
    _, store_b = _identity(db_session, "work-scope-b@example.com", "Work Scope B")
    definition = MetricDefinition(
        id=uuid4(),
        source_system="manual",
        metric_key="scope_test_views",
        metric_tier="content_performance",
        display_name="播放量",
        value_type="count",
        definition="Manual views report",
        aggregation_rule="sum",
        period_semantics="period_delta",
        definition_version=1,
        status="active",
    )
    work = PublishedWork(
        id=uuid4(),
        store_id=store_b.id,
        channel_key="douyin",
        external_work_id="private-to-store-b",
        ownership_status="merchant_claim",
    )
    db_session.add_all([definition, work])
    db_session.flush()
    headers = _login(identity_client, "work-scope-a@example.com", store_a.id)

    response = identity_client.post(
        "/api/v1/effects/observations",
        headers=headers,
        json={
            "metric_key": "scope_test_views",
            "value_numeric": "10",
            "period_timezone": "Asia/Tokyo",
            "published_work_id": str(work.id),
        },
    )

    assert response.status_code == 404


def test_effects_overview_does_not_compare_gaps_or_zero_baselines(
    identity_client, db_session, monkeypatch
):
    import store_operator.auth.router as auth_router

    monkeypatch.setattr(auth_router, "redis_client", FakeRedis())
    _, store = _identity(db_session, "trend-edge@example.com", "Trend Edge Shop")
    definitions = [
        MetricDefinition(
            id=uuid4(),
            source_system="official_api",
            metric_key=metric_key,
            metric_tier="content_performance",
            display_name=metric_key,
            value_type="count",
            definition="Verified period metric",
            aggregation_rule="sum",
            period_semantics="period_delta",
            definition_version=1,
            status="active",
        )
        for metric_key in ("gap_views", "zero_views")
    ]
    db_session.add_all(definitions)
    db_session.flush()
    observations = [
        ("gap_views", "2026-11-01T00:00:00+00:00", "2026-11-02T00:00:00+00:00", "10", "g1"),
        ("gap_views", "2026-11-04T00:00:00+00:00", "2026-11-05T00:00:00+00:00", "20", "g2"),
        ("zero_views", "2026-11-01T00:00:00+00:00", "2026-11-02T00:00:00+00:00", "0", "z1"),
        ("zero_views", "2026-11-02T00:00:00+00:00", "2026-11-03T00:00:00+00:00", "10", "z2"),
    ]
    definition_by_key = {item.metric_key: item for item in definitions}
    for metric_key, start, end, value, key in observations:
        db_session.add(
            MetricObservation(
                id=uuid4(),
                store_id=store.id,
                metric_definition_id=definition_by_key[metric_key].id,
                metric_key=metric_key,
                metric_tier="content_performance",
                value_numeric=Decimal(value),
                unit="count",
                source_system="official_api",
                source_record_id=key,
                period_start=datetime.fromisoformat(start),
                period_end=datetime.fromisoformat(end),
                period_timezone="UTC",
                collected_at=datetime(2026, 11, 6, tzinfo=UTC),
                definition_version=1,
                integrity_status="complete",
                authenticity_status="official_api",
                sync_status="current",
                deduplication_key=key.ljust(64, "0"),
            )
        )
    db_session.flush()
    headers = _login(identity_client, "trend-edge@example.com", store.id)

    response = identity_client.get("/api/v1/effects/overview", headers=headers)

    assert response.status_code == 200, response.text
    comparisons = {
        item["metric_key"]: item["comparison"] for item in response.json()["trends"]
    }
    assert comparisons["gap_views"]["status"] == "insufficient_samples"
    assert comparisons["gap_views"]["change_percent"] is None
    assert comparisons["zero_views"]["status"] == "zero_baseline"
    assert comparisons["zero_views"]["change_percent"] is None


def test_douyin_capability_check_distinguishes_readback_from_metrics_and_versions_snapshots(
    identity_client, db_session, monkeypatch
):
    import store_operator.auth.router as auth_router

    monkeypatch.setattr(auth_router, "redis_client", FakeRedis())
    _, store = _identity(db_session, "capabilities@example.com", "Capabilities Shop")
    headers = _login(identity_client, "capabilities@example.com", store.id)

    first = identity_client.post(
        "/api/v1/effects/data-source-capabilities/check", headers=headers
    )
    assert first.status_code == 200, first.text
    first_items = {item["capability_key"]: item for item in first.json()["items"]}
    assert first.json()["total"] == 3
    assert first_items["published_work_readback"]["status"] == "unsupported"
    assert first_items["content_metrics_read"]["status"] == "unsupported"
    assert first_items["business_outcome_read"]["status"] == "unsupported"

    second = identity_client.post(
        "/api/v1/effects/data-source-capabilities/check", headers=headers
    )
    assert second.status_code == 200, second.text
    assert {item["snapshot_version"] for item in second.json()["items"]} == {2}

    latest = identity_client.get(
        "/api/v1/effects/data-source-capabilities", headers=headers
    )
    assert latest.status_code == 200
    latest_items = {item["capability_key"]: item for item in latest.json()["items"]}
    assert latest_items["content_metrics_read"]["reason"]
    assert "video.list" in latest_items["published_work_readback"]["required_scopes"]


def test_future_observation_window_is_marked_accumulating_and_excluded_from_trends(
    identity_client, db_session, monkeypatch
):
    import store_operator.auth.router as auth_router

    monkeypatch.setattr(auth_router, "redis_client", FakeRedis())
    _, store = _identity(db_session, "window@example.com", "Window Shop")
    definition = MetricDefinition(
        id=uuid4(),
        source_system="official_api",
        metric_key="future_views",
        metric_tier="content_performance",
        display_name="未来周期播放量",
        value_type="count",
        definition="Metric for a not-yet-complete observation window",
        aggregation_rule="sum",
        period_semantics="period_delta",
        definition_version=1,
        status="active",
    )
    now = datetime.now(UTC)
    observation = MetricObservation(
        id=uuid4(),
        store_id=store.id,
        metric_definition_id=definition.id,
        metric_key="future_views",
        metric_tier="content_performance",
        value_numeric=Decimal("50"),
        unit="count",
        source_system="official_api",
        source_record_id="future-window-1",
        period_start=now - timedelta(hours=1),
        period_end=now + timedelta(hours=1),
        period_timezone="UTC",
        collected_at=now,
        definition_version=1,
        integrity_status="complete",
        authenticity_status="official_api",
        sync_status="current",
        deduplication_key="f" * 64,
    )
    db_session.add_all([definition, observation])
    db_session.flush()
    headers = _login(identity_client, "window@example.com", store.id)

    overview = identity_client.get("/api/v1/effects/overview", headers=headers)
    history = identity_client.get("/api/v1/effects/observations", headers=headers)

    assert overview.status_code == 200, overview.text
    assert overview.json()["data_status"] == "unavailable"
    assert overview.json()["trends"] == []
    assert overview.json()["data_quality"]["accumulating_observations"] == 1
    assert overview.json()["items"][0]["status"] == "accumulating"
    assert history.status_code == 200, history.text
    assert history.json()["items"][0]["observation_window_status"] == "accumulating"


def _minimal_metrics_xlsx() -> bytes:
    workbook = BytesIO()
    with ZipFile(workbook, "w") as archive:
        archive.writestr(
            "xl/workbook.xml",
            """<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
              xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
              <sheets><sheet name="Metrics" sheetId="1" r:id="rId1"/></sheets>
            </workbook>""",
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            """<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
              <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"
                Target="worksheets/sheet1.xml"/>
            </Relationships>""",
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            """<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
              <sheetData>
                <row r="1">
                  <c r="A1" t="inlineStr"><is><t>metric_key</t></is></c>
                  <c r="B1" t="inlineStr"><is><t>value_numeric</t></is></c>
                  <c r="C1" t="inlineStr"><is><t>period_timezone</t></is></c>
                </row>
                <row r="2">
                  <c r="A2" t="inlineStr"><is><t>views</t></is></c>
                  <c r="B2"><v>120</v></c>
                  <c r="C2" t="inlineStr"><is><t>Asia/Tokyo</t></is></c>
                </row>
              </sheetData>
            </worksheet>""",
        )
    return workbook.getvalue()


def test_xlsx_metric_import_creates_merchant_reported_observation(
    identity_client, db_session, monkeypatch
):
    import store_operator.auth.router as auth_router

    monkeypatch.setattr(auth_router, "redis_client", FakeRedis())
    _, store = _identity(db_session, "xlsx-import@example.com", "XLSX Import Shop")
    _ensure_manual_metric_definition(
        db_session,
        metric_key="views",
        metric_tier="content_performance",
        display_name="播放/浏览",
        definition="Views within a period",
    )
    headers = _login(identity_client, "xlsx-import@example.com", store.id)

    response = identity_client.post(
        "/api/v1/effects/import-xlsx",
        headers=headers,
        json={
            "file_name": "metrics.xlsx",
            "file_base64": base64.b64encode(_minimal_metrics_xlsx()).decode("ascii"),
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["created"] == 1
    assert response.json()["duplicates_skipped"] == 0
    batch = db_session.query(MetricImportBatch).filter_by(store_id=store.id).one()
    assert batch.source_format == "xlsx"
    observation = db_session.query(MetricObservation).filter_by(store_id=store.id).one()
    assert observation.value_numeric == Decimal("120")
    assert observation.authenticity_status == "merchant_reported"
