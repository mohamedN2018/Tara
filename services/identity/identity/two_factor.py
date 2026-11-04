"""Two-factor sign-in with an authenticator app (TOTP, RFC 6238) and recovery codes.

- The secret is 20 random bytes, shown once as base32 (and an ``otpauth://``
  link for the QR code). At rest it is Fernet-encrypted with a key from
  ``IDENTITY_TOTP_ENCRYPTION_KEY`` (or, when that is empty, one derived from
  ``SECRET_KEY``, so rotating either makes stored secrets unreadable: the owner
  then signs in with a recovery code and sets 2FA up again).
- A code is 6 digits over 30 s steps, accepted one step either side for clock
  drift. ``last_used_step`` makes every code single-use.
- Ten recovery codes, stored as SHA-256 hashes, each usable once.

Turning 2FA on or off needs the current password (when the account has one),
so a stolen access token cannot lock the owner out or strip the second factor.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from tara_common.exceptions import TaraAPIError

from . import emails
from .events import emit_security_event
from .models import Account, TwoFactorRecoveryCode, TwoFactorSecret

STEP_SECONDS = 30
DIGITS = 6
DRIFT_STEPS = 1
RECOVERY_CODE_COUNT = 10
ISSUER = "Tara"


# ---- primitives -------------------------------------------------------------


def _fernet() -> Fernet:
    raw = (getattr(settings, "TOTP_ENCRYPTION_KEY", "") or "").strip()
    if not raw:
        raw = settings.SECRET_KEY
    key = hashlib.sha256(b"tara-totp-secret:" + raw.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_secret(secret: bytes) -> bytes:
    return _fernet().encrypt(secret)


def decrypt_secret(blob: bytes | memoryview) -> bytes | None:
    try:
        return _fernet().decrypt(bytes(blob))
    except InvalidToken:
        return None


def totp_at(secret: bytes, step: int) -> str:
    digest = hmac.new(secret, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10**DIGITS).zfill(DIGITS)


def current_step(now: float | None = None) -> int:
    return int((time.time() if now is None else now) // STEP_SECONDS)


def matching_step(secret: bytes, code: str, now: float | None = None) -> int | None:
    """The time step ``code`` belongs to (within the drift window), or None."""
    code = "".join(ch for ch in code if ch.isdigit())
    if len(code) != DIGITS:
        return None
    base = current_step(now)
    for step in range(base - DRIFT_STEPS, base + DRIFT_STEPS + 1):
        if hmac.compare_digest(totp_at(secret, step), code):
            return step
    return None


def _b32(secret: bytes) -> str:
    return base64.b32encode(secret).decode().rstrip("=")


def otpauth_uri(secret: bytes, label: str) -> str:
    return (
        f"otpauth://totp/{quote(ISSUER)}:{quote(label)}?secret={_b32(secret)}"
        f"&issuer={quote(ISSUER)}&algorithm=SHA1&digits={DIGITS}&period={STEP_SECONDS}"
    )


def _normalise_recovery(code: str) -> str:
    return "".join(ch for ch in code.lower() if ch.isalnum())


def _recovery_hash(code: str) -> str:
    return hashlib.sha256(_normalise_recovery(code).encode()).hexdigest()


def _new_recovery_codes(account: Account) -> list[str]:
    """Replace the account's recovery codes. Returns the new ones (shown once)."""
    TwoFactorRecoveryCode.objects.filter(account=account).delete()
    codes = []
    for _ in range(RECOVERY_CODE_COUNT):
        raw = secrets.token_hex(5)  # 10 hex characters, shown as xxxxx-xxxxx
        codes.append(f"{raw[:5]}-{raw[5:]}")
    TwoFactorRecoveryCode.objects.bulk_create(
        [TwoFactorRecoveryCode(account=account, code_hash=_recovery_hash(c)) for c in codes]
    )
    return codes


# ---- errors -----------------------------------------------------------------


def _field_error(field: str, code: str, message: str) -> TaraAPIError:
    return TaraAPIError(
        message,
        code="validation_error",
        details=[{"field": field, "code": code, "message": message}],
        http_status_code=400,
    )


class TwoFactorRequired(TaraAPIError):
    """Sign-in: the password was right, now the second factor is needed."""

    code = "two_factor_required"
    message = "Enter the code from your authenticator app."
    http_status = 401


class TwoFactorInvalid(TaraAPIError):
    code = "two_factor_invalid"
    message = "That code didn't work. Check it and try again."
    http_status = 401


# ---- state ------------------------------------------------------------------


def confirmed_secret(account: Account) -> TwoFactorSecret | None:
    return TwoFactorSecret.objects.filter(account=account, confirmed_at__isnull=False).first()


def is_enabled(account: Account) -> bool:
    return confirmed_secret(account) is not None


def status(account: Account) -> dict:
    row = TwoFactorSecret.objects.filter(account=account).first()
    enabled = row is not None and row.confirmed_at is not None
    remaining = (
        TwoFactorRecoveryCode.objects.filter(account=account, used_at__isnull=True).count()
        if enabled
        else 0
    )
    return {
        "enabled": enabled,
        "method": "totp" if enabled else None,
        "enabled_at": row.confirmed_at.isoformat() if enabled else None,
        "recovery_codes_remaining": remaining,
    }


