from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class GatewaySchema(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ProviderCapability(StrEnum):
    TEXT = "text"
    IMAGE = "image"
    VISION = "vision"
    OCR = "ocr"


class ProviderCallContext(GatewaySchema):
    schema_version: Literal[1] = 1
    request_id: str = Field(min_length=1, max_length=128)
    store_id: UUID
    job_id: UUID | None = None
    attempt_id: UUID | None = None
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=200)
    marketing_task_id: UUID | None = None
    prompt_version_id: UUID | None = None


class ProviderDescriptor(GatewaySchema):
    provider_id: str = Field(min_length=1, max_length=80)
    display_name: str = Field(min_length=1, max_length=120)
    capabilities: frozenset[ProviderCapability]
    supported_models: dict[ProviderCapability, tuple[str, ...]]
    enabled: bool = True
    region: str | None = Field(default=None, max_length=32)
    max_concurrency: int = Field(default=1, ge=1, le=10000)


class TextGenerateRequest(GatewaySchema):
    context: ProviderCallContext
    model_id: str = Field(min_length=1, max_length=160)
    system_instruction: str = Field(min_length=1, max_length=30000)
    user_input: str = Field(min_length=1, max_length=100000)
    output_schema: dict[str, object] | None = None
    temperature: float = Field(default=0.7, ge=0, le=2)
    max_output_tokens: int = Field(default=2048, ge=1, le=65536)


class TextGenerateResponse(GatewaySchema):
    model_id: str = Field(min_length=1, max_length=160)
    provider_request_id: str | None = Field(default=None, max_length=200)
    text: str
    structured_output: dict[str, object] | None = None
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)


class ImageGenerateRequest(GatewaySchema):
    context: ProviderCallContext
    model_id: str = Field(min_length=1, max_length=160)
    prompt: str = Field(min_length=1, max_length=30000)
    width: int = Field(default=1024, ge=64, le=8192)
    height: int = Field(default=1024, ge=64, le=8192)
    output_mime_type: Literal["image/png", "image/jpeg", "image/webp"] = "image/png"


class ImageEditRequest(ImageGenerateRequest):
    source_asset_object_key: str = Field(min_length=1, max_length=700)


class ImageGenerateResponse(GatewaySchema):
    model_id: str = Field(min_length=1, max_length=160)
    provider_request_id: str | None = Field(default=None, max_length=200)
    asset_object_key: str = Field(min_length=1, max_length=700)
    sha256: str = Field(pattern="^[a-f0-9]{64}$")
    mime_type: Literal["image/png", "image/jpeg", "image/webp"]
    width: int = Field(ge=1, le=8192)
    height: int = Field(ge=1, le=8192)


class VisionInspectRequest(GatewaySchema):
    context: ProviderCallContext
    model_id: str = Field(min_length=1, max_length=160)
    asset_object_key: str = Field(min_length=1, max_length=700)
    inspection_criteria: tuple[str, ...] = ()


class VisionInspectResponse(GatewaySchema):
    model_id: str = Field(min_length=1, max_length=160)
    provider_request_id: str | None = Field(default=None, max_length=200)
    passed: bool
    findings: tuple[dict[str, object], ...] = ()


class OCRRequest(GatewaySchema):
    context: ProviderCallContext
    model_id: str = Field(min_length=1, max_length=160)
    asset_object_key: str = Field(min_length=1, max_length=700)
    language_hints: tuple[str, ...] = ()


class OCRResponse(GatewaySchema):
    model_id: str = Field(min_length=1, max_length=160)
    provider_request_id: str | None = Field(default=None, max_length=200)
    extracted_text: str
    structured_fields: dict[str, object] = Field(default_factory=dict)
    confidence: float | None = Field(default=None, ge=0, le=1)
