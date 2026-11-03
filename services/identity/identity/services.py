"""Identity business logic.

Each public function is a use case (register, login, verify, ...). State changes
and their outbox events commit atomically; emails fire only on commit. Views
stay thin and call into here.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.contrib.auth.password_validation import validate_password
from django.core.cache import cache
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone

from tara_common.exceptions import Conflict, TaraAPIError

from . import tokens as token_engine
from .emails import send_password_reset_email, send_verification_email
from .events import emit_domain_event, emit_security_event
from .models import (
    Account,
    Device,
    EmailChangeRequest,
    EmailVerification,
    PasswordReset,
    UserSession,
)

EMAIL_VERIFICATION_TTL = timedelta(hours=24)
LOGIN_MAX_FAILURES = 10
LOGIN_LOCK_SECONDS = 900
PASSWORD_RESET_TTL = timedelta(hours=1)


@dataclass
class IssuedTokens:
    account: Account
    session: UserSession
    access_token: str
    access_expires_in: int
    refresh_token: str


class InvalidCredentials(TaraAPIError):
    code = "authentication_failed"
    message = "Invalid email or password."
    http_status = 401


class AccountNotUsable(TaraAPIError):
    code = "permission_denied"
    message = "This account cannot sign in."
    http_status = 403


def _hash(raw: str) -> str:
    return token_engine.hash_token(raw)


def _validate_password(
    password: str, account: Account | None = None, *, field: str = "password"
) -> None:
    try:
        validate_password(password, account)
    except DjangoValidationError as exc:
        raise TaraAPIError(
            "Password does not meet the security requirements.",
            code="validation_error",
            details=[{"field": field, "code": "weak_password", "message": m} for m in exc.messages],
            http_status_code=400,
        ) from exc


# ---- Sessions ---------------------------------------------------------------


def _create_session_and_tokens(
    account: Account, *, ip_region: str, user_agent: str, platform: str = "web"
) -> IssuedTokens:
    # No unique constraint on these columns: two concurrent first logins can
    # both create one, and get_or_create would then fail every later login.
    lookup = {"account": account, "platform": platform, "label": user_agent[:120]}
    device = Device.objects.filter(**lookup).first() or Device.objects.create(**lookup)
    session = UserSession.objects.create(
        account=account, device=device, ip_region=ip_region, user_agent=user_agent[:400]
    )
    refresh_raw, _ = token_engine.create_refresh_token(account, session)
    access, ttl = token_engine.issue_access_token(account, str(session.id))
    return IssuedTokens(account, session, access, ttl, refresh_raw)


# ---- Use cases --------------------------------------------------------------


def register(
    *,
    email: str,
    password: str,
    language: str = "en",
    theme: str = "system",
    display_name: str = "",
    handle: str = "",
    ip_region: str = "",
    user_agent: str = "",
    correlation_id: str | None = None,
) -> Account:
    email = email.strip().lower()
    if Account.objects.filter(email=email).exists():
        # Do not reveal which step failed beyond "already registered".
        raise Conflict("An account with this email already exists.", code="conflict")
    _validate_password(password)

    with transaction.atomic():
        account = Account.objects.create_user(
            email=email,
            password=password,
            language=language,
            theme=theme,
            status=Account.Status.PENDING,
        )
        raw_token = secrets.token_urlsafe(32)
        EmailVerification.objects.create(
            account=account,
            token_hash=_hash(raw_token),
            expires_at=timezone.now() + EMAIL_VERIFICATION_TTL,
        )
        # No email here: security events outlive the account (SET_NULL on delete).
        emit_security_event(account, "account_registered", {}, ip_region=ip_region)
        emit_domain_event(
            "account.registered",
            subject_id=str(account.id),
            # No email on the bus: no consumer needs it (docs/.../04-event-contracts.md).
            payload={
                "email_verified": False,
                "language": language,
                "display_name": display_name,
                "handle": handle,
            },
            actor_id=str(account.id),
            correlation_id=correlation_id,
        )
        transaction.on_commit(lambda: send_verification_email(email, raw_token))
    return account


def resend_verification(email: str) -> None:
    """Send a new link. Silent for unknown or active accounts (no enumeration)."""
    email = email.strip().lower()
    account = Account.objects.filter(email=email, status=Account.Status.PENDING).first()
    if account is None:
        return
    raw_token = secrets.token_urlsafe(32)
    with transaction.atomic():
        EmailVerification.objects.create(
            account=account,
            token_hash=_hash(raw_token),
            expires_at=timezone.now() + EMAIL_VERIFICATION_TTL,
        )
        transaction.on_commit(lambda: send_verification_email(email, raw_token))


def login(
    *,
    email: str,
    password: str,
    ip_region: str = "",
    user_agent: str = "",
    correlation_id: str | None = None,
) -> IssuedTokens:
    email = email.strip().lower()
    lock_key = "login-failures:" + hashlib.sha256(email.encode()).hexdigest()
    if (cache.get(lock_key) or 0) >= LOGIN_MAX_FAILURES:
        raise TaraAPIError(
            "Too many failed attempts. Try again later.",
            code="throttled",
            http_status_code=429,
        )
    account = Account.objects.filter(email=email).first()
    # Same work whether or not the account exists (mitigate enumeration).
    if account is None:
        make_password(password)
    if account is None or not account.check_password(password):
        cache.add(lock_key, 0, LOGIN_LOCK_SECONDS)
        cache.incr(lock_key)
        if account is not None:
            emit_security_event(account, "login_failed", {}, ip_region=ip_region)
        raise InvalidCredentials()
    if not account.is_usable:
        emit_security_event(
            account, "login_blocked", {"status": account.status}, ip_region=ip_region
        )
        raise AccountNotUsable()

    cache.delete(lock_key)
    with transaction.atomic():
        issued = _create_session_and_tokens(account, ip_region=ip_region, user_agent=user_agent)
        account.last_login_at = timezone.now()
        account.save(update_fields=["last_login_at"])
        emit_security_event(account, "login_succeeded", {}, ip_region=ip_region)
        emit_domain_event(
            "session.created",
            subject_id=str(issued.session.id),
            payload={"account_id": str(account.id), "ip_region": ip_region},
            actor_id=str(account.id),
            correlation_id=correlation_id,
        )
    return issued


def refresh(*, refresh_token: str) -> IssuedTokens:
    try:
        account, session, access, ttl, new_refresh = token_engine.rotate_refresh_token(
            refresh_token
        )
    except token_engine.TokenError as exc:
        raise TaraAPIError(str(exc), code="authentication_failed", http_status_code=401) from exc
    return IssuedTokens(account, session, access, ttl, new_refresh)


def logout(*, refresh_token: str | None = None, session_id: str | None = None) -> None:
    session = None
    if refresh_token:
        from .models import RefreshToken

        rt = (
            RefreshToken.objects.select_related("session")
            .filter(token_hash=_hash(refresh_token))
            .first()
        )
        session = rt.session if rt else None
    elif session_id:
        session = UserSession.objects.filter(id=session_id).first()
    if session is not None:
        token_engine.revoke_session(session)
        emit_security_event(session.account, "logout", {"session_id": str(session.id)})


def verify_email(*, raw_token: str) -> Account:
    record = (
        EmailVerification.objects.select_related("account")
        .filter(token_hash=_hash(raw_token), consumed_at__isnull=True)
        .first()
    )
    if record is None or record.expires_at <= timezone.now():
        raise TaraAPIError(
            "Invalid or expired verification token.", code="validation_error", http_status_code=400
        )
    with transaction.atomic():
        record.consumed_at = timezone.now()
        record.save(update_fields=["consumed_at"])
        account = record.account
        account.email_verified = True
        if account.status == Account.Status.PENDING:
            account.status = Account.Status.ACTIVE
        account.save(update_fields=["email_verified", "status"])
        emit_security_event(account, "email_verified", {})
        emit_domain_event(
            "account.verified",
            subject_id=str(account.id),
            payload={"email_verified": True},
            actor_id=str(account.id),
        )
    return account


def request_password_reset(*, email: str) -> None:
    """Always succeeds from the caller's view (no account-existence disclosure)."""
    email = email.strip().lower()
    account = Account.objects.filter(email=email).first()
    if account is None:
        return
    raw_token = secrets.token_urlsafe(32)
    with transaction.atomic():
        PasswordReset.objects.create(
            account=account,
            token_hash=_hash(raw_token),
            expires_at=timezone.now() + PASSWORD_RESET_TTL,
        )
        emit_security_event(account, "password_reset_requested", {})
        transaction.on_commit(lambda: send_password_reset_email(email, raw_token))


