"""Ads: campaign setup, serving + frequency cap, impression/click + budget, report."""

import time
import uuid

import jwt
import pytest
from django.conf import settings
from django.core.cache import cache
from django.urls import reverse

from ads import services
from ads.models import AdImpressionEvent, Campaign, OutboxEvent

pytestmark = pytest.mark.django_db


def _acct() -> str:
    return str(uuid.uuid4())


def _make_active_creative(owner, *, cpc="0.50", cpm="2.00", budget="100.00", cap=2):
    campaign = services.create_campaign(owner, {"name": "C", "budget": budget})
    ad_set = services.create_ad_set(
        owner, str(campaign.id), {"placement": "feed", "cpc": cpc, "cpm": cpm, "frequency_cap": cap}
    )
    creative = services.create_creative(
        owner, str(ad_set.id), {"headline": "Buy Tara"}
    )  # auto-approved
    return campaign, creative


# ---- setup + serving --------------------------------------------------------


def test_create_campaign_and_serve(client_for):
    owner = _acct()
    resp = client_for(owner).post(
        reverse("ads:campaigns"), {"name": "Launch", "budget": "50.00"}, format="json"
    )
    assert resp.status_code == 201
    _make_active_creative(owner)
    slot = services.pick_for_viewer(_acct(), "feed")
    assert slot and slot["sponsored"] is True and slot["headline"] == "Buy Tara"


def test_pending_creative_not_served(client_for, settings):
    settings.ADS_AUTO_APPROVE = False
    owner = _acct()
    _make_active_creative(owner)  # stays pending
    assert services.pick_for_viewer(_acct(), "feed") is None


def test_frequency_cap(client_for):
    owner = _acct()
    _campaign, creative = _make_active_creative(owner, cap=2)
    viewer = _acct()
    # Record 2 impressions -> capped.
    services.record_event("impression", str(creative.id), viewer)
    services.record_event("impression", str(creative.id), viewer)
    assert services.pick_for_viewer(viewer, "feed") is None
    # A different viewer is unaffected.
    assert services.pick_for_viewer(_acct(), "feed") is not None


def test_impression_and_click_debit_budget_and_emit():
    owner = _acct()
    campaign, creative = _make_active_creative(owner, cpc="1.00", cpm="2.00", budget="100.00")
    services.record_event("impression", str(creative.id), _acct())  # +0.002
    services.record_event("click", str(creative.id), _acct())  # +1.00
    campaign.refresh_from_db()
    assert float(campaign.spent) == pytest.approx(1.002)
    assert OutboxEvent.objects.filter(event_type="ad.impression.recorded").exists()
    assert OutboxEvent.objects.filter(event_type="ad.click.recorded").exists()
    # viewer id is never stored raw — only a coarse bucket.
    assert len(AdImpressionEvent.objects.first().viewer_bucket) == 2


def test_budget_exhaustion_completes_campaign():
    owner = _acct()
    campaign, creative = _make_active_creative(owner, cpc="60.00", cpm="0.00", budget="100.00")
    services.record_event("click", str(creative.id), _acct())  # 60
    services.record_event("click", str(creative.id), _acct())  # 120 -> over budget
    campaign.refresh_from_db()
    assert campaign.status == Campaign.Status.COMPLETED
    assert services.pick_for_viewer(_acct(), "feed") is None  # no longer eligible


# ---- review RBAC ------------------------------------------------------------


def test_review_requires_reviewer_role(client_for, settings):
    settings.ADS_AUTO_APPROVE = False  # build a pending creative
    cache.clear()
    _campaign, creative = _make_active_creative(_acct())

    # Non-reviewer -> 403.
    assert (
        client_for(_acct())
        .post(reverse("ads:review", args=[creative.id]), {"decision": "approved"}, format="json")
        .status_code
        == 403
    )
    # Reviewer -> 200 + approved.
    ok = client_for(_acct(), roles=["ad_reviewer"]).post(
        reverse("ads:review", args=[creative.id]), {"decision": "approved"}, format="json"
    )
    assert ok.status_code == 200
    assert ok.json()["data"]["review_status"] == "approved"


def test_events_endpoint_dedupes(client_for):
    owner = _acct()
    _campaign, creative = _make_active_creative(owner)
    client = client_for(_acct())
    headers = {"HTTP_IDEMPOTENCY_KEY": "evt-1"}
    body = {"kind": "impression", "creative_id": str(creative.id)}
    assert client.post(reverse("ads:events"), body, format="json", **headers).status_code == 202
    assert client.post(reverse("ads:events"), body, format="json", **headers).status_code == 202
    # Same idempotency key -> recorded once.
    assert AdImpressionEvent.objects.filter(creative=creative).count() == 1


# ---- internal feed-slot -----------------------------------------------------


def test_internal_feed_slot_requires_token():
    from rest_framework.test import APIClient

    owner = _acct()
    _make_active_creative(owner)
    client = APIClient()
    url = reverse("ads-feed-slot")
    assert client.get(url, {"viewer": _acct()}).status_code == 401

    now = int(time.time())
    token = jwt.encode(
        {"iss": "feed", "aud": "ads-internal", "iat": now, "exp": now + 30},
        settings.TARA_INTERNAL_JWT_SECRET,
        algorithm="HS256",
    )
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    resp = client.get(url, {"viewer": _acct()})
    assert resp.status_code == 200
    assert resp.json()["data"]["sponsored"]["sponsored"] is True
