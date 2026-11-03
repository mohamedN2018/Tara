"""Favorites, compare, view counter, inquiries, availability, sellers and reviews."""

import uuid

import pytest
from django.urls import reverse

from marketplace import services, view_counter
from marketplace.handlers import on_moderation_actioned
from marketplace.models import (
    BlockedPair,
    Listing,
    ListingInquiry,
    OutboxEvent,
    ProcessedEvent,
    SellerProfile,
    SellerReview,
)
from tara_events.envelope import EventEnvelope

pytestmark = pytest.mark.django_db


def _acct() -> str:
    return str(uuid.uuid4())


def _live(seller, category, **over) -> Listing:
    data = {"category_id": str(category.id), "title": over.pop("title", "Item"), "price": "10"}
    data.update(over)
    listing = services.create_listing(seller, data)
    services.publish_listing(seller, str(listing.id))
    listing.refresh_from_db()
    return listing


def _events(event_type: str) -> list[dict]:
    return [e.payload["payload"] for e in OutboxEvent.objects.filter(event_type=event_type)]


# ---- availability -----------------------------------------------------------


def test_availability_states_and_events(client_for, category):
    seller = _acct()
    listing = _live(seller, category)
    c = client_for(seller)
    url = reverse("marketplace:transition", args=[listing.id])
    assert c.post(url, {"action": "reserve"}, format="json").json()["data"]["availability"] == (
        "reserved"
    )
    assert c.post(url, {"action": "mark_sold"}, format="json").json()["data"]["availability"] == (
        "sold"
    )
    moves = [(e["from"], e["to"]) for e in _events("listing.availability.changed")]
    assert moves == [(None, "available"), ("available", "reserved"), ("reserved", "sold")]


def test_reserved_and_sold_listings_stay_openable_but_drafts_do_not(client_for, category):
    seller, buyer = _acct(), _acct()
    sold = _live(seller, category)
    services.transition(seller, str(sold.id), "mark_sold")
    draft = services.create_listing(seller, {"category_id": str(category.id), "title": "d"})
    c = client_for(buyer)
    assert c.get(reverse("marketplace:listing-detail", args=[sold.id])).status_code == 200
    assert c.get(reverse("marketplace:listing-detail", args=[draft.id])).status_code == 404


# ---- favorites --------------------------------------------------------------


def test_saved_list_filters_hidden_and_orders_by_save_time(client_for, category):
    seller, blocker, buyer = _acct(), _acct(), _acct()
    first = _live(seller, category, title="first")
    second = _live(seller, category, title="second")
    removed = _live(seller, category, title="removed")
    blocked = _live(blocker, category, title="blocked")
    c = client_for(buyer)
    for listing in (second, first, removed, blocked):  # save order != creation order
        assert c.post(reverse("marketplace:save", args=[listing.id])).status_code == 200
    services.apply_moderation(str(removed.id), "remove")
    BlockedPair.objects.create(blocker_id=blocker, blocked_id=buyer)

    body = c.get(reverse("marketplace:saved")).json()
    assert [row["id"] for row in body["data"]] == [str(first.id), str(second.id)]
    assert all(row["is_saved"] for row in body["data"])


def test_saved_list_pages_by_keyset(client_for, category):
    seller, buyer = _acct(), _acct()
    c = client_for(buyer)
    made = []
    for i in range(5):
        listing = _live(seller, category, title=f"s{i}")
        c.post(reverse("marketplace:save", args=[listing.id]))
        made.append(str(listing.id))
    seen, cursor = [], None
    while True:
        params = {"limit": 2, **({"cursor": cursor} if cursor else {})}
        body = c.get(reverse("marketplace:saved"), params).json()
        seen += [row["id"] for row in body["data"]]
        cursor = body["page"]["next_cursor"]
        if not body["page"]["has_more"]:
            break
    assert seen == list(reversed(made))


def test_is_saved_on_detail_and_search(client_for, category):
    seller, buyer = _acct(), _acct()
    listing = _live(seller, category)
    c = client_for(buyer)
    detail = reverse("marketplace:listing-detail", args=[listing.id])
    assert c.get(detail).json()["data"]["viewer"]["is_saved"] is False
    c.post(reverse("marketplace:save", args=[listing.id]))
    assert c.get(detail).json()["data"]["viewer"]["is_saved"] is True
    assert c.get(reverse("marketplace:listings")).json()["data"][0]["is_saved"] is True
    # Another viewer's flag is their own.
    assert client_for(_acct()).get(detail).json()["data"]["is_saved"] is False


