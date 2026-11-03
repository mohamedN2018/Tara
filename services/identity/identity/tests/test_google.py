"""Google sign-in, linking and unlinking.

Google's JWKS is mocked (PyJWKClient.fetch_data) with a locally generated key,
so the real signature/kid/aud/iss/exp checks run against tokens we sign.
"""

from __future__ import annotations

import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from django.urls import reverse
from jwt import PyJWKClient
from jwt.algorithms import RSAAlgorithm

from identity import google
from identity.models import Account, OutboxEvent, SecurityEvent, SocialIdentity

pytestmark = pytest.mark.django_db

CLIENT_ID = "1234-test.apps.googleusercontent.com"
KID = "google-test-kid"
PASSWORD = "DevPassw0rd!"

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _jwks() -> dict:
    jwk = RSAAlgorithm.to_jwk(_KEY.public_key(), as_dict=True)
    jwk.update({"kid": KID, "use": "sig", "alg": "RS256"})
    return {"keys": [jwk]}


@pytest.fixture
def google_on(settings, monkeypatch):
    settings.GOOGLE_CLIENT_ID = CLIENT_ID
    google.jwk_client.cache_clear()
    monkeypatch.setattr(PyJWKClient, "fetch_data", lambda self: _jwks())
    yield settings
    google.jwk_client.cache_clear()


def id_token(*, key=_KEY, kid=KID, alg="RS256", drop: tuple[str, ...] = (), **overrides) -> str:
    now = int(time.time())
    claims = {
        "iss": "https://accounts.google.com",
        "aud": CLIENT_ID,
        "sub": "google-sub-1",
        "email": "person@gmail.com",
        "email_verified": True,
        "name": "Google Person",
        "iat": now,
        "exp": now + 600,
    }
    claims.update(overrides)
    for name in drop:
        claims.pop(name, None)
    return jwt.encode(claims, key, algorithm=alg, headers={"kid": kid})


def _sign_in(client, credential, **extra):
    return client.post(
        reverse("identity:google-sign-in"), {"credential": credential, **extra}, format="json"
    )


def _login(client, email, password=PASSWORD):
    resp = client.post(
        reverse("identity:login"), {"email": email, "password": password}, format="json"
    )
    assert resp.status_code == 200, resp.content
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.json()['data']['access_token']}")
    return resp.json()["data"]


# ---- providers --------------------------------------------------------------


def test_providers_hide_google_when_unconfigured(api_client):
    body = api_client.get(reverse("identity:auth-providers")).json()["data"]
    assert body["password"] is True
    assert body["google"] == {"enabled": False, "client_id": ""}
    assert body["telegram"]["enabled"] is False


def test_providers_expose_public_client_id_when_configured(api_client, google_on):
    body = api_client.get(reverse("identity:auth-providers")).json()["data"]
    assert body["google"] == {"enabled": True, "client_id": CLIENT_ID}


def test_sign_in_is_404_when_google_disabled(api_client):
    resp = _sign_in(api_client, "anything")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


# ---- sign-in creates or logs in ---------------------------------------------


def test_first_sign_in_creates_verified_active_account(api_client, google_on):
    resp = _sign_in(api_client, id_token(), language="ar")
    assert resp.status_code == 201, resp.content
    data = resp.json()["data"]
    assert data["created"] is True
    assert data["access_token"] and data["refresh_token"]
    assert "refresh_token" in resp.cookies

    account = Account.objects.get(email="person@gmail.com")
    assert account.status == Account.Status.ACTIVE
    assert account.email_verified is True
    assert account.language == "ar"
    assert not account.has_usable_password()
    link = SocialIdentity.objects.get(account=account)
    assert (link.provider, link.subject) == ("google", "google-sub-1")

    registered = OutboxEvent.objects.get(event_type="account.registered")
    assert registered.payload["payload"]["email_verified"] is True
    assert registered.payload["payload"]["display_name"] == "Google Person"
    assert OutboxEvent.objects.filter(event_type="account.verified").exists()
    assert SecurityEvent.objects.filter(
        account=account, type="login_succeeded", metadata__method="google"
    ).exists()


