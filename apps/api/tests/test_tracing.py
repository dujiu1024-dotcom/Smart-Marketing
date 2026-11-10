from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from store_operator.tracing import create_tracer_provider


def test_tracer_provider_exports_spans_to_configured_exporter() -> None:
    exporter = InMemorySpanExporter()
    provider = create_tracer_provider("test-api", exporter=exporter)

    with provider.get_tracer("test-suite").start_as_current_span("http.test") as span:
        span.set_attribute("request.id", "req-123")

    provider.force_flush()
    spans = exporter.get_finished_spans()

    assert len(spans) == 1
    assert spans[0].name == "http.test"
    assert spans[0].attributes["request.id"] == "req-123"
    assert spans[0].resource.attributes["service.name"] == "test-api"
    provider.shutdown()
