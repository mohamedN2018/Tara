"""Advertisement business logic: setup, review, serving, events, budgeting."""

from __future__ import annotations

import hashlib
from decimal import Decimal

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.db.models import Count, F, IntegerField, OuterRef, Q, Subquery
from django.db.models.functions import Coalesce
from django.utils import timezone

from tara_common.exceptions import Conflict, TaraAPIError

from . import events, media_client, serve_tokens
from .models import (
    AdBudgetLedger,
    AdClickEvent,
    AdCreative,
    AdImpressionEvent,
    AdReview,
    AdSet,
    AdvertiserAccount,
    Campaign,
)


def viewer_bucket(viewer_id: str) -> str:
    """Coarse, non-reversible bucket for privacy-safe metrics (never the raw id)."""
    return hashlib.sha256(str(viewer_id).encode()).hexdigest()[:2]


# ---- advertiser setup -------------------------------------------------------


def ensure_advertiser(owner_account_id: str, name: str = "") -> AdvertiserAccount:
    advertiser, _ = AdvertiserAccount.objects.get_or_create(
        owner_account_id=owner_account_id, defaults={"name": name or "Advertiser"}
    )
    return advertiser


def _own_advertiser(owner_account_id: str) -> AdvertiserAccount:
    advertiser = AdvertiserAccount.objects.filter(owner_account_id=owner_account_id).first()
    if advertiser is None:
        raise TaraAPIError("No advertiser account.", code="not_found", http_status_code=404)
    return advertiser


def create_campaign(owner_account_id: str, data: dict) -> Campaign:
    advertiser = ensure_advertiser(owner_account_id)
    return Campaign.objects.create(
        advertiser=advertiser,
        name=data["name"],
        objective=data.get("objective", "reach"),
        budget=Decimal(str(data.get("budget", "0"))),
        currency=data.get("currency", "USD"),
        schedule_start=data.get("schedule_start"),
        schedule_end=data.get("schedule_end"),
        status=Campaign.Status.ACTIVE,
    )


def set_campaign_status(owner_account_id: str, campaign_id: str, status: str) -> Campaign:
    """Pause or resume. A finished campaign stays finished: its budget is spent."""
    # Locked like a debit, so a concurrent last charge's COMPLETED is never overwritten.
    campaign = _own_campaign(owner_account_id, campaign_id, lock=True)
    if campaign.status == Campaign.Status.COMPLETED:
        raise Conflict("This campaign has finished.", code="conflict")
    campaign.status = status
    campaign.save(update_fields=["status"])
    return campaign


def campaign_ad_sets(owner_account_id: str, campaign_id: str):
    campaign = _own_campaign(owner_account_id, campaign_id)
    return campaign.ad_sets.prefetch_related("creatives__reviews").order_by("created_at")


def _own_campaign(owner_account_id: str, campaign_id: str, *, lock: bool = False) -> Campaign:
    qs = Campaign.objects.select_related("advertiser")
    if lock:
        qs = qs.select_for_update(of=("self",))
    campaign = qs.filter(id=campaign_id).first()
    if campaign is None or str(campaign.advertiser.owner_account_id) != str(owner_account_id):
        raise TaraAPIError("Campaign not found.", code="not_found", http_status_code=404)
    return campaign


def create_ad_set(owner_account_id: str, campaign_id: str, data: dict) -> AdSet:
    campaign = _own_campaign(owner_account_id, campaign_id)
    return AdSet.objects.create(
        campaign=campaign,
        name=data.get("name", ""),
        targeting=data.get("targeting", {}),
        placement=data.get("placement", AdSet.Placement.FEED),
        cpc=Decimal(str(data.get("cpc", "0"))),
        cpm=Decimal(str(data.get("cpm", "0"))),
        frequency_cap=data.get("frequency_cap", 0),
    )


def _media_error(message: str, code: str) -> TaraAPIError:
    return TaraAPIError(
        message,
        code="validation_error",
        http_status_code=400,
        details=[{"field": "media_id", "code": code, "message": message}],
    )


