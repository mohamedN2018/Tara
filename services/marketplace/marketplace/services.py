"""Marketplace business logic: listings, prices, search, saves, inquiries, reviews."""

from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Avg, Count, Exists, F, Max, OuterRef, Q, QuerySet, Subquery
from django.utils import timezone

from tara_common.exceptions import Conflict, TaraAPIError

from . import events, media_client
from .models import (
    BlockedPair,
    Listing,
    ListingInquiry,
    ListingMedia,
    ListingReport,
    ListingSave,
    MarketplaceCategory,
    ReviewReport,
    SellerProfile,
    SellerReview,
)
from .money import infer_price_type, resolve_pricing
from .text import normalise, search_text

S = Listing.Status

# Statuses anyone (not just the seller) can open. Reserved and sold stay visible
# so saved items and shared links keep working; search shows "available" by default.
PUBLIC_STATUSES = (S.ACTIVE, S.RESERVED, S.SOLD)
AVAILABILITY = {S.ACTIVE: "available", S.RESERVED: "reserved", S.SOLD: "sold"}
STATUS_FOR_AVAILABILITY = {v: k for k, v in AVAILABILITY.items()}
INQUIRABLE_STATUSES = (S.ACTIVE, S.RESERVED)

# Seller-initiated status transitions (action -> (allowed_from, to)).
_SELLER_TRANSITIONS = {
    "reserve": ({S.ACTIVE}, S.RESERVED),
    "reactivate": ({S.RESERVED}, S.ACTIVE),
    "mark_sold": ({S.ACTIVE, S.RESERVED}, S.SOLD),
    "archive": ({S.DRAFT, S.ACTIVE, S.RESERVED, S.REJECTED}, S.ARCHIVED),
}


def availability_of(status: str) -> str | None:
    return AVAILABILITY.get(status)


def _not_found(what: str = "Listing") -> TaraAPIError:
    return TaraAPIError(f"{what} not found.", code="not_found", http_status_code=404)


def _bad_request(message: str, code: str, field: str | None = None) -> TaraAPIError:
    return TaraAPIError(
        message,
        code="validation_error",
        http_status_code=400,
        details=[{"field": field, "code": code, "message": message}],
    )


def _seller_listing(seller_id: str, listing_id: str) -> Listing:
    listing = Listing.objects.filter(
        id=listing_id, seller_id=seller_id, deleted_at__isnull=True
    ).first()
    if listing is None:
        raise _not_found()
    return listing


def _emit_status(listing: Listing, previous: str, actor_id: str) -> None:
    before, after = availability_of(previous), availability_of(listing.status)
    events.emit(
        "listing.status.changed",
        subject_id=str(listing.id),
        payload={
            "listing_id": str(listing.id),
            "from": previous,
            "to": listing.status,
            "availability": after,
            "seller_id": str(listing.seller_id),
            "title": listing.title,
        },
        actor_id=str(actor_id),
    )
    if before != after:
        events.emit(
            "listing.availability.changed",
            subject_id=str(listing.id),
            payload={
                "listing_id": str(listing.id),
                "seller_id": str(listing.seller_id),
                "from": before,
                "to": after,
            },
            actor_id=str(actor_id),
        )


# ---- create / edit ----------------------------------------------------------

MAX_MEDIA_PER_LISTING = 10  # roadmap 4.2; also under media's batch limit
_ATTACHABLE_STATUSES = {"processing", "ready"}


def _media_error(message: str, code: str) -> TaraAPIError:
    return TaraAPIError(
        message,
        code="validation_error",
        http_status_code=400,
        details=[{"field": "media_ids", "code": code, "message": message}],
    )


def _check_attachments(seller_id: str, media_ids: list[str]) -> None:
    """Each id is the seller's own image, uploaded. Videos wait for 5.7 (D1).

    A remote read, so it runs before any write; media being down is a 503.
    """
    if len(media_ids) > MAX_MEDIA_PER_LISTING:
        raise _media_error(
            f"A listing can have at most {MAX_MEDIA_PER_LISTING} photos.", "too_many_media"
        )
    if len(set(media_ids)) != len(media_ids):
        raise _media_error("The same photo is attached twice.", "duplicate_media")
    found = media_client.lookup(media_ids)
    infos = [found.get(m) for m in media_ids]
    # Someone else's media and unknown ids look the same, so neither leaks.
    if any(i is None or i.owner_id != str(seller_id) for i in infos):
        raise _media_error("Media not found.", "media_not_owned")
    if any(i.kind == "video" for i in infos):
        raise _media_error("Listing videos are not supported yet.", "video_not_supported_yet")
    if any(i.kind != "image" for i in infos):
        raise _media_error("Only photos can be attached to a listing.", "media_kind_not_allowed")
    if any(i.status not in _ATTACHABLE_STATUSES for i in infos):
        raise _media_error("Media upload is not complete.", "media_not_ready")


