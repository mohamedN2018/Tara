"""Ads: campaign setup, serving + frequency cap, impression/click + budget, report."""

import time
import uuid

import jwt
import pytest
from django.conf import settings
from django.core.cache import cache
from django.urls import reverse

from ads import serve_tokens, services
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
    viewer = _acct()
    client = client_for(viewer)
    headers = {"HTTP_IDEMPOTENCY_KEY": "evt-1"}
    slot = services.pick_for_viewer(viewer, "feed")
    body = {"kind": "impression", "creative_id": str(creative.id), "token": slot["token"]}
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


# ---- serve tokens ------------------------------------------------------------


def _event(client, creative, token, kind="impression", key=None):
    return client.post(
        reverse("ads:events"),
        {"kind": kind, "creative_id": str(creative.id), "token": token},
        format="json",
        HTTP_IDEMPOTENCY_KEY=key or uuid.uuid4().hex,
    )


def _spent(campaign):
    campaign.refresh_from_db()
    return campaign.spent


def test_event_without_a_token_spends_nothing(client_for):
    campaign, creative = _make_active_creative(_acct())
    resp = client_for(_acct()).post(
        reverse("ads:events"),
        {"kind": "click", "creative_id": str(creative.id)},
        format="json",
        HTTP_IDEMPOTENCY_KEY="k",
    )
    assert resp.status_code == 400
    assert _spent(campaign) == 0


def test_forged_and_foreign_tokens_are_refused(client_for):
    campaign, creative = _make_active_creative(_acct())
    other_campaign, other_creative = _make_active_creative(_acct())
    victim, attacker = _acct(), _acct()
    client = client_for(attacker)

    assert _event(client, creative, "garbage", "click").status_code == 403
    # A token served to someone else.
    theirs = services.pick_for_viewer(victim, "feed")["token"]
    assert _event(client, creative, theirs, "click").status_code == 403
    # A token for another creative.
    mine = next(
        s["token"]
        for s in [services.pick_for_viewer(attacker, "feed")]
        if s["creative_id"] != str(other_creative.id)
    )
    assert _event(client, other_creative, mine, "click").status_code == 403
    # Signed with the internal secret itself, not the derived key.
    now = int(time.time())
    forged = jwt.encode(
        {
            "aud": "ad-serve",
            "sub": attacker,
            "cid": str(creative.id),
            "jti": "x",
            "iat": now,
            "exp": now + 60,
        },
        settings.TARA_INTERNAL_JWT_SECRET,
        algorithm="HS256",
    )
    assert _event(client, creative, forged, "click").status_code == 403
    assert _spent(campaign) == 0 and _spent(other_campaign) == 0


def test_expired_token_is_refused(client_for, monkeypatch):
    campaign, creative = _make_active_creative(_acct())
    viewer = _acct()
    monkeypatch.setattr(serve_tokens, "TTL_SECONDS", -60)
    token = serve_tokens.issue(viewer, creative.id, "feed")
    assert _event(client_for(viewer), creative, token, "click").status_code == 403
    assert _spent(campaign) == 0


def test_one_token_pays_once_per_kind(client_for):
    campaign, creative = _make_active_creative(_acct())
    viewer = _acct()
    client = client_for(viewer)
    token = services.pick_for_viewer(viewer, "feed")["token"]

    assert _event(client, creative, token, "click").status_code == 202
    spent = _spent(campaign)
    assert spent > 0
    assert _event(client, creative, token, "click").status_code == 202  # replay
    assert _spent(campaign) == spent
    assert _event(client, creative, token, "impression").status_code == 202  # own kind
    assert AdImpressionEvent.objects.filter(creative=creative).count() == 1


def test_replay_after_the_viewer_window_still_pays_nothing(client_for):
    campaign, creative = _make_active_creative(_acct())
    viewer = _acct()
    client = client_for(viewer)
    token = services.pick_for_viewer(viewer, "feed")["token"]
    assert _event(client, creative, token, "click").status_code == 202
    spent = _spent(campaign)
    cache.delete(f"ad-event:click:{creative.id}:{viewer}")
    assert _event(client, creative, token, "click").status_code == 202
    assert _spent(campaign) == spent


# ---- dashboard + review -------------------------------------------------------


def test_owner_lists_ad_sets_with_creatives_and_outsider_cannot(client_for):
    owner = _acct()
    campaign, creative = _make_active_creative(owner)
    url = reverse("ads:ad-sets", args=[campaign.id])
    data = client_for(owner).get(url).json()["data"]
    assert data[0]["creatives"][0]["id"] == str(creative.id)
    assert client_for(_acct()).get(url).status_code == 404


def test_owner_pauses_and_resumes_and_paused_ads_stop(client_for):
    owner = _acct()
    campaign, _ = _make_active_creative(owner)
    url = reverse("ads:campaign-detail", args=[campaign.id])
    client = client_for(owner)
    assert client.patch(url, {"status": "paused"}, format="json").status_code == 200
    assert services.pick_for_viewer(_acct(), "feed") is None
    assert client.patch(url, {"status": "active"}, format="json").status_code == 200
    assert services.pick_for_viewer(_acct(), "feed") is not None
    assert client_for(_acct()).patch(url, {"status": "paused"}, format="json").status_code == 404
    assert client.patch(url, {"status": "completed"}, format="json").status_code == 400

    Campaign.objects.filter(id=campaign.id).update(status="completed")
    assert client.patch(url, {"status": "active"}, format="json").status_code == 409


def test_report_lists_creative_stats_for_the_owner_only(client_for):
    owner = _acct()
    campaign, creative = _make_active_creative(owner)
    services.record_event("impression", str(creative.id), _acct())
    services.record_event("impression", str(creative.id), _acct())
    services.record_event("click", str(creative.id), _acct())
    url = reverse("ads:campaign-report", args=[campaign.id])
    data = client_for(owner).get(url).json()["data"]
    assert data["creatives"][0]["impressions"] == 2
    assert data["creatives"][0]["clicks"] == 1
    assert client_for(_acct()).get(url).status_code == 404


def test_review_queue_is_for_reviewers_and_empties_on_decision(client_for, settings):
    settings.ADS_AUTO_APPROVE = False
    owner = _acct()
    _, creative = _make_active_creative(owner)
    url = reverse("ads:review-queue")
    assert client_for(owner).get(url).status_code == 403

    reviewer = client_for(_acct(), roles=["ad_reviewer"])
    rows = reviewer.get(url).json()["data"]
    assert [r["id"] for r in rows] == [str(creative.id)]
    assert rows[0]["campaign_name"] == "C"

    reviewer.post(
        reverse("ads:review", args=[creative.id]), {"decision": "rejected"}, format="json"
    )
    assert reviewer.get(url).json()["data"] == []
    assert services.pick_for_viewer(_acct(), "feed") is None


def test_creative_link_must_be_https(client_for):
    owner = _acct()
    campaign, _ = _make_active_creative(owner)
    ad_set = campaign.ad_sets.first()
    url = reverse("ads:creatives", args=[ad_set.id])
    client = client_for(owner)
    bad = {"headline": "x", "link_url": "javascript:alert(1)"}
    assert client.post(url, bad, format="json").status_code == 400
    bad = {"headline": "x", "link_url": "http://a.example/"}
    assert client.post(url, bad, format="json").status_code == 400
    good = {"headline": "x", "link_url": "https://a.example/"}
    assert client.post(url, good, format="json").status_code == 201
