"""The test clock (07 WP 4b.15): ``X-Tara-Test-Now`` moves "now" for one request.

The repetition harness and the end-to-end tests need to see what a feed does an
hour, a day or a week later without waiting. The header is honoured **only when all
three hold**, and every other request uses the real clock:

1. ``INTEL_TEST_CLOCK_ENABLED`` is true (default false; Dokploy hard-codes false);
2. ``TARA_ENV`` is a development environment (``development`` or ``dev``);
3. the authenticated account is registered in ``intel_synthetic_account`` (a seed or
   test account), so a real user can never shift their own clock.

Both processes read it the same way, so ranking and telemetry share one clock:
``feed`` uses it as the ranking ``now`` of a Home first page, ``feed-signals`` as
the ``received_at`` of an ingested batch. ``manage.py check --deploy`` fails
(``intel.E005``) and ``/readyz/`` returns 503 when the flag is on outside development.

The header is an ISO 8601 time (a naive one is UTC) or epoch seconds.
"""

from __future__ import annotations

from datetime import UTC, datetime

from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from . import origin

HEADER = "X-Tara-Test-Now"
_META = "HTTP_X_TARA_TEST_NOW"
DEV_ENVS = frozenset({"development", "dev"})


def is_dev() -> bool:
    return str(getattr(settings, "TARA_ENV", "")).strip().lower() in DEV_ENVS


def enabled() -> bool:
    return bool(getattr(settings, "INTEL_TEST_CLOCK_ENABLED", False))


def misconfigured() -> bool:
    """The flag is on outside development (check ``intel.E005``, readiness 503)."""
    return enabled() and not is_dev()


def parse(raw: str) -> datetime | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    when = parse_datetime(raw)
    if when is None:
        try:
            when = datetime.fromtimestamp(float(raw), tz=UTC)
        except (OverflowError, ValueError, OSError):
            return None
    if timezone.is_naive(when):
        when = timezone.make_aware(when, UTC)
    return when


def request_now(request, account_id) -> datetime:
    """``now`` for this request: the header's time when every gate holds, else the
    real clock. The gates are checked in order, cheapest first; the registry lookup
    (one primary-key read, cached for positives) runs only when a header is sent."""
    real = timezone.now()
    raw = request.META.get(_META) if request is not None else None
    if not raw or not enabled() or not is_dev():
        return real
    if account_id is None or origin.label_for(account_id) is None:
        return real
    return parse(raw) or real
