"""Readiness: production never holds synthetic accounts (02 section 12.3, WP 2.9)."""

from __future__ import annotations

from django.conf import settings


def synthetic_registry_check() -> tuple[bool, str]:
    """Not ready while synthetic rows are refused here but the registry is non-empty.

    With ``INTEL_ACCEPT_SYNTHETIC=false`` (production) the table must be empty: a
    registered account there is either a seed run against the wrong stack or a
    leftover, and its behaviour would otherwise be indistinguishable from a user's.
    """
    if settings.INTEL_ACCEPT_SYNTHETIC:
        return True, "ok"
    from .models import SyntheticAccount

    if SyntheticAccount.objects.exists():
        return False, "intel_synthetic_account is not empty while INTEL_ACCEPT_SYNTHETIC=false"
    return True, "ok"


def clock_check() -> tuple[bool, str]:
    """Not ready while the test clock (WP 4b.15) is on outside development."""
    from . import clock

    if clock.misconfigured():
        return False, "INTEL_TEST_CLOCK_ENABLED is true outside development"
    return True, "ok"
