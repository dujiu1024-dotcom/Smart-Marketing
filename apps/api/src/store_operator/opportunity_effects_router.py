import csv
import hashlib
import io
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Header, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from store_operator.auth.audit import record_audit
from store_operator.auth.context import AuthContext
from store_operator.auth.dependencies import AuthenticatedSession, require_csrf, require_store_context
from store_operator.auth.errors import ApiError
from store_operator.db import get_db
from store_operator.models.opportunity_effects import HotTopic, MetricDefinition, MetricObservation, OpportunityDecision, StoreOpportunity

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
    source_record_id: str | None = Field(default=None, max_length=300)
    source_evidence_ref: str | None = Field(default=None, max_length=2048)

    @field_validator("period_start", "period_end")
    @classmethod
    def require_aware_datetime(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("timestamps must include timezone information")
        return value

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
    }

def _create_observation(db: Session, *, store_id: UUID, payload: MetricObservationInput,
                        authenticity: str, source_system: str = "manual") -> MetricObservation:
    definition = db.scalar(select(MetricDefinition).where(
        MetricDefinition.source_system == source_system,
        MetricDefinition.metric_key == payload.metric_key,
        MetricDefinition.status == "active",
    ).order_by(MetricDefinition.definition_version.desc()))
    if definition is None:
        raise ApiError(422, "UNKNOWN_METRIC", "Metric key is not present in the active metric dictionary")
    if payload.period_start and payload.period_end and payload.period_end <= payload.period_start:
        raise ApiError(422, "INVALID_PERIOD", "period_end must be later than period_start")
    if payload.metric_key == "revenue" and payload.value_numeric is not None:
        raise ApiError(422, "CURRENCY_REQUIRED", "Revenue imports require a reviewed currency mapping")
    material = "|".join([str(store_id), source_system, payload.metric_key,
        payload.period_start.isoformat() if payload.period_start else "",
        payload.period_end.isoformat() if payload.period_end else "", payload.source_record_id or "",
        str(payload.value_numeric) if payload.value_numeric is not None else "NULL"])
    dedupe = hashlib.sha256(material.encode("utf-8")).hexdigest()
    existing = db.scalar(select(MetricObservation).where(
        MetricObservation.store_id == store_id, MetricObservation.deduplication_key == dedupe))
    if existing is not None:
        return existing
    item = MetricObservation(
        id=uuid4(), store_id=store_id, metric_definition_id=definition.id,
        metric_key=definition.metric_key, metric_tier=definition.metric_tier,
        value_numeric=payload.value_numeric, unit=definition.unit, currency=None,
        source_system=source_system, source_record_id=payload.source_record_id,
        source_evidence_ref=payload.source_evidence_ref, period_start=payload.period_start,
        period_end=payload.period_end, period_timezone=payload.period_timezone,
        collected_at=datetime.now(UTC), definition_version=definition.definition_version,
        integrity_status="unknown", authenticity_status=authenticity, sync_status="current",
        deduplication_key=dedupe)
    db.add(item)
    db.flush()
    return item

