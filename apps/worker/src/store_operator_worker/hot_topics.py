# ruff: noqa: I001
from __future__ import annotations

from typing import Any, cast

import hashlib
import html
import ipaddress
import json
import re
import socket
import time
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpcore
import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from store_operator.effects.easel_parsing import parse_num  # type: ignore[import-untyped]
from store_operator.models import (  # type: ignore[import-untyped]
    HotTopic,
    HotTopicHeatSample,
    HotTopicSource,
)
from store_operator_worker.handlers import (
    JobExecutionContext,
    JobExecutionError,
    register_job_handler,
)
from store_operator_worker.hot_topic_matching import match_store, topic_content_hash

MAX_FEED_BYTES = 2_000_000
MAX_FEED_ITEMS = 200
HTTP_TIMEOUT = httpx.Timeout(15.0, connect=5.0)
USER_AGENT = "AI-Store-Operator-HotTopicCollector/1.0"
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
RETRY_DELAY_SECONDS = 0.5


def _allowed_hosts() -> set[str]:
    from store_operator.config import settings  # type: ignore[import-untyped]

    return {
        host.strip().lower()
        for host in settings.hot_topic_allowed_hosts.split(",")
        if host.strip()
    }


class _PinnedSyncBackend(httpcore.SyncBackend):
    """Connect to the validated IP while preserving the URL hostname for TLS SNI."""

    def __init__(self, hostname: str, address: str) -> None:
        self.hostname = hostname.lower()
        self.address = address

    def connect_tcp(self, host: str, port: int, timeout: float | None = None,
                    local_address: str | None = None,
                    socket_options: Any = None) -> httpcore.NetworkStream:
        if host.lower() != self.hostname:
            raise OSError("Unexpected hostname passed to pinned feed transport")
        return super().connect_tcp(
            self.address, port, timeout=timeout, local_address=local_address,
            socket_options=socket_options,
        )


def _assert_public_host(host: str, allowed: set[str]) -> str:
    if host.lower() not in allowed:
        raise JobExecutionError(
            "SOURCE_HOST_NOT_ALLOWED",
            "Feed host is not in the configured allowlist.",
            retryable=False,
        )
    try:
        addresses = {str(item[4][0]) for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
    except OSError as exc:
        raise JobExecutionError(
            "SOURCE_DNS_FAILED", "Feed host could not be resolved.", retryable=True
        ) from exc
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise JobExecutionError(
            "SOURCE_HOST_NOT_PUBLIC",
            "Feed host resolves to a non-public network address.",
            retryable=False,
        )
    return min(addresses)


def _safe_https_url(value: str, allowed: set[str]) -> tuple[str, str]:
    parsed = urlsplit(value)
    host = (parsed.hostname or "").lower()
    try:
        port = parsed.port
    except ValueError as exc:
        raise JobExecutionError(
            "SOURCE_URL_INVALID", "Source URL port is invalid.", retryable=False
        ) from exc
    if (
        parsed.scheme != "https"
        or not host
        or parsed.username
        or parsed.password
        or port not in {None, 443}
    ):
        raise JobExecutionError(
            "SOURCE_URL_INVALID",
            "Source URL must use credential-free HTTPS on port 443.",
            retryable=False,
        )
    address = _assert_public_host(host, allowed)
    return value, address


def _text(node: ET.Element, tag: str) -> str:
    child = node.find(tag)
    if child is None:
        return ""
    value = " ".join(part.strip() for part in child.itertext() if part.strip())
    value = html.unescape(re.sub(r"<[^>]+>", " ", value))
    return " ".join(value.split())[:5000]


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].split(":")[-1].lower()


def _metadata_value(node: ET.Element, names: set[str]) -> str:
    for child in node.iter():
        if _local_name(child.tag) not in names:
            continue
        value = " ".join(part.strip() for part in child.itertext() if part.strip())
        value = value or child.attrib.get("value", "") or child.attrib.get("term", "")
        if value.strip():
            return value.strip()[:500]
    return ""


def _metadata_tags(node: ET.Element) -> list[str]:
    tags: list[str] = []
    for child in node.iter():
        if _local_name(child.tag) not in {"category", "subject", "tag", "keyword"}:
            continue
        value = child.attrib.get("term", "") or child.attrib.get("label", "")
        value = value or " ".join(part.strip() for part in child.itertext() if part.strip())
        value = value.strip()[:120]
        if value and value not in tags:
            tags.append(value)
    return tags[:50]


