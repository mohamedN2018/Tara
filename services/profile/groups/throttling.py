"""Per-account limit on group reports, on top of the default write limit."""

from __future__ import annotations

from django.conf import settings
from rest_framework.throttling import SimpleRateThrottle


class GroupReportThrottle(SimpleRateThrottle):
    """Each report can open a moderation case."""

    scope = "group_report"

    def get_rate(self) -> str:
        return getattr(settings, "GROUP_REPORT_RATE", "20/hour")

    def get_cache_key(self, request, view) -> str:
        return self.cache_format % {"scope": self.scope, "ident": request.user.account_id}
