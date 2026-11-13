"""大模型跨品类创意重算。

规则匹配只能做同品类字面相关；本模块对低分/跨品类热点做一次创意重算，
输出可直接执行的活动主题、玩法与优惠机制。失败不阻塞规则匹配。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from store_operator.models import (  # type: ignore[import-untyped]
    HotTopic,
    HotTopicAICreativeCache,
    HotTopicSource,
    StoreOpportunity,
)

from store_operator_worker.handlers import JobExecutionError

if TYPE_CHECKING:
    from store_operator_worker.hot_topic_matching import StoreContext

logger = logging.getLogger(__name__)

PROMPT_VERSION = "hot-topic-creative:v2"
MAX_CANDIDATES_PER_STORE = 8
RETRY_ATTEMPTS = 2
RETRY_BACKOFF_SECONDS = 1.0
MAX_SUMMARY_CHARS = 500

# 宁可少蹭，不许翻车：命中即不送模型，直接排除。
BLACKLIST_KEYWORDS: tuple[str, ...] = (
    "灾难", "事故", "伤亡", "遇难", "死亡", "失联", "坠机", "坠楼", "坍塌", "地震",
    "洪水", "爆炸", "火灾", "起火", "空难", "车祸", "溺水", "中毒", "疫情", "报复社会",
    "政治", "领导人", "主席", "总统", "选举", "抗议", "游行", "镇压", "政变",
    "悼念", "哀悼", "去世", "离世", "逝世", "追悼", "遗体", "殉职", "牺牲",
    "未成年", "儿童", "幼童", "婴儿", "性侵", "猥亵", "虐待", "霸凌", "绑架",
)

SYSTEM_INSTRUCTION = """你是连锁门店的营销创意总监。你要判断一条热点能否被门店“借势”，并给出具体、可执行、合规的活动方案。

判断标准：
1. 不要因为热点发生在别的城市、别的行业就排除。跨地域、跨品类恰恰是创意空间：本地的大连人、山东人、球迷、游客都是可定向客群。
   示例：上海的咖啡店遇到“大连球赛夺冠”，可以做“大连人半价”“山东老铁凭身份证免单”“穿球衣到店免费升杯”，借势逻辑是“为家乡球队庆祝的异乡人需要一个聚会据点”。
2. 体育夺冠、节庆、城市荣耀、影视综艺、天气生活、消费趋势类热点，优先考虑借势，不要轻易 excluded。
3. 只有以下情况才 excluded=true：灾难、事故、伤亡、政治敏感、逝者悼念、涉未成年人伤害，或热点与门店完全无法建立任何人群/情绪连接。
4. 借势逻辑必须说清：这家店为什么能蹭、面向哪类人、与哪个商品/权益结合。
5. 优惠机制必须具体：目标人群条件（如“持大连身份证/穿球衣/说山东话”）+ 折扣/赠品/免单规则，避免空话。
6. 不得承诺疗效、收益、绝对化效果；不得歧视地域或人群（“山东老铁免单”是友好致意，不能写成贬损）。
7. 只输出单个严格 JSON 对象，不要 Markdown、不要代码块、不要额外解释。confidence 为 0-1 的数字，低于 0.5 就不要硬凑。

