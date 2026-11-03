"""Marketplace business logic: listings, status state machine, search, saves, contact."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import transaction
from django.db.models import F, Q

from tara_common.exceptions import Conflict, TaraAPIError

from . import events
from .models import (
    BlockedPair,
    Listing,
    ListingMedia,
    ListingReport,
    ListingSave,
    MarketplaceCategory,
    SellerProfile,
)

# Seller-initiated status transitions (action -> (allowed_from, to)).
_SELLER_TRANSITIONS = {
    "reserve": ({Listing.Status.ACTIVE}, Listing.Status.RESERVED),
    "reactivate": ({Listing.Status.RESERVED}, Listing.Status.ACTIVE),
    "mark_sold": ({Listing.Status.ACTIVE, Listing.Status.RESERVED}, Listing.Status.SOLD),
    "archive": (
        {
            Listing.Status.DRAFT,
            Listing.Status.ACTIVE,
            Listing.Status.RESERVED,
            Listing.Status.REJECTED,
        },
        Listing.Status.ARCHIVED,
    ),
}


def _seller_listing(seller_id: str, listing_id: str) -> Listing:
    listing = Listing.objects.filter(
        id=listing_id, seller_id=seller_id, deleted_at__isnull=True
    ).first()
    if listing is None:
        raise TaraAPIError("Listing not found.", code="not_found", http_status_code=404)
    return listing


def _emit_status(listing: Listing, previous: str, actor_id: str) -> None:
    events.emit(
        "listing.status.changed",
        subject_id=str(listing.id),
        payload={
            "listing_id": str(listing.id),
            "from": previous,
            "to": listing.status,
            "seller_id": str(listing.seller_id),
            "title": listing.title,
        },
        actor_id=str(actor_id),
    )


# ---- create / edit ----------------------------------------------------------


def create_listing(seller_id: str, data: dict) -> Listing:
    category = MarketplaceCategory.objects.filter(id=data["category_id"]).first()
    if category is None:
        raise TaraAPIError("Unknown category.", code="validation_error", http_status_code=400)
    try:
        price = Decimal(str(data.get("price", "0")))
    except (InvalidOperation, TypeError) as exc:
        raise TaraAPIError("Invalid price.", code="validation_error", http_status_code=400) from exc
    if price < 0:
        raise TaraAPIError(
            "Price cannot be negative.", code="validation_error", http_status_code=400
        )

    with transaction.atomic():
        SellerProfile.objects.get_or_create(account_id=seller_id)
        listing = Listing.objects.create(
            seller_id=seller_id,
            category=category,
            title=data["title"],
            description=data.get("description", ""),
            price=price,
            currency=data.get("currency", "USD"),
            condition=data.get("condition", Listing.Condition.GOOD),
            location=data.get("location", ""),
            status=Listing.Status.DRAFT,
        )
        for i, media_id in enumerate(data.get("media_ids", [])):
            ListingMedia.objects.create(listing=listing, media_id=media_id, position=i)
        events.emit(
            "listing.created",
            subject_id=str(listing.id),
            payload={
                "listing_id": str(listing.id),
                "seller_id": str(seller_id),
                "category": category.slug,
                "price": str(price),
                "currency": listing.currency,
                "title": listing.title,
            },
            actor_id=str(seller_id),
        )
    return listing


def update_listing(seller_id: str, listing_id: str, data: dict) -> Listing:
    listing = _seller_listing(seller_id, listing_id)
    for key in ("title", "description", "currency", "condition", "location"):
        if key in data:
            setattr(listing, key, data[key])
    if "price" in data:
        listing.price = Decimal(str(data["price"]))
    listing.save()
    events.emit(
        "listing.updated",
        subject_id=str(listing.id),
        payload={"listing_id": str(listing.id)},
        actor_id=str(seller_id),
    )
    return listing


def publish_listing(seller_id: str, listing_id: str) -> Listing:
    listing = _seller_listing(seller_id, listing_id)
    if listing.status not in (Listing.Status.DRAFT, Listing.Status.REJECTED):
        raise Conflict("Only draft/rejected listings can be published.", code="conflict")
    previous = listing.status
    listing.status = (
        Listing.Status.ACTIVE if settings.MARKETPLACE_AUTO_APPROVE else Listing.Status.PENDING
    )
    listing.save(update_fields=["status"])
    _emit_status(listing, previous, seller_id)
    return listing


def transition(seller_id: str, listing_id: str, action: str) -> Listing:
    if action not in _SELLER_TRANSITIONS:
        raise TaraAPIError("Unknown action.", code="validation_error", http_status_code=400)
    allowed_from, to = _SELLER_TRANSITIONS[action]
    listing = _seller_listing(seller_id, listing_id)
    if listing.status not in allowed_from:
        raise Conflict(f"Cannot {action} a {listing.status} listing.", code="conflict")
    previous = listing.status
    listing.status = to
    listing.save(update_fields=["status"])
    _emit_status(listing, previous, seller_id)
    return listing


# ---- read / search ----------------------------------------------------------


def _blocked_seller_ids(viewer_id: str) -> set[str]:
    rows = BlockedPair.objects.filter(Q(blocker_id=viewer_id) | Q(blocked_id=viewer_id))
    out: set[str] = set()
    for r in rows:
        out.add(str(r.blocked_id if str(r.blocker_id) == str(viewer_id) else r.blocker_id))
    return out


def get_listing(viewer_id: str, listing_id: str) -> Listing:
    listing = Listing.objects.filter(id=listing_id, deleted_at__isnull=True).first()
    if listing is None:
        raise TaraAPIError("Listing not found.", code="not_found", http_status_code=404)
    if str(listing.seller_id) == str(viewer_id):
        return listing
    if listing.status != Listing.Status.ACTIVE or str(listing.seller_id) in _blocked_seller_ids(
        viewer_id
    ):
        raise TaraAPIError("Listing not found.", code="not_found", http_status_code=404)
    return listing


def search(viewer_id: str, filters: dict):
    qs = Listing.objects.filter(status=Listing.Status.ACTIVE, deleted_at__isnull=True)
    if filters.get("category"):
        qs = qs.filter(category__slug=filters["category"])
    if filters.get("condition"):
        qs = qs.filter(condition=filters["condition"])
    if filters.get("location"):
        qs = qs.filter(location__icontains=filters["location"])
    if filters.get("min_price") is not None:
        qs = qs.filter(price__gte=filters["min_price"])
    if filters.get("max_price") is not None:
        qs = qs.filter(price__lte=filters["max_price"])
    if filters.get("q"):
        q = filters["q"]
        qs = qs.filter(Q(title__icontains=q) | Q(description__icontains=q))
    blocked = _blocked_seller_ids(viewer_id)
    if blocked:
        qs = qs.exclude(seller_id__in=blocked)
    return qs.order_by("-created_at")


def my_listings(seller_id: str):
    return Listing.objects.filter(seller_id=seller_id, deleted_at__isnull=True).order_by(
        "-created_at"
    )


# ---- saves ------------------------------------------------------------------


def save_listing(account_id: str, listing_id: str) -> None:
    listing = get_listing(account_id, listing_id)
    _, created = ListingSave.objects.get_or_create(account_id=account_id, listing=listing)
    if created:
        Listing.objects.filter(id=listing.id).update(save_count=F("save_count") + 1)


def unsave_listing(account_id: str, listing_id: str) -> None:
    deleted, _ = ListingSave.objects.filter(account_id=account_id, listing_id=listing_id).delete()
    if deleted:
        Listing.objects.filter(id=listing_id).update(save_count=F("save_count") - 1)


def list_saved(account_id: str):
    listing_ids = ListingSave.objects.filter(account_id=account_id).values_list(
        "listing_id", flat=True
    )
    return Listing.objects.filter(id__in=list(listing_ids), deleted_at__isnull=True).order_by(
        "-created_at"
    )


# ---- report / contact -------------------------------------------------------


def report_listing(reporter_id: str, listing_id: str, reason: str) -> ListingReport:
    listing = Listing.objects.filter(id=listing_id, deleted_at__isnull=True).first()
    if listing is None:
        raise TaraAPIError("Listing not found.", code="not_found", http_status_code=404)
    report = ListingReport.objects.create(listing=listing, reporter_id=reporter_id, reason=reason)
    events.emit(
        "listing.reported",
        subject_id=str(listing.id),
        payload={"listing_id": str(listing.id), "reporter": str(reporter_id), "reason": reason},
        actor_id=str(reporter_id),
    )
    return report


def contact_seller(buyer_id: str, listing_id: str) -> Listing:
    listing = get_listing(buyer_id, listing_id)
    if str(listing.seller_id) == str(buyer_id):
        raise TaraAPIError("You own this listing.", code="validation_error", http_status_code=400)
    # Buyer/seller chat is created in Chat via this event (doc 01 §2.10).
    events.emit(
        "marketplace.contact.requested",
        subject_id=str(listing.id),
        payload={
            "listing_id": str(listing.id),
            "seller_id": str(listing.seller_id),
            "buyer_id": str(buyer_id),
            "title": listing.title,
        },
        actor_id=str(buyer_id),
    )
    return listing


# ---- inbound moderation -----------------------------------------------------


def apply_moderation(listing_id: str, action: str) -> None:
    """Driven by moderation.actioned events (Phase 6)."""
    listing = Listing.objects.filter(id=listing_id).first()
    if listing is None:
        return
    previous = listing.status
    if action == "remove":
        listing.status = Listing.Status.REMOVED  # sellers cannot republish this
    elif action == "reject":
        listing.status = Listing.Status.REJECTED
    elif action == "approve" and previous in (
        Listing.Status.PENDING,
        Listing.Status.REMOVED,
    ):
        listing.status = Listing.Status.ACTIVE  # review passed, or appeal overturned
    else:
        return
    listing.save(update_fields=["status"])
    _emit_status(listing, previous, actor_id=listing.seller_id)
