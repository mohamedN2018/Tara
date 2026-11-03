"""Catalogue features: three-state price, currency rules, search, filters, sort, facets."""

import uuid
from decimal import Decimal

import pytest
from django.db import IntegrityError, connection, transaction
from django.urls import reverse

from marketplace import backfill, services
from marketplace.models import BlockedPair, Listing, MarketplaceCategory, OutboxEvent

pytestmark = pytest.mark.django_db


def _acct() -> str:
    return str(uuid.uuid4())


def _live(seller, category, **over) -> Listing:
    data = {
        "category_id": str(category.id),
        "title": over.pop("title", "Item"),
        "description": over.pop("description", ""),
        "currency": over.pop("currency", "EGP"),
        "condition": over.pop("condition", "good"),
        "location": over.pop("location", "Cairo"),
        **over,
    }
    listing = services.create_listing(seller, data)
    services.publish_listing(seller, str(listing.id))
    listing.refresh_from_db()
    return listing


def _ids(resp) -> list[str]:
    assert resp.status_code == 200, resp.content
    return [row["id"] for row in resp.json()["data"]]


# ---- pricing ----------------------------------------------------------------


def _post(client, category, **body):
    return client.post(
        reverse("marketplace:listings"),
        {"category_id": str(category.id), "title": "T", **body},
        format="json",
    )


def test_three_price_states_and_effective_price(client_for, category):
    c = client_for(_acct())
    fixed = _post(c, category, price_type="fixed", price="100", sale_price="80", currency="egp")
    assert fixed.status_code == 201, fixed.content
    body = fixed.json()["data"]
    assert body["price_type"] == "fixed"
    assert body["currency"] == "EGP"  # normalised
    assert Decimal(body["effective_price"]) == Decimal("80")

    nego = _post(c, category, price_type="negotiable")
    assert nego.status_code == 201
    assert nego.json()["data"]["price"] is None
    assert nego.json()["data"]["effective_price"] is None

    free = _post(c, category, price_type="free")
    assert free.status_code == 201
    assert Decimal(free.json()["data"]["price"]) == 0

    # Postgres computes the generated column the same way.
    row = Listing.objects.get(id=fixed.json()["data"]["id"])
    assert row.effective_price == Decimal("80")


def test_old_clients_sending_only_a_price_get_an_inferred_type(client_for, category):
    c = client_for(_acct())
    assert _post(c, category, price="50").json()["data"]["price_type"] == "fixed"
    assert _post(c, category, price="0").json()["data"]["price_type"] == "free"


@pytest.mark.parametrize(
    ("body", "field", "code"),
    [
        ({"price_type": "fixed"}, "price", "price_required"),
        ({"price_type": "fixed", "price": "0"}, "price", "price_required"),
        ({"price_type": "free", "price": "10"}, "price", "free_has_price"),
        ({"price_type": "free", "sale_price": "1"}, "sale_price", "sale_price_not_allowed"),
        ({"price": "100", "sale_price": "100"}, "sale_price", "sale_price_not_below_price"),
        ({"price": "100", "sale_price": "120"}, "sale_price", "sale_price_not_below_price"),
        ({"price_type": "negotiable", "sale_price": "5"}, "sale_price", "sale_without_price"),
        ({"price": "10", "currency": "XYZ"}, "currency", "currency_not_allowed"),
        ({"price": "10.125", "currency": "EGP"}, "price", "too_many_decimals"),
    ],
)
def test_invalid_price_states_are_400(client_for, category, body, field, code):
    resp = _post(client_for(_acct()), category, **body)
    assert resp.status_code == 400, resp.content
    details = resp.json()["error"]["details"]
    assert {"field": field, "code": code} == {k: details[0][k] for k in ("field", "code")}
    assert not Listing.objects.exists()


def test_three_decimal_currencies_keep_their_minor_unit(client_for, category):
    resp = _post(client_for(_acct()), category, price="12.125", currency="KWD")
    assert resp.status_code == 201
    assert Decimal(resp.json()["data"]["price"]) == Decimal("12.125")


def test_negative_and_garbage_prices_are_400(client_for, category):
    c = client_for(_acct())
    assert _post(c, category, price="-1").status_code == 400
    assert _post(c, category, price="abc").status_code == 400


