"""Per-address limit on the public handle check, on top of the default read limit."""

from __future__ import annotations

from django.conf import settings
from rest_framework.throttling import SimpleRateThrottle


class HandleCheckThrottle(SimpleRateThrottle):
    """The sign-up form asks while someone types (debounced), signed out.

    Keyed by client address (behind the trusted proxies), so the check can't be
    used to walk the whole handle space quickly.
    """

    scope = "handle_check"

    def get_rate(self) -> str:
        return getattr(settings, "PROFILE_HANDLE_CHECK_RATE", "30/min")

    def get_cache_key(self, request, view) -> str:
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}