@router.get("/opportunities")
def list_opportunities(context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)], limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0), query: str | None = None,
    status_filter: str | None = Query(default=None, alias="status")) -> dict[str, object]:
    store_id = _store_id(context)
    statement = select(StoreOpportunity, HotTopic).join(HotTopic, HotTopic.id == StoreOpportunity.hot_topic_id).where(
        StoreOpportunity.store_id == store_id, StoreOpportunity.stale_at.is_(None),
        (StoreOpportunity.expires_at.is_(None)) | (StoreOpportunity.expires_at > datetime.now(UTC)))
    if query:
        statement = statement.where(HotTopic.title.ilike(f"%{query[:120]}%"))
    if status_filter:
        statement = statement.where(StoreOpportunity.eligibility_status == status_filter)
    rows = db.execute(statement.order_by(StoreOpportunity.relevance_score.desc().nullslast(),
        HotTopic.published_at.desc().nullslast()).limit(limit).offset(offset)).all()
    items: list[dict[str, object]] = []
    for opportunity, topic in rows:
        decision = db.scalar(select(OpportunityDecision).where(
            OpportunityDecision.store_id == store_id, OpportunityDecision.opportunity_id == opportunity.id
        ).order_by(OpportunityDecision.created_at.desc()).limit(1))
        items.append({
            "id": str(opportunity.id), "title": topic.title, "summary": topic.summary,
            "source_url": topic.canonical_url, "published_at": topic.published_at.isoformat() if topic.published_at else None,
            "discovered_at": topic.discovered_at.isoformat(), "expires_at": opportunity.expires_at.isoformat() if opportunity.expires_at else None,
            "region": topic.region, "heat_value": str(topic.heat_value) if topic.heat_value is not None else None,
            "heat_unit": topic.heat_unit, "evidence_status": topic.evidence_status,
            "relevance_score": str(opportunity.relevance_score) if opportunity.relevance_score is not None else None,
            "match_method": opportunity.match_method, "reason_summary": opportunity.reason_summary,
            "suggested_scenario": opportunity.suggested_scenario, "content_angle": opportunity.content_angle,
            "risk_flags": opportunity.risk_flags_json, "eligibility_status": opportunity.eligibility_status,
            "decision": decision.decision if decision else None})
    return {"items": items, "total": len(items), "source_status": "available" if items else "unavailable",
        "empty_reason": None if items else "当前没有已核验来源生成的有效机会；请勿将演示样例视为实时热点。按需制作仍可直接使用。"}

@router.get("/opportunities/{opportunity_id}")
def get_opportunity(opportunity_id: UUID, context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)]) -> dict[str, object]:
    store_id = _store_id(context)
    row = db.execute(select(StoreOpportunity, HotTopic).join(HotTopic, HotTopic.id == StoreOpportunity.hot_topic_id)
        .where(StoreOpportunity.id == opportunity_id, StoreOpportunity.store_id == store_id)).first()
    if row is None:
        raise ApiError(404, "RESOURCE_NOT_FOUND", "Resource not found")
    opportunity, topic = row
    return {"id": str(opportunity.id), "title": topic.title, "summary": topic.summary,
        "source": {"url": topic.canonical_url, "published_at": topic.published_at.isoformat() if topic.published_at else None,
            "discovered_at": topic.discovered_at.isoformat(), "evidence_status": topic.evidence_status},
        "match": {"score": str(opportunity.relevance_score) if opportunity.relevance_score is not None else None,
            "method": opportunity.match_method, "reason": opportunity.reason_summary,
            "products": opportunity.matched_product_ids_json, "offers": opportunity.matched_offer_ids_json,
            "audiences": opportunity.matched_audience_profile_ids_json, "scenario": opportunity.suggested_scenario,
            "content_angle": opportunity.content_angle, "risk_flags": opportunity.risk_flags_json,
            "eligibility_status": opportunity.eligibility_status},
        "expires_at": opportunity.expires_at.isoformat() if opportunity.expires_at else None}