def _money(value) -> str | None:
    return None if value is None else str(value)


def create_listing(seller_id: str, data: dict) -> Listing:
    category = MarketplaceCategory.objects.filter(id=data["category_id"]).first()
    if category is None:
        raise _bad_request("Unknown category.", "unknown_category", "category_id")
    pricing = resolve_pricing(
        price_type=data.get("price_type"),
        price=data.get("price"),
        sale_price=data.get("sale_price"),
        currency=data.get("currency"),
    )
    media_ids = [str(m) for m in data.get("media_ids") or []]
    if media_ids:
        _check_attachments(seller_id, media_ids)  # remote: before the first write

    with transaction.atomic():
        SellerProfile.objects.get_or_create(account_id=seller_id)
        title, description = data["title"], data.get("description", "")
        listing = Listing.objects.create(
            seller_id=seller_id,
            category=category,
            title=title,
            description=description,
            condition=data.get("condition", Listing.Condition.GOOD),
            location=data.get("location", ""),
            status=S.DRAFT,
            search_text=search_text(title, description),
            **pricing,
        )
        for i, media_id in enumerate(media_ids):
            ListingMedia.objects.create(listing=listing, media_id=media_id, position=i)
        events.emit(
            "listing.created",
            subject_id=str(listing.id),
            payload={
                "listing_id": str(listing.id),
                "seller_id": str(seller_id),
                "category": category.slug,
                "price": _money(pricing["price"]),
                "sale_price": _money(pricing["sale_price"]),
                "price_type": pricing["price_type"],
                "currency": listing.currency,
                "title": listing.title,
            },
            actor_id=str(seller_id),
        )
    return listing


_PRICE_KEYS = ("price_type", "price", "sale_price", "currency")


def update_listing(seller_id: str, listing_id: str, data: dict) -> Listing:
    listing = _seller_listing(seller_id, listing_id)
    if listing.status == S.REMOVED:
        raise Conflict("A listing removed by moderators cannot be edited.", code="listing_removed")
    changed = [k for k in ("title", "description", "condition", "location") if k in data]
    for key in changed:
        setattr(listing, key, data[key])
    if any(k in data for k in _PRICE_KEYS):
        if "price_type" in data:
            kind = data["price_type"]
        elif "price" in data:
            kind = infer_price_type(data["price"])
        else:
            kind = listing.price_type
        free = kind == Listing.PriceType.FREE
        pricing = resolve_pricing(
            price_type=kind,
            price=data["price"] if "price" in data else (None if free else listing.price),
            sale_price=(
                data["sale_price"]
                if "sale_price" in data
                else (None if free else listing.sale_price)
            ),
            currency=data.get("currency", listing.currency),
        )
        for key, value in pricing.items():
            if getattr(listing, key) != value:
                changed.append(key)
            setattr(listing, key, value)
        if any(k in data for k in ("price_type", "price", "sale_price")):
            listing.price_unconfirmed = False
        if "currency" in data:
            listing.currency_unconfirmed = False
    if "title" in data or "description" in data:
        listing.search_text = search_text(listing.title, listing.description)
    listing.save()
    events.emit(
        "listing.updated",
        subject_id=str(listing.id),
        payload={"listing_id": str(listing.id), "changed": sorted(set(changed))},
        actor_id=str(seller_id),
    )
    return listing


def publish_listing(seller_id: str, listing_id: str) -> Listing:
    listing = _seller_listing(seller_id, listing_id)
    if listing.status not in (S.DRAFT, S.REJECTED):
        raise Conflict("Only draft/rejected listings can be published.", code="conflict")
    previous = listing.status
    listing.status = S.ACTIVE if settings.MARKETPLACE_AUTO_APPROVE else S.PENDING
    listing.save(update_fields=["status", "updated_at"])
    _emit_status(listing, previous, seller_id)
    return listing


