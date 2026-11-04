"""Sign-in by email or username (decision 5.6) and "Remember me" (1C).

A username is resolved through profile's internal API. Whatever the handle,
the answer and the work done are the same: no account enumeration.
"""

from __future__ import annotations

import copy
import io
import json
import urllib.error

import jwt
import pytest
from django.urls import reverse
from rest_framework.throttling import SimpleRateThrottle

from identity import login_identifier, services
from identity.views import REFRESH_COOKIE, SESSION_ONLY_COOKIE

pytestmark = pytest.mark.django_db

PASSWORD = "DevPassw0rd!"


@pytest.fixture
def handles(monkeypatch):
    """Stand in for profile's ``profiles/by-handle/``: handle -> account id."""
    known: dict[str, str] = {}
    calls: list[str] = []

    def lookup(handle: str) -> str | None:
        calls.append(handle)
        return known.get(handle)

    monkeypatch.setattr(login_identifier, "_account_id_for_handle", lookup)
    return known, calls


@pytest.fixture
def rates(settings, monkeypatch):
    def apply(**overrides):
        rest = copy.deepcopy(settings.REST_FRAMEWORK)
        rest["DEFAULT_THROTTLE_RATES"].update(overrides)
        settings.REST_FRAMEWORK = rest
        monkeypatch.setattr(SimpleRateThrottle, "THROTTLE_RATES", rest["DEFAULT_THROTTLE_RATES"])

    return apply


def _login(client, ip="10.2.0.1", **body):
    return client.post(
        reverse("identity:login"), body, format="json", REMOTE_ADDR=ip, HTTP_X_FORWARDED_FOR=ip
    )


def _error(resp) -> dict:
    error = dict(resp.json()["error"])
    error.pop("request_id", None)
    return error


# ---- Remember me ------------------------------------------------------------


def test_unticked_remember_sets_a_session_cookie(api_client, active_account):
    resp = _login(api_client, identifier=active_account.email, password=PASSWORD, remember=False)
    assert resp.status_code == 200
    cookie = resp.cookies[REFRESH_COOKIE]
    assert cookie["max-age"] == ""
    assert cookie["expires"] == ""
    header = cookie.output()
    assert "Max-Age" not in header and "expires" not in header.lower()
    assert "HttpOnly" in header
    assert resp.cookies[SESSION_ONLY_COOKIE].value == "1"
    assert resp.cookies[SESSION_ONLY_COOKIE]["max-age"] == ""


def test_ticked_remember_keeps_the_refresh_lifetime(api_client, active_account, settings):
    resp = _login(api_client, identifier=active_account.email, password=PASSWORD, remember=True)
    assert resp.status_code == 200
    cookie = resp.cookies[REFRESH_COOKIE]
    assert int(cookie["max-age"]) == settings.REFRESH_TOKEN_TTL_SECONDS
    assert "Max-Age" in cookie.output()
    # A marker left by an earlier session-only login is removed.
    assert resp.cookies[SESSION_ONLY_COOKIE]["max-age"] == 0


def test_clients_that_do_not_send_remember_keep_a_persistent_cookie(api_client, active_account):
    resp = _login(api_client, email=active_account.email, password=PASSWORD)
    assert resp.status_code == 200
    assert resp.cookies[REFRESH_COOKIE]["max-age"] != ""


def test_refresh_keeps_a_session_cookie_session_only(api_client, active_account):
    _login(api_client, identifier=active_account.email, password=PASSWORD, remember=False)
    # The client sends back both cookies; rotation must not make it persistent.
    resp = api_client.post(reverse("identity:refresh"), {}, format="json")
    assert resp.status_code == 200
    assert resp.cookies[REFRESH_COOKIE]["max-age"] == ""
    assert resp.cookies[SESSION_ONLY_COOKIE].value == "1"


