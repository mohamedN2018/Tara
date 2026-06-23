"""Transactional email senders (captured by Mailpit in dev).

Kept side-effect-only and called via transaction.on_commit so a rolled-back
registration never sends an email. Email sending failures are logged, never
fatal to the originating request.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger("tara.identity.emails")


def send_verification_email(email: str, raw_token: str) -> None:
    link = f"{settings.FRONTEND_BASE_URL}/verify-email?token={raw_token}"
    try:
        send_mail(
            subject="Verify your Tara account",
            message=f"Welcome to Tara! Confirm your email:\n\n{link}\n\nThis link expires soon.",
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[email],
            fail_silently=False,
        )
    except Exception:  # noqa: BLE001 - email is best-effort; user can re-request
        logger.exception("failed to send verification email")


def send_password_reset_email(email: str, raw_token: str) -> None:
    link = f"{settings.FRONTEND_BASE_URL}/reset-password?token={raw_token}"
    try:
        send_mail(
            subject="Reset your Tara password",
            message=f"Use this link to reset your password:\n\n{link}\n\nIgnore if you didn't ask.",
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[email],
            fail_silently=False,
        )
    except Exception:  # noqa: BLE001
        logger.exception("failed to send password reset email")
