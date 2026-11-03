"""Register (or remove) the Telegram webhook used for phone verification.

    python manage.py set_telegram_webhook                       # base = FRONTEND_BASE_URL
    python manage.py set_telegram_webhook --url https://tara.example
    python manage.py set_telegram_webhook --delete

Needs TELEGRAM_BOT_TOKEN, plus TELEGRAM_WEBHOOK_SECRET when setting: Telegram
echoes the secret in X-Telegram-Bot-Api-Secret-Token, which the webhook checks.
The secret travels in that header only, never in the URL (URLs end up in logs).
"""

from __future__ import annotations

import re

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from identity.telegram import TelegramError, bot_api

WEBHOOK_PATH = "/api/v1/auth/telegram/webhook/"
# Telegram's secret_token alphabet and length limit.
_SECRET_RE = re.compile(r"^[A-Za-z0-9_-]{32,256}$")


class Command(BaseCommand):
    help = "Register the Telegram bot webhook for phone verification."

    def add_arguments(self, parser):
        parser.add_argument(
            "--url", help="Public https origin of the site. Defaults to FRONTEND_BASE_URL."
        )
        parser.add_argument("--delete", action="store_true", help="Remove the webhook instead.")

    def handle(self, *args, **opts):
        if not settings.TELEGRAM_BOT_TOKEN:
            raise CommandError("TELEGRAM_BOT_TOKEN is not set.")
        try:
            if opts["delete"]:
                bot_api("deleteWebhook", {"drop_pending_updates": True}, timeout=15)
                self.stdout.write(self.style.SUCCESS("Telegram webhook removed."))
                return

            secret = settings.TELEGRAM_WEBHOOK_SECRET
            if not _SECRET_RE.match(secret):
                raise CommandError(
                    "TELEGRAM_WEBHOOK_SECRET must be 32-256 characters of A-Z a-z 0-9 _ -"
                    " (e.g. `openssl rand -hex 32`)."
                )
            base = (opts.get("url") or settings.FRONTEND_BASE_URL or "").rstrip("/")
            if not base.startswith("https://"):
                raise CommandError("Telegram only calls https webhooks. Pass --url https://...")
            url = base + WEBHOOK_PATH
            bot_api(
                "setWebhook",
                {
                    "url": url,
                    "secret_token": secret,
                    "allowed_updates": ["message"],
                    "drop_pending_updates": True,
                },
                timeout=15,
            )
        except TelegramError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(f"Telegram webhook set to {url}"))