def transition(seller_id: str, listing_id: str, action: str) -> Listing:
    if action not in _SELLER_TRANSITIONS:
        raise _bad_request("Unknown action.", "invalid_choice", "action")
    allowed_from, to = _SELLER_TRANSITIONS[action]
    listing = _seller_listing(seller_id, listing_id)
    if listing.status not in allowed_from:
        raise Conflict(f"Cannot {action} a {listing.status} listing.", code="conflict")
    previous = listing.status
    listing.status = to
    listing.save(update_fields=["status", "updated_at"])
    _emit_status(listing, previous, seller_id)
    return listing


# ---- visibility -------------------------------------------------------------


def _blocked_ids(viewer_id: str) -> set[str]:
    """Accounts in a block with the viewer, in either direction."""
    rows = BlockedPair.objects.filter(Q(blocker_id=viewer_id) | Q(blocked_id=viewer_id))
    out: set[str] = set()
    for r in rows:
        out.add(str(r.blocked_id if str(r.blocker_id) == str(viewer_id) else r.blocker_id))
    return out


def public_listings(viewer_id: str) -> QuerySet:
    """Listings any viewer may open: public statuses, not deleted, no block."""
    qs = Listing.objects.filter(status__in=PUBLIC_STATUSES, deleted_at__isnull=True)
    blocked = _blocked_ids(viewer_id)
    return qs.exclude(seller_id__in=blocked) if blocked else qs


def listing_visible_to(viewer_id: str) -> QuerySet:
    """The one visibility rule: the public set, plus all of the viewer's own listings."""
    blocked = _blocked_ids(viewer_id)
    qs = Listing.objects.filter(deleted_at__isnull=True).filter(
        Q(status__in=PUBLIC_STATUSES) | Q(seller_id=viewer_id)
    )
    return qs.exclude(seller_id__in=blocked) if blocked else qs


def with_viewer(qs: QuerySet, viewer_id: str) -> QuerySet:
    saved = ListingSave.objects.filter(listing=OuterRef("pk"), account_id=viewer_id)
    return qs.annotate(is_saved=Exists(saved)).select_related("category").prefetch_related("media")


def get_listing(viewer_id: str, listing_id: str) -> Listing:
    listing = with_viewer(listing_visible_to(viewer_id), viewer_id).filter(id=listing_id).first()
    if listing is None:
        raise _not_found()
    return listing


def viewer_state(viewer_id: str, listing: Listing) -> dict:
    own = str(listing.seller_id) == str(viewer_id)
    inquired = (
        not own and ListingInquiry.objects.filter(listing=listing, buyer_id=viewer_id).exists()
    )
    reviewed = (
        inquired and SellerReview.objects.filter(listing=listing, buyer_id=viewer_id).exists()
    )
    return {
        "is_owner": own,
        "is_saved": bool(getattr(listing, "is_saved", False)),
        "has_inquired": inquired,
        "can_review": inquired and not reviewed,
        "has_reviewed": reviewed,
    }


# ---- search, filters, facets ------------------------------------------------


def _category_tree() -> tuple[dict, dict]:
    cats = list(MarketplaceCategory.objects.all())
    by_slug = {c.slug: c for c in cats}
    children: dict = {}
    for c in cats:
        children.setdefault(c.parent_id, []).append(c.id)
    return by_slug, children


def _descendants(root_id, children: dict) -> list:
    out, stack = [], [root_id]
    while stack:
        node = stack.pop()
        if node in out:
            continue
        out.append(node)
        stack.extend(children.get(node, []))
    return out


def _apply_filters(qs: QuerySet, f: dict, skip: str | None = None) -> QuerySet:
    if f.get("q"):
        needle = normalise(f["q"])
        if needle:
            # `contains` (LIKE) on the normalised column, so the trigram index is used.
            qs = qs.filter(search_text__contains=needle)
    if skip != "category" and f.get("category"):
        by_slug, children = _category_tree()
        root = by_slug.get(f["category"])
        if root is None:
            return qs.none()
        qs = qs.filter(category_id__in=_descendants(root.id, children))
    if skip != "condition" and f.get("condition"):
        qs = qs.filter(condition__in=f["condition"])
    if skip != "price_type" and f.get("price_type"):
        qs = qs.filter(price_type__in=f["price_type"])
    if skip != "availability":
        wanted = f.get("availability") or ["available"]
        qs = qs.filter(status__in=[STATUS_FOR_AVAILABILITY[a] for a in wanted])
    if f.get("location"):
        qs = qs.filter(location__icontains=f["location"])
    if f.get("currency"):
        qs = qs.filter(currency=f["currency"])
    if f.get("min_price") is not None:
        qs = qs.filter(effective_price__gte=f["min_price"])
    if f.get("max_price") is not None:
        qs = qs.filter(effective_price__lte=f["max_price"])
    return qs


