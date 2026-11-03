"""Admin business logic: flags, roles, capability matrix, health and statistics."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

import requests
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from tara_common.auth import mint_internal_token
from tara_common.exceptions import Conflict, TaraAPIError
from tara_common.middleware import current_request_id
from tara_resilience import CircuitBreaker, CircuitOpenError

from . import audit, identity_client
from .models import FeatureFlag, PlatformStat, ServiceHealthSnapshot

logger = logging.getLogger("tara.admin.services")
_breakers: dict[str, CircuitBreaker] = {}

PLATFORM_METRICS = ("accounts", "posts", "active_conversations", "listings", "open_cases")


def _breaker(name: str) -> CircuitBreaker:
    return _breakers.setdefault(name, CircuitBreaker(name=name, recovery_timeout=15.0))


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
    # Same transaction as the change (ATOMIC_REQUESTS): no flag change without its row.
    audit.record(
        "feature_flag.changed",
        actor_id=actor_id,
        target_type="feature_flag",
        target_id=key,
        request_id=current_request_id() or "",
        detail={"enabled": enabled, "rollout_pct": rollout_pct},
    )
    return flag


# Role grants and capability changes are audited from identity's events
# (account.role.*, capability.matrix.changed): identity owns the decision, so
# its outbox row commits with it, and a grant made elsewhere is audited too.


def grant_role(account_id: str, role: str, actor_id: str) -> dict:
    return identity_client.grant(account_id, role, actor_id)


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
    return identity_client.revoke(account_id, role, actor_id)


# ---- service health (polled by beat, read by the API) -----------------------


def _check_one(service: str, url: str) -> dict:
    """Poll one readiness endpoint. Runs in a worker thread: no database here."""

    def _call():
        return requests.get(url, timeout=settings.HEALTH_TIMEOUT)

    try:
        resp = _breaker(f"health:{service}").call(_call)
        status = "ready" if resp.status_code == 200 else "not_ready"
        latency = int(resp.elapsed.total_seconds() * 1000)
    except CircuitOpenError:
        status, latency = "unreachable", None
    except Exception:  # noqa: BLE001
        status, latency = "unreachable", None
    return {"service": service, "status": status, "latency_ms": latency}


def _prune_snapshots(service: str) -> None:
    """Keep the newest HEALTH_SNAPSHOTS_KEPT rows per service."""
    stale = (
        ServiceHealthSnapshot.objects.filter(service=service)
        .order_by("-checked_at")
        .values_list("id", flat=True)[settings.HEALTH_SNAPSHOTS_KEPT :]
    )
    ServiceHealthSnapshot.objects.filter(id__in=list(stale)).delete()


def poll_service_health() -> list[dict]:
    """Poll every service's /readyz at once and store a snapshot each (beat task).

    The calls run in parallel, so one slow service costs one timeout, not a
    timeout per service. Requests to the API never poll: they read snapshots.
    """
    targets = dict(settings.HEALTH_TARGETS)
    if not targets:
        return []
    with ThreadPoolExecutor(max_workers=min(len(targets), 16)) as pool:
        results = list(pool.map(lambda item: _check_one(*item), targets.items()))
    with transaction.atomic():
        for result in results:
            ServiceHealthSnapshot.objects.create(**result)
        for service in targets:
            _prune_snapshots(service)
    return results


def latest_health() -> dict:
    """The newest snapshot per configured service ("unknown" before the first poll)."""
    latest = {
        row.service: row
        for row in ServiceHealthSnapshot.objects.filter(service__in=list(settings.HEALTH_TARGETS))
        .order_by("service", "-checked_at")
        .distinct("service")
    }
    services = []
    for service in settings.HEALTH_TARGETS:
        row = latest.get(service)
        services.append(
            {
                "service": service,
                "status": row.status if row else "unknown",
                "latency_ms": row.latency_ms if row else None,
                "checked_at": row.checked_at.isoformat() if row else None,
            }
        )
    statuses = {s["status"] for s in services}
    if "unknown" in statuses and len(statuses) == 1:
        overall = "unknown"
    else:
        overall = "ok" if statuses == {"ready"} else "degraded"
    return {"overall": overall, "services": services}


# ---- platform statistics (polled by beat, read by the API) ------------------


def _fetch_stats(service: str, base_url: str) -> dict[str, int | None] | None:
    """One service's counters, or None when it cannot answer. Runs in a thread."""

    def _call():
        token = mint_internal_token(issuer="admin", audience=f"{service}-internal")
        resp = requests.get(
            f"{base_url}/internal/v1/stats/",
            headers={"Authorization": f"Bearer {token}"},
            timeout=settings.STATS_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()["data"]["stats"]

    try:
        stats = _breaker(f"stats:{service}").call(_call)
    except Exception:  # noqa: BLE001 - one service down must not stop the others
        logger.warning("stats poll failed", extra={"service": service})
        return None
    return stats if isinstance(stats, dict) else None


def poll_platform_stats() -> dict[str, int | None]:
    """Ask each owning service for its exact counts and keep the latest (beat task).

    A metric whose service did not answer keeps its last value and
    ``updated_at``, so the dashboard shows how old it is instead of a zero.
    """
    targets = dict(settings.STATS_TARGETS)
    if not targets:
        return {}
    with ThreadPoolExecutor(max_workers=min(len(targets), 8)) as pool:
        answers = dict(
            zip(targets, pool.map(lambda i: _fetch_stats(*i), targets.items()), strict=True)
        )
    now = timezone.now()
    seen: dict[str, int | None] = {}
    with transaction.atomic():
        for service, stats in answers.items():
            for metric, value in (stats or {}).items():
                if metric not in PLATFORM_METRICS:
                    continue
                row, _ = PlatformStat.objects.get_or_create(
                    metric=metric, defaults={"service": service}
                )
                row.service = service
                row.checked_at = now
                if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                    row.value = value
                    row.updated_at = now
                row.save()
                seen[metric] = row.value
    return seen


def platform_stats() -> list[dict]:
    rows = {row.metric: row for row in PlatformStat.objects.all()}
    return [
        {
            "metric": metric,
            "value": rows[metric].value if metric in rows else None,
            "updated_at": (
                rows[metric].updated_at.isoformat()
                if metric in rows and rows[metric].updated_at
                else None
            ),
        }
        for metric in PLATFORM_METRICS
    ]


def monitor() -> dict:
    health = latest_health()
    return {
        **health,
        "stats": platform_stats(),
        "intervals": {
            "health_seconds": int(settings.HEALTH_POLL_SECONDS),
            "stats_seconds": int(settings.STATS_POLL_SECONDS),
        },
    }
