"""Full registration (plan 08 track 1D, roadmap 2.12): names, confirmed password,
date of birth and the age claims, gender, and the recorded legal consent."""

from __future__ import annotations

import re
from datetime import date, timedelta

import jwt
import pytest
from django.core import mail
from django.urls import reverse

from identity import age
from identity.models import Account, LegalConsent, OutboxEvent
from identity.services import consent_ip_hash
from identity.tests.signup import adult_birth_date, signup_data

pytestmark = pytest.mark.django_db

PASSWORD = "DevPassw0rd!"
URL = reverse("identity:register")


def _register(client, email="new@tara.local", **fields):
    return client.post(URL, signup_data(email, PASSWORD, **fields), format="json")


def _detail(resp) -> tuple[str, str]:
    assert resp.status_code == 400, resp.content
    body = resp.json()["error"]
    assert body["code"] == "validation_error"
    first = body["details"][0]
    return first["field"], first["code"]


def _years_ago(years: int, *, days: int = 0) -> str:
    today = age.today()
    try:
        born = today.replace(year=today.year - years)
    except ValueError:  # 29 February
        born = today.replace(year=today.year - years, day=28)
    return (born + timedelta(days=days)).isoformat()


def _claims_after_signing_up(client, email: str, dob: str, capture) -> dict:
    """Register, verify through the mailed link, log in: the access token's claims."""
    with capture(execute=True):
        assert _register(client, email, date_of_birth=dob).status_code == 201
    token = re.search(r"token=([\w-]+)", mail.outbox[-1].body).group(1)
    verified = client.post(reverse("identity:verify-email"), {"token": token}, format="json")
    assert verified.status_code == 200
    login = client.post(
        reverse("identity:login"), {"email": email, "password": PASSWORD}, format="json"
    )
    assert login.status_code == 200, login.content
    return jwt.decode(login.json()["data"]["access_token"], options={"verify_signature": False})


# ---- the happy path ---------------------------------------------------------


def test_a_full_registration_stores_the_new_fields(api_client):
    resp = _register(
        api_client,
        first_name="  ليلى ",
        last_name="أحمد",
        handle="laila_a",
        gender="female",
        date_of_birth="1995-03-14",
    )
    assert resp.status_code == 201, resp.content
    account = Account.objects.get(email="new@tara.local")
    assert account.date_of_birth == date(1995, 3, 14)
    assert account.gender == "female" and account.gender_custom == ""
    # Decisions 5.3 and 5.8: birthday to friends, gender to the owner only.
    assert account.birthday_visibility == "friends"
    assert account.gender_visibility == "only_me"


def test_profile_gets_the_names_but_the_bus_never_gets_age_or_gender(api_client):
    _register(api_client, first_name="Omar", last_name="Nabil", gender="male")
    payload = OutboxEvent.objects.get(event_type="account.registered").payload["payload"]
    assert payload["first_name"] == "Omar" and payload["last_name"] == "Nabil"
    assert payload["display_name"] == "Omar Nabil"
    text = str(payload)
    for leaked in ("date_of_birth", "is_minor", "gender", adult_birth_date(), "new@tara.local"):
        assert leaked not in text


def test_the_payload_matches_its_schema(api_client):
    import json
    from pathlib import Path

    schema_path = Path("/opt/tara/libs/tara_events/tara_events/schemas/account.registered.v1.json")
    if not schema_path.exists():
        pytest.skip("schemas are copied into the image at /opt/tara/libs")
    schema = json.loads(schema_path.read_text())
    _register(api_client)
    payload = OutboxEvent.objects.get(event_type="account.registered").payload["payload"]
    assert set(schema["required"]) <= set(payload) <= set(schema["properties"])


# ---- confirm password -------------------------------------------------------


def test_a_password_mismatch_is_refused_by_the_server(api_client):
    resp = api_client.post(
        URL,
        signup_data("mismatch@tara.local", PASSWORD, password_confirm=PASSWORD + "x"),
        format="json",
    )
    assert _detail(resp) == ("password_confirm", "password_mismatch")
    assert not Account.objects.filter(email="mismatch@tara.local").exists()


def test_a_missing_confirmation_is_refused(api_client):
    data = signup_data("noconfirm@tara.local", PASSWORD)
    del data["password_confirm"]
    assert _detail(api_client.post(URL, data, format="json")) == ("password_confirm", "required")


# ---- consent ----------------------------------------------------------------