def search(viewer_id: str, filters: dict) -> QuerySet:
    """Unordered: the keyset paginator applies the sort."""
    return with_viewer(_apply_filters(public_listings(viewer_id), filters), viewer_id)


def _counts(qs: QuerySet, field: str) -> dict:
    return {row[field]: row["n"] for row in qs.order_by().values(field).annotate(n=Count("id"))}


def facets(viewer_id: str, filters: dict) -> dict:
    """Per-dimension counts. Each dimension ignores its own filter, so picking one
    category still shows how many results the other categories would give."""
    base = public_listings(viewer_id)  # blocked sellers never counted
    total = _apply_filters(base, filters).count()

    by_cat = _counts(_apply_filters(base, filters, skip="category"), "category_id")
    cats = list(MarketplaceCategory.objects.all())
    children: dict = {}
    for c in cats:
        children.setdefault(c.parent_id, []).append(c.id)
    category = []
    for c in cats:  # ordered by (position, name)
        n = sum(by_cat.get(cid, 0) for cid in _descendants(c.id, children))
        if n:
            category.append({"slug": c.slug, "name": c.name, "parent_id": c.parent_id, "count": n})

    def dim(name: str, field: str, values, mapping=None) -> list:
        counts = _counts(_apply_filters(base, filters, skip=name), field)
        out = []
        for value in values:
            n = counts.get(mapping[value] if mapping else value, 0)
            if n:
                out.append({"value": value, "count": n})
        return out

    return {
        "total": total,
        "category": category,
        "condition": dim("condition", "condition", Listing.Condition.values),
        "price_type": dim("price_type", "price_type", Listing.PriceType.values),
        "availability": dim(
            "availability", "status", list(STATUS_FOR_AVAILABILITY), STATUS_FOR_AVAILABILITY
        ),
    }


def my_listings(seller_id: str):
    return with_viewer(
        Listing.objects.filter(seller_id=seller_id, deleted_at__isnull=True), seller_id
    ).order_by("-created_at")


MAX_COMPARE = 4


def compare(viewer_id: str, listing_ids: list[str]) -> list[Listing]:
    """Visible listings among ``listing_ids``, in the order asked. Hidden ones are
    left out, exactly like ids that do not exist, so nothing leaks."""
    rows = with_viewer(listing_visible_to(viewer_id), viewer_id).filter(id__in=listing_ids)
    by_id = {str(r.id): r for r in rows}
    return [by_id[i] for i in listing_ids if i in by_id]


# ---- saves ------------------------------------------------------------------


def save_listing(account_id: str, listing_id: str) -> None:
    listing = get_listing(account_id, listing_id)
    _, created = ListingSave.objects.get_or_create(account_id=account_id, listing=listing)
    if created:
        Listing.objects.filter(id=listing.id).update(save_count=F("save_count") + 1)


def unsave_listing(account_id: str, listing_id: str) -> None:
    deleted, _ = ListingSave.objects.filter(account_id=account_id, listing_id=listing_id).delete()
    if deleted:
        Listing.objects.filter(id=listing_id, save_count__gt=0).update(
            save_count=F("save_count") - 1
        )


def list_saved(account_id: str) -> QuerySet:
    """Saved listings the account can still open, newest save first (``saved_at``)."""
    saves = ListingSave.objects.filter(account_id=account_id, listing=OuterRef("pk"))
    return with_viewer(
        public_listings(account_id)
        .filter(Exists(saves))
        .annotate(saved_at=Subquery(saves.values("created_at")[:1])),
        account_id,
    )


# ---- report / inquiries -----------------------------------------------------


