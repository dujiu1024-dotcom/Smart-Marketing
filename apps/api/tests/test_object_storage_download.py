from __future__ import annotations

from io import BytesIO

import pytest

from store_operator import object_storage


class FakeObjectStorageClient:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.get_called = False

    def head_object(self, **_kwargs):
        return {"ContentLength": len(self.payload)}

    def get_object(self, **_kwargs):
        self.get_called = True
        return {"Body": BytesIO(self.payload)}


def test_download_object_bytes_reads_within_limit(monkeypatch) -> None:
    client = FakeObjectStorageClient(b"image-bytes")
    monkeypatch.setattr(object_storage, "_client", lambda: client)

    result = object_storage.download_object_bytes(
        object_key="stores/store-a/media/image.png",
        max_bytes=100,
    )

    assert result == b"image-bytes"
    assert client.get_called is True


def test_download_object_bytes_rejects_oversize_before_download(monkeypatch) -> None:
    client = FakeObjectStorageClient(b"image-bytes")
    monkeypatch.setattr(object_storage, "_client", lambda: client)

    with pytest.raises(ValueError, match="exceeds the channel upload size limit"):
        object_storage.download_object_bytes(
            object_key="stores/store-a/media/image.png",
            max_bytes=2,
        )

    assert client.get_called is False
