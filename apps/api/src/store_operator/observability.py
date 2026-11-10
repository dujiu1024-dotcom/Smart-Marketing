"""Structured logging setup and recursive sensitive-field redaction."""

import logging
from collections.abc import Mapping
from typing import Any

import structlog
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor, SpanExporter

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
    event_dict: dict[str, Any],
) -> dict[str, Any]:
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

    return redact(event_dict)


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


def build_tracer_provider(
    endpoint: str | None = None,
    span_exporter: SpanExporter | None = None,
) -> TracerProvider:
    """Build a service-scoped provider with OTLP export when an endpoint is configured."""
    provider = TracerProvider(
        resource=Resource.create({"service.name": "store-operator-api"})
    )
    if span_exporter is not None:
        provider.add_span_processor(SimpleSpanProcessor(span_exporter))
    elif endpoint:
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint))
        )
    return provider


def configure_tracing(endpoint: str | None = None):
    """Configure process-wide tracing and return the API tracer."""
    provider = build_tracer_provider(endpoint=endpoint)
    trace.set_tracer_provider(provider)
    return trace.get_tracer("store_operator.api")
