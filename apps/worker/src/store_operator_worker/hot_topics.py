# ruff: noqa: I001
from __future__ import annotations

from collections.abc import Sequence
from typing import Any, cast
import hashlib
import html
import ipaddress
import re
import socket
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpcore
import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from store_operator.models import (  # type: ignore[import-untyped]
    AudienceProfile,
    BrandGuideline,
    HotTopic,
    HotTopicSource,
    Offer,
    Product,
    StoreOpportunity,
    StoreProfile,
)
from store_operator_worker.handlers import (
    JobExecutionContext,
    JobExecutionError,
    register_job_handler,
)

MAX_FEED_BYTES = 2_000_000
MATCHING_ALGORITHM_VERSION = 2
MAX_FEED_ITEMS = 200
HTTP_TIMEOUT = httpx.Timeout(15.0, connect=5.0)
USER_AGENT = "AI-Store-Operator-HotTopicCollector/1.0"


def _allowed_hosts() -> set[str]:
    from store_operator.config import settings  # type: ignore[import-untyped]

    return {
        host.strip().lower()
        for host in settings.hot_topic_allowed_hosts.split(",")
        if host.strip()
    }


class _PinnedSyncBackend(httpcore.SyncBackend):
    """Connect to the exact public IP validated before the request; preserve URL host for TLS SNI."""

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
        raise JobExecutionError("SOURCE_HOST_NOT_ALLOWED", "Feed host is not in the configured allowlist.", retryable=False)
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
    except OSError as exc:
        raise JobExecutionError("SOURCE_DNS_FAILED", "Feed host could not be resolved.", retryable=True) from exc
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise JobExecutionError("SOURCE_HOST_NOT_PUBLIC", "Feed host resolves to a non-public network address.", retryable=False)
    return sorted(addresses)[0]


def _safe_https_url(value: str, allowed: set[str]) -> tuple[str, str]:
    parsed = urlsplit(value)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host or parsed.username or parsed.password:
        raise JobExecutionError("SOURCE_URL_INVALID", "Source URL must be a credential-free HTTPS URL.", retryable=False)
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


def _tokens(value: str) -> set[str]:
    normalized = value.lower()
    words = set(re.findall(r"[a-z0-9]{2,}", normalized))
    chinese = re.findall(r"[\u4e00-\u9fff]", normalized)
    words.update(chinese[index] + chinese[index + 1] for index in range(len(chinese) - 1))
    return words


def _match_score(topic_text: str, fact_text: str) -> float:
    topic_tokens = _tokens(topic_text)
    fact_tokens = _tokens(fact_text)
    if not topic_tokens or not fact_tokens:
        return 0.0
    return len(topic_tokens & fact_tokens) / len(topic_tokens | fact_tokens)


def _store_profile_text(profile: StoreProfile) -> str:
    values = [
        profile.display_name,
        profile.business_type or "",
        profile.industry_category or "",
        profile.introduction or "",
        profile.service_radius or "",
        profile.region or "",
        profile.province or "",
        profile.city or "",
        profile.district or "",
        *(profile.service_capabilities_json or []),
    ]
    return " ".join(value for value in values if value)


def _brand_guideline_text(brand: BrandGuideline | None) -> str:
    if brand is None:
        return ""
    values = [
        brand.brand_story or "",
        brand.positioning or "",
        brand.differentiators or "",
        brand.tone_of_voice or "",
        brand.visual_style or "",
        *(brand.core_values_json or []),
        *(brand.common_phrases_json or []),
        *(brand.cta_preferences_json or []),
    ]
    return " ".join(value for value in values if value)


def _region_matches(topic_region: str | None, profile: StoreProfile) -> bool | None:
    if not topic_region:
        return None
    profile_regions = [
        profile.region,
        profile.province,
        profile.city,
        profile.district,
    ]
    profile_tokens = set().union(
        *(_tokens(value) for value in profile_regions if value and value.strip())
    )
    if not profile_tokens:
        return None
    return bool(_tokens(topic_region) & profile_tokens)


def _brand_risk_flags(topic_text: str, brand: BrandGuideline | None) -> list[str]:
    if brand is None:
        return []
    normalized = topic_text.lower()
    prohibited = [
        phrase.strip()
        for phrase in (brand.prohibited_phrases_json or [])
        if isinstance(phrase, str) and phrase.strip()
    ]
    return ["brand_prohibited_phrase"] if any(
        phrase.lower() in normalized for phrase in prohibited
    ) else []


