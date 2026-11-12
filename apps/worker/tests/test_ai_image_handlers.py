import hashlib
from types import SimpleNamespace
from uuid import uuid4
from types import SimpleNamespace
from uuid import uuid4

import pytest
from store_operator.ai_gateway.schemas import ImageGenerateResponse, VisionInspectResponse, VisionInspectResponse

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
        job=SimpleNamespace(id=uuid4()),
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