def _check_media(owner_account_id: str, media_id: str) -> None:
    """The advertiser's own image, fully processed. Media down is a 503 (fail closed)."""
    info = media_client.lookup([media_id]).get(media_id)
    # Someone else's media and an unknown id look the same, so neither leaks.
    if info is None or info.owner_id != str(owner_account_id):
        raise _media_error("Media not found.", "media_not_owned")
    if info.kind != "image":
        raise _media_error("Only images can be used in an ad.", "media_kind_not_allowed")
    if info.status != "ready":
        raise _media_error("Media upload is not complete.", "media_not_ready")


def create_creative(owner_account_id: str, ad_set_id: str, data: dict) -> AdCreative:
    ad_set = AdSet.objects.select_related("campaign__advertiser").filter(id=ad_set_id).first()
    if ad_set is None or str(ad_set.campaign.advertiser.owner_account_id) != str(owner_account_id):
        raise TaraAPIError("Ad set not found.", code="not_found", http_status_code=404)
    if data.get("media_id"):
        _check_media(owner_account_id, str(data["media_id"]))  # remote: before any write
    creative = AdCreative.objects.create(
        ad_set=ad_set,
        headline=data["headline"],
        body=data.get("body", ""),
        media_id=data.get("media_id"),
        cta=data.get("cta", "Learn more"),
        link_url=data.get("link_url", ""),
    )
    if settings.ADS_AUTO_APPROVE:
        creative.review_status = AdCreative.Review.APPROVED
        creative.save(update_fields=["review_status"])
    return creative


# Only an ad still waiting for, or refused by, review can be edited: an approved
# one would otherwise change after a reviewer looked at it.
EDITABLE_REVIEW_STATES = (AdCreative.Review.PENDING, AdCreative.Review.REJECTED)


def update_creative(owner_account_id: str, creative_id: str, data: dict) -> AdCreative:
    """Edit and resubmit: the creative goes back to review (unless auto-approve)."""
    creative = (
        AdCreative.objects.select_related("ad_set__campaign__advertiser")
        .filter(id=creative_id)
        .first()
    )
    owner = creative and creative.ad_set.campaign.advertiser.owner_account_id
    if creative is None or str(owner) != str(owner_account_id):
        raise TaraAPIError("Ad not found.", code="not_found", http_status_code=404)
    if creative.review_status not in EDITABLE_REVIEW_STATES:
        raise Conflict("An approved ad cannot be edited.", code="conflict")
    media_id = data.get("media_id")
    if media_id and str(media_id) != str(creative.media_id or ""):
        _check_media(owner_account_id, str(media_id))  # remote: before any write
    for key in ("headline", "body", "cta", "link_url"):
        if key in data:
            setattr(creative, key, data[key])
    if "media_id" in data:
        creative.media_id = data["media_id"] or None
    creative.review_status = (
        AdCreative.Review.APPROVED if settings.ADS_AUTO_APPROVE else AdCreative.Review.PENDING
    )
    creative.save()
    return creative


# ---- review (RBAC: ad_reviewer/admin) ---------------------------------------


def review_queue(reviewer_id: str):
    """Pending creatives, oldest first; never the reviewer's own (they cannot decide them)."""
    return (
        AdCreative.objects.filter(review_status=AdCreative.Review.PENDING)
        .exclude(ad_set__campaign__advertiser__owner_account_id=reviewer_id)
        .select_related("ad_set__campaign__advertiser")
        .order_by("created_at")
    )


def review_creative(
    reviewer_id: str, creative_id: str, decision: str, notes: str = ""
) -> AdCreative:
    if decision not in (AdCreative.Review.APPROVED, AdCreative.Review.REJECTED):
        raise TaraAPIError("Invalid decision.", code="validation_error", http_status_code=400)
    creative = (
        AdCreative.objects.select_related("ad_set__campaign__advertiser")
        .filter(id=creative_id)
        .first()
    )
    if creative is None:
        raise TaraAPIError("Creative not found.", code="not_found", http_status_code=404)
    if str(creative.ad_set.campaign.advertiser.owner_account_id) == str(reviewer_id):
        # Separation of duties: holding the role does not let anyone approve their own ads.
        raise TaraAPIError(
            "You cannot review your own ad.", code="permission_denied", http_status_code=403
        )
    with transaction.atomic():
        creative.review_status = decision
        creative.save(update_fields=["review_status"])
        AdReview.objects.create(
            creative=creative, reviewer_id=reviewer_id, decision=decision, notes=notes
        )
        events.emit(
            "ad.review.decided",
            subject_id=str(creative.id),
            payload={"creative_id": str(creative.id), "decision": decision},
            actor_id=str(reviewer_id),
        )
    return creative


