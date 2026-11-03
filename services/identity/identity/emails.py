"""Transactional email senders (captured by Mailpit in dev).

Called via transaction.on_commit so a rolled-back registration never sends mail.
Delivery is a retried task; a failure to enqueue is logged, never fatal to the
originating request, and the user can ask for a new verification link.
"""

from __future__ import annotations

import logging

from django.conf import settings

from .tasks_email import send_email

logger = logging.getLogger("tara.identity.emails")


def _enqueue(to: str, subject: str, body: str) -> None:
    try:
        send_email.delay(to, subject, body)
    except Exception:  # noqa: BLE001 - see module docstring
        logger.exception("failed to enqueue email")


def send_verification_email(email: str, raw_token: str) -> None:
    link = f"{settings.FRONTEND_BASE_URL}/verify-email?token={raw_token}"
    _enqueue(
        email,
        "Verify your Tara account",
        f"Welcome to Tara! Confirm your email:\n\n{link}\n\nThis link expires soon.",
    )


def send_password_reset_email(email: str, raw_token: str) -> None:
    link = f"{settings.FRONTEND_BASE_URL}/reset-password?token={raw_token}"
    _enqueue(
        email,
        "Reset your Tara password",
        f"Use this link to reset your password:\n\n{link}\n\nIgnore if you didn't ask.",
    )
