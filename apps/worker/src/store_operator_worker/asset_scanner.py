from __future__ import annotations

import socket
import struct
from dataclasses import dataclass


class AssetScannerUnavailable(RuntimeError):
    """The malware scanning service could not return a trustworthy verdict."""


@dataclass(frozen=True, slots=True)
class AssetScanResult:
    clean: bool
    signature_name: str | None = None


def scan_bytes(
    content: bytes,
    *,
    host: str,
    port: int,
    timeout_seconds: int,
    chunk_size: int = 1024 * 1024,
) -> AssetScanResult:
    if not content:
        raise ValueError("Asset content cannot be empty")
    if not host.strip() or not 1 <= port <= 65535 or timeout_seconds <= 0:
        raise ValueError("A valid scanner endpoint and timeout are required")
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")

    try:
        with socket.create_connection((host, port), timeout=timeout_seconds) as client:
            client.settimeout(timeout_seconds)
            client.sendall(b"zINSTREAM\0")
            for offset in range(0, len(content), chunk_size):
                chunk = content[offset : offset + chunk_size]
                client.sendall(struct.pack("!I", len(chunk)))
                client.sendall(chunk)
            client.sendall(struct.pack("!I", 0))

            response = bytearray()
            while len(response) <= 4096 and not response.endswith(b"\0"):
                part = client.recv(1024)
                if not part:
                    break
                response.extend(part)
    except (OSError, TimeoutError, socket.timeout) as exc:
        raise AssetScannerUnavailable("The malware scanner is unavailable") from exc

    if not response.endswith(b"\0"):
        raise AssetScannerUnavailable("The malware scanner returned an incomplete response")
    try:
        message = response[:-1].decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise AssetScannerUnavailable("The malware scanner returned an invalid response") from exc

    if message.endswith(": OK"):
        return AssetScanResult(clean=True)
    if message.endswith(" FOUND"):
        signature = message.rsplit(": ", 1)[-1][:-6].strip()
        return AssetScanResult(clean=False, signature_name=signature or "unknown")
    if message.endswith(" ERROR"):
        raise AssetScannerUnavailable("The malware scanner could not inspect the asset")
    raise AssetScannerUnavailable("The malware scanner returned an unknown verdict")