def test_second_sign_in_logs_into_the_same_account(api_client, google_on):
    first = _sign_in(api_client, id_token()).json()["data"]
    resp = _sign_in(api_client, id_token())
    assert resp.status_code == 200
    assert resp.json()["data"]["created"] is False
    assert Account.objects.filter(email="person@gmail.com").count() == 1
    claims = jwt.decode(resp.json()["data"]["access_token"], options={"verify_signature": False})
    first_claims = jwt.decode(first["access_token"], options={"verify_signature": False})
    assert claims["sub"] == first_claims["sub"]


def test_sign_in_follows_subject_not_email(api_client, google_on):
    _sign_in(api_client, id_token())
    # The Google account changed its address: still the same Tara account.
    resp = _sign_in(api_client, id_token(email="renamed@gmail.com"))
    assert resp.status_code == 200
    assert not Account.objects.filter(email="renamed@gmail.com").exists()
    assert SocialIdentity.objects.get().email == "renamed@gmail.com"


def test_existing_password_account_is_never_auto_linked(api_client, google_on, active_account):
    resp = _sign_in(api_client, id_token(email=active_account.email))
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "account_exists"
    assert not SocialIdentity.objects.exists()
    # The password account is untouched and still signs in.
    _login(api_client, active_account.email)


def test_pre_registered_unverified_account_is_not_hijackable(api_client, google_on):
    Account.objects.create_user(email="victim@gmail.com", password="AttackerPassw0rd!")
    resp = _sign_in(api_client, id_token(email="victim@gmail.com", sub="victim-sub"))
    assert resp.status_code == 409
    assert not SocialIdentity.objects.exists()


def test_suspended_account_cannot_sign_in_with_google(api_client, google_on):
    _sign_in(api_client, id_token())
    Account.objects.filter(email="person@gmail.com").update(status=Account.Status.SUSPENDED)
    resp = _sign_in(api_client, id_token())
    assert resp.status_code == 403


# ---- token verification (negative cases) ------------------------------------


@pytest.mark.parametrize(
    "credential",
    [
        pytest.param(lambda: id_token(aud="someone-else.apps.googleusercontent.com"), id="aud"),
        pytest.param(lambda: id_token(iss="https://evil.example"), id="iss"),
        pytest.param(
            lambda: id_token(iat=int(time.time()) - 7200, exp=int(time.time()) - 3600),
            id="expired",
        ),
        pytest.param(lambda: id_token(email_verified=False), id="email-unverified"),
        pytest.param(lambda: id_token(email_verified="false"), id="email-unverified-str"),
        pytest.param(lambda: id_token(drop=("email_verified",)), id="email-verified-missing"),
        pytest.param(lambda: id_token(drop=("email",)), id="no-email"),
        pytest.param(lambda: id_token(drop=("exp",)), id="no-exp"),
        pytest.param(lambda: id_token(key=_OTHER_KEY), id="bad-signature"),
        pytest.param(lambda: id_token(kid="unknown-kid"), id="unknown-kid"),
        pytest.param(lambda: id_token(key="x" * 32, alg="HS256"), id="hs256-confusion"),
        pytest.param(lambda: "not.a.jwt", id="garbage"),
    ],
)
def test_invalid_credentials_are_rejected(api_client, google_on, credential):
    resp = _sign_in(api_client, credential())
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "authentication_failed"
    assert not Account.objects.exists()


def test_unsigned_alg_none_token_is_rejected(api_client, google_on):
    unsigned = jwt.encode(
        {"iss": "accounts.google.com", "aud": CLIENT_ID, "sub": "x", "email": "a@b.co"},
        None,
        algorithm="none",
        headers={"kid": KID},
    )
    assert _sign_in(api_client, unsigned).status_code == 401


def test_plain_issuer_form_is_accepted(api_client, google_on):
    assert _sign_in(api_client, id_token(iss="accounts.google.com")).status_code == 201


def test_missing_credential_is_a_validation_error(api_client, google_on):
    resp = api_client.post(reverse("identity:google-sign-in"), {}, format="json")
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "validation_error"


# ---- link / unlink ----------------------------------------------------------


def test_link_requires_authentication(api_client, google_on):
    resp = api_client.post(reverse("identity:me-google"), {"credential": id_token()}, format="json")
    assert resp.status_code == 401


