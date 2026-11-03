"""Marketplace API: listing lifecycle, search, saves, contact, moderation, block."""

import uuid

import pytest
from django.urls import reverse

from marketplace import services
from marketplace.models import Listing, OutboxEvent

pytestmark = pytest.mark.django_db


def _acct() -> str:
    return str(uuid.uuid4())


def _create(seller, category, **over):
    data = {
        "category_id": str(category.id),
        "title": over.get("title", "iPhone"),
        "description": over.get("description", "good phone"),
        "price": over.get("price", "100.00"),
        "currency": "USD",
        "condition": "good",
        "location": over.get("location", "Cairo"),
        "media_ids": [],
    }
    return services.create_listing(seller, data)


# ---- lifecycle --------------------------------------------------------------


def test_create_publish_makes_active_and_searchable(client_for, category):
    seller = _acct()
    create = client_for(seller).post(
        reverse("marketplace:listings"),
        {"category_id": str(category.id), "title": "Bike", "price": "50.00"},
        format="json",
    )
    assert create.status_code == 201
    listing_id = create.json()["data"]["id"]
    assert create.json()["data"]["status"] == "draft"
    assert OutboxEvent.objects.filter(event_type="listing.created").exists()

    pub = client_for(seller).post(reverse("marketplace:publish", args=[listing_id]))
    assert pub.status_code == 200
    assert pub.json()["data"]["status"] == "active"  # AUTO_APPROVE on in tests

    # A different user can find it in search.
    search = client_for(_acct()).get(reverse("marketplace:listings"), {"q": "Bike"})
    assert search.status_code == 200
    assert any(it["id"] == listing_id for it in search.json()["data"])


def test_draft_not_visible_to_others(client_for, category):
    seller = _acct()
    listing = _create(seller, category)  # stays draft
    # Owner sees it; a stranger gets 404.
    assert (
        client_for(seller).get(reverse("marketplace:listing-detail", args=[listing.id])).status_code
        == 200
    )
    assert (
        client_for(_acct())
        .get(reverse("marketplace:listing-detail", args=[listing.id]))
        .status_code
        == 404
    )


def test_status_transitions(client_for, category):
    seller = _acct()
    listing = _create(seller, category)
    services.publish_listing(seller, str(listing.id))  # -> active
    client = client_for(seller)
    assert (
        client.post(
            reverse("marketplace:transition", args=[listing.id]),
            {"action": "reserve"},
            format="json",
        ).json()["data"]["status"]
        == "reserved"
    )
    assert (
        client.post(
            reverse("marketplace:transition", args=[listing.id]),
            {"action": "mark_sold"},
            format="json",
        ).json()["data"]["status"]
        == "sold"
    )
    # Can't reserve a sold listing.
    assert (
        client.post(
            reverse("marketplace:transition", args=[listing.id]),
            {"action": "reserve"},
            format="json",
        ).status_code
        == 409
    )


def test_search_filters_by_price_and_category(client_for, category):
    seller = _acct()
    cheap = _create(seller, category, title="Cheap", price="10.00")
    pricey = _create(seller, category, title="Pricey", price="999.00")
    services.publish_listing(seller, str(cheap.id))
    services.publish_listing(seller, str(pricey.id))
    resp = client_for(_acct()).get(reverse("marketplace:listings"), {"max_price": "100"})
    ids = [it["id"] for it in resp.json()["data"]]
    assert str(cheap.id) in ids and str(pricey.id) not in ids


# ---- saves / report / contact ----------------------------------------------


def test_save_unsave(client_for, category):
    seller, buyer = _acct(), _acct()
    listing = _create(seller, category)
    services.publish_listing(seller, str(listing.id))
    client = client_for(buyer)
    assert client.post(reverse("marketplace:save", args=[listing.id])).status_code == 200
    assert (
        client.post(reverse("marketplace:save", args=[listing.id])).status_code == 200
    )  # idempotent
    listing.refresh_from_db()
    assert listing.save_count == 1
    assert len(client.get(reverse("marketplace:saved")).json()["data"]) == 1


def test_contact_seller_emits_event(client_for, category):
    seller, buyer = _acct(), _acct()
    listing = _create(seller, category)
    services.publish_listing(seller, str(listing.id))
    resp = client_for(buyer).post(reverse("marketplace:contact", args=[listing.id]))
    assert resp.status_code == 202
    assert OutboxEvent.objects.filter(event_type="marketplace.contact.requested").exists()


def test_cannot_contact_own_listing(client_for, category):
    seller = _acct()
    listing = _create(seller, category)
    services.publish_listing(seller, str(listing.id))
    assert (
        client_for(seller).post(reverse("marketplace:contact", args=[listing.id])).status_code
        == 400
    )


def test_report_emits_event(client_for, category):
    seller = _acct()
    listing = _create(seller, category)
    services.publish_listing(seller, str(listing.id))
    resp = client_for(_acct()).post(
        reverse("marketplace:report", args=[listing.id]), {"reason": "fake"}, format="json"
    )
    assert resp.status_code == 202
    assert OutboxEvent.objects.filter(event_type="listing.reported").exists()


# ---- inbound moderation -----------------------------------------------------


def test_moderation_removal_via_handler(category):
    from marketplace.handlers import on_moderation_actioned
    from tara_events.envelope import EventEnvelope

    seller = _acct()
    listing = _create(seller, category)
    services.publish_listing(seller, str(listing.id))
    on_moderation_actioned(
        EventEnvelope(
            event_type="moderation.actioned",
            subject_id=str(listing.id),
            producer="moderation-service",
            payload={"target_type": "listing", "target_id": str(listing.id), "action": "remove"},
        )
    )
    listing.refresh_from_db()
    assert listing.status == Listing.Status.REMOVED
