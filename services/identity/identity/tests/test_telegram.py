"""Telegram phone verification: deep link, secret-guarded webhook, share contact.

The Bot API is mocked at the HTTP layer (urllib.request.urlopen), so replies
and the webhook command go through the real request-building code.
"""

from __future__ import annotations

import hashlib
import io
import json
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from django.core.management import CommandError, call_command
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from identity import telegram
from identity.checks import telegram_webhook_secret_check
from identity.models import Account, OutboxEvent, PhoneVerification, SecurityEvent

pytestmark = pytest.mark.django_db

BOT_TOKEN = "123456:TEST-token"
SECRET = "s3cret_" + "a" * 40
TG_USER = 777001


class FakeBotAPI:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.fail = False

    def __call__(self, request, timeout=None):
        method = request.full_url.rsplit("/", 1)[-1]
        self.calls.append((method, json.loads(request.data.decode())))
        if self.fail:
            raise OSError("network down")
        return io.BytesIO(json.dumps({"ok": True, "result": True}).encode())

    def messages(self):
        return [payload for method, payload in self.calls if method == "sendMessage"]


@pytest.fixture
def bot(monkeypatch):
    fake = FakeBotAPI()
    monkeypatch.setattr(telegram.urllib.request, "urlopen", fake)
    return fake


@pytest.fixture
def telegram_on(settings, bot):
    settings.TELEGRAM_BOT_TOKEN = BOT_TOKEN
    settings.TELEGRAM_BOT_USERNAME = "tara_test_bot"
    settings.TELEGRAM_WEBHOOK_SECRET = SECRET
    return bot


@pytest.fixture
def signed_in(api_client, active_account):
    resp = api_client.post(
        reverse("identity:login"),
        {"email": active_account.email, "password": "DevPassw0rd!"},
        format="json",
    )
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.json()['data']['access_token']}")
    return api_client


def _webhook(client, update, secret=SECRET):
    from rest_framework.test import APIClient

    headers = {"HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN": secret} if secret is not None else {}
    return APIClient().post(reverse("identity:telegram-webhook"), update, format="json", **headers)


def _msg(*, text=None, contact=None, user_id=TG_USER, chat_id=None, chat_type="private"):
    message = {
        "message_id": 1,
        "from": {"id": user_id, "is_bot": False, "first_name": "T"},
        "chat": {"id": chat_id or user_id, "type": chat_type},
    }
    if text is not None:
        message["text"] = text
    if contact is not None:
        message["contact"] = contact
    return {"update_id": 1, "message": message}


def _contact(phone="+20 100 123 4567", user_id=TG_USER):
    return {"phone_number": phone, "first_name": "T", "user_id": user_id}


def _start_code(client) -> str:
    resp = client.post(reverse("identity:me-phone-telegram"))
    assert resp.status_code == 200, resp.content
    link = resp.json()["data"]["deep_link"]
    assert link.startswith("https://t.me/tara_test_bot?start=")
    return parse_qs(urlparse(link).query)["start"][0]


