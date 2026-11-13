"""Worker 指标同步 Job 的最小集成测试。

需要可用的 PostgreSQL（与 apps/api 测试一致）。若库未迁移到 0025 或缺少
抓取口径的 metric_definitions 种子，则跳过，避免在未初始化环境误报。
"""

from datetime import UTC, datetime, timedelta
from threading import Event
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from store_operator.auth.security import hash_password
from store_operator.config import settings
from store_operator.db import engine
from store_operator.models.channel_delivery import ChannelAccount
from store_operator.models.identity import Store, StoreMembership, User
from store_operator.models.opportunity_effects import (
    MetricObservation,
    MetricSyncCursor,
)

from store_operator_worker.handlers import (
    JobExecutionContext,
    JobExecutionError,
    clear_job_handlers_for_testing,
)
from store_operator_worker.metric_sync import (
    JOB_TYPE,
    MerchantAuthorizedCollector,
    register_metric_sync_handlers,
)

pytestmark = pytest.mark.skipif(
    engine.dialect.name != "postgresql",
    reason="metric sync integration tests require PostgreSQL",
)

SessionFactory = sessionmaker(
    bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
)


def _database_ready() -> bool:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1 FROM metric_sync_cursors LIMIT 1"))
            count = connection.execute(
                text(
                    "SELECT count(*) FROM metric_definitions "
                    "WHERE source_system = 'merchant_authorized_scrape'"
                )
            ).scalar_one()
            return int(count) > 0
    except (SQLAlchemyError, OSError):
        return False


@pytest.fixture()
def db_ready() -> None:
    if not _database_ready():
        pytest.skip("database is not migrated to 0025 with scrape metric definitions")


@pytest.fixture()
def store_account(db_ready):
    suffix = uuid4().hex[:8]
    with SessionFactory.begin() as db:
        user = User(
            id=uuid4(),
            email_normalized=f"metric-worker-{suffix}@example.com",
            password_hash=hash_password("test-password-123"),
            status="active",
        )
        store = Store(
            id=uuid4(), name=f"Metric Worker {suffix}", timezone="Asia/Shanghai", status="active"
        )
        db.add_all([user, store])
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
        account = ChannelAccount(
            id=uuid4(),
            store_id=store.id,
            provider="douyin",
            external_account_id=f"open-{suffix}",
            display_name="抖音测试号",
            granted_scopes=["video.list"],
            access_token_secret_ref="secrets://channel/test/access",
            refresh_token_secret_ref="secrets://channel/test/refresh",
            access_token_expires_at=datetime.now(UTC) + timedelta(days=1),
            status="active",
            connected_by_user_id=user.id,
        )
        db.add(account)
        db.flush()
        store_id, account_id = store.id, account.id
    yield store_id, account_id
    with SessionFactory.begin() as db:
        db.execute(
            MetricObservation.__table__.delete().where(
                MetricObservation.store_id == store_id
            )
        )
        db.execute(
            MetricSyncCursor.__table__.delete().where(
                MetricSyncCursor.store_id == store_id
            )
        )
        db.execute(
            ChannelAccount.__table__.delete().where(ChannelAccount.store_id == store_id)
        )
        db.execute(StoreMembership.__table__.delete().where(StoreMembership.store_id == store_id))
        db.execute(Store.__table__.delete().where(Store.id == store_id))
        db.execute(User.__table__.delete().where(User.id == user.id))


def _context(store_id) -> JobExecutionContext:
    return JobExecutionContext(
        job_id=uuid4(),
        store_id=store_id,
        attempt_id=uuid4(),
        lease_token=uuid4(),
        worker_id="metric-test",
        deadline_at=datetime.now(UTC) + timedelta(minutes=5),
        cancellation_requested=Event(),
        lease_lost=Event(),
        update_progress_callback=lambda _current, _total: None,
    )


def _snapshot(captured_at: datetime, followers: str = "1.2万") -> dict[str, object]:
    return {
        "schema_version": 1,
        "platform": "douyin",
        "outcome": "verified",
        "captured_at": captured_at.isoformat(),
        "account_page_text": (
            f"粉丝\n{followers}\n获赞\n3.4万\n关注\n12\n作品数\n56\n"
            "近7日\n播放量\n1,234\n+12%"
        ),
        "works": [],
    }


@pytest.fixture()
def registered_handler():
    clear_job_handlers_for_testing()
    register_metric_sync_handlers(SessionFactory)
    yield
    clear_job_handlers_for_testing()


