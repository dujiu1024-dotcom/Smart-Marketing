from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Thread

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


def test_otlp_exporter_posts_spans_to_configured_collector() -> None:
    class CollectorHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            self.server.received_path = self.path
            self.server.received_body = self.rfile.read(int(self.headers["Content-Length"]))
            self.server.received_event.set()
            self.send_response(200)
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), CollectorHandler)
    server.received_event = Event()
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    provider = create_tracer_provider(
        "test-api",
        otlp_endpoint=f"http://127.0.0.1:{server.server_port}/v1/traces",
    )

    try:
        with provider.get_tracer("otlp-export-test").start_as_current_span("export-check"):
            pass
        assert provider.force_flush()
        assert server.received_event.wait(timeout=5)
        assert server.received_path == "/v1/traces"
        assert server.received_body
    finally:
        provider.shutdown()
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
