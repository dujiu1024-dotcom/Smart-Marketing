from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx
from pydantic import ValidationError

from store_operator.ai_gateway.errors import (
    ProviderError,
    ProviderErrorCode,
    SideEffectState,
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


class HttpJsonProvider:
    """HTTP adapter for providers implementing the Store Operator JSON wire contract.

    The adapter deliberately contains no vendor SDK or provider-specific fallback.
    Credentials are injected at construction time from a SecretStore reference and
    are never included in exceptions, response objects, or logs.
    """

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
            raise ValueError("Provider base URL must be an absolute HTTP(S) URL without credentials")
        if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("Non-local AI provider endpoints must use HTTPS")
        if not api_key.strip():
            raise ValueError("Provider API key is required")
        if timeout_seconds <= 0 or timeout_seconds > 300:
            raise ValueError("Provider timeout must be between 0 and 300 seconds")
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = httpx.Timeout(timeout_seconds, connect=min(timeout_seconds, 10))
        self._endpoints = endpoints or ProviderEndpoints()
        self._client = client
        self._owns_client = client is None

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()

    async def _post(
        self,
        path: str,
        payload: dict[str, Any],
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
                json=payload,
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
            retry_after = response.headers.get("Retry-After")
            try:
                retry_seconds = max(0.0, float(retry_after)) if retry_after else None
            except ValueError:
                retry_seconds = None
            raise ProviderError(
                ProviderErrorCode.RATE_LIMITED,
                retryable=True,
                retry_after_seconds=retry_seconds,
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
        if response.status_code in {400, 404, 413, 415, 422}:
            raise ProviderError(
                ProviderErrorCode.INVALID_REQUEST,
                retryable=False,
                side_effect_state=side_effect_state,
                user_safe_summary="The AI provider rejected the request format or capability.",
            )
        if response.status_code >= 500 or response.status_code in {408, 425}:
            raise ProviderError(
                ProviderErrorCode.UNAVAILABLE,
                retryable=True,
                side_effect_state=side_effect_state,
                user_safe_summary="The AI provider is temporarily unavailable.",
            )
        if response.is_error:
            raise ProviderError(
                ProviderErrorCode.INVALID_REQUEST,
                retryable=False,
                side_effect_state=side_effect_state,
                user_safe_summary="The AI provider rejected the request.",
            )
        try:
            result = response.json()
        except ValueError as exc:
            raise ProviderError(
                ProviderErrorCode.OUTPUT_INVALID,
                retryable=False,
                side_effect_state=side_effect_state,
                user_safe_summary="The AI provider returned an invalid response.",
            ) from exc
        if not isinstance(result, dict):
            raise ProviderError(
                ProviderErrorCode.OUTPUT_INVALID,
                retryable=False,
                side_effect_state=side_effect_state,
                user_safe_summary="The AI provider returned an unsupported response shape.",
            )
        return result

    @staticmethod
    def _validate(model: type[Any], payload: dict[str, Any], side_effect: SideEffectState) -> Any:
        try:
            return model.model_validate(payload)
        except ValidationError as exc:
            raise ProviderError(
                ProviderErrorCode.OUTPUT_INVALID,
                retryable=False,
                side_effect_state=side_effect,
                user_safe_summary="The AI provider response did not match the required contract.",
            ) from exc

    async def generate(self, request: TextGenerateRequest) -> TextGenerateResponse:
        result = await self._post(
            self._endpoints.text_generate,
            {
                "schema_version": 1,
                "operation": "text.generate",
                "request": request.model_dump(mode="json"),
            },
        )
        return self._validate(TextGenerateResponse, result, SideEffectState.NONE)

    async def generate_image(self, request: ImageGenerateRequest) -> ImageGenerateResponse:
        result = await self._post(
            self._endpoints.image_generate,
            {
                "schema_version": 1,
                "operation": "image.generate",
                "request": request.model_dump(mode="json"),
            },
            side_effect_state=SideEffectState.UNKNOWN,
        )
        return self._validate(ImageGenerateResponse, result, SideEffectState.UNKNOWN)

    async def edit(self, request: ImageEditRequest) -> ImageGenerateResponse:
        result = await self._post(
            self._endpoints.image_edit,
            {
                "schema_version": 1,
                "operation": "image.edit",
                "request": request.model_dump(mode="json"),
            },
            side_effect_state=SideEffectState.UNKNOWN,
        )
        return self._validate(ImageGenerateResponse, result, SideEffectState.UNKNOWN)

    async def inspect(self, request: VisionInspectRequest) -> VisionInspectResponse:
        result = await self._post(
            self._endpoints.vision_inspect,
            {
                "schema_version": 1,
                "operation": "vision.inspect",
                "request": request.model_dump(mode="json"),
            },
        )
        return self._validate(VisionInspectResponse, result, SideEffectState.NONE)

    async def extract(self, request: OCRRequest) -> OCRResponse:
        result = await self._post(
            self._endpoints.ocr_extract,
            {
                "schema_version": 1,
                "operation": "ocr.extract",
                "request": request.model_dump(mode="json"),
            },
        )
        return self._validate(OCRResponse, result, SideEffectState.NONE)
