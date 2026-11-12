from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from store_operator.models.base import Base


class StoreScoped:
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    store_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class StoreProfile(StoreScoped, Base):
    __tablename__ = "store_profiles"
    __table_args__ = (
        UniqueConstraint("store_id", name="uq_store_profiles_store"),
        UniqueConstraint("store_id", "id", name="uq_store_profiles_store_id"),
        CheckConstraint(
            "fact_status IN ('unverified', 'pending_confirmation', 'confirmed', "
            "'needs_review', 'expired')",
            name="fact_status",
        ),
    )

    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    business_type: Mapped[str | None] = mapped_column(String(80))
    industry_category: Mapped[str | None] = mapped_column(String(120))
    brand_name: Mapped[str | None] = mapped_column(String(160))
    introduction: Mapped[str | None] = mapped_column(Text)
    country_code: Mapped[str | None] = mapped_column(String(2))
    region: Mapped[str | None] = mapped_column(String(120))
    province: Mapped[str | None] = mapped_column(String(120))
    city: Mapped[str | None] = mapped_column(String(120))
    district: Mapped[str | None] = mapped_column(String(120))
    address: Mapped[str | None] = mapped_column(String(500))
    phone: Mapped[str | None] = mapped_column(String(40))
    opening_hours_json: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    temporary_closures_json: Mapped[list[dict[str, object]] | None] = mapped_column(JSONB)
    service_radius: Mapped[str | None] = mapped_column(String(120))
    service_capabilities_json: Mapped[list[str] | None] = mapped_column(JSONB)
    fact_status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="unverified"
    )
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_by_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )


class Product(StoreScoped, Base):
    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("store_id", "id", name="uq_products_store_id"),
        CheckConstraint(
            "(price_amount IS NULL AND currency IS NULL) OR "
            "(price_amount IS NOT NULL AND currency IS NOT NULL)",
            name="price_currency_pair",
        ),
        CheckConstraint("price_amount IS NULL OR price_amount >= 0", name="price_nonnegative"),
        CheckConstraint(
            "availability_status IN ('available', 'unavailable', 'seasonal', 'limited', 'unknown')",
            name="availability_status",
        ),
        CheckConstraint(
            "fact_status IN ('unverified', 'pending_confirmation', 'confirmed', "
            "'needs_review', 'expired')",
            name="fact_status",
        ),
        Index(
            "uq_products_store_sku",
            "store_id",
            "sku",
            unique=True,
            postgresql_where=text("sku IS NOT NULL"),
        ),
        Index("ix_products_store_status", "store_id", "availability_status", "fact_status"),
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str | None] = mapped_column(String(120))
    sku: Mapped[str | None] = mapped_column(String(120))
    specification: Mapped[str | None] = mapped_column(String(300))
    unit: Mapped[str | None] = mapped_column(String(40))
    price_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str | None] = mapped_column(String(3))
    availability_status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="unknown"
    )
    inventory_quantity: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    key_selling_points_json: Mapped[list[str] | None] = mapped_column(JSONB)
    description: Mapped[str | None] = mapped_column(Text)
    ingredients_or_materials: Mapped[str | None] = mapped_column(Text)
    allergens_and_restrictions_json: Mapped[list[str] | None] = mapped_column(JSONB)
    service_process: Mapped[str | None] = mapped_column(Text)
    delivery_method: Mapped[str | None] = mapped_column(String(120))
    fact_status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="unverified"
    )
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_by_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )


class Offer(StoreScoped, Base):
    __tablename__ = "offers"
    __table_args__ = (
        UniqueConstraint("store_id", "id", name="uq_offers_store_id"),
        CheckConstraint(
            "ends_at IS NULL OR starts_at IS NULL OR ends_at > starts_at",
            name="valid_window",
        ),
        CheckConstraint(
            "status IN ('draft', 'active', 'paused', 'expired', 'archived')", name="status"
        ),
        CheckConstraint(
            "fact_status IN ('unverified', 'pending_confirmation', 'confirmed', "
            "'needs_review', 'expired')",
            name="fact_status",
        ),
        Index("ix_offers_store_status_window", "store_id", "status", "starts_at", "ends_at"),
    )

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    offer_type: Mapped[str] = mapped_column(String(40), nullable=False)
    terms_json: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    eligibility_rules_json: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stacking_policy: Mapped[str | None] = mapped_column(String(40))
    usage_limit: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="draft")
    fact_status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="unverified"
    )
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_by_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )


