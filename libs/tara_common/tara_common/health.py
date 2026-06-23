"""Health, readiness, and liveness probes.

- /healthz  (liveness): process is up. Cheap, never touches dependencies.
- /readyz   (readiness): dependencies (DB, cache, broker) are reachable.
- /startupz (startup): same as readiness, used for slow-starting containers.

Readiness checks are registered by each service so the probe reflects that
service's real dependencies. A failing readiness check returns 503 so
orchestrators stop routing traffic without killing the pod.
"""

from __future__ import annotations

from collections.abc import Callable

from django.http import JsonResponse

# A check returns (ok: bool, detail: str). Register via register_readiness_check.
ReadinessCheck = Callable[[], tuple[bool, str]]
_readiness_checks: dict[str, ReadinessCheck] = {}


def register_readiness_check(name: str, check: ReadinessCheck) -> None:
    _readiness_checks[name] = check


def liveness(_request) -> JsonResponse:
    return JsonResponse({"status": "ok"})


def readiness(_request) -> JsonResponse:
    results: dict[str, str] = {}
    healthy = True
    for name, check in _readiness_checks.items():
        try:
            ok, detail = check()
        except Exception as exc:  # noqa: BLE001 - a check failing == not ready
            ok, detail = False, f"error: {exc}"
        results[name] = "ok" if ok else detail
        healthy = healthy and ok
    status = 200 if healthy else 503
    return JsonResponse(
        {"status": "ready" if healthy else "not_ready", "checks": results}, status=status
    )


# ---- Common reusable checks -------------------------------------------------


def database_check(alias: str = "default") -> ReadinessCheck:
    def _check() -> tuple[bool, str]:
        from django.db import connections

        try:
            connections[alias].cursor().execute("SELECT 1")
            return True, "ok"
        except Exception as exc:  # noqa: BLE001
            return False, f"db unavailable: {exc}"

    return _check


def cache_check() -> ReadinessCheck:
    def _check() -> tuple[bool, str]:
        from django.core.cache import cache

        try:
            cache.set("__readyz__", "1", 5)
            return (cache.get("__readyz__") == "1"), "ok"
        except Exception as exc:  # noqa: BLE001
            return False, f"cache unavailable: {exc}"

    return _check
