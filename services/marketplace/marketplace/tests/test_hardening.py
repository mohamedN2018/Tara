"""Review-pass regressions: tampered cursors, price switches, moderation and rating races."""

import base64
import json
import uuid
from datetime import timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from marketplace import services
from marketplace.handlers import on_moderation_actioned
from marketplace.models import (
    Listing,
    ListingInquiry,
    OutboxEvent,
    SellerProfile,
    SellerReview,
)
from tara_events.envelope import EventEnvelope

pytestmark = pytest.mark.django_db


def _acct() -> str:
    return str(uuid.uuid4())


def _live(seller, category, **over) -> Listing:
    data = {"category_id": str(category.id), "title": over.pop("title", "Item"), **over}
    listing = services.create_listing(seller, data)
    services.publish_listing(seller, str(listing.id))
    listing.refresh_from_db()
    return listing


def _cursor(sort: str, key, row_id=None) -> str:
    raw = json.dumps({"s": sort, "k": key, "i": str(row_id or uuid.uuid4())})
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


@pytest.mark.parametrize(
    "sort,key",
    [
        ("price_asc", "1e999999"),
        ("price_asc", "-1e999999"),
        ("price_desc", "NaN"),
        ("price_desc", "sNaN"),
        ("price_asc", "Infinity"),
        ("price_asc", "1" * 40),
        ("newest", "0001-01-01T00:00:00+05:00"),
        ("newest", "9999-12-31T23:59:59-05:00"),
        ("newest", "2026-01-01T00:00:00"),
        ("newest", 5),
    ],
)
def test_tampered_cursor_keys_are_400_never_500(client_for, category, sort, key):
    _live(_acct(), category, price="10")
    resp = client_for(_acct()).get(
        reverse("marketplace:listings"), {"sort": sort, "cursor": _cursor(sort, key)}
    )
    assert resp.status_code in (200, 400), resp.content


def test_free_listing_switches_to_negotiable_without_resending_a_price(client_for, category):
    seller = _acct()
    listing = _live(seller, category, price_type="free")
    url = reverse("marketplace:listing-detail", args=[listing.id])
    resp = client_for(seller).patch(url, {"price_type": "negotiable"}, format="json")
    assert resp.status_code == 200, resp.content
    body = resp.json()["data"]
    assert (body["price_type"], body["price"], body["effective_price"]) == (
        "negotiable",
        None,
        None,
    )


def _moderation(target_type: str, target_id: str, action: str) -> None:
    on_moderation_actioned(
        EventEnvelope(
            event_type="moderation.actioned",
            subject_id=str(uuid.uuid4()),
            producer="moderation-service",
            payload={"target_type": target_type, "target_id": target_id, "action": action},
        )
    )


def test_repeated_removal_emits_no_second_status_change(category):
    listing = _live(_acct(), category)
    _moderation("listing", str(listing.id), "remove")
    _moderation("listing", str(listing.id), "remove")
    moves = [
        (e.payload["payload"]["from"], e.payload["payload"]["to"])
        for e in OutboxEvent.objects.filter(event_type="listing.status.changed")
    ]
    assert moves == [("draft", "active"), ("active", "removed")]


def test_rating_refresh_locks_the_seller_profile(category):
    """Concurrent reviews serialise on the profile row, so none is lost from the average."""
    seller, buyer = _acct(), _acct()
    listing = _live(seller, category)
    services.record_inquiry(buyer, str(listing.id))
    with CaptureQueriesContext(connection) as ctx:
        services.create_review(buyer, str(listing.id), 5, "")
    sql = [q["sql"] for q in ctx.captured_queries]
    lock = next(i for i, q in enumerate(sql) if "FOR UPDATE" in q and '"seller_profile"' in q)
    count = next(i for i, q in enumerate(sql) if "AVG(" in q and '"seller_review"' in q)
    assert lock < count  # counted under the lock, not before it
    profile = SellerProfile.objects.get(account_id=seller)
    assert (profile.rating_avg, profile.rating_count) == (5.0, 1)


