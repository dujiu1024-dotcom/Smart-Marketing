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