def _invalid_reset_token() -> TaraAPIError:
    return TaraAPIError(
        "Invalid or expired reset token.", code="validation_error", http_status_code=400
    )


def invalidate_account_recovery(account: Account) -> None:
    """After a password reset or change, nothing issued earlier may still take over.

    Unused reset links were issued for the old password, and a pending email
    change may have been started by whoever knew it: confirming it would move
    the account to their address. Call inside the password-change transaction.
    """
    now = timezone.now()
    PasswordReset.objects.filter(account=account, consumed_at__isnull=True).update(consumed_at=now)
    EmailChangeRequest.objects.filter(
        account=account, consumed_at__isnull=True, cancelled_at__isnull=True
    ).update(cancelled_at=now)


def reset_password(*, raw_token: str, new_password: str) -> None:
    record = (
        PasswordReset.objects.select_related("account")
        .filter(token_hash=_hash(raw_token), consumed_at__isnull=True)
        .first()
    )
    if record is None or record.expires_at <= timezone.now():
        raise _invalid_reset_token()
    account = record.account
    _validate_password(new_password, account)
    with transaction.atomic():
        # Lock the link so two concurrent submissions cannot both use it.
        locked = (
            PasswordReset.objects.select_for_update()
            .filter(id=record.id, consumed_at__isnull=True)
            .first()
        )
        if locked is None:
            raise _invalid_reset_token()
        account.set_password(new_password)
        account.save(update_fields=["password", "updated_at"])
        invalidate_account_recovery(account)
        # Security: invalidate every existing session on password change.
        for session in account.sessions.filter(revoked_at__isnull=True):
            token_engine.revoke_session(session)
        emit_security_event(account, "password_reset_completed", {})


def list_sessions(account: Account):
    """Live sessions only: one unseen for a refresh-token lifetime cannot refresh again."""
    cutoff = timezone.now() - timedelta(seconds=settings.REFRESH_TOKEN_TTL_SECONDS)
    return (
        account.sessions.filter(revoked_at__isnull=True, last_seen_at__gt=cutoff)
        .select_related("device")
        .order_by("-last_seen_at")
    )


def revoke_session_by_id(account: Account, session_id: str) -> None:
    session = account.sessions.filter(id=session_id).first()
    if session is None:
        raise TaraAPIError("Session not found.", code="not_found", http_status_code=404)
    token_engine.revoke_session(session)
    emit_security_event(account, "session_revoked", {"session_id": str(session_id)})
