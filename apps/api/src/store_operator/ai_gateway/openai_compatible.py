"""Adapters for OpenAI-compatible providers (chat/completions and images/generations).

The Store Operator gateway contract stays unchanged: callers keep using
``TextGenerateRequest``/``ImageGenerateRequest``/``VisionInspectRequest``. This module
translates those requests to the OpenAI wire format and normalizes the responses,
including persisting generated image bytes into private object storage.
"""

from __future__ import annotations

import base64
import hashlib
import struct
from collections.abc import Mapping
from typing import Any
from uuid import uuid4

import httpx

from store_operator.ai_gateway.circuit_breaker import CircuitBreaker
from store_operator.ai_gateway.errors import (
    ProviderError,
    ProviderErrorCode,
    SideEffectState,
)
from store_operator.ai_gateway.http_provider import validate_provider_base_url
from store_operator.ai_gateway.prompt_runtime import (
    parse_and_validate_structured_output,
)
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

_MAX_IMAGE_BYTES = 25 * 1024 * 1024
_SUPPORTED_IMAGE_MIME_TYPES = {"image/png", "image/jpeg", "image/webp"}


def _invalid_output(summary: str) -> ProviderError:
    return ProviderError(
        ProviderErrorCode.OUTPUT_INVALID,
        retryable=False,
        user_safe_summary=summary,
    )


def _detect_image_mime_type(content: bytes) -> str:
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    raise _invalid_output("The AI provider returned an unsupported image format.")


def _png_dimensions(content: bytes) -> tuple[int, int]:
    if len(content) < 24 or content[12:16] != b"IHDR":
        raise ValueError("PNG header is invalid")
    width, height = struct.unpack(">II", content[16:24])
    return width, height


def _jpeg_dimensions(content: bytes) -> tuple[int, int]:
    offset = 2
    frame_markers = {
        0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
        0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF,
    }
    while offset + 4 <= len(content):
        if content[offset] != 0xFF:
            offset += 1
            continue
        while offset < len(content) and content[offset] == 0xFF:
            offset += 1
        if offset >= len(content):
            break
        marker = content[offset]
        offset += 1
        if marker in {0xD8, 0xD9, 0x01} or 0xD0 <= marker <= 0xD7:
            continue
        if offset + 2 > len(content):
            break
        segment_length = struct.unpack(">H", content[offset : offset + 2])[0]
        if segment_length < 2 or offset + segment_length > len(content):
            raise ValueError("JPEG segment length is invalid")
        if marker in frame_markers:
            if segment_length < 7:
                raise ValueError("JPEG frame header is invalid")
            height, width = struct.unpack(">HH", content[offset + 3 : offset + 7])
            return width, height
        offset += segment_length
    raise ValueError("JPEG frame dimensions are missing")


def _webp_dimensions(content: bytes) -> tuple[int, int]:
    if len(content) < 30:
        raise ValueError("WebP container is truncated")
    offset = 12
    while offset + 8 <= len(content):
        chunk_type = content[offset : offset + 4]
        chunk_size = struct.unpack("<I", content[offset + 4 : offset + 8])[0]
        start = offset + 8
        end = start + chunk_size
        if end > len(content):
            raise ValueError("WebP chunk length is invalid")
        payload = content[start:end]
        if chunk_type == b"VP8X" and len(payload) >= 10:
            width = 1 + int.from_bytes(payload[4:7], "little")
            height = 1 + int.from_bytes(payload[7:10], "little")
            return width, height
        if chunk_type == b"VP8 " and len(payload) >= 10:
            width, height = struct.unpack("<HH", payload[6:10])
            return width & 0x3FFF, height & 0x3FFF
        if chunk_type == b"VP8L" and len(payload) >= 5:
            bits = int.from_bytes(payload[1:5], "little")
            return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
        offset = end + (chunk_size % 2)
    raise ValueError("WebP dimensions are missing")


def _image_dimensions(content: bytes, mime_type: str) -> tuple[int, int]:
    if mime_type == "image/png":
        dimensions = _png_dimensions(content)
    elif mime_type == "image/jpeg":
        dimensions = _jpeg_dimensions(content)
    else:
        dimensions = _webp_dimensions(content)
    width, height = dimensions
    if width <= 0 or height <= 0 or width > 8192 or height > 8192:
        raise ValueError("Image dimensions are outside the supported range")
    return width, height


