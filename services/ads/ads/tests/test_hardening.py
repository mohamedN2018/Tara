"""Review-pass regressions: budget under concurrency, self-review, report query, throttles."""

import threading
import uuid
from decimal import Decimal

import pytest
from django.db import connection, transaction
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework.throttling import ScopedRateThrottle

from ads import media_client, services, views
from ads.internal_views import FeedSlotView
from ads.models import AdBudgetLedger, AdClickEvent, AdvertiserAccount, Campaign
from tara_common.auth import verify_internal_token
from tara_common.exceptions import TaraAPIError
from tara_common.throttling import WriteThrottle


def _acct() -> str:
    return str(uuid.uuid4())


def _active_creative(owner, *, cpc="1.00", budget="100.00"):
    campaign = services.create_campaign(owner, {"name": "C", "budget": budget})
    ad_set = services.create_ad_set(
        owner, str(campaign.id), {"placement": "feed", "cpc": cpc, "cpm": "0", "frequency_cap": 9}
    )
    return campaign, services.create_creative(owner, str(ad_set.id), {"headline": "H"})


@pytest.mark.django_db
def test_a_click_never_charges_past_the_budget():
    campaign, creative = _active_creative(_acct(), cpc="5.00", budget="1.00")
    services.record_event("click", str(creative.id), _acct())
    campaign.refresh_from_db()
    assert campaign.spent == Decimal("1.00")
    assert campaign.status == Campaign.Status.COMPLETED
    assert AdBudgetLedger.objects.get().amount == Decimal("1.00")


@pytest.mark.django_db(transaction=True)
def test_an_event_waiting_on_the_lock_rechecks_the_budget():
    """The pre-lock read says active; by the time the lock is ours the budget is gone."""
    campaign, creative = _active_creative(_acct(), cpc="1.00", budget="1.00")
    locked = threading.Event()
    release = threading.Event()

    def spend_the_rest() -> None:
        try:
            with transaction.atomic():
                row = Campaign.objects.select_for_update().get(id=campaign.id)
                locked.set()
                release.wait(5)
                row.spent, row.status = row.budget, Campaign.Status.COMPLETED
                row.save(update_fields=["spent", "status"])
        finally:
            connection.close()

    errors: list = []

    def click() -> None:
        try:
            services.record_event("click", str(creative.id), _acct())
        except TaraAPIError as exc:
            errors.append(exc)
        finally:
            connection.close()

    holder = threading.Thread(target=spend_the_rest)
    holder.start()
    assert locked.wait(5)
    clicker = threading.Thread(target=click)
    clicker.start()
    clicker.join(0.5)  # blocked on the row lock, past the unlocked status check
    release.set()
    holder.join(5)
    clicker.join(5)

    campaign.refresh_from_db()
    assert campaign.spent == Decimal("1.00")  # not 2.00
    assert len(errors) == 1 and errors[0].http_status == 409
    assert not AdClickEvent.objects.exists()


@pytest.mark.django_db
def test_a_reviewer_cannot_review_their_own_creative(client_for, settings):
    settings.ADS_AUTO_APPROVE = False
    owner = _acct()
    _campaign, creative = _active_creative(owner)
    queue = client_for(owner, roles=["ad_reviewer"]).get(reverse("ads:review-queue"))
    assert str(creative.id) not in [row["id"] for row in queue.json()["data"]]
    url = reverse("ads:review", args=[creative.id])
    own = client_for(owner, roles=["ad_reviewer"]).post(url, {"decision": "approved"})
    assert own.status_code == 403
    creative.refresh_from_db()
    assert creative.review_status == "pending"
    other = client_for(_acct(), roles=["ad_reviewer"]).post(url, {"decision": "approved"})
    assert other.status_code == 200


@pytest.mark.django_db
def test_report_counts_each_event_table_without_joining_them(client_for):
    owner = _acct()
    campaign, creative = _active_creative(owner, budget="1000.00")
    for _ in range(3):
        services.record_event("impression", str(creative.id), _acct())
    for _ in range(2):
        services.record_event("click", str(creative.id), _acct())
    with CaptureQueriesContext(connection) as ctx:
        report = services.campaign_report(owner, str(campaign.id))
    assert (report["impressions"], report["clicks"]) == (3, 2)
    assert report["creatives"][0]["impressions"] == 3
    assert report["creatives"][0]["clicks"] == 2
    for q in ctx.captured_queries:
        sql = q["sql"]
        assert not ('JOIN "ad_impression_event"' in sql and 'JOIN "ad_click_event"' in sql)


def test_write_endpoints_are_throttled_and_events_keep_their_own_scope():
    assert any(isinstance(t, WriteThrottle) for t in views.CampaignsView().get_throttles())
    assert [type(t) for t in views.EventsView().get_throttles()] == [ScopedRateThrottle]
    assert FeedSlotView().get_throttles() == []


# ---- creative media ---------------------------------------------------------


class _FakeMedia:
    def __init__(self):
        self.assets: dict = {}
        self.down = False

    def add(self, owner, *, kind="image", status="ready") -> str:
        media_id = str(uuid.uuid4())
        self.assets[media_id] = media_client.MediaInfo(media_id, str(owner), kind, status)
        return media_id

    def lookup(self, media_ids):
        if self.down:
            raise media_client._unavailable()
        return {m: self.assets[m] for m in map(str, media_ids) if m in self.assets}