def test_saving_a_hidden_listing_is_404(client_for, category):
    seller = _acct()
    draft = services.create_listing(seller, {"category_id": str(category.id), "title": "d"})
    assert client_for(_acct()).post(reverse("marketplace:save", args=[draft.id])).status_code == 404


def test_unsave_never_goes_negative(client_for, category):
    seller, buyer = _acct(), _acct()
    listing = _live(seller, category)
    c = client_for(buyer)
    c.post(reverse("marketplace:save", args=[listing.id]))
    c.delete(reverse("marketplace:save", args=[listing.id]))
    c.delete(reverse("marketplace:save", args=[listing.id]))
    listing.refresh_from_db()
    assert listing.save_count == 0


# ---- compare ----------------------------------------------------------------


def test_compare_returns_visible_listings_in_order(client_for, category):
    seller = _acct()
    a, b = _live(seller, category, title="a"), _live(seller, category, title="b")
    draft = services.create_listing(seller, {"category_id": str(category.id), "title": "d"})
    ids = ",".join(str(x) for x in (b.id, draft.id, uuid.uuid4(), a.id))
    resp = client_for(_acct()).get(reverse("marketplace:compare"), {"ids": ids})
    assert resp.status_code == 200
    assert [row["id"] for row in resp.json()["data"]] == [str(b.id), str(a.id)]


@pytest.mark.parametrize(
    "ids",
    ["", "not-a-uuid", ",".join(str(uuid.uuid4()) for _ in range(5))],
)
def test_compare_validates_ids(client_for, ids):
    resp = client_for(_acct()).get(reverse("marketplace:compare"), {"ids": ids})
    assert resp.status_code == 400


# ---- view counter -----------------------------------------------------------


def test_views_are_buffered_with_a_cooldown_and_flushed_once(client_for, category):
    seller, a, b = _acct(), _acct(), _acct()
    listing = _live(seller, category)
    url = reverse("marketplace:view", args=[listing.id])
    assert client_for(a).post(url).json()["data"]["counted"] is True
    assert client_for(a).post(url).json()["data"]["counted"] is False  # cooldown
    assert client_for(b).post(url).json()["data"]["counted"] is True
    assert client_for(seller).post(url).json()["data"]["counted"] is False  # own views

    listing.refresh_from_db()
    assert listing.view_count == 0  # no DB write per hit
    assert view_counter.pending_views(str(listing.id)) == 2

    assert view_counter.flush() == 2
    assert view_counter.flush() == 0
    listing.refresh_from_db()
    assert listing.view_count == 2


def test_a_batch_left_by_a_crash_is_applied_exactly_once(category):
    listing = _live(_acct(), category)
    view_counter.record_view(str(listing.id), _acct())
    r = view_counter._redis()
    # Crash after claiming the buffer, before applying it.
    orphan = f"{view_counter._batch_prefix()}{uuid.uuid4()}"
    r.rename(view_counter._buffer_key(), orphan)
    assert view_counter.flush() == 1
    listing.refresh_from_db()
    assert listing.view_count == 1

    # Crash after the DB commit, before the key was deleted: not counted again.
    view_counter.record_view(str(listing.id), _acct())
    batch_id = uuid.uuid4()
    applied = f"{view_counter._batch_prefix()}{batch_id}"
    r.rename(view_counter._buffer_key(), applied)
    ProcessedEvent.objects.create(event_id=batch_id, consumer=view_counter.FLUSH_CONSUMER)
    assert view_counter.flush() == 0
    assert not r.exists(applied)
    listing.refresh_from_db()
    assert listing.view_count == 1


def test_viewing_a_hidden_listing_is_404(client_for, category):
    seller = _acct()
    draft = services.create_listing(seller, {"category_id": str(category.id), "title": "d"})
    assert client_for(_acct()).post(reverse("marketplace:view", args=[draft.id])).status_code == 404


