from datetime import UTC, datetime
from types import SimpleNamespace

from store_operator_worker.hot_topics import (
    _brand_guideline_text,
    _brand_risk_flags,
    _match_score,
    _parse_feed,
    _store_profile_text,
    _tokens,
)


def test_parse_rss_feed_preserves_source_url_and_published_timestamp():
    payload = b"""<?xml version="1.0"?>
    <rss version="2.0"><channel><item>
      <guid>story-1</guid><title>Local spring drink trend</title>
      <link>https://news.example.test/story/1</link>
      <description><![CDATA[New seasonal drink launches]]></description>
      <pubDate>Wed, 11 Nov 2026 08:00:00 +0000</pubDate>
    </item></channel></rss>"""
    items = _parse_feed(payload)
    assert len(items) == 1
    assert items[0]["id"] == "story-1"
    assert items[0]["title"] == "Local spring drink trend"
    assert items[0]["link"] == "https://news.example.test/story/1"
    assert items[0]["published_at"] == datetime(2026, 11, 11, 8, 0, tzinfo=UTC)


def test_parse_atom_feed_uses_alternate_link_and_updated_date():
    payload = b"""<?xml version="1.0"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry><id>urn:story:2</id><title>Weekend food market</title>
        <link rel="alternate" href="https://news.example.test/story/2"/>
        <summary>Market event and seasonal offers</summary>
        <updated>2026-11-11T10:00:00+00:00</updated>
      </entry>
    </feed>"""
    items = _parse_feed(payload)
    assert len(items) == 1
    assert items[0]["id"] == "urn:story:2"
    assert items[0]["link"] == "https://news.example.test/story/2"
    assert items[0]["summary"] == "Market event and seasonal offers"
    assert items[0]["published_at"] == datetime(2026, 11, 11, 10, 0, tzinfo=UTC)


def test_chinese_bigram_matching_is_deterministic_and_bounded():
    assert _tokens("春季新品饮品") >= {"春季", "季新", "新品", "品饮"}
    assert _match_score("春季新品饮品", "春季新品饮品") == 1.0
    assert 0.0 < _match_score("春季新品饮品", "春季饮品上新") < 1.0


def test_store_profile_matching_uses_industry_and_service_region():
    profile = SimpleNamespace(
        display_name="Tokyo Coffee",
        business_type="咖啡馆",
        industry_category="餐饮",
        introduction="主打手冲咖啡和季节限定饮品",
        service_radius="门店周边三公里",
        region="东京都",
        province="东京都",
        city="涩谷区",
        district="神南",
        service_capabilities_json=["堂食", "外带"],
    )
    text = _store_profile_text(profile)
    assert "餐饮" in text
    assert "涩谷区" in text
    assert _match_score("涩谷区季节限定饮品", text) > 0


def test_brand_guideline_prohibited_phrases_raise_review_risk():
    brand = SimpleNamespace(
        brand_story="坚持真实原料",
        positioning="社区精品咖啡",
        differentiators="当季烘焙",
        tone_of_voice="克制、真诚",
        visual_style="自然光",
        core_values_json=["真实"],
        common_phrases_json=["每日现磨"],
        cta_preferences_json=["到店体验"],
        prohibited_phrases_json=["保证治愈", "绝对有效"],
    )
    assert "社区精品咖啡" in _brand_guideline_text(brand)
    assert _brand_risk_flags("新品介绍中包含保证治愈", brand) == [
        "brand_prohibited_phrase"
    ]
    assert _brand_risk_flags("季节限定饮品上新", brand) == []
