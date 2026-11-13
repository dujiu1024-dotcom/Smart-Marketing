"""热点与门店的品类门槛 + 加权匹配。

设计要点：
- 品类/行业 40%、实体/关键词 25%、客群/场景 15%、地域 10%、品牌安全 10%。
- 必须命中至少一个品类且至少命中一个内容词，才可能进入可采纳列表。
- 热度只用于同分排序，不参与资格判定。
- 增量匹配由 hot_topic_match_state 记录（门店 + 热点 + 内容哈希 + 门店上下文哈希）。
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, sessionmaker
from store_operator.db import SessionLocal  # type: ignore[import-untyped]
from store_operator.models import (  # type: ignore[import-untyped]
    AudienceProfile,
    BrandGuideline,
    HotTopic,
    HotTopicMatchState,
    Offer,
    Product,
    Store,
    StoreOpportunity,
    StoreProfile,
)

# 匹配算法版本变化会写入门店上下文哈希，触发该店全量回填重算。
MATCHING_ALGORITHM_VERSION = 5

logger = logging.getLogger(__name__)

CATEGORY_WEIGHT = 0.40
ENTITY_WEIGHT = 0.25
AUDIENCE_WEIGHT = 0.15
REGION_WEIGHT = 0.10
BRAND_WEIGHT = 0.10

ELIGIBLE_THRESHOLD = 0.45
REVIEW_THRESHOLD = 0.30

DEFAULT_MAX_OPPORTUNITIES_PER_STORE = 5
TOPIC_BATCH_SIZE = 200

INDUSTRY_TAXONOMY: dict[str, tuple[str, ...]] = {
    "餐饮": (
        "餐饮", "餐厅", "饭店", "火锅", "烧烤", "小吃", "快餐", "外卖", "堂食",
        "早餐", "夜宵", "菜品", "菜单", "食客", "下馆子",
    ),
    "咖啡": (
        "咖啡", "拿铁", "美式", "手冲", "冷萃", "浓缩", "卡布奇诺", "摩卡", "澳白",
        "dirty", "咖啡因", "咖啡馆", "咖啡店", "生椰", "燕麦奶",
    ),
    "茶饮": ("奶茶", "茶饮", "果茶", "柠檬茶", "奶盖", "珍珠", "鲜奶茶", "新茶饮"),
    "烘焙": ("烘焙", "面包", "蛋糕", "甜品", "吐司", "可颂", "贝果", "饼干"),
    "美业": ("美发", "理发", "美容", "美甲", "皮肤管理", "造型", "烫染"),
    "健身": ("健身", "私教", "瑜伽", "普拉提", "减脂", "增肌"),
    "教育": ("教育培训", "培训", "课程", "考研", "考试", "升学", "辅导", "学生"),
    "零售": ("便利店", "超市", "零售", "杂货", "折扣店"),
    "宠物": ("宠物", "猫咖", "狗咖", "宠物店", "撸猫"),
    "住宿": ("酒店", "民宿", "住宿", "客房", "旅馆"),
    "娱乐": ("剧本杀", "密室", "KTV", "桌游", "电影", "演出"),
}

CATEGORY_PARENT: dict[str, str] = {"咖啡": "餐饮", "茶饮": "餐饮", "烘焙": "餐饮"}

# 泛词降权：这些词可以命中，但不能单独构成匹配依据。
GENERIC_TERMS: frozenset[str] = frozenset(
    {
        "体验", "学生", "人数", "活动", "优惠", "免费", "推荐", "热门", "打卡",
        "新店", "开业", "网友", "视频", "直播", "曝光", "热搜", "话题", "新闻",
        "今日", "全国", "消费", "价格", "上涨", "下降", "市场", "品牌", "门店",
        "顾客", "服务", "产品", "新品", "上线", "发布", "大家", "可以", "怎么",
        "为什么", "如何", "我们", "他们", "这个", "那个", "今年", "去年", "现在",
        "已经", "开始", "表示", "认为", "相关", "情况", "问题", "影响", "出现",
    }
)

PROVINCE_NAMES: tuple[str, ...] = (
    "北京", "上海", "天津", "重庆", "河北", "山西", "辽宁", "吉林", "黑龙江",
    "江苏", "浙江", "安徽", "福建", "江西", "山东", "河南", "湖北", "湖南",
    "广东", "海南", "四川", "贵州", "云南", "陕西", "甘肃", "青海", "台湾",
    "内蒙古", "广西", "西藏", "宁夏", "新疆", "香港", "澳门",
)

CITY_NAMES: tuple[str, ...] = (
    "北京", "上海", "广州", "深圳", "杭州", "成都", "重庆", "武汉", "南京", "西安",
    "苏州", "天津", "长沙", "郑州", "青岛", "宁波", "厦门", "福州", "济南", "合肥",
    "昆明", "大连", "沈阳", "哈尔滨", "长春", "石家庄", "太原", "南昌", "贵阳",
    "南宁", "海口", "兰州", "西宁", "银川", "乌鲁木齐", "呼和浩特", "拉萨", "无锡",
    "佛山", "东莞", "珠海", "温州", "泉州", "烟台", "常州", "徐州", "嘉兴", "绍兴",
)

REGION_SUFFIXES = ("特别行政区", "自治区", "自治州", "省", "市", "区", "县", "地区")

_PUNCTUATION = re.compile(r"[\s\u3000,，。.!！?？;；:：、/\\|()（）\[\]【】<>《》\"'“”‘’~\-—_=+*#&%$@^]+")
_CJK_RUN = re.compile(r"[\u4e00-\u9fff]{2,}")
_LATIN_WORD = re.compile(r"[a-zA-Z][a-zA-Z0-9]{1,}")


@dataclass(slots=True)
class StoreContext:
    store_id: UUID
    profile: StoreProfile
    fingerprint: str
    categories: dict[str, str]
    entity_vocab: dict[str, float]
    audience_vocab: dict[str, float]
    products: list[Product]
    offers: list[Offer]
    audiences: list[AudienceProfile]
    brand: BrandGuideline | None
    region_tokens: set[str]


@dataclass(slots=True)
class Evaluation:
    topic: HotTopic
    score: float
    status: str
    category_hits: dict[str, str]
    entity_hits: list[str]
    audience_hits: list[str]
    region_state: str
    region_evidence: str
    risk_flags: list[str]
    product_ids: list[str]
    offer_ids: list[str]
    audience_ids: list[str]
    best_product_name: str | None
    best_offer_title: str | None
    reason: str

    @property
    def heat(self) -> Decimal:
        return self.topic.heat_value or Decimal(0)


@dataclass(slots=True)
class MatchOutcome:
    store_id: str
    evaluated: int = 0
    created: int = 0
    skipped: int = 0
    duplicate_events: int = 0
    deferred_by_cap: int = 0
    store_context_changed: bool = False
    items: list[dict[str, object]] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "store_id": self.store_id,
            "evaluated": self.evaluated,
            "opportunities_created": self.created,
            "skipped_below_threshold": self.skipped,
            "duplicate_events": self.duplicate_events,
            "deferred_by_cap": self.deferred_by_cap,
            "store_context_changed": self.store_context_changed,
            "items": self.items,
        }


def normalize_text(value: str) -> str:
    return unicodedata.normalize("NFKC", value or "").lower().strip()


def topic_content_hash(title: str, summary: str | None, tags: list[str] | None) -> str:
    payload = json.dumps(
        [normalize_text(title), normalize_text(summary or ""), sorted(normalize_text(t) for t in (tags or []))],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def event_key(title: str) -> str:
    """标题归一化聚类键：去掉标点/空白/话题符号，合并跨源同一事件。"""
    normalized = normalize_text(title)
    normalized = re.sub(r"[#【】\[\]（）()「」『』<>《》\"'“”‘’·•…—\-_=+~|/\\,，。.!！?？;；:：、]", "", normalized)
    normalized = re.sub(r"\s+", "", normalized)
    return normalized[:120]


def _region_variants(value: str) -> set[str]:
    text = normalize_text(value)
    variants = {text}
    for suffix in REGION_SUFFIXES:
        if text.endswith(suffix) and len(text) > len(suffix):
            variants.add(text[: -len(suffix)])
    return {item for item in variants if len(item) >= 2}


def _phrase_candidates(text: str) -> list[str]:
    phrases: list[str] = []
    for segment in _PUNCTUATION.split(normalize_text(text)):
        for match in _CJK_RUN.finditer(segment):
            run = match.group(0)
            if 2 <= len(run) <= 12:
                phrases.append(run)
            elif len(run) > 12:
                # 长句只保留 2-6 字的滑窗，避免把整句当词条。
                phrases.extend(run[index:index + 6] for index in range(0, len(run) - 5, 3))
    phrases.extend(match.group(0) for match in _LATIN_WORD.finditer(normalize_text(text)))
    return phrases


def _add_terms(vocab: dict[str, float], value: str | None, weight: float) -> None:
    if not value:
        return
    for phrase in _phrase_candidates(value):
        term = phrase.strip()
        if len(term) < 2 or term in GENERIC_TERMS:
            continue
        vocab[term] = max(vocab.get(term, 0.0), weight)


def infer_store_categories(
    profile: StoreProfile, products: list[Product], offers: list[Offer]
) -> dict[str, str]:
    """从业态与商品分类推断门店品类；推断不出时返回空字典（不硬猜）。"""
    sources = [
        profile.industry_category or "",
        profile.business_type or "",
        profile.introduction or "",
        *(product.category or "" for product in products),
        *(product.name for product in products),
        *(offer.title for offer in offers),
    ]
    text = normalize_text(" ".join(value for value in sources if value))
    hits: dict[str, str] = {}
    for category, keywords in INDUSTRY_TAXONOMY.items():
        for keyword in keywords:
            if normalize_text(keyword) in text:
                hits[category] = keyword
                break
    for category in list(hits):
        parent = CATEGORY_PARENT.get(category)
        if parent and parent not in hits:
            hits[parent] = hits[category]
    return hits


def detect_topic_categories(topic: HotTopic) -> dict[str, str]:
    text = normalize_text(
        " ".join(
            [
                topic.title,
                topic.summary or "",
                *(topic.topic_tags_json or []),
                *(topic.industry_tags_json or []),
            ]
        )
    )
    hits: dict[str, str] = {}
    for category, keywords in INDUSTRY_TAXONOMY.items():
        for keyword in keywords:
            if normalize_text(keyword) in text:
                hits[category] = keyword
                break
    for category in list(hits):
        parent = CATEGORY_PARENT.get(category)
        if parent and parent not in hits:
            hits[parent] = hits[category]
    return hits


def _specific_categories(categories: dict[str, str]) -> set[str]:
    """返回门店的细分品类；只有父品类（如“餐饮”）的门店视为泛行业。"""
    parent_categories = set(CATEGORY_PARENT.values())
    specific = {category for category in categories if category not in parent_categories}
    return specific or set(categories)


def _build_entity_vocab(
    profile: StoreProfile,
    products: list[Product],
    offers: list[Offer],
    brand: BrandGuideline | None,
    categories: dict[str, str],
) -> dict[str, float]:
    vocab: dict[str, float] = {}
    _add_terms(vocab, profile.business_type, 0.6)
    _add_terms(vocab, profile.introduction, 0.4)
    for product in products:
        _add_terms(vocab, product.name, 1.0)
        _add_terms(vocab, product.category, 0.7)
        for point in product.key_selling_points_json or []:
            _add_terms(vocab, point, 0.8)
    for offer in offers:
        _add_terms(vocab, offer.title, 0.8)
        _add_terms(vocab, offer.offer_type, 0.6)
    if brand is not None:
        for phrase in brand.common_phrases_json or []:
            _add_terms(vocab, phrase, 0.5)
        _add_terms(vocab, brand.positioning, 0.5)
    # 细分品类词权重更高；父品类（餐饮）词保留但降权，避免把烧烤/火锅误判为可采纳。
    specific = _specific_categories(categories)
    parent_only = set(categories) - specific
    for category in specific:
        for keyword in INDUSTRY_TAXONOMY.get(category, ()):
            term = normalize_text(keyword)
            if len(term) >= 2 and term not in GENERIC_TERMS:
                vocab.setdefault(term, 0.6)
    for category in parent_only:
        for keyword in INDUSTRY_TAXONOMY.get(category, ()):
            term = normalize_text(keyword)
            if len(term) >= 2 and term not in GENERIC_TERMS:
                vocab.setdefault(term, 0.35)
    return vocab


def _build_audience_vocab(audiences: list[AudienceProfile]) -> dict[str, float]:
    vocab: dict[str, float] = {}
    for audience in audiences:
        _add_terms(vocab, audience.name, 1.0)
        _add_terms(vocab, audience.audience_description, 0.8)
        for scenario in audience.consumption_scenarios_json or []:
            _add_terms(vocab, scenario, 1.0)
        for period in audience.consumption_periods_json or []:
            _add_terms(vocab, period, 0.8)
        for motivation in audience.purchase_motivations_json or []:
            _add_terms(vocab, motivation, 0.8)
        for objection in audience.common_objections_json or []:
            _add_terms(vocab, objection, 0.5)
    return vocab


def _store_region_tokens(profile: StoreProfile) -> set[str]:
    tokens: set[str] = set()
    for value in (profile.region, profile.province, profile.city, profile.district):
        if value and value.strip():
            tokens.update(_region_variants(value))
    return tokens


def _topic_text(topic: HotTopic) -> str:
    return normalize_text(
        " ".join(
            [
                topic.title,
                topic.summary or "",
                *(topic.topic_tags_json or []),
                *(topic.industry_tags_json or []),
            ]
        )
    )


def _store_fingerprint(profile: StoreProfile, products: list[Product], offers: list[Offer],
                       audiences: list[AudienceProfile], brand: BrandGuideline | None) -> str:
    parts = [
        f"matcher:{MATCHING_ALGORITHM_VERSION}",
        (
            f"profile:{profile.id}:{profile.current_version}:{profile.industry_category}:"
            f"{profile.business_type}:{profile.region}:{profile.province}:{profile.city}:"
            f"{profile.district}"
        ),
    ]
    if brand is not None:
        parts.append(f"brand:{brand.id}:{brand.current_version}")
    parts.extend(f"p:{item.id}:{item.current_version}" for item in products)
    parts.extend(f"o:{item.id}:{item.current_version}" for item in offers)
    parts.extend(f"a:{item.id}:{item.current_version}" for item in audiences)
    return hashlib.sha256("|".join(sorted(parts)).encode("utf-8")).hexdigest()


def load_store_context(db: Session, store_id: UUID) -> StoreContext | None:
    profile = db.scalar(
        select(StoreProfile).where(
            StoreProfile.store_id == store_id, StoreProfile.fact_status == "confirmed"
        )
    )
    products = db.scalars(
        select(Product).where(
            Product.store_id == store_id,
            Product.fact_status == "confirmed",
            Product.availability_status.in_(["available", "limited", "seasonal"]),
        )
    ).all()
    offers = db.scalars(
        select(Offer).where(
            Offer.store_id == store_id,
            Offer.fact_status == "confirmed",
            Offer.status == "active",
        )
    ).all()
    audiences = db.scalars(
        select(AudienceProfile).where(
            AudienceProfile.store_id == store_id,
            AudienceProfile.fact_status == "confirmed",
        )
    ).all()
    if profile is None or (not products and not offers and not audiences):
        return None
    brand = db.scalar(
        select(BrandGuideline).where(
            BrandGuideline.store_id == store_id, BrandGuideline.fact_status == "confirmed"
        )
    )
    categories = infer_store_categories(profile, products, offers)
    return StoreContext(
        store_id=store_id,
        profile=profile,
        fingerprint=_store_fingerprint(profile, products, offers, audiences, brand),
        categories=categories,
        entity_vocab=_build_entity_vocab(profile, products, offers, brand, categories),
        audience_vocab=_build_audience_vocab(audiences),
        products=list(products),
        offers=list(offers),
        audiences=list(audiences),
        brand=brand,
        region_tokens=_store_region_tokens(profile),
    )


def _idf_weights(topic_texts: list[str], vocab: dict[str, float]) -> dict[str, float]:
    """按当前热点批次计算 IDF，降低“活动/体验”等高频泛词的权重。"""
    total = max(1, len(topic_texts))
    weights: dict[str, float] = {}
    for term in vocab:
        document_frequency = sum(1 for text in topic_texts if term in text)
        idf = math.log((total + 1) / (document_frequency + 0.5))
        weights[term] = max(0.15, min(1.0, idf / 3.0))
    return weights


def _term_weight(term: str, base: float, idf: dict[str, float]) -> float:
    length_factor = min(1.5, 1.0 + 0.15 * (len(term) - 2))
    return base * idf.get(term, 0.3) * length_factor


def _extract_topic_regions(topic: HotTopic) -> set[str]:
    regions: set[str] = set()
    if topic.region:
        regions.update(_region_variants(topic.region))
    text = _topic_text(topic)
    for name in {*PROVINCE_NAMES, *CITY_NAMES}:
        if normalize_text(name) in text:
            regions.update(_region_variants(name))
    return regions


def _brand_risk_flags(text: str, brand: BrandGuideline | None) -> list[str]:
    if brand is None:
        return []
    prohibited = [
        phrase.strip()
        for phrase in (brand.prohibited_phrases_json or [])
        if isinstance(phrase, str) and phrase.strip()
    ]
    return ["brand_prohibited_phrase"] if any(
        normalize_text(phrase) in text for phrase in prohibited
    ) else []


def _match_audience_hits(
    text: str, ctx: StoreContext, idf: dict[str, float]
) -> tuple[list[str], list[str], float]:
    hits: list[str] = []
    audience_ids: list[str] = []
    weight = 0.0
    for audience in ctx.audiences:
        audience_text_parts = [
            audience.name,
            audience.audience_description or "",
            *(audience.consumption_scenarios_json or []),
            *(audience.consumption_periods_json or []),
            *(audience.purchase_motivations_json or []),
        ]
        matched_for_audience = [
            term
            for term in ctx.audience_vocab
            if term in normalize_text(" ".join(audience_text_parts)) and term in text
        ]
        if matched_for_audience:
            audience_ids.append(str(audience.id))
            for term in matched_for_audience:
                if term not in hits:
                    hits.append(term)
                    weight += _term_weight(term, ctx.audience_vocab[term], idf)
    return hits, audience_ids, min(1.0, weight / 1.5)


def _match_entity_hits(
    text: str, ctx: StoreContext, idf: dict[str, float]
) -> tuple[list[str], float, str | None, str | None, list[str], list[str]]:
    hits: list[str] = []
    weight = 0.0
    for term, base in ctx.entity_vocab.items():
        if term in text:
            hits.append(term)
            weight += _term_weight(term, base, idf)
    hits.sort(key=lambda term: _term_weight(term, ctx.entity_vocab[term], idf), reverse=True)

    product_scores: list[tuple[float, Product]] = []
    for product in ctx.products:
        product_text = normalize_text(
            " ".join(
                [
                    product.name,
                    product.category or "",
                    product.description or "",
                    *(product.key_selling_points_json or []),
                ]
            )
        )
        matched = [term for term in hits if term in product_text]
        if matched:
            product_scores.append(
                (sum(_term_weight(t, ctx.entity_vocab[t], idf) for t in matched), product)
            )
    offer_scores: list[tuple[float, Offer]] = []
    for offer in ctx.offers:
        offer_text = normalize_text(
            " ".join([offer.title, offer.offer_type, str(offer.terms_json or "")])
        )
        matched = [term for term in hits if term in offer_text]
        if matched:
            offer_scores.append(
                (sum(_term_weight(t, ctx.entity_vocab[t], idf) for t in matched), offer)
            )
    product_scores.sort(key=lambda pair: pair[0], reverse=True)
    offer_scores.sort(key=lambda pair: pair[0], reverse=True)
    return (
        hits,
        min(1.0, weight / 2.0),
        product_scores[0][1].name if product_scores else None,
        offer_scores[0][1].title if offer_scores else None,
        [str(item.id) for _, item in product_scores[:5]],
        [str(item.id) for _, item in offer_scores[:5]],
    )


def evaluate_topic(topic: HotTopic, ctx: StoreContext, idf: dict[str, float]) -> Evaluation | None:
    text = _topic_text(topic)
    category_hits = {
        category: keyword
        for category, keyword in detect_topic_categories(topic).items()
        if category in ctx.categories
    }
    entity_hits, entity_score, best_product, best_offer, product_ids, offer_ids = (
        _match_entity_hits(text, ctx, idf)
    )
    # 至少要命中一个内容词，否则纯品类/地域重合不算匹配（仍保留为 AI 候选信号）。
    if not entity_hits:
        return None
    audience_hits, audience_ids, audience_score = _match_audience_hits(text, ctx, idf)

    topic_regions = _extract_topic_regions(topic)
    if not topic_regions:
        region_score, region_state, region_evidence = 0.5, "unknown", "标题与摘要未出现城市/省份"
    elif not ctx.region_tokens:
        region_score, region_state, region_evidence = 0.5, "unknown", "门店未登记地区"
    else:
        overlaps = topic_regions & ctx.region_tokens
        if overlaps:
            region_score, region_state = 1.0, "matched"
            region_evidence = f"「{'、'.join(sorted(overlaps))}」与门店地区一致"
        else:
            region_score, region_state = 0.0, "mismatch"
            region_evidence = f"「{'、'.join(sorted(topic_regions))}」与门店地区不一致"

    risk_flags = _brand_risk_flags(text, ctx.brand)
    brand_score = 0.0 if risk_flags else 1.0
    specific_hits = set(category_hits) & _specific_categories(ctx.categories)
    if specific_hits:
        category_score = 1.0
    elif category_hits:
        # 只命中“餐饮”这类父品类时降权，避免把烧烤/火锅新闻当成咖啡店机会。
        category_score = 0.4
    else:
        category_score = 0.0
    score = round(
        CATEGORY_WEIGHT * category_score
        + ENTITY_WEIGHT * entity_score
        + AUDIENCE_WEIGHT * audience_score
        + REGION_WEIGHT * region_score
        + BRAND_WEIGHT * brand_score,
        4,
    )

    reasons: list[str] = []
    if not ctx.categories:
        reasons.append("门店行业标签未能从业态/商品推断，只能人工复核")
    if not category_hits:
        reasons.append("未命中门店品类")
    elif not specific_hits:
        reasons.append("仅命中父品类，未命中门店细分品类")
    if region_state == "mismatch":
        reasons.append("地域明确不匹配")
    if risk_flags:
        reasons.append("命中品牌禁用词")
    if score < ELIGIBLE_THRESHOLD:
        reasons.append(f"加权得分低于可采纳阈值 {ELIGIBLE_THRESHOLD:.2f}")

    if (
        ctx.categories
        and specific_hits
        and not reasons
        and score >= ELIGIBLE_THRESHOLD
    ):
        status = "eligible"
    elif score >= REVIEW_THRESHOLD:
        status = "review_required"
    else:
        return None
    if not ctx.categories or not specific_hits:
        status = "review_required"

    category_desc = "、".join(
        f"{category}（{keyword}）" for category, keyword in category_hits.items()
    ) or "无"
    audience_desc = "、".join(audience_hits[:5]) or "无"
    entity_desc = "、".join(entity_hits[:5])
    reason = (
        f"命中品类：{category_desc}；"
        f"命中内容词：{entity_desc}；"
        f"命中客群/场景词：{audience_desc}；"
        f"地域：{region_evidence}；"
        f"加权得分 {score:.2f} = 品类{category_score:.2f}×{CATEGORY_WEIGHT:.2f}"
        f" + 实体{entity_score:.2f}×{ENTITY_WEIGHT:.2f}"
        f" + 客群{audience_score:.2f}×{AUDIENCE_WEIGHT:.2f}"
        f" + 地域{region_score:.2f}×{REGION_WEIGHT:.2f}"
        f" + 品牌安全{brand_score:.2f}×{BRAND_WEIGHT:.2f}。"
    )
    if reasons:
        reason += "未达可采纳原因：" + "；".join(dict.fromkeys(reasons)) + "。"
    reason += "热度仅用于排序，不参与资格判定。"

    return Evaluation(
        topic=topic,
        score=score,
        status=status,
        category_hits=category_hits,
        entity_hits=entity_hits,
        audience_hits=audience_hits,
        region_state=region_state,
        region_evidence=region_evidence,
        risk_flags=risk_flags,
        product_ids=product_ids,
        offer_ids=offer_ids,
        audience_ids=audience_ids,
        best_product_name=best_product,
        best_offer_title=best_offer,
        reason=reason,
    )


def _valid_topic_conditions(now: datetime) -> list[object]:
    return [
        HotTopic.evidence_status == "collected",
        or_(HotTopic.expires_at.is_(None), HotTopic.expires_at > now),
    ]


def _max_opportunities_per_store() -> int:
    raw = os.environ.get("HOT_TOPIC_MAX_OPPORTUNITIES_PER_STORE", "")
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_MAX_OPPORTUNITIES_PER_STORE
    return value if value > 0 else DEFAULT_MAX_OPPORTUNITIES_PER_STORE


def _load_existing_opportunities(
    db: Session, store_id: UUID, fingerprint: str
) -> tuple[dict[UUID, int], set[str]]:
    rows = db.execute(
        select(StoreOpportunity, HotTopic.title)
        .join(HotTopic, HotTopic.id == StoreOpportunity.hot_topic_id)
        .where(StoreOpportunity.store_id == store_id)
    ).all()
    versions: dict[UUID, int] = {}
    current_events: set[str] = set()
    for opportunity, title in rows:
        topic_id = opportunity.hot_topic_id
        versions[topic_id] = max(versions.get(topic_id, 0), opportunity.matching_version)
        if (
            opportunity.store_context_fingerprint == fingerprint
            and opportunity.stale_at is None
        ):
            current_events.add(event_key(title))
    return versions, current_events


def _load_match_states(db: Session, store_id: UUID) -> dict[UUID, HotTopicMatchState]:
    rows = db.scalars(
        select(HotTopicMatchState).where(HotTopicMatchState.store_id == store_id)
    ).all()
    return {row.hot_topic_id: row for row in rows}


def _upsert_state(
    db: Session,
    states: dict[UUID, HotTopicMatchState],
    store_id: UUID,
    topic: HotTopic,
    content_hash: str,
    fingerprint: str,
    now: datetime,
) -> None:
    state = states.get(topic.id)
    if state is None:
        state = HotTopicMatchState(
            store_id=store_id,
            hot_topic_id=topic.id,
            topic_content_hash=content_hash,
            store_context_hash=fingerprint,
            matched_at=now,
            match_version=MATCHING_ALGORITHM_VERSION,
        )
        db.add(state)
        states[topic.id] = state
    else:
        state.topic_content_hash = content_hash
        state.store_context_hash = fingerprint
        state.matched_at = now
        state.match_version = MATCHING_ALGORITHM_VERSION


def match_store(
    db: Session,
    store_id: UUID,
    *,
    now: datetime | None = None,
    max_opportunities: int | None = None,
    force_full: bool = False,
    job_id: UUID | None = None,
    attempt_id: UUID | None = None,
) -> MatchOutcome:
    """增量匹配一家门店：只算未评估过或内容/门店上下文变化的热点。"""
    now = now or datetime.now(UTC)
    outcome = MatchOutcome(store_id=str(store_id))
    ctx = load_store_context(db, store_id)
    if ctx is None:
        return outcome

    states = _load_match_states(db, store_id)
    if states:
        # 以最近一次评估记录判断门店上下文是否变化；被限额截断的热点可能仍带旧哈希，
        # 不能因此触发每次全量重算。
        latest_state = max(states.values(), key=lambda item: (item.matched_at, item.match_version))
        store_changed = force_full or latest_state.store_context_hash != ctx.fingerprint
    else:
        store_changed = True
    outcome.store_context_changed = store_changed

    idf_source = db.execute(
        select(
            HotTopic.title,
            HotTopic.summary,
            HotTopic.topic_tags_json,
            HotTopic.industry_tags_json,
        ).where(*_valid_topic_conditions(now))
    ).all()
    idf = _idf_weights(
        [
            normalize_text(" ".join([title, summary or "", *tags, *industry_tags]))
            for title, summary, tags, industry_tags in idf_source
        ],
        {**ctx.entity_vocab, **ctx.audience_vocab},
    )

    versions, current_events = _load_existing_opportunities(db, store_id, ctx.fingerprint)
    if store_changed:
        # 门店资料变化后旧机会不再代表当前画像，统一标记 stale，保留历史不删除。
        db.execute(
            StoreOpportunity.__table__.update()
            .where(
                StoreOpportunity.store_id == store_id,
                StoreOpportunity.stale_at.is_(None),
            )
            .values(stale_at=now)
        )

    evaluations: dict[str, Evaluation] = {}
    duplicate_topic_ids: list[UUID] = []
    evaluated_topics: dict[UUID, tuple[HotTopic, str]] = {}
    discarded_topic_ids: list[UUID] = []

    last_id: UUID | None = None
    while True:
        conditions = [*_valid_topic_conditions(now)]
        statement = select(HotTopic)
        if not store_changed:
            statement = statement.outerjoin(
                HotTopicMatchState,
                and_(
                    HotTopicMatchState.hot_topic_id == HotTopic.id,
                    HotTopicMatchState.store_id == store_id,
                ),
            ).where(
                or_(
                    HotTopicMatchState.hot_topic_id.is_(None),
                    HotTopicMatchState.topic_content_hash != HotTopic.content_hash,
                )
            )
        statement = statement.where(*conditions)
        if last_id is not None:
            statement = statement.where(HotTopic.id > last_id)
        batch = db.scalars(
            statement.order_by(HotTopic.id).limit(TOPIC_BATCH_SIZE)
        ).all()
        if not batch:
            break
        last_id = batch[-1].id
        for topic in batch:
            content_hash = topic_content_hash(
                topic.title, topic.summary, topic.topic_tags_json
            )
            if topic.content_hash != content_hash:
                # 历史数据或采集端未写入时补齐，保证下一轮可增量比较。
                topic.content_hash = content_hash
            evaluated_topics[topic.id] = (topic, content_hash)
            outcome.evaluated += 1
            key = event_key(topic.title)
            evaluation = evaluate_topic(topic, ctx, idf)
            if evaluation is None:
                discarded_topic_ids.append(topic.id)
                continue
            if key in current_events:
                duplicate_topic_ids.append(topic.id)
                continue
            previous = evaluations.get(key)
            if previous is None:
                evaluations[key] = evaluation
            elif (evaluation.score, evaluation.heat) > (previous.score, previous.heat):
                evaluations[key] = evaluation
                duplicate_topic_ids.append(previous.topic.id)
            else:
                duplicate_topic_ids.append(evaluation.topic.id)

    limit = max_opportunities or _max_opportunities_per_store()
    ranked = sorted(
        evaluations.values(), key=lambda item: (item.score, item.heat), reverse=True
    )
    selected = ranked[:limit]
    deferred = ranked[limit:]

    for evaluation in selected:
        topic = evaluation.topic
        version = versions.get(topic.id, 0) + 1
        db.add(
            StoreOpportunity(
                id=uuid4(),
                store_id=store_id,
                hot_topic_id=topic.id,
                store_context_fingerprint=ctx.fingerprint,
                matching_version=version,
                matching_algorithm_version=MATCHING_ALGORITHM_VERSION,
                relevance_score=round(Decimal(str(evaluation.score)) * 100, 3),
                match_method="rules",
                matched_product_ids_json=evaluation.product_ids,
                matched_offer_ids_json=evaluation.offer_ids,
                matched_audience_profile_ids_json=evaluation.audience_ids,
                suggested_scenario=evaluation.best_offer_title,
                content_angle=(
                    f"围绕{evaluation.best_product_name}回应当前话题"
                    if evaluation.best_product_name
                    else None
                ),
                reason_summary=evaluation.reason,
                risk_flags_json=evaluation.risk_flags,
                eligibility_status=evaluation.status,
                matched_at=now,
                expires_at=topic.expires_at,
            )
        )
        outcome.created += 1
        outcome.items.append(
            {
                "topic_id": str(topic.id),
                "title": topic.title,
                "score": evaluation.score,
                "status": evaluation.status,
                "reason": evaluation.reason,
            }
        )
        content_hash = topic_content_hash(topic.title, topic.summary, topic.topic_tags_json)
        _upsert_state(db, states, store_id, topic, content_hash, ctx.fingerprint, now)

    # 同事件落选、低于阈值、已给过当前上下文的条目也写状态，避免重复计算。
    handled_ids = {
        *(item.topic.id for item in selected),
        *duplicate_topic_ids,
        *discarded_topic_ids,
    }
    for topic, content_hash in evaluated_topics.values():
        if topic.id in handled_ids:
            _upsert_state(db, states, store_id, topic, content_hash, ctx.fingerprint, now)
    outcome.skipped = len(discarded_topic_ids)
    outcome.duplicate_events = len(duplicate_topic_ids)
    outcome.deferred_by_cap = len(deferred)
    db.flush()
    return outcome


def reconcile_all_stores(
    session_factory: sessionmaker[Session] = SessionLocal,
) -> dict[str, object]:
    """每日对账：补算未匹配的新热点，并在门店上下文变化时分页回填。"""
    with session_factory() as db:
        store_ids = db.scalars(
            select(StoreProfile.store_id)
            .join(Store, Store.id == StoreProfile.store_id)
            .where(
                StoreProfile.fact_status == "confirmed",
                Store.status == "active",
            )
        ).all()
    totals = {
        "stores": len(store_ids),
        "evaluated": 0,
        "opportunities_created": 0,
        "store_context_recomputed": 0,
    }
    for store_id in store_ids:
        try:
            with session_factory.begin() as db:
                outcome = match_store(db, store_id)
            totals["evaluated"] += outcome.evaluated
            totals["opportunities_created"] += outcome.created
            if outcome.store_context_changed:
                totals["store_context_recomputed"] += 1
        except Exception:  # pragma: no cover - 单店失败不阻塞对账
            logger.exception("hot topic reconcile failed for store %s", store_id)
    return totals
