import socket
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from threading import Event
from types import SimpleNamespace
from uuid import uuid4

import httpcore
import httpx

from store_operator_worker.handlers import (
    JobExecutionContext,
    clear_job_handlers_for_testing,
    resolve_job_handler,
)
from store_operator_worker.hot_topics import (
    MAX_FEED_BYTES,
    _brand_guideline_text,
    _brand_risk_flags,
    _collect_source,
    _match_score,
    _parse_feed,
    _PinnedSyncBackend,
    _region_matches,
    _safe_https_url,
    _store_profile_text,
    _tokens,
    register_hot_topic_handlers,
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


def test_region_matching_uses_province_city_and_district_not_only_region():
    profile = SimpleNamespace(
        region="日本",
        province="东京都",
        city="涩谷区",
        district="神南",
    )
    assert _region_matches("涩谷区", profile) is True
    assert _region_matches("大阪府", profile) is False
    assert _region_matches("关东地区", SimpleNamespace(
        region=None, province=None, city=None, district=None
    )) is None


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


def test_safe_https_url_returns_the_validated_public_address(monkeypatch):
    monkeypatch.setattr(
        "store_operator_worker.hot_topics.socket.getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ],
    )
    assert _safe_https_url("https://feeds.example.test/rss", {"feeds.example.test"}) == (
        "https://feeds.example.test/rss",
        "93.184.216.34",
    )


def test_safe_https_url_rejects_private_dns_answers(monkeypatch):
    monkeypatch.setattr(
        "store_operator_worker.hot_topics.socket.getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))
        ],
    )
    from store_operator_worker.handlers import JobExecutionError

    try:
        _safe_https_url("https://feeds.example.test/rss", {"feeds.example.test"})
    except JobExecutionError as exc:
        assert exc.code == "SOURCE_HOST_NOT_PUBLIC"
    else:
        raise AssertionError("private DNS answer must be rejected")


def test_pinned_backend_never_resolves_the_original_hostname_again(monkeypatch):
    monkeypatch.setattr(
        httpcore.SyncBackend,
        "connect_tcp",
        lambda self, host, port, timeout=None, local_address=None, socket_options=None: host,
    )
    backend = _PinnedSyncBackend("feeds.example.test", "93.184.216.34")
    assert backend.connect_tcp("feeds.example.test", 443) == "93.184.216.34"


class _FakeResponse:
    def __init__(self, chunks, status_code=200, url="https://feeds.example.test/rss"):
        self.chunks = chunks
        self.status_code = status_code
        self.url = url

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def raise_for_status(self):
        if self.status_code >= 400 or 300 <= self.status_code < 400:
            request = httpx.Request("GET", self.url)
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("upstream status", request=request, response=response)

    def iter_bytes(self):
        yield from self.chunks


class _FakeClient:
    response = None
    init_kwargs = None

    def __init__(self, *args, **kwargs):
        type(self).init_kwargs = kwargs

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def stream(self, method, url):
        return type(self).response


class _FakeDatabase:
    def __init__(self, existing=None):
        self.existing = existing
        self.added = []

    def scalar(self, statement):
        return self.existing

    def add(self, item):
        self.added.append(item)

    def flush(self):
        return None


def _fake_public_dns(monkeypatch):
    monkeypatch.setattr(
        "store_operator_worker.hot_topics.socket.getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ],
    )


def _fake_source():
    return SimpleNamespace(
        id="source-1",
        source_url="https://feeds.example.test/rss",
        terms_url="https://feeds.example.test/terms",
        permitted_use="Public feed permitted for editorial discovery",
        health_status="unknown",
        last_success_at=None,
        last_failure_at=None,
    )


def test_collect_source_rejects_oversized_stream_before_buffering(monkeypatch):
    _fake_public_dns(monkeypatch)
    _FakeClient.response = _FakeResponse([b"x" * (MAX_FEED_BYTES + 1)])
    monkeypatch.setattr("store_operator_worker.hot_topics.httpx.Client", _FakeClient)
    from store_operator_worker.handlers import JobExecutionError

    try:
        _collect_source(_FakeDatabase(), _fake_source(), {"feeds.example.test"})
    except JobExecutionError as exc:
        assert exc.code == "SOURCE_FEED_TOO_LARGE"
        assert exc.retryable is False
    else:
        raise AssertionError("oversized feed must be rejected")
    assert _FakeClient.init_kwargs["follow_redirects"] is False


def test_collect_source_maps_non_2xx_to_retryable_fetch_error(monkeypatch):
    _fake_public_dns(monkeypatch)
    _FakeClient.response = _FakeResponse([], status_code=503)
    monkeypatch.setattr("store_operator_worker.hot_topics.httpx.Client", _FakeClient)
    from store_operator_worker.handlers import JobExecutionError

    try:
        _collect_source(_FakeDatabase(), _fake_source(), {"feeds.example.test"})
    except JobExecutionError as exc:
        assert exc.code == "SOURCE_FETCH_FAILED"
        assert exc.retryable is True
    else:
        raise AssertionError("non-2xx feed response must fail")


