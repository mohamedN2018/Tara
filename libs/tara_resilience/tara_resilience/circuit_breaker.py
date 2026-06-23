"""A minimal in-process circuit breaker.

States: CLOSED (normal) → OPEN (failing; calls short-circuit) → HALF_OPEN
(probe one call). Used to wrap synchronous cross-service reads so a failing
dependency degrades fast instead of piling up latency. See ADR-008 / doc 02 §6.

For multi-process sharing, back the counters with Redis later; the interface
stays the same.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


class CircuitOpenError(Exception):
    """Raised when the breaker is OPEN and the call is short-circuited."""


class CircuitBreaker:
    def __init__(
        self,
        *,
        name: str = "default",
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._clock = clock
        self._lock = threading.Lock()
        self._failures = 0
        self._state = "closed"
        self._opened_at = 0.0

    @property
    def state(self) -> str:
        return self._state

    def _can_attempt(self) -> bool:
        if self._state == "closed":
            return True
        if self._state == "open":
            if (self._clock() - self._opened_at) >= self.recovery_timeout:
                self._state = "half_open"
                return True
            return False
        return True  # half_open: allow a single probe

    def _on_success(self) -> None:
        self._failures = 0
        self._state = "closed"

    def _on_failure(self) -> None:
        self._failures += 1
        if self._failures >= self.failure_threshold or self._state == "half_open":
            self._state = "open"
            self._opened_at = self._clock()

    def call(self, func: Callable[..., T], *args, **kwargs) -> T:
        """Run ``func`` through the breaker. Raises CircuitOpenError if open."""
        with self._lock:
            if not self._can_attempt():
                raise CircuitOpenError(f"circuit '{self.name}' is open")
        try:
            result = func(*args, **kwargs)
        except Exception:
            with self._lock:
                self._on_failure()
            raise
        with self._lock:
            self._on_success()
        return result