class OpenAiCompatibleTransport:
    """JSON transport for OpenAI-compatible HTTP APIs."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        timeout_seconds: float = 45,
        client: httpx.AsyncClient | None = None,
        circuit_breaker: CircuitBreaker | None = None,
    ) -> None:
        validate_provider_base_url(base_url)
        if not api_key.strip():
            raise ValueError("Provider API key is required")
        if not 0 < timeout_seconds <= 300:
            raise ValueError("Provider timeout must be between 0 and 300 seconds")
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = httpx.Timeout(timeout_seconds, connect=min(timeout_seconds, 15))
        self._client = client
        self._owns_client = client is None
        self._circuit_breaker = circuit_breaker or CircuitBreaker()

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()

    @staticmethod
    def _rate_limit_signal(response: httpx.Response) -> bool:
        """Treat the vendor's ``insufficient_quota`` as a per-minute rate limit."""
        if response.status_code == 429:
            return True
        try:
            payload = response.json()
        except ValueError:
            return False
        error = payload.get("error") if isinstance(payload, dict) else None
        if not isinstance(error, dict):
            return False
        code = str(error.get("code") or error.get("type") or "").lower()
        message = str(error.get("message") or "").lower()
        return (
            code in {
                "insufficient_quota", "rate_limit_exceeded",
                "rate_limited", "too_many_requests",
            }
            or "insufficient_quota" in message
            or "rate limit" in message
            or "too many requests" in message
        )

    def _handle_error(
        self,
        response: httpx.Response,
        *,
        side_effect_state: SideEffectState,
    ) -> None:
        if self._rate_limit_signal(response):
            # A rate limit is a normal window boundary, not a provider outage, so it
            # must not open the circuit breaker. The caller backs off or degrades.
            raw_retry_after = response.headers.get("Retry-After")
            try:
                retry_after = max(0.0, float(raw_retry_after)) if raw_retry_after else 60.0
            except ValueError:
                retry_after = 60.0
            raise ProviderError(
                ProviderErrorCode.RATE_LIMITED,
                retryable=True,
                retry_after_seconds=retry_after,
                side_effect_state=side_effect_state,
                user_safe_summary="The AI provider rate limit was reached.",
            )
        if response.status_code in {401, 403}:
            self._circuit_breaker.record_rejected()
            raise ProviderError(
                ProviderErrorCode.AUTH_FAILED,
                retryable=False,
                side_effect_state=side_effect_state,
                user_safe_summary="The configured AI provider credentials were rejected.",
            )
        retryable = response.status_code >= 500 or response.status_code in {408, 425}
        if retryable:
            self._circuit_breaker.record_failure()
        else:
            self._circuit_breaker.record_rejected()
        raise ProviderError(
            ProviderErrorCode.UNAVAILABLE if retryable else ProviderErrorCode.INVALID_REQUEST,
            retryable=retryable,
            side_effect_state=side_effect_state,
            user_safe_summary=(
                "The AI provider is temporarily unavailable."
                if retryable
                else "The AI provider rejected the request."
            ),
        )

    @staticmethod
    def _json_payload(response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise _invalid_output(
                "The AI provider returned an invalid response."
            ) from exc
        if not isinstance(payload, dict):
            raise _invalid_output(
                "The AI provider returned an unsupported response shape."
            )
        return payload

    async def post_json(
        self,
        path: str,
        body: Mapping[str, Any],
        *,
        side_effect_state: SideEffectState = SideEffectState.NONE,
    ) -> dict[str, Any]:
        if not path.startswith("/") or path.startswith("//"):
            raise ValueError("Provider endpoint paths must be absolute paths")
        self._circuit_breaker.before_call()
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        close_client = self._client is None
        try:
            response = await client.post(
                f"{self._base_url}{path}",
                json=dict(body),
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                timeout=self._timeout,
            )
        except httpx.TimeoutException as exc:
            self._circuit_breaker.record_failure()
            raise ProviderError(
                ProviderErrorCode.TIMEOUT,
                retryable=True,
                side_effect_state=side_effect_state,
                user_safe_summary="The AI provider did not respond before the request deadline.",
            ) from exc
        except httpx.HTTPError as exc:
            self._circuit_breaker.record_failure()
            raise ProviderError(
                ProviderErrorCode.UNAVAILABLE,
                retryable=True,
                side_effect_state=side_effect_state,
                user_safe_summary="The AI provider is temporarily unavailable.",
            ) from exc
        finally:
            if close_client:
                await client.aclose()

        if response.is_error:
            self._handle_error(response, side_effect_state=side_effect_state)
        self._circuit_breaker.record_success()
        return self._json_payload(response)

    async def post_multipart(
        self,
        path: str,
        *,
        data: Mapping[str, str],
        files: Mapping[str, tuple[str, bytes, str]],
        side_effect_state: SideEffectState = SideEffectState.NONE,
    ) -> dict[str, Any]:
        if not path.startswith("/") or path.startswith("//"):
            raise ValueError("Provider endpoint paths must be absolute paths")
        self._circuit_breaker.before_call()
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        close_client = self._client is None
        try:
            response = await client.post(
                f"{self._base_url}{path}",
                data=dict(data),
                files=dict(files),
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Accept": "application/json",
                },
                timeout=self._timeout,
            )
        except httpx.TimeoutException as exc:
            self._circuit_breaker.record_failure()
            raise ProviderError(
                ProviderErrorCode.TIMEOUT,
                retryable=True,
                side_effect_state=side_effect_state,
                user_safe_summary="The AI provider did not respond before the request deadline.",
            ) from exc
        except httpx.HTTPError as exc:
            self._circuit_breaker.record_failure()
            raise ProviderError(
                ProviderErrorCode.UNAVAILABLE,
                retryable=True,
                side_effect_state=side_effect_state,
                user_safe_summary="The AI provider is temporarily unavailable.",
            ) from exc
        finally:
            if close_client:
                await client.aclose()

        if response.is_error:
            self._handle_error(response, side_effect_state=side_effect_state)
        self._circuit_breaker.record_success()
        return self._json_payload(response)


