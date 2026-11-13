from decimal import Decimal
from uuid import uuid4

from store_operator.models.opportunity_effects import HotTopic

from store_operator_worker.hot_topic_creative import (
    MAX_CANDIDATES_PER_STORE,
    blacklist_reason,
    validate_creative_payload,
)
from store_operator_worker.hot_topic_matching import Evaluation, select_ai_candidates


def _topic(title: str, heat: int = 0) -> HotTopic:
    return HotTopic(id=uuid4(), title=title, heat_value=Decimal(heat))


def _evaluation(
    topic: HotTopic,
    *,
    status: str = "weak",
    score: float = 0.2,
    entity_hits: list[str] | None = None,
    region_state: str = "unknown",
    category_specific: bool = False,
    risk_flags: list[str] | None = None,
) -> Evaluation:
    return Evaluation(
        topic=topic,
        score=score,
        status=status,
        category_hits={},
        entity_hits=entity_hits or [],
        audience_hits=[],
        region_state=region_state,
        region_evidence="",
        risk_flags=risk_flags or [],
        product_ids=[],
        offer_ids=[],
        audience_ids=[],
        best_product_name=None,
        best_offer_title=None,
        reason="test",
        category_specific=category_specific,
    )


def test_blacklist_blocks_disaster_and_mourning_topics():
    assert (
        blacklist_reason(_topic("上海一商场突发火灾 3人受伤"))
        == "命中硬性排除关键词：火灾"
    )
    assert "悼念" in (blacklist_reason(_topic("全城悼念")) or "")
    assert blacklist_reason(_topic("大连人队夺冠引爆全城庆祝")) is None


def test_validate_creative_payload_requires_concrete_offer():
    valid = {
        "excluded": False,
        "exclude_reason": "",
        "theme": "大连人夺冠·异乡球迷咖啡庆功局",
        "play": "凭大连身份证或球衣到店享庆功价",
        "offer": {
            "audience_condition": "持大连身份证或穿球衣的顾客",
            "mechanic": "免费升杯",
            "discount_rule": "免费升大杯，每桌限1杯",
        },
        "target_audience": "在沪大连人、球迷",
        "borrow_logic": "家乡球队夺冠，异乡人需要聚会据点",
        "risk_notes": ["避免地域贬损"],
        "channels": ["门店海报"],
        "confidence": 0.82,
    }
    payload, error = validate_creative_payload(valid)
    assert error is None
    assert payload is not None
    assert payload["offer"]["discount_rule"] == "免费升大杯，每桌限1杯"

    invalid = {**valid, "offer": {"audience_condition": "", "mechanic": "", "discount_rule": ""}}
    assert validate_creative_payload(invalid) == (None, "AI_CREATIVE_INVALID_OUTPUT")

    unsafe = {**valid, "theme": "商场火灾后特惠"}
    assert validate_creative_payload(unsafe) == (None, "AI_CREATIVE_UNSAFE_OUTPUT")


def test_select_ai_candidates_prioritizes_review_and_caps_batch():
    review = [
        _evaluation(_topic(f"上海咖啡新品{index}"), status="review_required", score=0.4)
        for index in range(MAX_CANDIDATES_PER_STORE - 2)
    ]
    eligible = _evaluation(_topic("上海咖啡老客回归"), status="eligible", score=0.6)
    cross_category = _evaluation(
        _topic("大连夺冠夜球迷挤满小店", heat=18_000_000),
        score=0.2,
        entity_hits=["小店"],
    )
    high_heat = _evaluation(_topic("大连球赛夺冠", heat=18_000_000), score=0.2)
    low_heat = _evaluation(_topic("某地小雨"), score=0.2)
    brand_risk = _evaluation(
        _topic("上海咖啡新品争议"), status="review_required", risk_flags=["brand_prohibited_phrase"]
    )

    candidates = select_ai_candidates(
        [*review, eligible, cross_category, high_heat, low_heat, brand_risk],
        {high_heat.topic.id},
    )
    titles = [candidate.topic.title for candidate in candidates]

    assert len(candidates) == MAX_CANDIDATES_PER_STORE
    assert eligible.topic.title not in titles
    assert brand_risk.topic.title not in titles
    assert cross_category.topic.title in titles
    assert high_heat.topic.title in titles
    assert low_heat.topic.title not in titles
