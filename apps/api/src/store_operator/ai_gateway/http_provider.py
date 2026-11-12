from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypeVar
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ValidationError

from store_operator.ai_gateway.errors import ProviderError, ProviderErrorCode, SideEffectState
from store_operator.ai_gateway.prompt_runtime import (
    parse_and_validate_structured_output,
    validate_structured_output,
)
from store_operator.ai_gateway.schemas import (
    ImageEditRequest,
    ImageGenerateRequest,
    ImageGenerateResponse,
    OCRRequest,
    OCRResponse,
    TextGenerateRequest,
    TextGenerateResponse,
    VisionInspectRequest,
    VisionInspectResponse,
)


@dataclass(frozen=True, slots=True)
class ProviderEndpoints:
    """Paths for the versioned Store Operator provider wire contract."""

    text_generate: str = "/v1/text/generate"
    image_generate: str = "/v1/images/generate"
    image_edit: str = "/v1/images/edit"
    vision_inspect: str = "/v1/vision/inspect"
    ocr_extract: str = "/v1/ocr/extract"


ResponseModel = TypeVar("ResponseModel", bound=BaseModel)


class HttpJsonTransport:
    """Shared transport for providers implementing the Store Operator JSON contract."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        timeout_seconds: float = 45,
        endpoints: ProviderEndpoints | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        parsed = urlsplit(base_url)
        if (
            parsed.scheme not in {"https", "http"}
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Provider base URL must be absolute and must not contain credentials")
        if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("Non-local AI provider endpoints must use HTTPS")
        if not api_key.strip():
            raise ValueError("Provider API key is required")
        if not 0 < timeout_seconds <= 300:
            raise ValueError("Provider timeout must be between 0 and 300 seconds")
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = httpx.Timeout(timeout_seconds, connect=min(timeout_seconds, 10))
        self.endpoints = endpoints or ProviderEndpoints()
        self._client = client
        self._owns_client = client is None

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()

    async def post(
        self,
        path: str,
        operation: str,
        request: Any,
        *,
        side_effect_state: SideEffectState = SideEffectState.NONE,
    ) -> dict[str, Any]:
        if not path.startswith("/") or path.startswith("//"):
            raise ValueError("Provider endpoint paths must be absolute paths")
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        close_client = self._client is None
        try:
            response = await client.post(
                f"{self._base_url}{path}",
                json={
                    "schema_version": 1,
                    "operation": operation,
                    "request": request.model_dump(mode="json"),
                },
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                timeout=self._timeout,
            )
        except httpx.TimeoutException as exc:
            raise ProviderError(
                ProviderErrorCode.TIMEOUT,
                retryable=True,
                side_effect_state=side_effect_state,
                user_safe_summary="The AI provider did not respond before the request deadline.",
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(
                ProviderErrorCode.UNAVAILABLE,
                retryable=True,
                side_effect_state=side_effect_state,
                user_safe_summary="The AI provider is temporarily unavailable.",
            ) from exc
        finally:
            if close_client:
                await client.aclose()

        if response.status_code == 429:
            raw_retry_after = response.headers.get("Retry-After")
            try:
                retry_after = max(0.0, float(raw_retry_after)) if raw_retry_after else None
            except ValueError:
                retry_after = None
            raise ProviderError(
                ProviderErrorCode.RATE_LIMITED,
                retryable=True,
                retry_after_seconds=retry_after,
                side_effect_state=side_effect_state,
                user_safe_summary="The AI provider rate limit was reached.",
            )
        if response.status_code in {401, 403}:
            raise ProviderError(
                ProviderErrorCode.AUTH_FAILED,
                retryable=False,
                side_effect_state=side_effect_state,
                user_safe_summary="The configured AI provider credentials were rejected.",
            )
        if response.status_code in {400, 404, 413, 415, 422} or response.is_error:
            retryable = response.status_code >= 500 or response.status_code in {408, 425}
            code = ProviderErrorCode.UNAVAILABLE if retryable else ProviderErrorCode.INVALID_REQUEST
            raise ProviderError(
                code,
                retryable=retryable,
                side_effect_state=side_effect_state,
                user_safe_summary=(
                    "The AI provider is temporarily unavailable."
                    if retryable
                    else "The AI provider rejected the request."
                ),
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderError(
                ProviderErrorCode.OUTPUT_INVALID,
                retryable=False,
                side_effect_state=side_effect_state,
                user_safe_summary="The AI provider returned an invalid response.",
            ) from exc
        if not isinstance(payload, dict):
            raise ProviderError(
                ProviderErrorCode.OUTPUT_INVALID,
                retryable=False,
                side_effect_state=side_effect_state,
                user_safe_summary="The AI provider returned an unsupported response shape.",
            )
        return payload

    @staticmethod
    def validate_response(
        model: type[ResponseModel],
        payload: dict[str, Any],
    ) -> ResponseModel:
        try:
            return model.model_validate(payload)
        except ValidationError as exc:
            raise ProviderError(
                ProviderErrorCode.OUTPUT_INVALID,
                retryable=False,
                user_safe_summary="The AI provider response did not match the required contract.",
            ) from exc


class HttpTextProvider:
    def __init__(self, transport: HttpJsonTransport) -> None:
        self.transport = transport

    async def generate(self, request: TextGenerateRequest) -> TextGenerateResponse:
        payload = await self.transport.post(
            self.transport.endpoints.text_generate, "text.generate", request
        )
        response = self.transport.validate_response(TextGenerateResponse, payload)
        if request.output_schema is None:
            return response
        structured = (
            validate_structured_output(response.structured_output, request.output_schema)
            if response.structured_output is not None
            else parse_and_validate_structured_output(response.text, request.output_schema)
        )
        return response.model_copy(update={"structured_output": structured})


class HttpImageProvider:
    def __init__(self, transport: HttpJsonTransport) -> None:
        self.transport = transport

    async def generate(self, request: ImageGenerateRequest) -> ImageGenerateResponse:
        payload = await self.transport.post(
            self.transport.endpoints.image_generate,
            "image.generate",
            request,
            side_effect_state=SideEffectState.UNKNOWN,
        )
        return self.transport.validate_response(ImageGenerateResponse, payload)

    async def edit(self, request: ImageEditRequest) -> ImageGenerateResponse:
        payload = await self.transport.post(
            self.transport.endpoints.image_edit,
            "image.edit",
            request,
            side_effect_state=SideEffectState.UNKNOWN,
        )
        return self.transport.validate_response(ImageGenerateResponse, payload)


class HttpVisionProvider:
    def __init__(self, transport: HttpJsonTransport) -> None:
        self.transport = transport

    async def inspect(self, request: VisionInspectRequest) -> VisionInspectResponse:
        payload = await self.transport.post(
            self.transport.endpoints.vision_inspect, "vision.inspect", request
        )
        return self.transport.validate_response(VisionInspectResponse, payload)


class HttpOCRProvider:
    def __init__(self, transport: HttpJsonTransport) -> None:
        self.transport = transport

    async def extract(self, request: OCRRequest) -> OCRResponse:
        payload = await self.transport.post(
            self.transport.endpoints.ocr_extract, "ocr.extract", request
        )
        return self.transport.validate_response(OCRResponse, payload)
