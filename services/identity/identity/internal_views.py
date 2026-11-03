"""Service-to-service API. Not routed by the gateway.

Identity owns roles: the Admin service changes them here, and access tokens read
them at issue time, so a change reaches the ``roles`` claim on the next refresh.

Caller-specific secrets (roadmap 1.0d). Every service holds the shared
``INTERNAL_JWT_SECRET``, so a token signed with it proves nothing about the
caller, whatever its ``iss`` says. These endpoints grant roles and list staff,
so they accept only a token signed with a secret that identity shares with one
named caller (picked by the token's ``iss``), issued by that caller, for the
``identity.roles`` audience. The shared secret is never tried here.
"""

from __future__ import annotations

import logging
import uuid

import jwt
from django.conf import settings
from django.db import connection, transaction
from django.db.models import Q
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tara_common import capabilities as registry
from tara_common.auth import verify_internal_token
from tara_common.exceptions import TaraAPIError
from tara_common.pagination import CursorPagination
from tara_common.responses import data_response

from . import account_admin
from .events import emit_domain_event, emit_security_event
from .models import Account, AccountRole, AccountSuspension, RoleCapability
from .services import list_sessions
from .tokens import bridged_roles, roles_for

logger = logging.getLogger("tara.identity.internal")

MAX_ROLE_HOLDERS = 200
ROLES_AUDIENCE = "identity.roles"

# Caller (the token's ``iss``) -> the setting with the secret that identity shares
# with that caller alone. A new caller (notification in 2.19, moderation in 8.4)
# gets its own secret here and is allowed only on the views it needs.
CALLER_SECRET_SETTINGS = {"admin": "ADMIN_IDENTITY_SECRET"}


def _invalid_token() -> TaraAPIError:
    return TaraAPIError("Invalid internal token.", code="unauthenticated", http_status_code=401)


def _caller_secret(caller: str) -> str | None:
    setting = CALLER_SECRET_SETTINGS.get(caller)
    secret = (getattr(settings, setting, "") or "") if setting else ""
    if not secret:
        logger.error("no secret configured for internal caller", extra={"caller": caller})
        return None
    if secret == getattr(settings, "TARA_INTERNAL_JWT_SECRET", None):
        # Every service could sign with it, which would undo the whole point.
        logger.error("caller secret equals the shared internal secret", extra={"caller": caller})
        return None
    return secret


def _require_internal(request: Request, *, callers: tuple[str, ...], audience: str) -> str:
    """Return the verified caller, or raise 401. Fails closed on any doubt."""
    parts = request.META.get("HTTP_AUTHORIZATION", "").split()
    if len(parts) != 2 or parts[0] != "Bearer":
        raise TaraAPIError("Internal auth required.", code="unauthenticated", http_status_code=401)
    token = parts[1]
    try:
        # The claimed caller only selects which key to try. The signature made with
        # that caller's own secret, and the issuer check, are what prove it.
        claimed = jwt.decode(token, options={"verify_signature": False}).get("iss")
    except jwt.PyJWTError as exc:
        raise _invalid_token() from exc
    if not isinstance(claimed, str) or claimed not in callers:
        logger.warning(
            "internal token from a caller not allowed here", extra={"path": request.path}
        )
        raise _invalid_token()
    secret = _caller_secret(claimed)
    if secret is None:
        raise _invalid_token()
    try:
        verify_internal_token(
            token, secret=secret, expected_issuer=claimed, expected_audience=audience
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "internal token rejected", extra={"caller": claimed, "reason": type(exc).__name__}
        )
        raise _invalid_token() from exc
    return claimed


def _account_data(account: Account) -> dict:
    return {
        "account_id": str(account.id),
        "email": account.email,
        "roles": roles_for(account),
        # From is_staff / is_superuser: they can't be revoked through the role API.
        "bridged_roles": bridged_roles(account),
    }


def _get_account(account_id) -> Account:
    account = Account.objects.filter(id=account_id).first()
    if account is None:
        raise TaraAPIError("Account not found.", code="not_found", http_status_code=404)
    return account


def _emit_audit_event(
    request: Request, event_type: str, *, subject_id: str, payload: dict, actor_id
) -> None:
    """Record an audit-worthy decision on the outbox (inside the caller's transaction).

    The correlation id is admin's request id: admin forwards it, and the edge,
    not the client, set it on admin's request. ``IDENTITY_EMIT_AUDIT_EVENTS``
    is the emission flag of roadmap 3.3: admin's consumer ships one release first.
    """
    if not getattr(settings, "IDENTITY_EMIT_AUDIT_EVENTS", True):
        return
    emit_domain_event(
        event_type,
        subject_id=subject_id,
        payload=payload,
        actor_id=str(actor_id) if actor_id else None,
        correlation_id=getattr(request, "request_id", None),
    )


