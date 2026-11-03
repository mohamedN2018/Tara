"""Identity-specific deploy checks (``manage.py check --deploy``)."""

from __future__ import annotations

import re

from django.conf import settings
from django.core.checks import Error, Tags, register

_SECRET_RE = re.compile(r"^[A-Za-z0-9_-]{32,256}$")


@register(Tags.security, deploy=True)
def telegram_webhook_secret_check(app_configs=None, **kwargs):
    """A configured bot must have a strong webhook secret: it is the only thing
    stopping anyone from posting forged "share contact" updates."""
    if not settings.TELEGRAM_BOT_TOKEN:
        return []
    if _SECRET_RE.match(settings.TELEGRAM_WEBHOOK_SECRET or ""):
        return []
    return [
        Error(
            "TELEGRAM_BOT_TOKEN is set but TELEGRAM_WEBHOOK_SECRET is missing or weak.",
            hint="Use 32+ characters of A-Z a-z 0-9 _ - (e.g. `openssl rand -hex 32`).",
            id="identity.E001",
        )
    ]
