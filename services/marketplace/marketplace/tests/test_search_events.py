"""What search learns from marketplace (roadmap 1.15): every ``listing.*``
lifecycle event carries the listing's searchable state; the backfill export
lists active listings only; the normaliser is the shared one."""

import time
import uuid

import jwt
import pytest
from django.conf import settings
from django.urls import reverse
from rest_framework.test import APIClient

from marketplace import services
from marketplace.models import OutboxEvent
from marketplace.text import normalise, search_text
from tara_common.text import normalize_ar

pytestmark = pytest.mark.django_db

SNAPSHOT = {
    "status",
    "seller_id",
    "title",
    "category",
    "category_name",
    "price_type",
    "price",
    "sale_price",
    "effective_price",
    "currency",
    "condition",
    "location",
    "cover_media_id",
    "created_at",
}


def _acct() -> str:
    return str(uuid.uuid4())


def _create(seller, category, **over):
    data = {
        "category_id": str(category.id),
        "title": over.get("title", "كنبة"),
        "description": "",
        "price": over.get("price", "100.00"),
        "currency": "EGP",
        "condition": "good",
        "location": "الإسكندرية",
        "media_ids": [],
    }
    return services.create_listing(seller, data)


def _payloads(event_type):
    return [
        e.payload["payload"]
        for e in OutboxEvent.objects.filter(event_type=event_type).order_by("created_at")
    ]


def test_every_lifecycle_event_carries_the_searchable_state(category):
    seller = _acct()
    listing = _create(seller, category)
    services.publish_listing(seller, str(listing.id))
    services.update_listing(seller, str(listing.id), {"title": "كنبة جديدة", "price": "80.00"})
    services.transition(seller, str(listing.id), "mark_sold")

    (created,) = _payloads("listing.created")
    assert SNAPSHOT <= set(created) and created["status"] == "draft"
    published, sold = _payloads("listing.status.changed")
    assert published["status"] == "active" and sold["status"] == "sold"
    (updated,) = _payloads("listing.updated")
    assert SNAPSHOT <= set(updated)
    assert updated["title"] == "كنبة جديدة" and updated["effective_price"] == "80.00"
    assert updated["location"] == "الإسكندرية" and updated["seller_id"] == seller
    assert updated["category"] == category.slug and updated["category_name"] == category.name


def _internal(audience="marketplace-internal") -> APIClient:
    now = int(time.time())
    token = jwt.encode(
        {"iss": "search", "aud": audience, "iat": now, "exp": now + 30},
        settings.TARA_INTERNAL_JWT_SECRET,
        algorithm="HS256",
    )
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


def test_export_lists_active_listings_only(category):
    seller = _acct()
    active = _create(seller, category, title="lamp")
    services.publish_listing(seller, str(active.id))
    _create(seller, category, title="draft lamp")
    sold = _create(seller, category, title="sold lamp")
    services.publish_listing(seller, str(sold.id))
    services.transition(seller, str(sold.id), "mark_sold")

    body = _internal().get(reverse("search-export-listings")).json()["data"]
    assert [i["id"] for i in body["items"]] == [str(active.id)]
    assert body["items"][0]["payload"]["status"] == "active"
    assert body["next"] is None and body["as_of"]
    assert APIClient().get(reverse("search-export-listings")).status_code == 401
    assert _internal("post-internal").get(reverse("search-export-listings")).status_code == 401


def test_listing_search_uses_the_shared_normaliser():
    assert normalise is normalize_ar
    assert search_text("الإسكندرية", "") == "ال" + normalize_ar("اسكندريه")
