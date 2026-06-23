"""Tara observability baseline.

- logging: structured JSON logs carrying request_id / trace_id, no secrets.
- tracing: optional OpenTelemetry setup (no-op unless OTEL_ENABLED).
- metrics: Prometheus helpers.

See docs/architecture/phase-0/06-infrastructure-plan.md §5.
"""

from .logging import bind_request_id, build_logging_config

__all__ = ["bind_request_id", "build_logging_config", "__version__"]
__version__ = "0.1.0"
