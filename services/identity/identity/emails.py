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


def send_email_change_confirmation(new_email: str, raw_token: str) -> None:
    link = f"{settings.FRONTEND_BASE_URL}/confirm-email?token={raw_token}"
    _enqueue(
        new_email,
        "Confirm your new Tara email address",
        "Someone asked to use this address for a Tara account. If it was you, confirm:"
        f"\n\n{link}\n\nThis link expires in 24 hours. Ignore this message if you didn't ask.",
    )


def send_email_in_use_notice(new_email: str) -> None:
    # Sent instead of a confirmation link, so the API never reveals whether an
    # address is already registered.
    _enqueue(
        new_email,
        "Tara email change request",
        "Someone asked to move a Tara account to this address, but it already belongs to"
        " a Tara account. Nothing was changed. Ignore this message if you didn't ask.",
    )


def send_email_change_requested_notice(old_email: str, new_email: str) -> None:
    _enqueue(
        old_email,
        "Your Tara email address is being changed",
        f"A request was made to change your Tara sign-in email to {mask_email(new_email)}."
        " It changes only after the new address is confirmed.\n\nIf this wasn't you,"
        " change your password now and sign out your other sessions in Settings.",
    )


def send_email_changed_notice(old_email: str, new_email: str) -> None:
    _enqueue(
        old_email,
        "Your Tara email address was changed",
        f"Your Tara sign-in email is now {mask_email(new_email)}. If this wasn't you,"
        " contact support immediately.",
    )


def send_password_changed_notice(email: str) -> None:
    _enqueue(
        email,
        "Your Tara password was changed",
        "Your Tara password was just changed and your other sessions were signed out."
        "\n\nIf this wasn't you, reset your password now:"
        f"\n\n{settings.FRONTEND_BASE_URL}/forgot-password",
    )


def mask_email(email: str) -> str:
    """j***@example.com: enough to recognise, not enough to harvest."""
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}" if domain else "***"