class _RoleSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=AccountRole.Role.values)
    actor_id = serializers.UUIDField()


class _InternalView(APIView):
    permission_classes = [AllowAny]
    authentication_classes: list = []
    # Role grants, account lookup and staff lists: only admin may call them.
    internal_callers: tuple[str, ...] = ("admin",)
    internal_audience = ROLES_AUDIENCE

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        _require_internal(request, callers=self.internal_callers, audience=self.internal_audience)


class AccountLookupView(_InternalView):
    def get(self, request: Request) -> Response:
        email = request.query_params.get("email", "").strip()
        account = Account.objects.filter(email__iexact=email).first() if email else None
        if account is None:
            raise TaraAPIError("Account not found.", code="not_found", http_status_code=404)
        return data_response(_account_data(account))


class RoleHoldersView(_InternalView):
    def get(self, request: Request) -> Response:
        accounts = (
            Account.objects.filter(
                Q(role_grants__isnull=False) | Q(is_staff=True) | Q(is_superuser=True)
            )
            .distinct()
            .prefetch_related("role_grants")
            .order_by("email")[:MAX_ROLE_HOLDERS]
        )
        return data_response([_account_data(a) for a in accounts])


class AccountRolesView(_InternalView):
    def get(self, request: Request, account_id: str) -> Response:
        return data_response(_account_data(_get_account(account_id)))

    def post(self, request: Request, account_id: str) -> Response:
        serializer = _RoleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        role, actor = serializer.validated_data["role"], serializer.validated_data["actor_id"]
        account = _get_account(account_id)
        with transaction.atomic():
            _, created = AccountRole.objects.get_or_create(
                account=account, role=role, defaults={"granted_by": actor}
            )
            if created:
                emit_security_event(
                    account, "role_granted", {"role": role, "granted_by": str(actor)}
                )
                _emit_audit_event(
                    request,
                    "account.role.granted",
                    subject_id=str(account.id),
                    payload={"account_id": str(account.id), "role": role},
                    actor_id=actor,
                )
        return data_response(_account_data(account), status=201)

    def delete(self, request: Request, account_id: str) -> Response:
        serializer = _RoleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        role, actor = serializer.validated_data["role"], serializer.validated_data["actor_id"]
        account = _get_account(account_id)
        with transaction.atomic():
            deleted, _ = AccountRole.objects.filter(account=account, role=role).delete()
            if deleted:
                emit_security_event(
                    account, "role_revoked", {"role": role, "revoked_by": str(actor)}
                )
                _emit_audit_event(
                    request,
                    "account.role.revoked",
                    subject_id=str(account.id),
                    payload={"account_id": str(account.id), "role": role},
                    actor_id=actor,
                )
        return data_response(_account_data(account))


# ---- capability matrix (roadmap 8.12) ---------------------------------------

CAPABILITY_STATES = ("grant", "revoke", "default")
MAX_MATRIX_CHANGES = 200
MATRIX_LOCK_KEY = 0x7A_7243_4150  # any constant unique within identity_db


def matrix_data() -> dict:
    """Everything the matrix editor needs: registry, defaults, overrides, effective."""
    rows = list(RoleCapability.objects.order_by("role", "capability"))
    overrides = {(row.role, row.capability): row.granted for row in rows}
    return {
        "capabilities": [
            {"key": c.key, "namespace": c.namespace} for c in registry.CAPABILITIES.values()
        ],
        "roles": list(registry.ROLES),
        "locked_roles": sorted(registry.LOCKED_ROLES),
        "defaults": {
            role: sorted(registry.DEFAULT_ROLE_CAPABILITIES.get(role, ()))
            for role in registry.ROLES
        },
        "overrides": [
            {
                "role": row.role,
                "capability": row.capability,
                "granted": row.granted,
                "updated_by": str(row.updated_by) if row.updated_by else None,
                "updated_at": row.updated_at.isoformat(),
            }
            for row in rows
        ],
        "effective": {
            role: sorted(registry.role_capabilities(role, overrides)) for role in registry.ROLES
        },
        "implies": {key: sorted(implied) for key, implied in registry.IMPLIES.items()},
    }


class _CapabilityChangeSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=list(registry.ROLES))
    capability = serializers.ChoiceField(choices=list(registry.CAPABILITIES))
    state = serializers.ChoiceField(choices=CAPABILITY_STATES)

    def validate_role(self, role: str) -> str:
        if role in registry.LOCKED_ROLES:
            raise serializers.ValidationError("This role always holds every capability.")
        return role


