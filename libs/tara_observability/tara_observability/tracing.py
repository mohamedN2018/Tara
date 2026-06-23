"""Optional OpenTelemetry tracing.

A no-op unless ``OTEL_ENABLED`` is truthy AND the otel extras are installed, so
a missing collector or package never breaks a service. Call ``setup_tracing``
from settings/AppConfig.ready().
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger("tara.observability.tracing")


def setup_tracing(service_name: str) -> bool:
    """Wire OTLP tracing if enabled. Returns True if tracing was activated."""
    if os.getenv("OTEL_ENABLED", "false").lower() not in ("1", "true", "yes"):
        return False
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        logger.warning("OTEL_ENABLED but opentelemetry packages not installed; skipping.")
        return False

    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4317")
    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)

    try:
        from opentelemetry.instrumentation.django import DjangoInstrumentor

        DjangoInstrumentor().instrument()
    except ImportError:
        pass

    logger.info("OpenTelemetry tracing enabled", extra={"endpoint": endpoint})
    return True