class BrandGuideline(StoreScoped, Base):
    __tablename__ = "brand_guidelines"
    __table_args__ = (
        UniqueConstraint("store_id", name="uq_brand_guidelines_store"),
        UniqueConstraint("store_id", "id", name="uq_brand_guidelines_store_id"),
        ForeignKeyConstraint(
            ["store_id", "logo_asset_id"],
            ["media_assets.store_id", "media_assets.id"],
            name="fk_brand_guidelines_logo_asset_same_store",
        ),
    )

    brand_story: Mapped[str | None] = mapped_column(Text)
    positioning: Mapped[str | None] = mapped_column(Text)
    differentiators: Mapped[str | None] = mapped_column(Text)
    core_values_json: Mapped[list[str] | None] = mapped_column(JSONB)
    tone_of_voice: Mapped[str | None] = mapped_column(Text)
    common_phrases_json: Mapped[list[str] | None] = mapped_column(JSONB)
    prohibited_phrases_json: Mapped[list[str] | None] = mapped_column(JSONB)
    cta_preferences_json: Mapped[list[str] | None] = mapped_column(JSONB)
    logo_asset_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    color_palette_json: Mapped[list[dict[str, object]] | None] = mapped_column(JSONB)
    font_preferences_json: Mapped[list[str] | None] = mapped_column(JSONB)
    visual_style: Mapped[str | None] = mapped_column(Text)
    fact_status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="unverified"
    )
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")


class AudienceProfile(StoreScoped, Base):
    __tablename__ = "audience_profiles"
    __table_args__ = (
        UniqueConstraint("store_id", "id", name="uq_audience_profiles_store_id"),
        CheckConstraint(
            "segment_type IN ('core', 'secondary', 'seasonal', 'scenario')", name="segment_type"
        ),
        CheckConstraint(
            "fact_status IN ('unverified', 'pending_confirmation', 'confirmed', "
            "'needs_review', 'expired')",
            name="fact_status",
        ),
        Index("ix_audience_profiles_store_segment", "store_id", "segment_type"),
    )

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    segment_type: Mapped[str] = mapped_column(String(20), nullable=False)
    audience_description: Mapped[str | None] = mapped_column(Text)
    consumption_scenarios_json: Mapped[list[str] | None] = mapped_column(JSONB)
    consumption_periods_json: Mapped[list[str] | None] = mapped_column(JSONB)
    purchase_motivations_json: Mapped[list[str] | None] = mapped_column(JSONB)
    common_objections_json: Mapped[list[str] | None] = mapped_column(JSONB)
    source_type: Mapped[str | None] = mapped_column(String(40))
    source_ref: Mapped[str | None] = mapped_column(String(500))
    sample_size: Mapped[int | None] = mapped_column(Integer)
    sampled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confidence_level: Mapped[str | None] = mapped_column(String(24))
    fact_status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="unverified"
    )
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_by_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )


class KnowledgeItem(StoreScoped, Base):
    __tablename__ = "knowledge_items"
    __table_args__ = (
        UniqueConstraint("store_id", "id", name="uq_knowledge_items_store_id"),
        CheckConstraint(
            "fact_status IN ('unverified', 'pending_confirmation', 'confirmed', "
            "'needs_review', 'expired')",
            name="fact_status",
        ),
        Index("ix_knowledge_items_store_fact_expiry", "store_id", "fact_status", "expires_at"),
    )

    title: Mapped[str] = mapped_column(String(240), nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    content_text: Mapped[str | None] = mapped_column(Text)
    content_ref: Mapped[str | None] = mapped_column(String(700))
    content_hash: Mapped[str | None] = mapped_column(String(64))
    source_type: Mapped[str | None] = mapped_column(String(40))
    source_ref: Mapped[str | None] = mapped_column(String(500))
    effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fact_status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="unverified"
    )
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_by_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )


