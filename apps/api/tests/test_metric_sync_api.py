from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select

from store_operator.auth.security import hash_password
from store_operator.effects.metric_ingest import ingest_snapshot
from store_operator.models.channel_delivery import ChannelAccount
from store_operator.models.identity import (
    PlatformAdminGrant,
    Store,
    StoreMembership,
    User,
)
from store_operator.models.job_runtime import Job
from store_operator.models.opportunity_effects import MetricObservation

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
    user = User(
        id=uuid4(),
        email_normalized=email,
        password_hash=hash_password("test-password-123"),
        status="active",
    )
    db.add(user)
    db.flush()
    store = Store(id=uuid4(), name=store_name, timezone="Asia/Shanghai", status="active")
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
    return user, store


def _login(client, email: str, store_id=None):
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "test-password-123"},
        headers=ORIGIN,
    )
    assert response.status_code == 200, response.text
    headers = {**ORIGIN, "X-CSRF-Token": response.json()["csrf_token"]}
    if store_id is not None:
        headers["X-Store-ID"] = str(store_id)
    return headers


def _admin_login(client, email: str):
    response = client.post(
        "/api/v1/admin/auth/login",
        json={"email": email, "password": "test-password-123"},
        headers=ORIGIN,
    )
    assert response.status_code == 200, response.text
    return {**ORIGIN, "X-CSRF-Token": response.json()["csrf_token"]}


def _account(db, store: Store, user: User, *, status: str = "active") -> ChannelAccount:
    account = ChannelAccount(
        id=uuid4(),
        store_id=store.id,
        provider="douyin",
        external_account_id=f"open-{uuid4()}",
        display_name="测试账号",
        granted_scopes=["video.list"],
        access_token_secret_ref="secrets://channel/test/access",
        refresh_token_secret_ref="secrets://channel/test/refresh",
        access_token_expires_at=datetime.now(UTC) + timedelta(days=1),
        status=status,
        connected_by_user_id=user.id,
    )
    db.add(account)
    db.flush()
    return account


