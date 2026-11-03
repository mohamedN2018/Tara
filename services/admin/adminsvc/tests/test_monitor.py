"""Monitoring (8.11): health and statistics come from beat tasks, never per request."""

import time
import uuid

import jwt
import pytest
import requests
from django.urls import reverse

from adminsvc import services
from adminsvc.models import PlatformStat, ServiceHealthSnapshot
from adminsvc.tasks import poll_platform_stats, poll_service_health

pytestmark = pytest.mark.django_db

SHARED_SECRET = "shared-internal-secret-every-service-holds-0123456789"


@pytest.fixture(autouse=True)
def _fresh_breakers(settings):
    services._breakers.clear()
    settings.TARA_INTERNAL_JWT_SECRET = SHARED_SECRET
    yield
    services._breakers.clear()


def _acct() -> str:
    return str(uuid.uuid4())


def _response(status=200, json_body=b"{}", elapsed_ms=5):
    from datetime import timedelta

    resp = requests.Response()
    resp.status_code = status
    resp._content = json_body
    resp.elapsed = timedelta(milliseconds=elapsed_ms)
    return resp


def test_reading_health_never_polls(client_for, monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("the API must not poll services")

    monkeypatch.setattr("adminsvc.services.requests.get", boom)
    resp = client_for(_acct(), roles=["admin"]).get(reverse("adminsvc:service-health"))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["overall"] == "unknown"  # nothing polled yet
    assert {s["status"] for s in data["services"]} == {"unknown"}


def test_the_beat_poll_runs_in_parallel_and_snapshots_every_service(monkeypatch, settings):
    settings.HEALTH_TARGETS = {f"svc{i}": f"http://svc{i}/readyz/" for i in range(6)}
    settings.HEALTH_TIMEOUT = 2.0

    def slow(url, timeout):
        time.sleep(0.3)
        return _response(200 if "svc0" not in url else 503)

    monkeypatch.setattr("adminsvc.services.requests.get", slow)
    started = time.monotonic()
    poll_service_health()
    assert time.monotonic() - started < 1.2  # 6 x 0.3 s one after another would be 1.8 s
    statuses = dict(ServiceHealthSnapshot.objects.values_list("service", "status"))
    assert statuses == {"svc0": "not_ready", **{f"svc{i}": "ready" for i in range(1, 6)}}
    latest = services.latest_health()
    assert latest["overall"] == "degraded"
    assert all(s["checked_at"] for s in latest["services"])


def test_platform_stats_come_from_each_owner(monkeypatch, settings):
    settings.STATS_TARGETS = {"identity": "http://identity:8000", "post": "http://post:8000"}
    seen_tokens = {}

    def fake(url, headers, timeout):
        service = url.split("//")[1].split(":")[0]
        seen_tokens[service] = headers["Authorization"].removeprefix("Bearer ")
        stats = {"identity": b'{"accounts": 12}', "post": b'{"posts": 30, "bogus": 9}'}[service]
        return _response(json_body=b'{"data": {"stats": ' + stats + b"}}")

    monkeypatch.setattr("adminsvc.services.requests.get", fake)
    poll_platform_stats()
    assert dict(PlatformStat.objects.values_list("metric", "value")) == {
        "accounts": 12,
        "posts": 30,
    }
    # Short-lived internal token for each owner's own audience.
    for service, token in seen_tokens.items():
        claims = jwt.decode(
            token, SHARED_SECRET, algorithms=["HS256"], audience=f"{service}-internal"
        )
        assert claims["exp"] - claims["iat"] <= 30


def test_a_failed_stats_poll_keeps_the_last_value(monkeypatch, settings):
    settings.STATS_TARGETS = {"post": "http://post:8000"}
    monkeypatch.setattr(
        "adminsvc.services.requests.get",
        lambda *a, **k: _response(json_body=b'{"data": {"stats": {"posts": 7}}}'),
    )
    poll_platform_stats()
    first = PlatformStat.objects.get(metric="posts")

    def down(*args, **kwargs):
        raise requests.ConnectionError

    monkeypatch.setattr("adminsvc.services.requests.get", down)
    poll_platform_stats()
    after = PlatformStat.objects.get(metric="posts")
    assert after.value == 7
    assert after.updated_at == first.updated_at


def test_monitor_api_shape_and_capability(client_for):
    PlatformStat.objects.create(metric="accounts", service="identity", value=5)
    ServiceHealthSnapshot.objects.create(service="identity", status="ready", latency_ms=3)
    url = reverse("adminsvc:monitor")
    assert client_for(_acct(), roles=["moderator"]).get(url).status_code == 403
    assert client_for(_acct(), roles=["analyst"]).get(url).status_code == 403
    data = client_for(_acct(), caps=["admin.monitor.view"]).get(url).json()["data"]
    assert [s["metric"] for s in data["stats"]] == list(services.PLATFORM_METRICS)
    assert data["stats"][0]["value"] == 5
    assert data["stats"][1] == {"metric": "posts", "value": None, "updated_at": None}
    identity = next(s for s in data["services"] if s["service"] == "identity")
    assert identity["status"] == "ready" and identity["latency_ms"] == 3
    assert set(data["intervals"]) == {"health_seconds", "stats_seconds"}


def test_service_health_needs_the_monitor_capability(client_for):
    url = reverse("adminsvc:service-health")
    # Same as before for the default map: admin yes, moderator no.
    assert client_for(_acct(), roles=["moderator"]).get(url).status_code == 403
    assert client_for(_acct(), roles=["admin"]).get(url).status_code == 200
    # An analyst the matrix granted monitoring to gets in.
    assert (
        client_for(_acct(), roles=["analyst"], caps=["admin.monitor.view"]).get(url).status_code
        == 200
    )