def test_redis_down_never_breaks_the_request(client_for, category, monkeypatch):
    import redis

    listing = _live(_acct(), category)

    class Down:
        def set(self, *a, **k):
            raise redis.ConnectionError("down")

    monkeypatch.setattr(view_counter, "_redis", lambda: Down())
    resp = client_for(_acct()).post(reverse("marketplace:view", args=[listing.id]))
    assert resp.status_code == 202
    assert resp.json()["data"]["counted"] is False


# ---- inquiries --------------------------------------------------------------


def test_inquiry_is_recorded_once_per_buyer(client_for, category):
    seller, buyer = _acct(), _acct()
    listing = _live(seller, category)
    url = reverse("marketplace:inquiries", args=[listing.id])
    c = client_for(buyer)
    first = c.post(url, {"message": "Is it available?"}, format="json")
    assert first.status_code == 201
    assert first.json()["data"]["seller_id"] == seller
    assert c.post(url, {"message": "again"}, format="json").status_code == 201
    inquiry = ListingInquiry.objects.get()
    assert (inquiry.first_message, inquiry.message_count) == ("Is it available?", 2)
    listing.refresh_from_db()
    assert listing.inquiry_count == 1
    assert len(_events("marketplace.inquiry.created")) == 1
    detail = c.get(reverse("marketplace:listing-detail", args=[listing.id])).json()["data"]
    assert detail["viewer"]["has_inquired"] is True
    assert detail["viewer"]["can_review"] is True


def test_inquiry_rules(client_for, category):
    seller, buyer = _acct(), _acct()
    listing = _live(seller, category)
    url = reverse("marketplace:inquiries", args=[listing.id])
    assert client_for(seller).post(url, {}, format="json").status_code == 400  # own listing
    assert client_for(buyer).post(url, {"message": "x" * 1001}, format="json").status_code == 400
    services.transition(seller, str(listing.id), "mark_sold")
    assert client_for(buyer).post(url, {}, format="json").status_code == 409
    BlockedPair.objects.create(blocker_id=seller, blocked_id=buyer)
    assert client_for(buyer).post(url, {}, format="json").status_code == 404


def test_legacy_contact_also_records_the_inquiry(client_for, category):
    seller, buyer = _acct(), _acct()
    listing = _live(seller, category)
    resp = client_for(buyer).post(reverse("marketplace:contact", args=[listing.id]))
    assert resp.status_code == 202
    assert ListingInquiry.objects.filter(listing=listing, buyer_id=buyer).exists()
    assert _events("marketplace.contact.requested")[0]["inquiry_id"]


# ---- sellers ----------------------------------------------------------------


def test_seller_summary(client_for, category):
    seller = _acct()
    _live(seller, category)
    sold = _live(seller, category)
    services.transition(seller, str(sold.id), "mark_sold")
    services.create_listing(seller, {"category_id": str(category.id), "title": "draft"})
    resp = client_for(_acct()).get(reverse("marketplace:seller", args=[seller]))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["active_listings_count"] == 1
    assert data["sold_listings_count"] == 1
    assert data["rating_avg"] is None and data["rating_count"] == 0
    assert data["response_hint"] == "active_today"
    assert data["member_since"]


def test_seller_summary_hidden_cases_are_404(client_for, category):
    seller, viewer = _acct(), _acct()
    services.create_listing(seller, {"category_id": str(category.id), "title": "only a draft"})
    url = reverse("marketplace:seller", args=[seller])
    assert client_for(viewer).get(url).status_code == 404  # nothing public
    assert client_for(seller).get(url).status_code == 200  # but the seller sees theirs
    assert client_for(viewer).get(reverse("marketplace:seller", args=[_acct()])).status_code == 404
    _live(seller, category)
    BlockedPair.objects.create(blocker_id=viewer, blocked_id=seller)
    assert client_for(viewer).get(url).status_code == 404
    assert (
        client_for(viewer).get(reverse("marketplace:seller-reviews", args=[seller])).status_code
        == 404
    )


# ---- reviews ----------------------------------------------------------------


def _review(client, listing, rating=5, body="Great"):
    return client.post(
        reverse("marketplace:listing-reviews", args=[listing.id]),
        {"rating": rating, "body": body},
        format="json",
    )


