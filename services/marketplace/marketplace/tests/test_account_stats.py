"""Admin's user console (8.6): one seller's listings, on the internal stats API."""

import uuid

import pytest

from marketplace.models import Listing, MarketplaceCategory
from tara_common.auth import mint_internal_token

pytestmark = pytest.mark.django_db


def test_counts_the_sellers_listings_but_not_archived_ones(client):
    category = MarketplaceCategory.objects.create(slug="stats-cat", name="Stats")
    seller = uuid.uuid4()
    for status in (Listing.Status.ACTIVE, Listing.Status.DRAFT, Listing.Status.ARCHIVED):
        Listing.objects.create(seller_id=seller, category=category, title="t", status=status)
    Listing.objects.create(seller_id=uuid.uuid4(), category=category, title="t")
    url = f"/internal/v1/stats/accounts/{seller}/"
    assert client.get(url).status_code == 401
    token = mint_internal_token(issuer="admin", audience="marketplace-internal")
    resp = client.get(url, HTTP_AUTHORIZATION=f"Bearer {token}")
    assert resp.json()["data"]["stats"] == {"listings": 2}
