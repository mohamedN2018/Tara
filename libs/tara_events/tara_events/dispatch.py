"""Event handler registry.

Services register handlers with ``@on_event("post.created")``; the worker
(``tara_events.worker``) dispatches incoming events to them. Import side-effect:
a service's handlers module must be imported for registration to happen (the
``consume_events`` command does this).
"""

from __future__ import annotations

from collections.abc import Callable

from .envelope import EventEnvelope

Handler = Callable[[EventEnvelope], None]
_HANDLERS: dict[str, list[Handler]] = {}


def on_event(event_type: str) -> Callable[[Handler], Handler]:
    """Register a handler for an event type (may register many per type)."""

    def decorator(fn: Handler) -> Handler:
        _HANDLERS.setdefault(event_type, []).append(fn)
        return fn

    return decorator


def handlers_for(event_type: str) -> list[Handler]:
    return list(_HANDLERS.get(event_type, []))


def registered_event_types() -> list[str]:
    return list(_HANDLERS.keys())


def clear_handlers() -> None:
    """Test hook."""
    _HANDLERS.clear()