class _MatrixUpdateSerializer(serializers.Serializer):
    actor_id = serializers.UUIDField()
    changes = _CapabilityChangeSerializer(many=True, allow_empty=False)

    def validate_changes(self, changes: list[dict]) -> list[dict]:
        if len(changes) > MAX_MATRIX_CHANGES:
            raise serializers.ValidationError(f"At most {MAX_MATRIX_CHANGES} changes at once.")
        cells = [(c["role"], c["capability"]) for c in changes]
        if len(set(cells)) != len(cells):
            raise serializers.ValidationError("Each cell may appear once.")
        return changes


class CapabilityMatrixView(_InternalView):
    """GET the role x capability matrix; PUT a batch of cell changes.

    Setting a cell to the state it already has is a no-op, so the same batch
    sent twice emits nothing the second time. Each real change emits one
    ``capability.matrix.changed`` in the same transaction. Tokens pick the new
    matrix up at their next refresh (at most the access-token TTL later).
    """

    def get(self, request: Request) -> Response:
        return data_response(matrix_data())

    def put(self, request: Request) -> Response:
        serializer = _MatrixUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        actor = serializer.validated_data["actor_id"]
        with transaction.atomic():
            # Serialise editors (row locks cannot cover cells that have no row
            # yet), so each event's "previous" is what really was.
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_xact_lock(%s)", [MATRIX_LOCK_KEY])
            current = {
                (row.role, row.capability): row
                for row in RoleCapability.objects.select_for_update()
            }
            for change in serializer.validated_data["changes"]:
                role, key, state = change["role"], change["capability"], change["state"]
                row = current.get((role, key))
                previous = "default" if row is None else ("grant" if row.granted else "revoke")
                if state == previous:
                    continue
                if state == "default":
                    row.delete()
                elif row is None:
                    RoleCapability.objects.create(
                        role=role, capability=key, granted=state == "grant", updated_by=actor
                    )
                else:
                    row.granted = state == "grant"
                    row.updated_by = actor
                    row.save(update_fields=["granted", "updated_by", "updated_at"])
                _emit_audit_event(
                    request,
                    "capability.matrix.changed",
                    subject_id=role,
                    payload={"role": role, "capability": key, "state": state, "previous": previous},
                    actor_id=actor,
                )
        return data_response(matrix_data())


# ---- user management console (roadmap 8.6, identity side of 8.4) -------------
#
# Results and the overview carry masked contact details only. The full email,
# the phone number and the session list come from ``personal/``, which admin
# calls only after writing the staff member's reason to its audit log.

SEARCH_MIN_LENGTH = 2
MAX_SUMMARIES = 50


def mask_email(email: str) -> str:
    """``layla@example.com`` -> ``l****@e******.com``: enough to tell accounts apart."""
    local, _, domain = (email or "").partition("@")
    if not domain:
        return "*" * len(local)
    host, dot, tld = domain.rpartition(".")
    if not dot:
        host, tld = domain, ""
    masked_host = (host[:1] + "*" * max(len(host) - 1, 1)) + (f".{tld}" if tld else "")
    return f"{local[:1]}{'*' * max(len(local) - 1, 1)}@{masked_host}"


def mask_phone(phone: str) -> str:
    """Keep the leading ``+`` and the last two digits."""
    if not phone:
        return ""
    plus = "+" if phone.startswith("+") else ""
    digits = phone.lstrip("+")
    return plus + "*" * max(len(digits) - 2, 0) + digits[-2:]


def _iso(value) -> str | None:
    return value.isoformat() if value else None


def _summary(account: Account) -> dict:
    return {
        "account_id": str(account.id),
        "email_masked": mask_email(account.email),
        "status": account.status,
        "email_verified": account.email_verified,
        "created_at": _iso(account.created_at),
    }


def _suspension_data(suspension: AccountSuspension | None) -> dict | None:
    if suspension is None:
        return None
    return {
        "id": str(suspension.id),
        "reason": suspension.reason,
        "until": _iso(suspension.until),
        "source": suspension.source,
        "created_at": _iso(suspension.created_at),
        "created_by": str(suspension.created_by) if suspension.created_by else None,
    }


def _overview(account: Account) -> dict:
    return {
        **_summary(account),
        "phone_verified": account.phone_verified,
        "phone_masked": mask_phone(account.phone) if account.phone_verified else "",
        "last_login_at": _iso(account.last_login_at),
        "language": account.language,
        "roles": roles_for(account),
        "bridged_roles": bridged_roles(account),
        "active_sessions": list_sessions(account).count(),
        "google_linked": account.social_identities.filter(provider="google").exists(),
        "suspension": _suspension_data(account_admin.active_suspension(account)),
    }


class _SearchPagination(CursorPagination):
    page_size = 20
    max_page_size = 50


