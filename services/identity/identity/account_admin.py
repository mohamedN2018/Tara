"""Staff actions on one account, for admin's user console (roadmap 8.4, 8.6).

Identity owns the account, so it makes these decisions and records them:
each state change, its security event and its outbox event commit in one
transaction. Admin reaches them only through ``/internal/v1/`` with the secret
it alone shares with identity (1.0d).

Guards (roadmap step 8 acceptance): nobody acts on themselves; an account
holding any staff role cannot be suspended (revoke the role first), and an
admin account cannot be signed out by someone else.

Events. ``account.suspended`` and ``account.unsuspended`` carry ids, the end
date and enums only, never the reason (05 §3.3, payloads on the bus): search,
chat, graph, ads and realtime hide or close what the account owns (8.5).
``account.signed_out`` and ``account.verification.resent`` exist for admin's
audit log. ``IDENTITY_EMIT_ACCOUNT_ACTION_EVENTS`` is the two-release emission
flag (05 §3.3, deploy order).
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from tara_common.exceptions import Conflict, TaraAPIError

from . import tokens as token_engine
from .emails import send_verification_email
from .events import emit_domain_event, emit_security_event
from .models import (
    Account,
    AccountSuspension,
    EmailVerification,
    RefreshToken,
    UserSession,
)
from .services import EMAIL_VERIFICATION_TTL

logger = logging.getLogger("tara.identity.account_admin")

# A staff "resend" this soon after the last link is refused: it would only spam.
RESEND_COOLDOWN = timedelta(seconds=60)
EXPIRY_BATCH = 200


def _emit(event_type: str, account: Account, payload: dict, actor_id, correlation_id) -> None:
    if not getattr(settings, "IDENTITY_EMIT_ACCOUNT_ACTION_EVENTS", True):
        return
    emit_domain_event(
        event_type,
        subject_id=str(account.id),
        payload={"account_id": str(account.id), **payload},
        actor_id=str(actor_id) if actor_id else None,
        correlation_id=correlation_id,
    )


def _not_self(account: Account, actor_id) -> None:
    if actor_id and str(account.id) == str(actor_id):
        raise TaraAPIError(
            "You can't do this to your own account.", code="validation_error", http_status_code=400
        )


def _locked(account_id) -> Account:
    account = Account.objects.select_for_update().filter(id=account_id).first()
    if account is None:
        raise TaraAPIError("Account not found.", code="not_found", http_status_code=404)
    return account


def _revoke_everything(account: Account) -> int:
    """Revoke every live session and refresh token. Returns the sessions revoked."""
    now = timezone.now()
    sessions = UserSession.objects.filter(account=account, revoked_at__isnull=True).update(
        revoked_at=now
    )
    RefreshToken.objects.filter(account=account, revoked_at__isnull=True).update(revoked_at=now)
    return sessions


def active_suspension(account: Account) -> AccountSuspension | None:
    return account.suspensions.filter(lifted_at__isnull=True).first()


# ---- suspension ---------------------------------------------------------------


def suspend(
    account_id,
    *,
    actor_id,
    reason: str,
    until: datetime | None,
    idempotency_key: str,
    source: str = AccountSuspension.Source.ADMIN,
    correlation_id: str | None = None,
) -> tuple[AccountSuspension, bool]:
    """Suspend an account once per idempotency key. Returns (suspension, created).

    Revokes every session and refresh token in the same transaction. Access
    tokens already issued stay valid until they expire (at most the access TTL;
    8.14 adds a denylist).
    """
    if until is not None and until <= timezone.now():
        raise TaraAPIError(
            "The end date must be in the future.", code="validation_error", http_status_code=400
        )
    try:
        with transaction.atomic():
            account = _locked(account_id)
            replay = AccountSuspension.objects.filter(idempotency_key=idempotency_key).first()
            if replay is not None:
                if replay.account_id != account.id:
                    raise Conflict("This idempotency key was used for another account.")
                return replay, False
            _not_self(account, actor_id)
            if token_engine.roles_for(account):
                raise Conflict(
                    "Accounts with a staff role can't be suspended. Revoke the role first.",
                    code="conflict",
                )
            if account.status == Account.Status.DELETED:
                raise Conflict("This account is deleted.", code="conflict")
            if active_suspension(account) is not None:
                raise Conflict("This account is already suspended.", code="conflict")
            suspension = AccountSuspension.objects.create(
                account=account,
                reason=reason,
                until=until,
                previous_status=account.status,
                source=source,
                idempotency_key=idempotency_key,
                created_by=actor_id,
            )
            account.status = Account.Status.SUSPENDED
            account.save(update_fields=["status", "updated_at"])
            revoked = _revoke_everything(account)
            emit_security_event(
                account,
                "account_suspended",
                {
                    "suspension_id": str(suspension.id),
                    "by": str(actor_id) if actor_id else None,
                    "sessions_revoked": revoked,
                },
            )
            _emit(
                "account.suspended",
                account,
                {
                    "until": until.isoformat() if until else None,
                    "suspension_id": str(suspension.id),
                    "source": source,
                },
                actor_id,
                correlation_id,
            )
            return suspension, True
    except IntegrityError:
        # A concurrent request with the same key, or for the same account, won.
        replay = AccountSuspension.objects.filter(idempotency_key=idempotency_key).first()
        if replay is not None and str(replay.account_id) == str(account_id):
            return replay, False
        raise Conflict("This account is already suspended.", code="conflict")


def _lift(
    account: Account,
    suspension: AccountSuspension,
    *,
    actor_id,
    reason: str,
    expired: bool,
    correlation_id: str | None,
) -> None:
    """Lift ``suspension`` (inside a transaction, with ``account`` locked)."""
    now = timezone.now()
    suspension.lifted_at = now
    suspension.lifted_by = actor_id
    suspension.lift_reason = reason
    suspension.save(update_fields=["lifted_at", "lifted_by", "lift_reason"])
    if account.status == Account.Status.SUSPENDED:
        previous = suspension.previous_status
        account.status = previous if previous != Account.Status.SUSPENDED else Account.Status.ACTIVE
        account.save(update_fields=["status", "updated_at"])
    emit_security_event(
        account,
        "account_unsuspended",
        {
            "suspension_id": str(suspension.id),
            "by": str(actor_id) if actor_id else None,
            "expired": expired,
        },
    )
    _emit(
        "account.unsuspended",
        account,
        {"suspension_id": str(suspension.id), "expired": expired},
        actor_id,
        correlation_id,
    )


def unsuspend(
    account_id, *, actor_id, reason: str, correlation_id: str | None = None
) -> AccountSuspension:
    with transaction.atomic():
        account = _locked(account_id)
        _not_self(account, actor_id)
        suspension = active_suspension(account)
        if suspension is None:
            raise Conflict("This account is not suspended.", code="conflict")
        _lift(
            account,
            suspension,
            actor_id=actor_id,
            reason=reason,
            expired=False,
            correlation_id=correlation_id,
        )
    return suspension


def lift_if_expired(account: Account) -> Account:
    """Lift the account's suspension if its end date has passed (at sign-in).

    Returns the account as it now is. Cheap for everyone not suspended.
    """
    if account.status != Account.Status.SUSPENDED:
        return account
    with transaction.atomic():
        locked = _locked(account.id)
        suspension = active_suspension(locked)
        if suspension is None or suspension.until is None or suspension.until > timezone.now():
            return locked
        _lift(
            locked, suspension, actor_id=None, reason="expired", expired=True, correlation_id=None
        )
    return locked


def lift_expired_suspensions(limit: int = EXPIRY_BATCH) -> int:
    """Lift every suspension whose end date has passed (beat task). Returns the count.

    Each account commits on its own, so one failure does not undo the others.
    """
    due = list(
        AccountSuspension.objects.filter(
            lifted_at__isnull=True, until__isnull=False, until__lte=timezone.now()
        )
        .order_by("until")
        .values_list("account_id", flat=True)[:limit]
    )
    lifted = 0
    for account_id in due:
        try:
            account = Account.objects.filter(id=account_id).first()
            if account is None:
                continue
            if lift_if_expired(account).status != Account.Status.SUSPENDED:
                lifted += 1
        except Exception:  # noqa: BLE001 - the next run retries this one
            logger.exception("lifting an expired suspension failed")
    return lifted


# ---- sessions and verification ------------------------------------------------


def sign_out_everywhere(account_id, *, actor_id, correlation_id: str | None = None) -> int:
    """Revoke every session and refresh token of the account. Returns the sessions revoked."""
    with transaction.atomic():
        account = _locked(account_id)
        _not_self(account, actor_id)
        if "admin" in token_engine.roles_for(account):
            raise Conflict("An admin account can't be signed out by someone else.")
        revoked = _revoke_everything(account)
        emit_security_event(
            account,
            "signed_out_by_staff",
            {"by": str(actor_id) if actor_id else None, "sessions_revoked": revoked},
        )
        _emit("account.signed_out", account, {"sessions": revoked}, actor_id, correlation_id)
    return revoked


def resend_verification(account_id, *, actor_id, correlation_id: str | None = None) -> None:
    """Send a fresh verification link on a staff member's request."""
    with transaction.atomic():
        account = _locked(account_id)
        if account.email_verified:
            raise Conflict("This email is already verified.", code="conflict")
        if account.status == Account.Status.DELETED:
            raise Conflict("This account is deleted.", code="conflict")
        latest = account.email_verifications.order_by("-created_at").first()
        if latest is not None and latest.created_at > timezone.now() - RESEND_COOLDOWN:
            raise TaraAPIError(
                "A link was sent a moment ago. Try again in a minute.",
                code="throttled",
                http_status_code=429,
            )
        raw_token = secrets.token_urlsafe(32)
        EmailVerification.objects.create(
            account=account,
            token_hash=token_engine.hash_token(raw_token),
            expires_at=timezone.now() + EMAIL_VERIFICATION_TTL,
        )
        emit_security_event(
            account, "verification_resent_by_staff", {"by": str(actor_id) if actor_id else None}
        )
        _emit("account.verification.resent", account, {}, actor_id, correlation_id)
        email = account.email
        transaction.on_commit(lambda: send_verification_email(email, raw_token))