@pytest.fixture
def media(monkeypatch):
    fake = _FakeMedia()
    monkeypatch.setattr(media_client, "lookup", fake.lookup)
    return fake


def _post_creative(client, ad_set_id, media_id):
    return client.post(
        reverse("ads:creatives", args=[ad_set_id]),
        {"headline": "H", "media_id": media_id},
        format="json",
    )


@pytest.mark.django_db
def test_creative_media_must_be_the_advertisers_own_ready_image(client_for, media):
    owner = _acct()
    campaign, _ = _active_creative(owner)
    ad_set_id = campaign.ad_sets.get().id
    c = client_for(owner)
    cases = [
        (media.add(_acct()), "media_not_owned"),  # someone else's
        (str(uuid.uuid4()), "media_not_owned"),  # unknown
        (media.add(owner, kind="video"), "media_kind_not_allowed"),
        (media.add(owner, status="processing"), "media_not_ready"),
    ]
    for media_id, code in cases:
        resp = _post_creative(c, ad_set_id, media_id)
        assert resp.status_code == 400, resp.content
        assert resp.json()["error"]["details"][0]["code"] == code
    assert campaign.ad_sets.get().creatives.count() == 1  # only the fixture's
    assert _post_creative(c, ad_set_id, media.add(owner)).status_code == 201


@pytest.mark.django_db
def test_media_down_fails_closed_and_writes_nothing(client_for, media):
    owner = _acct()
    campaign, _ = _active_creative(owner)
    media.down = True
    resp = _post_creative(client_for(owner), campaign.ad_sets.get().id, media.add(owner))
    assert resp.status_code == 503
    assert campaign.ad_sets.get().creatives.count() == 1


@pytest.mark.django_db
def test_media_client_signs_an_internal_token_for_the_batch_endpoint(monkeypatch, settings):
    calls = []

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"id": "m1", "owner_id": "o", "kind": "image", "status": "ready"}]}

    def fake_post(url, json, headers, timeout):
        calls.append((url, json, headers))
        return _Resp()

    monkeypatch.setattr(media_client.requests, "post", fake_post)
    settings.MEDIA_INTERNAL_URL = "http://media:8000"
    assert media_client.lookup(["m1"])["m1"].owner_id == "o"
    url, body, headers = calls[0]
    assert url == "http://media:8000/internal/v1/media/batch/" and body == {"ids": ["m1"]}
    token = headers["Authorization"].removeprefix("Bearer ")
    assert verify_internal_token(token, expected_audience="media-internal")["iss"] == "ads"


# ---- campaigns ----------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_pause_waits_for_a_concurrent_final_charge_and_then_refuses():
    owner = _acct()
    campaign, _ = _active_creative(owner)
    locked, release = threading.Event(), threading.Event()

    def finish() -> None:
        try:
            with transaction.atomic():
                row = Campaign.objects.select_for_update().get(id=campaign.id)
                locked.set()
                release.wait(5)
                row.spent, row.status = row.budget, Campaign.Status.COMPLETED
                row.save(update_fields=["spent", "status"])
        finally:
            connection.close()

    errors: list = []

    def pause() -> None:
        try:
            with transaction.atomic():
                services.set_campaign_status(owner, str(campaign.id), Campaign.Status.PAUSED)
        except TaraAPIError as exc:
            errors.append(exc)
        finally:
            connection.close()

    holder = threading.Thread(target=finish)
    holder.start()
    assert locked.wait(5)
    pauser = threading.Thread(target=pause)
    pauser.start()
    pauser.join(0.5)
    release.set()
    holder.join(5)
    pauser.join(5)
    campaign.refresh_from_db()
    assert campaign.status == Campaign.Status.COMPLETED  # not overwritten by the pause
    assert len(errors) == 1 and errors[0].http_status == 409


@pytest.mark.django_db
@pytest.mark.parametrize(
    "body,field",
    [
        (
            {"schedule_start": "2026-12-02T00:00:00Z", "schedule_end": "2026-12-01T00:00:00Z"},
            "schedule_end",
        ),
        (
            {"schedule_start": "2026-12-01T00:00:00Z", "schedule_end": "2026-12-01T00:00:00Z"},
            "schedule_end",
        ),
        ({"currency": "XYZ"}, "currency"),
        ({"currency": "$"}, "currency"),
    ],
)
def test_campaign_schedule_and_currency_are_validated(client_for, body, field):
    resp = client_for(_acct()).post(
        reverse("ads:campaigns"), {"name": "C", "budget": "10", **body}, format="json"
    )
    assert resp.status_code == 400, resp.content
    assert field in str(resp.json()["error"])
    assert not Campaign.objects.exists()


@pytest.mark.django_db
def test_campaign_currency_is_upper_cased(client_for):
    resp = client_for(_acct()).post(
        reverse("ads:campaigns"), {"name": "C", "budget": "10", "currency": "kwd"}, format="json"
    )
    assert resp.status_code == 201 and resp.json()["data"]["currency"] == "KWD"


@pytest.mark.django_db
def test_listing_campaigns_creates_no_advertiser(client_for):
    resp = client_for(_acct()).get(reverse("ads:campaigns"))
    assert resp.status_code == 200 and resp.json()["data"] == []
    assert not AdvertiserAccount.objects.exists()
