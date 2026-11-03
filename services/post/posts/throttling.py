"""Per-account limit on reporting posts and comments, on top of the default write limit."""

from __future__ import annotations

from django.conf import settings
from rest_framework.throttling import SimpleRateThrottle


class ReportThrottle(SimpleRateThrottle):
    """One bucket for post and comment reports: each report can open a case."""

    scope = "post_report"

    def get_rate(self) -> str:
        # Read at request time, so the setting can change without a reload.
        return settings.POST_REPORT_RATE

    def get_cache_key(self, request, view) -> str:
        return self.cache_format % {"scope": self.scope, "ident": request.user.account_id}
