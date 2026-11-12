import asyncio
import json
from uuid import uuid4

import httpx
import pytest

from store_operator.ai_gateway import (
    HttpImageProvider,
    HttpJsonTransport,
    HttpOCRProvider,
    HttpTextProvider,
    HttpVisionProvider,
    ImageEditRequest,
    ImageGenerateRequest,
    OCRRequest,
    ProviderCallContext,
    ProviderError,
    ProviderErrorCode,
    TextGenerateRequest,
    VisionInspectRequest,
)
from store_operator.ai_gateway.prompt_runtime import (
    PromptContractError,
    parse_and_validate_structured_output,
    render_published_prompt,
    validate_json_schema,
)
from store_operator.ai_gateway.secrets import (
    EnvironmentSecretResolver,
    SecretStoreProviderResolver,
)
from store_operator.channels.secret_store import SecretStoreError
from store_operator.models.prompt_management import PromptVersion


def context() -> ProviderCallContext:
    return ProviderCallContext(request_id="req-test", store_id=uuid4())


def transport(handler, *, api_key: str = "test-secret") -> HttpJsonTransport:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return HttpJsonTransport(
        base_url="https://provider.example",
        api_key=api_key,
        client=client,
    )


def test_http_text_provider_uses_canonical_contract_and_secret_header() -> None:
    observed = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["authorization"] = request.headers["Authorization"]
        observed["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"model_id": "text-v1", "text": "{\"title\":\"Hello\"}"},
        )

    client_transport = transport(handler)
    provider = HttpTextProvider(client_transport)
    request = TextGenerateRequest(
        context=context(),
        model_id="text-v1",
        system_instruction="Be accurate",
        user_input="Write a short post",
        output_schema={"type": "object"},
    )
    result = asyncio.run(provider.generate(request))

    assert result.model_id == "text-v1"
    assert observed["authorization"] == "Bearer test-secret"
    assert observed["payload"]["schema_version"] == 1
    assert observed["payload"]["operation"] == "text.generate"
    assert observed["payload"]["request"]["model_id"] == "text-v1"
    asyncio.run(client_transport._client.aclose())


def test_http_image_provider_separates_generation_and_edit_operations() -> None:
    operations = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        operation = payload["operation"]
        operations.append(operation)
        suffix = "generated" if operation == "image.generate" else "edited"
        return httpx.Response(
            200,
            json={
                "model_id": "image-v1",
                "asset_object_key": f"private/{suffix}/result.png",
                "sha256": ("a" if suffix == "generated" else "b") * 64,
                "mime_type": "image/png",
                "width": 1024,
                "height": 1024,
            },
        )

    client_transport = transport(handler)
    provider = HttpImageProvider(client_transport)
    call_context = context()
    generated = asyncio.run(
        provider.generate(
            ImageGenerateRequest(
                context=call_context,
                model_id="image-v1",
                prompt="A storefront",
            )
        )
    )
    edited = asyncio.run(
        provider.edit(
            ImageEditRequest(
                context=call_context,
                model_id="image-v1",
                prompt="Remove the background",
                source_asset_object_key="private/source/original.png",
            )
        )
    )

    assert generated.asset_object_key != edited.asset_object_key
    assert generated.sha256 != edited.sha256
    assert operations == ["image.generate", "image.edit"]
    asyncio.run(client_transport._client.aclose())


def test_http_vision_and_ocr_adapters_return_structured_results() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        operation = json.loads(request.content)["operation"]
        if operation == "vision.inspect":
            return httpx.Response(
                200,
                json={
                    "model_id": "vision-v1",
                    "passed": False,
                    "findings": [{"code": "TEXT_OVERFLOW", "severity": "major"}],
                },
            )
        return httpx.Response(
            200,
            json={
                "model_id": "ocr-v1",
                "extracted_text": "¥99",
                "structured_fields": {"price": "99"},
                "confidence": 0.98,
            },
        )

    client_transport = transport(handler)
    vision = HttpVisionProvider(client_transport)
    ocr = HttpOCRProvider(client_transport)
    call_context = context()
    vision_result = asyncio.run(
        vision.inspect(
            VisionInspectRequest(
                context=call_context,
                model_id="vision-v1",
                asset_object_key="private/image.png",
            )
        )
    )
    ocr_result = asyncio.run(
        ocr.extract(
            OCRRequest(
                context=call_context,
                model_id="ocr-v1",
                asset_object_key="private/image.png",
            )
        )
    )

    assert vision_result.passed is False
    assert vision_result.findings[0]["code"] == "TEXT_OVERFLOW"
    assert ocr_result.structured_fields["price"] == "99"
    assert ocr_result.confidence == 0.98
    asyncio.run(client_transport._client.aclose())


