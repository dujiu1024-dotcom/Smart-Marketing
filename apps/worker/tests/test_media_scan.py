from __future__ import annotations

import socket
import struct
import threading
from contextlib import closing
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import uuid4

import pytest
from store_operator.models import MediaAsset, UploadIntent

from store_operator_worker.media_scanner import (
    ClamAvError,
    MalwareDetected,
    image_dimensions,
    scan_with_clamd,
    validate_image_dimensions,
)


def png_bytes(width: int = 640, height: int = 480) -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", 13)
        + b"IHDR"
        + struct.pack(">II", width, height)
        + b"\x08\x06\x00\x00\x00"
        + b"\x00\x00\x00\x00IEND\xaeB\x60\x82"
    )


def clamd_server(response: bytes) -> tuple[socket.socket, threading.Thread, list[bytes]]:
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    received: list[bytes] = []

    def serve() -> None:
        connection, _ = server.accept()
        with closing(connection):
            command = connection.recv(10)
            assert command == b"zINSTREAM\0"
            chunks = bytearray()
            while True:
                header = bytearray()
                while len(header) < 4:
                    header.extend(connection.recv(4 - len(header)))
                size = struct.unpack("!I", header)[0]
                if size == 0:
                    break
                payload = bytearray()
                while len(payload) < size:
                    payload.extend(connection.recv(size - len(payload)))
                chunks.extend(payload)
            received.append(bytes(chunks))
            connection.sendall(response)

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    return server, thread, received


def test_png_dimensions_and_pixel_safety() -> None:
    assert image_dimensions(png_bytes(), "image/png") == (640, 480)
    with pytest.raises(ValueError, match="pixel count"):
        validate_image_dimensions(8000, 8000)


def test_declared_mime_must_match_image_signature() -> None:
    with pytest.raises(ValueError, match="PNG MIME"):
        image_dimensions(b"not-an-image", "image/png")


def test_clamd_instream_protocol_accepts_clean_content() -> None:
    server, thread, received = clamd_server(b"stream: OK\0")
    try:
        scan_with_clamd(b"small-image", host="127.0.0.1", port=server.getsockname()[1])
    finally:
        server.close()
        thread.join(timeout=2)
    assert received == [b"small-image"]


def test_clamd_instream_protocol_rejects_malware() -> None:
    server, thread, _ = clamd_server(b"stream: Eicar-Test-Signature FOUND\0")
    try:
        with pytest.raises(MalwareDetected):
            scan_with_clamd(b"malware", host="127.0.0.1", port=server.getsockname()[1])
    finally:
        server.close()
        thread.join(timeout=2)


def test_clamd_indeterminate_response_fails_closed() -> None:
    server, thread, _ = clamd_server(b"stream: scan failed ERROR\0")
    try:
        with pytest.raises(ClamAvError):
            scan_with_clamd(b"image", host="127.0.0.1", port=server.getsockname()[1])
    finally:
        server.close()
        thread.join(timeout=2)


class FakeSession:
    def __init__(self, values):
        self.values = iter(values)

    def scalar(self, _statement):
        return next(self.values)


class FakeSessionFactory:
    def __init__(self, session):
        self.session = session

    def begin(self):
        from contextlib import contextmanager

        @contextmanager
        def transaction():
            yield self.session

        return transaction()


