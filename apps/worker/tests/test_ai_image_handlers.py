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