def test_http_provider_normalizes_rate_limit_without_exposing_response_body() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "7"}, text="secret=do-not-leak")

    client_transport = transport(handler)
    provider = HttpTextProvider(client_transport)
    request = TextGenerateRequest(
        context=context(),
        model_id="text-v1",
        system_instruction="Be accurate",
        user_input="Write",
    )
    with pytest.raises(ProviderError) as caught:
        asyncio.run(provider.generate(request))

    assert caught.value.code is ProviderErrorCode.RATE_LIMITED
    assert caught.value.retryable is True
    assert caught.value.retry_after_seconds == 7
    assert "do-not-leak" not in str(caught.value)
    asyncio.run(client_transport._client.aclose())


def test_image_timeout_marks_side_effect_as_unknown() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("transport detail")

    client_transport = transport(handler)
    provider = HttpImageProvider(client_transport)
    request = ImageGenerateRequest(
        context=context(),
        model_id="image-v1",
        prompt="A storefront",
    )
    with pytest.raises(ProviderError) as caught:
        asyncio.run(provider.generate(request))

    assert caught.value.code is ProviderErrorCode.TIMEOUT
    assert caught.value.retryable is True
    assert caught.value.side_effect_state.value == "unknown"
    asyncio.run(client_transport._client.aclose())


def test_http_provider_rejects_insecure_remote_urls_and_missing_keys() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        HttpJsonTransport(base_url="http://provider.example", api_key="secret")
    with pytest.raises(ValueError, match="API key"):
        HttpJsonTransport(base_url="https://provider.example", api_key=" ")


def test_environment_secret_resolver_accepts_only_secret_references() -> None:
    resolver = EnvironmentSecretResolver({"AI_TEXT_KEY": "runtime-secret"})

    assert resolver.resolve_api_key("env://AI_TEXT_KEY") == "runtime-secret"
    with pytest.raises(SecretStoreError):
        resolver.resolve_api_key("runtime-secret")
    with pytest.raises(SecretStoreError):
        resolver.resolve_api_key("env://MISSING")


def test_secret_store_resolver_extracts_key_without_persisting_it() -> None:
    class FakeSecretStore:
        def get_json(self, secret_ref: str) -> dict[str, str]:
            assert secret_ref == "arn:secret:provider"
            return {"api_key": "secret-from-store"}

        def put_json(self, secret_name: str, value: dict[str, str]) -> str:
            raise AssertionError("Resolver must not write secrets")

    resolver = SecretStoreProviderResolver(FakeSecretStore())
    assert resolver.resolve_api_key("arn:secret:provider") == "secret-from-store"


def prompt_version(*, status: str = "published") -> PromptVersion:
    return PromptVersion(
        prompt_template_id=uuid4(),
        version_no=1,
        system_prompt="Use only supplied confirmed facts.",
        user_prompt_template="Create content for {{store_name}}",
        variables_schema_json={
            "type": "object",
            "properties": {"store_name": {"type": "string", "minLength": 1}},
            "required": ["store_name"],
            "additionalProperties": False,
        },
        output_schema_json={
            "type": "object",
            "properties": {
                "title": {"type": "string", "minLength": 1},
                "body": {"type": "string", "minLength": 1},
            },
            "required": ["title", "body"],
            "additionalProperties": False,
        },
        schema_version=1,
        input_policy_json={"confirmed_facts_only": True},
        changelog="Initial version",
        status=status,
    )


def test_prompt_runtime_renders_only_published_version_and_valid_variables() -> None:
    system, user = render_published_prompt(
        prompt_version(),
        {"store_name": "Central Store"},
    )

    assert "confirmed facts" in system
    assert user == "Create content for Central Store"


def test_prompt_runtime_rejects_draft_versions_and_unexpected_variables() -> None:
    with pytest.raises(PromptContractError, match="published"):
        render_published_prompt(prompt_version(status="draft"), {"store_name": "Store"})
    with pytest.raises(PromptContractError, match="Unexpected"):
        render_published_prompt(
            prompt_version(),
            {"store_name": "Store", "other_store": "Not allowed"},
        )


