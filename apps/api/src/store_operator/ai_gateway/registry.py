from store_operator.ai_gateway.errors import ProviderError, ProviderErrorCode
from store_operator.ai_gateway.schemas import ProviderCapability, ProviderDescriptor


class ProviderRegistry:
    """Explicit in-process registry; it never imports adapters from request data."""

    def __init__(self) -> None:
        self._providers: dict[str, tuple[ProviderDescriptor, object]] = {}

    def register(self, descriptor: ProviderDescriptor, adapter: object) -> None:
        if not descriptor.capabilities:
            raise ValueError("A provider must declare at least one capability")
        if set(descriptor.supported_models) != set(descriptor.capabilities):
            raise ValueError("supported_models must declare every provider capability exactly once")
        if any(not models for models in descriptor.supported_models.values()):
            raise ValueError("Every declared capability must list at least one supported model")
        if descriptor.provider_id in self._providers:
            raise ValueError(f"Provider already registered: {descriptor.provider_id}")
        self._providers[descriptor.provider_id] = (descriptor, adapter)

    def resolve(
        self,
        capability: ProviderCapability,
        *,
        provider_id: str | None = None,
        region: str | None = None,
    ) -> object:
        if provider_id is not None:
            registration = self._providers.get(provider_id)
            candidates = [] if registration is None else [registration]
        else:
            candidates = [
                registration
                for _, registration in sorted(self._providers.items())
            ]

        for descriptor, adapter in candidates:
            if not descriptor.enabled or capability not in descriptor.capabilities:
                continue
            if region is not None and descriptor.region not in (None, region):
                continue
            return adapter

        if provider_id is not None and provider_id not in self._providers:
            summary = "The configured AI provider is not available."
            code = ProviderErrorCode.UNAVAILABLE
        elif region is not None:
            summary = "No enabled AI provider is allowed for the requested region."
            code = ProviderErrorCode.REGION_NOT_ALLOWED
        else:
            summary = "No enabled AI provider supports the requested capability."
            code = ProviderErrorCode.CAPABILITY_UNSUPPORTED
        raise ProviderError(code, retryable=False, user_safe_summary=summary)

    def descriptors(self) -> tuple[ProviderDescriptor, ...]:
        return tuple(
            descriptor
            for descriptor, _ in sorted(
                self._providers.values(), key=lambda item: item[0].provider_id
            )
        )
