import base64
import csv
import hashlib
import io
import math
import posixpath
import re
import xml.etree.ElementTree as ET
import zipfile
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Annotated, cast
from urllib.parse import urlsplit
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Header, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import and_, exists, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from store_operator.auth.audit import record_audit
from store_operator.auth.context import AuthContext
from store_operator.auth.dependencies import (
    AuthenticatedSession,
    require_admin_csrf,
    require_csrf,
    require_platform_admin,
    require_store_context,
)
from store_operator.auth.errors import ApiError
from store_operator.config import settings
from store_operator.db import get_db
from store_operator.effects.metric_ingest import compute_dedupe_key
from store_operator.jobs.service import JobIdempotencyConflict, create_job
from store_operator.models.channel_delivery import ChannelAccount, PublishOperation
from store_operator.models.content_delivery import PublishPackage, PublishPackageItem
from store_operator.models.marketing_task import MarketingTask
from store_operator.models.opportunity_effects import (
    AttributionEvidence,
    BusinessOutcomeEvidence,
    DataSourceCapabilitySnapshot,
    HotTopic,
    HotTopicSource,
    MetricDefinition,
    MetricImportBatch,
    MetricObservation,
    OpportunityDecision,
    PublishedWork,
    StoreOpportunity,
    WorkOwnershipEvidence,
)

router = APIRouter(tags=["opportunities", "effects"])

def _store_id(context: AuthContext) -> UUID:
    if context.request_store_id is None:
        raise ApiError(400, "STORE_CONTEXT_REQUIRED", "Store context is required")
    return context.request_store_id


def _decimal_text(value: Decimal) -> str:
    return format(value.normalize(), "f")

class DecisionInput(BaseModel):
    decision: str
    reason: str | None = Field(default=None, max_length=1000)

    @field_validator("decision")
    @classmethod
    def valid_decision(cls, value: str) -> str:
        if value not in {"adopt", "ignore", "snooze"}:
            raise ValueError("decision must be adopt, ignore or snooze")
        return value

class MetricObservationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    metric_key: str = Field(min_length=1, max_length=120)
    value_numeric: Decimal | None = Field(default=None, ge=0, max_digits=20, decimal_places=6)
    period_start: datetime | None = None
    period_end: datetime | None = None
    period_timezone: str = Field(min_length=1, max_length=80)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    source_record_id: str | None = Field(default=None, max_length=300)
    source_evidence_ref: str | None = Field(default=None, max_length=2048)
    supersedes_observation_id: UUID | None = None
    published_work_id: UUID | None = None
    marketing_task_id: UUID | None = None

    @field_validator("period_start", "period_end")
    @classmethod
    def require_aware_datetime(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("timestamps must include timezone information")
        return value

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        return value.upper() if value else None

    @field_validator("period_timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("period_timezone must be a valid IANA timezone") from exc
        return value

class BusinessOutcomeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outcome_type: str = Field(min_length=1, max_length=32)
    value_numeric: Decimal = Field(ge=0, max_digits=20, decimal_places=6)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    source_record_id: str | None = Field(default=None, max_length=300)
    source_evidence_ref: str = Field(min_length=1, max_length=2048)
    occurred_at: datetime

    @field_validator("occurred_at")
    @classmethod
    def require_aware_occurred_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("occurred_at must include timezone information")
        return value

    @field_validator("currency")
    @classmethod
    def normalize_outcome_currency(cls, value: str | None) -> str | None:
        return value.upper() if value else None

    @field_validator("outcome_type")
    @classmethod
    def validate_outcome_type(cls, value: str) -> str:
        if value not in {"revenue", "orders", "redemptions", "store_visits", "leads"}:
            raise ValueError("Unsupported business outcome type")
        return value


class AttributionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    marketing_task_id: UUID
    published_work_id: UUID
    outcome_evidence_id: UUID
    attribution_method: str
    evidence_strength: str
    allocation_percent: Decimal = Field(default=Decimal("100"), gt=0, le=100)

    @field_validator("attribution_method")
    @classmethod
    def validate_attribution_method(cls, value: str) -> str:
        if value not in {"direct_code", "platform_reported"}:
            raise ValueError("Attribution requires direct or platform-reported evidence")
        return value

    @field_validator("evidence_strength")
    @classmethod
    def validate_evidence_strength(cls, value: str) -> str:
        if value not in {"strong", "medium"}:
            raise ValueError("Weak evidence cannot create formal attribution")
        return value


class AttributionReversalInput(BaseModel):
    reason: str = Field(min_length=8, max_length=500)

    @field_validator("reason", mode="before")
    @classmethod
    def normalize_reason(cls, value: object) -> str:
        if not isinstance(value, str) or len(value.strip()) < 8:
            raise ValueError("reason must contain at least 8 non-whitespace characters")
        return value.strip()


class MetricImportInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    csv_text: str = Field(min_length=1, max_length=5_000_000)
    source_format: str = Field(default="csv", pattern="^(csv|xlsx)$")


class MetricXlsxImportInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    file_name: str = Field(min_length=5, max_length=255)
    file_base64: str = Field(min_length=1, max_length=8_000_000)

def _observation_window_status(item: MetricObservation) -> str:
    if item.period_start is None or item.period_end is None:
        return "unknown"
    if item.period_end > datetime.now(UTC):
        return "accumulating"
    if item.sync_status == "delayed":
        return "delayed"
    if item.integrity_status != "complete":
        return "incomplete"
    if item.authenticity_status not in {"official_api", "verified_import"}:
        return "unverified"
    if item.sync_status != "current":
        return "unavailable"
    return "complete"


def _observation_read(item: MetricObservation, definition: MetricDefinition) -> dict[str, object]:
    return {
        "id": str(item.id), "metric_key": item.metric_key, "metric_tier": item.metric_tier,
        "display_name": definition.display_name,
        "value_numeric": (
            _decimal_text(item.value_numeric) if item.value_numeric is not None else None
        ),
        "unit": item.unit, "currency": item.currency, "source_system": item.source_system,
        "source_record_id": item.source_record_id, "source_evidence_ref": item.source_evidence_ref,
        "period_start": item.period_start.isoformat() if item.period_start else None,
        "period_end": item.period_end.isoformat() if item.period_end else None,
        "period_timezone": item.period_timezone, "collected_at": item.collected_at.isoformat(),
        "observation_window_status": _observation_window_status(item),
        "definition_version": item.definition_version, "integrity_status": item.integrity_status,
        "authenticity_status": item.authenticity_status, "sync_status": item.sync_status,
        "supersedes_observation_id": (
            str(item.supersedes_observation_id)
            if item.supersedes_observation_id
            else None
        ),
        "import_batch_id": str(item.import_batch_id) if item.import_batch_id else None,
        "published_work_id": str(item.published_work_id) if item.published_work_id else None,
        "marketing_task_id": str(item.marketing_task_id) if item.marketing_task_id else None,
        "channel_account_id": (
            str(item.channel_account_id) if item.channel_account_id else None
        ),
        "observation_scope": item.observation_scope,
    }

def _published_work_read(item: PublishedWork) -> dict[str, object]:
    return {
        "id": str(item.id),
        "task_id": str(item.task_id) if item.task_id else None,
        "publish_operation_id": str(item.publish_operation_id) if item.publish_operation_id else None,  # noqa: E501
        "channel_account_id": str(item.channel_account_id) if item.channel_account_id else None,
        "channel_key": item.channel_key,
        "external_work_id": item.external_work_id,
        "title": item.title,
        "permalink": item.permalink,
        "published_at": item.published_at.isoformat() if item.published_at else None,
        "ownership_status": item.ownership_status,
        "verified_at": item.verified_at.isoformat() if item.verified_at else None,
        "source_snapshot": item.source_snapshot_json,
    }


def _business_outcome_read(item: BusinessOutcomeEvidence) -> dict[str, object]:
    return {
        "id": str(item.id),
        "outcome_type": item.outcome_type,
        "value_numeric": _decimal_text(item.value_numeric),
        "currency": item.currency,
        "source_system": item.source_system,
        "source_record_id": item.source_record_id,
        "source_evidence_ref": item.source_evidence_ref,
        "occurred_at": item.occurred_at.isoformat(),
        "authenticity_status": item.authenticity_status,
        "integrity_status": item.integrity_status,
    }


def _attribution_read(item: AttributionEvidence) -> dict[str, object]:
    return {
        "id": str(item.id),
        "marketing_task_id": str(item.marketing_task_id),
        "published_work_id": str(item.published_work_id),
        "outcome_evidence_id": str(item.outcome_evidence_id),
        "attribution_method": item.attribution_method,
        "evidence_strength": item.evidence_strength,
        "allocation_percent": str(item.allocation_percent),
        "status": item.status,
        "attribution_version": item.attribution_version,
        "supersedes_attribution_id": (
            str(item.supersedes_attribution_id)
            if item.supersedes_attribution_id is not None
            else None
        ),
        "snapshot": item.attribution_snapshot_json,
        "reversal_reason": item.reversal_reason,
        "reversed_at": item.reversed_at.isoformat() if item.reversed_at else None,
    }


def _create_observation(db: Session, *, store_id: UUID, payload: MetricObservationInput,
                        authenticity: str, source_system: str = "manual",
                        supersedes_observation_id: UUID | None = None,
                        import_batch_id: UUID | None = None) -> MetricObservation:
    definition = db.scalar(select(MetricDefinition).where(
        MetricDefinition.source_system == source_system,
        MetricDefinition.metric_key == payload.metric_key,
        MetricDefinition.status == "active",
    ).order_by(MetricDefinition.definition_version.desc()))
    if definition is None:
        raise ApiError(422, "UNKNOWN_METRIC",
            "Metric key is not present in the active metric dictionary")
    if payload.published_work_id is not None:
        work = db.scalar(
            select(PublishedWork).where(
                PublishedWork.id == payload.published_work_id,
                PublishedWork.store_id == store_id,
            )
        )
        if work is None:
            raise ApiError(404, "PUBLISHED_WORK_NOT_FOUND", "Published work not found")
        if (
            work.ownership_status not in {"verified_system_publish", "verified_platform_api"}
            or work.verified_at is None
        ):
            raise ApiError(
                409,
                "PUBLISHED_WORK_NOT_VERIFIED",
                "Unverified or merchant-claimed works cannot be linked to observations",
            )
        verified_evidence_id = db.scalar(
            select(WorkOwnershipEvidence.id).where(
                WorkOwnershipEvidence.store_id == store_id,
                WorkOwnershipEvidence.published_work_id == work.id,
                WorkOwnershipEvidence.evidence_status == "verified",
            )
        )
        if verified_evidence_id is None:
            raise ApiError(
                409,
                "PUBLISHED_WORK_EVIDENCE_MISSING",
                "A verified ownership evidence record is required",
            )
        if work.task_id is None:
            if payload.marketing_task_id is not None:
                raise ApiError(
                    409,
                    "PUBLISHED_WORK_TASK_MISMATCH",
                    "This published work has no verified marketing task association",
                )
        elif payload.marketing_task_id not in {None, work.task_id}:
            raise ApiError(
                409,
                "PUBLISHED_WORK_TASK_MISMATCH",
                "Published work is linked to a different marketing task",
            )
        payload.marketing_task_id = work.task_id
    elif payload.marketing_task_id is not None:
        task = db.scalar(
            select(MarketingTask).where(
                MarketingTask.id == payload.marketing_task_id,
                MarketingTask.store_id == store_id,
            )
        )
        if task is None:
            raise ApiError(404, "MARKETING_TASK_NOT_FOUND", "Marketing task not found")
    if payload.period_start and payload.period_end and payload.period_end <= payload.period_start:
        raise ApiError(422, "INVALID_PERIOD", "period_end must be later than period_start")
    if payload.metric_key == "revenue" and payload.value_numeric is not None and payload.currency is None:  # noqa: E501
        raise ApiError(422, "CURRENCY_REQUIRED",
            "Revenue observations require an ISO 4217 currency")
    dedupe = compute_dedupe_key(
        store_id=store_id,
        source_system=source_system,
        metric_key=payload.metric_key,
        period_start=payload.period_start,
        period_end=payload.period_end,
        source_record_id=payload.source_record_id,
        value_numeric=payload.value_numeric,
        currency=payload.currency,
        supersedes_observation_id=supersedes_observation_id,
        published_work_id=payload.published_work_id,
        marketing_task_id=payload.marketing_task_id,
    )
    existing = db.scalar(select(MetricObservation).where(
        MetricObservation.store_id == store_id, MetricObservation.deduplication_key == dedupe))
    if existing is not None:
        return existing
    item = MetricObservation(
        id=uuid4(), store_id=store_id, metric_definition_id=definition.id,
        metric_key=definition.metric_key, metric_tier=definition.metric_tier,
        value_numeric=payload.value_numeric, unit=definition.unit, currency=payload.currency,
        source_system=source_system, source_record_id=payload.source_record_id,
        source_evidence_ref=payload.source_evidence_ref, period_start=payload.period_start,
        period_end=payload.period_end, period_timezone=payload.period_timezone,
        collected_at=datetime.now(UTC), definition_version=definition.definition_version,
        integrity_status="unknown", authenticity_status=authenticity, sync_status="current",
        deduplication_key=dedupe, supersedes_observation_id=supersedes_observation_id,
        import_batch_id=import_batch_id,
        published_work_id=payload.published_work_id,
        marketing_task_id=payload.marketing_task_id)
    db.add(item)
    db.flush()
    return item


class HotTopicSourceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_key: str = Field(min_length=1, max_length=100)
    display_name: str = Field(min_length=1, max_length=160)
    source_type: str = Field(default="rss", pattern="^(rss|public_feed)$")
    source_url: str = Field(min_length=1, max_length=2048)
    fallback_url: str | None = Field(default=None, max_length=2048)
    terms_url: str = Field(min_length=1, max_length=2048)
    permitted_use: str = Field(min_length=10, max_length=2000)
    attribution_template: str | None = Field(default=None, max_length=500)


class HotTopicSourceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str | None = Field(default=None, min_length=1, max_length=160)
    source_url: str | None = Field(default=None, min_length=1, max_length=2048)
    fallback_url: str | None = Field(default=None, max_length=2048)
    terms_url: str | None = Field(default=None, min_length=1, max_length=2048)
    permitted_use: str | None = Field(default=None, min_length=10, max_length=2000)
    attribution_template: str | None = Field(default=None, max_length=500)

def _validate_feed_url(value: str) -> str:
    parsed = urlsplit(value)
    allowed = {host.strip().lower() for host in settings.hot_topic_allowed_hosts.split(",") if host.strip()}  # noqa: E501
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host or parsed.username or parsed.password or host not in allowed:  # noqa: E501
        raise ApiError(422, "SOURCE_HOST_NOT_ALLOWED",
            "Feed URL must use HTTPS and an administrator-approved host")
    return value


# 复用 Easel 的热榜端点清单（skills/shared/hotlist-apis.md，60s API）。
# 仅作为后台登记表单的可选预设，仍需通过条款 URL、域名白名单与启用准入。
PUBLIC_FEED_PRESETS: tuple[dict[str, str | None], ...] = (
    {"key": "weibo", "display_name": "微博热搜",
     "source_url": "https://v2.xxapi.cn/api/weibohot",
     "fallback_url": "https://60s.viki.moe/v2/weibo"},
    {"key": "douyin", "display_name": "抖音热点",
     "source_url": "https://v2.xxapi.cn/api/douyinhot",
     "fallback_url": "https://60s.viki.moe/v2/douyin"},
    {"key": "zhihu", "display_name": "知乎热榜",
     "source_url": "https://api.zhihu.com/topstory/hot-list?limit=50",
     "fallback_url": "https://api.zhihu.com/topstory/hot-lists/total?limit=50"},
    {"key": "toutiao", "display_name": "头条热榜",
     "source_url": "https://www.toutiao.com/hot-event/hot-board/?origin=toutiao_pc",
     "fallback_url": None},
    {"key": "baidu", "display_name": "百度热搜",
     "source_url": "https://v2.xxapi.cn/api/baiduhot",
     "fallback_url": "https://60s.viki.moe/v2/baidu/hot"},
    {"key": "bili", "display_name": "B 站热榜",
     "source_url": "https://v2.xxapi.cn/api/bilibilihot",
     "fallback_url": "https://60s.viki.moe/v2/bili"},
    {"key": "rednote", "display_name": "小红书热点",
     "source_url": "https://60s.viki.moe/v2/rednote", "fallback_url": None},
    {"key": "ai-news", "display_name": "AI 资讯",
     "source_url": "https://60s.viki.moe/v2/ai-news", "fallback_url": None},
    {"key": "it-news", "display_name": "IT 资讯",
     "source_url": "https://60s.viki.moe/v2/it-news", "fallback_url": None},
)


@router.get("/admin/opportunity-sources/presets")
def list_hot_topic_source_presets(
    admin: Annotated[AuthenticatedSession, Depends(require_platform_admin)],
) -> dict[str, object]:
    allowed_hosts = sorted(
        {
            host.strip().lower()
            for host in settings.hot_topic_allowed_hosts.split(",")
            if host.strip()
        }
    )
    return {
        "items": [dict(item) for item in PUBLIC_FEED_PRESETS],
        "allowed_hosts": allowed_hosts,
    }


@router.get("/admin/opportunity-sources")
def list_hot_topic_sources(
    admin: Annotated[AuthenticatedSession, Depends(require_platform_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    sources = db.scalars(select(HotTopicSource).order_by(HotTopicSource.created_at.desc())).all()
    return {"items": [{"id": str(item.id), "source_key": item.source_key,
        "display_name": item.display_name, "source_type": item.source_type,
        "source_url": item.source_url, "fallback_url": item.fallback_url,
        "terms_url": item.terms_url, "enabled": item.enabled,
        "permitted_use": item.permitted_use,
        "attribution_template": item.attribution_template,
        "health_status": item.health_status,
        "last_success_at": item.last_success_at.isoformat() if item.last_success_at else None,
        "last_failure_at": item.last_failure_at.isoformat() if item.last_failure_at else None,
        "last_error_code": item.last_error_code,
        "last_error_summary": item.last_error_summary}
        for item in sources]}

@router.post("/admin/opportunity-sources")
def create_hot_topic_source(payload: HotTopicSourceInput,
    auth: Annotated[AuthenticatedSession, Depends(require_admin_csrf)],
    admin: Annotated[AuthenticatedSession, Depends(require_platform_admin)],
    db: Annotated[Session, Depends(get_db)]) -> dict[str, object]:
    source = HotTopicSource(id=uuid4(), source_key=payload.source_key.strip(),
        display_name=payload.display_name.strip(), source_type=payload.source_type,
        source_url=_validate_feed_url(payload.source_url),
        fallback_url=(
            _validate_feed_url(payload.fallback_url.strip())
            if payload.fallback_url and payload.fallback_url.strip()
            else None
        ),
        terms_url=_validate_feed_url(payload.terms_url),
        permitted_use=payload.permitted_use.strip(),
        attribution_template=payload.attribution_template,
        enabled=False, health_status="unknown")
    db.add(source)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ApiError(409, "SOURCE_KEY_CONFLICT", "Source key already exists") from exc
    return {"id": str(source.id), "source_key": source.source_key, "enabled": False,
        "source_type": source.source_type,
        "message": "来源已登记但默认禁用。完成条款审查和网络出口配置后，管理员再启用。"}


@router.patch("/admin/opportunity-sources/{source_id}")
def update_hot_topic_source(source_id: UUID, payload: HotTopicSourceUpdate,
    auth: Annotated[AuthenticatedSession, Depends(require_admin_csrf)],
    admin: Annotated[AuthenticatedSession, Depends(require_platform_admin)],
    db: Annotated[Session, Depends(get_db)]) -> dict[str, object]:
    source = db.scalar(select(HotTopicSource).where(
        HotTopicSource.id == source_id).with_for_update())
    if source is None:
        raise ApiError(404, "RESOURCE_NOT_FOUND", "Source not found")
    if source.enabled:
        raise ApiError(409, "SOURCE_ENABLED_LOCKED",
            "请先停用来源再修改地址或条款，避免运行中的采集配置被替换")
    if payload.display_name is not None:
        source.display_name = payload.display_name.strip()
    if payload.source_url is not None:
        source.source_url = _validate_feed_url(payload.source_url)
    if payload.fallback_url is not None:
        # 空字符串表示清空备用地址。
        source.fallback_url = (
            _validate_feed_url(payload.fallback_url.strip())
            if payload.fallback_url.strip()
            else None
        )
    if payload.terms_url is not None:
        source.terms_url = _validate_feed_url(payload.terms_url)
    if payload.permitted_use is not None:
        source.permitted_use = payload.permitted_use.strip()
    if payload.attribution_template is not None:
        source.attribution_template = payload.attribution_template
    source.health_status = "unknown"
    db.commit()
    return {"id": str(source.id), "display_name": source.display_name,
        "source_type": source.source_type, "source_url": source.source_url,
        "fallback_url": source.fallback_url,
        "terms_url": source.terms_url, "permitted_use": source.permitted_use,
        "attribution_template": source.attribution_template,
        "enabled": source.enabled, "health_status": source.health_status,
        "last_error_code": source.last_error_code,
        "last_error_summary": source.last_error_summary}

@router.post("/admin/opportunity-sources/{source_id}/enable")
def enable_hot_topic_source(source_id: UUID,
    auth: Annotated[AuthenticatedSession, Depends(require_admin_csrf)],
    admin: Annotated[AuthenticatedSession, Depends(require_platform_admin)],
    db: Annotated[Session, Depends(get_db)]) -> dict[str, object]:
    source = db.scalar(select(HotTopicSource).where(HotTopicSource.id == source_id).with_for_update())  # noqa: E501
    if source is None:
        raise ApiError(404, "RESOURCE_NOT_FOUND", "Source not found")
    _validate_feed_url(source.source_url)
    if source.fallback_url:
        _validate_feed_url(source.fallback_url)
    _validate_feed_url(source.terms_url or "")
    if not source.permitted_use:
        raise ApiError(409, "SOURCE_TERMS_REQUIRED",
            "Source usage terms must be reviewed before enabling")
    source.enabled = True
    source.health_status = "unknown"
    db.commit()
    return {"id": str(source.id), "enabled": True, "health_status": source.health_status}

@router.post("/admin/opportunity-sources/{source_id}/disable")
def disable_hot_topic_source(source_id: UUID,
    auth: Annotated[AuthenticatedSession, Depends(require_admin_csrf)],
    admin: Annotated[AuthenticatedSession, Depends(require_platform_admin)],
    db: Annotated[Session, Depends(get_db)]) -> dict[str, object]:
    source = db.scalar(select(HotTopicSource).where(HotTopicSource.id == source_id).with_for_update())  # noqa: E501
    if source is None:
        raise ApiError(404, "RESOURCE_NOT_FOUND", "Source not found")
    source.enabled = False
    db.commit()
    return {"id": str(source.id), "enabled": False, "health_status": source.health_status}

@router.post("/opportunities/collect")
def request_opportunity_collection(request: Request,
    auth: Annotated[AuthenticatedSession, Depends(require_csrf)],
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")]) -> dict[str, object]:
    store_id = _store_id(context)
    sources = db.scalars(select(HotTopicSource).where(HotTopicSource.enabled.is_(True),
        HotTopicSource.source_type.in_(("rss", "public_feed")),
        HotTopicSource.terms_url.is_not(None),
        HotTopicSource.permitted_use.is_not(None))).all()
    if not sources:
        return {"status": "unavailable", "job_id": None,
            "message": "没有已启用且完成使用条款登记的热点来源；未创建采集任务。"}
    try:
        job = create_job(db, job_type="hot_topics.collect_and_match.v1",
            payload_ref={"schema_version": 1,
                "source_ids": sorted(str(item.id) for item in sources)},
            idempotency_key=idempotency_key, store_id=store_id, actor_type="user",
            actor_user_id=auth.user.id, queue_name="default", priority=0,
            max_attempts=3, timeout_seconds=300)
    except JobIdempotencyConflict as exc:
        raise ApiError(409, "IDEMPOTENCY_KEY_REUSED",
            "Collection key was used for a different request") from exc
    record_audit(db, request, action="opportunity.collection.requested", target_type="job",
        target_id=job.id, actor_user_id=auth.user.id, store_id=store_id,
        metadata={"source_count": len(sources)})
    db.commit()
    return {"status": job.status, "job_id": str(job.id), "source_count": len(sources)}

@router.get("/opportunities")
def list_opportunities(context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)], limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0), query: str | None = None,
    status_filter: str | None = Query(default=None, alias="status")) -> dict[str, object]:
    store_id = _store_id(context)
    statement = select(StoreOpportunity, HotTopic).join(HotTopic,
        HotTopic.id == StoreOpportunity.hot_topic_id).where(
        StoreOpportunity.store_id == store_id, HotTopic.evidence_status == "collected",
            StoreOpportunity.stale_at.is_(None),
        (StoreOpportunity.expires_at.is_(None)) | (StoreOpportunity.expires_at > datetime.now(UTC)))
    if query:
        statement = statement.where(HotTopic.title.ilike(f"%{query[:120]}%"))
    if status_filter:
        statement = statement.where(StoreOpportunity.eligibility_status == status_filter)
    total = db.scalar(statement.order_by(None).limit(None).offset(None).with_only_columns(func.count())) or 0  # noqa: E501
    rows = db.execute(statement.order_by(StoreOpportunity.relevance_score.desc().nullslast(),
        HotTopic.published_at.desc().nullslast()).limit(limit).offset(offset)).all()
    items: list[dict[str, object]] = []
    for opportunity, topic in rows:
        decision = db.scalar(select(OpportunityDecision).where(
            OpportunityDecision.store_id == store_id,
                OpportunityDecision.opportunity_id == opportunity.id
        ).order_by(OpportunityDecision.created_at.desc()).limit(1))
        items.append({
            "id": str(opportunity.id), "title": topic.title, "summary": topic.summary,
            "source_url": topic.canonical_url,
                "published_at": topic.published_at.isoformat() if topic.published_at else None,
            "discovered_at": topic.discovered_at.isoformat(),
                "expires_at": opportunity.expires_at.isoformat() if opportunity.expires_at else None,  # noqa: E501
            "region": topic.region,
                "heat_value": str(topic.heat_value) if topic.heat_value is not None else None,
                    # noqa: E501
            "heat_unit": topic.heat_unit, "evidence_status": topic.evidence_status,
            "relevance_score": str(opportunity.relevance_score) if opportunity.relevance_score is not None else None,  # noqa: E501
            "match_method": opportunity.match_method,
            "matching_algorithm_version": opportunity.matching_algorithm_version,
            "match_source": opportunity.match_source,
            "ai_creative": opportunity.ai_creative_json,
            "ai_confidence": (str(opportunity.ai_confidence)
                if opportunity.ai_confidence is not None else None),
            "reason_summary": opportunity.reason_summary,
            "suggested_scenario": opportunity.suggested_scenario,
                "content_angle": opportunity.content_angle,
            "risk_flags": opportunity.risk_flags_json,
                "eligibility_status": opportunity.eligibility_status,
            "decision": decision.decision if decision else None})
    return {"items": items, "total": total,
        "page": offset // limit + 1, "page_size": limit,
        "total_pages": (total + limit - 1) // limit,
        "source_status": "available" if total else "unavailable",
        "empty_reason": None if items else (
            "当前没有已核验来源生成的有效机会；请勿将演示样例视为实时热点。按需制作仍可直接使用。"
        )}

@router.get("/opportunities/{opportunity_id}")
def get_opportunity(opportunity_id: UUID, context: Annotated[AuthContext,
    Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)]) -> dict[str, object]:
    store_id = _store_id(context)
    row = db.execute(select(StoreOpportunity, HotTopic).join(HotTopic,
        HotTopic.id == StoreOpportunity.hot_topic_id)
        .where(StoreOpportunity.id == opportunity_id,
            StoreOpportunity.store_id == store_id)).first()
    if row is None:
        raise ApiError(404, "RESOURCE_NOT_FOUND", "Resource not found")
    opportunity, topic = row
    return {"id": str(opportunity.id), "title": topic.title, "summary": topic.summary,
        "source": {"url": topic.canonical_url,
            "published_at": topic.published_at.isoformat() if topic.published_at else None,
            "discovered_at": topic.discovered_at.isoformat(),
                "evidence_status": topic.evidence_status},
        "match": {"score": str(opportunity.relevance_score) if opportunity.relevance_score is not None else None,  # noqa: E501
            "method": opportunity.match_method,
            "algorithm_version": opportunity.matching_algorithm_version,
            "source": opportunity.match_source,
            "ai_creative": opportunity.ai_creative_json,
            "ai_confidence": (str(opportunity.ai_confidence)
                if opportunity.ai_confidence is not None else None),
            "ai_prompt_version": opportunity.ai_prompt_version,
            "reason": opportunity.reason_summary,
            "products": opportunity.matched_product_ids_json,
                "offers": opportunity.matched_offer_ids_json,
            "audiences": opportunity.matched_audience_profile_ids_json,
                "scenario": opportunity.suggested_scenario,
            "content_angle": opportunity.content_angle, "risk_flags": opportunity.risk_flags_json,
            "eligibility_status": opportunity.eligibility_status},
        "expires_at": opportunity.expires_at.isoformat() if opportunity.expires_at else None}

@router.post("/opportunities/{opportunity_id}/decisions")
def decide_opportunity(opportunity_id: UUID, payload: DecisionInput, request: Request,
    auth: Annotated[AuthenticatedSession, Depends(require_csrf)],
    context: Annotated[AuthContext, Depends(require_store_context)], db: Annotated[Session,
        Depends(get_db)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")]) -> dict[str, object]:
    store_id = _store_id(context)
    key = idempotency_key.strip()
    if not key or len(key) > 128:
        raise ApiError(400, "INVALID_IDEMPOTENCY_KEY", "A valid Idempotency-Key is required")
    replay = db.scalar(select(OpportunityDecision).where(
        OpportunityDecision.store_id == store_id, OpportunityDecision.actor_user_id == auth.user.id,
        OpportunityDecision.idempotency_key == key))
    if replay is not None:
        if replay.opportunity_id != opportunity_id or replay.decision != payload.decision:
            raise ApiError(409, "IDEMPOTENCY_KEY_REUSED",
                "Idempotency key was reused for a different decision")
        return {"id": str(replay.id), "decision": replay.decision, "replayed": True}
    row = db.execute(select(StoreOpportunity, HotTopic).join(HotTopic,
        HotTopic.id == StoreOpportunity.hot_topic_id).where(
        StoreOpportunity.id == opportunity_id,
            StoreOpportunity.store_id == store_id).with_for_update()).first()
    if row is None:
        raise ApiError(404, "RESOURCE_NOT_FOUND", "Resource not found")
    opportunity, topic = row
    if payload.decision == "adopt" and (topic.evidence_status != "collected" or opportunity.eligibility_status not in {"eligible", "review_required"} or  # noqa: E501
        opportunity.stale_at is not None or (opportunity.expires_at and opportunity.expires_at <= datetime.now(UTC))):  # noqa: E501
        raise ApiError(409, "OPPORTUNITY_NOT_ADOPTABLE",
            "Opportunity is expired, stale or not adoptable")
    item = OpportunityDecision(id=uuid4(), store_id=store_id, opportunity_id=opportunity_id,
        actor_user_id=auth.user.id, decision=payload.decision, reason=payload.reason,
            idempotency_key=key)
    db.add(item)
    record_audit(db, request, action="opportunity.decision.recorded",
        target_type="store_opportunity",
        target_id=opportunity_id, actor_user_id=auth.user.id, store_id=store_id,
        metadata={"decision": payload.decision})
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ApiError(409, "IDEMPOTENCY_CONFLICT", "Decision was already submitted") from exc
    return {"id": str(item.id), "decision": item.decision, "replayed": False,
        "next_step": "Review the opportunity reference in the existing marketing task flow; no task is created automatically."}  # noqa: E501

@router.get("/effects/definitions")
def list_metric_definitions(db: Annotated[Session, Depends(get_db)]) -> dict[str, object]:
    definitions = db.scalars(select(MetricDefinition).where(MetricDefinition.status == "active")
        .order_by(MetricDefinition.metric_tier, MetricDefinition.display_name)).all()
    return {"items": [{"id": str(item.id), "source_system": item.source_system,
        "metric_key": item.metric_key,
        "metric_tier": item.metric_tier, "display_name": item.display_name, "unit": item.unit,
        "definition": item.definition,
            "definition_version": item.definition_version} for item in definitions]}

@router.get("/effects/observations")
def list_metric_observations(context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)], metric_tier: str | None = None,
    channel_account_id: UUID | None = None, observation_scope: str | None = None,
    authenticity_status: str | None = None,
    limit: int = Query(default=100, ge=1, le=500)) -> dict[str, object]:
    store_id = _store_id(context)
    statement = select(MetricObservation, MetricDefinition).join(
        MetricDefinition, MetricDefinition.id == MetricObservation.metric_definition_id).where(MetricObservation.store_id == store_id)  # noqa: E501
    if metric_tier:
        if metric_tier not in {"content_performance", "intent", "business_outcome"}:
            raise ApiError(422, "INVALID_METRIC_TIER", "Unknown metric tier")
        statement = statement.where(MetricObservation.metric_tier == metric_tier)
    if channel_account_id is not None:
        owned = db.scalar(select(ChannelAccount.id).where(
            ChannelAccount.id == channel_account_id,
            ChannelAccount.store_id == store_id))
        if owned is None:
            raise ApiError(404, "RESOURCE_NOT_FOUND", "Channel account not found")
        statement = statement.where(
            MetricObservation.channel_account_id == channel_account_id
        )
    if observation_scope:
        if observation_scope not in {"work", "account", "store"}:
            raise ApiError(422, "INVALID_OBSERVATION_SCOPE", "Unknown observation scope")
        statement = statement.where(MetricObservation.observation_scope == observation_scope)
    if authenticity_status:
        if authenticity_status not in {
            "official_api",
            "verified_import",
            "merchant_reported",
            "merchant_authorized_scrape",
            "demo_sample",
        }:
            raise ApiError(422, "INVALID_AUTHENTICITY_STATUS", "Unknown authenticity status")
        statement = statement.where(
            MetricObservation.authenticity_status == authenticity_status
        )
    rows = db.execute(statement.order_by(MetricObservation.period_end.desc().nullslast(),
        MetricObservation.collected_at.desc()).limit(limit)).all()
    return {"items": [_observation_read(item, definition) for item, definition in rows]}

@router.get("/effects/overview")
def effects_overview(
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    store_id = _store_id(context)
    now = datetime.now(UTC)
    rows = db.execute(
        select(MetricObservation, MetricDefinition)
        .join(
            MetricDefinition,
            MetricDefinition.id == MetricObservation.metric_definition_id,
        )
        .where(MetricObservation.store_id == store_id)
        .order_by(MetricObservation.collected_at.desc())
    ).all()

    latest: dict[str, tuple[MetricObservation, MetricDefinition]] = {}
    verified_rows: list[tuple[MetricObservation, MetricDefinition]] = []
    for item, definition in rows:
        is_verified = (
            item.authenticity_status in {"official_api", "verified_import"}
            and item.sync_status == "current"
            and item.integrity_status == "complete"
            and item.value_numeric is not None
        )
        if is_verified:
            latest.setdefault(item.metric_key, (item, definition))
            if (
                item.period_start is not None
                and item.period_end is not None
                and item.period_end <= now
            ):
                verified_rows.append((item, definition))

    cards = []
    for item, definition in latest.values():
        cards.append(
            {
                "metric_key": item.metric_key,
                "display_name": definition.display_name,
                "metric_tier": item.metric_tier,
                "value": (
                    _decimal_text(item.value_numeric)
                    if item.value_numeric is not None
                    else None
                ),
                "status": (
                    "accumulating"
                    if (
                        item.period_start is not None
                        and item.period_end is not None
                        and item.period_end > now
                    )
                    else "window_unknown"
                    if item.period_start is None or item.period_end is None
                    else "available"
                ),
                "reason": (
                    "统计窗口尚未结束，数据仍在积累。"
                    if (
                        item.period_start is not None
                        and item.period_end is not None
                        and item.period_end > now
                    )
                    else "缺少完整统计窗口，暂不纳入趋势分析。"
                    if item.period_start is None or item.period_end is None
                    else None
                ),
                "source_system": item.source_system,
                "period_end": item.period_end.isoformat() if item.period_end else None,
                "period_timezone": item.period_timezone,
                "collected_at": item.collected_at.isoformat(),
                "authenticity_status": item.authenticity_status,
                "integrity_status": item.integrity_status,
            }
        )

    grouped: dict[
        tuple[str, str, str, int, str],
        list[tuple[MetricObservation, MetricDefinition]],
    ] = {}
    for item, definition in verified_rows:
        if item.period_start is None or item.period_end is None:
            continue
        period_key = "|".join(
            [item.period_start.isoformat(), item.period_end.isoformat(), item.period_timezone]
        )
        group_key = (
            item.metric_key,
            item.source_system,
            definition.channel_key or "",
            definition.definition_version,
            period_key,
        )
        grouped.setdefault(group_key, []).append((item, definition))

    metric_periods: dict[tuple[str, str, str, int], list[dict[str, object]]] = {}
    for (metric_key, source_system, channel_key, definition_version, _), samples in grouped.items():
        definition = samples[0][1]
        values = [sample.value_numeric for sample, _ in samples]
        numeric_values = [value for value in values if value is not None]
        if not numeric_values:
            continue
        rule = definition.aggregation_rule
        if definition.period_semantics == "cumulative_snapshot":
            aggregate = numeric_values[0]
        elif rule == "avg":
            aggregate = sum(numeric_values) / Decimal(len(numeric_values))
        elif rule == "max":
            aggregate = max(numeric_values)
        elif rule == "min":
            aggregate = min(numeric_values)
        elif rule == "latest":
            aggregate = numeric_values[0]
        else:
            aggregate = sum(numeric_values, Decimal("0"))
        first = samples[0][0]
        if first.period_start is None or first.period_end is None:
            continue
        zone = ZoneInfo(first.period_timezone)
        period_start = first.period_start.astimezone(zone)
        period_end = first.period_end.astimezone(zone)
        metric_periods.setdefault(
            (metric_key, source_system, channel_key, definition_version), []
        ).append(
            {
                "period_start": period_start.isoformat(),
                "period_end": period_end.isoformat(),
                "value": _decimal_text(aggregate),
                "sample_count": len(numeric_values),
                "timezone": first.period_timezone,
                "aggregation_rule": rule,
                "display_name": definition.display_name,
                "metric_tier": definition.metric_tier,
                "definition_version": definition.definition_version,
                "source_system": source_system,
                "channel_key": channel_key or None,
            }
        )

    trends = []
    for (
        metric_key,
        source_system,
        channel_key,
        definition_version,
    ), points in metric_periods.items():
        points.sort(
            key=lambda point: datetime.fromisoformat(str(point["period_end"])).astimezone(UTC)
        )
        previous = points[-2] if len(points) > 1 else None
        current = points[-1] if points else None
        comparison: dict[str, object] = {
            "status": "insufficient_samples",
            "change_percent": None,
        }
        if previous is not None and current is not None:
            previous_start = datetime.fromisoformat(str(previous["period_start"]))
            previous_end = datetime.fromisoformat(str(previous["period_end"]))
            current_start = datetime.fromisoformat(str(current["period_start"]))
            current_end = datetime.fromisoformat(str(current["period_end"]))
            same_window = (
                previous_end - previous_start == current_end - current_start
                and previous_end == current_start
            )
            previous_value = Decimal(str(previous["value"]))
            current_value = Decimal(str(current["value"]))
            if same_window and previous_value != 0:
                change = (current_value - previous_value) / previous_value * 100
                comparison = {
                    "status": "available",
                    "change_percent": str(change.quantize(Decimal("0.01"))),
                }
            elif same_window and previous_value == 0:
                comparison = {
                    "status": "zero_baseline",
                    "change_percent": None,
                }
        trends.append(
            {
                "metric_key": metric_key,
                "source_system": source_system,
                "channel_key": channel_key or None,
                "definition_version": definition_version,
                "display_name": str(points[-1]["display_name"]),
                "metric_tier": str(points[-1]["metric_tier"]),
                "points": points[-30:],
                "comparison": comparison,
            }
        )

    total_observations = len(rows)
    verified_count = sum(
        1
        for item, _ in rows
        if item.authenticity_status in {"official_api", "verified_import"}
        and item.sync_status == "current"
        and item.integrity_status == "complete"
        and item.value_numeric is not None
    )
    accumulating_count = sum(
        1
        for item, _ in rows
        if item.authenticity_status in {"official_api", "verified_import"}
        and item.sync_status == "current"
        and item.integrity_status == "complete"
        and item.period_end is not None
        and item.period_end > now
    )
    window_unknown_count = sum(
        1
        for item, _ in rows
        if item.authenticity_status in {"official_api", "verified_import"}
        and item.sync_status == "current"
        and item.integrity_status == "complete"
        and (item.period_start is None or item.period_end is None)
    )
    delayed_count = sum(
        1 for item, _ in rows if item.sync_status == "delayed"
    )
    completed_verified_count = max(
        0, verified_count - accumulating_count - window_unknown_count
    )
    incomplete_count = sum(
        1
        for item, _ in rows
        if item.integrity_status in {"partial", "anomalous", "unknown"}
    )
    period_index: dict[
        tuple[str, str, str, str, str, str],
        list[tuple[int, dict[str, object]]],
    ] = {}
    for (metric_key, source_system, channel_key, definition_version), points in (
        metric_periods.items()
    ):
        for point in points:
            period_index.setdefault(
                (
                    metric_key,
                    source_system,
                    channel_key,
                    str(point["period_start"]),
                    str(point["period_end"]),
                    str(point["timezone"]),
                ),
                [],
            ).append((definition_version, point))
    conversion_pairs = [
        ("clicks", "views", "点击率"),
        ("consultations", "views", "咨询率"),
        ("booking_intents", "consultations", "咨询预约意向率"),
        ("orders", "booking_intents", "预约意向订单率"),
    ]
    conversion_rates: list[dict[str, object]] = []
    for numerator_key, denominator_key, display_name in conversion_pairs:
        numerator_series = [
            (source_system, channel_key, points)
            for (metric_key, source_system, channel_key, _), points in metric_periods.items()
            if metric_key == numerator_key
        ]
        for source_system, channel_key, numerator_points in numerator_series:
            for numerator_point in numerator_points:
                conversion_period_key = (
                    str(numerator_point["period_start"]),
                    str(numerator_point["period_end"]),
                    str(numerator_point["timezone"]),
                )
                numerator_candidates = period_index.get(
                    (numerator_key, source_system, channel_key, *conversion_period_key), []
                )
                denominator_candidates = period_index.get(
                    (denominator_key, source_system, channel_key, *conversion_period_key), []
                )
                if len(numerator_candidates) != 1 or len(denominator_candidates) != 1:
                    continue
                numerator_version, numerator_sample = numerator_candidates[0]
                denominator_version, denominator_point = denominator_candidates[0]
                denominator_value = Decimal(str(denominator_point["value"]))
                numerator_value = Decimal(str(numerator_sample["value"]))
                if denominator_value <= 0:
                    conversion_status = "zero_denominator"
                    conversion_value = None
                else:
                    conversion_status = "available"
                    conversion_value = str(
                        (numerator_value / denominator_value * 100).quantize(
                            Decimal("0.01")
                        )
                    )
                conversion_rates.append(
                    {
                        "metric_key": f"{numerator_key}_per_{denominator_key}",
                        "display_name": display_name,
                        "numerator_key": numerator_key,
                        "denominator_key": denominator_key,
                        "source_system": source_system,
                        "channel_key": channel_key or None,
                        "numerator_definition_version": numerator_version,
                        "denominator_definition_version": denominator_version,
                        "period_start": numerator_sample["period_start"],
                        "period_end": numerator_sample["period_end"],
                        "timezone": numerator_sample["timezone"],
                        "numerator_value": str(numerator_value),
                        "denominator_value": str(denominator_value),
                        "value_percent": conversion_value,
                        "status": conversion_status,
                    }
                )

    insights: list[dict[str, object]] = []
    for trend in trends:
        comparison = cast(dict[str, object], trend["comparison"])
        trend_points = cast(list[dict[str, object]], trend["points"])
        current_point = trend_points[-1]
        status = str(comparison["status"])
        change_percent = comparison["change_percent"]
        metric_tier = str(trend["metric_tier"])
        if status == "available" and change_percent is not None:
            change = Decimal(str(change_percent))
            if change > 0:
                observation_text = (
                    f"已核验指标上升 {change_percent}%，但不代表单一因素导致。"
                )
            elif change < 0:
                observation_text = (
                    f"相邻等长周期内下降 {abs(change)}%，需要结合样本和内容差异复核。"
                )
            else:
                observation_text = "相邻等长周期内基本持平。"
        elif status == "zero_baseline":
            observation_text = "上一周期基线为 0，不计算百分比变化。"
        else:
            observation_text = "当前缺少连续、等长的已核验周期样本，暂不形成趋势判断。"
        if metric_tier == "content_performance":
            next_action = (
                "对比该渠道已核验作品的主题、素材和发布时间，再决定是否复用表现较好的内容方向。"
            )
        elif metric_tier == "intent":
            next_action = "检查咨询入口、行动号召和承接流程；不要仅凭点击或咨询数量推断订单增长。"
        else:
            next_action = "先核对订单、核销或到店来源凭证及观察窗口，再评估经营结果变化。"
        insights.append(
            {
                "metric_key": trend["metric_key"],
                "display_name": trend["display_name"],
                "source_system": trend["source_system"],
                "channel_key": trend["channel_key"],
                "period_end": current_point["period_end"],
                "sample_count": current_point["sample_count"],
                "comparison_status": status,
                "observation": observation_text,
                "next_action": next_action,
            }
        )

    content_rows = db.execute(
        select(MetricObservation, MetricDefinition, PublishedWork)
        .join(
            MetricDefinition,
            MetricDefinition.id == MetricObservation.metric_definition_id,
        )
        .join(
            PublishedWork,
            and_(
                PublishedWork.store_id == MetricObservation.store_id,
                PublishedWork.id == MetricObservation.published_work_id,
            ),
        )
        .where(
            MetricObservation.store_id == store_id,
            MetricObservation.metric_tier == "content_performance",
            MetricObservation.published_work_id.is_not(None),
            MetricObservation.authenticity_status.in_(["official_api", "verified_import"]),
            MetricObservation.sync_status == "current",
            MetricObservation.integrity_status == "complete",
            MetricObservation.value_numeric.is_not(None),
            MetricObservation.period_end.is_not(None),
            MetricObservation.period_end <= now,
            PublishedWork.ownership_status.in_(
                ["verified_system_publish", "verified_platform_api"]
            ),
            PublishedWork.verified_at.is_not(None),
            MetricObservation.marketing_task_id == PublishedWork.task_id,
            exists(
                select(WorkOwnershipEvidence.id).where(
                    WorkOwnershipEvidence.store_id == PublishedWork.store_id,
                    WorkOwnershipEvidence.published_work_id == PublishedWork.id,
                    WorkOwnershipEvidence.evidence_status == "verified",
                )
            ),
        )
        .order_by(MetricObservation.collected_at.desc())
    ).all()
    content_groups: dict[str, list[tuple[MetricObservation, MetricDefinition, PublishedWork]]] = {}
    for observation, definition, work in content_rows:
        if observation.period_start is None or observation.period_end is None:
            continue
        content_period_key = "|".join(
            [
                observation.period_start.isoformat(),
                observation.period_end.isoformat(),
                observation.period_timezone,
            ]
        )
        content_decision_key = "|".join(
            [
                str(work.id),
                observation.metric_key,
                observation.source_system,
                str(definition.definition_version),
                content_period_key,
            ]
        )
        content_groups.setdefault(content_decision_key, []).append((observation, definition, work))

    content_periods: dict[str, list[dict[str, object]]] = {}
    for content_samples in content_groups.values():
        observation, definition, work = content_samples[0]
        content_values: list[Decimal] = []
        for content_observation, _, _ in content_samples:
            if content_observation.value_numeric is not None:
                content_values.append(content_observation.value_numeric)
        if not content_values:
            continue
        rule = definition.aggregation_rule
        if definition.period_semantics == "cumulative_snapshot" or rule == "latest":
            content_aggregate = content_values[0]
        elif rule == "avg":
            content_aggregate = sum(content_values) / Decimal(len(content_values))
        elif rule == "max":
            content_aggregate = max(content_values)
        elif rule == "min":
            content_aggregate = min(content_values)
        else:
            content_aggregate = sum(content_values, Decimal("0"))
        if observation.period_start is None or observation.period_end is None:
            continue
        zone = ZoneInfo(observation.period_timezone)
        content_period_start = observation.period_start.astimezone(zone)
        content_period_end = observation.period_end.astimezone(zone)
        content_group_key = "|".join(
            [
                str(work.id),
                observation.metric_key,
                observation.source_system,
                str(definition.definition_version),
            ]
        )
        content_periods.setdefault(content_group_key, []).append(
            {
                "published_work_id": str(work.id),
                "marketing_task_id": str(work.task_id) if work.task_id else None,
                "channel_key": work.channel_key,
                "external_work_id": work.external_work_id,
                "metric_key": observation.metric_key,
                "source_system": observation.source_system,
                "definition_version": definition.definition_version,
                "display_name": definition.display_name,
                "period_start": content_period_start.isoformat(),
                "period_end": content_period_end.isoformat(),
                "value": _decimal_text(content_aggregate),
                "sample_count": len(content_values),
                "timezone": observation.period_timezone,
            }
        )
    content_performance = []
    for _key, points in content_periods.items():
        points.sort(
            key=lambda point: datetime.fromisoformat(str(point["period_end"])).astimezone(UTC)
        )
        previous = points[-2] if len(points) > 1 else None
        current = points[-1] if points else None
        comparison_status = "insufficient_samples"
        change_percent = None
        if previous is not None and current is not None:
            previous_start = datetime.fromisoformat(str(previous["period_start"]))
            previous_end = datetime.fromisoformat(str(previous["period_end"]))
            current_start = datetime.fromisoformat(str(current["period_start"]))
            current_end = datetime.fromisoformat(str(current["period_end"]))
            same_window = (
                previous_end - previous_start == current_end - current_start
                and previous_end == current_start
            )
            previous_value = Decimal(str(previous["value"]))
            current_value = Decimal(str(current["value"]))
            if same_window and previous_value != 0:
                comparison_status = "available"
                change_percent = str(
                    ((current_value - previous_value) / previous_value * 100).quantize(
                        Decimal("0.01")
                    )
                )
            elif same_window:
                comparison_status = "zero_baseline"
        content_performance.append(
            {
                "published_work_id": str(points[-1]["published_work_id"]),
                "marketing_task_id": points[-1]["marketing_task_id"],
                "channel_key": points[-1]["channel_key"],
                "external_work_id": points[-1]["external_work_id"],
                "metric_key": points[-1]["metric_key"],
                "source_system": points[-1]["source_system"],
                "definition_version": points[-1]["definition_version"],
                "display_name": points[-1]["display_name"],
                "points": points[-30:],
                "comparison": {
                    "status": comparison_status,
                    "change_percent": change_percent,
                },
            }
        )

    return {
        "items": cards,
        "trends": trends,
        "conversion_rates": conversion_rates,
        "content_performance": content_performance,
        "insights": insights,
        "data_quality": {
            "total_observations": total_observations,
            "verified_observations": verified_count,
            "accumulating_observations": accumulating_count,
            "window_unknown_observations": window_unknown_count,
            "delayed_observations": delayed_count,
            "incomplete_or_anomalous_observations": incomplete_count,
            "status": "available" if completed_verified_count else "unavailable",
            "reason": (
                None
                if completed_verified_count
                else "暂无已完成统计窗口的完整、当前且已核验指标观测。"
            ),
        },
        "data_status": "available" if completed_verified_count else "unavailable",
        "business_outcomes": {
            "roi": None,
            "sales_growth": None,
            "store_visit_growth": None,
            "reason": "没有已核验的真实经营结果与成本证据时，不计算 ROI、销售增长或到店增长。",
        },
    }


@router.get("/effects/data-source-capabilities")
def list_data_source_capabilities(
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    store_id = _store_id(context)
    rows = db.scalars(
        select(DataSourceCapabilitySnapshot)
        .where(DataSourceCapabilitySnapshot.store_id == store_id)
        .order_by(
            DataSourceCapabilitySnapshot.channel_key,
            DataSourceCapabilitySnapshot.capability_key,
            DataSourceCapabilitySnapshot.snapshot_version.desc(),
        )
    ).all()
    latest: dict[tuple[str, str], DataSourceCapabilitySnapshot] = {}
    for item in rows:
        latest.setdefault((item.channel_key, item.capability_key), item)
    return {
        "items": [
            {
                "id": str(item.id),
                "channel_key": item.channel_key,
                "capability_key": item.capability_key,
                "status": item.status,
                "required_scopes": item.required_scopes_json,
                "granted_scopes": item.granted_scopes_json,
                "evidence_ref": item.evidence_ref,
                "snapshot_version": item.snapshot_version,
                "checked_at": item.checked_at.isoformat(),
                "reason": item.snapshot_json.get("reason"),
            }
            for item in latest.values()
        ],
        "total": len(latest),
    }


@router.get("/effects/published-works")
def list_published_works(
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    store_id = _store_id(context)
    rows = db.scalars(
        select(PublishedWork)
        .where(PublishedWork.store_id == store_id)
        .order_by(PublishedWork.created_at.desc())
    ).all()
    verified_work_ids = set(
        db.scalars(
            select(WorkOwnershipEvidence.published_work_id).where(
                WorkOwnershipEvidence.store_id == store_id,
                WorkOwnershipEvidence.evidence_status == "verified",
            )
        ).all()
    )
    return {
        "items": [_published_work_read(item) for item in rows],
        "total": len(rows),
        "verified_count": sum(
            1 for item in rows
            if item.id in verified_work_ids
            and item.ownership_status in {"verified_system_publish", "verified_platform_api"}
            and item.verified_at is not None
        ),
    }


@router.post("/effects/data-source-capabilities/check")
def check_data_source_capabilities(
    request: Request,
    auth: Annotated[AuthenticatedSession, Depends(require_csrf)],
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    store_id = _store_id(context)
    accounts = db.scalars(
        select(ChannelAccount).where(
            ChannelAccount.store_id == store_id,
            ChannelAccount.provider == "douyin",
        )
    ).all()
    active_accounts = [account for account in accounts if account.status == "active"]
    granted_scopes = sorted(
        {scope for account in active_accounts for scope in (account.granted_scopes or [])}
    )
    has_readback_scope = any(
        "video.list" in (account.granted_scopes or [])
        for account in active_accounts
    )
    has_reauth_required = any(account.status == "reauth_required" for account in accounts)
    capabilities: list[tuple[str, list[str], str, str]] = [
        (
            "published_work_readback",
            ["video.list"],
            (
                "available"
                if has_readback_scope
                else "reauth_required"
                if has_reauth_required
                else "unsupported"
            ),
            (
                "当前授权包含作品列表读取范围，可用于核验系统发布作品归属。"
                if has_readback_scope
                else "没有有效账号授权作品列表读取范围；发布授权不等于作品读回授权。"
            ),
        ),
        (
            "content_metrics_read",
            [],
            "unsupported",
            "当前接入仅使用 video.list 做作品归属读回；尚无经过验证的官方内容表现指标读取适配器。",
        ),
        (
            "business_outcome_read",
            [],
            "unsupported",
            "当前没有经过验证的官方订单、营业额、核销或到店结果数据源。",
        ),
    ]
    created = []
    for capability_key, required_scopes, capability_status, reason in capabilities:
        latest_version = db.scalar(
            select(func.max(DataSourceCapabilitySnapshot.snapshot_version)).where(
                DataSourceCapabilitySnapshot.store_id == store_id,
                DataSourceCapabilitySnapshot.channel_key == "douyin",
                DataSourceCapabilitySnapshot.capability_key == capability_key,
            )
        ) or 0
        item = DataSourceCapabilitySnapshot(
            id=uuid4(),
            store_id=store_id,
            channel_key="douyin",
            capability_key=capability_key,
            status=capability_status,
            required_scopes_json=required_scopes,
            granted_scopes_json=granted_scopes,
            evidence_ref="Douyin OAuth granted-scope snapshot",
            snapshot_version=latest_version + 1,
            snapshot_json={
                "account_count": len(accounts),
                "active_account_count": len(active_accounts),
                "account_statuses": sorted(account.status for account in accounts),
                "reason": reason,
            },
            checked_at=datetime.now(UTC),
        )
        db.add(item)
        created.append(item)
    record_audit(
        db,
        request,
        action="effects.data_source_capabilities.checked",
        target_type="data_source_capability_snapshot",
        target_id=created[0].id,
        actor_user_id=auth.user.id,
        store_id=store_id,
        metadata={
            "channel_key": "douyin",
            "snapshot_count": len(created),
            "active_account_count": len(active_accounts),
        },
    )
    db.commit()
    return {
        "items": [
            {
                "id": str(item.id),
                "channel_key": item.channel_key,
                "capability_key": item.capability_key,
                "status": item.status,
                "required_scopes": item.required_scopes_json,
                "granted_scopes": item.granted_scopes_json,
                "evidence_ref": item.evidence_ref,
                "snapshot_version": item.snapshot_version,
                "checked_at": item.checked_at.isoformat(),
                "reason": item.snapshot_json.get("reason"),
            }
            for item in created
        ],
        "total": len(created),
    }


@router.get("/effects/publish-readbacks")
def list_unregistered_publish_readbacks(
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    store_id = _store_id(context)
    registered_ids = set(
        db.scalars(
            select(PublishedWork.publish_operation_id).where(
                PublishedWork.store_id == store_id,
                PublishedWork.publish_operation_id.is_not(None),
            )
        ).all()
    )
    rows = db.execute(
        select(PublishOperation, PublishPackage, PublishPackageItem, ChannelAccount)
        .join(
            PublishPackage,
            and_(
                PublishPackage.store_id == PublishOperation.store_id,
                PublishPackage.id == PublishOperation.publish_package_id,
            ),
        )
        .join(
            PublishPackageItem,
            and_(
                PublishPackageItem.store_id == PublishOperation.store_id,
                PublishPackageItem.id == PublishOperation.publish_package_item_id,
            ),
        )
        .join(
            ChannelAccount,
            and_(
                ChannelAccount.store_id == PublishOperation.store_id,
                ChannelAccount.id == PublishOperation.channel_account_id,
            ),
        )
        .where(
            PublishOperation.store_id == store_id,
            PublishOperation.status == "published",
            PublishOperation.platform_item_id.is_not(None),
            PublishOperation.last_readback_at.is_not(None),
        )
        .order_by(PublishOperation.last_readback_at.desc())
        .limit(100)
    ).all()
    items = []
    for operation, package, package_item, account in rows:
        if operation.id in registered_ids:
            continue
        if operation.platform_item_id is None or operation.last_readback_at is None:
            continue
        items.append(
            {
                "publish_operation_id": str(operation.id),
                "marketing_task_id": str(package.task_id),
                "channel_key": package_item.channel_key,
                "channel_account_id": str(account.id),
                "channel_provider": account.provider,
                "external_work_id": operation.platform_item_id,
                "published_at": operation.published_at.isoformat()
                if operation.published_at
                else None,
                "readback_at": operation.last_readback_at.isoformat(),
            }
        )
    return {"items": items, "total": len(items)}


@router.post("/effects/published-works/from-publish-operation/{operation_id}")
def register_published_work_from_readback(
    operation_id: UUID,
    request: Request,
    auth: Annotated[AuthenticatedSession, Depends(require_csrf)],
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    store_id = _store_id(context)
    row = db.execute(
        select(PublishOperation, PublishPackage, PublishPackageItem, ChannelAccount)
        .join(
            PublishPackage,
            and_(
                PublishPackage.store_id == PublishOperation.store_id,
                PublishPackage.id == PublishOperation.publish_package_id,
            ),
        )
        .join(
            PublishPackageItem,
            and_(
                PublishPackageItem.store_id == PublishOperation.store_id,
                PublishPackageItem.id == PublishOperation.publish_package_item_id,
            ),
        )
        .join(
            ChannelAccount,
            and_(
                ChannelAccount.store_id == PublishOperation.store_id,
                ChannelAccount.id == PublishOperation.channel_account_id,
            ),
        )
        .where(
            PublishOperation.id == operation_id,
            PublishOperation.store_id == store_id,
            PublishOperation.status == "published",
            PublishOperation.platform_item_id.is_not(None),
            PublishOperation.last_readback_at.is_not(None),
        )
        .with_for_update()
    ).first()
    if row is None:
        raise ApiError(
            409,
            "PUBLISH_READBACK_NOT_VERIFIED",
            "A published status and platform readback are required before registering work ownership",  # noqa: E501
        )
    operation, package, package_item, account = row
    if (
        package_item.publish_package_id != package.id
        or package_item.channel_key != account.provider
        or package_item.channel_account_id != account.id
    ):
        raise ApiError(
            409,
            "PUBLISH_READBACK_RELATIONSHIP_MISMATCH",
            "Publish package item and channel account do not match",
        )
    assert operation.platform_item_id is not None
    assert operation.last_readback_at is not None
    existing = db.scalar(
        select(PublishedWork).where(
            PublishedWork.store_id == store_id,
            PublishedWork.publish_operation_id == operation.id,
        )
    )
    if existing is not None:
        return {"item": _published_work_read(existing), "replayed": True}
    snapshot = {
        "publish_operation_id": str(operation.id),
        "publish_package_id": str(package.id),
        "publish_package_item_id": str(package_item.id),
        "marketing_task_id": str(package.task_id),
        "channel_account_id": str(account.id),
        "channel_provider": account.provider,
        "platform_item_id": operation.platform_item_id,
        "publish_status": operation.status,
        "last_readback_at": operation.last_readback_at.isoformat(),
        "request_fingerprint": operation.request_fingerprint,
        "confirmed_package_fingerprint": operation.confirmed_package_fingerprint,
    }
    item = PublishedWork(
        id=uuid4(),
        store_id=store_id,
        task_id=package.task_id,
        publish_operation_id=operation.id,
        channel_account_id=account.id,
        channel_key=package_item.channel_key,
        external_work_id=operation.platform_item_id,
        published_at=operation.published_at,
        ownership_status="verified_system_publish",
        verified_at=operation.last_readback_at,
        source_snapshot_json=snapshot,
    )
    db.add(item)
    db.flush()
    evidence = WorkOwnershipEvidence(
        id=uuid4(),
        store_id=store_id,
        published_work_id=item.id,
        evidence_type="system_publish_readback",
        evidence_status="verified",
        source_system=account.provider,
        evidence_payload_json=snapshot,
        verified_by_user_id=auth.user.id,
        verified_at=operation.last_readback_at,
    )
    db.add(evidence)
    record_audit(
        db,
        request,
        action="effects.published_work.verified",
        target_type="published_work",
        target_id=item.id,
        actor_user_id=auth.user.id,
        store_id=store_id,
        metadata={
            "publish_operation_id": str(operation.id),
            "platform_item_id": operation.platform_item_id,
            "evidence_type": "system_publish_readback",
        },
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        existing = db.scalar(
            select(PublishedWork).where(
                PublishedWork.store_id == store_id,
                PublishedWork.publish_operation_id == operation_id,
            )
        )
        if existing is not None:
            return {"item": _published_work_read(existing), "replayed": True}
        raise ApiError(409, "PUBLISHED_WORK_CONFLICT",
            "Published work registration conflicted") from exc
    return {"item": _published_work_read(item), "replayed": False}


@router.get("/effects/business-outcomes")
def list_business_outcomes(
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    store_id = _store_id(context)
    rows = db.scalars(
        select(BusinessOutcomeEvidence)
        .where(BusinessOutcomeEvidence.store_id == store_id)
        .order_by(BusinessOutcomeEvidence.occurred_at.desc())
    ).all()
    return {"items": [_business_outcome_read(item) for item in rows], "total": len(rows)}


@router.post("/effects/business-outcomes")
def create_manual_business_outcome(
    payload: BusinessOutcomeInput,
    request: Request,
    auth: Annotated[AuthenticatedSession, Depends(require_csrf)],
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    store_id = _store_id(context)
    if payload.outcome_type == "revenue" and payload.currency is None:
        raise ApiError(422, "CURRENCY_REQUIRED", "Revenue outcomes require an ISO 4217 currency")
    material = "|".join(
        [
            str(store_id),
            "manual",
            payload.outcome_type,
            payload.source_record_id or "",
            str(payload.value_numeric),
            payload.currency or "",
            payload.occurred_at.isoformat(),
        ]
    )
    deduplication_key = hashlib.sha256(material.encode("utf-8")).hexdigest()
    existing = db.scalar(
        select(BusinessOutcomeEvidence).where(
            BusinessOutcomeEvidence.store_id == store_id,
            BusinessOutcomeEvidence.deduplication_key == deduplication_key,
        )
    )
    if existing is not None:
        return {"item": _business_outcome_read(existing), "replayed": True}
    item = BusinessOutcomeEvidence(
        id=uuid4(),
        store_id=store_id,
        outcome_type=payload.outcome_type,
        value_numeric=payload.value_numeric,
        currency=payload.currency,
        source_system="manual",
        source_record_id=payload.source_record_id,
        source_evidence_ref=payload.source_evidence_ref,
        occurred_at=payload.occurred_at,
        authenticity_status="merchant_reported",
        integrity_status="unknown",
        deduplication_key=deduplication_key,
        imported_by_user_id=auth.user.id,
    )
    db.add(item)
    record_audit(
        db,
        request,
        action="effects.business_outcome.reported",
        target_type="business_outcome_evidence",
        target_id=item.id,
        actor_user_id=auth.user.id,
        store_id=store_id,
        metadata={"outcome_type": item.outcome_type,
            "authenticity_status": item.authenticity_status},
    )
    db.commit()
    return {
        "item": _business_outcome_read(item),
        "replayed": False,
        "message": "该结果为商家报告，尚未核验，不进入正式归因或经营结论。",
    }


@router.get("/effects/attributions")
def list_attributions(
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    store_id = _store_id(context)
    rows = db.scalars(
        select(AttributionEvidence)
        .where(
            AttributionEvidence.store_id == store_id,
            AttributionEvidence.status == "active",
        )
        .order_by(AttributionEvidence.created_at.desc())
    ).all()
    return {"items": [_attribution_read(item) for item in rows], "total": len(rows)}


@router.post("/effects/attributions/{attribution_id}/reversal")
def reverse_attribution(
    attribution_id: UUID,
    payload: AttributionReversalInput,
    request: Request,
    auth: Annotated[AuthenticatedSession, Depends(require_csrf)],
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    store_id = _store_id(context)
    item = db.scalar(
        select(AttributionEvidence)
        .where(
            AttributionEvidence.id == attribution_id,
            AttributionEvidence.store_id == store_id,
        )
        .with_for_update()
    )
    if item is None:
        raise ApiError(404, "ATTRIBUTION_NOT_FOUND", "Attribution evidence not found")
    if item.status != "active":
        raise ApiError(
            409,
            "ATTRIBUTION_NOT_ACTIVE",
            "Only active attribution evidence can be reversed",
        )
    item.status = "rejected"
    item.reversal_reason = payload.reason
    item.reversed_at = datetime.now(UTC)
    item.reversed_by_user_id = auth.user.id
    record_audit(
        db,
        request,
        action="effects.attribution.reversed",
        target_type="attribution_evidence",
        target_id=item.id,
        actor_user_id=auth.user.id,
        store_id=store_id,
        metadata={"reason": payload.reason},
    )
    db.commit()
    return {
        "item": _attribution_read(item),
        "message": "归因已撤销；原始证据和归因快照保留，可在核对后重新建立归因。",
    }


@router.post("/effects/attributions")
def create_attribution(
    payload: AttributionInput,
    request: Request,
    auth: Annotated[AuthenticatedSession, Depends(require_csrf)],
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    store_id = _store_id(context)
    work = db.scalar(
        select(PublishedWork).where(
            PublishedWork.id == payload.published_work_id,
            PublishedWork.store_id == store_id,
        )
    )
    task = db.scalar(
        select(MarketingTask).where(
            MarketingTask.id == payload.marketing_task_id,
            MarketingTask.store_id == store_id,
        )
    )
    outcome = db.scalar(
        select(BusinessOutcomeEvidence).where(
            BusinessOutcomeEvidence.id == payload.outcome_evidence_id,
            BusinessOutcomeEvidence.store_id == store_id,
        ).with_for_update()
    )
    if work is None or task is None or outcome is None:
        raise ApiError(404, "ATTRIBUTION_SOURCE_NOT_FOUND", "Attribution source not found")
    if (
        work.ownership_status not in {"verified_system_publish", "verified_platform_api"}
        or work.verified_at is None
    ):
        raise ApiError(
            409,
            "PUBLISHED_WORK_NOT_VERIFIED",
            "Only verified platform works can be attributed",
        )
    verified_evidence_id = db.scalar(
        select(WorkOwnershipEvidence.id).where(
            WorkOwnershipEvidence.store_id == store_id,
            WorkOwnershipEvidence.published_work_id == work.id,
            WorkOwnershipEvidence.evidence_status == "verified",
        )
    )
    if verified_evidence_id is None:
        raise ApiError(
            409,
            "PUBLISHED_WORK_EVIDENCE_MISSING",
            "A verified ownership evidence record is required",
        )
    if work.task_id != task.id:
        raise ApiError(
            409,
            "PUBLISHED_WORK_TASK_MISMATCH",
            "Published work does not belong to the supplied marketing task",
        )
    if (
        outcome.authenticity_status not in {"official_api", "verified_import"}
        or outcome.integrity_status != "complete"
        or not outcome.source_evidence_ref
    ):
        raise ApiError(
            409,
            "BUSINESS_OUTCOME_NOT_VERIFIED",
            "Merchant-reported or incomplete outcomes cannot enter formal attribution",
        )
    existing = db.scalar(
        select(AttributionEvidence)
        .where(
            AttributionEvidence.store_id == store_id,
            AttributionEvidence.outcome_evidence_id == outcome.id,
            AttributionEvidence.marketing_task_id == task.id,
            AttributionEvidence.status == "active",
        )
        .with_for_update()
    )
    latest = db.scalar(
        select(AttributionEvidence)
        .where(
            AttributionEvidence.store_id == store_id,
            AttributionEvidence.outcome_evidence_id == outcome.id,
            AttributionEvidence.marketing_task_id == task.id,
        )
        .order_by(AttributionEvidence.attribution_version.desc())
        .limit(1)
        .with_for_update()
    )
    if existing is not None:
        same_input = (
            existing.published_work_id == work.id
            and existing.attribution_method == payload.attribution_method
            and existing.evidence_strength == payload.evidence_strength
            and existing.allocation_percent == payload.allocation_percent
        )
        if same_input:
            return {
                "item": _attribution_read(existing),
                "replayed": True,
                "message": "相同归因输入已存在，返回原始归因快照。",
            }
        existing.status = "superseded"
        record_audit(
            db,
            request,
            action="effects.attribution.superseded",
            target_type="attribution_evidence",
            target_id=existing.id,
            actor_user_id=auth.user.id,
            store_id=store_id,
            metadata={"reason": "attribution_input_changed"},
        )
    supersedes_attribution_id = (
        existing.id if existing is not None else latest.id if latest is not None else None
    )
    attribution_version = (
        (latest.attribution_version + 1) if latest is not None else 1
    )
    allocated = db.scalar(
        select(func.coalesce(func.sum(AttributionEvidence.allocation_percent), 0)).where(
            AttributionEvidence.store_id == store_id,
            AttributionEvidence.outcome_evidence_id == outcome.id,
            AttributionEvidence.status == "active",
        )
    ) or Decimal("0")
    if allocated + payload.allocation_percent > Decimal("100"):
        raise ApiError(
            409,
            "OUTCOME_ALLOCATION_EXCEEDED",
            "Attribution allocations for an outcome cannot exceed 100 percent",
        )
    snapshot = {
        "marketing_task_id": str(task.id),
        "published_work_id": str(work.id),
        "external_work_id": work.external_work_id,
        "channel_key": work.channel_key,
        "work_ownership_status": work.ownership_status,
        "work_verified_at": work.verified_at.isoformat(),
        "outcome_evidence_id": str(outcome.id),
        "outcome_type": outcome.outcome_type,
        "outcome_value": str(outcome.value_numeric),
        "outcome_currency": outcome.currency,
        "outcome_authenticity_status": outcome.authenticity_status,
        "outcome_integrity_status": outcome.integrity_status,
        "attribution_method": payload.attribution_method,
        "evidence_strength": payload.evidence_strength,
        "allocation_percent": str(payload.allocation_percent),
    }
    item = AttributionEvidence(
        id=uuid4(),
        store_id=store_id,
        marketing_task_id=task.id,
        published_work_id=work.id,
        outcome_evidence_id=outcome.id,
        attribution_method=payload.attribution_method,
        evidence_strength=payload.evidence_strength,
        allocation_percent=payload.allocation_percent,
        status="active",
        attribution_version=attribution_version,
        supersedes_attribution_id=supersedes_attribution_id,
        attribution_snapshot_json=snapshot,
    )
    db.add(item)
    record_audit(
        db,
        request,
        action="effects.attribution.created",
        target_type="attribution_evidence",
        target_id=item.id,
        actor_user_id=auth.user.id,
        store_id=store_id,
        metadata={
            "marketing_task_id": str(task.id),
            "published_work_id": str(work.id),
            "outcome_evidence_id": str(outcome.id),
            "allocation_percent": str(payload.allocation_percent),
            "attribution_version": attribution_version,
            "supersedes_attribution_id": (
                str(supersedes_attribution_id) if supersedes_attribution_id else None
            ),
        },
    )
    db.commit()
    return {
        "item": _attribution_read(item),
        "replayed": False,
        "message": "归因证据已保存；历史快照不可覆盖。",
    }


@router.post("/effects/observations")
def create_manual_observation(payload: MetricObservationInput, request: Request,
    auth: Annotated[AuthenticatedSession, Depends(require_csrf)],
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)]) -> dict[str, object]:
    store_id = _store_id(context)
    if payload.supersedes_observation_id is not None:
        raise ApiError(
            422,
            "CORRECTION_ENDPOINT_REQUIRED",
            "Use the observation corrections endpoint",
        )
    item = _create_observation(db, store_id=store_id, payload=payload,
        authenticity="merchant_reported")
    definition = db.get(MetricDefinition, item.metric_definition_id)
    if definition is None:
        raise ApiError(500, "METRIC_DEFINITION_MISSING", "Metric definition is unavailable")
    record_audit(db, request, action="effects.observation.merchant_reported",
        target_type="metric_observation",
        target_id=item.id, actor_user_id=auth.user.id, store_id=store_id,
        metadata={"metric_key": item.metric_key, "authenticity_status": item.authenticity_status})
    db.commit()
    return {"item": _observation_read(item, definition),
        "message": "已记录为商家手工报告，不作为已核验经营结果或 ROI 依据。"}

@router.post("/effects/observations/{observation_id}/corrections")
def correct_manual_observation(
    observation_id: UUID,
    payload: MetricObservationInput,
    request: Request,
    auth: Annotated[AuthenticatedSession, Depends(require_csrf)],
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    store_id = _store_id(context)
    if payload.supersedes_observation_id not in {None, observation_id}:
        raise ApiError(
            422,
            "CORRECTION_TARGET_MISMATCH",
            "Correction target must match the observation in the URL",
        )
    original = db.scalar(
        select(MetricObservation)
        .where(
            MetricObservation.id == observation_id,
            MetricObservation.store_id == store_id,
        )
        .with_for_update()
    )
    if original is None:
        raise ApiError(404, "RESOURCE_NOT_FOUND", "Observation not found")
    if original.authenticity_status != "merchant_reported":
        raise ApiError(
            409,
            "VERIFIED_OBSERVATION_IMMUTABLE",
            "Verified observations must be corrected by their source adapter",
        )
    successor = db.scalar(
        select(MetricObservation.id).where(
            MetricObservation.store_id == store_id,
            MetricObservation.supersedes_observation_id == original.id,
        )
    )
    if successor is not None:
        raise ApiError(
            409,
            "OBSERVATION_ALREADY_SUPERSEDED",
            "This observation already has a correction",
        )
    if not payload.source_evidence_ref or not payload.source_evidence_ref.strip():
        raise ApiError(
            422,
            "CORRECTION_EVIDENCE_REQUIRED",
            "A correction must include its source evidence or correction note",
        )
    payload.published_work_id = original.published_work_id
    payload.marketing_task_id = original.marketing_task_id
    if payload.metric_key != original.metric_key:
        raise ApiError(
            422,
            "CORRECTION_METRIC_MISMATCH",
            "A correction must keep the original metric key",
        )
    try:
        item = _create_observation(
            db,
            store_id=store_id,
            payload=payload,
            authenticity="merchant_reported",
            source_system="manual",
            supersedes_observation_id=original.id,
        )
    except IntegrityError as exc:
        db.rollback()
        raise ApiError(
            409,
            "OBSERVATION_ALREADY_SUPERSEDED",
            "This observation already has a correction",
        ) from exc
    definition = db.get(MetricDefinition, item.metric_definition_id)
    if definition is None:
        raise ApiError(500, "METRIC_DEFINITION_MISSING", "Metric definition is unavailable")
    record_audit(
        db,
        request,
        action="effects.observation.corrected",
        target_type="metric_observation",
        target_id=item.id,
        actor_user_id=auth.user.id,
        store_id=store_id,
        metadata={
            "supersedes_observation_id": str(original.id),
            "authenticity_status": item.authenticity_status,
        },
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ApiError(
            409,
            "OBSERVATION_ALREADY_SUPERSEDED",
            "This observation already has a correction",
        ) from exc
    return {
        "item": _observation_read(item, definition),
        "supersedes_observation_id": str(original.id),
        "message": "已追加更正记录；原始观测保持不变，新记录仍标记为商家报告。",
    }



@router.post("/effects/import-xlsx")
def import_manual_observations_xlsx(payload: MetricXlsxImportInput, request: Request,
    auth: Annotated[AuthenticatedSession, Depends(require_csrf)],
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)]) -> dict[str, object]:
    if not payload.file_name.lower().endswith(".xlsx"):
        raise ApiError(422, "XLSX_FILE_REQUIRED", "Only .xlsx workbooks are supported")
    try:
        raw = base64.b64decode(payload.file_base64, validate=True)
    except (ValueError, TypeError) as exc:
        raise ApiError(422, "XLSX_INVALID_BASE64", "Workbook payload is not valid base64") from exc
    if not raw or len(raw) > 5_000_000:
        raise ApiError(413, "XLSX_FILE_SIZE_INVALID", "Workbook must be between 1 byte and 5 MB")
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            members = archive.infolist()
            if len(members) > 100 or sum(item.file_size for item in members) > 20_000_000:
                raise ValueError("Workbook expands beyond the safe archive limits")
            workbook_xml = ET.fromstring(archive.read("xl/workbook.xml"))
            rels_xml = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
            ns = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
                  "rel": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
                  "pkg": "http://schemas.openxmlformats.org/package/2006/relationships"}
            first_sheet = workbook_xml.find("main:sheets/main:sheet", ns)
            if first_sheet is None:
                raise ValueError("Workbook has no worksheets")
            relationship_id = first_sheet.attrib.get(
                "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
            )
            relationship = next((item for item in rels_xml.findall("pkg:Relationship", ns)
                if item.attrib.get("Id") == relationship_id), None)
            if relationship is None:
                raise ValueError("Worksheet relationship is missing")
            sheet_path = relationship.attrib.get("Target", "")
            sheet_path = (sheet_path.lstrip("/") if sheet_path.startswith("/")
                else posixpath.normpath(posixpath.join("xl", sheet_path)))
            if sheet_path not in archive.namelist() or not sheet_path.startswith("xl/worksheets/"):
                raise ValueError("Worksheet path is invalid")
            shared_strings = []
            if "xl/sharedStrings.xml" in archive.namelist():
                shared_xml = ET.fromstring(archive.read("xl/sharedStrings.xml"))
                shared_strings = [
                    "".join(node.itertext())
                    for node in shared_xml.findall("main:si", ns)
                ]
            date_style_ids = set()
            if "xl/styles.xml" in archive.namelist():
                styles_xml = ET.fromstring(archive.read("xl/styles.xml"))
                custom_formats = {int(item.attrib["numFmtId"]): item.attrib.get("formatCode", "")
                    for item in styles_xml.findall("main:numFmts/main:numFmt", ns)}
                built_in_dates = (
                    set(range(14, 23)) | set(range(27, 37)) | {45, 46, 47} | set(range(50, 59))
                )
                xfs = styles_xml.find("main:cellXfs", ns)
                if xfs is not None:
                    for style_index, xf in enumerate(list(xfs)):
                        format_id = int(xf.attrib.get("numFmtId", "0"))
                        format_code = custom_formats.get(format_id, "")
                        normalized_format = re.sub(r'"[^"]*"|\\\\.', "", format_code)
                        if format_id in built_in_dates or re.search(
                            r"(?i)[ymdhis]", normalized_format
                        ):
                            date_style_ids.add(style_index)
            sheet_xml = ET.fromstring(archive.read(sheet_path))
            sheet_data = sheet_xml.find("main:sheetData", ns)
            if sheet_data is None:
                raise ValueError("Worksheet has no data")
            parsed_rows = []
            for row_index, row_node in enumerate(sheet_data.findall("main:row", ns), start=1):
                if row_index > 10001:
                    raise ValueError("Worksheet exceeds the 10,000-row limit")
                cells: list[object | None] = []
                for cell in row_node.findall("main:c", ns):
                    reference = cell.attrib.get("r", "")
                    column_letters = re.match(r"[A-Z]+", reference.upper())
                    if not column_letters:
                        continue
                    column_index = 0
                    for character in column_letters.group(0):
                        column_index = column_index * 26 + ord(character) - 64
                    if column_index > 50:
                        raise ValueError("Worksheet exceeds the 50-column limit")
                    while len(cells) < column_index:
                        cells.append(None)
                    if cell.find("main:f", ns) is not None:
                        raise ValueError(
                            "Formula cells are not supported; import calculated values"
                        )
                    cell_type = cell.attrib.get("t")
                    value_node = cell.find("main:v", ns)
                    cell_value: str | datetime | None = (
                        value_node.text if value_node is not None else None
                    )
                    if cell_type == "s" and isinstance(cell_value, str):
                        cell_value = shared_strings[int(cell_value)]
                    elif cell_type == "inlineStr":
                        inline = cell.find("main:is", ns)
                        cell_value = "".join(inline.itertext()) if inline is not None else ""
                    elif cell_type == "b" and cell_value is not None:
                        cell_value = "true" if cell_value == "1" else "false"
                    elif cell_type == "d" and isinstance(cell_value, str):
                        cell_value = datetime.fromisoformat(cell_value.replace("Z", "+00:00"))
                    elif (
                        isinstance(cell_value, str)
                        and int(cell.attrib.get("s", "0")) in date_style_ids
                    ):
                        cell_value = datetime(1899, 12, 30) + timedelta(days=float(cell_value))
                    cells[column_index - 1] = cell_value
                parsed_rows.append(cells)
            if not parsed_rows:
                raise ValueError("Worksheet is empty")
            headers = parsed_rows[0]
            normalized_headers = [
                str(value).strip() if value is not None else "" for value in headers
            ]
            if (
                not normalized_headers
                or any(not value for value in normalized_headers)
                or len(set(normalized_headers)) != len(normalized_headers)
            ):
                raise ValueError("Worksheet headers must be non-empty and unique")
            required = {"metric_key", "value_numeric", "period_timezone"}
            if not required.issubset(set(normalized_headers)):
                raise ValueError(
                    "Worksheet must include metric_key, value_numeric, period_timezone"
                )
            output = io.StringIO()
            writer = csv.DictWriter(output, fieldnames=normalized_headers, lineterminator="\n")
            writer.writeheader()
            for row_number, row_values in enumerate(parsed_rows[1:], start=2):
                mapped = {}
                for index, key in enumerate(normalized_headers):
                    row_value: object | None = (
                        row_values[index] if index < len(row_values) else None
                    )
                    if isinstance(row_value, date) and key in {"period_start", "period_end"}:
                        timezone_index = normalized_headers.index("period_timezone")
                        timezone_value = (
                            row_values[timezone_index]
                            if timezone_index < len(row_values)
                            else None
                        )
                        timezone_name = str(timezone_value or "").strip()
                        try:
                            zone = ZoneInfo(timezone_name)
                        except (ZoneInfoNotFoundError, ValueError) as exc:
                            raise ValueError(
                                f"Row {row_number}: period_timezone must be a valid IANA timezone"
                            ) from exc
                        if isinstance(row_value, datetime):
                            row_value = (
                                row_value.replace(tzinfo=zone)
                                if row_value.tzinfo is None
                                else row_value
                            )
                        else:
                            row_value = datetime.combine(
                                row_value, datetime.min.time(), tzinfo=zone
                            )
                        row_value = row_value.isoformat()
                    elif row_value is None:
                        row_value = ""
                    elif isinstance(row_value, float) and not math.isfinite(row_value):
                        raise ValueError(f"Row {row_number}: non-finite numeric cell")
                    else:
                        row_value = str(row_value)
                    mapped[key] = str(row_value)
                writer.writerow(mapped)
    except ApiError:
        raise
    except (
        KeyError, IndexError, ValueError, TypeError, zipfile.BadZipFile, ET.ParseError,
        OverflowError
    ) as exc:
        raise ApiError(
            422, "XLSX_INVALID", f"Workbook could not be read: {str(exc)[:200]}"
        ) from exc
    csv_payload = MetricImportInput(csv_text=output.getvalue(), source_format="xlsx")
    return _import_manual_observations(csv_payload, request, auth, context, db)


def _import_manual_observations(payload: MetricImportInput, request: Request,
    auth: Annotated[AuthenticatedSession, Depends(require_csrf)],
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)]) -> dict[str, object]:
    store_id = _store_id(context)
    reader = csv.DictReader(io.StringIO(payload.csv_text))
    required = {"metric_key", "value_numeric", "period_timezone"}
    if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
        raise ApiError(422, "CSV_COLUMNS_REQUIRED",
            "CSV must include metric_key,value_numeric,period_timezone")
    content_sha256 = hashlib.sha256(payload.csv_text.encode("utf-8")).hexdigest()
    existing_batch = db.scalar(
        select(MetricImportBatch).where(
            MetricImportBatch.store_id == store_id,
            MetricImportBatch.content_sha256 == content_sha256,
        )
    )
    if existing_batch is not None:
        return {
            "created": 0,
            "duplicates_skipped": existing_batch.row_count,
            "import_batch_id": str(existing_batch.id),
            "content_sha256": existing_batch.content_sha256,
            "authenticity_status": "merchant_reported",
            "message": "相同文件内容已导入，未重复创建观测。",
        }
    batch = MetricImportBatch(
        id=uuid4(),
        store_id=store_id,
        content_sha256=content_sha256,
        source_format=payload.source_format,
        imported_by_user_id=auth.user.id,
        row_count=0,
        created_count=0,
        skipped_count=0,
    )
    db.add(batch)
    db.flush()
    created = 0
    skipped = 0
    row_count = 0
    for line_number, row in enumerate(reader, start=2):
        row_count += 1
        try:
            raw = (row.get("value_numeric") or "").strip()
            data = MetricObservationInput(metric_key=(row.get("metric_key") or "").strip(),
                value_numeric=Decimal(raw) if raw else None,
                period_start=(
                    datetime.fromisoformat(row["period_start"])
                    if row.get("period_start")
                    else None
                ),
                period_end=(
                    datetime.fromisoformat(row["period_end"])
                    if row.get("period_end")
                    else None
                ),
                period_timezone=(row.get("period_timezone") or "").strip(),
                currency=(row.get("currency") or "").strip().upper() or None,
                source_record_id=(row.get("source_record_id") or "").strip() or None,
                source_evidence_ref=(row.get("source_evidence_ref") or "").strip() or None,
                published_work_id=UUID(row["published_work_id"]) if row.get("published_work_id") else None,  # noqa: E501
                marketing_task_id=UUID(row["marketing_task_id"]) if row.get("marketing_task_id") else None)  # noqa: E501
            if data.published_work_id is not None:
                linked_work = db.scalar(
                    select(PublishedWork).where(
                        PublishedWork.id == data.published_work_id,
                        PublishedWork.store_id == store_id,
                    )
                )
                if linked_work is None or linked_work.ownership_status not in {
                    "verified_system_publish",
                    "verified_platform_api",
                } or linked_work.verified_at is None:
                    raise ValueError("CSV published work reference is not verified")
                data.marketing_task_id = linked_work.task_id
            material = "|".join([str(store_id), "manual", data.metric_key,
                data.period_start.isoformat() if data.period_start else "",
                data.period_end.isoformat() if data.period_end else "", data.source_record_id or "",
                str(data.value_numeric) if data.value_numeric is not None else "NULL",
                data.currency or "", "",
                str(data.published_work_id) if data.published_work_id else "",
                str(data.marketing_task_id) if data.marketing_task_id else ""])
            dedupe = hashlib.sha256(material.encode("utf-8")).hexdigest()
            existed = db.scalar(select(MetricObservation.id).where(
                MetricObservation.store_id == store_id,
                MetricObservation.deduplication_key == dedupe))
            _create_observation(
                db,
                store_id=store_id,
                payload=data,
                authenticity="merchant_reported",
                import_batch_id=batch.id,
            )
            created += 1 if existed is None else 0
            skipped += 0 if existed is None else 1
        except (ValueError, InvalidOperation, KeyError) as exc:
            db.rollback()
            raise ApiError(422, "CSV_ROW_INVALID", f"CSV row {line_number} is invalid") from exc
    batch.row_count = row_count
    batch.created_count = created
    batch.skipped_count = skipped
    record_audit(db, request, action="effects.observations.imported",
        target_type="metric_import_batch",
        target_id=batch.id, actor_user_id=auth.user.id, store_id=store_id,
        metadata={
            "created": created,
            "duplicates": skipped,
            "content_sha256": content_sha256,
            "row_count": row_count,
            "authenticity_status": "merchant_reported",
        })
    db.commit()
    return {
        "created": created,
        "duplicates_skipped": skipped,
        "import_batch_id": str(batch.id),
        "content_sha256": content_sha256,
        "authenticity_status": "merchant_reported",
        "message": "导入记录均标记为商家报告；未经独立核验的数据不会进入正式经营结果或 ROI 计算。",
    }


@router.post("/effects/import")
def import_manual_observations(payload: MetricImportInput, request: Request,
    auth: Annotated[AuthenticatedSession, Depends(require_csrf)],
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)]) -> dict[str, object]:
    if payload.source_format != "csv":
        raise ApiError(
            422,
            "IMPORT_FORMAT_MISMATCH",
            "CSV endpoint only accepts CSV source format",
        )
    return _import_manual_observations(payload, request, auth, context, db)
