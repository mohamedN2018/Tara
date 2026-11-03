"""Account-security use cases: Google sign-in and linking, change password,
change email, and the security overview the settings page reads.

Same rules as services.py: state changes and their outbox events commit
together (identity has no ATOMIC_REQUESTS, so each use case opens its own
transaction), and mail goes out only on commit.
"""

from __future__ import annotations

import secrets
from datetime import timedelta
from typing import Any

from django.db import IntegrityError, transaction
from django.utils import timezone

from tara_common.exceptions import Conflict, TaraAPIError

from . import emails
from . import tokens as token_engine
from .events import emit_domain_event, emit_security_event
from .google import GoogleIdentity, GoogleTokenError, google_enabled, verify_credential
from .models import Account, EmailChangeRequest, PasswordReset, SocialIdentity
from .services import (
    AccountNotUsable,
    IssuedTokens,
    _create_session_and_tokens,
    _hash,
    _validate_password,
    invalidate_account_recovery,
)

EMAIL_CHANGE_TTL = timedelta(hours=24)
GOOGLE = SocialIdentity.Provider.GOOGLE


def _field_error(field: str, code: str, message: str) -> TaraAPIError:
    return TaraAPIError(
        message,
        code="validation_error",
        details=[{"field": field, "code": code, "message": message}],
        http_status_code=400,
    )


def _reauthenticate(account: Account, password: object, *, ip_region: str) -> None:
    """Re-auth for adding or removing a sign-in method, when the account has a password.

    A stolen access token alone must not be able to plant a lasting way in.
    Accounts without a password (Google-only) have nothing to check against.
    """
    if not account.has_usable_password():
        return
    if not password:
        raise _field_error(
            "password", "password_required", "Enter your current password to continue."
        )
    _require_password(account, str(password), field="password", ip_region=ip_region)


def _require_password(account: Account, password: str, *, field: str, ip_region: str) -> None:
    """Re-authenticate a sensitive change with the current password."""
    if not account.has_usable_password():
        raise _field_error(
            field, "no_password", "Set a password first (use 'Forgot password' to create one)."
        )
    if not account.check_password(password or ""):
        emit_security_event(account, "reauth_failed", {"field": field}, ip_region=ip_region)
        raise _field_error(field, "invalid_password", "The current password is incorrect.")


# ---- Google -----------------------------------------------------------------


def _verified_google(credential: object, *, signed_in: bool = False) -> GoogleIdentity:
    if not google_enabled():
        raise TaraAPIError("Google sign-in is not enabled.", code="not_found", http_status_code=404)
    try:
        return verify_credential(credential)
    except GoogleTokenError as exc:
        if signed_in:
            # Not 401: the caller's own session is fine, and a 401 would make
            # clients rotate their refresh token for nothing.
            raise _field_error(
                "credential", "invalid_google_credential", "Could not verify the Google account."
            ) from exc
        raise TaraAPIError(
            "Could not verify the Google sign-in.",
            code="authentication_failed",
            http_status_code=401,
        ) from exc


def google_sign_in(
    *,
    credential: object,
    language: str = "en",
    theme: str = "system",
    ip_region: str = "",
    user_agent: str = "",
    correlation_id: str | None = None,
) -> tuple[IssuedTokens, bool]:
    """Sign in with Google, creating the account on first use.

    An existing password account with the same email is NEVER linked here:
    whoever holds that Google account has not proven they own the Tara account
    (and a pre-registered, unverified account may belong to an attacker). The
    owner signs in with their password and links Google from Settings.
    Returns (tokens, created).
    """
    google = _verified_google(credential)
    link = (
        SocialIdentity.objects.select_related("account")
        .filter(provider=GOOGLE, subject=google.subject)
        .first()
    )
    created = False
    if link is not None:
        account = link.account
    else:
        existing = Account.objects.filter(email=google.email).first()
        if existing is not None:
            emit_security_event(
                existing, "google_signin_refused", {"reason": "email_in_use"}, ip_region=ip_region
            )
            raise TaraAPIError(
                "An account with this email already exists. Sign in with your password,"
                " then link Google in Settings.",
                code="account_exists",
                http_status_code=409,
            )
        try:
            with transaction.atomic():
                account = Account.objects.create_user(
                    email=google.email,
                    password=None,  # unusable: Google is the only login method
                    language=language,
                    theme=theme,
                    status=Account.Status.ACTIVE,
                    email_verified=True,
                )
                link = SocialIdentity.objects.create(
                    account=account, provider=GOOGLE, subject=google.subject, email=google.email
                )
                emit_security_event(
                    account, "account_registered", {"method": "google"}, ip_region=ip_region
                )
                emit_domain_event(
                    "account.registered",
                    subject_id=str(account.id),
                    payload={
                        "email_verified": True,
                        "language": language,
                        "display_name": google.name,
                        "handle": "",
                    },
                    actor_id=str(account.id),
                    correlation_id=correlation_id,
                )
                emit_domain_event(
                    "account.verified",
                    subject_id=str(account.id),
                    payload={"email_verified": True},
                    actor_id=str(account.id),
                    correlation_id=correlation_id,
                )
        except IntegrityError as exc:  # a concurrent sign-up took the email or subject
            raise Conflict("An account with this email already exists.") from exc
        created = True

    if not account.is_usable:
        emit_security_event(
            account,
            "login_blocked",
            {"status": account.status, "method": "google"},
            ip_region=ip_region,
        )
        raise AccountNotUsable()

    with transaction.atomic():
        issued = _create_session_and_tokens(account, ip_region=ip_region, user_agent=user_agent)
        now = timezone.now()
        account.last_login_at = now
        account.save(update_fields=["last_login_at"])
        link.last_used_at = now
        link.email = google.email
        link.save(update_fields=["last_used_at", "email"])
        emit_security_event(account, "login_succeeded", {"method": "google"}, ip_region=ip_region)
        emit_domain_event(
            "session.created",
            subject_id=str(issued.session.id),
            payload={"account_id": str(account.id), "ip_region": ip_region},
            actor_id=str(account.id),
            correlation_id=correlation_id,
        )
    return issued, created


