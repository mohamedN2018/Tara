"""Ads manager (T6): objective and schedule, served placements only, the
marketplace slot, rejection reasons for the advertiser, edit and resubmit."""

import uuid
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from ads import media_client, services
from ads.models import AdCreative, AdSet

pytestmark = pytest.mark.django_db


def _acct() -> str:
    return str(uuid.uuid4())


class _FakeMedia:
    def __init__(self):
        self.assets: dict = {}

    def add(self, owner, *, kind="image", status="ready") -> str:
        media_id = str(uuid.uuid4())
        self.assets[media_id] = media_client.MediaInfo(media_id, str(owner), kind, status)
        return media_id

    def lookup(self, media_ids):
        return {m: self.assets[m] for m in map(str, media_ids) if m in self.assets}


@pytest.fixture
def media(monkeypatch):
    fake = _FakeMedia()
    monkeypatch.setattr(media_client, "lookup", fake.lookup)
    return fake


def _creative(owner, *, placement="feed", **creative):
    campaign = services.create_campaign(owner, {"name": "C", "budget": "50"})
    ad_set = services.create_ad_set(owner, str(campaign.id), {"placement": placement})
    return campaign, services.create_creative(
        owner, str(ad_set.id), {"headline": "Tara", **creative}
    )


# ---- campaign objective and schedule ------------------------------------------


def test_campaign_keeps_its_objective_and_schedule(client_for):
    start = timezone.now() + timedelta(days=1)
    end = start + timedelta(days=7)
    resp = client_for(_acct()).post(
        reverse("ads:campaigns"),
        {
            "name": "Launch",
            "budget": "20",
            "objective": "traffic",
            "schedule_start": start.isoformat(),
            "schedule_end": end.isoformat(),
        },
        format="json",
    )
    assert resp.status_code == 201
    body = resp.json()["data"]
    assert body["objective"] == "traffic"
    assert body["schedule_start"] and body["schedule_end"]


def test_unknown_objective_and_inverted_schedule_are_refused(client_for):
    url = reverse("ads:campaigns")
    client = client_for(_acct())
    bad = {"name": "x", "budget": "1", "objective": "conversions"}
    assert client.post(url, bad, format="json").status_code == 400
    now = timezone.now()
    inverted = {
        "name": "x",
        "budget": "1",
        "schedule_start": now.isoformat(),
        "schedule_end": (now - timedelta(hours=1)).isoformat(),
    }
    resp = client.post(url, inverted, format="json")
    assert resp.status_code == 400
    assert resp.json()["error"]["details"][0]["field"] == "schedule_end"


def test_a_campaign_outside_its_schedule_is_not_served():
    owner = _acct()
    campaign, _ = _creative(owner)
    campaign.schedule_start = timezone.now() + timedelta(days=1)
    campaign.save(update_fields=["schedule_start"])
    assert services.pick_for_viewer(_acct(), "feed") is None


# ---- placements and the marketplace slot ----------------------------------------


def test_new_ad_sets_take_only_served_placements(client_for):
    owner = _acct()
    campaign, _ = _creative(owner)
    url = reverse("ads:ad-sets", args=[campaign.id])
    client = client_for(owner)
    assert client.post(url, {"placement": "search"}, format="json").status_code == 400
    resp = client.post(url, {"placement": "marketplace", "frequency_cap": 3}, format="json")
    assert resp.status_code == 201
    assert resp.json()["data"]["frequency_cap"] == 3


def test_marketplace_slot_serves_marketplace_ads_with_a_bound_token(client_for):
    _creative(_acct(), placement="feed", headline="In the feed")
    _creative(_acct(), placement="marketplace", headline="In the market")
    viewer = _acct()
    resp = client_for(viewer).get(reverse("ads:slot"), {"placement": "marketplace"})
    assert resp.status_code == 200
    slot = resp.json()["data"]["sponsored"]
    assert slot["headline"] == "In the market" and slot["placement"] == "marketplace"
    # The token is the viewer's: someone else cannot spend it.
    event = {"kind": "click", "creative_id": slot["creative_id"], "token": slot["token"]}
    stolen = client_for(_acct()).post(
        reverse("ads:events"), event, format="json", HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4())
    )
    assert stolen.status_code == 403
    mine = client_for(viewer).post(
        reverse("ads:events"), event, format="json", HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4())
    )
    assert mine.status_code == 202