def test_repeat_reports_by_one_person_reach_moderation_once(client_for, category):
    listing = _live(_acct(), category)
    c = client_for(_acct())
    url = reverse("marketplace:report", args=[listing.id])
    for _ in range(3):
        assert c.post(url, {"reason": "scam"}, format="json").status_code == 202
    assert OutboxEvent.objects.filter(event_type="listing.reported").count() == 1
    other = client_for(_acct()).post(url, {"reason": "scam"}, format="json")
    assert other.status_code == 202
    assert OutboxEvent.objects.filter(event_type="listing.reported").count() == 2


# ---- seller reviews visibility, reject guard ---------------------------------


def test_seller_reviews_follow_the_seller_page_rule(client_for, category):
    seller, buyer, viewer = _acct(), _acct(), _acct()
    listing = _live(seller, category)
    services.record_inquiry(buyer, str(listing.id))
    services.create_review(buyer, str(listing.id), 5, "")
    reviews = reverse("marketplace:seller-reviews", args=[seller])
    page = reverse("marketplace:seller", args=[seller])
    assert client_for(viewer).get(reviews).status_code == 200

    services.transition(seller, str(listing.id), "archive")  # nothing public any more
    for url in (page, reviews):
        assert client_for(viewer).get(url).status_code == 404
        assert client_for(seller).get(url).status_code == 200  # the seller still sees theirs
    unknown = reverse("marketplace:seller-reviews", args=[uuid.uuid4()])
    assert client_for(viewer).get(unknown).status_code == 404


def test_reject_cannot_undo_a_removal(category):
    listing = _live(_acct(), category)
    _moderation("listing", str(listing.id), "remove")
    _moderation("listing", str(listing.id), "reject")
    listing.refresh_from_db()
    assert listing.status == Listing.Status.REMOVED


# ---- review brakes ------------------------------------------------------------


def _review(client, listing):
    return client.post(
        reverse("marketplace:listing-reviews", args=[listing.id]), {"rating": 5}, format="json"
    )


def test_a_fresh_inquiry_cannot_review_yet(client_for, category, settings):
    settings.MARKETPLACE_REVIEW_MIN_INQUIRY_AGE_SECONDS = 3600
    seller, buyer = _acct(), _acct()
    listing = _live(seller, category)
    inquiry = services.record_inquiry(buyer, str(listing.id))
    c = client_for(buyer)
    detail = c.get(reverse("marketplace:listing-detail", args=[listing.id])).json()["data"]
    assert detail["viewer"]["has_inquired"] is True and detail["viewer"]["can_review"] is False
    resp = _review(c, listing)
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "review_not_eligible_yet"

    ListingInquiry.objects.filter(id=inquiry.id).update(
        created_at=timezone.now() - timedelta(hours=2)
    )
    detail = c.get(reverse("marketplace:listing-detail", args=[listing.id])).json()["data"]
    assert detail["viewer"]["can_review"] is True
    assert _review(c, listing).status_code == 201


def test_one_buyer_rates_one_seller_once_per_window(client_for, category):
    seller, buyer = _acct(), _acct()
    first, second = _live(seller, category), _live(seller, category)
    for listing in (first, second):
        services.record_inquiry(buyer, str(listing.id))
    c = client_for(buyer)
    assert _review(c, first).status_code == 201
    resp = _review(c, second)
    assert resp.status_code == 429
    assert resp.json()["error"]["code"] == "review_rate_limited"
    detail = c.get(reverse("marketplace:listing-detail", args=[second.id])).json()["data"]
    assert detail["viewer"]["can_review"] is False

    SellerReview.objects.update(created_at=timezone.now() - timedelta(days=31))
    assert _review(c, second).status_code == 201
    assert SellerProfile.objects.get(account_id=seller).rating_count == 2


def test_review_takes_the_seller_lock_before_checking_the_window(category):
    seller, buyer = _acct(), _acct()
    listing = _live(seller, category)
    services.record_inquiry(buyer, str(listing.id))
    with CaptureQueriesContext(connection) as ctx:
        services.create_review(buyer, str(listing.id), 4, "")
    sql = [q["sql"] for q in ctx.captured_queries]
    lock = next(i for i, q in enumerate(sql) if "FOR UPDATE" in q and '"seller_profile"' in q)
    window = next(i for i, q in enumerate(sql) if '"seller_review"' in q and '"created_at" >=' in q)
    assert lock < window
