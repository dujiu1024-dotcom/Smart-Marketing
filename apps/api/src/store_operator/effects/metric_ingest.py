"""指标采集落库的共享证据门禁。

去重键材料与人工录入/导入路径保持一致；采集路径在此基础上附加
`channel_account_id` 与 `observation_scope`，避免不同账号或不同观测范围
的同名指标互相覆盖。
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from store_operator.effects.easel_parsing import (
    LABEL_TO_METRIC_KEY,
    PLATFORM_PROFILES,
    lines_of,
    metrics_with_vs,
    num_by_label,
    parse_num,
)
from store_operator.models.channel_delivery import ChannelAccount
from store_operator.models.opportunity_effects import (
    MetricDefinition,
    MetricObservation,
    MetricSyncCursor,
    PublishedWork,
)

# 采集路径的固定真实性档：商家授权抓取，不得混同 official_api。
SCRAPE_AUTHENTICITY = "merchant_authorized_scrape"
SCRAPE_SOURCE_SYSTEM = "merchant_authorized_scrape"

CURSOR_STATUSES = (
    "idle",
    "running",
    "succeeded",
    "failed",
    "login_required",
    "unsupported",
    "unavailable",
)


def compute_dedupe_key(
    *,
    store_id: UUID,
    source_system: str,
    metric_key: str,
    period_start: datetime | None,
    period_end: datetime | None,
    source_record_id: str | None,
    value_numeric: Decimal | int | None,
    currency: str | None,
    supersedes_observation_id: UUID | None = None,
    published_work_id: UUID | None = None,
    marketing_task_id: UUID | None = None,
    channel_account_id: UUID | None = None,
    observation_scope: str | None = None,
) -> str:
    parts = [
        str(store_id),
        source_system,
        metric_key,
        period_start.isoformat() if period_start else "",
        period_end.isoformat() if period_end else "",
        source_record_id or "",
        str(value_numeric) if value_numeric is not None else "NULL",
        currency or "",
        str(supersedes_observation_id) if supersedes_observation_id else "",
        str(published_work_id) if published_work_id else "",
        str(marketing_task_id) if marketing_task_id else "",
    ]
    # 仅在采集路径追加维度，保持既有手工/导入去重键不变。
    if channel_account_id is not None:
        parts.append(str(channel_account_id))
    if observation_scope is not None:
        parts.append(observation_scope)
    material = "|".join(parts)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def get_or_create_cursor(
    db: Session,
    *,
    store_id: UUID,
    channel_account_id: UUID,
    scope: str,
    source_system: str = SCRAPE_SOURCE_SYSTEM,
) -> MetricSyncCursor:
    cursor = db.scalar(
        select(MetricSyncCursor)
        .where(
            MetricSyncCursor.store_id == store_id,
            MetricSyncCursor.channel_account_id == channel_account_id,
            MetricSyncCursor.scope == scope,
        )
        .with_for_update()
    )
    if cursor is not None:
        return cursor
    cursor = MetricSyncCursor(
        id=uuid4(),
        store_id=store_id,
        channel_account_id=channel_account_id,
        scope=scope,
        source_system=source_system,
        status="idle",
        cursor_json={},
        consecutive_failures=0,
    )
    db.add(cursor)
    db.flush()
    return cursor


def mark_cursor_running(cursor: MetricSyncCursor, *, now: datetime | None = None) -> None:
    cursor.status = "running"
    cursor.last_attempt_at = now or datetime.now(UTC)


def mark_cursor_success(
    cursor: MetricSyncCursor,
    *,
    cursor_json: dict[str, object] | None = None,
    now: datetime | None = None,
) -> None:
    current = now or datetime.now(UTC)
    cursor.status = "succeeded"
    cursor.last_success_at = current
    cursor.last_failure_at = None
    cursor.last_error_code = None
    cursor.last_error_summary = None
    cursor.consecutive_failures = 0
    if cursor_json is not None:
        cursor.cursor_json = cursor_json
        cursor.cursor_version += 1


def mark_cursor_failure(
    cursor: MetricSyncCursor,
    *,
    status: str,
    error_code: str,
    error_summary: str,
    now: datetime | None = None,
) -> None:
    if status not in CURSOR_STATUSES:
        raise ValueError(f"Unsupported cursor status: {status}")
    current = now or datetime.now(UTC)
    cursor.status = status
    cursor.last_failure_at = current
    cursor.last_error_code = error_code[:100]
    cursor.last_error_summary = " ".join(error_summary.split())[:500]
    cursor.consecutive_failures += 1


def day_bucket(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


def account_snapshot_metrics(
    payload: dict[str, Any], *, platform: str, captured_at: datetime
) -> list[dict[str, Any]]:
    """账号范围：概览累计值 + 近 7 日窗口指标。"""
    text = payload.get("account_page_text") or ""
    if not isinstance(text, str) or not text.strip():
        return []
    profile = PLATFORM_PROFILES.get(platform) or {}
    lines = lines_of(text)
    captured_day = day_bucket(captured_at)
    observed: list[dict[str, Any]] = []

    overview = profile.get("overview") or {}
    direction = profile.get("overview_dir") or "after"
    for metric_key, labels in overview.items():
        if not labels:
            continue
        value = num_by_label(lines, list(labels), direction)
        if value is not None:
            observed.append(
                {
                    "metric_key": metric_key,
                    "value": value,
                    "period_start": None,
                    "period_end": captured_day,
                    "record_suffix": "overview",
                }
            )

    value = num_by_label(lines, ["作品数", "笔记数", "内容数"], direction)
    if value is not None and all(item["metric_key"] != "posts" for item in observed):
        observed.append(
            {
                "metric_key": "posts",
                "value": value,
                "period_start": None,
                "period_end": captured_day,
                "record_suffix": "overview",
            }
        )

    window_start = captured_day - timedelta(days=7)
    for item in metrics_with_vs(
        lines,
        list(profile.get("metrics") or []),
        profile.get("metrics_anchor"),
    ):
        metric_key = LABEL_TO_METRIC_KEY.get(item["label"])
        value = parse_num(item["value"])
        if metric_key is None or value is None or value < 0:
            continue
        observed.append(
            {
                "metric_key": metric_key,
                "value": value,
                "period_start": window_start,
                "period_end": captured_day,
                "record_suffix": "window7d",
            }
        )
    return observed


def work_snapshot_metrics(
    payload: dict[str, Any], *, captured_at: datetime
) -> list[dict[str, Any]]:
    """作品范围：采集器返回的作品统计。"""
    raw_works = payload.get("works")
    if not isinstance(raw_works, list):
        return []
    captured_day = day_bucket(captured_at)
    observed: list[dict[str, Any]] = []
    for raw in raw_works:
        if not isinstance(raw, dict):
            continue
        external_id = str(raw.get("platform_content_id") or "").strip()
        stats = raw.get("stats")
        if not external_id or not isinstance(stats, dict):
            continue
        for stat_field, metric_key in (
            ("play_count", "views"),
            ("digg_count", "likes"),
            ("like_count", "likes"),
            ("comment_count", "comments"),
        ):
            raw_value = stats.get(stat_field)
            if raw_value is None:
                continue
            value = parse_num(raw_value)
            if value is None or value < 0:
                continue
            observed.append(
                {
                    "metric_key": metric_key,
                    "value": value,
                    "period_start": None,
                    "period_end": captured_day,
                    "record_suffix": f"work:{external_id}",
                    "external_work_id": external_id,
                }
            )
    return observed


def _load_definitions(db: Session, metric_keys: set[str]) -> dict[str, MetricDefinition]:
    if not metric_keys:
        return {}
    rows = db.scalars(
        select(MetricDefinition)
        .where(
            MetricDefinition.source_system == SCRAPE_SOURCE_SYSTEM,
            MetricDefinition.status == "active",
            MetricDefinition.metric_key.in_(metric_keys),
        )
        .order_by(MetricDefinition.definition_version.desc())
    ).all()
    definitions: dict[str, MetricDefinition] = {}
    for row in rows:
        definitions.setdefault(row.metric_key, row)
    return definitions


def _verified_works(
    db: Session, *, store_id: UUID, external_ids: set[str]
) -> dict[str, PublishedWork]:
    if not external_ids:
        return {}
    rows = db.scalars(
        select(PublishedWork).where(
            PublishedWork.store_id == store_id,
            PublishedWork.external_work_id.in_(external_ids),
            PublishedWork.ownership_status.in_(
                ("verified_system_publish", "verified_platform_api")
            ),
        )
    ).all()
    return {row.external_work_id: row for row in rows}


def _prior_observation_id(
    db: Session,
    *,
    store_id: UUID,
    channel_account_id: UUID,
    scope: str,
    metric_key: str,
    published_work_id: UUID | None,
    period_start: datetime | None,
    period_end: datetime,
    value_numeric: Decimal,
) -> UUID | None:
    statement = select(MetricObservation.id).where(
        MetricObservation.store_id == store_id,
        MetricObservation.channel_account_id == channel_account_id,
        MetricObservation.observation_scope == scope,
        MetricObservation.metric_key == metric_key,
        MetricObservation.source_system == SCRAPE_SOURCE_SYSTEM,
        MetricObservation.period_end == period_end,
        MetricObservation.supersedes_observation_id.is_(None),
        MetricObservation.value_numeric != value_numeric,
    )
    if published_work_id is None:
        statement = statement.where(MetricObservation.published_work_id.is_(None))
    else:
        statement = statement.where(MetricObservation.published_work_id == published_work_id)
    if period_start is None:
        statement = statement.where(MetricObservation.period_start.is_(None))
    else:
        statement = statement.where(MetricObservation.period_start == period_start)
    return db.scalar(
        statement.order_by(MetricObservation.collected_at.desc()).limit(1)
    )


def ingest_snapshot(
    db: Session,
    *,
    store_id: UUID,
    account: ChannelAccount,
    scope: str,
    payload: dict[str, Any],
    captured_at: datetime,
) -> dict[str, Any]:
    """把采集器快照写入观测表；返回本次写入统计。"""
    platform = str(payload.get("platform") or account.provider)
    if scope == "account":
        observed = account_snapshot_metrics(payload, platform=platform, captured_at=captured_at)
    elif scope == "work":
        observed = work_snapshot_metrics(payload, captured_at=captured_at)
    else:
        observed = []

    definitions = _load_definitions(db, {item["metric_key"] for item in observed})
    external_ids = {
        str(item["external_work_id"]) for item in observed if item.get("external_work_id")
    }
    works = (
        _verified_works(db, store_id=store_id, external_ids=external_ids)
        if scope == "work"
        else {}
    )

    created = 0
    skipped_unmatched = 0
    skipped_missing_definition = 0
    skipped_negative = 0
    for item in observed:
        value = int(item["value"])
        if value < 0:
            skipped_negative += 1
            continue
        definition = definitions.get(item["metric_key"])
        if definition is None:
            skipped_missing_definition += 1
            continue
        published_work_id: UUID | None = None
        if scope == "work":
            work = works.get(str(item.get("external_work_id") or ""))
            if work is None:
                skipped_unmatched += 1
                continue
            published_work_id = work.id
        record_suffix = str(item["record_suffix"])
        period_end = item["period_end"]
        source_record_id = (
            f"collector:{platform}:{account.external_account_id}:{scope}:"
            f"{item['metric_key']}:{record_suffix}:{period_end.date().isoformat()}"
        )
        value_numeric = Decimal(value)
        dedupe = compute_dedupe_key(
            store_id=store_id,
            source_system=SCRAPE_SOURCE_SYSTEM,
            metric_key=item["metric_key"],
            period_start=item["period_start"],
            period_end=period_end,
            source_record_id=source_record_id,
            value_numeric=value_numeric,
            currency=None,
            published_work_id=published_work_id,
            channel_account_id=account.id,
            observation_scope=scope,
        )
        prior_id = _prior_observation_id(
            db,
            store_id=store_id,
            channel_account_id=account.id,
            scope=scope,
            metric_key=item["metric_key"],
            published_work_id=published_work_id,
            period_start=item["period_start"],
            period_end=period_end,
            value_numeric=value_numeric,
        )
        statement = (
            pg_insert(MetricObservation)
            .values(
                id=uuid4(),
                store_id=store_id,
                metric_definition_id=definition.id,
                metric_key=item["metric_key"],
                metric_tier=definition.metric_tier,
                value_numeric=value_numeric,
                unit=definition.unit,
                currency=None,
                source_system=SCRAPE_SOURCE_SYSTEM,
                source_record_id=source_record_id[:300],
                source_evidence_ref=(
                    f"collector:{platform}:{account.external_account_id}:{scope}"
                )[:2048],
                period_start=item["period_start"],
                period_end=period_end,
                period_timezone="UTC",
                collected_at=captured_at,
                source_updated_at=None,
                definition_version=definition.definition_version,
                integrity_status="complete",
                authenticity_status=SCRAPE_AUTHENTICITY,
                sync_status="current",
                deduplication_key=dedupe,
                supersedes_observation_id=prior_id,
                import_batch_id=None,
                published_work_id=published_work_id,
                marketing_task_id=None,
                channel_account_id=account.id,
                observation_scope=scope,
            )
            .on_conflict_do_nothing(index_elements=["store_id", "deduplication_key"])
            .returning(MetricObservation.id)
        )
        inserted = db.execute(statement).scalar_one_or_none()
        if inserted is not None:
            created += 1

    return {
        "scope": scope,
        "observed": len(observed),
        "created": created,
        "skipped_unmatched_works": skipped_unmatched,
        "skipped_missing_definition": skipped_missing_definition,
        "skipped_negative": skipped_negative,
    }
