"""Capability checks (8.12) and the matrix proxy to identity."""

import json
import uuid

import pytest
import requests
from django.urls import reverse

from tara_common import capabilities as registry
from tara_common.permissions import HasCapability

pytestmark = pytest.mark.django_db


def _acct() -> str:
    return str(uuid.uuid4())


MATRIX = {"roles": list(registry.ROLES), "locked_roles": ["admin"], "effective": {}}


def _fake_identity(monkeypatch, status=200, body=None):
    calls = []

    def fake(method, url, **kwargs):
        calls.append({"method": method, "url": url, **kwargs})
        resp = requests.Response()
        resp.status_code = status
        resp._content = json.dumps(body if body is not None else {"data": MATRIX}).encode()
        return resp

    monkeypatch.setattr("adminsvc.identity_client.requests.request", fake)
    return calls


def test_matrix_read_and_write_need_the_capability(client_for, monkeypatch):
    calls = _fake_identity(monkeypatch)
    url = reverse("adminsvc:capabilities")
    change = {
        "changes": [{"role": "analyst", "capability": "admin.monitor.view", "state": "grant"}]
    }
    for client in (
        client_for(_acct(), roles=["moderator"]),
        client_for(_acct(), caps=["admin.roles.manage"]),
    ):
        assert client.get(url).status_code == 403
        assert client.put(url, change, format="json").status_code == 403
    assert calls == []


def test_matrix_put_forwards_the_actor_and_the_request_id(client_for, monkeypatch):
    calls = _fake_identity(monkeypatch)
    me = _acct()
    client = client_for(me, roles=["admin"])  # token without caps: admin by default
    change = {"role": "analyst", "capability": "admin.monitor.view", "state": "grant"}
    resp = client.put(
        reverse("adminsvc:capabilities"),
        {"changes": [change]},
        format="json",
        HTTP_X_REQUEST_ID="edge-7",
    )
    assert resp.status_code == 200
    call = calls[-1]
    assert call["method"] == "PUT" and call["url"].endswith("/internal/v1/capabilities/")
    assert call["json"] == {"changes": [change], "actor_id": me}
    assert call["headers"]["X-Request-Id"] == "edge-7"


def test_identity_validation_errors_stay_400(client_for, monkeypatch):
    _fake_identity(
        monkeypatch,
        status=400,
        body={"error": {"code": "validation_error", "message": "locked role"}},
    )
    resp = client_for(_acct(), roles=["admin"]).put(
        reverse("adminsvc:capabilities"),
        {"changes": [{"role": "admin", "capability": "ads.review", "state": "revoke"}]},
        format="json",
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "validation_error"


def test_an_empty_change_list_is_refused_here(client_for, monkeypatch):
    calls = _fake_identity(monkeypatch)
    resp = client_for(_acct(), roles=["admin"]).put(
        reverse("adminsvc:capabilities"), {"changes": []}, format="json"
    )
    assert resp.status_code == 400
    assert calls == []


@pytest.mark.parametrize(
    ("roles", "caps", "allowed"),
    [
        (["admin"], None, True),  # pre-8.12 token: role default
        (["moderator"], None, False),
        ([], ["admin.flags.manage"], True),  # the matrix granted it
        (["admin"], ["admin.audit.view"], False),  # the matrix took it away
    ],
)
def test_flag_writes_follow_capabilities(client_for, roles, caps, allowed):
    resp = client_for(_acct(), roles=roles, caps=caps).patch(
        reverse("adminsvc:feature-flag-detail", args=["f1"]), {"enabled": True}, format="json"
    )
    assert resp.status_code == (200 if allowed else 403)


def test_unknown_capability_keys_fail_loudly():
    with pytest.raises(ValueError):
        HasCapability("admin.audit.veiw")
    with pytest.raises(ValueError):
        HasCapability()


def test_anonymous_is_401_not_403(client):
    assert client.get(reverse("adminsvc:audit")).status_code == 401
