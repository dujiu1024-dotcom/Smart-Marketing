from __future__ import annotations

from contextlib import contextmanager
from hashlib import sha256
from types import SimpleNamespace
from uuid import uuid4

import pytest

from store_operator_worker.asset_scanner import AssetScannerUnavailable
from store_operator_worker.handlers import JobExecutionError


class ScanSession:
    def __init__(self, asset, intent) -> None:
        self.asset = asset
        self.intent = intent
        self.scalar_calls = 0

    def scalar(self, _statement):
        self.scalar_calls += 1
        return self.asset if self.scalar_calls % 2 else self.intent


class ScanSessionFactory:
    def __init__(self, asset, intent) -> None:
        self.session = ScanSession(asset, intent)

    @contextmanager
    def begin(self):
        yield self.session


def make_context(store_id):
    return SimpleNamespace(
        store_id=store_id,
        check_control=lambda: None,
        update_progress=lambda **_kwargs: None,
    )


def setup_handler(monkeypatch, *, clean=True):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://test:test@localhost/test")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    from store_operator.config import settings
    from store_operator_worker import tasks

    store_id = uuid4()
    asset_id = uuid4()
    intent_id = uuid4()
    content = b"verified-image-bytes"
    asset = SimpleNamespace(
        id=asset_id,
        store_id=store_id,
        object_key="stores/test/quarantine/image.png",
        sha256=sha256(content).hexdigest(),
        byte_size=len(content),
        status="quarantined",
        version_no=1,
    )
    intent = SimpleNamespace(
        id=intent_id,
        store_id=store_id,
        object_key=asset.object_key,
        status="scanning",
        rejection_reason=None,
    )
    factory = ScanSessionFactory(asset, intent)
    monkeypatch.setattr(tasks, "SessionLocal", factory)
    monkeypatch.setattr(tasks, "download_object_bytes", lambda **_kwargs: content)
    monkeypatch.setattr(settings, "asset_scanner_host", "clamav")
    monkeypatch.setattr(settings, "asset_scanner_port", 3310)
    monkeypatch.setattr(settings, "asset_scanner_timeout_seconds", 20)
    if clean:
        monkeypatch.setattr(
            tasks,
            "scan_bytes",
            lambda *_args, **_kwargs: SimpleNamespace(clean=True, signature_name=None),
        )
    else:
        monkeypatch.setattr(
            tasks,
            "scan_bytes",
            lambda *_args, **_kwargs: SimpleNamespace(
                clean=False, signature_name="Eicar-Test-Signature"
            ),
        )
    payload = {
        "schema_version": 1,
        "asset_id": str(asset_id),
        "upload_intent_id": str(intent_id),
    }
    return tasks, make_context(store_id), payload, asset, intent, factory


def test_asset_scan_promotes_verified_clean_file_to_ready(monkeypatch) -> None:
    tasks, context, payload, asset, intent, factory = setup_handler(monkeypatch)

    result = tasks.execute_asset_scan(context, payload)

    assert result == {"asset_id": str(asset.id), "status": "ready"}
    assert asset.status == "ready"
    assert asset.version_no == 2
    assert intent.status == "completed"
    assert intent.rejection_reason is None
    assert factory.session.scalar_calls == 4
    assert tasks.resolve_job_handler("store.asset.scan") is tasks.execute_asset_scan


def test_asset_scan_rejects_malware_and_keeps_asset_unavailable(monkeypatch) -> None:
    tasks, context, payload, asset, intent, _factory = setup_handler(monkeypatch, clean=False)

    result = tasks.execute_asset_scan(context, payload)

    assert result == {"asset_id": str(asset.id), "status": "rejected"}
    assert asset.status == "rejected"
    assert asset.version_no == 2
    assert intent.status == "rejected"
    assert intent.rejection_reason == "Malware detected by the file security scanner"


def test_asset_scan_retries_when_scanner_is_unavailable(monkeypatch) -> None:
    tasks, context, payload, asset, intent, _factory = setup_handler(monkeypatch)

    def unavailable(*_args, **_kwargs):
        raise AssetScannerUnavailable("private scanner detail")

    monkeypatch.setattr(tasks, "scan_bytes", unavailable)

    with pytest.raises(JobExecutionError) as error:
        tasks.execute_asset_scan(context, payload)

    assert error.value.code == "ASSET_SCANNER_UNAVAILABLE"
    assert error.value.retryable
    assert asset.status == "quarantined"
    assert intent.status == "scanning"


def test_asset_scan_fails_closed_when_stored_bytes_do_not_match_asset_hash(monkeypatch) -> None:
    tasks, context, payload, asset, intent, _factory = setup_handler(monkeypatch)
    monkeypatch.setattr(tasks, "download_object_bytes", lambda **_kwargs: b"different-content")

    result = tasks.execute_asset_scan(context, payload)

    assert result == {"asset_id": str(asset.id), "status": "rejected"}
    assert asset.status == "rejected"
    assert intent.status == "rejected"
    assert intent.rejection_reason == "Stored asset integrity verification failed"