def test_refresh_of_a_remembered_session_stays_persistent(api_client, active_account):
    tokens = _login(api_client, identifier=active_account.email, password=PASSWORD).json()["data"]
    api_client.cookies.clear()
    resp = api_client.post(
        reverse("identity:refresh"), {"refresh_token": tokens["refresh_token"]}, format="json"
    )
    assert resp.status_code == 200
    assert resp.cookies[REFRESH_COOKIE]["max-age"] != ""


def test_logout_clears_the_session_only_marker(api_client, active_account):
    _login(api_client, identifier=active_account.email, password=PASSWORD, remember=False)
    resp = api_client.post(reverse("identity:logout"), {}, format="json")
    assert resp.status_code == 204
    assert resp.cookies[SESSION_ONLY_COOKIE]["max-age"] == 0


# ---- Identifier: email or username -----------------------------------------


def test_login_by_handle(api_client, active_account, handles):
    known, calls = handles
    known["sara_k"] = str(active_account.id)
    resp = _login(api_client, identifier="sara_k", password=PASSWORD)
    assert resp.status_code == 200
    assert resp.json()["data"]["access_token"]
    assert calls == ["sara_k"]


def test_login_by_handle_accepts_at_sign_and_any_case(api_client, active_account, handles):
    known, calls = handles
    known["sara_k"] = str(active_account.id)
    assert _login(api_client, identifier="  @Sara_K ", password=PASSWORD).status_code == 200
    assert calls == ["sara_k"]


def test_login_by_email_identifier_skips_profile(api_client, active_account, handles):
    _, calls = handles
    resp = _login(api_client, identifier=active_account.email.upper(), password=PASSWORD)
    assert resp.status_code == 200
    assert calls == []


def test_legacy_email_field_still_validates_as_an_email(api_client):
    resp = _login(api_client, email="not-an-email", password=PASSWORD)
    assert resp.status_code == 400


def test_missing_identifier_is_a_validation_error(api_client):
    resp = _login(api_client, password=PASSWORD)
    assert resp.status_code == 400
    fields = {d["field"] for d in resp.json()["error"]["details"]}
    assert "identifier" in fields


def test_unknown_handle_and_wrong_password_give_the_same_answer(
    api_client, active_account, handles
):
    known, _ = handles
    known["sara_k"] = str(active_account.id)
    wrong_password = _login(api_client, identifier="sara_k", password="WrongPassw0rd!")
    unknown_handle = _login(api_client, identifier="nobody_here", password="WrongPassw0rd!")
    wrong_email = _login(api_client, identifier=active_account.email, password="WrongPassw0rd!")
    unknown_email = _login(api_client, identifier="ghost@tara.local", password="WrongPassw0rd!")
    garbage = _login(api_client, identifier="not a handle!", password="WrongPassw0rd!")
    answers = [wrong_password, unknown_handle, wrong_email, unknown_email, garbage]
    assert {r.status_code for r in answers} == {401}
    assert all(_error(r) == _error(wrong_password) for r in answers)
    assert _error(wrong_password)["code"] == "authentication_failed"


def test_unknown_handle_still_runs_a_password_hash(api_client, handles, monkeypatch):
    hashed: list[str] = []
    real = services.make_password
    monkeypatch.setattr(services, "make_password", lambda p: hashed.append(p) or real(p))
    _login(api_client, identifier="nobody_here", password="WrongPassw0rd!")
    assert hashed == ["WrongPassw0rd!"]


def test_unknown_handle_creates_no_session(api_client, handles):
    from identity.models import UserSession

    _login(api_client, identifier="nobody_here", password=PASSWORD)
    assert not UserSession.objects.exists()


def test_profile_down_is_a_503_whatever_the_handle(api_client, monkeypatch):
    def down(*_a, **_k):
        raise urllib.error.URLError("refused")

    monkeypatch.setattr(login_identifier.urllib.request, "urlopen", down)
    resp = _login(api_client, identifier="sara_k", password=PASSWORD)
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "dependency_unavailable"