def _collect_source(db: Session, source: HotTopicSource, allowed: set[str]) -> int:
    feed_url, feed_ip = _safe_https_url(source.source_url, allowed)
    terms_url, _ = _safe_https_url(source.terms_url or "", allowed)
    if not source.permitted_use or not terms_url:
        raise JobExecutionError("SOURCE_TERMS_MISSING", "Source usage terms are not registered.", retryable=False)
    try:
        transport = httpx.HTTPTransport()
        cast(Any, transport)._pool._network_backend = _PinnedSyncBackend(
            (urlsplit(feed_url).hostname or "").lower(), feed_ip
        )
        with httpx.Client(transport=transport, timeout=HTTP_TIMEOUT, follow_redirects=False,
                          headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml"}) as client:
            response = client.get(feed_url)
            response.raise_for_status()
            if len(response.content) > MAX_FEED_BYTES:
                raise JobExecutionError("SOURCE_FEED_TOO_LARGE", "Feed exceeded the configured size limit.", retryable=False)
            entries = _parse_feed(response.content)
    except JobExecutionError:
        raise
    except (httpx.HTTPError, OSError) as exc:
        raise JobExecutionError("SOURCE_FETCH_FAILED", "Feed request failed; retry according to the source policy.", retryable=True) from exc

    now = datetime.now(UTC)
    inserted = 0
    for entry in entries:
        title = str(entry.get("title") or "").strip()
        link = str(entry.get("link") or "").strip()
        item_id = str(entry.get("id") or link).strip()
        if not title or not link or not item_id:
            continue
        parsed_link = urlsplit(link)
        link_host = (parsed_link.hostname or "").lower()
        if parsed_link.scheme != "https" or not link_host or parsed_link.username or parsed_link.password or link_host not in allowed:
            continue
        summary = str(entry.get("summary") or "")[:5000]
        fingerprint = hashlib.sha256(f"{link}|{title}".encode()).hexdigest()
        existing = db.scalar(select(HotTopic).where(
            HotTopic.source_id == source.id,
            (HotTopic.source_item_id == item_id) | (HotTopic.content_fingerprint == fingerprint),
        ).with_for_update())
        if existing:
            existing.last_seen_at = now
            if existing.expires_at and existing.expires_at <= now:
                existing.evidence_status = "expired"
            continue
        published = entry.get("published_at")
        published_at = published if isinstance(published, datetime) else None
        db.add(HotTopic(id=uuid4(), source_id=source.id, source_item_id=item_id,
            canonical_url=link, title=title[:500], summary=summary, raw_excerpt=None,
            published_at=published_at, discovered_at=now, last_seen_at=now,
            expires_at=(published_at or now) + timedelta(days=3),
            evidence_status="collected", content_fingerprint=fingerprint,
            normalization_version=1, industry_tags_json=[], topic_tags_json=[]))
        inserted += 1
    source.health_status = "healthy"
    source.last_success_at = now
    source.last_failure_at = None
    db.flush()
    return inserted


def _match_store(db: Session, store_id: UUID, topics: Sequence[HotTopic], context: JobExecutionContext) -> int:
    profile = db.scalar(select(StoreProfile).where(StoreProfile.store_id == store_id,
        StoreProfile.fact_status == "confirmed"))
    products = db.scalars(select(Product).where(Product.store_id == store_id,
        Product.fact_status == "confirmed", Product.availability_status.in_(["available", "limited", "seasonal"]))).all()
    offers = db.scalars(select(Offer).where(Offer.store_id == store_id,
        Offer.fact_status == "confirmed", Offer.status == "active")).all()
    audiences = db.scalars(select(AudienceProfile).where(AudienceProfile.store_id == store_id,
        AudienceProfile.fact_status == "confirmed")).all()
    brand = db.scalar(select(BrandGuideline).where(
        BrandGuideline.store_id == store_id,
        BrandGuideline.fact_status == "confirmed",
    ))
    if profile is None or (not products and not offers and not audiences):
        return 0
    context_parts = [str(profile.current_version), f"matcher:{MATCHING_ALGORITHM_VERSION}"]
    if brand is not None:
        context_parts.append(f"brand:{brand.id}:{brand.current_version}")
    context_parts.extend(f"p:{item.id}:{item.current_version}" for item in products)
    context_parts.extend(f"o:{item.id}:{item.current_version}" for item in offers)
    context_parts.extend(f"a:{item.id}:{item.current_version}" for item in audiences)
    context_fingerprint = hashlib.sha256("|".join(sorted(context_parts)).encode("utf-8")).hexdigest()
    created = 0
    for topic in topics:
        context.check_control()
        if topic.evidence_status != "collected" or (topic.expires_at and topic.expires_at <= datetime.now(UTC)):
            continue
        topic_text = " ".join(
            [topic.title, topic.summary or "", *topic.topic_tags_json, *topic.industry_tags_json]
        )
        profile_text = _store_profile_text(profile)
        region_text = " ".join(
            value
            for value in (
                profile.region,
                profile.province,
                profile.city,
                profile.district,
            )
            if value
        )
        brand_text = _brand_guideline_text(brand)
        profile_score = _match_score(topic_text, profile_text)
        region_score = _match_score(topic.region or "", region_text)
        brand_score = _match_score(topic_text, brand_text)
        risk_flags = _brand_risk_flags(topic_text, brand)
        region_match = _region_matches(topic.region, profile)
        if region_match is False:
            risk_flags.append("region_mismatch")
        product_scores = []
        for product in products:
            product_text = " ".join([product.name, product.category or "", product.description or "",
                *(product.key_selling_points_json or [])])
            score = _match_score(topic_text, product_text)
            if score >= 0.08:
                product_scores.append((score, product))
        offer_scores = []
        for offer in offers:
            offer_text = " ".join([offer.title, offer.offer_type, str(offer.terms_json), str(offer.eligibility_rules_json)])
            score = _match_score(topic_text, offer_text)
            if score >= 0.08:
                offer_scores.append((score, offer))
        audience_scores = []
        for audience in audiences:
            audience_text = " ".join([audience.name, audience.audience_description or "",
                *(audience.consumption_scenarios_json or []), *(audience.consumption_periods_json or []),
                *(audience.purchase_motivations_json or []), *(audience.common_objections_json or [])])
            score = _match_score(topic_text, audience_text)
            if score >= 0.08:
                audience_scores.append((score, audience))
        if not product_scores and not offer_scores and not audience_scores:
            continue
        score = max(
            [value for value, _ in product_scores]
            + [value for value, _ in offer_scores]
            + [value for value, _ in audience_scores]
            + [profile_score * 0.8, region_score * 0.6, brand_score * 0.5]
        )
        latest = db.scalar(select(StoreOpportunity).where(
            StoreOpportunity.store_id == store_id, StoreOpportunity.hot_topic_id == topic.id)
            .order_by(StoreOpportunity.matching_version.desc()).limit(1).with_for_update())
        if latest and latest.store_context_fingerprint == context_fingerprint:
            continue
        if latest:
            latest.stale_at = datetime.now(UTC)
        version = (latest.matching_version + 1) if latest else 1
        status = (
            "eligible"
            if score >= 0.12 and product_scores and not risk_flags
            else "review_required"
        )
        product_ids = [str(item.id) for _, item in sorted(product_scores, key=lambda pair: pair[0], reverse=True)[:5]]
        offer_ids = [str(item.id) for _, item in sorted(offer_scores, key=lambda pair: pair[0], reverse=True)[:5]]
        audience_ids = [str(item.id) for _, item in sorted(audience_scores, key=lambda pair: pair[0], reverse=True)[:5]]
        best_product = max(product_scores, key=lambda pair: pair[0])[1] if product_scores else None
        best_offer = max(offer_scores, key=lambda pair: pair[0])[1] if offer_scores else None
        db.add(StoreOpportunity(id=uuid4(), store_id=store_id, hot_topic_id=topic.id,
            store_context_fingerprint=context_fingerprint, matching_version=version,
            matching_algorithm_version=MATCHING_ALGORITHM_VERSION,
            relevance_score=round(score * 100, 3), match_method="rules",
            matched_product_ids_json=product_ids, matched_offer_ids_json=offer_ids,
            matched_audience_profile_ids_json=audience_ids, suggested_scenario=(best_offer.title if best_offer else None),
            content_angle=(f"围绕{best_product.name}回应当前话题" if best_product else None),
            reason_summary=(
                f"门店资料文本相关度 {profile_score:.2f}，区域文本相关度 {region_score:.2f}，"
                f"品牌规范文本相关度 {brand_score:.2f}；"
                f"区域匹配："
                f"{'匹配' if region_match is True else '不匹配' if region_match is False else '未提供区域证据'}；"
                "该分值仅代表文本相关性，不代表趋势热度或经营效果。"
            ),
            risk_flags_json=risk_flags, eligibility_status=status, matched_at=datetime.now(UTC),
            expires_at=topic.expires_at))
        created += 1
    db.flush()
    return created


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
        matched_total = 0
        for index, source_id in enumerate(source_ids, start=1):
            context.check_control()
            try:
                with session_factory.begin() as db:
                    source = db.scalar(select(HotTopicSource).where(
                        HotTopicSource.id == source_id, HotTopicSource.enabled.is_(True)).with_for_update())
                    if source is None:
                        continue
                    inserted_total += _collect_source(db, source, allowed)
                    topics = db.scalars(select(HotTopic).where(
                        HotTopic.source_id == source.id, HotTopic.evidence_status == "collected",
                        (HotTopic.expires_at.is_(None)) | (HotTopic.expires_at > datetime.now(UTC)))
                        .order_by(HotTopic.published_at.desc().nullslast()).limit(MAX_FEED_ITEMS)).all()
                    matched_total += _match_store(db, context.store_id, topics, context)
            except JobExecutionError:
                with session_factory.begin() as db:
                    failed_source = db.scalar(select(HotTopicSource).where(HotTopicSource.id == source_id).with_for_update())
                    if failed_source is not None:
                        failed_source.health_status = "failed"
                        failed_source.last_failure_at = datetime.now(UTC)
                raise
            context.update_progress(current=index, total=len(source_ids))
        return {"sources_processed": len(source_ids), "topics_inserted": inserted_total,
            "opportunities_created": matched_total, "store_id": str(context.store_id)}