def _run(client, update, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        resp = _webhook(client, update)
    assert resp.status_code == 200
    return resp


# ---- enablement and webhook guard -------------------------------------------


def test_disabled_by_default(api_client, signed_in):
    body = api_client.get(reverse("identity:auth-providers")).json()["data"]
    assert body["telegram"] == {"enabled": False, "bot_username": ""}
    assert signed_in.post(reverse("identity:me-phone-telegram")).status_code == 404
    assert _webhook(api_client, _msg(text="/start x")).status_code == 404


def test_needs_all_three_settings(settings, bot):
    settings.TELEGRAM_BOT_TOKEN = BOT_TOKEN
    settings.TELEGRAM_BOT_USERNAME = "tara_test_bot"
    settings.TELEGRAM_WEBHOOK_SECRET = ""
    assert telegram.telegram_enabled() is False


def test_providers_report_bot_when_enabled(api_client, telegram_on):
    body = api_client.get(reverse("identity:auth-providers")).json()["data"]
    assert body["telegram"] == {"enabled": True, "bot_username": "tara_test_bot"}


@pytest.mark.parametrize("secret", [None, "", "wrong-secret", SECRET + "x"])
def test_webhook_rejects_missing_or_wrong_secret(api_client, telegram_on, secret):
    resp = _webhook(api_client, _msg(text="/start abc"), secret=secret)
    assert resp.status_code == 403
    assert telegram_on.calls == []


def test_secret_in_query_or_path_is_not_accepted(api_client, telegram_on):
    from rest_framework.test import APIClient

    resp = APIClient().post(
        reverse("identity:telegram-webhook") + f"?secret={SECRET}",
        _msg(text="/start x"),
        format="json",
    )
    assert resp.status_code == 403


def test_start_requires_auth(api_client, telegram_on):
    assert api_client.post(reverse("identity:me-phone-telegram")).status_code == 401


# ---- happy path -------------------------------------------------------------


def test_full_verification_flow(
    api_client, signed_in, active_account, telegram_on, django_capture_on_commit_callbacks
):
    code = _start_code(signed_in)
    # Only the hash is stored.
    attempt = PhoneVerification.objects.get(account=active_account)
    assert attempt.code_hash == hashlib.sha256(code.encode()).hexdigest()
    assert code not in attempt.code_hash

    _run(api_client, _msg(text=f"/start {code}"), django_capture_on_commit_callbacks)
    ask = telegram_on.messages()[-1]
    assert ask["chat_id"] == str(TG_USER)
    assert ask["reply_markup"]["keyboard"][0][0]["request_contact"] is True

    _run(api_client, _msg(contact=_contact()), django_capture_on_commit_callbacks)
    active_account.refresh_from_db()
    assert active_account.phone == "+201001234567"
    assert active_account.phone_verified is True
    assert "remove_keyboard" in telegram_on.messages()[-1]["reply_markup"]

    event = OutboxEvent.objects.get(event_type="account.phone_verified")
    assert event.payload["payload"] == {
        "phone_verified": True,
        "channel": "telegram",
    }  # no raw number
    assert SecurityEvent.objects.filter(account=active_account, type="phone_verified").exists()
    overview = signed_in.get(reverse("identity:me-security")).json()["data"]
    assert overview["phone"] == "+201001234567" and overview["phone_verified"] is True


def test_remove_phone(signed_in, active_account):
    Account.objects.filter(id=active_account.id).update(
        phone="+201001234567", phone_verified_at=timezone.now()
    )
    resp = signed_in.delete(reverse("identity:me-phone"))
    assert resp.status_code == 200
    assert resp.json()["data"]["phone_verified"] is False
    assert OutboxEvent.objects.filter(event_type="account.phone_removed").exists()


# ---- security cases ---------------------------------------------------------


def test_forwarded_contact_is_rejected(
    api_client, signed_in, active_account, telegram_on, django_capture_on_commit_callbacks
):
    code = _start_code(signed_in)
    _run(api_client, _msg(text=f"/start {code}"), django_capture_on_commit_callbacks)
    # Someone else's contact card (user_id is not the sender).
    _run(api_client, _msg(contact=_contact(user_id=999)), django_capture_on_commit_callbacks)
    _run(
        api_client,
        _msg(contact={"phone_number": "+201001234567"}),
        django_capture_on_commit_callbacks,
    )
    active_account.refresh_from_db()
    assert active_account.phone_verified is False


def test_contact_from_a_different_telegram_user_is_rejected(
    api_client, signed_in, active_account, telegram_on, django_capture_on_commit_callbacks
):
    code = _start_code(signed_in)
    _run(api_client, _msg(text=f"/start {code}"), django_capture_on_commit_callbacks)
    intruder = 555
    _run(
        api_client,
        _msg(contact=_contact(user_id=intruder), user_id=intruder, chat_id=TG_USER),
        django_capture_on_commit_callbacks,
    )
    active_account.refresh_from_db()
    assert active_account.phone_verified is False


def test_code_claimed_by_one_telegram_user_cannot_be_reused_by_another(
    api_client, signed_in, active_account, telegram_on, django_capture_on_commit_callbacks
):
    code = _start_code(signed_in)
    _run(api_client, _msg(text=f"/start {code}"), django_capture_on_commit_callbacks)
    _run(api_client, _msg(text=f"/start {code}", user_id=555), django_capture_on_commit_callbacks)
    attempt = PhoneVerification.objects.get(account=active_account)
    assert attempt.telegram_user_id == TG_USER
    assert "invalid or expired" in telegram_on.messages()[-1]["text"]


def test_contact_without_start_is_rejected(
    api_client, active_account, telegram_on, django_capture_on_commit_callbacks
):
    _run(api_client, _msg(contact=_contact()), django_capture_on_commit_callbacks)
    assert not Account.objects.filter(phone_verified_at__isnull=False).exists()


def test_expired_code_is_rejected(
    api_client, signed_in, active_account, telegram_on, django_capture_on_commit_callbacks
):
    code = _start_code(signed_in)
    PhoneVerification.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
    _run(api_client, _msg(text=f"/start {code}"), django_capture_on_commit_callbacks)
    _run(api_client, _msg(contact=_contact()), django_capture_on_commit_callbacks)
    active_account.refresh_from_db()
    assert active_account.phone_verified is False


def test_new_link_supersedes_the_old_one(
    api_client, signed_in, active_account, telegram_on, django_capture_on_commit_callbacks
):
    old = _start_code(signed_in)
    _start_code(signed_in)
    _run(api_client, _msg(text=f"/start {old}"), django_capture_on_commit_callbacks)
    assert "invalid or expired" in telegram_on.messages()[-1]["text"]


def test_group_chats_are_ignored(
    api_client, signed_in, active_account, telegram_on, django_capture_on_commit_callbacks
):
    code = _start_code(signed_in)
    _run(
        api_client,
        _msg(text=f"/start {code}", chat_id=-100123, chat_type="supergroup"),
        django_capture_on_commit_callbacks,
    )
    assert PhoneVerification.objects.get().telegram_chat_id == ""
    assert telegram_on.messages() == []


def test_number_verified_on_another_account_is_refused(
    api_client, signed_in, active_account, telegram_on, django_capture_on_commit_callbacks
):
    Account.objects.create_user(
        email="owner@tara.local",
        password="DevPassw0rd!",
        phone="+201001234567",
        phone_verified_at=timezone.now(),
    )
    code = _start_code(signed_in)
    _run(api_client, _msg(text=f"/start {code}"), django_capture_on_commit_callbacks)
    _run(api_client, _msg(contact=_contact()), django_capture_on_commit_callbacks)
    active_account.refresh_from_db()
    assert active_account.phone_verified is False
    assert "another Tara account" in telegram_on.messages()[-1]["text"]


@pytest.mark.parametrize(
    "update",
    [
        {},
        {"message": "nope"},
        {"message": {"chat": "x"}},
        {"message": {"from": {"id": "string"}, "chat": {"id": 1, "type": "private"}}},
        {"edited_message": {"text": "/start x"}},
        _msg(contact=_contact(phone="not a phone")),
    ],
)
def test_malformed_updates_never_fail_the_webhook(api_client, telegram_on, update):
    assert _webhook(api_client, update).status_code == 200


def test_webhook_survives_bot_api_outage(
    api_client, signed_in, telegram_on, django_capture_on_commit_callbacks
):
    code = _start_code(signed_in)
    telegram_on.fail = True
    resp = _run(api_client, _msg(text=f"/start {code}"), django_capture_on_commit_callbacks)
    assert resp.status_code == 200


def test_bot_api_errors_never_leak_the_token(telegram_on):
    telegram_on.fail = True
    with pytest.raises(telegram.TelegramError) as exc:
        telegram.bot_api("getMe", {})
    assert BOT_TOKEN not in str(exc.value)


def test_phone_normalisation():
    assert telegram.normalize_phone("201001234567") == "+201001234567"
    assert telegram.normalize_phone("+1 (555) 010-9999") == "+15550109999"
    assert telegram.normalize_phone("12") is None
    assert telegram.normalize_phone("+0123456789") is None
    assert telegram.normalize_phone(None) is None


# ---- management command and deploy check ------------------------------------


def test_set_webhook_command_registers_url_and_secret(telegram_on):
    out = io.StringIO()
    call_command("set_telegram_webhook", url="https://tara.example/", stdout=out)
    method, payload = telegram_on.calls[-1]
    assert method == "setWebhook"
    assert payload["url"] == "https://tara.example/api/v1/auth/telegram/webhook/"
    assert payload["secret_token"] == SECRET
    assert SECRET not in payload["url"]
    assert SECRET not in out.getvalue()


def test_delete_webhook_command(telegram_on):
    call_command("set_telegram_webhook", delete=True, stdout=io.StringIO())
    assert telegram_on.calls[-1][0] == "deleteWebhook"


def test_set_webhook_command_refuses_unsafe_config(settings, telegram_on):
    with pytest.raises(CommandError):
        call_command("set_telegram_webhook", url="http://insecure.example", stdout=io.StringIO())
    settings.TELEGRAM_WEBHOOK_SECRET = "short"
    with pytest.raises(CommandError):
        call_command("set_telegram_webhook", url="https://tara.example", stdout=io.StringIO())
    settings.TELEGRAM_BOT_TOKEN = ""
    with pytest.raises(CommandError):
        call_command("set_telegram_webhook", url="https://tara.example", stdout=io.StringIO())
    assert all(method != "setWebhook" for method, _ in telegram_on.calls)


def test_deploy_check_flags_weak_webhook_secret():
    with override_settings(TELEGRAM_BOT_TOKEN="", TELEGRAM_WEBHOOK_SECRET=""):
        assert telegram_webhook_secret_check() == []
    with override_settings(TELEGRAM_BOT_TOKEN=BOT_TOKEN, TELEGRAM_WEBHOOK_SECRET="weak"):
        assert [e.id for e in telegram_webhook_secret_check()] == ["identity.E001"]
    with override_settings(TELEGRAM_BOT_TOKEN=BOT_TOKEN, TELEGRAM_WEBHOOK_SECRET=SECRET):
        assert telegram_webhook_secret_check() == []