# ---- serving ----------------------------------------------------------------


def _freq_key(viewer_id: str, creative_id: str) -> str:
    return f"adfreq:{viewer_id}:{creative_id}"


def _cap_for(ad_set: AdSet) -> int:
    return ad_set.frequency_cap or settings.ADS_DEFAULT_FREQUENCY_CAP


def eligible_creatives(placement: str):
    """Approved creatives in active, in-schedule, in-budget campaigns for a placement.

    The advertiser must be in good standing too (D13, WP 4.11): a suspended,
    unfunded or otherwise non-``active`` billing status never serves, whatever the
    campaign's own state. Anything but the exact ``active`` value fails closed.
    """
    now = timezone.now()
    return (
        AdCreative.objects.select_related("ad_set__campaign")
        .filter(
            review_status=AdCreative.Review.APPROVED,
            ad_set__campaign__advertiser__billing_status=AdvertiserAccount.BILLING_ACTIVE,
            ad_set__placement=placement,
            ad_set__campaign__status=Campaign.Status.ACTIVE,
            ad_set__campaign__spent__lt=F("ad_set__campaign__budget"),
        )
        .filter(
            Q(ad_set__campaign__schedule_start__isnull=True)
            | Q(ad_set__campaign__schedule_start__lte=now),
            Q(ad_set__campaign__schedule_end__isnull=True)
            | Q(ad_set__campaign__schedule_end__gte=now),
        )
        .order_by("-created_at")
    )


def pick_for_viewer(viewer_id: str, placement: str = "feed") -> dict | None:
    """Return one eligible, frequency-uncapped creative for the viewer (or None).

    With serving switched off nothing is picked and no serve token is minted.
    """
    if not settings.ADS_SERVING_ENABLED:
        return None
    for creative in eligible_creatives(placement)[:25]:
        seen = cache.get(_freq_key(viewer_id, str(creative.id)), 0)
        if seen < _cap_for(creative.ad_set):
            return {
                "creative_id": str(creative.id),
                "campaign_id": str(creative.ad_set.campaign_id),
                "headline": creative.headline,
                "body": creative.body,
                "media_id": str(creative.media_id) if creative.media_id else None,
                "cta": creative.cta,
                "link_url": creative.link_url,
                "placement": placement,
                "sponsored": True,
                "token": serve_tokens.issue(viewer_id, creative.id, placement),
            }
    return None


# ---- events + budgeting -----------------------------------------------------


def _debit(campaign: Campaign, amount: Decimal, reason: str) -> None:
    """Charge ``campaign`` (locked by the caller), never past its budget."""
    amount = min(amount, campaign.budget_remaining)
    if amount <= 0:
        return
    campaign.spent = (campaign.spent or Decimal("0")) + amount
    if campaign.spent >= campaign.budget:
        campaign.status = Campaign.Status.COMPLETED
    campaign.save(update_fields=["spent", "status"])
    AdBudgetLedger.objects.create(
        advertiser=campaign.advertiser,
        campaign=campaign,
        amount=amount,
        currency=campaign.currency,
        balance_after=campaign.budget_remaining,
        reason=reason,
    )


AD_EVENT_DEDUPE_SECONDS = 300


def first_in_window(kind: str, creative_id: str, viewer_id: str) -> bool:
    """One billable event per viewer, creative and kind in a window."""
    return cache.add(f"ad-event:{kind}:{creative_id}:{viewer_id}", 1, AD_EVENT_DEDUPE_SECONDS)


