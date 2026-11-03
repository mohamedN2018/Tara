"""Admin business logic: flags, roles, service-health overview."""

from __future__ import annotations

import logging

import requests
from django.conf import settings

from tara_common.exceptions import Conflict, TaraAPIError
from tara_resilience import CircuitBreaker, CircuitOpenError

from . import identity_client
from .models import AuditLog, FeatureFlag, ServiceHealthSnapshot

logger = logging.getLogger("tara.admin.services")
_breakers: dict[str, CircuitBreaker] = {}


def audit(actor_id: str, action: str, target: str = "", **metadata) -> None:
    AuditLog.objects.create(actor_id=actor_id, action=action, target=target, metadata=metadata)


def set_flag(
    key: str, *, enabled: bool, rollout_pct: int, description: str, actor_id: str
) -> FeatureFlag:
    flag, _ = FeatureFlag.objects.update_or_create(
        key=key,
        defaults={
            "enabled": enabled,
            "rollout_pct": rollout_pct,
            "description": description,
            "updated_by": actor_id,
        },
    )
    audit(actor_id, "feature_flag.set", target=key, enabled=enabled, rollout_pct=rollout_pct)
    return flag


def grant_role(account_id: str, role: str, actor_id: str) -> dict:
    account = identity_client.grant(account_id, role, actor_id)
    audit(actor_id, "role.grant", target=str(account_id), role=role)
    return account


def revoke_role(account_id: str, role: str, actor_id: str) -> dict:
    if str(account_id) == str(actor_id) and role == "admin":
        raise TaraAPIError(
            "You can't remove your own admin role.",
            code="validation_error",
            http_status_code=400,
        )
    account = identity_client.account_roles(account_id)
    if role in account["bridged_roles"]:
        raise Conflict("This role comes from staff or superuser status.", code="conflict")
    account = identity_client.revoke(account_id, role, actor_id)
    audit(actor_id, "role.revoke", target=str(account_id), role=role)
    return account


def _check_one(service: str, url: str) -> dict:
    breaker = _breakers.setdefault(service, CircuitBreaker(name=service, recovery_timeout=15.0))

    def _call():
        resp = requests.get(url, timeout=settings.HEALTH_TIMEOUT)
        return resp

    try:
        resp = breaker.call(_call)
        status = "ready" if resp.status_code == 200 else "not_ready"
        latency = int(resp.elapsed.total_seconds() * 1000)
    except CircuitOpenError:
        status, latency = "unreachable", None
    except Exception:  # noqa: BLE001
        status, latency = "unreachable", None
    ServiceHealthSnapshot.objects.create(service=service, status=status, latency_ms=latency)
    return {"service": service, "status": status, "latency_ms": latency}


def service_health() -> list[dict]:
    """Poll every service's /readyz (circuit-broken). One slow service can't block the rest."""
    return [_check_one(svc, url) for svc, url in settings.HEALTH_TARGETS.items()]