def test_database_checks_reject_bad_prices_written_around_the_service(category):
    listing = services.create_listing(
        _acct(), {"category_id": str(category.id), "title": "x", "price": "100"}
    )
    for bad in (
        {"sale_price": Decimal("150")},
        {"price_type": "free"},
        {"currency": "ZZZ"},
        {"price": Decimal("-5")},
    ):
        with pytest.raises(IntegrityError), transaction.atomic():
            Listing.objects.filter(id=listing.id).update(**bad)


def test_editing_price_revalidates_the_whole_state(client_for, category):
    seller = _acct()
    listing = _live(seller, category, price="100")
    url = reverse("marketplace:listing-detail", args=[listing.id])
    c = client_for(seller)
    assert c.patch(url, {"sale_price": "150"}, format="json").status_code == 400
    ok = c.patch(url, {"sale_price": "70"}, format="json")
    assert ok.status_code == 200
    assert Decimal(ok.json()["data"]["effective_price"]) == 70
    free = c.patch(url, {"price_type": "free"}, format="json")
    assert free.status_code == 200
    assert Decimal(free.json()["data"]["price"]) == 0
    assert free.json()["data"]["sale_price"] is None
    event = OutboxEvent.objects.filter(event_type="listing.updated").last()
    assert "price_type" in event.payload["payload"]["changed"]


def test_removed_listing_cannot_be_edited(client_for, category):
    seller = _acct()
    listing = _live(seller, category, price="10")
    services.apply_moderation(str(listing.id), "remove")
    resp = client_for(seller).patch(
        reverse("marketplace:listing-detail", args=[listing.id]), {"title": "new"}, format="json"
    )
    assert resp.status_code == 409


# ---- data migration (4.3) ---------------------------------------------------


def test_zero_prices_become_unconfirmed_no_price(category):
    listing = services.create_listing(
        _acct(), {"category_id": str(category.id), "title": "x", "price": "5"}
    )
    # What the old schema allowed: fixed with price 0. Bypass the checks to fake it.
    with connection.cursor() as cur:
        cur.execute("SET CONSTRAINTS ALL IMMEDIATE")  # flush deferred FK checks first
        cur.execute("ALTER TABLE listing DROP CONSTRAINT listing_price_type_valid")
        cur.execute(
            "UPDATE listing SET price = 0, price_type = 'fixed' WHERE id = %s", [listing.id]
        )
    assert backfill.classify_zero_price_listings(Listing) == 1
    assert backfill.classify_zero_price_listings(Listing) == 0  # idempotent
    listing.refresh_from_db()
    assert (listing.price, listing.price_type, listing.price_unconfirmed) == (
        None,
        "negotiable",
        True,
    )


def test_free_text_currencies_are_mapped_or_flagged(category):
    seller = _acct()
    a = services.create_listing(
        seller, {"category_id": str(category.id), "title": "a", "price": "5"}
    )
    b = services.create_listing(
        seller, {"category_id": str(category.id), "title": "b", "price": "5"}
    )
    c = services.create_listing(
        seller, {"category_id": str(category.id), "title": "c", "price": "5"}
    )
    with connection.cursor() as cur:
        cur.execute("SET CONSTRAINTS ALL IMMEDIATE")  # flush deferred FK checks first
        cur.execute("ALTER TABLE listing DROP CONSTRAINT listing_currency_allowed")
        cur.execute("UPDATE listing SET currency = 'egp' WHERE id = %s", [a.id])
        cur.execute("UPDATE listing SET currency = 'LE' WHERE id = %s", [b.id])
        cur.execute("UPDATE listing SET currency = '??' WHERE id = %s", [c.id])
    assert backfill.normalise_currencies(Listing) == (2, 1)
    for row, currency, flagged in ((a, "EGP", False), (b, "EGP", False), (c, "USD", True)):
        row.refresh_from_db()
        assert (row.currency, row.currency_unconfirmed) == (currency, flagged)


