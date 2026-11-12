from __future__ import annotations

import struct

import pytest

from store_operator_worker.asset_scanner import (
    AssetScannerUnavailable,
    scan_bytes,
)


class FakeSocket:
    def __init__(self, response: bytes) -> None:
        self.response = response
        self.sent: list[bytes] = []
        self.timeout: int | None = None
        self.closed = False

    def __enter__(self) -> FakeSocket:
        return self

    def __exit__(self, *_args: object) -> None:
        self.closed = True

    def settimeout(self, value: int) -> None:
        self.timeout = value

    def sendall(self, data: bytes) -> None:
        self.sent.append(data)

    def recv(self, _size: int) -> bytes:
        response = self.response
        self.response = b""
        return response


def test_scan_bytes_streams_bounded_chunks_and_accepts_clean_verdict(monkeypatch) -> None:
    fake = FakeSocket(b"stream: OK\0")
    monkeypatch.setattr(
        "store_operator_worker.asset_scanner.socket.create_connection",
        lambda address, timeout: fake,
    )

    result = scan_bytes(
        b"abcdef",
        host="clamav",
        port=3310,
        timeout_seconds=20,
        chunk_size=3,
    )

    assert result.clean
    assert result.signature_name is None
    assert fake.sent == [
        b"zINSTREAM\0",
        struct.pack("!I", 3),
        b"abc",
        struct.pack("!I", 3),
        b"def",
        struct.pack("!I", 0),
    ]
    assert fake.timeout == 20
    assert fake.closed


def test_scan_bytes_returns_malware_signature_without_exposing_file_content(monkeypatch) -> None:
    fake = FakeSocket(b"stream: Eicar-Test-Signature FOUND\0")
    monkeypatch.setattr(
        "store_operator_worker.asset_scanner.socket.create_connection",
        lambda address, timeout: fake,
    )

    result = scan_bytes(
        b"sample",
        host="clamav",
        port=3310,
        timeout_seconds=20,
    )

    assert not result.clean
    assert result.signature_name == "Eicar-Test-Signature"


@pytest.mark.parametrize(
    "response",
    [
        b"",
        b"stream: OK",
        b"stream: maybe\0",
        b"stream: ERROR\0",
    ],
)
def test_scan_bytes_fails_closed_for_incomplete_or_unknown_verdict(monkeypatch, response) -> None:
    fake = FakeSocket(response)
    monkeypatch.setattr(
        "store_operator_worker.asset_scanner.socket.create_connection",
        lambda address, timeout: fake,
    )

    with pytest.raises(AssetScannerUnavailable):
        scan_bytes(b"sample", host="clamav", port=3310, timeout_seconds=20)


def test_scan_bytes_wraps_scanner_connection_failure(monkeypatch) -> None:
    def unavailable(*_args, **_kwargs):
        raise ConnectionRefusedError("internal detail")

    monkeypatch.setattr(
        "store_operator_worker.asset_scanner.socket.create_connection",
        unavailable,
    )

    with pytest.raises(AssetScannerUnavailable, match="unavailable"):
        scan_bytes(b"sample", host="clamav", port=3310, timeout_seconds=20)