def link_google(
    account: Account, *, credential: object, password: object = "", ip_region: str = ""
) -> SocialIdentity:
    """Attach a Google identity to the signed-in account, after re-authentication."""
    _reauthenticate(account, password, ip_region=ip_region)
    google = _verified_google(credential, signed_in=True)
    existing = SocialIdentity.objects.filter(provider=GOOGLE, subject=google.subject).first()
    if existing is not None:
        if existing.account_id == account.id:
            return existing  # already linked: idempotent
        raise Conflict("This Google account is already linked to another Tara account.")
    if account.social_identities.filter(provider=GOOGLE).exists():
        raise TaraAPIError(
            "A Google account is already linked. Unlink it first.",
            code="already_linked",
            http_status_code=409,
        )
    # Otherwise "Sign in with Google" for that address would land somewhere
    # its Tara owner does not expect.
    if Account.objects.filter(email=google.email).exclude(id=account.id).exists():
        raise Conflict("This Google address belongs to another Tara account.")
    try:
        with transaction.atomic():
            link = SocialIdentity.objects.create(
                account=account, provider=GOOGLE, subject=google.subject, email=google.email
            )
            emit_security_event(account, "google_linked", {}, ip_region=ip_region)
    except IntegrityError as exc:
        raise Conflict("This Google account is already linked.") from exc
    return link


def unlink_google(account: Account, *, password: object = "", ip_region: str = "") -> None:
    link = account.social_identities.filter(provider=GOOGLE).first()
    if link is None:
        raise TaraAPIError("No Google account is linked.", code="not_found", http_status_code=404)
    if not account.has_usable_password():
        raise TaraAPIError(
            "Google is your only way to sign in. Set a password before unlinking it.",
            code="last_login_method",
            http_status_code=409,
        )
    _reauthenticate(account, password, ip_region=ip_region)
    with transaction.atomic():
        link.delete()
        emit_security_event(account, "google_unlinked", {}, ip_region=ip_region)


# ---- Change password --------------------------------------------------------


def change_password(
    account: Account,
    *,
    current_password: str,
    new_password: str,
    current_session_id: str | None,
    ip_region: str = "",
) -> int:
    """Change the password and sign out every OTHER session. Returns how many."""
    _require_password(account, current_password, field="current_password", ip_region=ip_region)
    if current_password == new_password:
        raise _field_error(
            "new_password", "same_password", "The new password must differ from the current one."
        )
    _validate_password(new_password, account, field="new_password")
    with transaction.atomic():
        account.set_password(new_password)
        account.save(update_fields=["password", "updated_at"])
        others = account.sessions.filter(revoked_at__isnull=True)
        if current_session_id:
            others = others.exclude(id=current_session_id)
        revoked = 0
        for session in others:
            token_engine.revoke_session(session)
            revoked += 1
        # Old reset links and a pending email change die with the old password.
        invalidate_account_recovery(account)
        emit_security_event(
            account, "password_changed", {"revoked_sessions": revoked}, ip_region=ip_region
        )
        email = account.email
        transaction.on_commit(lambda: emails.send_password_changed_notice(email))
    return revoked


# ---- Change email -----------------------------------------------------------


