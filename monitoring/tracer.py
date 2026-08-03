# monitoring/tracer.py
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.resources import Resource
from opentelemetry.trace import Status, StatusCode

# Opsæt OpenTelemetry
def configure_tracer(service_name: str = "dor") -> None:
    """Konfigurer OpenTelemetry Tracer."""
    # Opret en TracerProvider
    resource = Resource(attributes={
        "service.name": service_name,
        "service.version": "1.0.0"
    })
    provider = TracerProvider(resource=resource)

    # Opret en Span Processor (sender spans til OTLP endpoint)
    processor = BatchSpanProcessor(
        OTLPSpanExporter(endpoint="http://localhost:4317", insecure=True)
    )
    provider.add_span_processor(processor)

    # Sæt TracerProvider som global
    trace.set_tracer_provider(provider)

    # Instrumenter FastAPI
    FastAPIInstrumentor.instrument_app(app)

    return trace.get_tracer(__name__)

# Opret en global tracer
tracer = configure_tracer()
