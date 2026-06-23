"""Retry with exponential backoff + full jitter.

For transient failures (broker hiccup, brief network blip). Do NOT wrap
non-idempotent operations unless they're guarded by an idempotency key.
"""

from __future__ import annotations

import functools
import logging
import random
import time
from collections.abc import Callable
from typing import TypeVar

logger = logging.getLogger("tara.resilience.retry")

T = TypeVar("T")


def retry(
    *,
    attempts: int = 5,
    base_delay: float = 0.2,
    max_delay: float = 10.0,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
    sleep: Callable[[float], None] = time.sleep,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator: retry on the given exceptions with exponential backoff + jitter."""

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> T:
            last_exc: BaseException | None = None
            for attempt in range(1, attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:  # noqa: PERF203
                    last_exc = exc
                    if attempt == attempts:
                        break
                    # full jitter: random between 0 and capped exponential
                    cap = min(max_delay, base_delay * (2 ** (attempt - 1)))
                    delay = random.uniform(0, cap)  # noqa: S311 - jitter, not crypto
                    logger.warning(
                        "retrying after failure",
                        extra={"func": func.__name__, "attempt": attempt, "delay": round(delay, 3)},
                    )
                    sleep(delay)
            assert last_exc is not None
            raise last_exc

        return wrapper

    return decorator
