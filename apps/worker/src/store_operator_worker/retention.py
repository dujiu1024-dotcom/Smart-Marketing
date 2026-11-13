from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from store_operator.db import SessionLocal
from store_operator.models import (  # type: ignore[import-untyped]
    HotTopic,
    HotTopicHeatSample,
    HotTopicRetentionRun,
    StoreOpportunity,
)

from store_operator_worker.celery_app import celery_app

logger = logging.getLogger(__name__)

RETENTION_DAYS = 3
BATCH_SIZE = 500


def _trend_within_window(
    db: Session, topic_ids: list[UUID], window_start: datetime
) -> dict[UUID, tuple[Decimal, Decimal, int]]:
    """返回窗口内每个主题的 (首次热度, 末次热度, 样本数)。"""
    if not topic_ids:
        return {}
    rows = db.execute(
        select(
            HotTopicHeatSample.hot_topic_id,
            HotTopicHeatSample.heat_value,
        )
        .where(
            HotTopicHeatSample.hot_topic_id.in_(topic_ids),
            HotTopicHeatSample.observed_at >= window_start,
        )
        .order_by(HotTopicHeatSample.hot_topic_id, HotTopicHeatSample.observed_at)
    ).all()
    trend: dict[UUID, list[object]] = {}
    for topic_id, heat_value in rows:
        values = trend.setdefault(topic_id, [heat_value, heat_value, 0])
        values[1] = heat_value
        values[2] = int(values[2]) + 1
    return {topic_id: (values[0], values[1], values[2]) for topic_id, values in trend.items()}


def retention_decision(
    *,
    last_seen_at: datetime,
    first_heat: Decimal | None,
    last_heat: Decimal | None,
    sample_count: int,
    cutoff: datetime,
) -> str | None:
    """返回 'stale' / 'trend' / None（保留）。"""
    if last_seen_at < cutoff:
        return "stale"
    # 样本不足 2 个时无法判断趋势，按“未知”保留，避免新条目被误删。
    if (
        sample_count >= 2
        and first_heat is not None
        and last_heat is not None
        and last_heat <= first_heat
    ):
        return "trend"
    return None


def purge_hot_topics(
    *,
    now: datetime | None = None,
    session_factory: sessionmaker[Session] = SessionLocal,
) -> dict[str, object]:
    """按保留策略清理热点池：超过 3 天未再采集，或窗口内热度未上升。

    被门店机会引用的热点不物理删除，只标记 expired，避免破坏已采纳/已下发的记录。
    """
    started_at = now or datetime.now(UTC)
    cutoff = started_at - timedelta(days=RETENTION_DAYS)
    stats = {
        "scanned": 0,
        "deleted": 0,
        "retired": 0,
        "kept": 0,
        "deleted_stale": 0,
        "deleted_trend": 0,
    }
    run_id = uuid4()
    with session_factory.begin() as db:
        db.add(
            HotTopicRetentionRun(
                id=run_id,
                started_at=started_at,
                status="succeeded",
                **stats,
            )
        )

    cursor: UUID | None = None
    try:
        while True:
            with session_factory.begin() as db:
                statement = select(HotTopic).order_by(HotTopic.id).limit(BATCH_SIZE)
                if cursor is not None:
                    statement = statement.where(HotTopic.id > cursor)
                topics = list(db.scalars(statement).all())
                if not topics:
                    break
                cursor = topics[-1].id
                stats["scanned"] += len(topics)

                fresh_ids = [topic.id for topic in topics if topic.last_seen_at >= cutoff]
                trend = _trend_within_window(db, fresh_ids, cutoff)

                candidates: list[tuple[HotTopic, str]] = []
                for topic in topics:
                    first_heat: Decimal | None = None
                    last_heat: Decimal | None = None
                    sample_count = 0
                    first_last = trend.get(topic.id)
                    if first_last is not None:
                        first_heat, last_heat, sample_count = first_last
                    reason = retention_decision(
                        last_seen_at=topic.last_seen_at,
                        first_heat=first_heat,
                        last_heat=last_heat,
                        sample_count=sample_count,
                        cutoff=cutoff,
                    )
                    if reason is not None:
                        candidates.append((topic, reason))
                stats["kept"] += len(topics) - len(candidates)
                if not candidates:
                    continue

                candidate_ids = [topic.id for topic, _ in candidates]
                referenced = set(
                    db.scalars(
                        select(StoreOpportunity.hot_topic_id)
                        .where(StoreOpportunity.hot_topic_id.in_(candidate_ids))
                        .distinct()
                    ).all()
                )
                for topic, reason in candidates:
                    if topic.id in referenced:
                        # 门店已采纳/已下发的记录依赖热点标题；保留记录，仅退出热点池。
                        topic.evidence_status = "expired"
                        topic.expires_at = started_at
                        stats["retired"] += 1
                        continue
                    db.delete(topic)
                    stats["deleted"] += 1
                    if reason == "stale":
                        stats["deleted_stale"] += 1
                    else:
                        stats["deleted_trend"] += 1
    except Exception as exc:
        with session_factory.begin() as db:
            run = db.get(HotTopicRetentionRun, run_id)
            if run is not None:
                run.status = "failed"
                run.finished_at = datetime.now(UTC)
                run.error_code = "HOT_TOPIC_RETENTION_FAILED"
                run.error_summary = f"{type(exc).__name__}: {exc}"[:500]
        logger.exception("hot_topic_retention failed")
        raise

    finished_at = datetime.now(UTC)
    with session_factory.begin() as db:
        run = db.get(HotTopicRetentionRun, run_id)
        if run is not None:
            run.finished_at = finished_at
            for key, value in stats.items():
                setattr(run, key, value)
    result = {
        **stats,
        "run_id": str(run_id),
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "duration_ms": int((finished_at - started_at).total_seconds() * 1000),
    }
    logger.info("hot_topic_retention completed %s", result)
    return result


@celery_app.task(name="hot_topics.purge_retention", ignore_result=True)  # type: ignore[untyped-decorator]
def purge_retention() -> None:
    purge_hot_topics()
