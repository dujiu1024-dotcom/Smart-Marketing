from uuid import uuid4

import pytest

from store_operator.ai_gateway import (
    ProviderCallContext,
    ProviderCapability,
    ProviderDescriptor,
    ProviderError,
    ProviderErrorCode,
    ProviderRegistry,
    SideEffectState,
)


class FakeTextProvider:
    pass


def descriptor(
    provider_id: str = "test-provider",
    *,
    enabled: bool = True,
    region: str | None = None,
) -> ProviderDescriptor:
    return ProviderDescriptor(
        provider_id=provider_id,
        display_name="Test Provider",
        capabilities=frozenset({ProviderCapability.TEXT}),
        supported_models={ProviderCapability.TEXT: ("test-model",)},
        enabled=enabled,
        region=region,
    )


def test_provider_registry_resolves_explicit_provider() -> None:
    registry = ProviderRegistry()
    adapter = FakeTextProvider()
    registry.register(descriptor(), adapter)

    assert registry.resolve(ProviderCapability.TEXT, provider_id="test-provider") is adapter


def test_provider_registry_does_not_fall_back_from_explicit_provider() -> None:
    registry = ProviderRegistry()
    registry.register(descriptor("available"), FakeTextProvider())

    with pytest.raises(ProviderError) as error:
        registry.resolve(ProviderCapability.TEXT, provider_id="missing")

    assert error.value.code is ProviderErrorCode.UNAVAILABLE


def test_provider_registry_filters_capability_and_region() -> None:
    registry = ProviderRegistry()
    registry.register(descriptor(region="eu"), FakeTextProvider())

    with pytest.raises(ProviderError) as error:
        registry.resolve(ProviderCapability.TEXT, region="us")

    assert error.value.code is ProviderErrorCode.REGION_NOT_ALLOWED


def test_provider_registry_rejects_duplicate_provider_ids() -> None:
    registry = ProviderRegistry()
    registry.register(descriptor(), FakeTextProvider())

    with pytest.raises(ValueError, match="already registered"):
        registry.register(descriptor(), FakeTextProvider())


def test_provider_error_preserves_retry_and_side_effect_semantics() -> None:
    error = ProviderError(
        ProviderErrorCode.TIMEOUT,
        retryable=True,
        retry_after_seconds=2.5,
        side_effect_state=SideEffectState.UNKNOWN,
        user_safe_summary="The AI service did not return a confirmed result.",
    )

    assert error.retryable is True
    assert error.retry_after_seconds == 2.5
    assert error.side_effect_state is SideEffectState.UNKNOWN


def test_provider_call_context_is_versioned_and_store_scoped() -> None:
    context = ProviderCallContext(request_id="req-1", store_id=uuid4())

    assert context.schema_version == 1
    assert context.marketing_task_id is None