def _chat_message_content(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise _invalid_output("The AI provider returned no completion choices.")
    first = choices[0]
    if not isinstance(first, dict):
        raise _invalid_output("The AI provider returned an invalid completion choice.")
    message = first.get("message")
    if not isinstance(message, dict):
        raise _invalid_output("The AI provider returned an invalid chat message.")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise _invalid_output("The AI provider returned empty generated text.")
    return content


class OpenAiCompatibleTextProvider:
    def __init__(
        self,
        transport: OpenAiCompatibleTransport,
        *,
        disable_thinking: bool = False,
    ) -> None:
        self.transport = transport
        self._disable_thinking = disable_thinking

    async def generate(self, request: TextGenerateRequest) -> TextGenerateResponse:
        body: dict[str, Any] = {
            "model": request.model_id,
            "messages": [
                {"role": "system", "content": request.system_instruction},
                {"role": "user", "content": request.user_input},
            ],
            "temperature": request.temperature,
            "max_tokens": request.max_output_tokens,
        }
        if request.output_schema is not None:
            body["response_format"] = {"type": "json_object"}
        if self._disable_thinking:
            body["thinking"] = {"type": "disabled"}
        payload = await self.transport.post_json("/chat/completions", body)
        text = _chat_message_content(payload)
        usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
        structured_output = (
            parse_and_validate_structured_output(text, request.output_schema)
            if request.output_schema is not None
            else None
        )
        model_id = payload.get("model")
        return TextGenerateResponse(
            model_id=model_id if isinstance(model_id, str) and model_id else request.model_id,
            provider_request_id=(
                payload.get("id") if isinstance(payload.get("id"), str) else None
            ),
            text=text,
            structured_output=structured_output,
            input_tokens=(
                usage.get("prompt_tokens")
                if isinstance(usage.get("prompt_tokens"), int)
                else None
            ),
            output_tokens=(
                usage.get("completion_tokens")
                if isinstance(usage.get("completion_tokens"), int)
                else None
            ),
        )


def _decode_image_payload(payload: dict[str, Any]) -> bytes:
    data = payload.get("data")
    if not isinstance(data, list) or not data or not isinstance(data[0], dict):
        raise _invalid_output("The AI provider returned no generated image.")
    encoded = data[0].get("b64_json")
    if not isinstance(encoded, str) or not encoded.strip():
        raise ProviderError(
            ProviderErrorCode.CAPABILITY_UNSUPPORTED,
            retryable=False,
            user_safe_summary=(
                "The AI provider returned an image URL instead of inline image bytes; "
                "that response mode is not supported by this adapter."
            ),
        )
    try:
        content = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError) as exc:
        raise _invalid_output("The AI provider returned invalid base64 image data.") from exc
    if not content or len(content) > _MAX_IMAGE_BYTES:
        raise _invalid_output("The AI provider returned an image outside the allowed size.")
    return content


