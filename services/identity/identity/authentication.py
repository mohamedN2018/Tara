"""Identity's own access-token check: the token's session must still be live.

Other services verify access tokens statelessly (tara_common.auth), so a token
outlives its session by up to ACCESS_TOKEN_TTL_SECONDS. Identity holds the
session table, so on its endpoints (email, password, Google link, sessions,
phone) a signed-out, revoked or password-changed session stops working at
once, at the cost of one primary-key lookup.
"""

from __future__ import annotations

import uuid

from rest_framework import exceptions

from tara_common.auth import JWTAuthentication


class SessionJWTAuthentication(JWTAuthentication):
    def authenticate(self, request):
        result = super().authenticate(request)
        if result is None:
            return None
        from .models import UserSession  # lazy: DRF loads this class while importing views

        user, _token = result
        try:
            session_id = uuid.UUID(str(user.claims.get("sid")))
            account_id = uuid.UUID(str(user.id))
        except ValueError as exc:
            raise exceptions.AuthenticationFailed("Invalid access token.") from exc
        live = UserSession.objects.filter(
            id=session_id, account_id=account_id, revoked_at__isnull=True
        ).exists()
        if not live:
            raise exceptions.AuthenticationFailed("This session has been signed out.")
        return result
