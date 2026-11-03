"""Default API rate limits, per account (or per IP for anonymous callers)."""

from __future__ import annotations

from rest_framework.throttling import SimpleRateThrottle


class _AccountThrottle(SimpleRateThrottle):
    def get_cache_key(self, request, view):
        user = request.user
        ident = (
            getattr(user, "account_id", None)
            if getattr(user, "is_authenticated", False)
            else self.get_ident(request)
        )
        return self.cache_format % {"scope": self.scope, "ident": ident}


class ReadThrottle(_AccountThrottle):
    scope = "tara_read"

    def allow_request(self, request, view):
        if request.method not in ("GET", "HEAD"):
            return True
        return super().allow_request(request, view)


class WriteThrottle(_AccountThrottle):
    scope = "tara_write"

    def allow_request(self, request, view):
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return True
        return super().allow_request(request, view)
