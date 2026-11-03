"""Web Push: subscriptions, delivery, and a real encrypted payload."""

import base64
import json
import logging
import os
import uuid
from datetime import UTC, datetime
from unittest import mock

import http_ece
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from django.urls import reverse
from py_vapid import Vapid02
from pywebpush import WebPushException

from notifications import push, services
from notifications.models import (
    Notification,
    NotificationDeliveryLog,
    NotificationPreference,
    PushDeviceToken,
)

pytestmark = pytest.mark.django_db

ENDPOINT = "https://fcm.googleapis.com/fcm/send/abc"


def _acct() -> str:
    return str(uuid.uuid4())


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _subscription(endpoint=ENDPOINT) -> dict:
    return {"endpoint": endpoint, "keys": {"p256dh": "key", "auth": "secret"}}


@pytest.fixture
def vapid(settings):
    key = Vapid02()
    key.generate_keys()
    settings.VAPID_PRIVATE_KEY = _b64(
        key.private_key.private_numbers().private_value.to_bytes(32, "big")
    )
    settings.VAPID_PUBLIC_KEY = _b64(
        key.public_key.public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )
    )
    settings.VAPID_SUBJECT = "mailto:admin@example.com"
    return settings


def _token(account, endpoint=ENDPOINT, subscription=None):
    return PushDeviceToken.objects.create(
        account_id=account,
        platform="web",
        token=services.endpoint_token(endpoint),
        subscription=subscription or _subscription(endpoint),
    )


def _notification(account, **extra):
    return Notification.objects.create(
        recipient_id=account, kind="follow", body="started following you", **extra
    )


# ---- subscribing -------------------------------------------------------------


def test_web_subscription_is_stored_and_replaced_on_re_subscribe(client_for):
    me = _acct()
    url = reverse("notifications:push-token")
    body = {"platform": "web", "subscription": _subscription()}
    assert client_for(me).post(url, body, format="json").status_code == 201
    assert client_for(me).post(url, body, format="json").status_code == 201
    row = PushDeviceToken.objects.get()
    assert str(row.account_id) == me
    assert row.subscription["endpoint"] == ENDPOINT


def test_browser_moves_to_the_account_now_using_it(client_for):
    url = reverse("notifications:push-token")
    body = {"platform": "web", "subscription": _subscription()}
    client_for(_acct()).post(url, body, format="json")
    second = _acct()
    client_for(second).post(url, body, format="json")
    assert str(PushDeviceToken.objects.get().account_id) == second


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://fcm.googleapis.com/fcm/send/abc",
        "https://evil.example/push",
        "https://fcm.googleapis.com.evil.example/x",
        "https://localhost/x",
        "https://169.254.169.254/latest",
        "https://user:pw@fcm.googleapis.com/x",
        "https://fcm.googleapis.com:8443/x",
    ],
)
def test_endpoints_outside_known_push_services_are_refused(client_for, endpoint):
    resp = client_for(_acct()).post(
        reverse("notifications:push-token"),
        {"platform": "web", "subscription": _subscription(endpoint)},
        format="json",
    )
    assert resp.status_code == 400
    assert not PushDeviceToken.objects.exists()


@pytest.mark.parametrize(
    "endpoint",
    [
        ENDPOINT,
        "https://updates.push.services.mozilla.com/wpush/v2/x",
        "https://web.push.apple.com/x",
        "https://wns2-par02p.notify.windows.com/w/?token=x",
    ],
)
def test_known_push_services_are_accepted(endpoint):
    assert push.is_allowed_endpoint(endpoint)


def test_web_needs_a_subscription_with_keys(client_for):
    url = reverse("notifications:push-token")
    client = client_for(_acct())
    assert client.post(url, {"platform": "web"}, format="json").status_code == 400
    bad = {"platform": "web", "subscription": {"endpoint": ENDPOINT, "keys": {}}}
    assert client.post(url, bad, format="json").status_code == 400


def test_only_the_owner_can_unsubscribe(client_for):
    owner = _acct()
    _token(owner)
    url = reverse("notifications:push-token")
    body = {"endpoint": ENDPOINT}
    assert client_for(_acct()).delete(url, body, format="json").status_code == 204
    assert PushDeviceToken.objects.exists()
    assert client_for(owner).delete(url, body, format="json").status_code == 204
    assert not PushDeviceToken.objects.exists()


def test_subscriptions_per_account_are_capped(client_for):
    me = _acct()
    client = client_for(me)
    url = reverse("notifications:push-token")
    for i in range(push.MAX_SUBSCRIPTIONS_PER_ACCOUNT + 2):
        body = {"platform": "web", "subscription": _subscription(f"{ENDPOINT}{i}")}
        assert client.post(url, body, format="json").status_code == 201
    assert PushDeviceToken.objects.filter(account_id=me).count() == (
        push.MAX_SUBSCRIPTIONS_PER_ACCOUNT
    )


def test_config_reports_state_without_the_private_key(client_for, settings):
    settings.VAPID_PUBLIC_KEY = ""
    url = reverse("notifications:push-config")
    assert client_for(_acct()).get(url).json()["data"] == {"enabled": False, "public_key": ""}
    settings.VAPID_PUBLIC_KEY = "pub"
    settings.VAPID_PRIVATE_KEY = "priv"
    data = client_for(_acct()).get(url).json()["data"]
    assert data == {"enabled": True, "public_key": "pub"}


