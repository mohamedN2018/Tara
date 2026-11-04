"""Listing inquiries notify the seller; kinds nobody writes stay out of Settings (T5)."""

import uuid

import pytest

from notifications import commerce_handlers, registry
from notifications.models import Notification
from tara_events.envelope import EventEnvelope

pytestmark = pytest.mark.django_db


def _acct() -> str:
    return str(uuid.uuid4())


def _inquiry(seller: str, buyer: str, listing: str) -> EventEnvelope:
    return EventEnvelope(
        event_type="marketplace.inquiry.created",
        payload={
            "inquiry_id": str(uuid.uuid4()),
            "listing_id": listing,
            "seller_id": seller,
            "buyer_id": buyer,
        },
        subject_id=listing,
        producer="marketplace-service",
        actor_id=buyer,
    )


def test_inquiry_notifies_the_seller_once_per_listing_row():
    seller, listing = _acct(), str(uuid.uuid4())
    first, second = _acct(), _acct()
    commerce_handlers.on_marketplace_inquiry(_inquiry(seller, first, listing))
    commerce_handlers.on_marketplace_inquiry(_inquiry(seller, second, listing))
    commerce_handlers.on_marketplace_inquiry(_inquiry(seller, second, listing))  # replay

    rows = Notification.objects.filter(recipient_id=seller, kind="listing.inquiry")
    assert rows.count() == 1
    row = rows.get()
    assert row.actor_count == 2
    assert row.subject_ref == f"listing:{listing}"
    assert registry.url_for(row) == f"/marketplace/{listing}"
    assert registry.KINDS["listing.inquiry"].category == "marketplace"


def test_inquiry_on_own_listing_is_ignored():
    me = _acct()
    commerce_handlers.on_marketplace_inquiry(_inquiry(me, me, str(uuid.uuid4())))
    assert not Notification.objects.filter(recipient_id=me).exists()


def test_kinds_without_a_producer_are_not_offered():
    described = {k["kind"] for k in registry.describe()}
    assert "listing.inquiry" in described
    assert "page.follow" not in described
    assert "ad.review" not in described


def test_page_link_without_a_handle_uses_the_by_id_route():
    url = registry.build_url("page.follow", subject_ref="page:abc")
    assert url == "/pages/id/abc"


def test_group_invite_resolutions_cover_join_decline_and_a_withdrawn_invite():
    # The inline Join / Decline buttons record one of these (T5).
    assert registry.KINDS["group.invite"].resolutions == {"joined", "declined", "expired"}
