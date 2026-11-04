"""The marketplace hub (T6): a seller's shop, editing photos, the Selling
overview, the Buying/Selling inbox and the seller's moderation note."""

import uuid

import pytest
from django.urls import reverse

from marketplace import services
from marketplace.handlers import on_moderation_actioned
from marketplace.models import BlockedPair, Listing, ListingMedia, OutboxEvent
from tara_events.envelope import EventEnvelope

pytestmark = pytest.mark.django_db


def _acct() -> str:
    return str(uuid.uuid4())


def _listing(seller, category, *, publish=True, title="Lamp", media_ids=None) -> Listing:
    listing = services.create_listing(
        seller,
        {
            "category_id": str(category.id),
            "title": title,
            "price": "20.00",
            "currency": "USD",
            "media_ids": media_ids or [],
        },
    )
    if publish:
        listing = services.publish_listing(seller, str(listing.id))
    return listing


def _ids(resp) -> list[str]:
    return [row["id"] for row in resp.json()["data"]]


def _moderate(listing_id: str, action: str, **extra) -> None:
    on_moderation_actioned(
        EventEnvelope(
            event_type="moderation.actioned",
            subject_id=str(uuid.uuid4()),
            producer="moderation-service",
            payload={"target_type": "listing", "target_id": listing_id, "action": action, **extra},
        )
    )


# ---- seller shop (?seller_id=) ------------------------------------------------


def test_seller_filter_lists_only_that_sellers_public_listings(client_for, category):
    seller, other, viewer = _acct(), _acct(), _acct()
    live = _listing(seller, category)
    _listing(seller, category, publish=False, title="Draft")  # never public
    _listing(other, category)
    url = reverse("marketplace:listings")
    resp = client_for(viewer).get(url, {"seller_id": seller})
    assert resp.status_code == 200
    assert _ids(resp) == [str(live.id)]
    # The short alias works too, and the facets follow the same filter.
    assert _ids(client_for(viewer).get(url, {"seller": seller})) == [str(live.id)]
    facets = client_for(viewer).get(reverse("marketplace:facets"), {"seller_id": seller})
    assert facets.json()["data"]["total"] == 1


def test_seller_filter_is_empty_across_a_block_and_rejects_bad_ids(client_for, category):
    seller, viewer = _acct(), _acct()
    _listing(seller, category)
    BlockedPair.objects.create(blocker_id=seller, blocked_id=viewer)
    url = reverse("marketplace:listings")
    assert _ids(client_for(viewer).get(url, {"seller_id": seller})) == []
    assert client_for(viewer).get(url, {"seller_id": "nope"}).status_code == 400


# ---- editing photos ------------------------------------------------------------


def test_patch_replaces_the_photo_set_in_order(client_for, category, media_stub):
    seller = _acct()
    a, b, c = (media_stub.add(seller) for _ in range(3))
    listing = _listing(seller, category, media_ids=[a, b])
    url = reverse("marketplace:listing-detail", args=[listing.id])
    resp = client_for(seller).patch(url, {"media_ids": [c, a]}, format="json")
    assert resp.status_code == 200
    assert [m["media_id"] for m in resp.json()["data"]["media"]] == [c, a]
    event = (
        OutboxEvent.objects.filter(event_type="listing.updated").order_by("created_at", "id").last()
    )
    assert "media" in event.payload["payload"]["changed"]
    assert event.payload["payload"]["cover_media_id"] == c


def test_patch_with_someone_elses_photo_changes_nothing(client_for, category, media_stub):
    seller, stranger = _acct(), _acct()
    mine = media_stub.add(seller)
    theirs = media_stub.add(stranger)
    listing = _listing(seller, category, media_ids=[mine])
    url = reverse("marketplace:listing-detail", args=[listing.id])
    resp = client_for(seller).patch(url, {"title": "New", "media_ids": [theirs]}, format="json")
    assert resp.status_code == 400
    assert resp.json()["error"]["details"][0]["code"] == "media_not_owned"
    listing.refresh_from_db()
    assert listing.title == "Lamp"
    assert list(ListingMedia.objects.values_list("media_id", flat=True)) == [uuid.UUID(mine)]


def test_patch_without_media_ids_keeps_photos_and_others_get_404(client_for, category, media_stub):
    seller = _acct()
    photo = media_stub.add(seller)
    listing = _listing(seller, category, media_ids=[photo])
    url = reverse("marketplace:listing-detail", args=[listing.id])
    resp = client_for(seller).patch(url, {"price": "15.00"}, format="json")
    assert resp.status_code == 200
    assert [m["media_id"] for m in resp.json()["data"]["media"]] == [photo]
    assert media_stub.calls[-1] == [photo]  # only the create checked media
    # Someone else's listing is not theirs to edit, and does not say it exists.
    assert client_for(_acct()).patch(url, {"title": "x"}, format="json").status_code == 404


def test_patch_can_clear_all_photos(client_for, category, media_stub):
    seller = _acct()
    listing = _listing(seller, category, media_ids=[media_stub.add(seller)])
    url = reverse("marketplace:listing-detail", args=[listing.id])
    resp = client_for(seller).patch(url, {"media_ids": []}, format="json")
    assert resp.status_code == 200
    assert resp.json()["data"]["media"] == []


# ---- Selling overview ------------------------------------------------------------


