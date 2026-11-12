from datetime import UTC, datetime

from store_operator_worker.hot_topics import _match_score, _parse_feed, _tokens


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
