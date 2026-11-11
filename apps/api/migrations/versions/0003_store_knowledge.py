"""Store Knowledge tenant-scoped records, fact revisions and media metadata.

Revision ID: 0003_store_knowledge
Revises: 0002_identity_store_security
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_store_knowledge"
down_revision: str | None = "0002_identity_store_security"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

FACT_STATUS = (
    "fact_status IN (" + "'unverified', 'pending_confirmation', 'confirmed', "
    "'needs_review', 'expired'" + ")"
)


def upgrade() -> None:
    op.create_table(
        "store_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "store_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("stores.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("display_name", sa.String(160), nullable=False),
        sa.Column("business_type", sa.String(80)),
        sa.Column("industry_category", sa.String(120)),
        sa.Column("brand_name", sa.String(160)),
        sa.Column("introduction", sa.Text()),
        sa.Column("country_code", sa.String(2)),
        sa.Column("region", sa.String(120)),
        sa.Column("province", sa.String(120)),
        sa.Column("city", sa.String(120)),
        sa.Column("district", sa.String(120)),
        sa.Column("address", sa.String(500)),
        sa.Column("phone", sa.String(40)),
        sa.Column("opening_hours_json", postgresql.JSONB()),
        sa.Column("temporary_closures_json", postgresql.JSONB()),
        sa.Column("service_radius", sa.String(120)),
        sa.Column("service_capabilities_json", postgresql.JSONB()),
        sa.Column("fact_status", sa.String(32), server_default="unverified", nullable=False),
        sa.Column("current_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "updated_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
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
        sa.UniqueConstraint("store_id", name="uq_store_profiles_store"),
        sa.UniqueConstraint("store_id", "id", name="uq_store_profiles_store_id"),
        sa.CheckConstraint(FACT_STATUS, name="ck_store_profiles_fact_status"),
    )

    op.create_table(
        "products",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "store_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("stores.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("category", sa.String(120)),
        sa.Column("sku", sa.String(120)),
        sa.Column("specification", sa.String(300)),
        sa.Column("unit", sa.String(40)),
        sa.Column("price_amount", sa.Numeric(12, 2)),
        sa.Column("currency", sa.String(3)),
        sa.Column("availability_status", sa.String(20), server_default="unknown", nullable=False),
        sa.Column("inventory_quantity", sa.Numeric(14, 3)),
        sa.Column("key_selling_points_json", postgresql.JSONB()),
        sa.Column("description", sa.Text()),
        sa.Column("ingredients_or_materials", sa.Text()),
        sa.Column("allergens_and_restrictions_json", postgresql.JSONB()),
        sa.Column("service_process", sa.Text()),
        sa.Column("delivery_method", sa.String(120)),
        sa.Column("fact_status", sa.String(32), server_default="unverified", nullable=False),
        sa.Column("current_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "updated_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
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
        sa.UniqueConstraint("store_id", "id", name="uq_products_store_id"),
        sa.CheckConstraint(
            "(price_amount IS NULL AND currency IS NULL) OR " 
            "(price_amount IS NOT NULL AND currency IS NOT NULL)",
            name="ck_products_price_currency_pair",
        ),
        sa.CheckConstraint(
            "price_amount IS NULL OR price_amount >= 0",
            name="ck_products_price_nonnegative",
        ),
        sa.CheckConstraint(
            "availability_status IN ('available', 'unavailable', 'seasonal', 'limited', 'unknown')",
            name="ck_products_availability_status",
        ),
        sa.CheckConstraint(FACT_STATUS, name="ck_products_fact_status"),
    )
    op.create_index(
        "uq_products_store_sku",
        "products",
        ["store_id", "sku"],
        unique=True,
        postgresql_where=sa.text("sku IS NOT NULL"),
    )
    op.create_index(
        "ix_products_store_status",
        "products",
        ["store_id", "availability_status", "fact_status"],
    )

    op.create_table(
        "offers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "store_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("stores.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("offer_type", sa.String(40), nullable=False),
        sa.Column("terms_json", postgresql.JSONB(), nullable=False),
        sa.Column(
            "eligibility_rules_json",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("starts_at", sa.DateTime(timezone=True)),
        sa.Column("ends_at", sa.DateTime(timezone=True)),
        sa.Column("stacking_policy", sa.String(40)),
        sa.Column("usage_limit", sa.Integer()),
        sa.Column("status", sa.String(16), server_default="draft", nullable=False),
        sa.Column("fact_status", sa.String(32), server_default="unverified", nullable=False),
        sa.Column("current_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "updated_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
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
        sa.UniqueConstraint("store_id", "id", name="uq_offers_store_id"),
        sa.CheckConstraint(
            "ends_at IS NULL OR starts_at IS NULL OR ends_at > starts_at",
            name="ck_offers_valid_window",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'paused', 'expired', 'archived')",
            name="ck_offers_status",
        ),
        sa.CheckConstraint(FACT_STATUS, name="ck_offers_fact_status"),
    )
    op.create_index(
        "ix_offers_store_status_window",
        "offers",
        ["store_id", "status", "starts_at", "ends_at"],
    )

    op.create_table(
        "audience_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "store_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("stores.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("segment_type", sa.String(20), nullable=False),
        sa.Column("audience_description", sa.Text()),
        sa.Column("consumption_scenarios_json", postgresql.JSONB()),
        sa.Column("consumption_periods_json", postgresql.JSONB()),
        sa.Column("purchase_motivations_json", postgresql.JSONB()),
        sa.Column("common_objections_json", postgresql.JSONB()),
        sa.Column("source_type", sa.String(40)),
        sa.Column("source_ref", sa.String(500)),
        sa.Column("sample_size", sa.Integer()),
        sa.Column("sampled_at", sa.DateTime(timezone=True)),
        sa.Column("confidence_level", sa.String(24)),
        sa.Column("fact_status", sa.String(32), server_default="unverified", nullable=False),
        sa.Column("current_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "updated_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
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
        sa.UniqueConstraint("store_id", "id", name="uq_audience_profiles_store_id"),
        sa.CheckConstraint(
            "segment_type IN ('core', 'secondary', 'seasonal', 'scenario')",
            name="ck_audience_profiles_segment_type",
        ),
        sa.CheckConstraint(FACT_STATUS, name="ck_audience_profiles_fact_status"),
    )
    op.create_index(
        "ix_audience_profiles_store_segment",
        "audience_profiles",
        ["store_id", "segment_type"],
    )

    op.create_table(
        "knowledge_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "store_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("stores.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("category", sa.String(40), nullable=False),
        sa.Column("content_text", sa.Text()),
        sa.Column("content_ref", sa.String(700)),
        sa.Column("content_hash", sa.String(64)),
        sa.Column("source_type", sa.String(40)),
        sa.Column("source_ref", sa.String(500)),
        sa.Column("effective_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("fact_status", sa.String(32), server_default="unverified", nullable=False),
        sa.Column("current_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "updated_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
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
        sa.UniqueConstraint("store_id", "id", name="uq_knowledge_items_store_id"),
        sa.CheckConstraint(FACT_STATUS, name="ck_knowledge_items_fact_status"),
    )
    op.create_index(
        "ix_knowledge_items_store_fact_expiry",
        "knowledge_items",
        ["store_id", "fact_status", "expires_at"],
    )

    op.create_table(
        "media_assets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "store_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("stores.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("object_key", sa.String(700), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("mime_type", sa.String(120), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("width", sa.Integer()),
        sa.Column("height", sa.Integer()),
        sa.Column("original_filename_sanitized", sa.String(255)),
        sa.Column("asset_type", sa.String(40), nullable=False),
        sa.Column("source_type", sa.String(40)),
        sa.Column("source_ref", sa.String(500)),
        sa.Column("usage_rights_status", sa.String(24), server_default="unknown", nullable=False),
        sa.Column("license_note", sa.Text()),
        sa.Column("parent_asset_id", postgresql.UUID(as_uuid=True)),
        sa.Column("version_no", sa.Integer(), server_default="1", nullable=False),
        sa.Column("derivation_instruction", sa.Text()),
        sa.Column("status", sa.String(16), server_default="uploading", nullable=False),
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
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
        sa.UniqueConstraint("store_id", "id", name="uq_media_assets_store_id"),
        sa.UniqueConstraint("object_key", name="uq_media_assets_object_key"),
        sa.UniqueConstraint(
            "store_id",
            "parent_asset_id",
            "version_no",
            name="uq_media_assets_parent_version",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "parent_asset_id"],
            ["media_assets.store_id", "media_assets.id"],
            name="fk_media_assets_parent_same_store",
        ),
        sa.CheckConstraint("byte_size > 0", name="ck_media_assets_byte_size_positive"),
        sa.CheckConstraint(
            "status IN ('uploading', 'quarantined', 'scanning', 'ready', 'rejected', 'archived')",
            name="ck_media_assets_status",
        ),
        sa.CheckConstraint(
            "usage_rights_status IN ('unknown', 'confirmed_allowed', 'restricted')",
            name="ck_media_assets_usage_rights_status",
        ),
    )
    op.create_index(
        "ix_media_assets_store_status_type_created",
        "media_assets",
        ["store_id", "status", "asset_type", "created_at"],
    )

    op.create_table(
        "brand_guidelines",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "store_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("stores.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("brand_story", sa.Text()),
        sa.Column("positioning", sa.Text()),
        sa.Column("differentiators", sa.Text()),
        sa.Column("core_values_json", postgresql.JSONB()),
        sa.Column("tone_of_voice", sa.Text()),
        sa.Column("common_phrases_json", postgresql.JSONB()),
        sa.Column("prohibited_phrases_json", postgresql.JSONB()),
        sa.Column("cta_preferences_json", postgresql.JSONB()),
        sa.Column("logo_asset_id", postgresql.UUID(as_uuid=True)),
        sa.Column("color_palette_json", postgresql.JSONB()),
        sa.Column("font_preferences_json", postgresql.JSONB()),
        sa.Column("visual_style", sa.Text()),
        sa.Column("fact_status", sa.String(32), server_default="unverified", nullable=False),
        sa.Column("current_version", sa.Integer(), server_default="1", nullable=False),
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
        sa.UniqueConstraint("store_id", name="uq_brand_guidelines_store"),
        sa.UniqueConstraint("store_id", "id", name="uq_brand_guidelines_store_id"),
        sa.ForeignKeyConstraint(
            ["store_id", "logo_asset_id"],
            ["media_assets.store_id", "media_assets.id"],
            name="fk_brand_guidelines_logo_asset_same_store",
        ),
        sa.CheckConstraint(FACT_STATUS, name="ck_brand_guidelines_fact_status"),
    )

    op.create_table(
        "upload_intents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "store_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("stores.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("object_key", sa.String(700), nullable=False),
        sa.Column("expected_mime_type", sa.String(120), nullable=False),
        sa.Column("expected_byte_size", sa.Integer(), nullable=False),
        sa.Column("expected_sha256", sa.String(64)),
        sa.Column("status", sa.String(16), server_default="created", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("rejection_reason", sa.String(240)),
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
        sa.UniqueConstraint("store_id", "id", name="uq_upload_intents_store_id"),
        sa.UniqueConstraint("object_key", name="uq_upload_intents_object_key"),
        sa.CheckConstraint(
            "expected_byte_size > 0",
            name="ck_upload_intents_expected_byte_size_positive",
        ),
        sa.CheckConstraint(
            "status IN ('created', 'uploaded', 'scanning', 'completed', 'rejected', 'expired')",
            name="ck_upload_intents_status",
        ),
    )
    op.create_index("ix_upload_intents_status_expiry", "upload_intents", ["status", "expires_at"])

    op.create_table(
        "store_record_revisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "store_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("stores.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("record_type", sa.String(60), nullable=False),
        sa.Column("record_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("snapshot_json", postgresql.JSONB(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("content_fingerprint", sa.String(64), nullable=False),
        sa.Column("fact_status", sa.String(32), nullable=False),
        sa.Column("source_type", sa.String(40)),
        sa.Column("source_ref", sa.String(500)),
        sa.Column("valid_from", sa.DateTime(timezone=True)),
        sa.Column("valid_until", sa.DateTime(timezone=True)),
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "confirmed_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("change_reason", sa.Text()),
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
            "record_type",
            "record_id",
            "version_no",
            name="uq_store_record_revisions_version",
        ),
        sa.CheckConstraint(FACT_STATUS, name="ck_store_record_revisions_fact_status"),
    )
    op.create_index(
        "ix_store_record_revisions_lookup",
        "store_record_revisions",
        ["store_id", "record_type", "record_id", "created_at"],
    )

    op.create_table(
        "offer_products",
        sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("offer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint("store_id", "offer_id", "product_id", name="pk_offer_products"),
        sa.ForeignKeyConstraint(
            ["store_id", "offer_id"],
            ["offers.store_id", "offers.id"],
            ondelete="CASCADE",
            name="fk_offer_products_offer_same_store",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "product_id"],
            ["products.store_id", "products.id"],
            ondelete="CASCADE",
            name="fk_offer_products_product_same_store",
        ),
    )
    op.create_table(
        "product_media_assets",
        sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(24), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.PrimaryKeyConstraint(
            "store_id",
            "product_id",
            "asset_id",
            name="pk_product_media_assets",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "product_id"],
            ["products.store_id", "products.id"],
            ondelete="CASCADE",
            name="fk_product_media_assets_product_same_store",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "asset_id"],
            ["media_assets.store_id", "media_assets.id"],
            ondelete="RESTRICT",
            name="fk_product_media_assets_asset_same_store",
        ),
    )
    op.create_table(
        "knowledge_item_products",
        sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("knowledge_item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "store_id",
            "knowledge_item_id",
            "product_id",
            name="pk_knowledge_item_products",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "knowledge_item_id"],
            ["knowledge_items.store_id", "knowledge_items.id"],
            ondelete="CASCADE",
            name="fk_knowledge_item_products_item_same_store",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "product_id"],
            ["products.store_id", "products.id"],
            ondelete="CASCADE",
            name="fk_knowledge_item_products_product_same_store",
        ),
    )
    op.create_table(
        "audience_profile_products",
        sa.Column("store_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("audience_profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "store_id",
            "audience_profile_id",
            "product_id",
            name="pk_audience_profile_products",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "audience_profile_id"],
            ["audience_profiles.store_id", "audience_profiles.id"],
            ondelete="CASCADE",
            name="fk_audience_profile_products_profile_same_store",
        ),
        sa.ForeignKeyConstraint(
            ["store_id", "product_id"],
            ["products.store_id", "products.id"],
            ondelete="CASCADE",
            name="fk_audience_profile_products_product_same_store",
        ),
    )


def downgrade() -> None:
    op.drop_table("audience_profile_products")
    op.drop_table("knowledge_item_products")
    op.drop_table("product_media_assets")
    op.drop_table("offer_products")
    op.drop_index("ix_store_record_revisions_lookup", table_name="store_record_revisions")
    op.drop_table("store_record_revisions")
    op.drop_index("ix_upload_intents_status_expiry", table_name="upload_intents")
    op.drop_table("upload_intents")
    op.drop_table("brand_guidelines")
    op.drop_index("ix_media_assets_store_status_type_created", table_name="media_assets")
    op.drop_table("media_assets")
    op.drop_index("ix_knowledge_items_store_fact_expiry", table_name="knowledge_items")
    op.drop_table("knowledge_items")
    op.drop_index("ix_audience_profiles_store_segment", table_name="audience_profiles")
    op.drop_table("audience_profiles")
    op.drop_index("ix_offers_store_status_window", table_name="offers")
    op.drop_table("offers")
    op.drop_index("ix_products_store_status", table_name="products")
    op.drop_index("uq_products_store_sku", table_name="products")
    op.drop_table("products")
    op.drop_table("store_profiles")
