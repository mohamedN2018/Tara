"""tara_common internal-token helpers: the 1.0d extension and the default path.

``verify_internal_token`` keeps its old behaviour for every existing caller
(shared secret, audience only). A privileged endpoint passes its own secret and
an expected issuer, and then a token signed with the shared secret fails.
"""

from __future__ import annotations

import time

import jwt
import pytest
from django.core.exceptions import ImproperlyConfigured
from rest_framework import exceptions

from tara_common.auth import mint_internal_token, verify_internal_token

SHARED = "shared-internal-secret-every-service-holds-0123456789"
CALLER = "caller-only-secret-for-one-endpoint-0123456789"


@pytest.fixture(autouse=True)
def _shared_secret(settings):
    settings.TARA_INTERNAL_JWT_SECRET = SHARED


def _legacy(claims: dict, secret: str = SHARED) -> str:
    """How post, feed, profile and realtime mint their tokens today."""
    now = int(time.time())
    return jwt.encode({"iat": now, "exp": now + 30, **claims}, secret, algorithm="HS256")


# ---- default path: unchanged for existing callers ---------------------------


def test_default_path_still_verifies_shared_secret_tokens():
    token = _legacy({"iss": "post", "aud": "graph-internal"})
    claims = verify_internal_token(token, expected_audience="graph-internal")
    assert claims["iss"] == "post"


def test_default_path_does_not_require_an_issuer():
    token = _legacy({"aud": "graph-internal"})
    assert verify_internal_token(token, expected_audience="graph-internal")["aud"] == (
        "graph-internal"
    )


def test_default_path_still_checks_the_audience():
    with pytest.raises(jwt.InvalidAudienceError):
        verify_internal_token(
            _legacy({"iss": "post", "aud": "graph-internal"}), expected_audience="chat-internal"
        )


def test_default_path_rejects_another_secret():
    with pytest.raises(jwt.InvalidSignatureError):
        verify_internal_token(
            _legacy({"aud": "graph-internal"}, secret=CALLER), expected_audience="graph-internal"
        )


def test_default_path_without_a_configured_secret(settings):
    settings.TARA_INTERNAL_JWT_SECRET = ""
    with pytest.raises(exceptions.AuthenticationFailed):
        verify_internal_token(_legacy({"aud": "x"}), expected_audience="x")


# ---- caller-specific secret -------------------------------------------------


def test_caller_secret_verifies_its_own_tokens():
    token = mint_internal_token(issuer="admin", audience="identity.roles", secret=CALLER)
    claims = verify_internal_token(
        token, secret=CALLER, expected_issuer="admin", expected_audience="identity.roles"
    )
    assert (claims["iss"], claims["aud"]) == ("admin", "identity.roles")
    assert claims["exp"] - claims["iat"] == 30


def test_caller_secret_rejects_shared_secret_tokens():
    token = mint_internal_token(issuer="admin", audience="identity.roles")  # shared secret
    with pytest.raises(jwt.InvalidSignatureError):
        verify_internal_token(
            token, secret=CALLER, expected_issuer="admin", expected_audience="identity.roles"
        )


def test_expected_issuer_rejects_another_issuer():
    token = mint_internal_token(issuer="post", audience="identity.roles", secret=CALLER)
    with pytest.raises(jwt.InvalidIssuerError):
        verify_internal_token(
            token, secret=CALLER, expected_issuer="admin", expected_audience="identity.roles"
        )


def test_expected_issuer_requires_the_claim():
    token = _legacy({"aud": "identity.roles"}, secret=CALLER)
    with pytest.raises(jwt.MissingRequiredClaimError):
        verify_internal_token(
            token, secret=CALLER, expected_issuer="admin", expected_audience="identity.roles"
        )


def test_empty_caller_secret_never_falls_back_to_the_shared_one():
    token = mint_internal_token(issuer="admin", audience="identity.roles")  # shared secret
    with pytest.raises(exceptions.AuthenticationFailed):
        verify_internal_token(
            token, secret="", expected_issuer="admin", expected_audience="identity.roles"
        )


def test_expired_token_is_rejected():
    token = mint_internal_token(
        issuer="admin", audience="identity.roles", secret=CALLER, ttl_seconds=-1
    )
    with pytest.raises(jwt.ExpiredSignatureError):
        verify_internal_token(token, secret=CALLER, expected_issuer="admin")


# ---- minting ----------------------------------------------------------------


def test_mint_defaults_to_the_shared_secret():
    token = mint_internal_token(issuer="post", audience="graph-internal")
    assert verify_internal_token(token, expected_audience="graph-internal")["iss"] == "post"


def test_mint_refuses_an_empty_secret(settings):
    with pytest.raises(ImproperlyConfigured):
        mint_internal_token(issuer="admin", audience="identity.roles", secret="")
    settings.TARA_INTERNAL_JWT_SECRET = ""
    with pytest.raises(ImproperlyConfigured):
        mint_internal_token(issuer="post", audience="graph-internal")
