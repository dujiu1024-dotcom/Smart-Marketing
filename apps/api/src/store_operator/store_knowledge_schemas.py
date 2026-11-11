from decimal import Decimal
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StoreProfileFields(BaseModel):
    display_name: str = Field(min_length=1, max_length=160)
    business_type: str | None = Field(default=None, max_length=80)
    industry_category: str | None = Field(default=None, max_length=120)
    brand_name: str | None = Field(default=None, max_length=160)
    introduction: str | None = None
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    region: str | None = Field(default=None, max_length=120)
    province: str | None = Field(default=None, max_length=120)
    city: str | None = Field(default=None, max_length=120)
    district: str | None = Field(default=None, max_length=120)
    address: str | None = Field(default=None, max_length=500)
    phone: str | None = Field(default=None, max_length=40)
    opening_hours_json: dict[str, object] | None = None
    temporary_closures_json: list[dict[str, object]] | None = None
    service_radius: str | None = Field(default=None, max_length=120)
    service_capabilities_json: list[str] | None = None


class StoreProfileCreate(StoreProfileFields):
    pass


class StoreProfileUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=160)
    business_type: str | None = Field(default=None, max_length=80)
    industry_category: str | None = Field(default=None, max_length=120)
    brand_name: str | None = Field(default=None, max_length=160)
    introduction: str | None = None
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    region: str | None = Field(default=None, max_length=120)
    province: str | None = Field(default=None, max_length=120)
    city: str | None = Field(default=None, max_length=120)
    district: str | None = Field(default=None, max_length=120)
    address: str | None = Field(default=None, max_length=500)
    phone: str | None = Field(default=None, max_length=40)
    opening_hours_json: dict[str, object] | None = None
    temporary_closures_json: list[dict[str, object]] | None = None
    service_radius: str | None = Field(default=None, max_length=120)
    service_capabilities_json: list[str] | None = None

    @model_validator(mode="after")
    def require_changes(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided")
        return self


class StoreProfileRead(StoreProfileFields):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    store_id: UUID
    fact_status: str
    current_version: int


class ProductFields(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    category: str | None = Field(default=None, max_length=120)
    sku: str | None = Field(default=None, max_length=120)
    specification: str | None = Field(default=None, max_length=300)
    unit: str | None = Field(default=None, max_length=40)
    price_amount: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    availability_status: str = Field(
        default="unknown", pattern="^(available|unavailable|seasonal|limited|unknown)$"
    )
    inventory_quantity: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=3)
    key_selling_points_json: list[str] | None = None
    description: str | None = None
    ingredients_or_materials: str | None = None
    allergens_and_restrictions_json: list[str] | None = None
    service_process: str | None = None
    delivery_method: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def require_price_currency_pair(self) -> Self:
        if (self.price_amount is None) != (self.currency is None):
            raise ValueError("price_amount and currency must be provided together")
        return self


class ProductCreate(ProductFields):
    pass


class ProductUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    category: str | None = Field(default=None, max_length=120)
    sku: str | None = Field(default=None, max_length=120)
    specification: str | None = Field(default=None, max_length=300)
    unit: str | None = Field(default=None, max_length=40)
    price_amount: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    availability_status: str | None = Field(
        default=None, pattern="^(available|unavailable|seasonal|limited|unknown)$"
    )
    inventory_quantity: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=3)
    key_selling_points_json: list[str] | None = None
    description: str | None = None
    ingredients_or_materials: str | None = None
    allergens_and_restrictions_json: list[str] | None = None
    service_process: str | None = None
    delivery_method: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def require_changes(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided")
        return self


class ProductRead(ProductFields):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    store_id: UUID
    fact_status: str
    current_version: int


class ProductList(BaseModel):
    items: list[ProductRead]
    total: int


class OfferFields(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    offer_type: str = Field(min_length=1, max_length=40)
    terms_json: dict[str, object]
    eligibility_rules_json: dict[str, object] = Field(default_factory=dict)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    stacking_policy: str | None = Field(default=None, max_length=40)
    usage_limit: int | None = Field(default=None, ge=1)
    status: str = Field(
        default="draft", pattern="^(draft|active|paused|expired|archived)$"
    )

    @model_validator(mode="after")
    def validate_window(self) -> Self:
        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be later than starts_at")
        return self


class OfferCreate(OfferFields):
    pass


class OfferUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    offer_type: str | None = Field(default=None, min_length=1, max_length=40)
    terms_json: dict[str, object] | None = None
    eligibility_rules_json: dict[str, object] | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    stacking_policy: str | None = Field(default=None, max_length=40)
    usage_limit: int | None = Field(default=None, ge=1)
    status: str | None = Field(
        default=None, pattern="^(draft|active|paused|expired|archived)$"
    )

    @model_validator(mode="after")
    def require_changes(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided")
        return self


class OfferRead(OfferFields):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    store_id: UUID
    fact_status: str
    current_version: int


class AudienceProfileFields(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    segment_type: str = Field(
        pattern="^(core|secondary|seasonal|scenario)$"
    )
    audience_description: str | None = None
    consumption_scenarios_json: list[str] | None = None
    consumption_periods_json: list[str] | None = None
    purchase_motivations_json: list[str] | None = None
    common_objections_json: list[str] | None = None
    source_type: str | None = Field(default=None, max_length=40)
    source_ref: str | None = Field(default=None, max_length=500)
    sample_size: int | None = Field(default=None, ge=0)
    sampled_at: datetime | None = None
    confidence_level: str | None = Field(default=None, max_length=24)


class AudienceProfileCreate(AudienceProfileFields):
    pass


class AudienceProfileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    segment_type: str | None = Field(
        default=None, pattern="^(core|secondary|seasonal|scenario)$"
    )
    audience_description: str | None = None
    consumption_scenarios_json: list[str] | None = None
    consumption_periods_json: list[str] | None = None
    purchase_motivations_json: list[str] | None = None
    common_objections_json: list[str] | None = None
    source_type: str | None = Field(default=None, max_length=40)
    source_ref: str | None = Field(default=None, max_length=500)
    sample_size: int | None = Field(default=None, ge=0)
    sampled_at: datetime | None = None
    confidence_level: str | None = Field(default=None, max_length=24)

    @model_validator(mode="after")
    def require_changes(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided")
        return self


class AudienceProfileRead(AudienceProfileFields):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    store_id: UUID
    fact_status: str
    current_version: int


class KnowledgeItemFields(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    category: str = Field(min_length=1, max_length=40)
    content_text: str | None = None
    content_ref: str | None = Field(default=None, max_length=700)
    content_hash: str | None = Field(default=None, max_length=64)
    source_type: str | None = Field(default=None, max_length=40)
    source_ref: str | None = Field(default=None, max_length=500)
    effective_at: datetime | None = None
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def validate_expiry(self) -> Self:
        if self.effective_at and self.expires_at and self.expires_at <= self.effective_at:
            raise ValueError("expires_at must be later than effective_at")
        if not self.content_text and not self.content_ref:
            raise ValueError("content_text or content_ref is required")
        return self


class KnowledgeItemCreate(KnowledgeItemFields):
    pass


class KnowledgeItemUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=240)
    category: str | None = Field(default=None, min_length=1, max_length=40)
    content_text: str | None = None
    content_ref: str | None = Field(default=None, max_length=700)
    content_hash: str | None = Field(default=None, max_length=64)
    source_type: str | None = Field(default=None, max_length=40)
    source_ref: str | None = Field(default=None, max_length=500)
    effective_at: datetime | None = None
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def require_changes(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided")
        return self


class KnowledgeItemRead(KnowledgeItemFields):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    store_id: UUID
    fact_status: str
    current_version: int


class BrandGuidelineFields(BaseModel):
    brand_story: str | None = None
    positioning: str | None = None
    differentiators: str | None = None
    core_values_json: list[str] | None = None
    tone_of_voice: str | None = None
    common_phrases_json: list[str] | None = None
    prohibited_phrases_json: list[str] | None = None
    cta_preferences_json: list[str] | None = None
    logo_asset_id: UUID | None = None
    color_palette_json: list[dict[str, object]] | None = None
    font_preferences_json: list[str] | None = None
    visual_style: str | None = None


class BrandGuidelineCreate(BrandGuidelineFields):
    pass


class BrandGuidelineUpdate(BrandGuidelineFields):
    pass


class BrandGuidelineRead(BrandGuidelineFields):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    store_id: UUID
    fact_status: str
    current_version: int