def test_seller_edit_clears_the_unconfirmed_price_flag(client_for, category):
    seller = _acct()
    listing = _live(seller, category, price_type="negotiable")
    Listing.objects.filter(id=listing.id).update(price_unconfirmed=True)
    resp = client_for(seller).patch(
        reverse("marketplace:listing-detail", args=[listing.id]),
        {"price_type": "free"},
        format="json",
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["price_unconfirmed"] is False


# ---- query validation -------------------------------------------------------


@pytest.mark.parametrize(
    "params",
    [
        {"min_price": "abc"},
        {"max_price": "-1"},
        {"min_price": "10", "max_price": "5"},
        {"condition": "broken"},
        {"availability": "gone"},
        {"price_type": "auction"},
        {"currency": "XYZ"},
        {"sort": "random"},
        {"limit": "0"},
        {"limit": "500"},
        {"cursor": "not-a-cursor"},
        {"q": "x" * 101},
    ],
)
def test_bad_query_parameters_are_400_never_500(client_for, category, params):
    resp = client_for(_acct()).get(reverse("marketplace:listings"), params)
    assert resp.status_code == 400, resp.content
    resp = client_for(_acct()).get(reverse("marketplace:facets"), params)
    assert resp.status_code in (200, 400)  # facets ignore paging params


def test_empty_values_mean_no_filter_and_old_names_are_aliases(client_for, category):
    seller = _acct()
    cheap = _live(seller, category, price="10")
    pricey = _live(seller, category, price="999")
    c = client_for(_acct())
    assert set(_ids(c.get(reverse("marketplace:listings"), {"min_price": ""}))) == {
        str(cheap.id),
        str(pricey.id),
    }
    assert _ids(c.get(reverse("marketplace:listings"), {"price_max": "100"})) == [str(cheap.id)]


# ---- search -----------------------------------------------------------------


def test_arabic_search_is_normalised(client_for, category):
    seller = _acct()
    hit = _live(seller, category, title="شقة في الإسكندرية", price="100")
    _live(seller, category, title="سيارة", price="100")
    c = client_for(_acct())
    assert _ids(c.get(reverse("marketplace:listings"), {"q": "اسكندريه"})) == [str(hit.id)]
    assert _ids(c.get(reverse("marketplace:listings"), {"q": "الاسكندرية"})) == [str(hit.id)]


def test_search_uses_the_trigram_index(category):
    _live(_acct(), category, title="bike", price="1")
    # The service filters with a case-sensitive LIKE on the normalised column...
    sql = str(services.search(_acct(), {"q": "Bike"}).query)
    assert '"listing"."search_text"::text LIKE %bike%' in sql, sql
    # ...which the GIN trigram index serves (icontains' UPPER() could not).
    qs = Listing.objects.filter(search_text__contains="bike")
    with connection.cursor() as cur:
        cur.execute("SET LOCAL enable_seqscan = off")
        query, params = qs.query.sql_with_params()
        cur.execute(f"EXPLAIN {query}", params)
        plan = "\n".join(r[0] for r in cur.fetchall())
    assert "listing_search_trgm" in plan, plan


def test_filters_condition_price_type_availability_location(client_for, category):
    seller = _acct()
    new = _live(seller, category, condition="new", price="10", location="Giza")
    free = _live(seller, category, condition="fair", price_type="free", location="Cairo")
    sold = _live(seller, category, condition="new", price="10", location="Giza")
    services.transition(seller, str(sold.id), "mark_sold")
    c = client_for(_acct())
    url = reverse("marketplace:listings")
    assert _ids(c.get(url, {"condition": "new"})) == [str(new.id)]  # sold hidden by default
    assert set(_ids(c.get(url, {"condition": "new", "availability": "available,sold"}))) == {
        str(new.id),
        str(sold.id),
    }
    assert _ids(c.get(url, {"price_type": "free"})) == [str(free.id)]
    assert _ids(c.get(url, {"location": "giz"})) == [str(new.id)]


def test_category_filter_includes_subcategories(client_for, category):
    phones = MarketplaceCategory.objects.create(slug="phones", name="Phones", parent=category)
    seller = _acct()
    in_child = _live(seller, phones, price="5")
    in_parent = _live(seller, category, price="5")
    c = client_for(_acct())
    url = reverse("marketplace:listings")
    assert set(_ids(c.get(url, {"category": "electronics"}))) == {
        str(in_child.id),
        str(in_parent.id),
    }
    assert _ids(c.get(url, {"category": "phones"})) == [str(in_child.id)]
    assert _ids(c.get(url, {"category": "unknown-slug"})) == []


def test_price_range_uses_the_effective_price(client_for, category):
    seller = _acct()
    on_sale = _live(seller, category, price="200", sale_price="90")
    _live(seller, category, price="150")
    _live(seller, category, price_type="negotiable")  # no price: never in a range
    resp = client_for(_acct()).get(
        reverse("marketplace:listings"), {"min_price": "50", "max_price": "100"}
    )
    assert _ids(resp) == [str(on_sale.id)]


def _walk(client, params) -> list[str]:
    seen, cursor = [], None
    for _ in range(100):
        query = dict(params, **({"cursor": cursor} if cursor else {}))
        body = client.get(reverse("marketplace:listings"), query).json()
        seen += [row["id"] for row in body["data"]]
        cursor = body["page"]["next_cursor"]
        if not body["page"]["has_more"]:
            return seen
    raise AssertionError("pagination did not terminate")


@pytest.mark.parametrize("sort", ["price_asc", "price_desc"])
def test_price_sort_pages_unpriced_last_without_repeats(client_for, category, sort):
    seller = _acct()
    priced = {}
    for i, (price, sale) in enumerate([("50", None), ("30", None), ("90", "20"), ("30", None)]):
        extra = {"sale_price": sale} if sale else {}
        priced[str(_live(seller, category, title=f"p{i}", price=price, **extra).id)] = Decimal(
            sale or price
        )
    free = _live(seller, category, price_type="free")
    unpriced = {str(_live(seller, category, price_type="negotiable").id) for _ in range(7)}

    seen = _walk(client_for(_acct()), {"sort": sort, "limit": 3})
    assert len(seen) == len(set(seen)) == len(priced) + 1 + len(unpriced)
    assert set(seen[-len(unpriced) :]) == unpriced  # "no price" last in both directions
    head = seen[: -len(unpriced)]
    values = [Decimal(0) if i == str(free.id) else priced[i] for i in head]
    assert values == sorted(values, reverse=(sort == "price_desc"))


def test_newest_sort_pages_without_repeats(client_for, category):
    seller = _acct()
    made = [str(_live(seller, category, title=f"n{i}", price="1").id) for i in range(7)]
    seen = _walk(client_for(_acct()), {"limit": 2})
    assert seen == list(reversed(made))


def test_cursor_from_another_sort_is_rejected(client_for, category):
    seller = _acct()
    for _ in range(3):
        _live(seller, category, price="1")
    c = client_for(_acct())
    cursor = c.get(reverse("marketplace:listings"), {"limit": 1}).json()["page"]["next_cursor"]
    resp = c.get(
        reverse("marketplace:listings"), {"limit": 1, "sort": "price_asc", "cursor": cursor}
    )
    assert resp.status_code == 400


# ---- facets -----------------------------------------------------------------


def test_facets_exclude_their_own_filter_and_blocked_sellers(client_for, category):
    other = MarketplaceCategory.objects.create(slug="books", name="Books")
    seller, blocked_seller, viewer = _acct(), _acct(), _acct()
    _live(seller, category, condition="new", price="10")
    _live(seller, category, condition="good", price="10")
    _live(seller, other, condition="new", price_type="free")
    _live(blocked_seller, other, condition="new", price="10")
    BlockedPair.objects.create(blocker_id=viewer, blocked_id=blocked_seller)

    resp = client_for(viewer).get(
        reverse("marketplace:facets"), {"category": "electronics", "condition": "new"}
    )
    assert resp.status_code == 200
    f = resp.json()["data"]
    assert f["total"] == 1
    # Category counts ignore the category filter but keep condition=new.
    assert {c["slug"]: c["count"] for c in f["category"]} == {"electronics": 1, "books": 1}
    # Condition counts ignore the condition filter but keep the category.
    assert {c["value"]: c["count"] for c in f["condition"]} == {"new": 1, "good": 1}
    assert {c["value"]: c["count"] for c in f["availability"]} == {"available": 1}
