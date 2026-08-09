"""Opt-in OpenTelemetry instrumentation for the canonical FastAPI app."""

from __future__ import annotations

import os
from urllib.parse import urlparse

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Tracer

_TRACER_ATTRIBUTE = "_dor_otel_tracer"


def _validate_endpoint(endpoint: str) -> str:
    parsed = urlparse(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("OTLP endpoint must be an absolute http(s) URL")
    return endpoint


def configure_tracing(
    app: FastAPI,
    *,
    service_name: str = "dor-api",
    endpoint: str | None = None,
) -> Tracer:
    """Instrument ``app`` once when an OTLP endpoint is configured.

    Tracing is optional for local and test execution.  Supplying an invalid
    endpoint fails closed instead of silently disabling telemetry.
    """
    configured = getattr(app.state, _TRACER_ATTRIBUTE, None)
    if configured is not None:
        return configured

    configured_endpoint = endpoint or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not configured_endpoint:
        return trace.get_tracer(service_name)

    configured_endpoint = _validate_endpoint(configured_endpoint)
    resource = Resource.create(
        {
            "service.name": service_name,
            "service.version": "1.0.0",
        }
    )
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(
        endpoint=configured_endpoint,
        insecure=urlparse(configured_endpoint).scheme == "http",
    )
    provider.add_span_processor(BatchSpanProcessor(exporter))
    FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)
    app.router.add_event_handler("shutdown", provider.shutdown)

    tracer = provider.get_tracer(__name__)
    setattr(app.state, _TRACER_ATTRIBUTE, tracer)
    return tracer