class MediaAsset(StoreScoped, Base):
    __tablename__ = "media_assets"
    __table_args__ = (
        UniqueConstraint("store_id", "id", name="uq_media_assets_store_id"),
        UniqueConstraint("object_key", name="uq_media_assets_object_key"),
        UniqueConstraint(
            "store_id", "parent_asset_id", "version_no",
            name="uq_media_assets_parent_version",
        ),
        ForeignKeyConstraint(
            ["store_id", "parent_asset_id"],
            ["media_assets.store_id", "media_assets.id"],
            name="fk_media_assets_parent_same_store",
        ),
        CheckConstraint("byte_size > 0", name="byte_size_positive"),
        CheckConstraint(
            "status IN ('uploading', 'quarantined', 'scanning', 'ready', 'rejected', 'scan_failed', 'archived')",
            name="status",
        ),
        CheckConstraint(
            "usage_rights_status IN ('unknown', 'confirmed_allowed', 'restricted')",
            name="usage_rights_status",
        ),
        Index(
            "ix_media_assets_store_status_type_created",
            "store_id", "status", "asset_type", "created_at",
        ),
    )

    object_key: Mapped[str] = mapped_column(String(700), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(120), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    original_filename_sanitized: Mapped[str | None] = mapped_column(String(255))
    asset_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source_type: Mapped[str | None] = mapped_column(String(40))
    source_ref: Mapped[str | None] = mapped_column(String(500))
    usage_rights_status: Mapped[str] = mapped_column(
        String(24), nullable=False, server_default="unknown"
    )
    license_note: Mapped[str | None] = mapped_column(Text)
    parent_asset_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    version_no: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    derivation_instruction: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="uploading")
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )


class UploadIntent(StoreScoped, Base):
    __tablename__ = "upload_intents"
    __table_args__ = (
        UniqueConstraint("store_id", "id", name="uq_upload_intents_store_id"),
        UniqueConstraint("object_key", name="uq_upload_intents_object_key"),
        CheckConstraint(
            "status IN ('created', 'uploaded', 'scanning', 'completed', 'rejected', 'scan_failed', 'expired')",
            name="status",
        ),
        CheckConstraint("expected_byte_size > 0", name="expected_byte_size_positive"),
        Index("ix_upload_intents_status_expiry", "status", "expires_at"),
    )

    created_by_user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    object_key: Mapped[str] = mapped_column(String(700), nullable=False)
    expected_mime_type: Mapped[str] = mapped_column(String(120), nullable=False)
    expected_byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    expected_sha256: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="created")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejection_reason: Mapped[str | None] = mapped_column(String(240))


class StoreRecordRevision(StoreScoped, Base):
    __tablename__ = "store_record_revisions"
    __table_args__ = (
        UniqueConstraint(
            "store_id", "record_type", "record_id", "version_no",
            name="uq_store_record_revisions_version",
        ),
        CheckConstraint(
            "fact_status IN ('unverified', 'pending_confirmation', 'confirmed', "
            "'needs_review', 'expired')",
            name="fact_status",
        ),
        Index(
            "ix_store_record_revisions_lookup",
            "store_id", "record_type", "record_id", "created_at",
        ),
    )

    record_type: Mapped[str] = mapped_column(String(60), nullable=False)
    record_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot_json: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    content_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    fact_status: Mapped[str] = mapped_column(String(32), nullable=False)
    source_type: Mapped[str | None] = mapped_column(String(40))
    source_ref: Mapped[str | None] = mapped_column(String(500))
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    confirmed_by_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    change_reason: Mapped[str | None] = mapped_column(Text)