@pytest.mark.parametrize("consent", [None, False, "false"])
def test_registration_needs_consent(api_client, consent):
    data = signup_data("noconsent@tara.local", PASSWORD)
    if consent is None:
        del data["accept_terms"]
    else:
        data["accept_terms"] = consent
    assert _detail(api_client.post(URL, data, format="json")) == (
        "accept_terms",
        "consent_required",
    )
    assert not Account.objects.filter(email="noconsent@tara.local").exists()


def test_the_consent_record_keeps_the_versions_and_only_a_hashed_address(api_client, settings):
    settings.LEGAL_TERMS_VERSION = "2026-12-01"
    settings.LEGAL_PRIVACY_VERSION = "2026-12-02"
    resp = api_client.post(
        URL,
        signup_data("consent@tara.local", PASSWORD),
        format="json",
        REMOTE_ADDR="203.0.113.9",
    )
    assert resp.status_code == 201, resp.content
    consent = LegalConsent.objects.get(account__email="consent@tara.local")
    assert (consent.terms_version, consent.privacy_version) == ("2026-12-01", "2026-12-02")
    assert consent.source == "register" and consent.accepted_at is not None
    assert re.fullmatch(r"[0-9a-f]{64}", consent.ip_hash)
    assert consent.ip_hash == consent_ip_hash("203.0.113.9")
    assert "203.0.113.9" not in str(LegalConsent.objects.values().get())


def test_the_ip_hash_is_keyed_and_stable():
    assert consent_ip_hash("198.51.100.1") == consent_ip_hash("198.51.100.1")
    assert consent_ip_hash("198.51.100.1") != consent_ip_hash("198.51.100.2")
    import hashlib

    assert consent_ip_hash("198.51.100.1") != hashlib.sha256(b"198.51.100.1").hexdigest()
    assert consent_ip_hash("") == ""


@pytest.mark.parametrize("field", ["terms_version", "privacy_version"])
def test_an_outdated_legal_version_is_refused(api_client, field):
    resp = _register(api_client, **{field: "2020-01-01"})
    assert _detail(resp) == (field, "legal_version_mismatch")


# ---- date of birth ----------------------------------------------------------


def test_under_the_minimum_age_is_refused(api_client):
    resp = _register(api_client, date_of_birth=_years_ago(13, days=1))  # 13 tomorrow
    assert _detail(resp) == ("date_of_birth", "age_below_minimum")
    assert not Account.objects.exists()


def test_the_minimum_age_birthday_is_allowed(api_client):
    assert _register(api_client, date_of_birth=_years_ago(13)).status_code == 201


def test_the_minimum_age_is_a_setting(api_client, settings):
    settings.REGISTRATION_MIN_AGE = 16
    resp = _register(api_client, date_of_birth=_years_ago(15))
    assert _detail(resp) == ("date_of_birth", "age_below_minimum")


@pytest.mark.parametrize("dob", ["2999-01-01", "1850-01-01", "not-a-date", ""])
def test_an_impossible_date_of_birth_is_refused(api_client, dob):
    field, code = _detail(_register(api_client, date_of_birth=dob))
    assert field == "date_of_birth" and code in ("invalid_date", "invalid", "validation_error")


def test_the_date_of_birth_is_required(api_client):
    data = signup_data("nodob@tara.local", PASSWORD)
    del data["date_of_birth"]
    assert _detail(api_client.post(URL, data, format="json")) == ("date_of_birth", "required")


# ---- the age claims ---------------------------------------------------------


def test_a_minor_gets_is_minor_in_the_token(api_client, django_capture_on_commit_callbacks):
    claims = _claims_after_signing_up(
        api_client, "teen@tara.local", _years_ago(15), django_capture_on_commit_callbacks
    )
    assert claims["is_minor"] is True
    assert claims["age_band"] == "13-17"
    assert "date_of_birth" not in claims


def test_an_adult_is_not_a_minor(api_client, django_capture_on_commit_callbacks):
    claims = _claims_after_signing_up(
        api_client, "adult@tara.local", _years_ago(30), django_capture_on_commit_callbacks
    )
    assert claims["is_minor"] is False
    assert claims["age_band"] == "25-34"


def test_an_account_from_before_the_age_gate_is_unknown(active_account):
    from identity.tokens import issue_access_token

    token, _ = issue_access_token(active_account, "sid")
    claims = jwt.decode(token, options={"verify_signature": False})
    assert claims["is_minor"] is False and claims["age_band"] == "unknown"