def test_quarantine_worker_marks_asset_ready_only_after_clean_scan(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://test:test@localhost/test")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    from store_operator_worker import tasks

    content = png_bytes()
    now = datetime.now(UTC)
    store_id = uuid4()
    user_id = uuid4()
    object_key = f"stores/{store_id}/quarantine/test.png"
    asset = MediaAsset(
        id=uuid4(), store_id=store_id, object_key=object_key, sha256=sha256(content).hexdigest(),
        mime_type="image/png", byte_size=len(content), asset_type="image",
        usage_rights_status="unknown", status="quarantined", version_no=1,
    )
    intent = UploadIntent(
        id=uuid4(), store_id=store_id, created_by_user_id=user_id, object_key=object_key,
        expected_mime_type="image/png", expected_byte_size=len(content),
        expected_sha256=sha256(content).hexdigest(), status="scanning",
        expires_at=now + timedelta(minutes=10),
    )
    session = FakeSession([asset, intent])
    monkeypatch.setattr(tasks, "SessionLocal", FakeSessionFactory(session))
    monkeypatch.setattr(tasks, "download_object_bytes", lambda **_kwargs: content)
    monkeypatch.setattr(tasks, "scan_with_clamd", lambda *_args, **_kwargs: None)

    assert tasks.scan_quarantined_assets(batch_size=1) == 1
    assert asset.status == "ready"
    assert (asset.width, asset.height) == (640, 480)
    assert intent.status == "completed"


def test_quarantine_worker_rejects_infected_upload(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://test:test@localhost/test")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    from store_operator_worker import tasks

    content = png_bytes()
    now = datetime.now(UTC)
    store_id = uuid4()
    user_id = uuid4()
    object_key = f"stores/{store_id}/quarantine/infected.png"
    digest = sha256(content).hexdigest()
    asset = MediaAsset(
        id=uuid4(), store_id=store_id, object_key=object_key, sha256=digest,
        mime_type="image/png", byte_size=len(content), asset_type="image",
        usage_rights_status="unknown", status="quarantined", version_no=1,
    )
    intent = UploadIntent(
        id=uuid4(), store_id=store_id, created_by_user_id=user_id, object_key=object_key,
        expected_mime_type="image/png", expected_byte_size=len(content),
        expected_sha256=digest, status="scanning", expires_at=now + timedelta(minutes=10),
    )
    monkeypatch.setattr(tasks, "SessionLocal", FakeSessionFactory(FakeSession([asset, intent])))
    monkeypatch.setattr(tasks, "download_object_bytes", lambda **_kwargs: content)

    def infected(*_args, **_kwargs):
        raise MalwareDetected("test detection")

    monkeypatch.setattr(tasks, "scan_with_clamd", infected)
    assert tasks.scan_quarantined_assets(batch_size=1) == 1
    assert asset.status == "rejected"
    assert intent.status == "rejected"
    assert intent.rejection_reason == "Uploaded media was rejected by malware scanning"


def test_expired_upload_intents_are_deleted_and_marked_expired(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://test:test@localhost/test")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    from store_operator_worker import tasks

    intent = UploadIntent(
        id=uuid4(),
        store_id=uuid4(),
        created_by_user_id=uuid4(),
        object_key="stores/test/quarantine/expired.png",
        expected_mime_type="image/png",
        expected_byte_size=128,
        expected_sha256="a" * 64,
        status="created",
        expires_at=datetime.now(UTC) - timedelta(minutes=10),
    )
    deleted: list[str] = []
    monkeypatch.setattr(
        tasks, "SessionLocal", FakeSessionFactory(FakeSession([intent, None]))
    )
    monkeypatch.setattr(tasks, "delete_object", lambda *, object_key: deleted.append(object_key))

    assert tasks.expire_upload_intents(batch_size=1) == 1
    assert intent.status == "expired"
    assert deleted == ["stores/test/quarantine/expired.png"]


def test_expired_upload_intent_storage_failure_is_retryable(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://test:test@localhost/test")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    from store_operator_worker import tasks

    intent = UploadIntent(
        id=uuid4(),
        store_id=uuid4(),
        created_by_user_id=uuid4(),
        object_key="stores/test/quarantine/retry.png",
        expected_mime_type="image/png",
        expected_byte_size=128,
        expected_sha256="b" * 64,
        status="created",
        expires_at=datetime.now(UTC) - timedelta(minutes=10),
    )
    monkeypatch.setattr(tasks, "SessionLocal", FakeSessionFactory(FakeSession([intent])))
    monkeypatch.setattr(
        tasks,
        "delete_object",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("storage unavailable")),
    )

    with pytest.raises(RuntimeError, match="storage unavailable"):
        tasks.expire_upload_intents(batch_size=1)
    assert intent.status == "created"