def test_link_then_sign_in_with_google_reaches_the_password_account(
    api_client, google_on, active_account
):
    _login(api_client, active_account.email)
    resp = api_client.post(
        reverse("identity:me-google"),
        {"credential": id_token(email="other.address@gmail.com")},
        format="json",
    )
    assert resp.status_code == 200, resp.content
    body = resp.json()["data"]
    assert body["google"]["linked"] is True
    assert body["google"]["email"] == "other.address@gmail.com"
    assert body["has_password"] is True

    api_client.credentials()
    signed_in = _sign_in(api_client, id_token(email="other.address@gmail.com"))
    assert signed_in.status_code == 200
    claims = jwt.decode(
        signed_in.json()["data"]["access_token"], options={"verify_signature": False}
    )
    assert claims["sub"] == str(active_account.id)


def test_link_is_idempotent_for_the_same_identity(api_client, google_on, active_account):
    _login(api_client, active_account.email)
    url = reverse("identity:me-google")
    assert api_client.post(url, {"credential": id_token()}, format="json").status_code == 200
    assert api_client.post(url, {"credential": id_token()}, format="json").status_code == 200
    assert SocialIdentity.objects.count() == 1


def test_cannot_link_google_identity_owned_by_another_account(
    api_client, google_on, active_account
):
    _sign_in(api_client, id_token())  # person@gmail.com owns google-sub-1
    _login(api_client, active_account.email)
    resp = api_client.post(reverse("identity:me-google"), {"credential": id_token()}, format="json")
    assert resp.status_code == 409
    assert not SocialIdentity.objects.filter(account=active_account).exists()


def test_cannot_link_google_address_that_is_another_accounts_email(
    api_client, google_on, active_account
):
    Account.objects.create_user(
        email="taken@gmail.com", password="DevPassw0rd!", status=Account.Status.ACTIVE
    )
    _login(api_client, active_account.email)
    resp = api_client.post(
        reverse("identity:me-google"),
        {"credential": id_token(email="taken@gmail.com", sub="sub-taken")},
        format="json",
    )
    assert resp.status_code == 409


def test_second_google_account_needs_unlink_first(api_client, google_on, active_account):
    _login(api_client, active_account.email)
    url = reverse("identity:me-google")
    api_client.post(url, {"credential": id_token()}, format="json")
    resp = api_client.post(
        url, {"credential": id_token(sub="sub-2", email="second@gmail.com")}, format="json"
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "already_linked"


def test_link_with_invalid_credential_is_400(api_client, google_on, active_account):
    _login(api_client, active_account.email)
    resp = api_client.post(
        reverse("identity:me-google"), {"credential": id_token(key=_OTHER_KEY)}, format="json"
    )
    # 400, not 401: the session itself is valid.
    assert resp.status_code == 400
    assert resp.json()["error"]["details"][0]["code"] == "invalid_google_credential"
    assert not SocialIdentity.objects.exists()


def test_unlink_keeps_password_login(api_client, google_on, active_account):
    _login(api_client, active_account.email)
    url = reverse("identity:me-google")
    api_client.post(url, {"credential": id_token()}, format="json")
    resp = api_client.delete(url)
    assert resp.status_code == 200
    assert resp.json()["data"]["google"]["linked"] is False
    assert SecurityEvent.objects.filter(account=active_account, type="google_unlinked").exists()


def test_cannot_unlink_the_only_login_method(api_client, google_on):
    tokens = _sign_in(api_client, id_token()).json()["data"]
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access_token']}")
    resp = api_client.delete(reverse("identity:me-google"))
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "last_login_method"
    assert SocialIdentity.objects.count() == 1


def test_unlink_without_link_is_404(api_client, google_on, active_account):
    _login(api_client, active_account.email)
    assert api_client.delete(reverse("identity:me-google")).status_code == 404


def test_google_only_account_has_no_password_login(api_client, google_on):
    _sign_in(api_client, id_token())
    resp = api_client.post(
        reverse("identity:login"), {"email": "person@gmail.com", "password": ""}, format="json"
    )
    assert resp.status_code in (400, 401)
