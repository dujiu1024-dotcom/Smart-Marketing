"""Add hotspot opportunities and metric observations.

Revision ID: 0018_opportunity_effects
Revises: 0017_channel_specs
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0018_opportunity_effects"
down_revision: str | None = "0017_channel_specs"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "hot_topic_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source_key", sa.String(100), nullable=False),
        sa.Column("display_name", sa.String(160), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("source_url", sa.String(2048), nullable=False),
        sa.Column("terms_url", sa.String(2048)),
        sa.Column("permitted_use", sa.Text()),
        sa.Column("attribution_template", sa.String(500)),
        sa.Column("enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("health_status", sa.String(24), server_default="unknown", nullable=False),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("last_failure_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False),
        sa.UniqueConstraint("source_key", name="uq_hot_topic_sources_source_key"),
        sa.CheckConstraint("source_type IN ('official_api','rss','public_feed','manual')",
            name="ck_hot_topic_sources_source_type"),
        sa.CheckConstraint("health_status IN ('unknown','healthy','degraded','failed','disabled')", name="ck_hot_topic_sources_health_status"),  # noqa: E501
    )
    op.create_table(
        "hot_topics",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hot_topic_sources.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("source_item_id", sa.String(500)),
        sa.Column("canonical_url", sa.String(2048), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("summary", sa.Text()),
        sa.Column("raw_excerpt", sa.Text()),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("region", sa.String(120)),
        sa.Column("industry_tags_json", postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("topic_tags_json", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"),
            nullable=False),
        sa.Column("heat_value", sa.Numeric(20, 6)),
        sa.Column("heat_unit", sa.String(80)),
        sa.Column("evidence_status", sa.String(24), server_default="unverified", nullable=False),
        sa.Column("content_fingerprint", sa.String(64), nullable=False),
        sa.Column("normalization_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False),
        sa.UniqueConstraint("source_id", "source_item_id", name="uq_hot_topics_source_item"),
        sa.UniqueConstraint("source_id", "content_fingerprint",
            name="uq_hot_topics_source_fingerprint"),
        sa.CheckConstraint("evidence_status IN ('collected','partial','failed','unverified','expired')", name="ck_hot_topics_evidence_status"),  # noqa: E501
    )
    op.create_index("ix_hot_topics_expiry", "hot_topics", ["expires_at"])
    op.create_index("ix_hot_topics_published", "hot_topics", ["published_at"])
    op.create_table(
        "store_opportunities",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("stores.id",
            ondelete="RESTRICT"), nullable=False),
        sa.Column("hot_topic_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("hot_topics.id",
            ondelete="RESTRICT"), nullable=False),
        sa.Column("store_context_fingerprint", sa.String(64), nullable=False),
        sa.Column("matching_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("relevance_score", sa.Numeric(6, 3)),
        sa.Column("match_method", sa.String(16), server_default="rules", nullable=False),
        sa.Column("matched_product_ids_json", postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("matched_offer_ids_json", postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("matched_audience_profile_ids_json", postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("suggested_scenario", sa.String(500)),
        sa.Column("content_angle", sa.Text()),
        sa.Column("reason_summary", sa.Text()),
        sa.Column("risk_flags_json", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"),
            nullable=False),
        sa.Column("eligibility_status", sa.String(24), server_default="unassessed", nullable=False),
        sa.Column("matched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("stale_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False),
        sa.UniqueConstraint("store_id", "id", name="uq_store_opportunities_store_id"),
        sa.UniqueConstraint("store_id", "hot_topic_id", "matching_version",
            name="uq_store_opportunities_match_version"),
        sa.CheckConstraint("eligibility_status IN ('eligible','review_required','ineligible','unassessed')", name="ck_store_opportunities_eligibility_status"),  # noqa: E501
        sa.CheckConstraint("match_method IN ('rules','semantic','hybrid','manual')",
            name="ck_store_opportunities_match_method"),
    )
    op.create_index("ix_store_opportunities_store_expiry", "store_opportunities", ["store_id",
        "expires_at"])
    op.create_table(
        "opportunity_decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("stores.id",
            ondelete="RESTRICT"), nullable=False),
        sa.Column("opportunity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id",
            ondelete="RESTRICT"), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("reason", sa.String(1000)),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False),
        sa.ForeignKeyConstraint(["store_id", "opportunity_id"],
            ["store_opportunities.store_id", "store_opportunities.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("store_id", "actor_user_id", "idempotency_key",
            name="uq_opportunity_decisions_idempotency"),
        sa.CheckConstraint("decision IN ('adopt','ignore','snooze')",
            name="ck_opportunity_decisions_decision"),
    )
    op.create_index("ix_opportunity_decisions_store_created", "opportunity_decisions",
        ["store_id", "created_at"])
    op.create_table(
        "metric_definitions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source_system", sa.String(80), nullable=False),
        sa.Column("channel_key", sa.String(80)),
        sa.Column("metric_key", sa.String(120), nullable=False),
        sa.Column("metric_tier", sa.String(32), nullable=False),
        sa.Column("display_name", sa.String(160), nullable=False),
        sa.Column("value_type", sa.String(24), nullable=False),
        sa.Column("unit", sa.String(40)),
        sa.Column("definition", sa.Text(), nullable=False),
        sa.Column("aggregation_rule", sa.String(40), server_default="sum", nullable=False),
        sa.Column("period_semantics", sa.String(40), server_default="period_delta", nullable=False),
        sa.Column("definition_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("status", sa.String(16), server_default="active", nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False),
        sa.Column("effective_to", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False),
        sa.UniqueConstraint("source_system", "metric_key", "definition_version",
            name="uq_metric_definitions_source_key_version"),
        sa.CheckConstraint("metric_tier IN ('content_performance','intent','business_outcome')", name="ck_metric_definitions_metric_tier"),  # noqa: E501
        sa.CheckConstraint("value_type IN ('count','decimal','duration','rate','currency')",
            name="ck_metric_definitions_value_type"),
        sa.CheckConstraint("status IN ('active','deprecated')",
            name="ck_metric_definitions_status"),
    )
    op.create_table(
        "metric_observations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("store_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("stores.id",
            ondelete="RESTRICT"), nullable=False),
        sa.Column("metric_definition_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("metric_definitions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("metric_key", sa.String(120), nullable=False),
        sa.Column("metric_tier", sa.String(32), nullable=False),
        sa.Column("value_numeric", sa.Numeric(20, 6)),
        sa.Column("unit", sa.String(40)),
        sa.Column("currency", sa.String(3)),
        sa.Column("source_system", sa.String(80), nullable=False),
        sa.Column("source_record_id", sa.String(300)),
        sa.Column("source_evidence_ref", sa.String(2048)),
        sa.Column("period_start", sa.DateTime(timezone=True)),
        sa.Column("period_end", sa.DateTime(timezone=True)),
        sa.Column("period_timezone", sa.String(80), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_updated_at", sa.DateTime(timezone=True)),
        sa.Column("definition_version", sa.Integer(), nullable=False),
        sa.Column("integrity_status", sa.String(16), server_default="unknown", nullable=False),
        sa.Column("authenticity_status", sa.String(24), nullable=False),
        sa.Column("sync_status", sa.String(16), server_default="current", nullable=False),
        sa.Column("deduplication_key", sa.String(64), nullable=False),
        sa.Column("supersedes_observation_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("metric_observations.id", ondelete="RESTRICT")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False),
        sa.UniqueConstraint("store_id", "deduplication_key",
            name="uq_metric_observations_store_dedupe"),
        sa.CheckConstraint("integrity_status IN ('complete','partial','anomalous','unknown')",
            name="ck_metric_observations_integrity_status"),
        sa.CheckConstraint("authenticity_status IN ('official_api','verified_import','merchant_reported','demo_sample')", name="ck_metric_observations_authenticity_status"),  # noqa: E501
        sa.CheckConstraint("sync_status IN ('current','delayed','failed','unavailable')",
            name="ck_metric_observations_sync_status"),
        sa.CheckConstraint("value_numeric IS NULL OR value_numeric >= 0",
            name="ck_metric_observations_value_nonnegative"),
        sa.CheckConstraint("period_end IS NULL OR period_start IS NULL OR period_end > period_start", name="ck_metric_observations_period_valid"),  # noqa: E501
    )
    op.create_index("ix_metric_observations_store_collected", "metric_observations",
        ["store_id", "collected_at"])
    op.create_index("ix_metric_observations_store_metric_period", "metric_observations",
        ["store_id", "metric_key", "period_end"])

    seeds = [
        ("manual", "views", "content_performance", "播放/浏览", "count",
         "作品在统计周期内的播放或浏览次数"),
        ("manual", "impressions", "content_performance", "曝光", "count",
         "作品在统计周期内的曝光次数"),
        ("manual", "reads", "content_performance", "阅读", "count", "作品在统计周期内的阅读次数"),
        ("manual", "likes", "content_performance", "点赞", "count", "作品在统计周期内的点赞次数"),
        ("manual", "comments", "content_performance", "评论", "count", "作品在统计周期内的评论次数"),
        ("manual", "shares", "content_performance", "分享", "count", "作品在统计周期内的分享次数"),
        ("manual", "consultations", "intent", "咨询", "count", "可核验的咨询意向数量"),
        ("manual", "clicks", "intent", "点击", "count", "可核验的内容点击数量"),
        ("manual", "booking_intents", "intent", "预约意向", "count", "可核验的预约意向数量"),
        ("manual", "store_visits", "business_outcome", "到店", "count", "有来源凭证的到店数量"),
        ("manual", "orders", "business_outcome", "订单", "count", "有来源凭证的订单数量"),
        ("manual", "redemptions", "business_outcome", "核销", "count", "有来源凭证的优惠核销数量"),
        ("manual", "revenue", "business_outcome", "销售额", "currency", "有来源凭证的销售金额"),
    ]
    for source, key, tier, name, value_type, definition in seeds:
        op.execute(sa.text("""
            INSERT INTO metric_definitions
            (id, source_system, metric_key, metric_tier, display_name, value_type, unit, definition,
             aggregation_rule, period_semantics, definition_version, status)
            VALUES (gen_random_uuid(), :source, :key, :tier, :name, :value_type, NULL, :definition,
                    'sum', 'period_delta', 1, 'active')
            ON CONFLICT (source_system, metric_key, definition_version) DO NOTHING
        """).bindparams(source=source, key=key, tier=tier, name=name, value_type=value_type, definition=definition))  # noqa: E501


def downgrade() -> None:
    op.drop_index("ix_metric_observations_store_metric_period", table_name="metric_observations")
    op.drop_index("ix_metric_observations_store_collected", table_name="metric_observations")
    op.drop_table("metric_observations")
    op.drop_table("metric_definitions")
    op.drop_index("ix_opportunity_decisions_store_created", table_name="opportunity_decisions")
    op.drop_table("opportunity_decisions")
    op.drop_index("ix_store_opportunities_store_expiry", table_name="store_opportunities")
    op.drop_table("store_opportunities")
    op.drop_index("ix_hot_topics_published", table_name="hot_topics")
    op.drop_index("ix_hot_topics_expiry", table_name="hot_topics")
    op.drop_table("hot_topics")
    op.drop_table("hot_topic_sources")