def _use_totp(row: TwoFactorSecret, code: str) -> bool:
    secret = decrypt_secret(row.secret_enc)
    if secret is None:
        return False
    step = matching_step(secret, code)
    if step is None or (row.last_used_step is not None and step <= row.last_used_step):
        return False
    # Conditional update: two concurrent sign-ins with one code cannot both win.
    updated = (
        TwoFactorSecret.objects.filter(pk=row.pk)
        .filter(Q(last_used_step__isnull=True) | Q(last_used_step__lt=step))
        .update(last_used_step=step)
    )
    return updated == 1


def _use_recovery(account: Account, code: str) -> bool:
    if len(_normalise_recovery(code)) != 10:
        return False
    updated = TwoFactorRecoveryCode.objects.filter(
        account=account, code_hash=_recovery_hash(code), used_at__isnull=True
    ).update(used_at=timezone.now())
    return updated >= 1


def verify_second_factor(account: Account, code: str) -> str | None:
    """Accept a TOTP code or a recovery code. Returns which ("totp"/"recovery") or None."""
    row = confirmed_secret(account)
    if row is None or not code:
        return None
    if _use_totp(row, code):
        return "totp"
    if _use_recovery(account, code):
        return "recovery"
    return None


def check_sign_in(account: Account, code: str | None, *, ip_region: str = "") -> None:
    """Sign-in gate: raise unless 2FA is off or ``code`` is a valid second factor."""
    if not is_enabled(account):
        return
    if not code:
        raise TwoFactorRequired()
    used = verify_second_factor(account, code)
    if used is None:
        emit_security_event(account, "two_factor_failed", {}, ip_region=ip_region)
        raise TwoFactorInvalid()
    if used == "recovery":
        emit_security_event(account, "two_factor_recovery_used", {}, ip_region=ip_region)


# ---- use cases --------------------------------------------------------------


def _reauth(account: Account, password: str, *, ip_region: str) -> None:
    from .account_security import _reauthenticate

    _reauthenticate(account, password, ip_region=ip_region)


def start_setup(account: Account, *, password: str, ip_region: str = "") -> dict:
    """A new unconfirmed secret (replacing any unconfirmed one)."""
    _reauth(account, password, ip_region=ip_region)
    if is_enabled(account):
        raise TaraAPIError(
            "Two-factor authentication is already on.", code="conflict", http_status_code=409
        )
    secret = secrets.token_bytes(20)
    TwoFactorSecret.objects.update_or_create(
        account=account,
        defaults={
            "type": "totp",
            "secret_enc": encrypt_secret(secret),
            "confirmed_at": None,
            "last_used_step": None,
        },
    )
    return {
        "secret": _b32(secret),
        "otpauth_uri": otpauth_uri(secret, account.email),
        "digits": DIGITS,
        "period": STEP_SECONDS,
    }


def confirm_setup(account: Account, *, code: str, ip_region: str = "") -> list[str]:
    """Prove the app holds the secret; turns 2FA on. Returns the recovery codes."""
    with transaction.atomic():
        row = TwoFactorSecret.objects.select_for_update().filter(account=account).first()
        if row is None or row.confirmed_at is not None:
            raise _field_error("code", "no_pending_setup", "Start the setup again.")
        secret = decrypt_secret(row.secret_enc)
        step = matching_step(secret, code) if secret else None
        if step is None:
            raise _field_error("code", "invalid_code", "That code didn't work. Try the newest one.")
        row.confirmed_at = timezone.now()
        row.last_used_step = step
        row.save(update_fields=["confirmed_at", "last_used_step"])
        codes = _new_recovery_codes(account)
        emit_security_event(account, "two_factor_enabled", {}, ip_region=ip_region)
        email = account.email
        transaction.on_commit(lambda: emails.send_two_factor_changed_notice(email, enabled=True))
    return codes


def disable(account: Account, *, password: str, code: str, ip_region: str = "") -> None:
    _reauth(account, password, ip_region=ip_region)
    if not is_enabled(account):
        return
    if verify_second_factor(account, code) is None:
        emit_security_event(account, "two_factor_failed", {}, ip_region=ip_region)
        raise _field_error("code", "invalid_code", "That code didn't work.")
    with transaction.atomic():
        TwoFactorSecret.objects.filter(account=account).delete()
        TwoFactorRecoveryCode.objects.filter(account=account).delete()
        emit_security_event(account, "two_factor_disabled", {}, ip_region=ip_region)
        email = account.email
        transaction.on_commit(lambda: emails.send_two_factor_changed_notice(email, enabled=False))


def regenerate_recovery_codes(account: Account, *, password: str, ip_region: str = "") -> list[str]:
    _reauth(account, password, ip_region=ip_region)
    if not is_enabled(account):
        raise TaraAPIError(
            "Two-factor authentication is off.", code="not_found", http_status_code=404
        )
    with transaction.atomic():
        codes = _new_recovery_codes(account)
        emit_security_event(account, "two_factor_recovery_regenerated", {}, ip_region=ip_region)
    return codes
