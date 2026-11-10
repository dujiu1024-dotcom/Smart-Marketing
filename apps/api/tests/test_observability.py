from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from store_operator.observability import build_tracer_provider, redact_sensitive_fields


def test_redact_sensitive_fields_recursively() -> None:
    event = {
        "event": "request.received",
        "authorization": "Bearer top-secret",
        "profile": {
            "password": "pw-value",
            "refresh_token": "refresh-value",
            "nested": [{"api-key": "key-value", "label": "safe"}],
        },
        "safe_value": "visible",
    }

    result = redact_sensitive_fields(None, "info", event)

    assert result["authorization"] == "[REDACTED]"
    assert result["profile"]["password"] == "[REDACTED]"
    assert result["profile"]["refresh_token"] == "[REDACTED]"
    assert result["profile"]["nested"][0]["api-key"] == "[REDACTED]"
    assert result["profile"]["nested"][0]["label"] == "safe"
    assert result["safe_value"] == "visible"


def test_tracer_provider_exports_finished_spans() -> None:
    exporter = InMemorySpanExporter()
    provider = build_tracer_provider(span_exporter=exporter)
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    with provider.get_tracer("observability-test").start_as_current_span("healthcheck") as span:
        span.set_attribute("test.outcome", "ok")

    provider.force_flush()
    finished = exporter.get_finished_spans()
    provider.shutdown()

    assert len(finished) == 1
    assert finished[0].name == "healthcheck"
    assert finished[0].attributes["test.outcome"] == "ok"
