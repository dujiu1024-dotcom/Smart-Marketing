"""OpenTelemetry tracing with optional OTLP/HTTP export."""

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.propagate import set_global_textmap
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor, SpanExporter
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator


def create_tracer_provider(
    service_name: str,
    *,
    exporter: SpanExporter | None = None,
    otlp_endpoint: str | None = None,
) -> TracerProvider:
    """Create a provider; inject an exporter in tests or configure OTLP in deployment."""
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    if exporter is not None:
        provider.add_span_processor(SimpleSpanProcessor(exporter))
    elif otlp_endpoint:
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint)))
    return provider


def configure_tracing(
    service_name: str,
    otlp_endpoint: str | None = None,
) -> TracerProvider:
    """Configure W3C trace-context propagation and optional OTLP export."""
    provider = create_tracer_provider(service_name, otlp_endpoint=otlp_endpoint)
    trace.set_tracer_provider(provider)
    set_global_textmap(TraceContextTextMapPropagator())
    return provider