def report_listing(reporter_id: str, listing_id: str, reason: str) -> ListingReport:
    # 404 for anything the reporter cannot see (drafts, pending, blocked sellers),
    # so reporting does not reveal that a hidden listing exists.
    listing = get_listing(reporter_id, listing_id)
    if str(listing.seller_id) == str(reporter_id):
        raise _bad_request("You cannot report your own listing.", "own_listing")
    report = ListingReport.objects.create(listing=listing, reporter_id=reporter_id, reason=reason)
    events.emit(
        "listing.reported",
        subject_id=str(listing.id),
        payload={
            "listing_id": str(listing.id),
            "reporter": str(reporter_id),
            # The seller: moderation lets only the owner appeal the decision.
            "owner_id": str(listing.seller_id),
            "reason": reason,
        },
        actor_id=str(reporter_id),
    )
    return report


def record_inquiry(buyer_id: str, listing_id: str, message: str = "") -> ListingInquiry:
    """The buyer is messaging the seller about this listing (the DM itself is chat's)."""
    listing = get_listing(buyer_id, listing_id)
    if str(listing.seller_id) == str(buyer_id):
        raise _bad_request("You own this listing.", "own_listing")
    if listing.status not in INQUIRABLE_STATUSES:
        raise Conflict("This listing is no longer available.", code="listing_unavailable")
    inquiry, created = ListingInquiry.objects.get_or_create(
        listing=listing,
        buyer_id=buyer_id,
        defaults={"seller_id": listing.seller_id, "first_message": message[:1000]},
    )
    if created:
        Listing.objects.filter(id=listing.id).update(inquiry_count=F("inquiry_count") + 1)
        events.emit(
            "marketplace.inquiry.created",
            subject_id=str(listing.id),
            payload={
                "inquiry_id": str(inquiry.id),
                "listing_id": str(listing.id),
                "seller_id": str(listing.seller_id),
                "buyer_id": str(buyer_id),
            },
            actor_id=str(buyer_id),
        )
    else:
        ListingInquiry.objects.filter(id=inquiry.id).update(
            message_count=F("message_count") + 1, last_activity_at=timezone.now()
        )
    inquiry.listing = listing
    return inquiry


def contact_seller(buyer_id: str, listing_id: str, message: str = "") -> Listing:
    """Legacy flow: chat opens a listing thread from ``marketplace.contact.requested``."""
    inquiry = record_inquiry(buyer_id, listing_id, message)
    listing = inquiry.listing
    events.emit(
        "marketplace.contact.requested",
        subject_id=str(listing.id),
        payload={
            "listing_id": str(listing.id),
            "seller_id": str(listing.seller_id),
            "buyer_id": str(buyer_id),
            "inquiry_id": str(inquiry.id),
            "title": listing.title,
        },
        actor_id=str(buyer_id),
    )
    return listing


# ---- sellers and reviews ----------------------------------------------------


def _response_hint(last_active) -> str | None:
    """A coarse activity hint until chat thread events give real response times (4.7)."""
    if last_active is None:
        return None
    age = timezone.now() - last_active
    if age <= timedelta(days=1):
        return "active_today"
    if age <= timedelta(days=7):
        return "active_this_week"
    if age <= timedelta(days=30):
        return "active_this_month"
    return "inactive"


def seller_summary(viewer_id: str, seller_id: str) -> dict:
    if str(seller_id) in _blocked_ids(viewer_id):
        raise _not_found("Seller")
    profile = SellerProfile.objects.filter(account_id=seller_id).first()
    public = Q(status__in=PUBLIC_STATUSES)
    stats = Listing.objects.filter(seller_id=seller_id, deleted_at__isnull=True).aggregate(
        active=Count("id", filter=Q(status=S.ACTIVE)),
        sold=Count("id", filter=Q(status=S.SOLD)),
        public=Count("id", filter=public),
        last_active=Max("updated_at", filter=public),
    )
    if profile is None or (not stats["public"] and str(seller_id) != str(viewer_id)):
        raise _not_found("Seller")
    return {
        "seller_id": str(seller_id),
        "member_since": profile.created_at,
        "active_listings_count": stats["active"],
        "sold_listings_count": stats["sold"],
        "rating_avg": round(profile.rating_avg, 2) if profile.rating_count else None,
        "rating_count": profile.rating_count,
        "response_hint": _response_hint(stats["last_active"]),
    }


def _refresh_rating(seller_id: str) -> None:
    agg = SellerReview.objects.filter(
        seller_id=seller_id, status=SellerReview.Status.PUBLISHED
    ).aggregate(avg=Avg("rating"), n=Count("id"))
    SellerProfile.objects.update_or_create(
        account_id=seller_id,
        defaults={"rating_avg": float(agg["avg"] or 0.0), "rating_count": agg["n"]},
    )