def _persist_generated_image(
    *,
    store_id: Any,
    content: bytes,
    mime_type: str,
) -> str:
    from store_operator import object_storage

    suffix = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/webp": ".webp",
    }[mime_type]
    object_key = f"stores/{store_id}/ai-generated/{uuid4()}{suffix}"
    try:
        object_storage.upload_object_bytes(
            object_key=object_key,
            content=content,
            mime_type=mime_type,
            sha256=hashlib.sha256(content).hexdigest(),
        )
    except Exception as exc:
        raise ProviderError(
            ProviderErrorCode.UNAVAILABLE,
            retryable=True,
            side_effect_state=SideEffectState.UNKNOWN,
            user_safe_summary=(
                "The generated image could not be written to private object storage."
            ),
        ) from exc
    return object_key


class OpenAiCompatibleImageProvider:
    def __init__(
        self,
        transport: OpenAiCompatibleTransport,
        *,
        watermark: bool = True,
    ) -> None:
        self.transport = transport
        self._watermark = watermark

    @staticmethod
    def _response(
        *,
        model_id: str,
        request: ImageGenerateRequest,
        payload: dict[str, Any],
    ) -> ImageGenerateResponse:
        content = _decode_image_payload(payload)
        mime_type = _detect_image_mime_type(content)
        try:
            width, height = _image_dimensions(content, mime_type)
        except ValueError as exc:
            raise _invalid_output(
                "The AI provider returned an image with unreadable dimensions."
            ) from exc
        object_key = _persist_generated_image(
            store_id=request.context.store_id,
            content=content,
            mime_type=mime_type,
        )
        return ImageGenerateResponse(
            model_id=model_id,
            provider_request_id=(
                payload.get("id") if isinstance(payload.get("id"), str) else None
            ),
            asset_object_key=object_key,
            sha256=hashlib.sha256(content).hexdigest(),
            mime_type=mime_type,  # type: ignore[arg-type]
            width=width,
            height=height,
        )

    async def generate(self, request: ImageGenerateRequest) -> ImageGenerateResponse:
        payload = await self.transport.post_json(
            "/images/generations",
            {
                "model": request.model_id,
                "prompt": request.prompt,
                "size": f"{request.width}x{request.height}",
                "n": 1,
                "response_format": "b64_json",
                "watermark": self._watermark,
            },
            side_effect_state=SideEffectState.UNKNOWN,
        )
        return self._response(
            model_id=request.model_id,
            request=request,
            payload=payload,
        )

    async def edit(self, request: ImageEditRequest) -> ImageGenerateResponse:
        from store_operator import object_storage

        try:
            source = object_storage.download_object_bytes(
                object_key=request.source_asset_object_key,
                max_bytes=_MAX_IMAGE_BYTES,
            )
        except Exception as exc:
            raise ProviderError(
                ProviderErrorCode.INVALID_REQUEST,
                retryable=False,
                user_safe_summary="The source image for editing could not be read.",
            ) from exc
        source_mime_type = _detect_image_mime_type(source)
        payload = await self.transport.post_multipart(
            "/images/edits",
            data={
                "model": request.model_id,
                "prompt": request.prompt,
                "size": f"{request.width}x{request.height}",
                "n": "1",
                "response_format": "b64_json",
                "watermark": "true" if self._watermark else "false",
            },
            files={
                "image": (
                    "source" + {
                        "image/png": ".png",
                        "image/jpeg": ".jpg",
                        "image/webp": ".webp",
                    }[source_mime_type],
                    source,
                    source_mime_type,
                )
            },
            side_effect_state=SideEffectState.UNKNOWN,
        )
        return self._response(
            model_id=request.model_id,
            request=request,
            payload=payload,
        )


