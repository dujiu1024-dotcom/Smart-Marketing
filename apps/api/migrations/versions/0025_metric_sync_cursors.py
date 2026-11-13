"""Add metric sync cursors and merchant-authorized scrape observations.

Revision ID: 0025_metric_sync_cursors
Revises: 0024_attribution_snap_versions
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0025_metric_sync_cursors"
down_revision: str | None = "0024_attribution_snap_versions"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "metric_observations",
        sa.Column("channel_account_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "metric_observations",
        sa.Column(
            "observation_scope",
            sa.String(16),
            server_default="store",
            nullable=False,
        ),
    )
    op.execute(
        sa.text(
            """
            UPDATE metric_observations
            SET observation_scope = CASE
                WHEN published_work_id IS NOT NULL THEN 'work'
                WHEN channel_account_id IS NOT NULL THEN 'account'
                ELSE 'store'
            END
            """
        )
    )
    op.create_foreign_key(
        "fk_metric_observations_channel_account_same_store",
        "metric_observations",
        "channel_accounts",
        ["store_id", "channel_account_id"],
        ["store_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "observation_scope",
        "metric_observations",
        "observation_scope IN ('work', 'account', 'store')",
    )
    op.create_index(
        "ix_metric_observations_store_account_scope",
        "metric_observations",
        ["store_id", "channel_account_id", "observation_scope"],
    )
    # 0018 的约束名已经带表名前缀，命名约定又补了一层前缀，实际名称被截断。
    # 按列语义查找并删除，避免依赖具体截断后的约束名。
    op.execute(
        sa.text(
            """
            DO $$
            DECLARE constraint_name text;
            BEGIN
                FOR constraint_name IN
                    SELECT conname
                    FROM pg_constraint
                    WHERE conrelid = 'metric_observations'::regclass
                      AND contype = 'c'
                      AND pg_get_constraintdef(oid) LIKE '%authenticity_status%'
                LOOP
                    EXECUTE format(
                        'ALTER TABLE metric_observations DROP CONSTRAINT %I',
                        constraint_name
                    );
                END LOOP;
            END $$;
            """
        )
    )
    # merchant_authorized_scrape 为 26 字符，原 varchar(24) 需扩容。
    op.alter_column(
        "metric_observations",
        "authenticity_status",
        existing_type=sa.String(24),
        type_=sa.String(32),
        existing_nullable=False,
    )
    op.create_check_constraint(
        "authenticity_status",
        "metric_observations",
        "authenticity_status IN ('official_api','verified_import','merchant_reported',"
        "'merchant_authorized_scrape','demo_sample')",
    )

    op.create_table(
        "metric_sync_cursors",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "store_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("stores.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("channel_account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scope", sa.String(16), nullable=False),
        sa.Column("source_system", sa.String(80), nullable=False),
        sa.Column("status", sa.String(24), server_default="idle", nullable=False),
        sa.Column("cursor_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "cursor_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("consecutive_failures", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("last_failure_at", sa.DateTime(timezone=True)),
        sa.Column("last_error_code", sa.String(100)),
        sa.Column("last_error_summary", sa.String(500)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "store_id",
            "channel_account_id",
            "scope",
            name="uq_metric_sync_cursors_store_account_scope",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "channel_account_id"],
            ["channel_accounts.store_id", "channel_accounts.id"],
            name="fk_metric_sync_cursors_channel_account_same_store",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("scope IN ('work','account','store')", name="scope"),
        sa.CheckConstraint(
            "status IN ('idle','running','succeeded','failed','login_required',"
            "'unsupported','unavailable')",
            name="status",
        ),
        sa.CheckConstraint("cursor_version >= 1", name="version_positive"),
        sa.CheckConstraint(
            "consecutive_failures >= 0",
            name="consecutive_failures_nonnegative",
        ),
    )
    op.create_index(
        "ix_metric_sync_cursors_store_account",
        "metric_sync_cursors",
        ["store_id", "channel_account_id"],
    )

    seeds = [
        ("followers", "content_performance", "粉丝/关注者", "count"),
        ("likes", "content_performance", "获赞", "count"),
        ("following", "content_performance", "关注", "count"),
        ("posts", "content_performance", "作品数", "count"),
        ("views", "content_performance", "播放/观看", "count"),
        ("reads", "content_performance", "阅读", "count"),
        ("impressions", "content_performance", "曝光", "count"),
        ("comments", "content_performance", "评论", "count"),
        ("favorites", "content_performance", "收藏", "count"),
        ("shares", "content_performance", "分享", "count"),
        ("home_visits", "content_performance", "主页访问", "count"),
        ("net_follower_gain", "content_performance", "净涨粉", "count"),
    ]
    for metric_key, tier, display_name, value_type in seeds:
        op.execute(
            sa.text(
                """
                INSERT INTO metric_definitions
                (id, source_system, metric_key, metric_tier, display_name, value_type, unit,
                 definition, aggregation_rule, period_semantics, definition_version, status)
                VALUES (gen_random_uuid(), 'merchant_authorized_scrape', :metric_key, :tier,
                        :display_name, :value_type, NULL, :definition, 'sum', 'period_delta', 1,
                        'active')
                ON CONFLICT (source_system, metric_key, definition_version) DO NOTHING
                """
            ).bindparams(
                metric_key=metric_key,
                tier=tier,
                display_name=display_name,
                value_type=value_type,
                definition=(
                    "商家本人授权后，通过其已登录创作者中心读取的可见指标；"
                    "非平台官方接口口径，不得标记为 official_api。"
                ),
            )
        )


def downgrade() -> None:
    # 先清理抓取口径观测，避免旧约束/外键回退失败。
    op.execute(
        sa.text(
            "DELETE FROM metric_observations "
            "WHERE authenticity_status = 'merchant_authorized_scrape'"
        )
    )
    op.execute(
        sa.text(
            "DELETE FROM metric_definitions WHERE source_system = 'merchant_authorized_scrape'"
        )
    )
    op.drop_index("ix_metric_sync_cursors_store_account", table_name="metric_sync_cursors")
    op.drop_table("metric_sync_cursors")
    op.drop_constraint(
        "authenticity_status",
        "metric_observations",
        type_="check",
    )
    op.alter_column(
        "metric_observations",
        "authenticity_status",
        existing_type=sa.String(32),
        type_=sa.String(24),
        existing_nullable=False,
    )
    # 恢复 0018 迁移的历史命名（该约束在 0018 中带表名前缀，套用命名约定后会被加长截断）。
    op.create_check_constraint(
        "ck_metric_observations_authenticity_status",
        "metric_observations",
        "authenticity_status IN ('official_api','verified_import','merchant_reported','demo_sample')",
    )
    op.drop_index(
        "ix_metric_observations_store_account_scope",
        table_name="metric_observations",
    )
    op.drop_constraint(
        "observation_scope",
        "metric_observations",
        type_="check",
    )
    op.drop_constraint(
        "fk_metric_observations_channel_account_same_store",
        "metric_observations",
        type_="foreignkey",
    )
    op.drop_column("metric_observations", "observation_scope")
    op.drop_column("metric_observations", "channel_account_id")