JSON 字段（未排除时创意字段必须全部给出且非空；排除时只填 excluded 与 exclude_reason）：
{
  "excluded": false,
  "exclude_reason": "未排除时填空字符串",
  "theme": "活动主题，不超过40字",
  "play": "一句话玩法，不超过80字",
  "offer": {
    "audience_condition": "目标人群条件，如“持山东身份证/山东籍顾客”",
    "mechanic": "赠品/免单/折扣形式，如“免费升杯”",
    "discount_rule": "具体折扣或免单规则，如“山东老铁到店免单1杯，每桌限1杯”"
  },
  "target_audience": "目标客群",
  "borrow_logic": "为什么这家店能蹭这个热点",
  "risk_notes": ["风险提示1", "风险提示2"],
  "channels": ["门店海报", "朋友圈"],
  "confidence": 0.78
}
"""

# Provider 只负责保证输出是 JSON 对象；字段契约由 validate_creative_payload 校验，
# 因为 Provider 的确定性 schema 不支持 null/union，强制字段会让排除场景也失败。
PROVIDER_OUTPUT_SCHEMA: dict[str, object] = {"type": "object"}


@dataclass(slots=True)
class CreativeCandidate:
    topic: HotTopic
    rule_score: float
    rule_status: str
    category_hits: dict[str, str]
    entity_hits: list[str]
    audience_hits: list[str]
    region_state: str
    category_specific: bool


@dataclass(slots=True)
class CreativeProposal:
    topic: HotTopic
    score: float
    payload: dict[str, object]
    risk_flags: list[str]
    reason: str


@dataclass(slots=True)
class CreativeOutcome:
    candidates: int = 0
    model_calls: int = 0
    cache_hits: int = 0
    excluded: int = 0
    created: int = 0
    errors: list[dict[str, str]] = field(default_factory=list)
    # 明确不让蹭的热点（黑名单/模型排除/低置信度），不回退规则结果。
    excluded_topic_ids: set[UUID] = field(default_factory=set)
    # 模型调用或结构校验失败的热点，允许回退为规则结果降级展示。
    failed_topic_ids: set[UUID] = field(default_factory=set)

    def as_dict(self) -> dict[str, object]:
        return {
            "candidates": self.candidates,
            "model_calls": self.model_calls,
            "cache_hits": self.cache_hits,
            "excluded": self.excluded,
            "created": self.created,
            "errors": self.errors,
        }


def _source_blacklist() -> set[str]:
    raw = os.environ.get("HOT_TOPIC_AI_SOURCE_BLACKLIST", "")
    return {item.strip().lower() for item in raw.split(",") if item.strip()}


def blacklist_reason(topic: HotTopic, source_key: str | None = None) -> str | None:
    text = f"{topic.title} {topic.summary or ''}"
    for keyword in BLACKLIST_KEYWORDS:
        if keyword in text:
            return f"命中硬性排除关键词：{keyword}"
    if source_key and source_key.lower() in _source_blacklist():
        return f"来源在排除名单：{source_key}"
    return None


def _clip(value: object, limit: int) -> str:
    return str(value or "").strip()[:limit]


def validate_creative_payload(payload: object) -> tuple[dict[str, object] | None, str | None]:
    """严格校验模型输出；结构不符不落库，文本超长按上限截断。"""
    if not isinstance(payload, dict):
        return None, "AI_CREATIVE_INVALID_OUTPUT"
    if not isinstance(payload.get("excluded"), bool):
        return None, "AI_CREATIVE_INVALID_OUTPUT"
    if payload["excluded"]:
        return {
            "excluded": True,
            "exclude_reason": _clip(payload.get("exclude_reason"), 200),
        }, None
    offer = payload.get("offer")
    if not isinstance(offer, dict):
        return None, "AI_CREATIVE_INVALID_OUTPUT"
    for key in ("audience_condition", "mechanic", "discount_rule"):
        if not isinstance(offer.get(key), str) or not offer[key].strip():
            return None, "AI_CREATIVE_INVALID_OUTPUT"
    for key in ("theme", "play", "target_audience", "borrow_logic"):
        if not isinstance(payload.get(key), str) or not payload[key].strip():
            return None, "AI_CREATIVE_INVALID_OUTPUT"
    confidence = payload.get("confidence")
    if not isinstance(confidence, (int, float)) or not 0 <= float(confidence) <= 1:
        return None, "AI_CREATIVE_INVALID_OUTPUT"
    risk_notes = payload.get("risk_notes") or []
    channels = payload.get("channels") or []
    if not isinstance(risk_notes, list) or not isinstance(channels, list):
        return None, "AI_CREATIVE_INVALID_OUTPUT"

    validated: dict[str, object] = {
        "excluded": False,
        "exclude_reason": None,
        "theme": _clip(payload.get("theme"), 80),
        "play": _clip(payload.get("play"), 160),
        "offer": {
            "audience_condition": _clip(offer.get("audience_condition"), 120),
            "mechanic": _clip(offer.get("mechanic"), 120),
            "discount_rule": _clip(offer.get("discount_rule"), 160),
        },
        "target_audience": _clip(payload.get("target_audience"), 120),
        "borrow_logic": _clip(payload.get("borrow_logic"), 300),
        "risk_notes": [_clip(item, 120) for item in risk_notes[:5] if str(item).strip()],
        "channels": [_clip(item, 40) for item in channels[:5] if str(item).strip()],
        "confidence": round(float(confidence), 3),
    }
    generated_text = " ".join(
        [
            str(validated["theme"]),
            str(validated["play"]),
            str(validated["borrow_logic"]),
            str(validated["offer"]),
        ]
    )
    for keyword in BLACKLIST_KEYWORDS:
        if keyword in generated_text:
            return None, "AI_CREATIVE_UNSAFE_OUTPUT"
    return validated, None


def _build_input(
    db: Session, ctx: StoreContext, candidate: CreativeCandidate
) -> dict[str, object]:
    profile = ctx.profile
    source = db.get(HotTopicSource, candidate.topic.source_id)
    product_rows = [
        {
            "name": product.name,
            "category": product.category,
            "selling_points": list(product.key_selling_points_json or [])[:4],
        }
        for product in ctx.products[:8]
    ]
    offer_rows = [
        {"title": offer.title, "type": offer.offer_type} for offer in ctx.offers[:5]
    ]
    audience_rows = [
        {
            "name": audience.name,
            "scenarios": list(audience.consumption_scenarios_json or [])[:4],
            "motivations": list(audience.purchase_motivations_json or [])[:3],
        }
        for audience in ctx.audiences[:5]
    ]
    brand = None
    if ctx.brand is not None:
        brand = {
            "positioning": ctx.brand.positioning,
            "tone_of_voice": ctx.brand.tone_of_voice,
            "common_phrases": list(ctx.brand.common_phrases_json or [])[:5],
            "prohibited_phrases": list(ctx.brand.prohibited_phrases_json or [])[:10],
        }
    return {
        "store": {
            "name": profile.display_name,
            "business_type": profile.business_type,
            "industry_category": profile.industry_category,
            "city": profile.city,
            "district": profile.district,
            "service_radius": profile.service_radius,
            "capabilities": list(profile.service_capabilities_json or [])[:8],
            "introduction": profile.introduction,
        },
        "products": product_rows,
        "offers": offer_rows,
        "audiences": audience_rows,
        "brand": brand,
        "topic": {
            "title": candidate.topic.title,
            "summary": candidate.topic.summary,
            "source": source.source_key if source else None,
            "heat_value": str(candidate.topic.heat_value) if candidate.topic.heat_value else None,
            "heat_unit": candidate.topic.heat_unit,
            "published_at": (
                candidate.topic.published_at.isoformat()
                if candidate.topic.published_at
                else None
            ),
        },
        "rule_signals": {
            "rule_score": round(candidate.rule_score, 3),
            "category_hits": candidate.category_hits,
            "category_specific": candidate.category_specific,
            "entity_hits": candidate.entity_hits[:8],
            "audience_hits": candidate.audience_hits[:5],
            "region_state": candidate.region_state,
        },
    }


def _call_model(
    db: Session,
    *,
    store_id: UUID,
    job_id: UUID | None,
    attempt_id: UUID | None,
    topic_id: UUID,
    payload: dict[str, object],
) -> dict[str, object]:
    from store_operator.ai_gateway import (  # type: ignore[import-untyped]
        ProviderCallContext,
        TextGenerateRequest,
        parse_and_validate_structured_output,
    )

    from store_operator_worker.ai_handlers import _load_executor

    executor, provider_id, model_id = _load_executor()
    request = TextGenerateRequest(
        context=ProviderCallContext(
            request_id=str(uuid4()),
            store_id=store_id,
            job_id=job_id,
            attempt_id=attempt_id,
            idempotency_key=f"hot-topic-creative:{topic_id}:{PROMPT_VERSION}",
            prompt_version_id=None,
        ),
        model_id=model_id,
        system_instruction=SYSTEM_INSTRUCTION,
        user_input=json.dumps(payload, ensure_ascii=False),
        output_schema=PROVIDER_OUTPUT_SCHEMA,
        temperature=0.8,
        max_output_tokens=1200,
    )
    response = asyncio.run(executor.generate_text(request, provider_id=provider_id))
    if response.structured_output is not None:
        return dict(response.structured_output)
    return dict(
        parse_and_validate_structured_output(response.text, PROVIDER_OUTPUT_SCHEMA)
    )


def _error_code(exc: Exception) -> tuple[str, bool]:
    code = getattr(exc, "code", None)
    if code is None and isinstance(exc, JobExecutionError):
        return exc.code, exc.retryable
    return str(code or "AI_CREATIVE_FAILED"), bool(getattr(exc, "retryable", False))


def _cached(db: Session, topic_id: UUID, context_hash: str) -> dict[str, object] | None:
    row = db.scalar(
        select(HotTopicAICreativeCache).where(
            HotTopicAICreativeCache.hot_topic_id == topic_id,
            HotTopicAICreativeCache.store_context_hash == context_hash,
            HotTopicAICreativeCache.prompt_version == PROMPT_VERSION,
        )
    )
    return dict(row.payload_json) if row is not None else None


def _store_cache(
    db: Session,
    *,
    store_id: UUID,
    topic: HotTopic,
    context_hash: str,
    payload: dict[str, object],
) -> None:
    """写缓存；并发写同一 key 时忽略冲突，不影响本轮匹配。"""
    try:
        with db.begin_nested():
            db.add(
                HotTopicAICreativeCache(
                    id=uuid4(),
                    hot_topic_id=topic.id,
                    store_id=store_id,
                    store_context_hash=context_hash,
                    topic_content_hash=topic.content_hash,
                    prompt_version=PROMPT_VERSION,
                    payload_json=payload,
                )
            )
    except IntegrityError:
        logger.info("AI creative cache already exists for topic %s", topic.id)


def _proposal_reason(payload: dict[str, object]) -> str:
    raw_offer = payload.get("offer")
    offer: dict[str, object] = raw_offer if isinstance(raw_offer, dict) else {}
    raw_risk_notes = payload.get("risk_notes")
    risk_notes: list[object] = raw_risk_notes if isinstance(raw_risk_notes, list) else []
    raw_confidence = payload.get("confidence")
    confidence = raw_confidence if isinstance(raw_confidence, (int, float)) else 0.0
    return (
        f"AI 创意：{payload.get('theme')}；玩法：{payload.get('play')}；"
        f"优惠：{offer.get('audience_condition')}，{offer.get('mechanic')}，"
        f"{offer.get('discount_rule')}；借势逻辑：{payload.get('borrow_logic')}；"
        f"目标客群：{payload.get('target_audience')}；"
        f"置信度 {float(confidence):.2f}；"
        f"风险提示：{'；'.join(str(item) for item in risk_notes) or '无'}。"
        "该创意由大模型生成，热度仅用于排序。"
    )[:MAX_SUMMARY_CHARS]


def ai_rematch(
    db: Session,
    *,
    store_id: UUID,
    ctx: StoreContext,
    candidates: list[CreativeCandidate],
    now: datetime | None = None,
    job_id: UUID | None = None,
    attempt_id: UUID | None = None,
) -> tuple[list[CreativeProposal], CreativeOutcome]:
    """对候选热点做创意重算；单条失败只记录错误码，不影响其他候选。"""
    del now  # 时间由调用方统一控制
    outcome = CreativeOutcome()
    proposals: list[CreativeProposal] = []
    if not candidates:
        return proposals, outcome
    if os.environ.get("HOT_TOPIC_AI_ENABLED", "1").strip() == "0":
        outcome.errors.append(
            {"error_code": "AI_CREATIVE_DISABLED", "summary": "AI 创意层已通过环境变量关闭"}
        )
        return proposals, outcome

    limit = min(len(candidates), MAX_CANDIDATES_PER_STORE)
    for candidate in candidates[:limit]:
        outcome.candidates += 1
        topic = candidate.topic
        source = db.get(HotTopicSource, topic.source_id)
        source_key = source.source_key if source else None
        blocked = blacklist_reason(topic, source_key)
        if blocked:
            outcome.excluded += 1
            outcome.excluded_topic_ids.add(topic.id)
            outcome.errors.append(
                {
                    "error_code": "AI_CREATIVE_EXCLUDED",
                    "summary": f"{topic.title[:40]}：{blocked}",
                }
            )
            _store_cache(
                db,
                store_id=store_id,
                topic=topic,
                context_hash=ctx.fingerprint,
                payload={"excluded": True, "exclude_reason": blocked},
            )
            continue

        payload = _cached(db, topic.id, ctx.fingerprint)
        if payload is not None:
            outcome.cache_hits += 1
        else:
            model_input = _build_input(db, ctx, candidate)
            last_error: tuple[str, bool] = ("AI_CREATIVE_FAILED", False)
            for attempt in range(RETRY_ATTEMPTS):
                try:
                    raw = _call_model(
                        db,
                        store_id=store_id,
                        job_id=job_id,
                        attempt_id=attempt_id,
                        topic_id=topic.id,
                        payload=model_input,
                    )
                    outcome.model_calls += 1
                    validated, error_code = validate_creative_payload(raw)
                    if validated is None:
                        outcome.errors.append(
                            {
                                "error_code": error_code or "AI_CREATIVE_INVALID_OUTPUT",
                                "summary": f"{topic.title[:40]}：创意输出结构不合法，已丢弃",
                            }
                        )
                        last_error = (error_code or "AI_CREATIVE_INVALID_OUTPUT", False)
                        break
                    payload = validated
                    _store_cache(
                        db,
                        store_id=store_id,
                        topic=topic,
                        context_hash=ctx.fingerprint,
                        payload=payload,
                    )
                    break
                except Exception as exc:  # noqa: BLE001 - 失败降级，不拖垮整轮
                    code, retryable = _error_code(exc)
                    last_error = (code, retryable)
                    outcome.model_calls += 1
                    if retryable and attempt + 1 < RETRY_ATTEMPTS:
                        time.sleep(RETRY_BACKOFF_SECONDS * (attempt + 1))
                        continue
                    break
            if payload is None:
                outcome.failed_topic_ids.add(topic.id)
                outcome.errors.append(
                    {
                        "error_code": last_error[0],
                        "summary": f"{topic.title[:40]}：创意重算失败，已回退规则结果",
                    }
                )
                continue

        if bool(payload.get("excluded")):
            outcome.excluded += 1
            outcome.excluded_topic_ids.add(topic.id)
            continue
        raw_confidence = payload.get("confidence")
        confidence = (
            float(raw_confidence)
            if isinstance(raw_confidence, (int, float))
            else 0.0
        )
        if confidence < 0.5:
            outcome.excluded += 1
            outcome.excluded_topic_ids.add(topic.id)
            outcome.errors.append(
                {
                    "error_code": "AI_CREATIVE_LOW_CONFIDENCE",
                    "summary": f"{topic.title[:40]}：置信度 {confidence:.2f} 低于 0.50，已丢弃",
                }
            )
            continue
        raw_risk_notes = payload.get("risk_notes")
        proposals.append(
            CreativeProposal(
                topic=topic,
                score=round(confidence * 100, 2),
                payload=payload,
                risk_flags=(
                    [str(item) for item in raw_risk_notes]
                    if isinstance(raw_risk_notes, list)
                    else []
                ),
                reason=_proposal_reason(payload),
            )
        )
    return proposals, outcome


def create_ai_opportunity(
    db: Session,
    *,
    store_id: UUID,
    proposal: CreativeProposal,
    store_context_fingerprint: str,
    algorithm_version: int,
    version: int,
    now: datetime,
) -> StoreOpportunity:
    opportunity = StoreOpportunity(
        id=uuid4(),
        store_id=store_id,
        hot_topic_id=proposal.topic.id,
        store_context_fingerprint=store_context_fingerprint,
        matching_version=version,
        matching_algorithm_version=algorithm_version,
        relevance_score=Decimal(str(proposal.score)),
        match_method="hybrid",
        match_source="ai_creative",
        ai_creative_json=proposal.payload,
        ai_confidence=Decimal(str(proposal.payload.get("confidence") or 0)),
        ai_prompt_version=PROMPT_VERSION,
        matched_product_ids_json=[],
        matched_offer_ids_json=[],
        matched_audience_profile_ids_json=[],
        suggested_scenario=_clip(proposal.payload.get("theme"), 200),
        content_angle=_clip(proposal.payload.get("play"), 500),
        reason_summary=proposal.reason,
        risk_flags_json=[
            f"ai_risk:{_clip(item, 80)}" for item in proposal.risk_flags[:5]
        ],
        eligibility_status="eligible",
        matched_at=now,
        expires_at=proposal.topic.expires_at,
    )
    db.add(opportunity)
    return opportunity
