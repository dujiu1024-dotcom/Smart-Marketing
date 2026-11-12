import asyncio
from contextlib import nullcontext
from uuid import uuid4

import pytest
from sqlalchemy import select

from store_operator.ai_gateway import (
    AIProviderExecutor,
    ImageGenerateRequest,
    ProviderCallContext,
    ProviderCapability,
    ProviderDescriptor,
    ProviderError,
    ProviderErrorCode,
    ProviderRegistry,
    SideEffectState,
    TextGenerateRequest,
    TextGenerateResponse,
)
from store_operator.models import AIInvocation, AIUsageRecord, Store


class FakeTextProvider:
    async def generate(self, request: TextGenerateRequest) -> TextGenerateResponse:
        return TextGenerateResponse(
            model_id=request.model_id,
            provider_request_id="provider-request-123",
            text="Generated copy",
            input_tokens=12,
            output_tokens=24,
        )


def test_provider_executor_persists_invocation_and_usage(db_session) -> None:
    store = Store(name="AI Provider Execution Store", timezone="Asia/Tokyo")
    db_session.add(store)
    db_session.flush()

    registry = ProviderRegistry()
    registry.register(
        ProviderDescriptor(
            provider_id="test-provider",
            display_name="Test Provider",
            capabilities=frozenset({ProviderCapability.TEXT}),
            supported_models={ProviderCapability.TEXT: ("text-test-v1",)},
        ),
        FakeTextProvider(),
    )
    executor = AIProviderExecutor(
        registry=registry,
        session_context_factory=lambda: nullcontext(db_session),
    )
    request = TextGenerateRequest(
        context=ProviderCallContext(
            request_id="request-execution-test",
            store_id=store.id,
            idempotency_key="job-idempotency-key-001",
        ),
        model_id="text-test-v1",
        system_instruction="Use confirmed facts only",
        user_input="Write a short store introduction",
        temperature=0.3,
    )

    result = asyncio.run(
        executor.generate_text(request, provider_id="test-provider")
    )

    invocation = db_session.scalar(
        select(AIInvocation).where(
            AIInvocation.store_id == store.id,
            AIInvocation.provider_request_id == "provider-request-123",
        )
    )
    assert result.text == "Generated copy"
    assert invocation is not None
    assert invocation.status == "succeeded"
    assert invocation.provider_key == "test-provider"
    assert invocation.model_key == "text-test-v1"
    assert invocation.capability == ProviderCapability.TEXT.value
    assert invocation.request_fingerprint is not None
    usage = db_session.get(AIUsageRecord, invocation.id)
    assert usage is not None
    assert usage.input_tokens == 12
    assert usage.output_tokens == 24


def test_async_image_execution_requires_idempotency_key(db_session) -> None:
    store = Store(name="AI Image Idempotency Store", timezone="Asia/Tokyo")
    db_session.add(store)
    db_session.flush()

    executor = AIProviderExecutor(
        registry=ProviderRegistry(),
        session_context_factory=lambda: nullcontext(db_session),
    )
    from store_operator.ai_gateway.schemas import ImageGenerateRequest

    request = ImageGenerateRequest(
        context=ProviderCallContext(
            request_id="image-job-request",
            store_id=store.id,
            job_id=uuid4(),
        ),
        model_id="image-test-v1",
        prompt="A storefront image",
    )

    with pytest.raises(ValueError, match="idempotency key"):
        asyncio.run(executor.generate_image(request, provider_id="test-provider"))



class TimeoutAfterImageSubmissionProvider:
    def __init__(self) -> None:
        self.idempotency_key: str | None = None

    async def generate(self, request: ImageGenerateRequest):
        self.idempotency_key = request.context.idempotency_key
        raise ProviderError(
            ProviderErrorCode.TIMEOUT,
            retryable=True,
            user_safe_summary="The image provider timed out.",
            side_effect_state=SideEffectState.UNKNOWN,
        )


def test_image_provider_timeout_preserves_unknown_side_effect_and_audit(
    db_session,
) -> None:
    store = Store(name="AI Image Timeout Store", timezone="Asia/Tokyo")
    db_session.add(store)
    db_session.flush()

    provider = TimeoutAfterImageSubmissionProvider()
    registry = ProviderRegistry()
    registry.register(
        ProviderDescriptor(
            provider_id="image-test-provider",
            display_name="Image Test Provider",
            capabilities=frozenset({ProviderCapability.IMAGE}),
            supported_models={ProviderCapability.IMAGE: ("image-test-v1",)},
        ),
        provider,
    )
    executor = AIProviderExecutor(
        registry=registry,
        session_context_factory=lambda: nullcontext(db_session),
    )
    request = ImageGenerateRequest(
        context=ProviderCallContext(
            request_id="image-timeout-request",
            store_id=store.id,
            idempotency_key="stable-image-job-operation-key",
        ),
        model_id="image-test-v1",
        prompt="Generate a promotional image",
    )

    with pytest.raises(ProviderError) as exc_info:
        asyncio.run(
            executor.generate_image(
                request,
                provider_id="image-test-provider",
            )
        )

    invocation = db_session.scalar(
        select(AIInvocation).where(
            AIInvocation.store_id == store.id,
            AIInvocation.capability == ProviderCapability.IMAGE.value,
        )
    )
    assert provider.idempotency_key == "stable-image-job-operation-key"
    assert exc_info.value.code is ProviderErrorCode.TIMEOUT
    assert exc_info.value.retryable is True
    assert exc_info.value.side_effect_state is SideEffectState.UNKNOWN
    assert invocation is not None
    assert invocation.status == "failed"
    assert invocation.error_code == ProviderErrorCode.TIMEOUT.value