def _pending_email_change(account: Account) -> EmailChangeRequest | None:
    return (
        account.email_changes.filter(
            consumed_at__isnull=True, cancelled_at__isnull=True, expires_at__gt=timezone.now()
        )
        .order_by("-created_at")
        .first()
    )


def request_email_change(
    account: Account, *, new_email: str, password: str, ip_region: str = ""
) -> EmailChangeRequest:
    """Send a confirmation link to the new address; nothing changes until it is opened.

    The response is the same whether or not the new address is taken: a taken
    address gets a notice instead of a link, so the API cannot be used to probe
    which emails are registered.
    """
    new_email = new_email.strip().lower()
    _require_password(account, password, field="password", ip_region=ip_region)
    if new_email == account.email:
        raise _field_error("new_email", "same_email", "This is already your email address.")

    raw_token = secrets.token_urlsafe(32)
    in_use = Account.objects.filter(email=new_email).exists()
    old_email = account.email
    with transaction.atomic():
        now = timezone.now()
        account.email_changes.filter(consumed_at__isnull=True, cancelled_at__isnull=True).update(
            cancelled_at=now
        )
        record = EmailChangeRequest.objects.create(
            account=account,
            new_email=new_email,
            token_hash=_hash(raw_token),
            expires_at=now + EMAIL_CHANGE_TTL,
        )
        emit_security_event(account, "email_change_requested", {}, ip_region=ip_region)
        if in_use:
            transaction.on_commit(lambda: emails.send_email_in_use_notice(new_email))
        else:
            transaction.on_commit(
                lambda: emails.send_email_change_confirmation(new_email, raw_token)
            )
            transaction.on_commit(
                lambda: emails.send_email_change_requested_notice(old_email, new_email)
            )
    return record


def cancel_email_change(account: Account) -> None:
    account.email_changes.filter(consumed_at__isnull=True, cancelled_at__isnull=True).update(
        cancelled_at=timezone.now()
    )


def confirm_email_change(*, raw_token: str, correlation_id: str | None = None) -> Account:
    record = (
        EmailChangeRequest.objects.select_related("account")
        .filter(token_hash=_hash(raw_token), consumed_at__isnull=True, cancelled_at__isnull=True)
        .first()
    )
    if (
        record is None
        or record.expires_at <= timezone.now()
        or record.account.status == Account.Status.DELETED
    ):
        raise TaraAPIError(
            "Invalid or expired confirmation link.", code="validation_error", http_status_code=400
        )
    account = record.account
    new_email = record.new_email
    if Account.objects.filter(email=new_email).exclude(id=account.id).exists():
        raise Conflict("This email address is already in use.")
    old_email = account.email
    try:
        with transaction.atomic():
            # Re-check under a lock: a password reset may cancel it meanwhile,
            # and two clicks on the link must not both apply it.
            if (
                not EmailChangeRequest.objects.select_for_update()
                .filter(id=record.id, consumed_at__isnull=True, cancelled_at__isnull=True)
                .first()
            ):
                raise TaraAPIError(
                    "Invalid or expired confirmation link.",
                    code="validation_error",
                    http_status_code=400,
                )
            now = timezone.now()
            account.email = new_email
            account.email_verified = True
            account.save(update_fields=["email", "email_verified", "updated_at"])
            record.consumed_at = now
            record.save(update_fields=["consumed_at"])
            account.email_changes.filter(
                consumed_at__isnull=True, cancelled_at__isnull=True
            ).update(cancelled_at=now)
            # Reset links went to the old address, which no longer signs in.
            PasswordReset.objects.filter(account=account, consumed_at__isnull=True).update(
                consumed_at=now
            )
            emit_security_event(account, "email_changed", {})
            emit_domain_event(
                "account.email_changed",
                subject_id=str(account.id),
                payload={"email_verified": True},  # addresses stay in identity
                actor_id=str(account.id),
                correlation_id=correlation_id,
            )
            transaction.on_commit(lambda: emails.send_email_changed_notice(old_email, new_email))
    except IntegrityError as exc:  # someone registered the address meanwhile
        raise Conflict("This email address is already in use.") from exc
    return account


# ---- Overview ---------------------------------------------------------------


def security_overview(account: Account) -> dict[str, Any]:
    google = account.social_identities.filter(provider=GOOGLE).first()
    pending = _pending_email_change(account)
    return {
        "email": account.email,
        "email_verified": account.email_verified,
        "has_password": account.has_usable_password(),
        "pending_email": pending.new_email if pending else None,
        "google": {
            "linked": google is not None,
            "email": google.email if google else None,
            "linked_at": google.created_at.isoformat() if google else None,
        },
        "phone": account.phone or None,
        "phone_verified": account.phone_verified,
        "phone_verified_at": (
            account.phone_verified_at.isoformat() if account.phone_verified_at else None
        ),
    }
