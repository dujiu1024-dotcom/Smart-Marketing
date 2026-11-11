from __future__ import annotations

import pytest

from store_operator.channel_douyin_router import DouyinPublishOperationRequest
from store_operator.models.channel_delivery import PublishOperation
from store_operator.object_storage import read_object_bytes


def test_douyin_publish_request_requires_package_fingerprint() -> None:
    request = DouyinPublishOperationRequest(
        publish_package_id="00000000-0000-0000-0000-000000000001",
        publish_package_item_id="00000000-0000-0000-0000-000000000002",
        package_fingerprint="a" * 64,
    )

    assert request.package_fingerprint == "a" * 64


def test_douyin_publish_request_rejects_invalid_package_fingerprint() -> None:
    with pytest.raises(ValueError):
        DouyinPublishOperationRequest(
            publish_package_id="00000000-0000-0000-0000-000000000001",
            publish_package_item_id="00000000-0000-0000-0000-000000000002",
            package_fingerprint="not-a-sha256",
        )


def test_publish_operation_has_one_operation_per_frozen_package_item() -> None:
    constraint_names = {
        constraint.name for constraint in PublishOperation.__table__.constraints
    }

    assert "uq_publish_operations_package_item" in constraint_names


class FakeBody:
    def __init__(self, value: bytes) -> None:
        self.value = value
        self.closed = False

    def read(self, limit: int) -> bytes:
        return self.value[:limit]

    def close(self) -> None:
        self.closed = True


class FakeS3:
    def __init__(self, *, value: bytes, content_type: str = "image/png") -> None:
        self.body = FakeBody(value)
        self.content_type = content_type

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
        return {
            "Body": self.body,
            "ContentLength": len(self.body.value),
            "ContentType": self.content_type,
        }


def test_read_object_bytes_enforces_size_and_closes_body(monkeypatch) -> None:
    from store_operator import object_storage

    client = FakeS3(value=b"image-bytes")
    monkeypatch.setattr(object_storage, "_client", lambda: client)

    content, content_type = read_object_bytes(
        object_key="stores/store-1/image.png",
        max_bytes=64,
    )

    assert content == b"image-bytes"
    assert content_type == "image/png"
    assert client.body.closed is True


def test_read_object_bytes_rejects_oversized_object_and_closes_body(monkeypatch) -> None:
    from store_operator import object_storage

    client = FakeS3(value=b"oversized")
    monkeypatch.setattr(object_storage, "_client", lambda: client)

    with pytest.raises(ValueError, match="size limit"):
        read_object_bytes(
            object_key="stores/store-1/image.png",
            max_bytes=4,
        )

    assert client.body.closed is True