offer_products = Table(
    "offer_products",
    Base.metadata,
    Column("store_id", PGUUID(as_uuid=True), nullable=False),
    Column("offer_id", PGUUID(as_uuid=True), nullable=False),
    Column("product_id", PGUUID(as_uuid=True), nullable=False),
    ForeignKeyConstraint(
        ["store_id", "offer_id"], ["offers.store_id", "offers.id"],
        ondelete="CASCADE", name="fk_offer_products_offer_same_store",
    ),
    ForeignKeyConstraint(
        ["store_id", "product_id"], ["products.store_id", "products.id"],
        ondelete="CASCADE", name="fk_offer_products_product_same_store",
    ),
    PrimaryKeyConstraint("store_id", "offer_id", "product_id", name="pk_offer_products"),
)

product_media_assets = Table(
    "product_media_assets",
    Base.metadata,
    Column("store_id", PGUUID(as_uuid=True), nullable=False),
    Column("product_id", PGUUID(as_uuid=True), nullable=False),
    Column("asset_id", PGUUID(as_uuid=True), nullable=False),
    Column("role", String(24), nullable=False),
    Column("sort_order", Integer, nullable=False, server_default="0"),
    ForeignKeyConstraint(
        ["store_id", "product_id"], ["products.store_id", "products.id"],
        ondelete="CASCADE", name="fk_product_media_assets_product_same_store",
    ),
    ForeignKeyConstraint(
        ["store_id", "asset_id"], ["media_assets.store_id", "media_assets.id"],
        ondelete="RESTRICT", name="fk_product_media_assets_asset_same_store",
    ),
    PrimaryKeyConstraint("store_id", "product_id", "asset_id", name="pk_product_media_assets"),
)

knowledge_item_products = Table(
    "knowledge_item_products",
    Base.metadata,
    Column("store_id", PGUUID(as_uuid=True), nullable=False),
    Column("knowledge_item_id", PGUUID(as_uuid=True), nullable=False),
    Column("product_id", PGUUID(as_uuid=True), nullable=False),
    ForeignKeyConstraint(
        ["store_id", "knowledge_item_id"], ["knowledge_items.store_id", "knowledge_items.id"],
        ondelete="CASCADE", name="fk_knowledge_item_products_item_same_store",
    ),
    ForeignKeyConstraint(
        ["store_id", "product_id"], ["products.store_id", "products.id"],
        ondelete="CASCADE", name="fk_knowledge_item_products_product_same_store",
    ),
    PrimaryKeyConstraint(
        "store_id", "knowledge_item_id", "product_id",
        name="pk_knowledge_item_products",
    ),
)

audience_profile_products = Table(
    "audience_profile_products",
    Base.metadata,
    Column("store_id", PGUUID(as_uuid=True), nullable=False),
    Column("audience_profile_id", PGUUID(as_uuid=True), nullable=False),
    Column("product_id", PGUUID(as_uuid=True), nullable=False),
    ForeignKeyConstraint(
        ["store_id", "audience_profile_id"], ["audience_profiles.store_id", "audience_profiles.id"],
        ondelete="CASCADE", name="fk_audience_profile_products_profile_same_store",
    ),
    ForeignKeyConstraint(
        ["store_id", "product_id"], ["products.store_id", "products.id"],
        ondelete="CASCADE", name="fk_audience_profile_products_product_same_store",
    ),
    PrimaryKeyConstraint(
        "store_id", "audience_profile_id", "product_id",
        name="pk_audience_profile_products",
    ),
)


class IdempotencyRecord(StoreScoped, Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint(
            "store_id", "idempotency_key", name="uq_idempotency_records_store_key"
        ),
        CheckConstraint(
            "status IN ('in_progress', 'completed')",
            name="status",
        ),
        Index("ix_idempotency_records_expires_at", "expires_at"),
    )

    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    actor_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    operation: Mapped[str] = mapped_column(String(120), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="in_progress"
    )
    response_status: Mapped[int | None] = mapped_column(Integer)
    response_json: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    resource_type: Mapped[str | None] = mapped_column(String(60))
    resource_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