def test_prompt_runtime_validates_structured_output_schema() -> None:
    output = parse_and_validate_structured_output(
        '{"title":"Welcome","body":"Visit our store"}',
        prompt_version().output_schema_json,
    )
    assert output == {"title": "Welcome", "body": "Visit our store"}

    with pytest.raises(ProviderError) as caught:
        parse_and_validate_structured_output(
            '{"title":"Welcome"}',
            prompt_version().output_schema_json,
        )
    assert caught.value.code is ProviderErrorCode.OUTPUT_INVALID


def test_prompt_runtime_fails_closed_for_unsupported_schema_keywords() -> None:
    with pytest.raises(PromptContractError, match="Unsupported"):
        validate_json_schema(
            {"value": "x"},
            {"type": "object", "patternProperties": {}},
        )


def test_provider_environment_config_is_disabled_until_explicitly_configured() -> None:
    from store_operator.ai_gateway.provider_config import HttpProviderEnvironmentConfig

    assert HttpProviderEnvironmentConfig.from_environment({}) is None
    with pytest.raises(ValueError, match="incomplete"):
        HttpProviderEnvironmentConfig.from_environment(
            {"AI_PROVIDER_ID": "primary"}
        )


def test_provider_environment_config_parses_only_declared_capabilities() -> None:
    from store_operator.ai_gateway.provider_config import HttpProviderEnvironmentConfig
    from store_operator.ai_gateway.schemas import ProviderCapability

    config = HttpProviderEnvironmentConfig.from_environment(
        {
            "AI_PROVIDER_PROVIDER_ID": "primary",
            "AI_PROVIDER_DISPLAY_NAME": "Primary AI",
            "AI_PROVIDER_BASE_URL": "https://ai.example",
            "AI_PROVIDER_SECRET_REF": "env://AI_PRIMARY_KEY",
            "AI_PROVIDER_TEXT_MODELS": "text-a, text-b",
            "AI_PROVIDER_IMAGE_MODELS": "image-a",
            "AI_PROVIDER_TIMEOUT_SECONDS": "30",
        }
    )

    assert config is not None
    assert config.models[ProviderCapability.TEXT] == ("text-a", "text-b")
    assert config.models[ProviderCapability.IMAGE] == ("image-a",)
    assert ProviderCapability.VISION not in config.models
    assert config.timeout_seconds == 30


def test_configured_registry_resolves_capability_specific_adapters_and_models() -> None:
    from store_operator.ai_gateway.provider_config import (
        HttpProviderEnvironmentConfig,
        build_http_provider_registry,
    )
    from store_operator.ai_gateway.schemas import ProviderCapability

    config = HttpProviderEnvironmentConfig.from_environment(
        {
            "AI_PROVIDER_PROVIDER_ID": "primary",
            "AI_PROVIDER_DISPLAY_NAME": "Primary AI",
            "AI_PROVIDER_BASE_URL": "https://ai.example",
            "AI_PROVIDER_SECRET_REF": "env://AI_PRIMARY_KEY",
            "AI_PROVIDER_TEXT_MODELS": "text-a",
            "AI_PROVIDER_IMAGE_MODELS": "image-a",
        }
    )
    assert config is not None

    class FakeResolver:
        def resolve_api_key(self, secret_ref: str) -> str:
            assert secret_ref == "env://AI_PRIMARY_KEY"
            return "secret-value"

    client = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda _: httpx.Response(200, json={"model_id": "text-a", "text": "ok"})
    ))
    registry = build_http_provider_registry(
        config,
        secret_resolver=FakeResolver(),
        client=client,
    )

    assert isinstance(
        registry.resolve(
            ProviderCapability.TEXT,
            provider_id="primary",
            model_id="text-a",
        ),
        HttpTextProvider,
    )
    assert isinstance(
        registry.resolve(
            ProviderCapability.IMAGE,
            provider_id="primary",
            model_id="image-a",
        ),
        HttpImageProvider,
    )
    with pytest.raises(ProviderError) as caught:
        registry.resolve(
            ProviderCapability.TEXT,
            provider_id="primary",
            model_id="not-configured",
        )
    assert caught.value.code is ProviderErrorCode.CAPABILITY_UNSUPPORTED
    asyncio.run(client.aclose())