# ---- Throttles and lockout apply to usernames too ---------------------------


def test_target_throttle_applies_to_handles(api_client, rates, active_account, handles):
    known, _ = handles
    known["sara_k"] = str(active_account.id)
    rates(auth_login="1000/min", auth_login_target="3/min")
    for n, typed in enumerate(["sara_k", "@SARA_K", " Sara_k"]):
        assert _login(api_client, f"10.3.0.{n}", identifier=typed, password="x").status_code == 401
    blocked = _login(api_client, "10.3.9.9", identifier="sara_k", password=PASSWORD)
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "throttled"


def test_target_throttle_is_the_same_for_unknown_handles(api_client, rates, handles):
    rates(auth_login="1000/min", auth_login_target="3/min")
    for n in range(3):
        _login(api_client, f"10.4.0.{n}", identifier="nobody_here", password="x")
    assert _login(api_client, "10.4.9.9", identifier="nobody_here", password="x").status_code == 429


def test_ip_throttle_applies_to_handles(api_client, rates, handles):
    rates(auth_login="2/min", auth_login_target="1000/min")
    _login(api_client, "10.5.0.1", identifier="first_one", password="x")
    _login(api_client, "10.5.0.1", identifier="second_one", password="x")
    assert _login(api_client, "10.5.0.1", identifier="third_one", password="x").status_code == 429


@pytest.mark.parametrize("exists", [True, False])
def test_failure_lockout_applies_to_handles(api_client, rates, active_account, handles, exists):
    known, calls = handles
    if exists:
        known["sara_k"] = str(active_account.id)
    rates(auth_login="1000/min", auth_login_target="1000/min")
    for n in range(10):
        _login(api_client, f"10.6.0.{n}", identifier="sara_k", password="WrongPassw0rd!")
    resp = _login(api_client, "10.6.1.1", identifier="sara_k", password=PASSWORD)
    assert resp.status_code == 429
    assert len(calls) == 10  # a locked identifier never reaches profile


# ---- The profile client -----------------------------------------------------


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_handle_lookup_asks_profile_with_an_internal_token(monkeypatch, settings):
    settings.PROFILE_INTERNAL_URL = "http://profile.test:8000"
    seen = {}

    def urlopen(request, timeout):
        seen["url"] = request.full_url
        seen["body"] = json.loads(request.data)
        seen["auth"] = request.get_header("Authorization")
        seen["timeout"] = timeout
        return _Response(json.dumps({"data": {"sara_k": "0190-account"}}).encode())

    monkeypatch.setattr(login_identifier.urllib.request, "urlopen", urlopen)
    assert login_identifier._account_id_for_handle("sara_k") == "0190-account"
    assert seen["url"] == "http://profile.test:8000/internal/v1/profiles/by-handle/"
    assert seen["body"] == {"handles": ["sara_k"]}
    assert seen["timeout"] == settings.PROFILE_CALL_TIMEOUT
    claims = jwt.decode(
        seen["auth"].removeprefix("Bearer "),
        settings.TARA_INTERNAL_JWT_SECRET,
        algorithms=["HS256"],
        audience="profile-internal",
    )
    assert claims["iss"] == "identity"


def test_handle_lookup_returns_none_for_an_unknown_handle(monkeypatch):
    monkeypatch.setattr(
        login_identifier.urllib.request,
        "urlopen",
        lambda request, timeout: _Response(b'{"data": {}}'),
    )
    assert login_identifier._account_id_for_handle("nobody_here") is None


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        (" Sara@Tara.Local ", "sara@tara.local"),
        ("@Sara_K", "sara_k"),
        ("sara_k", "sara_k"),
        ("@@sara", "@@sara"),
        ("", ""),
        (None, ""),
    ],
)
def test_normalise(typed, expected):
    assert login_identifier.normalise(typed) == expected