def test_only_buyers_who_inquired_can_review_once(client_for, category):
    seller, buyer, stranger = _acct(), _acct(), _acct()
    listing = _live(seller, category)
    resp = _review(client_for(stranger), listing)
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "review_not_eligible"

    services.record_inquiry(buyer, str(listing.id))
    c = client_for(buyer)
    assert _review(c, listing, rating=4).status_code == 201
    dup = _review(c, listing, rating=1)
    assert dup.status_code == 409
    assert dup.json()["error"]["code"] == "already_reviewed"
    assert SellerReview.objects.count() == 1

    profile = SellerProfile.objects.get(account_id=seller)
    assert (profile.rating_avg, profile.rating_count) == (4.0, 1)
    assert _events("marketplace.review.created")[0]["rating"] == 4
    detail = c.get(reverse("marketplace:listing-detail", args=[listing.id])).json()["data"]
    assert detail["viewer"]["can_review"] is False and detail["viewer"]["has_reviewed"] is True


@pytest.mark.parametrize("rating", [0, 6, "x"])
def test_review_rating_is_validated(client_for, category, rating):
    seller, buyer = _acct(), _acct()
    listing = _live(seller, category)
    services.record_inquiry(buyer, str(listing.id))
    assert _review(client_for(buyer), listing, rating=rating).status_code == 400


def test_seller_cannot_review_own_listing_and_hidden_is_404(client_for, category):
    seller = _acct()
    listing = _live(seller, category)
    assert _review(client_for(seller), listing).status_code == 400
    draft = services.create_listing(seller, {"category_id": str(category.id), "title": "d"})
    assert _review(client_for(_acct()), draft).status_code == 404


def test_reviews_list_and_aggregate(client_for, category):
    seller = _acct()
    listing = _live(seller, category)
    buyers = [_acct() for _ in range(3)]
    for buyer, rating in zip(buyers, (5, 4, 3), strict=True):
        services.record_inquiry(buyer, str(listing.id))
        services.create_review(buyer, str(listing.id), rating, "ok")
    viewer = _acct()
    BlockedPair.objects.create(blocker_id=viewer, blocked_id=buyers[0])  # hides their review
    body = client_for(viewer).get(reverse("marketplace:seller-reviews", args=[seller])).json()
    assert [r["rating"] for r in body["data"]] == [3, 4]
    assert body["data"][0]["listing_title"] == "Item"
    summary = client_for(viewer).get(reverse("marketplace:seller", args=[seller])).json()["data"]
    assert summary["rating_avg"] == 4.0 and summary["rating_count"] == 3


def test_review_report_and_moderation_removal(client_for, category):
    seller, buyer, reporter = _acct(), _acct(), _acct()
    listing = _live(seller, category)
    services.record_inquiry(buyer, str(listing.id))
    review = services.create_review(buyer, str(listing.id), 1, "scam")
    url = reverse("marketplace:review-report", args=[review.id])

    assert client_for(buyer).post(url, {"reason": "x"}, format="json").status_code == 400  # own
    assert client_for(reporter).post(url, {}, format="json").status_code == 400  # no reason
    assert client_for(reporter).post(url, {"reason": "abuse"}, format="json").status_code == 202
    assert client_for(reporter).post(url, {"reason": "abuse"}, format="json").status_code == 202
    reported = _events("marketplace.review.reported")
    assert len(reported) == 1  # deduped per reporter
    assert reported[0]["owner_id"] == buyer and reported[0]["reporter"] == reporter

    missing = reverse("marketplace:review-report", args=[uuid.uuid4()])
    assert client_for(reporter).post(missing, {"reason": "x"}, format="json").status_code == 404

    on_moderation_actioned(
        EventEnvelope(
            event_type="moderation.actioned",
            subject_id=str(review.id),
            producer="moderation-service",
            payload={
                "target_type": "listing_review",
                "target_id": str(review.id),
                "action": "remove",
            },
        )
    )
    review.refresh_from_db()
    assert review.status == SellerReview.Status.REMOVED
    assert SellerProfile.objects.get(account_id=seller).rating_count == 0
    listing_reviews = client_for(reporter).get(reverse("marketplace:seller-reviews", args=[seller]))
    assert listing_reviews.json()["data"] == []
    # A removed review cannot be reported again.
    assert client_for(_acct()).post(url, {"reason": "x"}, format="json").status_code == 404