def test_my_listings_filters_by_status(client_for, category):
    seller = _acct()
    live = _listing(seller, category)
    draft = _listing(seller, category, publish=False)
    url = reverse("marketplace:my-listings")
    assert _ids(client_for(seller).get(url, {"status": "draft"})) == [str(draft.id)]
    assert set(_ids(client_for(seller).get(url, {"status": "active,draft"}))) == {
        str(live.id),
        str(draft.id),
    }
    assert client_for(seller).get(url, {"status": "bogus"}).status_code == 400


def test_selling_summary_counts_only_the_viewers_listings(client_for, category):
    seller = _acct()
    _listing(seller, category)
    _listing(seller, category, publish=False)
    _listing(_acct(), category)
    body = client_for(seller).get(reverse("marketplace:selling-summary")).json()["data"]
    assert body["counts"]["active"] == 1 and body["counts"]["draft"] == 1
    assert body["counts"]["sold"] == 0
    assert {"views", "saves", "inquiries"} <= set(body)


# ---- inquiries inbox ------------------------------------------------------------


def test_inbox_lists_each_side_of_an_inquiry(client_for, category):
    seller, buyer, stranger = _acct(), _acct(), _acct()
    listing = _listing(seller, category)
    services.record_inquiry(buyer, str(listing.id), "Still available?")
    url = reverse("marketplace:inquiries-list")

    buying = client_for(buyer).get(url, {"role": "buyer"}).json()["data"]
    assert len(buying) == 1
    assert buying[0]["counterpart_id"] == seller
    assert buying[0]["listing"]["title"] == "Lamp"

    selling = client_for(seller).get(url, {"role": "seller"}).json()["data"]
    assert [r["counterpart_id"] for r in selling] == [buyer]
    assert selling[0]["first_message"] == "Still available?"

    # Nobody else sees the conversation, from either side.
    assert client_for(stranger).get(url, {"role": "buyer"}).json()["data"] == []
    assert client_for(stranger).get(url, {"role": "seller"}).json()["data"] == []
    assert client_for(seller).get(url, {"role": "buyer"}).json()["data"] == []
    assert client_for(buyer).get(url, {"role": "admin"}).status_code == 400


def test_inbox_hides_listing_details_from_the_buyer_once_it_is_gone(client_for, category):
    seller, buyer = _acct(), _acct()
    listing = _listing(seller, category)
    services.record_inquiry(buyer, str(listing.id), "")
    services.transition(seller, str(listing.id), "archive")
    url = reverse("marketplace:inquiries-list")
    row = client_for(buyer).get(url, {"role": "buyer"}).json()["data"][0]
    assert row["listing"] is None and row["listing_id"] == str(listing.id)
    seller_row = client_for(seller).get(url, {"role": "seller"}).json()["data"][0]
    assert seller_row["listing"]["status"] == "archived"


def test_inbox_leaves_out_people_in_a_block(client_for, category):
    seller, buyer = _acct(), _acct()
    listing = _listing(seller, category)
    services.record_inquiry(buyer, str(listing.id), "")
    BlockedPair.objects.create(blocker_id=buyer, blocked_id=seller)
    url = reverse("marketplace:inquiries-list")
    assert client_for(seller).get(url, {"role": "seller"}).json()["data"] == []
    assert client_for(buyer).get(url, {"role": "buyer"}).json()["data"] == []


# ---- moderation note for the seller ----------------------------------------------


def test_removed_listing_tells_only_its_seller_why(client_for, category):
    seller = _acct()
    listing = _listing(seller, category)
    case_id = str(uuid.uuid4())
    _moderate(str(listing.id), "remove", case_id=case_id, reason="Counterfeit goods")
    url = reverse("marketplace:listing-detail", args=[listing.id])
    body = client_for(seller).get(url).json()["data"]
    assert body["status"] == "removed"
    assert body["moderation"] == {"case_id": case_id, "reason": "Counterfeit goods"}
    # Anyone else: a removed listing does not exist.
    assert client_for(_acct()).get(url).status_code == 404


def test_moderation_note_without_reason_and_cleared_on_approval(client_for, category):
    seller = _acct()
    listing = _listing(seller, category)
    _moderate(str(listing.id), "remove", case_id="not-a-uuid")
    url = reverse("marketplace:listing-detail", args=[listing.id])
    assert client_for(seller).get(url).json()["data"]["moderation"] == {
        "case_id": None,
        "reason": "",
    }
    _moderate(str(listing.id), "approve")
    body = client_for(seller).get(url).json()["data"]
    assert body["status"] == "active" and body["moderation"] is None


def test_rejected_listing_can_be_edited_and_resubmitted(client_for, category):
    seller = _acct()
    listing = _listing(seller, category)
    _moderate(str(listing.id), "reject", case_id=str(uuid.uuid4()), reason="Blurry photo")
    detail = reverse("marketplace:listing-detail", args=[listing.id])
    assert client_for(seller).get(detail).json()["data"]["moderation"]["reason"] == "Blurry photo"
    assert client_for(seller).patch(detail, {"title": "Lamp v2"}, format="json").status_code == 200
    resp = client_for(seller).post(reverse("marketplace:publish", args=[listing.id]))
    assert resp.status_code == 200 and resp.json()["data"]["status"] == "active"
