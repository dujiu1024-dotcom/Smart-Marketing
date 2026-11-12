from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import httpx

from store_operator.ai_gateway.http_provider import (
    HttpImageProvider,
    HttpJsonTransport,
    HttpOCRProvider,
    HttpTextProvider,
    HttpVisionProvider,
)
from store_operator.ai_gateway.registry import ProviderRegistry
from store_operator.ai_gateway.schemas import ProviderCapability, ProviderDescriptor
from store_operator.ai_gateway.secrets import ProviderSecretResolver


class HttpProviderBundle:
    """Capability-specific adapters sharing one transport and credential handle."""

    def __init__(self, transport: HttpJsonTransport) -> None:
        self.transport = transport
        self.text = HttpTextProvider(transport)
        self.image = HttpImageProvider(transport)
        self.vision = HttpVisionProvider(transport)
        self.ocr = HttpOCRProvider(transport)

    def for_capability(self, capability: ProviderCapability) -> object:
        adapters = {
            ProviderCapability.TEXT: self.text,
            ProviderCapability.IMAGE: self.image,
            ProviderCapability.VISION: self.vision,
            ProviderCapability.OCR: self.ocr,
        }
        return adapters[capability]

    async def aclose(self) -> None:
        await self.transport.aclose()


@dataclass(frozen=True, slots=True)
class HttpProviderEnvironmentConfig:
    provider_id: str
    display_name: str
    base_url: str
    secret_ref: str
    models: Mapping[ProviderCapability, tuple[str, ...]]
    region: str | None = None
    timeout_seconds: float = 45

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str],
    ) -> HttpProviderEnvironmentConfig | None:
        prefix = "AI_PROVIDER_"
        keys = (
            "PROVIDER_ID",
            "DISPLAY_NAME",
            "BASE_URL",
            "SECRET_REF",
            "TEXT_MODELS",
            "IMAGE_MODELS",
            "VISION_MODELS",
            "OCR_MODELS",
        )
        values = {key: environ.get(prefix + key, "").strip() for key in keys}
        if not any(values.values()):
            return None
        required = ("PROVIDER_ID", "DISPLAY_NAME", "BASE_URL", "SECRET_REF")
        missing = [key for key in required if not values[key]]
        if missing:
            raise ValueError("AI provider configuration is incomplete")
        models = {
            capability: tuple(dict.fromkeys(
                model.strip()
                for model in values[key].split(",")
                if model.strip()
            ))
            for capability, key in (
                (ProviderCapability.TEXT, "TEXT_MODELS"),
                (ProviderCapability.IMAGE, "IMAGE_MODELS"),
                (ProviderCapability.VISION, "VISION_MODELS"),
                (ProviderCapability.OCR, "OCR_MODELS"),
            )
        }
        configured_models = {key: value for key, value in models.items() if value}
        if not configured_models:
            raise ValueError("At least one AI provider capability and model must be configured")
        timeout_raw = environ.get(prefix + "TIMEOUT_SECONDS", "45").strip() or "45"
        try:
            timeout_seconds = float(timeout_raw)
        except ValueError as exc:
            raise ValueError("AI_PROVIDER_TIMEOUT_SECONDS must be numeric") from exc
        if not 0 < timeout_seconds <= 300:
            raise ValueError("AI_PROVIDER_TIMEOUT_SECONDS must be between 0 and 300")
        provider_id = values["PROVIDER_ID"]
        display_name = values["DISPLAY_NAME"]
        if len(provider_id) > 80 or len(display_name) > 120:
            raise ValueError("AI provider identifier or display name exceeds its limit")
        return cls(
            provider_id=provider_id,
            display_name=display_name,
            base_url=values["BASE_URL"],
            secret_ref=values["SECRET_REF"],
            models=configured_models,
            region=environ.get(prefix + "REGION") or None,
            timeout_seconds=timeout_seconds,
        )


def build_http_provider_registry(
    config: HttpProviderEnvironmentConfig,
    *,
    secret_resolver: ProviderSecretResolver,
    client: httpx.AsyncClient | None = None,
) -> ProviderRegistry:
    """Build a registry from explicit deployment config and an external Secret resolver."""
    api_key = secret_resolver.resolve_api_key(config.secret_ref)
    transport = HttpJsonTransport(
        base_url=config.base_url,
        api_key=api_key,
        timeout_seconds=config.timeout_seconds,
        client=client,
    )
    descriptor = ProviderDescriptor(
        provider_id=config.provider_id,
        display_name=config.display_name,
        capabilities=frozenset(config.models),
        supported_models=dict(config.models),
        enabled=True,
        region=config.region,
    )
    registry = ProviderRegistry()
    registry.register(descriptor, HttpProviderBundle(transport))
    return registry
