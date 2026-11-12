from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace
from typing import Any

import pytest

from store_operator.auth.errors import ApiError
from store_operator.channel_douyin_router import (
    _parse_douyin_unauthorize_event,
    _verify_douyin_webhook_signature,
    receive_douyin_webhook,
)
from store_operator.config import settings
from store_operator.models.channel_delivery import DouyinWebhookReceipt


class FakeRequest:
    def __init__(self, body: bytes, headers: dict[str, str] | None = None) -> None:
        self._body = body
        self.headers = headers or {}

    async def body(self) -> bytes:
        return self._body


class FakeScalars:
    def __init__(self, values: list[Any]) -> None:
        self._values = values

    def all(self) -> list[Any]:
        return self._values


class FakeSession:
    def __init__(self, accounts: list[Any] | None = None, existing: Any = None) -> None:
        self.accounts = accounts or []
        self.existing = existing
        self.receipts: list[Any] = []
        self.committed = False
        self.rolled_back = False

    def scalar(self, _statement: Any) -> Any:
        return self.existing

    def add(self, value: Any) -> None:
        self.receipts.append(value)

    def flush(self) -> None:
        return None

    def scalars(self, _statement: Any) -> FakeScalars:
        return FakeScalars(self.accounts)

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True


def signed_request(payload: dict[str, Any], *, message_id: str = "msg-001") -> FakeRequest:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    signature = hashlib.sha1(b"webhook-secret" + body).hexdigest()
    return FakeRequest(body, {"X-Douyin-Signature": signature, "Msg-Id": message_id})


def test_webhook_signature_uses_client_secret_prefix_and_raw_body() -> None:
    body = b'{"event":"unauthorize"}'
    signature = hashlib.sha1(b"secret" + body).hexdigest()

    assert _verify_douyin_webhook_signature(
        raw_body=body, signature=signature, client_secret="secret"
    )
    assert not _verify_douyin_webhook_signature(
        raw_body=body + b" ", signature=signature, client_secret="secret"
    )
    assert not _verify_douyin_webhook_signature(
        raw_body=body, signature="", client_secret="secret"
    )


def test_parse_unauthorize_event_validates_account_and_scopes() -> None:
    open_id, scopes = _parse_douyin_unauthorize_event(
        {
            "from_user_id": "open-123",
            "content": {"scopes": ["video.create", "user_info", "video.create"]},
        }
    )

    assert open_id == "open-123"
    assert scopes == ["user_info", "video.create"]

    with pytest.raises(ApiError):
        _parse_douyin_unauthorize_event({"from_user_id": "", "content": {"scopes": []}})
    with pytest.raises(ApiError):
        _parse_douyin_unauthorize_event({"from_user_id": "open-123", "content": {"scopes": "bad"}})


def test_webhook_verification_echoes_challenge_without_token_or_database_access() -> None:
    import asyncio

    request = FakeRequest(
        json.dumps({"event": "verify_webhook", "content": {"challenge": 98765}}).encode()
    )
    response = asyncio.run(receive_douyin_webhook(request, FakeSession()))

    assert response.status_code == 200
    assert json.loads(response.body) == {"challenge": 98765}


def test_unauthorize_webhook_revokes_matching_accounts_and_persists_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    monkeypatch.setattr(settings, "douyin_client_key", "test-client")
    monkeypatch.setattr(settings, "douyin_client_secret", "webhook-secret")
    account = SimpleNamespace(
        status="active",
        granted_scopes=["user_info", "video.create", "video.list"],
        revoked_at=None,
        updated_at=None,
    )
    db = FakeSession(accounts=[account])
    request = signed_request(
        {
            "client_key": "test-client",
            "event": "unauthorize",
            "from_user_id": "open-123",
            "content": {"scopes": ["user_info", "video.create", "video.list"]},
        }
    )

    response = asyncio.run(receive_douyin_webhook(request, db))

    assert response.status_code == 200
    assert json.loads(response.body) == {"code": 0}
    assert account.status == "revoked"
    assert account.granted_scopes == []
    assert account.revoked_at is not None
    assert db.committed
    receipt = db.receipts[0]
    assert receipt.external_user_id_hash == hashlib.sha256(b"open-123").hexdigest()
    assert receipt.external_user_id_hash != "open-123"
    assert receipt.affected_account_count == 1
    assert receipt.message_id == "msg-001"


def test_duplicate_message_id_is_acknowledged_without_reprocessing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    monkeypatch.setattr(settings, "douyin_client_key", "test-client")
    monkeypatch.setattr(settings, "douyin_client_secret", "webhook-secret")
    db = FakeSession(existing="existing-receipt")
    request = signed_request(
        {
            "client_key": "test-client",
            "event": "unauthorize",
            "from_user_id": "open-123",
            "content": {"scopes": []},
        }
    )

    response = asyncio.run(receive_douyin_webhook(request, db))

    assert json.loads(response.body) == {"code": 0}
    assert db.receipts == []
    assert not db.committed


def test_invalid_webhook_signature_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    monkeypatch.setattr(settings, "douyin_client_key", "test-client")
    monkeypatch.setattr(settings, "douyin_client_secret", "webhook-secret")
    request = FakeRequest(
        b'{"client_key":"test-client","event":"unauthorize","from_user_id":"open-123","content":{"scopes":[]}}',
        {"X-Douyin-Signature": "invalid", "Msg-Id": "msg-001"},
    )

    with pytest.raises(ApiError):
        asyncio.run(receive_douyin_webhook(request, FakeSession()))


def test_webhook_receipt_has_message_id_deduplication_constraint() -> None:
    names = {constraint.name for constraint in DouyinWebhookReceipt.__table__.constraints}

    assert "uq_douyin_webhook_receipts_provider_message_id" in names