def test_sync_writes_scrape_observations_and_cursor(
    monkeypatch, registered_handler, store_account
):
    store_id, account_id = store_account
    captured_at = datetime(2026, 11, 13, 6, 30, tzinfo=UTC)
    monkeypatch.setattr(settings, "metric_sync_enabled", True)
    monkeypatch.setattr(settings, "metric_collector_base_url", "http://collector.local")
    monkeypatch.setattr(
        MerchantAuthorizedCollector,
        "collect",
        lambda self, **kwargs: _snapshot(captured_at),
    )

    from store_operator_worker.handlers import resolve_job_handler

    handler = resolve_job_handler(JOB_TYPE)
    assert handler is not None
    result = handler(
        _context(store_id),
        {
            "schema_version": 1,
            "channel_account_id": str(account_id),
            "scopes": ["account"],
        },
    )

    assert result["results"][0]["status"] == "succeeded"
    assert result["results"][0]["created"] >= 4

    with SessionFactory() as db:
        observations = db.scalars(
            select(MetricObservation).where(MetricObservation.store_id == store_id)
        ).all()
        assert observations
        assert all(
            item.authenticity_status == "merchant_authorized_scrape"
            for item in observations
        )
        assert all(item.source_system != "official_api" for item in observations)
        assert {item.observation_scope for item in observations} == {"account"}
        cursor = db.scalar(
            select(MetricSyncCursor).where(
                MetricSyncCursor.store_id == store_id,
                MetricSyncCursor.channel_account_id == account_id,
                MetricSyncCursor.scope == "account",
            )
        )
        assert cursor is not None
        assert cursor.status == "succeeded"
        assert cursor.last_success_at is not None
        assert cursor.last_error_code is None
        assert cursor.consecutive_failures == 0
        assert cursor.cursor_json["last_captured_at"]


def test_sync_deduplicates_same_snapshot(monkeypatch, registered_handler, store_account):
    store_id, account_id = store_account
    captured_at = datetime(2026, 11, 13, 7, 0, tzinfo=UTC)
    monkeypatch.setattr(settings, "metric_sync_enabled", True)
    monkeypatch.setattr(settings, "metric_collector_base_url", "http://collector.local")
    monkeypatch.setattr(
        MerchantAuthorizedCollector,
        "collect",
        lambda self, **kwargs: _snapshot(captured_at),
    )

    from store_operator_worker.handlers import resolve_job_handler

    handler = resolve_job_handler(JOB_TYPE)
    payload = {
        "schema_version": 1,
        "channel_account_id": str(account_id),
        "scopes": ["account"],
    }
    first = handler(_context(store_id), payload)
    second = handler(_context(store_id), payload)

    assert first["results"][0]["created"] >= 4
    assert second["results"][0]["created"] == 0

    with SessionFactory() as db:
        count = len(
            db.scalars(
                select(MetricObservation.id).where(
                    MetricObservation.store_id == store_id
                )
            ).all()
        )
        assert count == first["results"][0]["created"]


def test_sync_without_collector_fails_as_configuration_gap(
    monkeypatch, registered_handler, store_account
):
    store_id, account_id = store_account
    monkeypatch.setattr(settings, "metric_sync_enabled", False)
    monkeypatch.setattr(settings, "metric_collector_base_url", None)

    from store_operator_worker.handlers import resolve_job_handler

    handler = resolve_job_handler(JOB_TYPE)
    with pytest.raises(JobExecutionError) as excinfo:
        handler(
            _context(store_id),
            {
                "schema_version": 1,
                "channel_account_id": str(account_id),
                "scopes": ["account"],
            },
        )
    assert excinfo.value.code == "METRIC_COLLECTOR_NOT_CONFIGURED"
    assert excinfo.value.retryable is False

    with SessionFactory() as db:
        cursor = db.scalar(
            select(MetricSyncCursor).where(
                MetricSyncCursor.store_id == store_id,
                MetricSyncCursor.channel_account_id == account_id,
                MetricSyncCursor.scope == "account",
            )
        )
        assert cursor is not None
        assert cursor.status == "unsupported"
        assert cursor.last_error_code == "METRIC_COLLECTOR_NOT_CONFIGURED"
        assert cursor.consecutive_failures == 1
        assert cursor.last_success_at is None
        observations = db.scalars(
            select(MetricObservation.id).where(MetricObservation.store_id == store_id)
        ).all()
        assert observations == []
