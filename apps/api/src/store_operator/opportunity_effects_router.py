import csv
import hashlib
import io
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated
from urllib.parse import urlsplit
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Header, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from store_operator.auth.audit import record_audit
from store_operator.auth.context import AuthContext
from store_operator.auth.dependencies import (
    AuthenticatedSession,
    require_csrf,
    require_platform_admin,
    require_store_context,
)
from store_operator.auth.errors import ApiError
from store_operator.config import settings
from store_operator.db import get_db
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

class MetricImportInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    csv_text: str = Field(min_length=1, max_length=5_000_000)

def _observation_read(item: MetricObservation, definition: MetricDefinition) -> dict[str, object]:
    return {
        "id": str(item.id), "metric_key": item.metric_key, "metric_tier": item.metric_tier,
        "display_name": definition.display_name,
        "value_numeric": str(item.value_numeric) if item.value_numeric is not None else None,
        "unit": item.unit, "currency": item.currency, "source_system": item.source_system,
        "source_record_id": item.source_record_id, "source_evidence_ref": item.source_evidence_ref,
        "period_start": item.period_start.isoformat() if item.period_start else None,
        "period_end": item.period_end.isoformat() if item.period_end else None,
        "period_timezone": item.period_timezone, "collected_at": item.collected_at.isoformat(),
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
        published_work = db.scalar(
            select(PublishedWork).where(
                PublishedWork.id == payload.published_work_id,
                PublishedWork.store_id == store_id,
            )
        )
        if published_work is None:
            raise ApiError(404, "PUBLISHED_WORK_NOT_FOUND", "Published work not found")
        if published_work.ownership_status not in {
            "verified_system_publish",
            "verified_platform_api",
        } or published_work.verified_at is None:
            raise ApiError(
                409,
                "PUBLISHED_WORK_NOT_VERIFIED",
                "Unverified or merchant-claimed works cannot be used for attribution",
            )
        if published_work.task_id is None:
            if payload.marketing_task_id is not None:
                raise ApiError(
                    409,
                    "PUBLISHED_WORK_TASK_MISMATCH",
                    "This published work has no verified marketing task association",
                )
        elif payload.marketing_task_id not in {None, published_work.task_id}:
            raise ApiError(
                409,
                "PUBLISHED_WORK_TASK_MISMATCH",
                "Published work is linked to a different marketing task",
            )
        payload.marketing_task_id = published_work.task_id
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
    material = "|".join([str(store_id), source_system, payload.metric_key,
        payload.period_start.isoformat() if payload.period_start else "",
        payload.period_end.isoformat() if payload.period_end else "",
            payload.source_record_id or "",
        str(payload.value_numeric) if payload.value_numeric is not None else "NULL",
        payload.currency or "",
        str(supersedes_observation_id) if supersedes_observation_id else "",
        str(payload.published_work_id) if payload.published_work_id else "",
        str(payload.marketing_task_id) if payload.marketing_task_id else ""])
    dedupe = hashlib.sha256(material.encode("utf-8")).hexdigest()
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
    source_url: str = Field(min_length=1, max_length=2048)
    terms_url: str = Field(min_length=1, max_length=2048)
    permitted_use: str = Field(min_length=10, max_length=2000)
    attribution_template: str | None = Field(default=None, max_length=500)

def _validate_feed_url(value: str) -> str:
    parsed = urlsplit(value)
    allowed = {host.strip().lower() for host in settings.hot_topic_allowed_hosts.split(",") if host.strip()}  # noqa: E501
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host or parsed.username or parsed.password or host not in allowed:  # noqa: E501
        raise ApiError(422, "SOURCE_HOST_NOT_ALLOWED",
            "Feed URL must use HTTPS and an administrator-approved host")
    return value


@router.get("/admin/opportunity-sources")
def list_hot_topic_sources(
    admin: Annotated[AuthenticatedSession, Depends(require_platform_admin)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    sources = db.scalars(select(HotTopicSource).order_by(HotTopicSource.created_at.desc())).all()
    return {"items": [{"id": str(item.id), "source_key": item.source_key,
        "display_name": item.display_name, "source_type": item.source_type,
        "source_url": item.source_url, "terms_url": item.terms_url, "enabled": item.enabled,
        "health_status": item.health_status,
        "last_success_at": item.last_success_at.isoformat() if item.last_success_at else None,
        "last_failure_at": item.last_failure_at.isoformat() if item.last_failure_at else None}
        for item in sources]}

@router.post("/admin/opportunity-sources")
def create_hot_topic_source(payload: HotTopicSourceInput,
    auth: Annotated[AuthenticatedSession, Depends(require_csrf)],
    admin: Annotated[AuthenticatedSession, Depends(require_platform_admin)],
    db: Annotated[Session, Depends(get_db)]) -> dict[str, object]:
    source = HotTopicSource(id=uuid4(), source_key=payload.source_key.strip(),
        display_name=payload.display_name.strip(), source_type="rss",
        source_url=_validate_feed_url(payload.source_url),
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
        "message": "来源已登记但默认禁用。完成条款审查和网络出口配置后，管理员再启用。"}

@router.post("/admin/opportunity-sources/{source_id}/enable")
def enable_hot_topic_source(source_id: UUID,
    auth: Annotated[AuthenticatedSession, Depends(require_csrf)],
    admin: Annotated[AuthenticatedSession, Depends(require_platform_admin)],
    db: Annotated[Session, Depends(get_db)]) -> dict[str, object]:
    source = db.scalar(select(HotTopicSource).where(HotTopicSource.id == source_id).with_for_update())  # noqa: E501
    if source is None:
        raise ApiError(404, "RESOURCE_NOT_FOUND", "Source not found")
    _validate_feed_url(source.source_url)
    _validate_feed_url(source.terms_url or "")
    if not source.permitted_use:
        raise ApiError(409, "SOURCE_TERMS_REQUIRED",
            "Source usage terms must be reviewed before enabling")
    source.enabled = True
    source.health_status = "unknown"
    db.commit()
    return {"id": str(source.id), "enabled": True, "health_status": source.health_status}

@router.post("/opportunities/collect")
def request_opportunity_collection(request: Request,
    auth: Annotated[AuthenticatedSession, Depends(require_csrf)],
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")]) -> dict[str, object]:
    store_id = _store_id(context)
    sources = db.scalars(select(HotTopicSource).where(HotTopicSource.enabled.is_(True),
        HotTopicSource.source_type == "rss", HotTopicSource.terms_url.is_not(None),
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
    db: Annotated[Session, Depends(get_db)], limit: int = Query(default=50, ge=1, le=200),
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
            "region": topic.region, "heat_value": str(topic.heat_value) if topic.heat_value is not None else None,  # noqa: E501
            "heat_unit": topic.heat_unit, "evidence_status": topic.evidence_status,
            "relevance_score": str(opportunity.relevance_score) if opportunity.relevance_score is not None else None,  # noqa: E501
            "match_method": opportunity.match_method, "reason_summary": opportunity.reason_summary,
            "suggested_scenario": opportunity.suggested_scenario,
                "content_angle": opportunity.content_angle,
            "risk_flags": opportunity.risk_flags_json,
                "eligibility_status": opportunity.eligibility_status,
            "decision": decision.decision if decision else None})
    return {"items": items, "total": total,
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
            "method": opportunity.match_method, "reason": opportunity.reason_summary,
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
    if payload.decision == "adopt" and (topic.evidence_status != "collected" or opportunity.eligibility_status != "eligible" or  # noqa: E501
        opportunity.stale_at is not None or (opportunity.expires_at and opportunity.expires_at <= datetime.now(UTC))):  # noqa: E501
        raise ApiError(409, "OPPORTUNITY_NOT_ADOPTABLE",
            "Opportunity is expired, stale or requires review")
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
    limit: int = Query(default=100, ge=1, le=500)) -> dict[str, object]:
    store_id = _store_id(context)
    statement = select(MetricObservation, MetricDefinition).join(
        MetricDefinition, MetricDefinition.id == MetricObservation.metric_definition_id).where(MetricObservation.store_id == store_id)  # noqa: E501
    if metric_tier:
        if metric_tier not in {"content_performance", "intent", "business_outcome"}:
            raise ApiError(422, "INVALID_METRIC_TIER", "Unknown metric tier")
        statement = statement.where(MetricObservation.metric_tier == metric_tier)
    rows = db.execute(statement.order_by(MetricObservation.period_end.desc().nullslast(),
        MetricObservation.collected_at.desc()).limit(limit)).all()
    return {"items": [_observation_read(item, definition) for item, definition in rows]}

@router.get("/effects/overview")
def effects_overview(
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    store_id = _store_id(context)
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
            if item.period_start is not None and item.period_end is not None:
                verified_rows.append((item, definition))

    cards = []
    for item, definition in latest.values():
        cards.append(
            {
                "metric_key": item.metric_key,
                "display_name": definition.display_name,
                "metric_tier": item.metric_tier,
                "value": str(item.value_numeric),
                "status": "available",
                "reason": None,
                "source_system": item.source_system,
                "period_end": item.period_end.isoformat() if item.period_end else None,
                "period_timezone": item.period_timezone,
                "collected_at": item.collected_at.isoformat(),
                "authenticity_status": item.authenticity_status,
                "integrity_status": item.integrity_status,
            }
        )

    grouped: dict[str, list[tuple[MetricObservation, MetricDefinition]]] = {}
    for item, definition in verified_rows:
        if item.period_start is None or item.period_end is None:
            continue
        period_key = "|".join(
            [item.period_start.isoformat(), item.period_end.isoformat()]
        )
        grouped.setdefault(item.metric_key + "|" + period_key, []).append(
            (item, definition)
        )

    metric_periods: dict[str, list[dict[str, object]]] = {}
    for key, samples in grouped.items():
        metric_key = key.split("|", 1)[0]
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
        zone = ZoneInfo(first.period_timezone)
        period_start = first.period_start.astimezone(zone)
        period_end = first.period_end.astimezone(zone)
        metric_periods.setdefault(metric_key, []).append(
            {
                "period_start": period_start.isoformat(),
                "period_end": period_end.isoformat(),
                "value": str(aggregate),
                "sample_count": len(numeric_values),
                "timezone": first.period_timezone,
                "aggregation_rule": rule,
                "display_name": definition.display_name,
            }
        )

    trends = []
    for metric_key, points in metric_periods.items():
        points.sort(key=lambda point: str(point["period_end"]))
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
                "display_name": str(points[-1]["display_name"]),
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
    )
    delayed_count = sum(
        1 for item, _ in rows if item.sync_status == "delayed"
    )
    incomplete_count = sum(
        1
        for item, _ in rows
        if item.integrity_status in {"partial", "anomalous", "unknown"}
    )
    return {
        "items": cards,
        "trends": trends,
        "data_quality": {
            "total_observations": total_observations,
            "verified_observations": verified_count,
            "delayed_observations": delayed_count,
            "incomplete_or_anomalous_observations": incomplete_count,
            "status": "available" if verified_count else "unavailable",
            "reason": (
                None
                if verified_count
                else "缺少完整、当前且已核验的指标观测；手工报告不进入正式趋势和经营结论。"
            ),
        },
        "data_status": "available" if cards else "unavailable",
        "business_outcomes": {
            "roi": None,
            "sales_growth": None,
            "store_visit_growth": None,
            "reason": "没有已核验的真实经营结果与成本证据时，不计算 ROI、销售增长或到店增长。",
        },
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


@router.post("/effects/import")
def import_manual_observations(payload: MetricImportInput, request: Request,
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
        source_format="csv",
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
                published_work_id=UUID(row["published_work_id"]) if row.get("published_work_id") else None,
                marketing_task_id=UUID(row["marketing_task_id"]) if row.get("marketing_task_id") else None)
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
