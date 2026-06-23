"""Unit tests for the token engine, the event envelope, and the outbox relay."""

import hashlib

import jwt
import pytest
from django.conf import settings
from django.utils import timezone

from identity import services, tokens
from identity.models import OutboxEvent, PasswordReset, RefreshToken
from tara_events.envelope import EventEnvelope, uuid7
from tara_events.outbox import publish_pending, record_event
from tara_events.publisher import NullPublisher

pytestmark = pytest.mark.django_db


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


# ---- uuid7 & envelope (no DB) -----------------------------------------------


def test_uuid7_sets_version_and_variant():
    u = uuid7()
    assert u.version == 7
    # RFC 4122/9562 variant: two most-significant bits of clock_seq_hi are 10.
    assert (u.bytes[8] & 0xC0) == 0x80


def test_event_envelope_roundtrips_and_defaults_partition_key():
    env = EventEnvelope(
        event_type="account.registered",
        payload={"email": "x@tara.local"},
        subject_id="abc",
        producer="identity-service",
    )
    assert env.partition_key == "abc"  # defaults to subject
    restored = EventEnvelope.from_dict(env.to_dict())
    assert restored.to_dict() == env.to_dict()


# ---- access token -----------------------------------------------------------


def test_issue_access_token_verifies_with_public_key(active_account):
    token, ttl = tokens.issue_access_token(active_account, session_id="sess-1")
    assert ttl == settings.ACCESS_TOKEN_TTL_SECONDS
    claims = jwt.decode(
        token,
        settings.JWT_PUBLIC_KEY,
        algorithms=["RS256"],
        audience=settings.JWT_AUDIENCE,
        issuer=settings.JWT_ISSUER,
    )
    assert claims["sub"] == str(active_account.id)
    assert claims["type"] == "access"
    assert claims["sid"] == "sess-1"


# ---- outbox relay -----------------------------------------------------------


def test_outbox_publish_marks_rows_and_calls_publisher():
    env = EventEnvelope(
        event_type="account.registered",
        payload={"email": "y@tara.local"},
        subject_id=str(uuid7()),
        producer="identity-service",
    )
    record_event(OutboxEvent, env)
    assert OutboxEvent.objects.filter(published_at__isnull=True).count() == 1

    publisher = NullPublisher()
    count = publish_pending(OutboxEvent, publisher=publisher)
    assert count == 1
    assert len(publisher.published) == 1
    assert publisher.published[0].event_type == "account.registered"
    assert OutboxEvent.objects.filter(published_at__isnull=True).count() == 0


# ---- password reset revokes sessions ----------------------------------------


def test_password_reset_revokes_all_sessions(active_account):
    issued = services.login(email=active_account.email, password="DevPassw0rd!")
    assert RefreshToken.objects.filter(account=active_account, revoked_at__isnull=True).exists()

    raw = "known-reset-token"
    PasswordReset.objects.create(
        account=active_account,
        token_hash=_hash(raw),
        expires_at=timezone.now() + timezone.timedelta(hours=1),
    )
    services.reset_password(raw_token=raw, new_password="BrandNewPassw0rd!")

    # Every prior refresh token is revoked, so rotation now fails.
    with pytest.raises(tokens.TokenError):
        tokens.rotate_refresh_token(issued.refresh_token)
    active_account.refresh_from_db()
    assert active_account.check_password("BrandNewPassw0rd!")
