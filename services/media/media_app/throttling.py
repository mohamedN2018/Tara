"""The batch lookups' own rate limit, per account, apart from the read/write
limits: one page asks for up to ``MAX_BATCH_IDS`` media per call."""

from __future__ import annotations

from rest_framework.throttling import SimpleRateThrottle


class ResolveThrottle(SimpleRateThrottle):
    scope = "media_resolve"

    def get_cache_key(self, request, view):
        user = request.user
        ident = (
            getattr(user, "account_id", None)
            if getattr(user, "is_authenticated", False)
            else self.get_ident(request)
        )
        return self.cache_format % {"scope": self.scope, "ident": ident}