def record_event(kind: str, creative_id: str, viewer_id: str) -> None:
    """Record an impression or click (the view layer dedupes via Idempotency-Key)."""
    creative = (
        AdCreative.objects.select_related("ad_set__campaign__advertiser")
        .filter(id=creative_id)
        .first()
    )
    if creative is None:
        raise TaraAPIError("Creative not found.", code="not_found", http_status_code=404)
    ad_set = creative.ad_set
    campaign = ad_set.campaign
    if creative.review_status != AdCreative.Review.APPROVED or (
        campaign.status != Campaign.Status.ACTIVE
    ):
        raise TaraAPIError("This ad is not running.", code="conflict", http_status_code=409)
    bucket = viewer_bucket(viewer_id)
    placement = ad_set.placement

    with transaction.atomic():
        locked = (
            Campaign.objects.select_for_update().select_related("advertiser").get(id=campaign.id)
        )
        # Checked again under the lock: a concurrent event may have spent the
        # last of the budget (or the owner paused it) since the read above.
        # An advertiser whose billing is not ``active`` is never billed either (WP
        # 4.11): an ad rendered before a suspension records no impression or click.
        if (
            locked.status != Campaign.Status.ACTIVE
            or locked.budget_remaining <= 0
            or locked.advertiser.billing_status != AdvertiserAccount.BILLING_ACTIVE
        ):
            raise TaraAPIError("This ad is not running.", code="conflict", http_status_code=409)
        if kind == "impression":
            AdImpressionEvent.objects.create(
                creative=creative, viewer_bucket=bucket, placement=placement
            )
            _debit(locked, ad_set.cpm / Decimal("1000"), "impression")
            key = _freq_key(viewer_id, str(creative.id))
            cache.set(key, (cache.get(key, 0) or 0) + 1, 86_400)
            events.emit(
                "ad.impression.recorded",
                subject_id=str(creative.id),
                payload={
                    "creative_id": str(creative.id),
                    "campaign_id": str(campaign.id),
                    "viewer_bucket": bucket,
                    "placement": placement,
                },
            )
        elif kind == "click":
            AdClickEvent.objects.create(
                creative=creative, viewer_bucket=bucket, placement=placement
            )
            _debit(locked, ad_set.cpc, "click")
            events.emit(
                "ad.click.recorded",
                subject_id=str(creative.id),
                payload={
                    "creative_id": str(creative.id),
                    "campaign_id": str(campaign.id),
                    "viewer_bucket": bucket,
                    "placement": placement,
                },
            )
        else:
            raise TaraAPIError("Invalid event kind.", code="validation_error", http_status_code=400)


def _count_of(event_model) -> Subquery:
    rows = (
        event_model.objects.filter(creative=OuterRef("pk"))
        .order_by()
        .values("creative")
        .annotate(n=Count("id"))
        .values("n")
    )
    return Coalesce(Subquery(rows, output_field=IntegerField()), 0)


def campaign_report(owner_account_id: str, campaign_id: str) -> dict:
    campaign = _own_campaign(owner_account_id, campaign_id)
    impressions = AdImpressionEvent.objects.filter(creative__ad_set__campaign=campaign).count()
    clicks = AdClickEvent.objects.filter(creative__ad_set__campaign=campaign).count()
    ctr = (clicks / impressions) if impressions else 0.0
    # One subquery per counter: joining both event tables would multiply their rows.
    creatives = AdCreative.objects.filter(ad_set__campaign=campaign).annotate(
        impression_count=_count_of(AdImpressionEvent),
        click_count=_count_of(AdClickEvent),
    )
    return {
        "campaign_id": str(campaign.id),
        "status": campaign.status,
        "budget": str(campaign.budget),
        "spent": str(campaign.spent),
        "impressions": impressions,
        "clicks": clicks,
        "ctr": round(ctr, 4),
        "creatives": [
            {
                "id": str(c.id),
                "headline": c.headline,
                "review_status": c.review_status,
                "impressions": c.impression_count,
                "clicks": c.click_count,
            }
            for c in creatives
        ],
    }