class AccountSearchView(_InternalView):
    """Accounts by id (exact) or by email (prefix; a whole address is its own prefix).

    Keyset-paginated on the unique email, so a page never repeats or skips a row
    while accounts are added. Handles and names live in profile; admin asks it.
    """

    def get(self, request: Request) -> Response:
        q = request.query_params.get("q", "").strip()
        try:
            account_id = uuid.UUID(q)
        except ValueError:
            account_id = None
        if account_id is not None:
            rows = Account.objects.filter(id=account_id)
        elif SEARCH_MIN_LENGTH <= len(q) <= 254:
            rows = Account.objects.filter(email__startswith=q.lower())
        else:
            raise TaraAPIError(
                f"Search for an account id, or {SEARCH_MIN_LENGTH} or more characters of an email.",
                code="validation_error",
                http_status_code=400,
            )
        paginator = _SearchPagination()
        page = paginator.paginate_queryset(rows.order_by("email"), request, view=self)
        return paginator.get_paginated_response([_summary(a) for a in page])


class _IdsSerializer(serializers.Serializer):
    ids = serializers.ListField(
        child=serializers.UUIDField(), allow_empty=True, max_length=MAX_SUMMARIES
    )


class AccountSummariesView(_InternalView):
    """Summaries for accounts found elsewhere (a profile search), in the order asked."""

    def post(self, request: Request) -> Response:
        serializer = _IdsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ids = serializer.validated_data["ids"]
        found = {a.id: a for a in Account.objects.filter(id__in=ids)}
        return data_response([_summary(found[i]) for i in ids if i in found])


class AccountOverviewView(_InternalView):
    def get(self, request: Request, account_id: str) -> Response:
        return data_response(_overview(_get_account(account_id)))


class AccountPersonalDataView(_InternalView):
    """Full email, phone and live sessions. Admin audits every call before making it."""

    def get(self, request: Request, account_id: str) -> Response:
        account = _get_account(account_id)
        sessions = [
            {
                "id": str(s.id),
                "platform": s.device.platform if s.device else "web",
                "user_agent": s.user_agent,
                "ip_region": s.ip_region,
                "created_at": _iso(s.created_at),
                "last_seen_at": _iso(s.last_seen_at),
            }
            for s in list_sessions(account)[:50]
        ]
        return data_response(
            {
                "account_id": str(account.id),
                "email": account.email,
                "phone": account.phone if account.phone_verified else "",
                "sessions": sessions,
            }
        )


class _ActorSerializer(serializers.Serializer):
    actor_id = serializers.UUIDField()


class _SuspendSerializer(_ActorSerializer):
    reason = serializers.CharField(min_length=3, max_length=500)
    until = serializers.DateTimeField(required=False, allow_null=True, default=None)
    idempotency_key = serializers.CharField(min_length=8, max_length=100)
    source = serializers.ChoiceField(
        choices=AccountSuspension.Source.values, default=AccountSuspension.Source.ADMIN
    )


class _UnsuspendSerializer(_ActorSerializer):
    reason = serializers.CharField(min_length=3, max_length=500)


def _correlation(request: Request) -> str | None:
    return getattr(request, "request_id", None)


class AccountSuspensionView(_InternalView):
    """POST suspends (once per idempotency key); DELETE lifts the active suspension."""

    def post(self, request: Request, account_id: str) -> Response:
        serializer = _SuspendSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        v = serializer.validated_data
        suspension, created = account_admin.suspend(
            account_id,
            actor_id=v["actor_id"],
            reason=v["reason"],
            until=v["until"],
            idempotency_key=v["idempotency_key"],
            source=v["source"],
            correlation_id=_correlation(request),
        )
        return data_response(
            {"suspension": _suspension_data(suspension), "created": created},
            status=201 if created else 200,
        )

    def delete(self, request: Request, account_id: str) -> Response:
        serializer = _UnsuspendSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        v = serializer.validated_data
        suspension = account_admin.unsuspend(
            account_id,
            actor_id=v["actor_id"],
            reason=v["reason"],
            correlation_id=_correlation(request),
        )
        return data_response({"suspension_id": str(suspension.id), "lifted": True})


class AccountSignOutView(_InternalView):
    def post(self, request: Request, account_id: str) -> Response:
        serializer = _ActorSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        revoked = account_admin.sign_out_everywhere(
            account_id,
            actor_id=serializer.validated_data["actor_id"],
            correlation_id=_correlation(request),
        )
        return data_response({"sessions_revoked": revoked})


class AccountVerificationView(_InternalView):
    def post(self, request: Request, account_id: str) -> Response:
        serializer = _ActorSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        account_admin.resend_verification(
            account_id,
            actor_id=serializer.validated_data["actor_id"],
            correlation_id=_correlation(request),
        )
        return data_response({"sent": True}, status=202)