def test_metric_sync_creates_job_and_status_is_store_scoped(
    identity_client, db_session, monkeypatch
):
    import store_operator.auth.router as auth_router

    monkeypatch.setattr(auth_router, "redis_client", FakeRedis())
    user_a, store_a = _identity(db_session, "metric-a@example.com", "Metric A")
    _, store_b = _identity(db_session, "metric-b@example.com", "Metric B")
    account = _account(db_session, store_a, user_a)
    headers = _login(identity_client, "metric-a@example.com", store_a.id)

    response = identity_client.post(
        "/api/v1/effects/sync",
        json={"channel_account_id": str(account.id), "scopes": ["account", "work"]},
        headers={**headers, "Idempotency-Key": "metric-sync-key-1"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["job"]["job_type"] == "metrics.sync_channel_account.v1"
    assert body["scopes"] == ["account", "work"]

    job = db_session.scalar(select(Job).where(Job.id == body["job"]["id"]))
    assert job is not None
    assert job.payload_ref["channel_account_id"] == str(account.id)

    status_response = identity_client.get(
        "/api/v1/effects/sync/status",
        params={"channel_account_id": str(account.id)},
        headers=headers,
    )
    assert status_response.status_code == 200, status_response.text
    status_body = status_response.json()
    assert status_body["latest_job"]["id"] == str(job.id)
    assert status_body["collector_configured"] is False
    assert status_body["sync_in_progress"] is True
    assert status_body["last_success_at"] is None

    # 未配置采集端时，按账号查询同步状态仍可正常返回（游标尚未产生）
    all_status = identity_client.get(
        "/api/v1/effects/sync/status", headers=headers
    )
    assert all_status.status_code == 200, all_status.text
    assert all_status.json()["collector_configured"] is False
    assert all_status.json()["cursors"] == []

    # 另一门店无法为该账号建同步任务
    other_headers = _login(identity_client, "metric-b@example.com", store_b.id)
    forbidden = identity_client.post(
        "/api/v1/effects/sync",
        json={"channel_account_id": str(account.id), "scopes": ["account"]},
        headers={**other_headers, "Idempotency-Key": "metric-sync-key-b"},
    )
    assert forbidden.status_code == 404

    other_status = identity_client.get(
        "/api/v1/effects/sync/status",
        params={"channel_account_id": str(account.id)},
        headers=other_headers,
    )
    assert other_status.status_code == 404


def test_metric_sync_rejects_duplicate_running_job_and_inactive_account(
    identity_client, db_session, monkeypatch
):
    import store_operator.auth.router as auth_router

    monkeypatch.setattr(auth_router, "redis_client", FakeRedis())
    user, store = _identity(db_session, "metric-dup@example.com", "Metric Dup")
    account = _account(db_session, store, user)
    headers = _login(identity_client, "metric-dup@example.com", store.id)

    first = identity_client.post(
        "/api/v1/effects/sync",
        json={"channel_account_id": str(account.id), "scopes": ["account"]},
        headers={**headers, "Idempotency-Key": "metric-dup-1"},
    )
    assert first.status_code == 200, first.text
    second = identity_client.post(
        "/api/v1/effects/sync",
        json={"channel_account_id": str(account.id), "scopes": ["account"]},
        headers={**headers, "Idempotency-Key": "metric-dup-2"},
    )
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "METRIC_SYNC_ALREADY_RUNNING"

    revoked = _account(db_session, store, user, status="revoked")
    blocked = identity_client.post(
        "/api/v1/effects/sync",
        json={"channel_account_id": str(revoked.id), "scopes": ["account"]},
        headers={**headers, "Idempotency-Key": "metric-dup-3"},
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "CHANNEL_ACCOUNT_NOT_ACTIVE"


def test_ingest_snapshot_uses_evidence_gate_and_supersedes_corrections(db_session):
    user, store = _identity(db_session, "metric-ingest@example.com", "Metric Ingest")
    account = _account(db_session, store, user)
    captured_at = datetime(2026, 11, 13, 6, 30, tzinfo=UTC)
    payload = {
        "schema_version": 1,
        "platform": "douyin",
        "outcome": "verified",
        "account_page_text": "\n".join(
            [
                "粉丝",
                "1.2万",
                "获赞",
                "3.4万",
                "关注",
                "12",
                "作品数",
                "56",
                "近7日",
                "播放量",
                "1,234",
                "+12%",
                "主页访问量",
                "890",
                "-3%",
            ]
        ),
        "works": [],
    }

    result = ingest_snapshot(
        db_session,
        store_id=store.id,
        account=account,
        scope="account",
        payload=payload,
        captured_at=captured_at,
    )
    assert result["created"] >= 4
    observations = db_session.scalars(
        select(MetricObservation).where(
            MetricObservation.store_id == store.id,
            MetricObservation.channel_account_id == account.id,
            MetricObservation.observation_scope == "account",
        )
    ).all()
    assert observations
    assert all(item.authenticity_status == "merchant_authorized_scrape" for item in observations)
    assert all(item.source_system == "merchant_authorized_scrape" for item in observations)
    followers = next(item for item in observations if item.metric_key == "followers")
    assert followers.value_numeric == Decimal(12000)

    # 同日同快照重复同步不会重复写入
    again = ingest_snapshot(
        db_session,
        store_id=store.id,
        account=account,
        scope="account",
        payload=payload,
        captured_at=captured_at,
    )
    assert again["created"] == 0

    # 同日数值更正写入新版本，并冲正旧观测
    corrected = dict(payload)
    corrected["account_page_text"] = payload["account_page_text"].replace("1.2万", "1.3万")
    correction = ingest_snapshot(
        db_session,
        store_id=store.id,
        account=account,
        scope="account",
        payload=corrected,
        captured_at=captured_at,
    )
    assert correction["created"] >= 1
    successor = db_session.scalar(
        select(MetricObservation).where(
            MetricObservation.store_id == store.id,
            MetricObservation.metric_key == "followers",
            MetricObservation.value_numeric == Decimal(13000),
        )
    )
    assert successor is not None
    assert successor.supersedes_observation_id is not None


def test_observation_query_filters_by_account_scope_and_authenticity(
    identity_client, db_session, monkeypatch
):
    import store_operator.auth.router as auth_router

    monkeypatch.setattr(auth_router, "redis_client", FakeRedis())
    user, store = _identity(db_session, "metric-query@example.com", "Metric Query")
    account = _account(db_session, store, user)
    ingest_snapshot(
        db_session,
        store_id=store.id,
        account=account,
        scope="account",
        payload={
            "schema_version": 1,
            "platform": "douyin",
            "outcome": "verified",
            "account_page_text": "粉丝\n999\n",
            "works": [],
        },
        captured_at=datetime(2026, 11, 13, 3, 0, tzinfo=UTC),
    )
    headers = _login(identity_client, "metric-query@example.com", store.id)
    response = identity_client.get(
        "/api/v1/effects/observations",
        params={
            "channel_account_id": str(account.id),
            "observation_scope": "account",
            "authenticity_status": "merchant_authorized_scrape",
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["channel_account_id"] == str(account.id)
    assert items[0]["observation_scope"] == "account"
    assert items[0]["authenticity_status"] == "merchant_authorized_scrape"

    invalid = identity_client.get(
        "/api/v1/effects/observations",
        params={"observation_scope": "team"},
        headers=headers,
    )
    assert invalid.status_code == 422

    _, other_store = _identity(db_session, "metric-query-b@example.com", "Metric Query B")
    other_headers = _login(identity_client, "metric-query-b@example.com", other_store.id)
    cross_store = identity_client.get(
        "/api/v1/effects/observations",
        params={"channel_account_id": str(account.id), "observation_scope": "account"},
        headers=other_headers,
    )
    assert cross_store.status_code == 404


def test_admin_can_register_and_edit_public_feed_source(identity_client, db_session, monkeypatch):
    import store_operator.auth.router as auth_router
    import store_operator.opportunity_effects_router as effects_router

    monkeypatch.setattr(auth_router, "redis_client", FakeRedis())
    monkeypatch.setattr(
        effects_router.settings, "hot_topic_allowed_hosts", "60s.viki.moe"
    )
    admin = User(
        id=uuid4(),
        email_normalized="source-admin@example.com",
        password_hash=hash_password("test-password-123"),
        status="active",
    )
    db_session.add(admin)
    db_session.flush()
    db_session.add(
        PlatformAdminGrant(
            id=uuid4(), user_id=admin.id, status="active", reason_code="hot-topic-test"
        )
    )
    db_session.flush()
    headers = _admin_login(identity_client, "source-admin@example.com")

    presets = identity_client.get(
        "/api/v1/admin/opportunity-sources/presets", headers=headers
    )
    assert presets.status_code == 200, presets.text
    assert any(item["key"] == "weibo" for item in presets.json()["items"])
    assert presets.json()["allowed_hosts"] == ["60s.viki.moe"]

    created = identity_client.post(
        "/api/v1/admin/opportunity-sources",
        json={
            "source_key": "60s-weibo",
            "display_name": "微博热搜",
            "source_type": "public_feed",
            "source_url": "https://60s.viki.moe/v2/weibo",
            "terms_url": "https://60s.viki.moe/terms",
            "permitted_use": "仅用于热点选题参考，保留来源署名，不转载原文。",
        },
        headers=headers,
    )
    assert created.status_code == 200, created.text
    assert created.json()["source_type"] == "public_feed"

    updated = identity_client.patch(
        f"/api/v1/admin/opportunity-sources/{created.json()['id']}",
        json={"display_name": "微博热搜榜"},
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["display_name"] == "微博热搜榜"

    enabled = identity_client.post(
        f"/api/v1/admin/opportunity-sources/{created.json()['id']}/enable",
        headers=headers,
    )
    assert enabled.status_code == 200, enabled.text
    locked = identity_client.patch(
        f"/api/v1/admin/opportunity-sources/{created.json()['id']}",
        json={"display_name": "改名失败"},
        headers=headers,
    )
    assert locked.status_code == 409
    assert locked.json()["error"]["code"] == "SOURCE_ENABLED_LOCKED"

    disabled = identity_client.post(
        f"/api/v1/admin/opportunity-sources/{created.json()['id']}/disable",
        headers=headers,
    )
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["enabled"] is False
    reopened = identity_client.patch(
        f"/api/v1/admin/opportunity-sources/{created.json()['id']}",
        json={"display_name": "微博热搜榜（停用后可编辑）"},
        headers=headers,
    )
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["display_name"] == "微博热搜榜（停用后可编辑）"

    rejected = identity_client.post(
        "/api/v1/admin/opportunity-sources",
        json={
            "source_key": "unapproved-feed",
            "display_name": "未批准来源",
            "source_type": "rss",
            "source_url": "https://unapproved.example.com/rss",
            "terms_url": "https://unapproved.example.com/terms",
            "permitted_use": "仅用于热点选题参考，保留来源署名，不转载原文。",
        },
        headers=headers,
    )
    assert rejected.status_code == 422