def create_review(buyer_id: str, listing_id: str, rating: int, body: str) -> SellerReview:
    listing = get_listing(buyer_id, listing_id)
    if str(listing.seller_id) == str(buyer_id):
        raise _bad_request("You cannot review your own listing.", "own_listing")
    if not ListingInquiry.objects.filter(listing=listing, buyer_id=buyer_id).exists():
        raise TaraAPIError(
            "Only buyers who contacted the seller about this listing can review it.",
            code="review_not_eligible",
            http_status_code=403,
        )
    if SellerReview.objects.filter(listing=listing, buyer_id=buyer_id).exists():
        raise Conflict("You already reviewed this listing.", code="already_reviewed")
    try:
        with transaction.atomic():
            review = SellerReview.objects.create(
                listing=listing,
                seller_id=listing.seller_id,
                buyer_id=buyer_id,
                rating=rating,
                body=body,
            )
    except IntegrityError as exc:  # a concurrent duplicate
        raise Conflict("You already reviewed this listing.", code="already_reviewed") from exc
    _refresh_rating(str(listing.seller_id))
    events.emit(
        "marketplace.review.created",
        subject_id=str(review.id),
        payload={
            "review_id": str(review.id),
            "listing_id": str(listing.id),
            "seller_id": str(listing.seller_id),
            "buyer_id": str(buyer_id),
            "rating": rating,
        },
        actor_id=str(buyer_id),
    )
    return review


def seller_reviews(viewer_id: str, seller_id: str) -> QuerySet:
    blocked = _blocked_ids(viewer_id)
    if str(seller_id) in blocked:
        raise _not_found("Seller")
    qs = SellerReview.objects.filter(
        seller_id=seller_id, status=SellerReview.Status.PUBLISHED
    ).select_related("listing")
    return qs.exclude(buyer_id__in=blocked) if blocked else qs


def report_review(reporter_id: str, review_id: str, reason: str) -> None:
    review = SellerReview.objects.filter(id=review_id, status=SellerReview.Status.PUBLISHED).first()
    blocked = _blocked_ids(reporter_id)
    if review is None or str(review.seller_id) in blocked or str(review.buyer_id) in blocked:
        raise _not_found("Review")
    if str(review.buyer_id) == str(reporter_id):
        raise _bad_request("You cannot report your own review.", "own_review")
    _, created = ReviewReport.objects.get_or_create(
        review=review, reporter_id=reporter_id, defaults={"reason": reason}
    )
    if created:  # one report per reporter per review reaches moderation
        events.emit(
            "marketplace.review.reported",
            subject_id=str(review.id),
            payload={
                "review_id": str(review.id),
                "listing_id": str(review.listing_id),
                "seller_id": str(review.seller_id),
                "reporter": str(reporter_id),
                # The review's author: the one who may appeal a removal.
                "owner_id": str(review.buyer_id),
                "reason": reason,
            },
            actor_id=str(reporter_id),
        )


def apply_review_moderation(review_id: str, action: str) -> None:
    review = SellerReview.objects.filter(id=review_id).first()
    if review is None:
        return
    previous = review.status
    if action == "remove":
        review.status = SellerReview.Status.REMOVED
    elif action == "approve" and previous == SellerReview.Status.REMOVED:
        review.status = SellerReview.Status.PUBLISHED  # appeal overturned
    if review.status == previous:
        return
    review.save(update_fields=["status", "updated_at"])
    _refresh_rating(str(review.seller_id))
    events.emit(
        "marketplace.review.status.changed",
        subject_id=str(review.id),
        payload={
            "review_id": str(review.id),
            "seller_id": str(review.seller_id),
            "from": previous,
            "to": review.status,
        },
    )


# ---- inbound moderation -----------------------------------------------------


def apply_moderation(listing_id: str, action: str) -> None:
    """Driven by moderation.actioned events (Phase 6)."""
    listing = Listing.objects.filter(id=listing_id).first()
    if listing is None:
        return
    previous = listing.status
    if action == "remove":
        listing.status = S.REMOVED  # sellers cannot republish this
    elif action == "reject":
        listing.status = S.REJECTED
    elif action == "approve" and previous in (S.PENDING, S.REMOVED):
        listing.status = S.ACTIVE  # review passed, or appeal overturned
    else:
        return
    listing.save(update_fields=["status", "updated_at"])
    _emit_status(listing, previous, actor_id=listing.seller_id)
