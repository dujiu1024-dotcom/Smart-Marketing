from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from store_operator.ai_gateway.http_provider import (
    HttpImageProvider,
    HttpJsonTransport,
    HttpOCRProvider,
    HttpTextProvider,
    HttpVisionProvider,
)
from store_operator.ai_gateway.schemas import ProviderCapability


class HttpProviderBundle:
    """Capability-specific adapters sharing one transport and credential handle."""

    def __init__(self, transport: HttpJsonTransport) -> None:
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
            capability: tuple(
                model.strip()
                for model in values[key].split(",")
                if model.strip()
            )
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
        return cls(
            provider_id=values["PROVIDER_ID"],
            display_name=values["DISPLAY_NAME"],
            base_url=values["BASE_URL"],
            secret_ref=values["SECRET_REF"],
            models=configured_models,
            region=environ.get(prefix + "REGION") or None,
            timeout_seconds=timeout_seconds,
        )


def build_http_provider_registry(
    config: HttpProviderEnvironmentConfig,
    *,
    secret_resolver: object,
    client: object | None = None,
):
    """Build a registry from explicit deployment config and an external Secret resolver."""
    from store_operator.ai_gateway.registry import ProviderRegistry
    from store_operator.ai_gateway.schemas import ProviderDescriptor

    resolve = getattr(secret_resolver, "resolve_api_key", None)
    if not callable(resolve):
        raise TypeError("secret_resolver must implement resolve_api_key")
    api_key = resolve(config.secret_ref)
    transport = HttpJsonTransport(
        base_url=config.base_url,
        api_key=api_key,
        timeout_seconds=config.timeout_seconds,
        client=client,  # type: ignore[arg-type]
    )
    capabilities = frozenset(config.models)
    descriptor = ProviderDescriptor(
        provider_id=config.provider_id,
        display_name=config.display_name,
        capabilities=capabilities,
        supported_models=dict(config.models),
        enabled=True,
        region=config.region,
    )
    registry = ProviderRegistry()
    registry.register(descriptor, HttpProviderBundle(transport))
    return registry