@router.post("/opportunities/{opportunity_id}/decisions")
def decide_opportunity(opportunity_id: UUID, payload: DecisionInput, request: Request,
    auth: Annotated[AuthenticatedSession, Depends(require_csrf)],
    context: Annotated[AuthContext, Depends(require_store_context)], db: Annotated[Session, Depends(get_db)],
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
            raise ApiError(409, "IDEMPOTENCY_KEY_REUSED", "Idempotency key was reused for a different decision")
        return {"id": str(replay.id), "decision": replay.decision, "replayed": True}
    opportunity = db.scalar(select(StoreOpportunity).where(
        StoreOpportunity.id == opportunity_id, StoreOpportunity.store_id == store_id).with_for_update())
    if opportunity is None:
        raise ApiError(404, "RESOURCE_NOT_FOUND", "Resource not found")
    if payload.decision == "adopt" and (opportunity.eligibility_status != "eligible" or
        opportunity.stale_at is not None or (opportunity.expires_at and opportunity.expires_at <= datetime.now(UTC))):
        raise ApiError(409, "OPPORTUNITY_NOT_ADOPTABLE", "Opportunity is expired, stale or requires review")
    item = OpportunityDecision(id=uuid4(), store_id=store_id, opportunity_id=opportunity_id,
        actor_user_id=auth.user.id, decision=payload.decision, reason=payload.reason, idempotency_key=key)
    db.add(item)
    record_audit(db, request, action="opportunity.decision.recorded", target_type="store_opportunity",
        target_id=opportunity_id, actor_user_id=auth.user.id, store_id=store_id,
        metadata={"decision": payload.decision})
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ApiError(409, "IDEMPOTENCY_CONFLICT", "Decision was already submitted") from exc
    return {"id": str(item.id), "decision": item.decision, "replayed": False,
        "next_step": "Review the opportunity reference in the existing marketing task flow; no task is created automatically."}

@router.get("/effects/definitions")
def list_metric_definitions(db: Annotated[Session, Depends(get_db)]) -> dict[str, object]:
    definitions = db.scalars(select(MetricDefinition).where(MetricDefinition.status == "active")
        .order_by(MetricDefinition.metric_tier, MetricDefinition.display_name)).all()
    return {"items": [{"id": str(item.id), "source_system": item.source_system, "metric_key": item.metric_key,
        "metric_tier": item.metric_tier, "display_name": item.display_name, "unit": item.unit,
        "definition": item.definition, "definition_version": item.definition_version} for item in definitions]}

@router.get("/effects/observations")
def list_metric_observations(context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)], metric_tier: str | None = None,
    limit: int = Query(default=100, ge=1, le=500)) -> dict[str, object]:
    store_id = _store_id(context)
    statement = select(MetricObservation, MetricDefinition).join(
        MetricDefinition, MetricDefinition.id == MetricObservation.metric_definition_id).where(MetricObservation.store_id == store_id)
    if metric_tier:
        if metric_tier not in {"content_performance", "intent", "business_outcome"}:
            raise ApiError(422, "INVALID_METRIC_TIER", "Unknown metric tier")
        statement = statement.where(MetricObservation.metric_tier == metric_tier)
    rows = db.execute(statement.order_by(MetricObservation.period_end.desc().nullslast(),
        MetricObservation.collected_at.desc()).limit(limit)).all()
    return {"items": [_observation_read(item, definition) for item, definition in rows]}

@router.get("/effects/overview")
def effects_overview(context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)]) -> dict[str, object]:
    store_id = _store_id(context)
    rows = db.execute(select(MetricObservation, MetricDefinition)
        .join(MetricDefinition, MetricDefinition.id == MetricObservation.metric_definition_id)
        .where(MetricObservation.store_id == store_id).order_by(MetricObservation.collected_at.desc())).all()
    latest: dict[str, tuple[MetricObservation, MetricDefinition]] = {}
    for item, definition in rows:
        latest.setdefault(item.metric_key, (item, definition))
    cards = []
    for item, definition in latest.values():
        trusted = item.authenticity_status in {"official_api", "verified_import"} and item.sync_status in {"current", "delayed"}
        cards.append({"metric_key": item.metric_key, "display_name": definition.display_name,
            "metric_tier": item.metric_tier, "value": str(item.value_numeric) if trusted and item.value_numeric is not None else None,
            "status": "available" if trusted and item.value_numeric is not None else "unavailable",
            "reason": None if trusted else "缺少已核验的数据来源；手工报告与演示数据不进入正式指标。",
            "source_system": item.source_system, "period_end": item.period_end.isoformat() if item.period_end else None,
            "period_timezone": item.period_timezone, "collected_at": item.collected_at.isoformat(),
            "authenticity_status": item.authenticity_status, "integrity_status": item.integrity_status})
    return {"items": cards, "data_status": "available" if any(card["status"] == "available" for card in cards) else "unavailable",
        "business_outcomes": {"roi": None, "sales_growth": None, "store_visit_growth": None,
            "reason": "没有已核验的真实经营结果与成本证据时，不计算 ROI、销售增长或到店增长。"}}

