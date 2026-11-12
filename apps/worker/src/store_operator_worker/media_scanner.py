from __future__ import annotations

import socket
import struct


class ClamAvError(RuntimeError):
    """The malware scanner is unavailable or returned an indeterminate result."""


class MalwareDetected(RuntimeError):
    """ClamAV positively identified malicious content."""


def image_dimensions(data: bytes, mime_type: str) -> tuple[int, int]:
    """Read dimensions from supported image headers without decoding untrusted pixels."""
    if mime_type == "image/png":
        if len(data) < 33 or not data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("Image bytes do not match the declared PNG MIME type")
        if data[12:16] != b"IHDR":
            raise ValueError("PNG is missing its IHDR chunk")
        width, height = struct.unpack(">II", data[16:24])
        if not data.endswith(b"IEND\xaeB\x60\x82"):
            raise ValueError("PNG end marker is missing")
        return width, height

    if mime_type == "image/jpeg":
        if len(data) < 4 or not data.startswith(b"\xff\xd8") or not data.endswith(b"\xff\xd9"):
            raise ValueError("Image bytes do not match the declared JPEG MIME type")
        offset = 2
        sof_markers = {
            0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
            0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF,
        }
        while offset + 4 <= len(data) - 2:
            if data[offset] != 0xFF:
                offset += 1
                continue
            while offset < len(data) and data[offset] == 0xFF:
                offset += 1
            if offset >= len(data):
                break
            marker = data[offset]
            offset += 1
            if marker in {0xD8, 0xD9} or 0xD0 <= marker <= 0xD7 or marker == 0x01:
                continue
            if offset + 2 > len(data):
                break
            segment_length = struct.unpack(">H", data[offset : offset + 2])[0]
            if segment_length < 2 or offset + segment_length > len(data):
                raise ValueError("JPEG segment length is invalid")
            if marker in sof_markers:
                if segment_length < 7:
                    raise ValueError("JPEG frame header is invalid")
                height, width = struct.unpack(">HH", data[offset + 3 : offset + 7])
                return width, height
            offset += segment_length
        raise ValueError("JPEG frame dimensions could not be verified")

    if mime_type == "image/webp":
        if len(data) < 30 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
            raise ValueError("Image bytes do not match the declared WebP MIME type")
        riff_size = struct.unpack("<I", data[4:8])[0]
        if riff_size + 8 != len(data):
            raise ValueError("WebP container length is invalid")
        offset = 12
        while offset + 8 <= len(data):
            chunk_type = data[offset : offset + 4]
            chunk_size = struct.unpack("<I", data[offset + 4 : offset + 8])[0]
            start = offset + 8
            end = start + chunk_size
            if end > len(data):
                raise ValueError("WebP chunk length is invalid")
            payload = data[start:end]
            if chunk_type == b"VP8X" and len(payload) >= 10:
                width = 1 + int.from_bytes(payload[4:7], "little")
                height = 1 + int.from_bytes(payload[7:10], "little")
                return width, height
            if chunk_type == b"VP8 " and len(payload) >= 10 and payload[3:6] == b"\x9d\x01\x2a":
                width = int.from_bytes(payload[6:8], "little") & 0x3FFF
                height = int.from_bytes(payload[8:10], "little") & 0x3FFF
                return width, height
            if chunk_type == b"VP8L" and len(payload) >= 5 and payload[0] == 0x2F:
                bits = int.from_bytes(payload[1:5], "little")
                width = 1 + (bits & 0x3FFF)
                height = 1 + ((bits >> 14) & 0x3FFF)
                return width, height
            offset = end + (chunk_size & 1)
        raise ValueError("WebP image dimensions could not be verified")

    raise ValueError("Unsupported image MIME type")


def validate_image_dimensions(width: int, height: int) -> None:
    if width <= 0 or height <= 0 or width > 8000 or height > 8000:
        raise ValueError("Image dimensions are outside the supported range")
    if width * height > 40_000_000:
        raise ValueError("Image pixel count exceeds the safety limit")


def scan_with_clamd(
    data: bytes,
    *,
    host: str,
    port: int = 3310,
    timeout_seconds: float = 30.0,
) -> None:
    """Stream bytes to clamd using INSTREAM; fail closed on every uncertain response."""
    if not data:
        raise ValueError("Cannot scan an empty file")
    try:
        with socket.create_connection((host, port), timeout=timeout_seconds) as connection:
            connection.settimeout(timeout_seconds)
            connection.sendall(b"zINSTREAM\0")
            for offset in range(0, len(data), 1024 * 1024):
                chunk = data[offset : offset + 1024 * 1024]
                connection.sendall(struct.pack("!I", len(chunk)))
                connection.sendall(chunk)
            connection.sendall(struct.pack("!I", 0))
            response = bytearray()
            while len(response) < 4096:
                chunk = connection.recv(1024)
                if not chunk:
                    break
                response.extend(chunk)
                if b"\0" in chunk:
                    break
    except OSError as exc:
        raise ClamAvError("ClamAV scan service is unavailable") from exc

    result = bytes(response).split(b"\0", 1)[0].decode("utf-8", errors="replace")
    if result.endswith(" OK"):
        return
    if result.endswith(" FOUND"):
        raise MalwareDetected("ClamAV detected malicious content")
    raise ClamAvError("ClamAV returned an indeterminate scan result")
