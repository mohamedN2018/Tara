"""Free phone verification through a Telegram bot (QTech's pattern, hardened).

Telegram's "share contact" button vouches that the number belongs to the
Telegram user who taps it, so it is real proof of ownership at no SMS cost.

1. The signed-in user asks for a link: ``start_phone_verification`` stores a
   hashed one-time code and returns ``https://t.me/<bot>?start=<code>``.
2. They press Start; the bot receives ``/start <code>`` and binds that chat and
   Telegram user to the attempt, then shows a "share my number" button.
3. They tap it; Telegram sends a contact whose ``user_id`` is the sender. Only a
   contact the same Telegram user shared for themselves completes the attempt.

The webhook is guarded by ``TELEGRAM_WEBHOOK_SECRET`` (sent by Telegram as the
X-Telegram-Bot-Api-Secret-Token header). Everything is off unless the bot token,
bot username and webhook secret are all set.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import secrets
import urllib.request
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from .events import emit_domain_event, emit_security_event
from .models import Account, PhoneVerification

logger = logging.getLogger("tara.identity.telegram")

API_ROOT = "https://api.telegram.org"
LINK_TTL = timedelta(minutes=15)
_PHONE_RE = re.compile(r"^\+[1-9]\d{6,14}$")  # E.164

MSG_WELCOME = (
    "مرحبًا بك في بوت التحقق من Tara. ابدأ التحقق من رقمك من صفحة الإعدادات في التطبيق.\n"
    "Welcome to the Tara verification bot. Start phone verification from Settings in the app."
)
MSG_SHARE = (
    "اضغط الزر بالأسفل لمشاركة رقمك وتأكيده.\nTap the button below to share and verify your number."
)
MSG_INVALID_LINK = (
    "رابط التحقق غير صالح أو منتهي. أعد المحاولة من التطبيق.\n"
    "This verification link is invalid or expired. Please try again from the app."
)
MSG_NOT_OWN = (
    "شارك رقمك أنت باستخدام الزر، وليس جهة اتصال أخرى.\n"
    "Please share your own number with the button, not another contact."
)
MSG_NO_ATTEMPT = (
    "ابدأ التحقق من داخل التطبيق أولًا.\nPlease start phone verification from the app first."
)
MSG_IN_USE = (
    "هذا الرقم مرتبط بحساب آخر في Tara.\nThis number is already linked to another Tara account."
)
MSG_BAD_NUMBER = "تعذر قراءة هذا الرقم.\nWe couldn't read this phone number."
MSG_VERIFIED = (
    "تم التحقق من رقمك. يمكنك العودة إلى التطبيق.\n"
    "Your number is verified. You can return to the app."
)

SHARE_KEYBOARD = {
    "keyboard": [[{"text": "مشاركة رقمي / Share my number", "request_contact": True}]],
    "resize_keyboard": True,
    "one_time_keyboard": True,
}
REMOVE_KEYBOARD = {"remove_keyboard": True}


class TelegramError(Exception):
    """The Bot API call failed."""


def telegram_enabled() -> bool:
    return bool(
        settings.TELEGRAM_BOT_TOKEN
        and settings.TELEGRAM_BOT_USERNAME
        and settings.TELEGRAM_WEBHOOK_SECRET
    )


def bot_api(method: str, payload: dict[str, Any], *, timeout: int = 10) -> dict[str, Any]:
    """POST to the Bot API. Raises TelegramError (never with the token in it)."""
    token = settings.TELEGRAM_BOT_TOKEN
    if not token:
        raise TelegramError("TELEGRAM_BOT_TOKEN is not set.")
    request = urllib.request.Request(  # noqa: S310 - fixed https endpoint
        f"{API_ROOT}/bot{token}/{method}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:  # noqa: S310
            body = json.loads(resp.read().decode())
    except Exception as exc:  # noqa: BLE001 - urllib raises many types
        raise TelegramError(f"{method} failed: {type(exc).__name__}") from None
    if not isinstance(body, dict) or not body.get("ok"):
        description = body.get("description") if isinstance(body, dict) else ""
        raise TelegramError(f"{method} rejected: {description}")
    return body


def _hash_code(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def _reply(chat_id: str, text: str, markup: dict | None = None) -> None:
    from .tasks_telegram import send_telegram_message

    def enqueue() -> None:
        try:
            send_telegram_message.delay(chat_id, text, markup)
        except Exception:  # noqa: BLE001 - a reply must never break the webhook
            logger.exception("failed to enqueue telegram reply")

    transaction.on_commit(enqueue)


def normalize_phone(raw: object) -> str | None:
    if not isinstance(raw, str):
        return None
    phone = re.sub(r"[\s\-().]", "", raw)
    if phone and not phone.startswith("+"):
        phone = "+" + phone
    return phone if _PHONE_RE.match(phone) else None


# ---- Use cases --------------------------------------------------------------


def start_phone_verification(account: Account) -> tuple[str, int]:
    """Issue a fresh one-time code. Returns (deep_link, expires_in_seconds)."""
    # 32 chars of [A-Za-z0-9_-]: valid as a Telegram start parameter (max 64).
    code = secrets.token_urlsafe(24)
    with transaction.atomic():
        now = timezone.now()
        account.phone_verifications.filter(completed_at__isnull=True, expires_at__gt=now).update(
            expires_at=now
        )
        PhoneVerification.objects.create(
            account=account, code_hash=_hash_code(code), expires_at=now + LINK_TTL
        )
        emit_security_event(account, "phone_verification_started", {"channel": "telegram"})
    link = f"https://t.me/{settings.TELEGRAM_BOT_USERNAME}?start={code}"
    return link, int(LINK_TTL.total_seconds())


def handle_update(update: object) -> None:
    """Process one webhook update. Never raises: Telegram would retry it forever."""
    try:
        if isinstance(update, dict):
            _handle(update)
    except Exception:  # noqa: BLE001
        logger.exception("telegram update failed")


def _handle(update: dict) -> None:
    message = update.get("message")
    if not isinstance(message, dict):
        return
    chat = message.get("chat") or {}
    sender = message.get("from") or {}
    if not isinstance(chat, dict) or not isinstance(sender, dict):
        return
    if chat.get("type") != "private":
        return  # never verify from groups
    chat_id = str(chat.get("id") or "")
    sender_id = sender.get("id")
    if not chat_id or not isinstance(sender_id, int) or sender.get("is_bot"):
        return

    contact = message.get("contact")
    if isinstance(contact, dict):
        _handle_contact(chat_id, sender_id, contact)
        return

    text = message.get("text")
    if isinstance(text, str) and text.startswith("/start"):
        parts = text.split(maxsplit=1)
        code = parts[1].strip() if len(parts) > 1 else ""
        if code:
            _handle_start(chat_id, sender_id, code)
            return
    _reply(chat_id, MSG_WELCOME)


def _handle_start(chat_id: str, sender_id: int, code: str) -> None:
    attempt = PhoneVerification.objects.filter(
        code_hash=_hash_code(code[:64]), completed_at__isnull=True, expires_at__gt=timezone.now()
    ).first()
    # A code already claimed by another Telegram user stays theirs.
    if attempt is None or attempt.telegram_user_id not in (None, sender_id):
        _reply(chat_id, MSG_INVALID_LINK)
        return
    attempt.telegram_chat_id = chat_id
    attempt.telegram_user_id = sender_id
    attempt.save(update_fields=["telegram_chat_id", "telegram_user_id"])
    _reply(chat_id, MSG_SHARE, SHARE_KEYBOARD)


def _handle_contact(chat_id: str, sender_id: int, contact: dict) -> None:
    # The request_contact button sets user_id to the sharer. A forwarded or
    # typed contact has another (or no) user_id and proves nothing.
    if contact.get("user_id") != sender_id:
        _reply(chat_id, MSG_NOT_OWN, REMOVE_KEYBOARD)
        return
    attempt = (
        PhoneVerification.objects.select_related("account")
        .filter(
            telegram_chat_id=chat_id,
            telegram_user_id=sender_id,
            completed_at__isnull=True,
            expires_at__gt=timezone.now(),
        )
        .order_by("-created_at")
        .first()
    )
    if attempt is None or not attempt.account.is_usable:
        _reply(chat_id, MSG_NO_ATTEMPT, REMOVE_KEYBOARD)
        return
    phone = normalize_phone(contact.get("phone_number"))
    if phone is None:
        _reply(chat_id, MSG_BAD_NUMBER, REMOVE_KEYBOARD)
        return
    account = attempt.account
    taken = (
        Account.objects.filter(phone=phone, phone_verified_at__isnull=False)
        .exclude(id=account.id)
        .exists()
    )
    if taken:
        _reply(chat_id, MSG_IN_USE, REMOVE_KEYBOARD)
        return
    try:
        with transaction.atomic():
            now = timezone.now()
            account.phone = phone
            account.phone_verified_at = now
            account.save(update_fields=["phone", "phone_verified_at", "updated_at"])
            attempt.completed_at = now
            attempt.save(update_fields=["completed_at"])
            emit_security_event(account, "phone_verified", {"channel": "telegram"})
            emit_domain_event(
                "account.phone_verified",
                subject_id=str(account.id),
                payload={"phone_verified": True, "channel": "telegram"},
                actor_id=str(account.id),
            )
    except IntegrityError:  # verified on another account meanwhile
        _reply(chat_id, MSG_IN_USE, REMOVE_KEYBOARD)
        return
    _reply(chat_id, MSG_VERIFIED, REMOVE_KEYBOARD)


def remove_phone(account: Account) -> None:
    with transaction.atomic():
        account.phone = ""
        account.phone_verified_at = None
        account.save(update_fields=["phone", "phone_verified_at", "updated_at"])
        emit_security_event(account, "phone_removed", {})
        emit_domain_event(
            "account.phone_removed",
            subject_id=str(account.id),
            payload={"phone_verified": False},
            actor_id=str(account.id),
        )