def test_collect_source_deduplicates_existing_topic_and_marks_source_healthy(monkeypatch):
    _fake_public_dns(monkeypatch)
    payload = b"""<?xml version="1.0"?>
    <rss version="2.0"><channel><item>
      <guid>story-1</guid><title>Local spring drink trend</title>
      <link>https://feeds.example.test/story/1</link>
      <description>Seasonal drink launch</description>
    </item></channel></rss>"""
    _FakeClient.response = _FakeResponse([payload])
    monkeypatch.setattr("store_operator_worker.hot_topics.httpx.Client", _FakeClient)
    existing = SimpleNamespace(
        last_seen_at=None,
        expires_at=datetime.now(UTC) + timedelta(days=1),
        evidence_status="collected",
    )
    db = _FakeDatabase(existing=existing)
    source = _fake_source()

    inserted = _collect_source(db, source, {"feeds.example.test"})

    assert inserted == 0
    assert db.added == []
    assert existing.last_seen_at is not None
    assert source.health_status == "healthy"
    assert source.last_success_at is not None


def test_safe_https_url_rejects_nonstandard_https_ports(monkeypatch):
    from store_operator_worker.handlers import JobExecutionError

    try:
        _safe_https_url("https://feeds.example.test:8443/rss", {"feeds.example.test"})
    except JobExecutionError as exc:
        assert exc.code == "SOURCE_URL_INVALID"
    else:
        raise AssertionError("nonstandard HTTPS ports must be rejected")


def test_collect_source_maps_timeout_to_retryable_fetch_error(monkeypatch):
    _fake_public_dns(monkeypatch)

    class _TimeoutClient(_FakeClient):
        def stream(self, method, url):
            raise httpx.ReadTimeout("upstream timed out")

    monkeypatch.setattr("store_operator_worker.hot_topics.httpx.Client", _TimeoutClient)
    from store_operator_worker.handlers import JobExecutionError

    try:
        _collect_source(_FakeDatabase(), _fake_source(), {"feeds.example.test"})
    except JobExecutionError as exc:
        assert exc.code == "SOURCE_FETCH_FAILED"
        assert exc.retryable is True
    else:
        raise AssertionError("feed timeout must be retryable")


def test_collect_source_marks_reseen_expired_topic_as_expired(monkeypatch):
    _fake_public_dns(monkeypatch)
    payload = b"""<?xml version="1.0"?>
    <rss version="2.0"><channel><item>
      <guid>story-expired</guid><title>Expired seasonal topic</title>
      <link>https://feeds.example.test/story/expired</link>
    </item></channel></rss>"""
    _FakeClient.response = _FakeResponse([payload])
    monkeypatch.setattr("store_operator_worker.hot_topics.httpx.Client", _FakeClient)
    existing = SimpleNamespace(
        last_seen_at=None,
        expires_at=datetime.now(UTC) - timedelta(days=1),
        evidence_status="collected",
    )
    db = _FakeDatabase(existing=existing)

    _collect_source(db, _fake_source(), {"feeds.example.test"})

    assert existing.evidence_status == "expired"
    assert existing.last_seen_at is not None


def test_collection_handler_marks_source_failed_and_preserves_retryability(monkeypatch):
    from store_operator_worker.handlers import JobExecutionError

    _fake_public_dns(monkeypatch)

    class _TimeoutClient(_FakeClient):
        def stream(self, method, url):
            raise httpx.ReadTimeout("upstream timed out")

    monkeypatch.setattr("store_operator_worker.hot_topics.httpx.Client", _TimeoutClient)
    monkeypatch.setattr(
        "store_operator_worker.hot_topics._allowed_hosts",
        lambda: {"feeds.example.test"},
    )

    source = _fake_source()
    source.id = uuid4()
    source.enabled = True

    class _SessionFactory:
        def __init__(self):
            self.sessions = [_FakeDatabase(existing=source), _FakeDatabase(existing=source)]

        @contextmanager
        def begin(self):
            yield self.sessions.pop(0)

    context = JobExecutionContext(
        job_id=uuid4(),
        store_id=uuid4(),
        attempt_id=uuid4(),
        lease_token=uuid4(),
        worker_id="worker-test",
        deadline_at=datetime.now(UTC) + timedelta(minutes=1),
        cancellation_requested=Event(),
        lease_lost=Event(),
        update_progress_callback=lambda current, total: None,
    )
    clear_job_handlers_for_testing()
    try:
        register_hot_topic_handlers(_SessionFactory())
        handler = resolve_job_handler("hot_topics.collect_and_match.v1")
        assert handler is not None
        try:
            handler(context, {"schema_version": 1, "source_ids": [str(source.id)]})
        except JobExecutionError as exc:
            assert exc.code == "SOURCE_FETCH_FAILED"
            assert exc.retryable is True
        else:
            raise AssertionError("source fetch timeout must bubble up as retryable job failure")
        assert source.health_status == "failed"
        assert source.last_failure_at is not None
    finally:
        clear_job_handlers_for_testing()