def _feed_entry_metadata(node: ET.Element) -> dict[str, object]:
    return {
        "region": _metadata_value(
            node, {"region", "area", "geo_region", "location", "province", "city", "district"}
        ) or None,
        "heat_value": _metadata_value(
            node, {"heat", "heat_value", "heat_score", "hotness", "popularity", "search_volume"}
        ) or None,
        "heat_unit": _metadata_value(
            node, {"heat_unit", "heat_metric", "score_unit", "metric_unit"}
        ) or None,
        "topic_tags": _metadata_tags(node),
    }


def _parse_published(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        try:
            # Atom timestamps are RFC 3339 / ISO 8601, unlike RSS pubDate.
            parsed = datetime.fromisoformat(value.strip())
        except (TypeError, ValueError, OverflowError):
            return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _parse_feed(payload: bytes) -> list[dict[str, object]]:
    if len(payload) > MAX_FEED_BYTES:
        raise JobExecutionError("SOURCE_FEED_TOO_LARGE", "Feed exceeded the configured size limit.", retryable=False)
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise JobExecutionError("SOURCE_FEED_INVALID", "Feed XML could not be parsed.", retryable=False) from exc
    items: list[dict[str, object]] = []
    rss_items = root.findall("./channel/item")
    if not rss_items:
        atom = "{http://www.w3.org/2005/Atom}"
        rss_items = root.findall(f"{atom}entry")
        for entry in rss_items[:MAX_FEED_ITEMS]:
            link = next((item.attrib.get("href", "") for item in entry.findall(f"{atom}link")
                         if item.attrib.get("rel", "alternate") == "alternate"), "")
            items.append({
                "id": _text(entry, f"{atom}id") or link,
                "title": _text(entry, f"{atom}title"),
                "link": link,
                "summary": _text(entry, f"{atom}summary"),
                "published_at": _parse_published(
                    _text(entry, f"{atom}published") or _text(entry, f"{atom}updated")
                ),
                **_feed_entry_metadata(entry),
            })
        return items
    for entry in rss_items[:MAX_FEED_ITEMS]:
        items.append({
            "id": _text(entry, "guid") or _text(entry, "link"),
            "title": _text(entry, "title"),
            "link": _text(entry, "link"),
            "summary": _text(entry, "description"),
            "published_at": _parse_published(_text(entry, "pubDate")),
            **_feed_entry_metadata(entry),
        })
    return items


def _parse_public_feed(payload: bytes) -> list[dict[str, object]]:
    """解析公开热榜 JSON（复用 Easel hotlist-apis.md 约定的字段语义）。"""
    if len(payload) > MAX_FEED_BYTES:
        raise JobExecutionError(
            "SOURCE_FEED_TOO_LARGE", "Feed exceeded the configured size limit.",
            retryable=False,
        )
    try:
        document = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise JobExecutionError(
            "SOURCE_FEED_INVALID", "Public feed JSON could not be parsed.", retryable=False
        ) from exc
    rows: object = document
    if isinstance(document, dict):
        rows = document.get("data", document.get("items", document.get("list", [])))
        if isinstance(rows, dict):
            rows = rows.get("list", rows.get("items", rows.get("data", [])))
        code = document.get("code")
        if (
            code is not None
            and str(code) not in {"0", "200"}
            and not rows
        ):
            message = str(document.get("msg") or document.get("message") or "")[:200]
            auth_related = str(code) in {"401", "403", "980401"}
            raise JobExecutionError(
                "SOURCE_AUTH_REQUIRED" if auth_related else "SOURCE_API_ERROR",
                f"Feed API returned code {code}: {message}".strip(),
                retryable=False,
            )
    if not isinstance(rows, list):
        raise JobExecutionError(
            "SOURCE_FEED_INVALID", "Public feed JSON has no item list.", retryable=False
        )
    items: list[dict[str, object]] = []
    for row in rows[:MAX_FEED_ITEMS]:
        if isinstance(row, str):
            # 部分热榜（如 B 站）只返回标题字符串数组。
            title = row.strip()
            if not title:
                continue
            items.append(
                {
                    "id": title,
                    "title": title,
                    "link": "",
                    "summary": "",
                    "published_at": None,
                    "region": None,
                    "heat_value": None,
                    "heat_unit": None,
                    "topic_tags": [],
                }
            )
            continue
        if not isinstance(row, dict):
            continue
        # 知乎热榜把内容放在 target 下；头条使用首字母大写的 Title/Url/ClusterId。
        target = row.get("target") if isinstance(row.get("target"), dict) else row
        title = str(
            target.get("title")
            or target.get("name")
            or target.get("word")
            or row.get("Title")
            or ""
        ).strip()
        link = str(
            target.get("url") or target.get("link") or row.get("Url") or row.get("url") or ""
        ).strip()
        if not title:
            continue
        heat = (
            row.get("HotValue")
            or row.get("hot")
            or row.get("hot_value")
            or row.get("heat")
        )
        summary = (
            target.get("excerpt")
            or target.get("detail_text")
            or row.get("desc")
            or row.get("summary")
            or ""
        )
        items.append(
            {
                "id": str(
                    row.get("ClusterId")
                    or target.get("id")
                    or row.get("id")
                    or link
                    or title
                ),
                "title": title,
                "link": link,
                "summary": str(summary)[:5000],
                "published_at": None,
                "region": row.get("region") or row.get("area"),
                "heat_value": str(heat) if heat is not None else None,
                "heat_unit": row.get("hot_unit") or row.get("unit"),
                "topic_tags": [],
            }
        )
    if rows and not items:
        # 结构能解析但字段无法识别时按失败处理，避免把异常响应吞成空结果。
        raise JobExecutionError(
            "SOURCE_FEED_INVALID",
            "Public feed JSON did not contain recognizable entries.",
            retryable=False,
        )
    return items


def _http_error(status_code: int) -> tuple[str, str, bool]:
    if status_code == 429:
        return (
            "SOURCE_RATE_LIMITED",
            "Feed endpoint rejected the request with HTTP 429 (rate limited).",
            True,
        )
    if 400 <= status_code < 500:
        return (
            "SOURCE_HTTP_4XX",
            f"Feed endpoint returned HTTP {status_code}.",
            False,
        )
    return (
        "SOURCE_HTTP_5XX",
        f"Feed endpoint returned HTTP {status_code}.",
        True,
    )


def _request_headers(url: str, is_public_feed: bool) -> dict[str, str]:
    """部分站点会按 UA/Referer 拦截匿名请求，按实际域名补齐最小必要请求头。"""
    host = (urlsplit(url).hostname or "").lower()
    accept = (
        "application/json, text/plain, */*"
        if is_public_feed
        else "application/rss+xml, application/atom+xml, application/xml, text/xml"
    )
    headers = {"User-Agent": USER_AGENT, "Accept": accept}
    if host == "toutiao.com" or host.endswith(".toutiao.com"):
        headers.update(
            {
                "User-Agent": BROWSER_USER_AGENT,
                "Referer": "https://www.toutiao.com/",
            }
        )
    elif host == "zhihu.com" or host.endswith(".zhihu.com"):
        headers.update(
            {
                "User-Agent": BROWSER_USER_AGENT,
                "Referer": "https://www.zhihu.com/hot",
            }
        )
    return headers


def _fetch_entries(url: str, allowed: set[str], is_public_feed: bool) -> list[dict[str, object]]:
    """请求单个端点并解析条目；失败时必须抛出带错误码的 JobExecutionError。"""
    feed_url, feed_ip = _safe_https_url(url, allowed)
    headers = _request_headers(url, is_public_feed)
    try:
        transport = httpx.HTTPTransport()
        cast(Any, transport)._pool._network_backend = _PinnedSyncBackend(
            (urlsplit(feed_url).hostname or "").lower(), feed_ip
        )
        with httpx.Client(
            transport=transport,
            timeout=HTTP_TIMEOUT,
            follow_redirects=False,
            headers=headers,
        ) as client, client.stream("GET", feed_url) as response:
            if response.status_code >= 400:
                code, summary, retryable = _http_error(response.status_code)
                raise JobExecutionError(code, summary, retryable=retryable)
            chunks: list[bytes] = []
            total_bytes = 0
            for chunk in response.iter_bytes():
                total_bytes += len(chunk)
                if total_bytes > MAX_FEED_BYTES:
                    raise JobExecutionError(
                        "SOURCE_FEED_TOO_LARGE",
                        "Feed exceeded the configured size limit.",
                        retryable=False,
                    )
                chunks.append(chunk)
            raw_payload = b"".join(chunks)
    except JobExecutionError:
        raise
    except httpx.TimeoutException as exc:
        raise JobExecutionError(
            "SOURCE_TIMEOUT", "Feed request timed out.", retryable=True
        ) from exc
    except (httpx.HTTPError, OSError) as exc:
        raise JobExecutionError(
            "SOURCE_FETCH_FAILED",
            f"Feed request failed ({type(exc).__name__}).",
            retryable=True,
        ) from exc
    entries = _parse_public_feed(raw_payload) if is_public_feed else _parse_feed(raw_payload)
    if not entries:
        # 200 但无条目不能吞成“采集成功但 0 条”，否则后台看不到真实错因。
        raise JobExecutionError(
            "SOURCE_EMPTY_RESPONSE",
            "Feed returned no recognizable entries.",
            retryable=True,
        )
    return entries


def _collect_source(db: Session, source: HotTopicSource, allowed: set[str]) -> dict[str, object]:
    # 来源准入：条款与用途未登记时直接拒绝，不发起任何请求。
    if not (source.terms_url or "").strip() or not (source.permitted_use or "").strip():
        raise JobExecutionError(
            "SOURCE_TERMS_MISSING",
            "Source usage terms are not registered.",
            retryable=False,
        )
    _safe_https_url(source.terms_url, allowed)
    is_public_feed = getattr(source, "source_type", "rss") == "public_feed"
    candidate_urls = [source.source_url]
    fallback = (getattr(source, "fallback_url", None) or "").strip()
    if fallback:
        candidate_urls.append(fallback)

    entries: list[dict[str, object]] | None = None
    attempts: list[dict[str, object]] = []
    last_error: JobExecutionError | None = None
    used_url = source.source_url
    for candidate in candidate_urls:
        # 429/超时/5xx 属于可重试错误，单端点最多再试一次；4xx 直接切换备用端点。
        for retry_index in range(2):
            try:
                entries = _fetch_entries(candidate, allowed, is_public_feed)
                used_url = candidate
                break
            except JobExecutionError as exc:
                attempts.append(
                    {"url": candidate, "error_code": exc.code, "summary": exc.safe_summary}
                )
                last_error = exc
                if not exc.retryable or retry_index == 1:
                    break
                time.sleep(RETRY_DELAY_SECONDS)
        if entries is not None:
            break
    if entries is None:
        assert last_error is not None
        raise last_error

    now = datetime.now(UTC)
    inserted = 0
    for entry in entries:
        title = str(entry.get("title") or "").strip()
        link = str(entry.get("link") or "").strip()
        item_id = str(entry.get("id") or link or title).strip()
        if not title or not item_id:
            continue
        if not link:
            # 部分公开热榜（如抖音）只给词条不给链接；用来源端点作为可回溯地址。
            if not is_public_feed:
                continue
            link = source.source_url
        parsed_link = urlsplit(link)
        link_host = (parsed_link.hostname or "").lower()
        if (
            parsed_link.scheme != "https"
            or not link_host
            or parsed_link.username
            or parsed_link.password
        ):
            continue
        # 热榜条目链接只做展示，不发起请求；来源域名白名单约束的是采集目标。
        if not is_public_feed and link_host not in allowed:
            continue
        summary = str(entry.get("summary") or "")[:5000]
        fingerprint = hashlib.sha256(f"{link}|{title}".encode()).hexdigest()
        heat_number = parse_num(entry.get("heat_value"))
        heat_value = Decimal(heat_number) if heat_number is not None else None
        existing = db.scalar(select(HotTopic).where(
            HotTopic.source_id == source.id,
            (HotTopic.source_item_id == item_id) | (HotTopic.content_fingerprint == fingerprint),
        ).with_for_update())
        if existing:
            existing.last_seen_at = now
            # 仍在采集到的热点刷新保留期，避免被保留策略按旧 expires_at 判过期。
            existing.expires_at = now + timedelta(days=3)
            if existing.evidence_status == "expired":
                existing.evidence_status = "collected"
            # 内容未变时哈希保持一致，增量匹配才能跳过；变了则下一轮重算。
            existing.content_hash = topic_content_hash(
                existing.title, existing.summary, existing.topic_tags_json
            )
            if heat_value is not None:
                existing.heat_value = heat_value
                existing.last_heat_value = heat_value
                if existing.first_heat_value is None:
                    existing.first_heat_value = heat_value
                existing.heat_sample_count = (existing.heat_sample_count or 0) + 1
                db.add(HotTopicHeatSample(id=uuid4(), hot_topic_id=existing.id,
                    observed_at=now, heat_value=heat_value))
            continue
        published = entry.get("published_at")
        published_at = published if isinstance(published, datetime) else None
        topic_id = uuid4()
        db.add(HotTopic(id=topic_id, source_id=source.id, source_item_id=item_id,
            canonical_url=link, title=title[:500], summary=summary, raw_excerpt=None,
            published_at=published_at, discovered_at=now, last_seen_at=now,
            expires_at=(published_at or now) + timedelta(days=3),
            region=str(entry.get("region") or "")[:120] or None,
            heat_value=heat_value,
            heat_unit=str(entry.get("heat_unit") or "")[:80] or None,
            first_heat_value=heat_value, last_heat_value=heat_value,
            heat_sample_count=1 if heat_value is not None else 0,
            evidence_status="collected", content_fingerprint=fingerprint,
            content_hash=topic_content_hash(title, summary, []),
            normalization_version=1, industry_tags_json=[], topic_tags_json=[]))
        if heat_value is not None:
            db.add(HotTopicHeatSample(id=uuid4(), hot_topic_id=topic_id,
                observed_at=now, heat_value=heat_value))
        inserted += 1
    source.health_status = "healthy"
    source.last_success_at = now
    source.last_failure_at = None
    source.last_error_code = None
    source.last_error_summary = None
    db.flush()
    return {
        "used_url": used_url,
        "fallback_used": used_url != source.source_url,
        "attempts": attempts,
        "entries": len(entries),
        "inserted": inserted,
    }


def register_hot_topic_handlers(session_factory: sessionmaker[Session]) -> None:
    @register_job_handler("hot_topics.collect_and_match.v1")
    def collect_and_match(context: JobExecutionContext, payload_ref: dict[str, object]) -> dict[str, object]:
        context.check_control()
        if context.store_id is None:
            raise JobExecutionError("STORE_CONTEXT_REQUIRED", "Hot-topic jobs require a store context.", retryable=False)
        schema_version = payload_ref.get("schema_version")
        raw_ids = payload_ref.get("source_ids")
        if schema_version != 1 or not isinstance(raw_ids, list) or not raw_ids:
            raise JobExecutionError("INVALID_JOB_PAYLOAD", "Hot-topic job payload is invalid.", retryable=False)
        try:
            source_ids = [UUID(str(value)) for value in raw_ids]
        except (ValueError, TypeError) as exc:
            raise JobExecutionError("INVALID_SOURCE_IDS", "Source identifiers are invalid.", retryable=False) from exc
        allowed = _allowed_hosts()
        if not allowed:
            raise JobExecutionError("SOURCE_ALLOWLIST_EMPTY", "No approved public feed hosts are configured.", retryable=False)
        inserted_total = 0
        source_results: list[dict[str, object]] = []
        source_failures: list[dict[str, object]] = []
        for index, source_id in enumerate(source_ids, start=1):
            context.check_control()
            with session_factory.begin() as db:
                source = db.scalar(select(HotTopicSource).where(
                    HotTopicSource.id == source_id).with_for_update())
                if source is None:
                    source_failures.append({
                        "source_id": str(source_id),
                        "error_code": "SOURCE_NOT_FOUND",
                        "summary": "Source no longer exists.",
                        "retryable": False,
                    })
                elif not source.enabled:
                    source_failures.append({
                        "source_id": str(source_id),
                        "source_key": source.source_key,
                        "error_code": "SOURCE_DISABLED",
                        "summary": "Source is disabled.",
                        "retryable": False,
                    })
                else:
                    try:
                        collected = _collect_source(db, source, allowed)
                    except JobExecutionError as exc:
                        # 单源失败写回来源健康与错误码，不拖垮整个 Job。
                        source.health_status = "failed"
                        source.last_failure_at = datetime.now(UTC)
                        source.last_error_code = exc.code
                        source.last_error_summary = exc.safe_summary[:500]
                        source_failures.append({
                            "source_id": str(source_id),
                            "source_key": source.source_key,
                            "error_code": exc.code,
                            "summary": exc.safe_summary,
                            "retryable": exc.retryable,
                        })
                    else:
                        inserted_total += int(cast(int, collected["inserted"]))
                        source_results.append({
                            "source_id": str(source_id),
                            "source_key": source.source_key,
                            **collected,
                        })
            context.update_progress(current=index, total=len(source_ids))
        if source_ids and not source_results:
            first = source_failures[0]
            raise JobExecutionError(
                "ALL_SOURCES_FAILED",
                (
                    f"All {len(source_ids)} hot-topic sources failed; "
                    f"first error {first['error_code']}: {first['summary']}"
                )[:500],
                retryable=any(bool(item.get("retryable")) for item in source_failures),
            )
        # 全部来源采集完成后再统一匹配，才能按事件跨源去重并做每店限额。
        with session_factory.begin() as db:
            outcome = match_store(
                db,
                context.store_id,
                job_id=context.job_id,
                attempt_id=context.attempt_id,
            )
        return {
            "sources_processed": len(source_ids),
            "sources_succeeded": len(source_results),
            "sources_failed": len(source_failures),
            "source_results": source_results,
            "source_failures": source_failures,
            "topics_inserted": inserted_total,
            "opportunities_created": outcome.created,
            "match": outcome.as_dict(),
            "store_id": str(context.store_id),
        }
