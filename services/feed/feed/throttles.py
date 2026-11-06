"""Per-account throttles of Home first pages and peeks (06 section 6.3; R3 WP 4b.8).

- ``feed_first_page``: ``session.rate.first_page_per_min`` first pages a minute
  (refresh storms), on top of nginx ``limit_req``. Later pages (a ``cursor``) are
  never throttled here: scrolling is not a refresh.
- ``feed_peek``: ``session.rate.peek_per_min`` peeks a minute (the "new posts" pill).

The rates are read from the **active Home config** on each request (decision 20), not
from settings. Over the rate the request gets 429 with ``Retry-After``.
"""

from __future__ import annotations

from intel import config
from rest_framework.throttling import SimpleRateThrottle


def _is_peek(request) -> bool:
    return request.query_params.get("peek") in ("1", "true")


class _ConfigRateThrottle(SimpleRateThrottle):
    key: str = ""

    def __init__(self):  # the rate is read per request, in allow_request
        pass

    def applies(self, request) -> bool:
        raise NotImplementedError

    def allow_request(self, request, view):
        if not self.applies(request):
            return True
        self.rate = f"{int(config.for_surface('home').get(self.key))}/min"
        self.num_requests, self.duration = self.parse_rate(self.rate)
        return super().allow_request(request, view)

    def get_cache_key(self, request, view):
        user = getattr(request, "user", None)
        account = getattr(user, "account_id", None)
        if not account:
            return None
        return self.cache_format % {"scope": self.scope, "ident": str(account)}


class FeedFirstPageThrottle(_ConfigRateThrottle):
    scope = "feed_first_page"
    key = "session.rate.first_page_per_min"

    def applies(self, request) -> bool:
        return request.query_params.get("cursor") is None and not _is_peek(request)


class FeedPeekThrottle(_ConfigRateThrottle):
    scope = "feed_peek"
    key = "session.rate.peek_per_min"

    def applies(self, request) -> bool:
        return _is_peek(request)