def test_turning_18_takes_effect_at_the_next_token(active_account):
    from identity.tokens import issue_access_token

    active_account.date_of_birth = date.fromisoformat(_years_ago(18, days=1))
    active_account.save()
    token, _ = issue_access_token(active_account, "sid")
    assert jwt.decode(token, options={"verify_signature": False})["is_minor"] is True
    active_account.date_of_birth = date.fromisoformat(_years_ago(18))
    active_account.save()
    token, _ = issue_access_token(active_account, "sid")
    assert jwt.decode(token, options={"verify_signature": False})["is_minor"] is False


@pytest.mark.parametrize(
    "born,on,years",
    [
        (date(2008, 2, 29), date(2026, 2, 28), 17),  # a leap-day birthday...
        (date(2008, 2, 29), date(2026, 3, 1), 18),  # ...counts from 1 March
        (date(2000, 6, 15), date(2026, 6, 14), 25),
        (date(2000, 6, 15), date(2026, 6, 15), 26),
    ],
)
def test_age_in_whole_years(born, on, years):
    assert age.age_on(born, on) == years


@pytest.mark.parametrize(
    "years,band",
    [(13, "13-17"), (17, "13-17"), (18, "18-24"), (34, "25-34"), (40, "35-44"), (70, "45+")],
)
def test_age_bands(years, band):
    on = date(2026, 11, 4)
    assert age.age_band(date(2026 - years, 1, 1), on) == band


# ---- names and gender -------------------------------------------------------


@pytest.mark.parametrize("field", ["first_name", "last_name"])
def test_both_names_are_required(api_client, field):
    data = signup_data("noname@tara.local", PASSWORD)
    del data[field]
    assert _detail(api_client.post(URL, data, format="json")) == (field, "required")


def test_a_name_needs_letters(api_client):
    assert _detail(_register(api_client, first_name="1234 !!")) == ("first_name", "invalid_name")


def test_a_custom_gender_needs_its_words(api_client):
    assert _detail(_register(api_client, gender="custom")) == ("gender_custom", "required")
    resp = _register(api_client, "custom@tara.local", gender="custom", gender_custom=" non-binary ")
    assert resp.status_code == 201
    account = Account.objects.get(email="custom@tara.local")
    assert (account.gender, account.gender_custom) == ("custom", "non-binary")


def test_custom_words_are_dropped_for_other_genders(api_client):
    _register(api_client, gender="prefer_not_to_say", gender_custom="ignored")
    account = Account.objects.get(email="new@tara.local")
    assert (account.gender, account.gender_custom) == ("prefer_not_to_say", "")


def test_gender_is_optional_and_never_in_the_token(api_client, django_capture_on_commit_callbacks):
    claims = _claims_after_signing_up(
        api_client, "nogender@tara.local", adult_birth_date(), django_capture_on_commit_callbacks
    )
    assert "gender" not in claims
    assert Account.objects.get(email="nogender@tara.local").gender == ""


def test_an_unknown_gender_value_is_refused(api_client):
    assert _detail(_register(api_client, gender="robot"))[0] == "gender"


# ---- no mail server yet (EMAIL_VERIFICATION_REQUIRED=false) ------------------


def test_without_email_verification_the_account_is_active_at_once(
    api_client, settings, django_capture_on_commit_callbacks
):
    settings.EMAIL_VERIFICATION_REQUIRED = False
    with django_capture_on_commit_callbacks(execute=True):
        resp = _register(api_client, "nomail@tara.local")
    assert resp.status_code == 201, resp.content
    assert resp.json()["data"]["status"] == "active"
    account = Account.objects.get(email="nomail@tara.local")
    assert account.email_verified is True
    assert mail.outbox == []  # no link is mailed
    types = [
        e.event_type
        for e in OutboxEvent.objects.all()
        if e.payload.get("subject_id") == str(account.id)
    ]
    assert "account.registered" in types and "account.verified" in types
    login = api_client.post(
        reverse("identity:login"),
        {"email": "nomail@tara.local", "password": PASSWORD},
        format="json",
    )
    assert login.status_code == 200, login.content


def test_email_verification_stays_on_by_default(api_client, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        resp = _register(api_client, "withmail@tara.local")
    assert resp.json()["data"]["status"] == "pending"
    assert len(mail.outbox) == 1
