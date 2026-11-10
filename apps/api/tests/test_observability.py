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

    with provider.get_tracer("observability-test").start_as_current_span("healthcheck") as span:
        span.set_attribute("test.outcome", "ok")

    provider.force_flush()
    finished = exporter.get_finished_spans()
    provider.shutdown()

    assert len(finished) == 1
    assert finished[0].name == "healthcheck"
    assert finished[0].attributes["test.outcome"] == "ok"

def test_otlp_exporter_posts_spans_to_configured_collector() -> None:
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Event, Thread

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
    provider = build_tracer_provider(
        endpoint=f"http://127.0.0.1:{server.server_port}/v1/traces"
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
