from types import SimpleNamespace

import pytest

from store_operator_worker.handlers import JobExecutionError
from store_operator_worker.hot_topics import (
    _collect_source,
    _parse_public_feed,
    _safe_https_url,
)


def _source(**overrides):
    base = {
        "source_url": "https://60s.viki.moe/v2/weibo",
        "terms_url": "https://60s.viki.moe/terms",
        "permitted_use": "仅用于热点选题参考，保留来源署名。",
        "source_type": "public_feed",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_parse_public_feed_supports_common_response_shapes():
    top_level = (
        b'[{"title": "A", "url": "https://example.com/a", "hot": 100},'
        b' {"name": "B", "link": "https://example.com/b", "hot_value": "2.3\\u4e07"}]'
    )
    items = _parse_public_feed(top_level)
    assert [item["title"] for item in items] == ["A", "B"]
    assert items[0]["heat_value"] == "100"
    assert items[1]["heat_value"] == "2.3万"

    nested = b'{"code": 200, "data": {"list": [{"word": "C", "url": "https://example.com/c"}]}}'
    assert _parse_public_feed(nested)[0]["title"] == "C"

    wrapped = b'{"code": 0, "data": [{"title": "D", "link": "https://example.com/d"}]}'
    assert _parse_public_feed(wrapped)[0]["id"] == "https://example.com/d"

    string_rows = b'{"code": 200, "data": ["E", "F"]}'
    assert [item["title"] for item in _parse_public_feed(string_rows)] == ["E", "F"]


def test_parse_public_feed_rejects_invalid_or_unrecognized_payload():
    with pytest.raises(JobExecutionError) as invalid_json:
        _parse_public_feed(b"<html>not json</html>")
    assert invalid_json.value.code == "SOURCE_FEED_INVALID"

    with pytest.raises(JobExecutionError) as unrecognized:
        _parse_public_feed(b'{"data": [{"unknown_field": "x"}]}')
    assert unrecognized.value.code == "SOURCE_FEED_INVALID"

    # 合法空列表仍是有效结果
    assert _parse_public_feed(b'{"data": []}') == []


def test_non_allowlisted_host_is_rejected_before_fetch():
    with pytest.raises(JobExecutionError) as excinfo:
        _safe_https_url("https://evil.example.com/v2/weibo", {"60s.viki.moe"})
    assert excinfo.value.code == "SOURCE_HOST_NOT_ALLOWED"
    assert excinfo.value.retryable is False


def test_source_without_registered_terms_is_rejected():
    for source in (
        _source(terms_url=None),
        _source(terms_url="   "),
        _source(permitted_use=""),
    ):
        with pytest.raises(JobExecutionError) as excinfo:
            _collect_source(None, source, {"60s.viki.moe"})
        assert excinfo.value.code == "SOURCE_TERMS_MISSING"
        assert excinfo.value.retryable is False