# ---- delivery ----------------------------------------------------------------


def test_unset_keys_are_a_logged_no_op(settings, caplog):
    settings.VAPID_PUBLIC_KEY = ""
    settings.VAPID_PRIVATE_KEY = ""
    account = _acct()
    _token(account)
    with mock.patch("notifications.push.webpush") as send, caplog.at_level(logging.INFO):
        assert push.deliver(str(_notification(account).id)) == "disabled"
    send.assert_not_called()
    assert "VAPID keys are not set" in caplog.text


def test_notify_queues_a_push_after_commit(django_capture_on_commit_callbacks):
    account = _acct()
    with (
        mock.patch("notifications.tasks.deliver_push.delay") as delay,
        django_capture_on_commit_callbacks(execute=True),
    ):
        notification = services.notify(account, "follow", body="x")
    delay.assert_called_once_with(str(notification.id))


def test_payload_decrypts_to_the_notification(vapid):
    """The real pywebpush path, stopping only at the HTTP call to the push service."""
    receiver = ec.generate_private_key(ec.SECP256R1())
    public = receiver.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    auth = os.urandom(16)
    account = _acct()
    subscription = {"endpoint": ENDPOINT, "keys": {"p256dh": _b64(public), "auth": _b64(auth)}}
    _token(account, subscription=subscription)
    post_id = uuid.uuid4()
    notification = _notification(account, subject_ref=f"post:{post_id}")

    with mock.patch("requests.post") as http:
        http.return_value = mock.Mock(status_code=201, text="")
        assert push.deliver(str(notification.id)) == "sent"

    sent = http.call_args.kwargs
    assert sent["headers"]["ttl"] == str(push.TTL_SECONDS)
    assert sent["headers"]["authorization"].startswith("vapid ")
    plain = http_ece.decrypt(
        sent["data"], private_key=receiver, auth_secret=auth, version="aes128gcm"
    )
    payload = json.loads(plain)
    assert payload["url"] == f"/posts/{post_id}"
    assert payload["kind"] == "follow"
    assert NotificationDeliveryLog.objects.get(notification=notification).status == "sent"


def _failure(status):
    return WebPushException("nope", response=mock.Mock(status_code=status))


@pytest.mark.parametrize("status", [404, 410])
def test_expired_subscription_is_removed(vapid, status):
    account = _acct()
    _token(account)
    with mock.patch("notifications.push.webpush", side_effect=_failure(status)):
        assert push.deliver(str(_notification(account).id)) == "expired"
    assert not PushDeviceToken.objects.exists()


@pytest.mark.parametrize("status", [500, 503, 429])
def test_temporary_failures_retry(vapid, status):
    account = _acct()
    _token(account)
    with (
        mock.patch("notifications.push.webpush", side_effect=_failure(status)),
        pytest.raises(push.RetryablePushError),
    ):
        push.deliver(str(_notification(account).id))
    assert PushDeviceToken.objects.exists()


def test_rejected_push_is_logged_as_failed(vapid):
    account = _acct()
    _token(account)
    notification = _notification(account)
    with mock.patch("notifications.push.webpush", side_effect=_failure(400)):
        assert push.deliver(str(notification.id)) == "failed"
    assert NotificationDeliveryLog.objects.get(notification=notification).status == "failed"


def test_push_preference_mutes_delivery(vapid):
    account = _acct()
    _token(account)
    NotificationPreference.objects.create(account_id=account, prefs={"follow": {"push": False}})
    with mock.patch("notifications.push.webpush") as send:
        assert push.deliver(str(_notification(account).id)) == "muted"
    send.assert_not_called()


def test_quiet_hours_hold_back_push(vapid):
    account = _acct()
    _token(account)
    NotificationPreference.objects.create(
        account_id=account, quiet_hours={"start": "00:00", "end": "23:59", "timezone": "UTC"}
    )
    with (
        mock.patch("notifications.push.webpush") as send,
        mock.patch("notifications.push.in_quiet_hours", return_value=True),
    ):
        assert push.deliver(str(_notification(account).id)) == "quiet"
    send.assert_not_called()


@pytest.mark.parametrize(
    ("hour", "window", "expected"),
    [
        (23, ("22:00", "07:00"), True),
        (3, ("22:00", "07:00"), True),
        (7, ("22:00", "07:00"), False),
        (12, ("22:00", "07:00"), False),
        (13, ("09:00", "17:00"), True),
        (17, ("09:00", "17:00"), False),
    ],
)
def test_quiet_hours_windows(hour, window, expected):
    now = datetime(2026, 1, 1, hour, 0, tzinfo=UTC)
    quiet = {"start": window[0], "end": window[1], "timezone": "UTC"}
    assert push.in_quiet_hours(quiet, now) is expected


def test_quiet_hours_use_the_saved_timezone():
    now = datetime(2026, 1, 1, 21, 0, tzinfo=UTC)  # 23:00 in Cairo
    quiet = {"start": "22:00", "end": "07:00", "timezone": "Africa/Cairo"}
    assert push.in_quiet_hours(quiet, now) is True
    assert push.in_quiet_hours({**quiet, "timezone": "UTC"}, now) is False