def test_slot_is_empty_when_serving_is_off_and_refuses_other_placements(client_for, settings):
    _creative(_acct(), placement="marketplace")
    client = client_for(_acct())
    url = reverse("ads:slot")
    assert client.get(url, {"placement": "feed"}).status_code == 400
    assert client.get(url, {"placement": "search"}).status_code == 400
    settings.ADS_SERVING_ENABLED = False
    assert client.get(url, {"placement": "marketplace"}).json()["data"]["sponsored"] is None


def test_slot_needs_a_signed_in_viewer():
    from rest_framework.test import APIClient

    resp = APIClient().get(reverse("ads:slot"), {"placement": "marketplace"})
    assert resp.status_code == 401


# ---- review notes for the advertiser -------------------------------------------


def test_rejection_needs_a_reason_that_the_owner_then_sees(client_for, settings):
    settings.ADS_AUTO_APPROVE = False
    owner = _acct()
    campaign, creative = _creative(owner)
    reviewer = client_for(_acct(), roles=["ad_reviewer"])
    url = reverse("ads:review", args=[creative.id])
    blank = reviewer.post(url, {"decision": "rejected", "notes": "  "}, format="json")
    assert blank.status_code == 400
    assert blank.json()["error"]["details"][0]["field"] == "notes"
    ok = reviewer.post(url, {"decision": "rejected", "notes": "Text in the image"}, format="json")
    assert ok.status_code == 200

    rows = client_for(owner).get(reverse("ads:ad-sets", args=[campaign.id])).json()["data"]
    seen = rows[0]["creatives"][0]
    assert (seen["review_status"], seen["review_notes"]) == ("rejected", "Text in the image")
    # Nobody else can read the campaign, so nobody else reads the reason.
    other = client_for(_acct()).get(reverse("ads:ad-sets", args=[campaign.id]))
    assert other.status_code == 404


def test_approval_needs_no_reason_and_shows_none(client_for, settings):
    settings.ADS_AUTO_APPROVE = False
    owner = _acct()
    campaign, creative = _creative(owner)
    reviewer = client_for(_acct(), roles=["ad_reviewer"])
    resp = reviewer.post(
        reverse("ads:review", args=[creative.id]), {"decision": "approved"}, format="json"
    )
    assert resp.status_code == 200
    rows = client_for(owner).get(reverse("ads:ad-sets", args=[campaign.id])).json()["data"]
    assert rows[0]["creatives"][0]["review_notes"] is None


# ---- edit and resubmit ------------------------------------------------------------


def test_rejected_ad_is_edited_and_goes_back_to_review(client_for, settings, media):
    settings.ADS_AUTO_APPROVE = False
    owner = _acct()
    _, creative = _creative(owner)
    services.review_creative(_acct(), str(creative.id), "rejected", "Blurry")
    image = media.add(owner)
    url = reverse("ads:creative-detail", args=[creative.id])
    resp = client_for(owner).patch(url, {"headline": "Sharper", "media_id": image}, format="json")
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert (body["headline"], body["media_id"], body["review_status"]) == (
        "Sharper",
        image,
        "pending",
    )
    reviewer = client_for(_acct(), roles=["ad_reviewer"])
    queue = reviewer.get(reverse("ads:review-queue")).json()["data"]
    assert [r["id"] for r in queue] == [str(creative.id)]


def test_only_the_owner_edits_and_never_an_approved_ad(client_for, media):
    owner = _acct()
    _, creative = _creative(owner)  # auto-approved
    url = reverse("ads:creative-detail", args=[creative.id])
    assert client_for(_acct()).patch(url, {"headline": "x"}, format="json").status_code == 404
    assert client_for(owner).patch(url, {"headline": "x"}, format="json").status_code == 409
    AdCreative.objects.filter(id=creative.id).update(review_status=AdCreative.Review.REJECTED)
    foreign = media.add(_acct())
    resp = client_for(owner).patch(url, {"media_id": foreign}, format="json")
    assert resp.status_code == 400
    assert resp.json()["error"]["details"][0]["code"] == "media_not_owned"
    creative.refresh_from_db()
    assert creative.media_id is None


def test_old_search_ad_sets_still_load(client_for):
    owner = _acct()
    campaign, _ = _creative(owner)
    AdSet.objects.create(campaign=campaign, placement=AdSet.Placement.SEARCH)
    rows = client_for(owner).get(reverse("ads:ad-sets", args=[campaign.id])).json()["data"]
    assert {r["placement"] for r in rows} == {"feed", "search"}
