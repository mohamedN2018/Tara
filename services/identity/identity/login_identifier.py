"""Sign-in identifiers: an email address or a username (decision 5.6).

Handles belong to the profile service, so a username is turned into an account
id by asking profile's internal ``profiles/by-handle/`` endpoint. Nothing here
tells the caller whether a handle exists: an unknown handle resolves to no
account, and ``services.login`` answers it exactly like a wrong password.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request

from django.conf import settings

from tara_common.auth import mint_internal_token
from tara_common.exceptions import DependencyUnavailable

from .models import Account

logger = logging.getLogger("tara.identity.login")

# Same shape as RegisterSerializer.handle; a leading "@" is what people type.
HANDLE_RE = re.compile(r"^@?([a-z0-9_]{3,30})$")


def normalise(raw: object) -> str:
    """Lowercased, trimmed identifier. A handle loses its leading "@".

    The lockout and the per-target throttle key on this, so "@Sara" and "sara"
    share one budget. Emails come out exactly as before (strip + lower).
    """
    value = raw.strip().lower() if isinstance(raw, str) else ""
    match = HANDLE_RE.match(value)
    return match.group(1) if match else value


def _account_id_for_handle(handle: str) -> str | None:
    token = mint_internal_token(issuer="identity", audience="profile-internal")
    request = urllib.request.Request(  # noqa: S310 - internal URL from settings
        f"{settings.PROFILE_INTERNAL_URL}/internal/v1/profiles/by-handle/",
        data=json.dumps({"handles": [handle]}).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=settings.PROFILE_CALL_TIMEOUT) as resp:  # noqa: S310
            body = json.loads(resp.read().decode())
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        # Never the handle in the log: it is what the person typed to sign in.
        logger.warning("profile handle lookup failed", exc_info=True)
        raise DependencyUnavailable("Sign-in by username is unavailable right now.") from None
    data = body.get("data") if isinstance(body, dict) else None
    account_id = data.get(handle) if isinstance(data, dict) else None
    return account_id if isinstance(account_id, str) else None


def find_account(identifier: str) -> Account | None:
    """The account an identifier (already ``normalise``d) names, or None."""
    if "@" in identifier:
        return Account.objects.filter(email=identifier).first()
    if not HANDLE_RE.match(identifier):
        return None  # neither an email nor a handle: no lookup to make
    account_id = _account_id_for_handle(identifier)
    return Account.objects.filter(id=account_id).first() if account_id else None
