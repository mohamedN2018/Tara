"""Login throttling keyed on the targeted account (QTech's LoginTargetThrottle).

The per-IP ``auth_login`` scope limits one attacker's machine. This limits the
attempts against one email however many IPs they come from (a botnet or proxy
pool). The failure lockout in ``services.login`` still applies on top: it counts
wrong passwords over 15 minutes, this counts every attempt over a short window.
"""

from __future__ import annotations

import hashlib

from rest_framework.throttling import SimpleRateThrottle

from .login_identifier import normalise


def email_ident(raw: object) -> str | None:
    """Normalised, hashed sign-in identifier (email or username), so raw
    addresses never become cache keys. Normalised as ``services.login`` does."""
    email = normalise(raw)
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
        # The same field services.login signs in with: identifier first (5.6).
        ident = email_ident(data.get("identifier") or data.get("email"))
        if ident is None:
            return None  # nothing to key on; the per-IP throttle still applies
        return self.cache_format % {"scope": self.scope, "ident": ident}
