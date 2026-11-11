"""Structured logging setup and recursive sensitive-field redaction."""

import logging
from collections.abc import Mapping, MutableMapping
from typing import Any, cast

import structlog

_SENSITIVE_KEY_FRAGMENTS = (
    "password",
    "token",
    "secret",
    "authorization",
    "cookie",
    "api_key",
    "apikey",
    "credential",
    "database_url",
    "private_key",
)


def redact_sensitive_fields(
    logger: Any,
    method_name: str,
    event_dict: MutableMapping[str, Any],
) -> MutableMapping[str, Any]:
    """Redact sensitive values recursively before JSON serialization."""

    def redact(value: Any) -> Any:
        if isinstance(value, Mapping):
            cleaned: dict[str, Any] = {}
            for key, nested in value.items():
                normalized = str(key).lower().replace("-", "_")
                if any(fragment in normalized for fragment in _SENSITIVE_KEY_FRAGMENTS):
                    cleaned[str(key)] = "[REDACTED]"
                else:
                    cleaned[str(key)] = redact(nested)
            return cleaned
        if isinstance(value, list):
            return [redact(item) for item in value]
        if isinstance(value, tuple):
            return [redact(item) for item in value]
        return value

    return cast(MutableMapping[str, Any], redact(event_dict))


def configure_logging() -> None:
    """Configure JSON logs with redaction applied before serialization."""
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.add_log_level,
            redact_sensitive_fields,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

