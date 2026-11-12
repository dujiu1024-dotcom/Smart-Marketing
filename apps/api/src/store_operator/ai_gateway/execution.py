from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from contextlib import AbstractContextManager
from time import monotonic
from typing import TypeVar, cast

from pydantic import BaseModel
from sqlalchemy.orm import Session

from store_operator.ai_gateway.errors import (
    ProviderError,
    ProviderErrorCode,
    SideEffectState,
)
from store_operator.ai_gateway.invocations import (
    complete_ai_invocation,
    fail_ai_invocation,
    start_ai_invocation,
)
from store_operator.ai_gateway.protocols import ImageProvider, OCRProvider, TextProvider, VisionProvider
from store_operator.ai_gateway.registry import ProviderRegistry
from store_operator.ai_gateway.schemas import (
    ImageEditRequest,
    ImageGenerateRequest,
    ImageGenerateResponse,
    OCRRequest,
    OCRResponse,
    ProviderCapability,
    TextGenerateRequest,
    TextGenerateResponse,
    VisionInspectRequest,
    VisionInspectResponse,
)

ResponseT = TypeVar("ResponseT", bound=BaseModel)
SessionContextFactory = Callable[[], AbstractContextManager[Session]]


def _image_response_reference(result: ImageGenerateResponse) -> dict[str, object]:
    return {
        "schema_version": 1,
        "object_key": result.asset_object_key,
        "sha256": result.sha256,
        "mime_type": result.mime_type,
        "width": result.width,
        "height": result.height,
    }


