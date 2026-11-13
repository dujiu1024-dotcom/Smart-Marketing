from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select
from store_operator_worker.hot_topic_matching import (
    MATCHING_ALGORITHM_VERSION,
    event_key,
    match_store,
)

from store_operator.models.identity import Store
from store_operator.models.opportunity_effects import (
    HotTopic,
    HotTopicMatchState,
    HotTopicSource,
    StoreOpportunity,
)
from store_operator.models.store_knowledge import AudienceProfile, Product, StoreProfile


def _store_with_coffee_profile(db):
    store = Store(id=uuid4(), name="咖啡测试门店", timezone="Asia/Shanghai", status="active")
    db.add(store)
    db.flush()
    db.add(
        StoreProfile(
            id=uuid4(),
            store_id=store.id,
            display_name="咖啡测试门店",
            business_type="精品咖啡馆",
            industry_category="餐饮",
            introduction="社区精品咖啡，主打手冲与生椰拿铁",
            region="上海市",
            province="上海市",
            city="上海市",
            district="静安区",
            fact_status="confirmed",
            current_version=1,
        )
    )
    db.add(
        Product(
            id=uuid4(),
            store_id=store.id,
            name="生椰拿铁",
            category="咖啡饮品",
            availability_status="available",
            fact_status="confirmed",
            current_version=1,
        )
    )
    db.add(
        AudienceProfile(
            id=uuid4(),
            store_id=store.id,
            name="周边上班族",
            segment_type="core",
            audience_description="工作日通勤经过门店的咖啡消费者",
            consumption_scenarios_json=["通勤", "早餐"],
            fact_status="confirmed",
            current_version=1,
        )
    )
    db.flush()
    return store


def _source(db, key: str) -> HotTopicSource:
    source = HotTopicSource(
        id=uuid4(),
        source_key=key,
        display_name=key,
        source_type="public_feed",
        source_url="https://feeds.example.test/hot",
        enabled=True,
        health_status="healthy",
    )
    db.add(source)
    db.flush()
    return source


def _topic(db, source: HotTopicSource, title: str, summary: str | None = None) -> HotTopic:
    topic = HotTopic(
        id=uuid4(),
        source_id=source.id,
        source_item_id=f"{source.source_key}-{uuid4()}",
        canonical_url="https://feeds.example.test/topic",
        title=title,
        summary=summary,
        discovered_at=datetime.now(UTC),
        last_seen_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(days=3),
        evidence_status="collected",
        content_fingerprint=uuid4().hex * 2,
        content_hash="",
    )
    db.add(topic)
    db.flush()
    return topic


def test_match_store_requires_category_and_explains_dimensions(db_session):
    store = _store_with_coffee_profile(db_session)
    source = _source(db_session, "feed-a")
    eligible = _topic(
        db_session, source, "上海咖啡店早餐新品：生椰拿铁回归", "上班族通勤路上的早餐搭配"
    )
    mismatch = _topic(db_session, source, "北京咖啡节开幕，手冲咖啡人气高")
    noise = _topic(db_session, source, "正部级王忠林被查")
    duplicate = _topic(db_session, source, "上海咖啡店早餐新品:生椰拿铁回归！")

    outcome = match_store(db_session, store.id)
    db_session.flush()

    rows = db_session.scalars(
        select(StoreOpportunity).where(StoreOpportunity.store_id == store.id)
    ).all()
    by_topic = {row.hot_topic_id: row for row in rows}
    assert eligible.id in by_topic
    assert by_topic[eligible.id].eligibility_status == "eligible"
    assert float(by_topic[eligible.id].relevance_score) >= 45
    assert "命中品类" in by_topic[eligible.id].reason_summary
    assert "生椰拿铁" in by_topic[eligible.id].reason_summary
    assert "地域" in by_topic[eligible.id].reason_summary

    assert by_topic[mismatch.id].eligibility_status == "review_required"
    assert "地域明确不匹配" in by_topic[mismatch.id].reason_summary

    # 同标题跨源只生成一条机会；纯新闻无内容词命中不生成机会。
    assert duplicate.id not in by_topic
    assert noise.id not in by_topic
    assert outcome.created == 2
    assert outcome.duplicate_events == 1

    duplicate_event_key = event_key("上海咖啡店早餐新品：生椰拿铁回归")
    assert (
        db_session.scalar(
            select(HotTopicMatchState).where(
                HotTopicMatchState.store_id == store.id,
                HotTopicMatchState.hot_topic_id == duplicate.id,
            )
        )
        is not None
    )
    assert duplicate_event_key  # 归一化键非空，供跨源聚类使用


def test_match_store_caps_per_round_and_is_incremental(db_session):
    store = _store_with_coffee_profile(db_session)
    source = _source(db_session, "feed-b")
    titles = [f"上海咖啡新品第{index}款生椰拿铁上市" for index in range(7)]
    topics = [_topic(db_session, source, title) for title in titles]

    first = match_store(db_session, store.id, max_opportunities=5)
    db_session.flush()
    assert first.created == 5
    assert first.deferred_by_cap == 2
    assert first.store_context_changed is True

    # 第二轮：已生成的 5 条不再生成，只补上轮被截断的 2 条中的可匹配项。
    second = match_store(db_session, store.id, max_opportunities=5)
    db_session.flush()
    assert second.created == 2
    assert second.store_context_changed is False

    # 第三轮：没有新热点、也没有门店资料变化，不再重复匹配。
    third = match_store(db_session, store.id, max_opportunities=5)
    db_session.flush()
    assert third.created == 0
    assert third.evaluated == 0

    created_before = len(
        db_session.scalars(
            select(StoreOpportunity).where(StoreOpportunity.store_id == store.id)
        ).all()
    )
    assert created_before == 7

    # 门店资料版本变化后，该店全量回填重算，旧机会标记 stale。
    product = db_session.scalar(select(Product).where(Product.store_id == store.id))
    assert product is not None
    product.current_version += 1
    db_session.flush()
    recomputed = match_store(db_session, store.id, max_opportunities=5)
    db_session.flush()
    assert recomputed.store_context_changed is True
    assert recomputed.created == 5
    stale_rows = db_session.scalars(
        select(StoreOpportunity).where(
            StoreOpportunity.store_id == store.id,
            StoreOpportunity.stale_at.is_not(None),
        )
    ).all()
    assert len(stale_rows) == 7
    state = db_session.scalar(
        select(HotTopicMatchState).where(HotTopicMatchState.store_id == store.id)
    )
    assert state is not None
    assert state.match_version == MATCHING_ALGORITHM_VERSION
    assert len(topics) == 7
