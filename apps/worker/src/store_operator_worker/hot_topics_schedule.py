"""热点定时采集与每日匹配对账。

- 每天 08:00 / 18:00（Asia/Shanghai）为每个活跃门店创建一个采集+匹配 Job。
- 幂等键按“时段（YYYYMMDD-HH）+ 门店作用域”生成，重复触发不会重复建 Job。
- 单店失败只记录日志，不影响其他门店和下一次调度。
"""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from store_operator.db import SessionLocal  # type: ignore[import-untyped]
from store_operator.jobs.service import create_job  # type: ignore[import-untyped]
from store_operator.models import HotTopicSource, Store  # type: ignore[import-untyped]

from store_operator_worker.celery_app import celery_app
from store_operator_worker.hot_topic_matching import reconcile_all_stores

logger = logging.getLogger(__name__)

SHANGHAI = ZoneInfo("Asia/Shanghai")
SCHEDULE_IDEMPOTENCY_PREFIX = "hot-topic-schedule"


def _enabled_source_ids(db) -> list[str]:
    rows = db.scalars(
        select(HotTopicSource.id).where(
            HotTopicSource.enabled.is_(True),
            HotTopicSource.source_type.in_(("rss", "public_feed")),
            HotTopicSource.terms_url.is_not(None),
            HotTopicSource.permitted_use.is_not(None),
        )
    ).all()
    return sorted(str(source_id) for source_id in rows)


@celery_app.task(name="hot_topics.scheduled_collect")  # type: ignore[untyped-decorator]
def scheduled_collect() -> dict[str, object]:
    now = datetime.now(SHANGHAI)
    slot = now.strftime("%Y%m%d-%H")
    with SessionLocal() as db:
        source_ids = _enabled_source_ids(db)
        stores = db.scalars(
            select(Store).where(Store.status == "active").order_by(Store.created_at)
        ).all()
        if not source_ids:
            logger.warning("hot topic scheduled collection skipped: no enabled sources")
            return {"slot": slot, "status": "skipped", "reason": "NO_ENABLED_SOURCES"}
        if not stores:
            logger.warning("hot topic scheduled collection skipped: no active stores")
            return {"slot": slot, "status": "skipped", "reason": "NO_ACTIVE_STORES"}

        items: list[dict[str, object]] = []
        for store in stores:
            try:
                job = create_job(
                    db,
                    job_type="hot_topics.collect_and_match.v1",
                    payload_ref={"schema_version": 1, "source_ids": source_ids},
                    idempotency_key=f"{SCHEDULE_IDEMPOTENCY_PREFIX}:{slot}",
                    store_id=store.id,
                    actor_type="system",
                    actor_user_id=None,
                    queue_name="default",
                    priority=0,
                    max_attempts=3,
                    timeout_seconds=600,
                )
                db.commit()
                items.append(
                    {"store_id": str(store.id), "job_id": str(job.id), "status": job.status}
                )
            except Exception as exc:  # 单店失败不阻塞其他门店
                db.rollback()
                logger.exception("hot topic scheduled job failed for store %s", store.id)
                items.append(
                    {
                        "store_id": str(store.id),
                        "error_code": type(exc).__name__,
                        "summary": str(exc)[:200],
                    }
                )
    logger.info("hot topic scheduled collection slot=%s items=%s", slot, items)
    return {"slot": slot, "status": "queued", "stores": len(stores), "items": items}


@celery_app.task(name="hot_topics.reconcile_matches")  # type: ignore[untyped-decorator]
def reconcile_matches() -> dict[str, object]:
    result = reconcile_all_stores()
    logger.info("hot topic reconciliation completed %s", result)
    return result
