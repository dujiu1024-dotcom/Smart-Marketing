"""JSON worker logs with correlation fields and recursive secret redaction."""

from __future__ import annotations

import json
import logging
import os
import socket
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

_SENSITIVE_KEY_FRAGMENTS = (
    "password",
    "token",
    "secret",
    "authorization",
    "cookie",
    "api_key",
    "apikey",
    "credential",
    "private_key",
    "database_url",
)

_STANDARD_RECORD_FIELDS = frozenset(
    set(logging.makeLogRecord({}).__dict__)
    | {"message", "asctime", "taskName"}
)


def _redact(value: Any, key: str = "") -> Any:
    normalized = key.lower().replace("-", "_")
    if any(fragment in normalized for fragment in _SENSITIVE_KEY_FRAGMENTS):
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return {
            str(child_key): _redact(child_value, str(child_key))
            for child_key, child_value in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    return value


class JsonRedactingFormatter(logging.Formatter):
    """Emit one JSON object per record; never serialize known secret fields."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "event": record.getMessage(),
            "service": "store-operator-worker",
            "worker_id": getattr(
                record,
                "worker_id",
                os.environ.get("WORKER_ID", f"{socket.gethostname()}:{os.getpid()}"),
            ),
        }
        extras = {
            key: value
            for key, value in record.__dict__.items()
            if key not in _STANDARD_RECORD_FIELDS and not key.startswith("_")
        }
        if "job_id" in extras:
            payload["correlation_id"] = str(extras["job_id"])
        payload.update(_redact(extras))
        if record.exc_info and record.exc_info[1] is not None:
            payload["error_type"] = type(record.exc_info[1]).__name__
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_worker_logging() -> None:
    """Install a root JSON handler once; preserve Celery's own logger hierarchy."""
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if any(getattr(handler, "_store_operator_json", False) for handler in root.handlers):
        return
    handler = logging.StreamHandler()
    handler.setFormatter(JsonRedactingFormatter())
    handler._store_operator_json = True  # type: ignore[attr-defined]
    root.addHandler(handler)
