"""Login throttling keyed on the targeted account (QTech's LoginTargetThrottle).

The per-IP ``auth_login`` scope limits one attacker's machine. This limits the
attempts against one email however many IPs they come from (a botnet or proxy
pool). The failure lockout in ``services.login`` still applies on top: it counts
wrong passwords over 15 minutes, this counts every attempt over a short window.
"""

from __future__ import annotations

import hashlib

from rest_framework.throttling import SimpleRateThrottle


def email_ident(raw: object) -> str | None:
    """Normalised, hashed email, so raw addresses never become cache keys."""
    email = raw.strip().lower() if isinstance(raw, str) else ""
    if not email:
        return None
    return hashlib.sha256(email.encode()).hexdigest()


class LoginTargetThrottle(SimpleRateThrottle):
    """Per targeted email. A fixed scope on purpose: ScopedRateThrottle would
    read ``view.throttle_scope`` (``auth_login``) and silently use the per-IP rate."""

    scope = "auth_login_target"

    def get_rate(self):
        # Read the rate per request (not at import) so settings overrides apply.
        from rest_framework.settings import api_settings

        return api_settings.DEFAULT_THROTTLE_RATES.get(self.scope)

    def get_cache_key(self, request, view):
        data = request.data if hasattr(request.data, "get") else {}
        ident = email_ident(data.get("email"))
        if ident is None:
            return None  # nothing to key on; the per-IP throttle still applies
        return self.cache_format % {"scope": self.scope, "ident": ident}