class OpenAiCompatibleVisionProvider:
    def __init__(
        self,
        transport: OpenAiCompatibleTransport,
        *,
        disable_thinking: bool = False,
    ) -> None:
        self.transport = transport
        self._disable_thinking = disable_thinking

    async def inspect(self, request: VisionInspectRequest) -> VisionInspectResponse:
        from store_operator import object_storage

        try:
            content = object_storage.download_object_bytes(
                object_key=request.asset_object_key,
                max_bytes=_MAX_IMAGE_BYTES,
            )
        except Exception as exc:
            raise ProviderError(
                ProviderErrorCode.INVALID_REQUEST,
                retryable=False,
                user_safe_summary="The image to inspect could not be read from storage.",
            ) from exc
        mime_type = _detect_image_mime_type(content)
        if mime_type not in _SUPPORTED_IMAGE_MIME_TYPES:
            raise _invalid_output("The image to inspect has an unsupported format.")
        criteria = [item for item in request.inspection_criteria if item.strip()]
        system_instruction = criteria[0] if criteria else (
            "You are a strict visual quality inspector for marketing images."
        )
        user_instruction = criteria[1] if len(criteria) > 1 else (
            "Inspect this marketing image and return JSON only."
        )
        data_uri = f"data:{mime_type};base64,{base64.b64encode(content).decode('ascii')}"
        body: dict[str, Any] = {
            "model": request.model_id,
            "messages": [
                {"role": "system", "content": system_instruction},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_instruction},
                        {"type": "image_url", "image_url": {"url": data_uri}},
                    ],
                },
            ],
            "response_format": {"type": "json_object"},
        }
        if self._disable_thinking:
            body["thinking"] = {"type": "disabled"}
        payload = await self.transport.post_json("/chat/completions", body)
        text = _chat_message_content(payload)
        try:
            report = parse_and_validate_structured_output(
                text,
                {
                    "type": "object",
                    "properties": {
                        "passed": {"type": "boolean"},
                        "findings": {"type": "array"},
                        "overall_severity": {"type": "string"},
                    },
                    "required": ["passed", "findings"],
                },
            )
        except ProviderError as exc:
            raise _invalid_output(
                "The AI vision model did not return the required inspection JSON."
            ) from exc
        findings = report.get("findings")
        if not isinstance(findings, list):
            raise _invalid_output("The AI vision model returned invalid findings.")
        model_id = payload.get("model")
        return VisionInspectResponse(
            model_id=model_id if isinstance(model_id, str) and model_id else request.model_id,
            provider_request_id=(
                payload.get("id") if isinstance(payload.get("id"), str) else None
            ),
            passed=bool(report.get("passed")),
            findings=tuple(
                finding for finding in findings if isinstance(finding, dict)
            ),
        )


class OpenAiCompatibleOCRProvider:
    async def extract(self, request: OCRRequest) -> OCRResponse:
        raise ProviderError(
            ProviderErrorCode.CAPABILITY_UNSUPPORTED,
            retryable=False,
            user_safe_summary="OCR is not supported by the OpenAI-compatible adapter.",
        )


class OpenAiCompatibleProviderBundle:
    """Capability-specific adapters sharing one OpenAI-compatible transport."""

    def __init__(
        self,
        transport: OpenAiCompatibleTransport,
        *,
        disable_thinking: bool = False,
        watermark: bool = True,
    ) -> None:
        self.transport = transport
        self.text = OpenAiCompatibleTextProvider(
            transport, disable_thinking=disable_thinking
        )
        self.image = OpenAiCompatibleImageProvider(
            transport, watermark=watermark
        )
        self.vision = OpenAiCompatibleVisionProvider(
            transport, disable_thinking=disable_thinking
        )
        self.ocr = OpenAiCompatibleOCRProvider()

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
