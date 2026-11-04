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


@pytest.mark.parametrize(
    ("is_staff", "is_superuser", "expected"),
    [
        (False, False, []),
        (True, False, ["moderator"]),
        (True, True, ["admin", "moderator"]),
    ],
)
def test_access_token_carries_roles_from_account_flags(
    active_account, is_staff, is_superuser, expected
):
    active_account.is_staff = is_staff
    active_account.is_superuser = is_superuser
    active_account.save(update_fields=["is_staff", "is_superuser"])

    token, _ = tokens.issue_access_token(active_account, session_id="sess-1")
    claims = jwt.decode(token, options={"verify_signature": False})

    assert claims["roles"] == expected


def test_reused_refresh_token_stays_revoked_after_the_error(active_account, settings):
    settings.REFRESH_REUSE_GRACE_SECONDS = 0  # the grace window has its own tests
    issued = services.login(email=active_account.email, password="DevPassw0rd!")
    tokens.rotate_refresh_token(issued.refresh_token)

    with pytest.raises(tokens.TokenError):
        tokens.rotate_refresh_token(issued.refresh_token)

    assert RefreshToken.objects.filter(revoked_at__isnull=True).count() == 0


def test_repeated_failures_lock_the_login(active_account):
    from tara_common.exceptions import TaraAPIError

    for _ in range(services.LOGIN_MAX_FAILURES):
        with pytest.raises(services.InvalidCredentials):
            services.login(email=active_account.email, password="wrong-password")

    with pytest.raises(TaraAPIError) as caught:
        services.login(email=active_account.email, password="wrong-password")
    assert caught.value.http_status == 429


def test_failed_consumer_retries_then_dead_letters():
    from unittest.mock import MagicMock

    from kombu import Connection

    from tara_events import worker as event_worker

    consumer = event_worker.EventWorker(Connection("memory://"), exchange_name="x", queue_name="q")
    consumer.producer = MagicMock()

    message = MagicMock(headers={})
    consumer._retry_or_dead_letter({"event_id": "1"}, message)
    assert consumer.producer.publish.call_args.kwargs["routing_key"] == "q.retry.5s"
    message.ack.assert_called_once()

    final = MagicMock(headers={event_worker.ATTEMPT_HEADER: 5})
    consumer._retry_or_dead_letter({"event_id": "1"}, final)
    final.reject.assert_called_once_with(requeue=False)


def test_broker_outage_does_not_use_up_attempts(active_account):
    from tara_events.publisher import PublisherUnavailable

    class Down:
        def publish(self, envelope):
            raise PublisherUnavailable("down")

    OutboxEvent.objects.all().delete()
    record_event(
        OutboxEvent,
        EventEnvelope(event_type="t", payload={}, subject_id="s", producer="p"),
    )
    assert publish_pending(OutboxEvent, publisher=Down()) == 0
    assert OutboxEvent.objects.get().attempts == 0


def test_handler_failure_is_not_recorded_as_processed():
    from identity.models import ProcessedEvent
    from tara_events.consumer import idempotent

    event_id = str(uuid7())
    with pytest.raises(ValueError):
        with idempotent(ProcessedEvent, event_id, "c"):
            raise ValueError

    assert not ProcessedEvent.objects.filter(event_id=event_id).exists()
