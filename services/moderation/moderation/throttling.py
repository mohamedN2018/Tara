"""Per-account limit on filing reports, on top of the default write limit."""

from __future__ import annotations

from django.conf import settings
from rest_framework.throttling import SimpleRateThrottle


class ReportThrottle(SimpleRateThrottle):
    scope = "moderation_report"

    def get_rate(self) -> str:
        # Read at request time, so the setting can change without a reload.
        return settings.MODERATION_REPORT_RATE

    def get_cache_key(self, request, view) -> str:
        return self.cache_format % {"scope": self.scope, "ident": request.user.account_id}
