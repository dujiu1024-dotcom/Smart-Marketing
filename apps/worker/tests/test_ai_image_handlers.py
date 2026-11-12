import hashlib
from types import SimpleNamespace
from uuid import uuid4

import pytest
from store_operator.ai_gateway.schemas import ImageGenerateResponse, VisionInspectResponse

from store_operator_worker import ai_image_handlers
from store_operator_worker.handlers import JobExecutionError


def test_image_size_maps_supported_aspect_ratios() -> None:
    assert ai_image_handlers._image_size("1:1") == (1024, 1024)
    assert ai_image_handlers._image_size("4:5") == (1024, 1280)
    assert ai_image_handlers._image_size("9:16") == (864, 1536)
    assert ai_image_handlers._image_size("unknown") == (1024, 1024)


def test_generated_image_is_verified_and_scanned(monkeypatch: pytest.MonkeyPatch) -> None:
    content = b"verified-image-bytes"
    digest = hashlib.sha256(content).hexdigest()
    monkeypatch.setattr(
        ai_image_handlers,
        "download_object_bytes",
        lambda **kwargs: content,
    )
    monkeypatch.setattr(
        ai_image_handlers,
        "image_dimensions",
        lambda image_bytes, mime_type: (1024, 1024),
    )
    monkeypatch.setattr(
        ai_image_handlers,
        "validate_image_dimensions",
        lambda width, height: None,
    )
    monkeypatch.setattr(
        ai_image_handlers,
        "scan_with_clamd",
        lambda image_bytes, host, port: None,
    )
    result = ImageGenerateResponse(
        model_id="image-model",
        asset_object_key="stores/store-1/generated/image.png",
        sha256=digest,
        mime_type="image/png",
        width=1024,
        height=1024,
    )

    verified, width, height = ai_image_handlers._verify_and_scan_image(result)

    assert verified == content
    assert (width, height) == (1024, 1024)


def test_generated_image_rejects_path_traversal_before_storage_access() -> None:
    result = ImageGenerateResponse(
        model_id="image-model",
        asset_object_key="stores/store-1/../other-store/image.png",
        sha256="a" * 64,
        mime_type="image/png",
        width=1024,
        height=1024,
    )

    with pytest.raises(JobExecutionError) as exc_info:
        ai_image_handlers._verify_and_scan_image(result)

    assert exc_info.value.code == "AI_IMAGE_OBJECT_KEY_INVALID"



@pytest.mark.parametrize(
    ("severity", "expected_passed"),
    [
        ("none", True),
        ("low", True),
        ("medium", True),
        ("high", False),
        ("critical", False),
        ("unrecognized", False),
    ],
)
def test_vision_inspection_fails_closed_for_high_or_unknown_severity(
    monkeypatch: pytest.MonkeyPatch,
    severity: str,
    expected_passed: bool,
) -> None:
    class FakeExecutor:
        async def inspect_image(self, request, *, provider_id):
            assert request.asset_object_key == "stores/store-1/generated/image.png"
            assert provider_id == "vision-provider"
            return VisionInspectResponse(
                model_id="vision-model",
                passed=True,
                findings=(
                    {
                        "severity": severity,
                        "revision_suggestion": "Revise the promotional visual",
                    },
                ),
            )

    class FakeClient:
        async def aclose(self) -> None:
            return None

    monkeypatch.setattr(
        ai_image_handlers,
        "render_published_prompt",
        lambda version, variables: ("system criteria", "user criteria"),
    )
    monkeypatch.setattr(
        ai_image_handlers,
        "_load_executor",
        lambda *args, **kwargs: (
            FakeExecutor(),
            FakeClient(),
            "vision-provider",
            "vision-model",
        ),
    )
    monkeypatch.setattr(
        ai_image_handlers,
        "validate_structured_output",
        lambda payload, schema: payload,
    )

    result = ai_image_handlers._vision_report(
        context=SimpleNamespace(attempt_id=uuid4()),
        task=SimpleNamespace(store_id=uuid4()),
        job=SimpleNamespace(id=uuid4(), idempotency_key="vision-test-job-key"),
        version=SimpleNamespace(output_schema_json={}),
        variables={},
        asset_object_key="stores/store-1/generated/image.png",
    )

    assert result["passed"] is expected_passed
    assert result["report"]["human_review_required"] is True
    assert result["report"]["overall_severity"] == (
        "high" if severity == "unrecognized" else severity
    )
    assert result["report"]["revision_suggestions"] == [
        "Revise the promotional visual"
    ]


def test_image_artifact_audit_refs_bind_each_provider_invocation() -> None:
    store_id, job_id, attempt_id = uuid4(), uuid4(), uuid4()
    text_prompt_id, image_prompt_id, vision_prompt_id = uuid4(), uuid4(), uuid4()
    invocations = [
        SimpleNamespace(
            id=uuid4(),
            capability="text",
            prompt_version_id=text_prompt_id,
        ),
        SimpleNamespace(
            id=uuid4(),
            capability="image",
            prompt_version_id=image_prompt_id,
        ),
        SimpleNamespace(
            id=uuid4(),
            capability="vision",
            prompt_version_id=vision_prompt_id,
        ),
    ]

    class FakeScalarResult:
        def all(self):
            return invocations

    class FakeSession:
        def scalars(self, statement):
            return FakeScalarResult()

    refs = ai_image_handlers._ai_invocation_source_refs(
        FakeSession(),
        store_id=store_id,
        job_id=job_id,
        attempt_id=attempt_id,
        prompt_capabilities=(
            (text_prompt_id, "text"),
            (image_prompt_id, "image"),
            (vision_prompt_id, "vision"),
        ),
    )

    assert [ref["capability"] for ref in refs] == ["text", "image", "vision"]
    assert [ref["id"] for ref in refs] == [
        str(invocation.id) for invocation in invocations
    ]


def test_image_artifact_audit_refs_fail_closed_when_invocation_is_missing() -> None:
    class FakeScalarResult:
        def all(self):
            return []

    class FakeSession:
        def scalars(self, statement):
            return FakeScalarResult()

    with pytest.raises(JobExecutionError) as exc_info:
        ai_image_handlers._ai_invocation_source_refs(
            FakeSession(),
            store_id=uuid4(),
            job_id=uuid4(),
            attempt_id=uuid4(),
            prompt_capabilities=((uuid4(), "image"),),
        )

    assert exc_info.value.code == "AI_IMAGE_INVOCATION_AUDIT_MISSING"
