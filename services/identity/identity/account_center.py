"""Settings-centre use cases (plan 08 wave 3C): login activity, recognised
devices, new-device sign-in alerts, deactivation and reactivation, and the
birthday and gender others may see.

Same rules as services.py: a state change and its outbox event commit
together, and mail goes out only on commit.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from tara_common.auth import mint_internal_token
from tara_common.exceptions import TaraAPIError

from . import emails
from . import tokens as token_engine
from .events import emit_domain_event, emit_security_event
from .models import Account, PersonalVisibility, SecurityEvent, TwoFactorSecret

logger = logging.getLogger("tara.identity.account_center")

# What the owner sees in "Login activity". Internal bookkeeping (grace
# replays, staff actions with staff ids) stays out.
ACTIVITY_TYPES = (
    "login_succeeded",
    "login_failed",
    "login_blocked",
    "login_new_device",
    "logout",
    "session_revoked",
    "device_removed",
    "password_changed",
    "password_reset_requested",
    "password_reset_completed",
    "email_change_requested",
    "email_changed",
    "email_verified",
    "google_linked",
    "google_unlinked",
    "phone_verified",
    "phone_removed",
    "reauth_failed",
    "refresh_reuse_detected",
    "two_factor_enabled",
    "two_factor_disabled",
    "two_factor_failed",
    "two_factor_recovery_used",
    "two_factor_recovery_regenerated",
    "account_deactivated",
    "account_reactivated",
    "account_deletion_scheduled",
    "account_deletion_cancelled",
)
ACTIVITY_PAGE = 30


def _not_found(what: str) -> TaraAPIError:
    return TaraAPIError(f"{what} not found.", code="not_found", http_status_code=404)


# ---- login activity and devices ---------------------------------------------


def security_activity(account: Account, *, before: str | None = None) -> dict:
    """The owner's own security log, newest first, a page at a time."""
    qs = SecurityEvent.objects.filter(account=account, type__in=ACTIVITY_TYPES)
    if before:
        anchor = SecurityEvent.objects.filter(account=account, id=before).first()
        if anchor is None:
            raise TaraAPIError("Unknown cursor.", code="validation_error", http_status_code=400)
        qs = qs.filter(created_at__lt=anchor.created_at)
    rows = list(qs.order_by("-created_at")[: ACTIVITY_PAGE + 1])
    more = len(rows) > ACTIVITY_PAGE
    rows = rows[:ACTIVITY_PAGE]
    return {
        "results": [
            {
                "id": str(row.id),
                "type": row.type,
                "ip_region": row.ip_region,
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ],
        "next": str(rows[-1].id) if more and rows else None,
    }


def devices(account: Account, *, current_session_id: str | None) -> list[dict]:
    """Devices that signed in, with how many live sessions each still has."""
    current = account.sessions.filter(id=current_session_id).first() if current_session_id else None
    current_device = str(current.device_id) if current and current.device_id else None
    out = []
    for device in account.devices.order_by("-last_seen_at"):
        live = account.sessions.filter(device=device, revoked_at__isnull=True).order_by(
            "-last_seen_at"
        )
        newest = live.first()
        out.append(
            {
                "id": str(device.id),
                "platform": device.platform,
                "label": device.label,
                "created_at": device.created_at.isoformat(),
                "last_seen_at": (
                    newest.last_seen_at if newest else device.last_seen_at
                ).isoformat(),
                "ip_region": newest.ip_region if newest else "",
                "active_sessions": live.count(),
                "is_current": str(device.id) == current_device,
            }
        )
    return out


def remove_device(
    account: Account, device_id: str, *, current_session_id: str | None, ip_region: str = ""
) -> int:
    """Sign the device out (every session on it) and forget it.

    The next sign-in from it counts as a new device again (and alerts).
    """
    device = account.devices.filter(id=device_id).first()
    if device is None:
        raise _not_found("Device")
    if (
        current_session_id
        and account.sessions.filter(id=current_session_id, device=device).exists()
    ):
        raise TaraAPIError(
            "Use 'Log out' to sign this device out.",
            code="validation_error",
            http_status_code=400,
        )
    with transaction.atomic():
        sessions = list(account.sessions.filter(device=device, revoked_at__isnull=True))
        for session in sessions:
            token_engine.revoke_session(session)
        device.delete()
        emit_security_event(
            account, "device_removed", {"sessions": len(sessions)}, ip_region=ip_region
        )
    return len(sessions)


def alert_new_device(
    account: Account, *, device_label: str, ip_region: str, first_device: bool
) -> None:
    """Called inside the sign-in transaction when the device row was just made."""
    emit_security_event(account, "login_new_device", {}, ip_region=ip_region)
    # The very first device is the one the account was created on: no alert.
    if first_device or not account.login_alerts:
        return
    email = account.email
    when = timezone.now()
    transaction.on_commit(
        lambda: emails.send_login_alert(email, device=device_label, region=ip_region, when=when)
    )


# ---- deactivation -----------------------------------------------------------


def _emit_lifecycle(event_type: str, account: Account, correlation_id: str | None) -> None:
    if not getattr(settings, "IDENTITY_EMIT_ACCOUNT_ACTION_EVENTS", True):
        return
    emit_domain_event(
        event_type,
        subject_id=str(account.id),
        payload={"account_id": str(account.id)},
        actor_id=str(account.id),
        correlation_id=correlation_id,
    )


def emit_presence_changed(account: Account, *, correlation_id: str | None = None) -> None:
    """``account.presence.updated`` (inside the caller's transaction)."""
    if not getattr(settings, "IDENTITY_EMIT_ACCOUNT_ACTION_EVENTS", True):
        return
    emit_domain_event(
        "account.presence.updated",
        subject_id=str(account.id),
        payload={"account_id": str(account.id), "show_presence": bool(account.show_presence)},
        actor_id=str(account.id),
        correlation_id=correlation_id,
    )


DEACTIVATE_CONFIRMATION = "DEACTIVATE"


def deactivate(
    account: Account,
    *,
    password: str,
    confirm: str = "",
    ip_region: str = "",
    correlation_id: str | None = None,
) -> int:
    """The owner deactivates their account: every session ends, sign-in reactivates it.

    Re-authenticated with the password. An account without one (Google only)
    types the confirmation word instead; the change is undone by signing in.
    """
    from .account_security import _field_error, _require_password

    if account.has_usable_password():
        _require_password(account, password, field="password", ip_region=ip_region)
    elif confirm.strip().upper() != DEACTIVATE_CONFIRMATION:
        raise _field_error(
            "confirm", "confirmation_required", f"Type {DEACTIVATE_CONFIRMATION} to confirm."
        )
    with transaction.atomic():
        locked = Account.objects.select_for_update().get(pk=account.pk)
        if locked.status != Account.Status.ACTIVE:
            raise TaraAPIError(
                "Only an active account can be deactivated.",
                code="conflict",
                http_status_code=409,
            )
        locked.status = Account.Status.DEACTIVATED
        locked.save(update_fields=["status", "updated_at"])
        sessions = list(locked.sessions.filter(revoked_at__isnull=True))
        for session in sessions:
            token_engine.revoke_session(session)
        emit_security_event(
            locked, "account_deactivated", {"sessions": len(sessions)}, ip_region=ip_region
        )
        _emit_lifecycle("account.deactivated", locked, correlation_id)
        email = locked.email
        transaction.on_commit(lambda: emails.send_deactivated_notice(email))
    account.status = Account.Status.DEACTIVATED
    return len(sessions)


def reactivate_if_deactivated(
    account: Account, *, ip_region: str = "", correlation_id: str | None = None
) -> Account:
    """Sign-in with the right credentials brings a deactivated account back,
    and cancels a deletion still in its grace period."""
    if account.status != Account.Status.DEACTIVATED:
        return account
    with transaction.atomic():
        locked = (
            Account.objects.select_for_update()
            .filter(pk=account.pk, status=Account.Status.DEACTIVATED)
            .first()
        )
        if locked is not None:
            cancelled = locked.deletion_scheduled_for is not None
            locked.status = Account.Status.ACTIVE
            locked.deletion_scheduled_for = None
            locked.save(update_fields=["status", "deletion_scheduled_for", "updated_at"])
            emit_security_event(locked, "account_reactivated", {}, ip_region=ip_region)
            if cancelled:
                emit_security_event(locked, "account_deletion_cancelled", {}, ip_region=ip_region)
                email = locked.email
                transaction.on_commit(lambda: emails.send_deletion_cancelled_notice(email))
            _emit_lifecycle("account.reactivated", locked, correlation_id)
    account.refresh_from_db()
    return account


# ---- deletion (30-day grace, then erasure) ------------------------------------------

DELETION_GRACE = timedelta(days=30)
DELETE_CONFIRMATION = "DELETE"
PURGE_BATCH = 100


def schedule_deletion(
    account: Account,
    *,
    password: str,
    confirm: str = "",
    ip_region: str = "",
    correlation_id: str | None = None,
) -> dict:
    """The owner asks to delete the account: it is deactivated now (hidden
    everywhere, every session ends) and erased after ``DELETION_GRACE`` unless
    they sign in before then. Re-authenticated like deactivation."""
    from .account_security import _field_error, _require_password

    if account.has_usable_password():
        _require_password(account, password, field="password", ip_region=ip_region)
    elif confirm.strip().upper() != DELETE_CONFIRMATION:
        raise _field_error(
            "confirm", "confirmation_required", f"Type {DELETE_CONFIRMATION} to confirm."
        )
    with transaction.atomic():
        locked = Account.objects.select_for_update().get(pk=account.pk)
        if locked.status != Account.Status.ACTIVE:
            raise TaraAPIError(
                "Only an active account can be deleted.", code="conflict", http_status_code=409
            )
        when = timezone.now() + DELETION_GRACE
        locked.status = Account.Status.DEACTIVATED
        locked.deletion_scheduled_for = when
        locked.save(update_fields=["status", "deletion_scheduled_for", "updated_at"])
        sessions = list(locked.sessions.filter(revoked_at__isnull=True))
        for session in sessions:
            token_engine.revoke_session(session)
        emit_security_event(
            locked,
            "account_deletion_scheduled",
            {"sessions": len(sessions), "scheduled_for": when.isoformat()},
            ip_region=ip_region,
        )
        # Hidden during the grace period exactly as a deactivated account is.
        _emit_lifecycle("account.deactivated", locked, correlation_id)
        email = locked.email
        transaction.on_commit(lambda: emails.send_deletion_scheduled_notice(email, when=when))
    account.status = Account.Status.DEACTIVATED
    account.deletion_scheduled_for = when
    return {"revoked_sessions": len(sessions), "deletion_scheduled_for": when.isoformat()}


def erase_account(account_id, *, now: datetime | None = None) -> bool:
    """Erase one account whose grace period ended. Idempotent: False when it is
    not (or no longer) due, e.g. its owner signed in meanwhile.

    The row stays as a tombstone (id, status ``deleted``, dates) so the id is
    never reused and audit rows keep their key; every personal field is wiped,
    and every credential, session, device, link and code is deleted. Security
    events stay, without their metadata or region (the audit trail).
    """
    now = now or timezone.now()
    with transaction.atomic():
        account = (
            Account.objects.select_for_update()
            .filter(
                pk=account_id,
                status=Account.Status.DEACTIVATED,
                deletion_scheduled_for__lte=now,
            )
            .first()
        )
        if account is None:
            return False
        email = account.email
        for model in _ERASED_MODELS():
            model.objects.filter(account=account).delete()
        SecurityEvent.objects.filter(account=account).update(metadata={}, ip_region="")
        account.email = f"deleted+{account.id}@deleted.invalid"
        account.email_verified = False
        account.set_unusable_password()
        account.phone = ""
        account.phone_verified_at = None
        account.date_of_birth = None
        account.gender = ""
        account.gender_custom = ""
        account.is_staff = False
        account.is_superuser = False
        account.is_active = False
        account.status = Account.Status.DELETED
        account.deleted_at = now
        account.deletion_scheduled_for = None
        account.save()
        account.groups.clear()
        account.user_permissions.clear()
        emit_security_event(account, "account_deleted", {})
        if getattr(settings, "IDENTITY_EMIT_ACCOUNT_ACTION_EVENTS", True):
            emit_domain_event(
                "account.deleted",
                subject_id=str(account.id),
                payload={"account_id": str(account.id)},
                actor_id=None,
            )
        transaction.on_commit(lambda: emails.send_deleted_notice(email))
    return True


def _ERASED_MODELS():  # noqa: N802 - a constant list, built lazily
    from . import models as m

    return (
        m.RefreshToken,
        m.UserSession,
        m.Device,
        m.SocialIdentity,
        m.EmailChangeRequest,
        m.EmailVerification,
        m.PasswordReset,
        m.PhoneVerification,
        m.TwoFactorRecoveryCode,
        TwoFactorSecret,
        m.AccountRole,
    )


def purge_due_deletions(*, now: datetime | None = None) -> int:
    """Erase the accounts whose deletion grace ended (the beat task)."""
    now = now or timezone.now()
    due = list(
        Account.objects.filter(
            status=Account.Status.DEACTIVATED, deletion_scheduled_for__lte=now
        ).values_list("id", flat=True)[:PURGE_BATCH]
    )
    return sum(1 for account_id in due if erase_account(account_id, now=now))


# ---- birthday and gender, as others see them -------------------------------


def _relationship(a: str, b: str) -> dict | None:
    """Graph's relationship answer; None when graph can't be reached."""
    token = mint_internal_token(issuer="identity", audience="graph-internal")
    query = urllib.parse.urlencode({"a": a, "b": b})
    request = urllib.request.Request(  # noqa: S310 - internal URL from settings
        f"{settings.GRAPH_INTERNAL_URL}/internal/v1/relationship/?{query}",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=settings.GRAPH_CALL_TIMEOUT) as resp:  # noqa: S310
            body = json.loads(resp.read().decode())
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        logger.warning("graph relationship lookup failed", exc_info=True)
        return None
    data = body.get("data") if isinstance(body, dict) else None
    return data if isinstance(data, dict) else None


def _visible(level: str, *, is_owner: bool, friend: bool) -> bool:
    if is_owner:
        return True
    return level == PersonalVisibility.FRIENDS and friend


def _birthday(dob: date | None) -> dict | None:
    # Decision 5.3: day and month only, never the year.
    return {"month": dob.month, "day": dob.day} if dob else None


def personal_details(viewer_id: str, account_id: str) -> dict:
    """Birthday (day and month) and gender, each only when its audience allows."""
    account = Account.objects.filter(id=account_id).first()
    if account is None or not account.is_usable:
        raise _not_found("Account")
    is_owner = str(viewer_id) == str(account.id)
    friend = False
    if not is_owner:
        # Asked every time, not only when a field is shared with friends: across
        # a block (either way) the account does not exist for the viewer, as
        # its profile does not. Graph down: nothing is shown (fail closed).
        rel = _relationship(str(viewer_id), str(account.id))
        if rel is not None and rel.get("blocked_either_way"):
            raise _not_found("Account")
        friend = bool(rel and rel.get("are_friends"))
    gender = None
    if account.gender and _visible(account.gender_visibility, is_owner=is_owner, friend=friend):
        gender = {"value": account.gender, "custom": account.gender_custom or None}
    birthday = None
    if _visible(account.birthday_visibility, is_owner=is_owner, friend=friend):
        birthday = _birthday(account.date_of_birth)
    return {"account_id": str(account.id), "birthday": birthday, "gender": gender}