@router.post("/effects/observations")
def create_manual_observation(payload: MetricObservationInput, request: Request,
    auth: Annotated[AuthenticatedSession, Depends(require_csrf)],
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)]) -> dict[str, object]:
    store_id = _store_id(context)
    item = _create_observation(db, store_id=store_id, payload=payload, authenticity="merchant_reported")
    definition = db.get(MetricDefinition, item.metric_definition_id)
    record_audit(db, request, action="effects.observation.merchant_reported", target_type="metric_observation",
        target_id=item.id, actor_user_id=auth.user.id, store_id=store_id,
        metadata={"metric_key": item.metric_key, "authenticity_status": item.authenticity_status})
    db.commit()
    return {"item": _observation_read(item, definition),
        "message": "已记录为商家手工报告，不作为已核验经营结果或 ROI 依据。"}

@router.post("/effects/import")
def import_manual_observations(payload: MetricImportInput, request: Request,
    auth: Annotated[AuthenticatedSession, Depends(require_csrf)],
    context: Annotated[AuthContext, Depends(require_store_context)],
    db: Annotated[Session, Depends(get_db)]) -> dict[str, object]:
    store_id = _store_id(context)
    reader = csv.DictReader(io.StringIO(payload.csv_text))
    required = {"metric_key", "value_numeric", "period_timezone"}
    if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
        raise ApiError(422, "CSV_COLUMNS_REQUIRED", "CSV must include metric_key,value_numeric,period_timezone")
    created = 0
    skipped = 0
    for line_number, row in enumerate(reader, start=2):
        try:
            raw = (row.get("value_numeric") or "").strip()
            data = MetricObservationInput(metric_key=(row.get("metric_key") or "").strip(),
                value_numeric=Decimal(raw) if raw else None,
                period_start=datetime.fromisoformat(row["period_start"]) if row.get("period_start") else None,
                period_end=datetime.fromisoformat(row["period_end"]) if row.get("period_end") else None,
                period_timezone=(row.get("period_timezone") or "").strip(),
                source_record_id=(row.get("source_record_id") or "").strip() or None,
                source_evidence_ref=(row.get("source_evidence_ref") or "").strip() or None)
            material = "|".join([str(store_id), "manual", data.metric_key,
                data.period_start.isoformat() if data.period_start else "",
                data.period_end.isoformat() if data.period_end else "", data.source_record_id or "",
                str(data.value_numeric) if data.value_numeric is not None else "NULL"])
            dedupe = hashlib.sha256(material.encode("utf-8")).hexdigest()
            existed = db.scalar(select(MetricObservation.id).where(
                MetricObservation.store_id == store_id, MetricObservation.deduplication_key == dedupe))
            _create_observation(db, store_id=store_id, payload=data, authenticity="merchant_reported")
            created += 1 if existed is None else 0
            skipped += 0 if existed is None else 1
        except (ValueError, InvalidOperation, KeyError) as exc:
            db.rollback()
            raise ApiError(422, "CSV_ROW_INVALID", f"CSV row {line_number} is invalid") from exc
    record_audit(db, request, action="effects.observations.imported", target_type="metric_observation",
        target_id=None, actor_user_id=auth.user.id, store_id=store_id,
        metadata={"created": created, "duplicates": skipped, "authenticity_status": "merchant_reported"})
    db.commit()
    return {"created": created, "duplicates_skipped": skipped, "authenticity_status": "merchant_reported",
        "message": "导入记录均标记为商家报告；未经独立核验的数据不会进入正式经营结果或 ROI 计算。"}