class AIProviderExecutor:
    """Execute provider calls with persisted invocation/usage audit boundaries.

    The caller supplies a short-lived SQLAlchemy session context factory. Invocation
    start and finish/failure are committed in separate transactions so a remote
    provider request never holds a database transaction or row lock open.
    """

    def __init__(
        self,
        *,
        registry: ProviderRegistry,
        session_context_factory: SessionContextFactory,
    ) -> None:
        self._registry = registry
        self._session_context_factory = session_context_factory

    @staticmethod
    def _fingerprint(
        request: BaseModel,
        *,
        capability: ProviderCapability,
        provider_id: str,
    ) -> str:
        payload = request.model_dump(mode="json")
        context = payload.pop("context", {})
        if isinstance(context, dict):
            context.pop("request_id", None)
            context.pop("attempt_id", None)
        canonical = json.dumps(
            {
                "capability": capability.value,
                "provider_id": provider_id,
                "request": payload,
                "context": context,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    async def _execute(
        self,
        *,
        capability: ProviderCapability,
        provider_id: str,
        request: BaseModel,
        call: Callable[[], Awaitable[ResponseT]],
        side_effect_state: SideEffectState = SideEffectState.NONE,
        response_ref: Callable[[ResponseT], dict[str, object] | None] | None = None,
    ) -> ResponseT:
        context = getattr(request, "context")
        model_id = getattr(request, "model_id")
        fingerprint = self._fingerprint(
            request,
            capability=capability,
            provider_id=provider_id,
        )
        parameters = {
            key: getattr(request, key)
            for key in (
                "temperature",
                "top_p",
                "max_output_tokens",
                "width",
                "height",
                "aspect_ratio",
                "output_mime_type",
                "quality",
                "seed",
                "steps",
                "guidance_scale",
                "num_images",
            )
            if hasattr(request, key)
        }
        with self._session_context_factory() as db:
            invocation = start_ai_invocation(
                db,
                store_id=context.store_id,
                job_id=context.job_id,
                attempt_id=context.attempt_id,
                provider_key=provider_id,
                model_key=model_id,
                capability=capability.value,
                request_fingerprint=fingerprint,
                task_id=context.marketing_task_id,
                prompt_version_id=context.prompt_version_id,
                parameter_snapshot=parameters,
            )
            invocation_id = invocation.id

        started_at = monotonic()
        try:
            result = await call()
            if getattr(result, "model_id", None) != model_id:
                raise ProviderError(
                    ProviderErrorCode.OUTPUT_INVALID,
                    retryable=False,
                    side_effect_state=side_effect_state,
                    user_safe_summary="The AI provider returned a model identifier different from the requested model.",
                )
        except ProviderError as exc:
            with self._session_context_factory() as db:
                fail_ai_invocation(
                    db,
                    invocation_id=invocation_id,
                    error_code=exc.code.value,
                    duration_ms=max(0, int((monotonic() - started_at) * 1000)),
                )
            raise
        except Exception as exc:
            with self._session_context_factory() as db:
                fail_ai_invocation(
                    db,
                    invocation_id=invocation_id,
                    error_code="AI_PROVIDER_INTERNAL",
                    duration_ms=max(0, int((monotonic() - started_at) * 1000)),
                )
            raise ProviderError(
                ProviderErrorCode.UNAVAILABLE,
                retryable=True,
                side_effect_state=side_effect_state,
                user_safe_summary="The AI provider execution could not be completed.",
            ) from exc

        response_reference = response_ref(result) if response_ref else None
        with self._session_context_factory() as db:
            complete_ai_invocation(
                db,
                invocation_id=invocation_id,
                input_tokens=getattr(result, "input_tokens", None),
                output_tokens=getattr(result, "output_tokens", None),
                provider_request_id=getattr(result, "provider_request_id", None),
                response_ref=response_reference,
                duration_ms=max(0, int((monotonic() - started_at) * 1000)),
            )
        return result

    async def generate_text(
        self,
        request: TextGenerateRequest,
        *,
        provider_id: str,
    ) -> TextGenerateResponse:
        provider = cast(
            TextProvider,
            self._registry.resolve(
                ProviderCapability.TEXT,
                provider_id=provider_id,
                model_id=request.model_id,
            ),
        )
        return await self._execute(
            capability=ProviderCapability.TEXT,
            provider_id=provider_id,
            request=request,
            call=lambda: provider.generate(request),
        )

    async def generate_image(
        self,
        request: ImageGenerateRequest,
        *,
        provider_id: str,
    ) -> ImageGenerateResponse:
        if request.context.job_id is not None and request.context.idempotency_key is None:
            raise ValueError("Asynchronous image generation requires an idempotency key")
        provider = cast(
            ImageProvider,
            self._registry.resolve(
                ProviderCapability.IMAGE,
                provider_id=provider_id,
                model_id=request.model_id,
            ),
        )
        return await self._execute(
            capability=ProviderCapability.IMAGE,
            provider_id=provider_id,
            request=request,
            call=lambda: provider.generate(request),
            side_effect_state=SideEffectState.UNKNOWN,
            response_ref=lambda result: _image_response_reference(
                cast(ImageGenerateResponse, result)
            ),
        )

    async def edit_image(
        self,
        request: ImageEditRequest,
        *,
        provider_id: str,
    ) -> ImageGenerateResponse:
        if request.context.job_id is not None and request.context.idempotency_key is None:
            raise ValueError("Asynchronous image editing requires an idempotency key")
        provider = cast(
            ImageProvider,
            self._registry.resolve(
                ProviderCapability.IMAGE,
                provider_id=provider_id,
                model_id=request.model_id,
            ),
        )
        return await self._execute(
            capability=ProviderCapability.IMAGE,
            provider_id=provider_id,
            request=request,
            call=lambda: provider.edit(request),
            side_effect_state=SideEffectState.UNKNOWN,
            response_ref=lambda result: {
                "schema_version": 1,
                "object_key": result.asset_object_key,
                "sha256": result.sha256,
                "mime_type": result.mime_type,
                "width": result.width,
                "height": result.height,
            },
        )

    async def inspect_image(
        self,
        request: VisionInspectRequest,
        *,
        provider_id: str,
    ) -> VisionInspectResponse:
        provider = cast(
            VisionProvider,
            self._registry.resolve(
                ProviderCapability.VISION,
                provider_id=provider_id,
                model_id=request.model_id,
            ),
        )
        return await self._execute(
            capability=ProviderCapability.VISION,
            provider_id=provider_id,
            request=request,
            call=lambda: provider.inspect(request),
        )

    async def extract_ocr(
        self,
        request: OCRRequest,
        *,
        provider_id: str,
    ) -> OCRResponse:
        provider = cast(
            OCRProvider,
            self._registry.resolve(
                ProviderCapability.OCR,
                provider_id=provider_id,
                model_id=request.model_id,
            ),
        )
        return await self._execute(
            capability=ProviderCapability.OCR,
            provider_id=provider_id,
            request=request,
            call=lambda: provider.extract(request),
        )
