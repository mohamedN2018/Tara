"""Marketplace inquiries (plan 08 4D): ``marketplace.inquiry.created`` becomes a
``listing.inquiry`` notification for the seller, one open row per listing
("X and 2 others asked about your listing"). Marketplace emits it once per buyer
per listing, and the aggregate counts each buyer once, so a replay never
inflates the row. Imported by ``handlers`` so the consumer registers it.
"""

from __future__ import annotations

from tara_events import on_event
from tara_events.envelope import EventEnvelope

from .services import notify


@on_event("marketplace.inquiry.created")
def on_marketplace_inquiry(e: EventEnvelope) -> None:
    p = e.payload
    seller, buyer, listing = p.get("seller_id"), p.get("buyer_id"), p.get("listing_id")
    if not (seller and buyer and listing) or str(seller) == str(buyer):
        return
    notify(
        seller,
        "listing.inquiry",
        actor_id=buyer,
        subject_ref=f"listing:{listing}",
        body="asked about your listing",
        data={"listing_id": listing},
    )
