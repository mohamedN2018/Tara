"""Tara resilience primitives.

- idempotency: dedupe unsafe HTTP writes via the ``Idempotency-Key`` header.
- retry: exponential backoff + jitter for transient failures.
- circuit_breaker: stop hammering a failing dependency; degrade instead.

See docs/architecture/phase-0/02-service-boundaries.md §6.
"""

from .circuit_breaker import CircuitBreaker, CircuitOpenError
from .retry import retry

__all__ = ["CircuitBreaker", "CircuitOpenError", "retry", "__version__"]
__version__ = "0.1.0"
