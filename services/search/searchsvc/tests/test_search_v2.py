"""Search v2 (roadmap 1.15): Arabic matching, keyset pages, permissions, event order,
recent searches, suggestions and trending."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest import mock

import pytest
from django.urls import reverse
from django.utils import timezone

from searchsvc import handlers
from searchsvc.models import BlockedPair, DocState, PublicPostHashtag, RecentSearch, SearchDocument
from tara_common.text import normalize_ar, normalize_key
from tara_events.envelope import EventEnvelope

pytestmark = pytest.mark.django_db

T0 = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)


def acct() -> str:
    return str(uuid.uuid4())


def ev(event_type, subject, payload, at=0):
    return EventEnvelope(
        event_type=event_type,
        subject_id=str(subject),
        producer="test",
        occurred_at=(T0 + timedelta(seconds=at)).isoformat(),
        payload=payload,
    )


def person(account_id, display_name, *, handle=None, at=0, **extra):
    handle = handle or f"h{uuid.uuid4().hex[:8]}"
    payload = {"handle": handle, "display_name": display_name, "visibility": "public", **extra}
    handlers.on_profile_updated(ev("profile.updated", account_id, payload, at))


def public_post(post_id, excerpt, *, author=None, at=0, **extra):
    payload = {
        "post_id": post_id,
        "author_id": author or acct(),
        "audience": "public",
        "excerpt": excerpt,
        "hashtags": [],
        "type": "text",
        "media_ids": [],
        "created_at": (T0 + timedelta(seconds=at)).isoformat(),
        **extra,
    }
    handlers.on_post_created(ev("post.created", post_id, payload, at))


def group(group_id, name, privacy="public", *, at=0, event="group.created", **extra):
    payload = {
        "group_id": group_id,
        "handle": name.lower().replace(" ", "-"),
        "name": name,
        "privacy": privacy,
        "category": "community",
        **extra,
    }
    fn = {
        "group.created": handlers.on_group_created,
        "group.updated": handlers.on_group_updated,
        "group.deleted": handlers.on_group_deleted,
    }[event]
    fn(ev(event, group_id, payload, at))


def listing(listing_id, title, *, status="active", seller=None, at=0, **extra):
    payload = {
        "listing_id": listing_id,
        "seller_id": seller or acct(),
        "status": status,
        "title": title,
        "category": "furniture",
        "category_name": "Furniture",
        "price": "100.0000",
        "sale_price": None,
        "effective_price": "100.0000",
        "price_type": "fixed",
        "currency": "EGP",
        "condition": "good",
        "location": "Alexandria",
        "cover_media_id": None,
        "created_at": (T0 + timedelta(seconds=at)).isoformat(),
        **extra,
    }
    handlers.on_listing_updated(ev("listing.updated", listing_id, payload, at))


@pytest.fixture
def viewer():
    return acct()


@pytest.fixture
def api(client_for, viewer):
    return client_for(viewer)


@pytest.fixture(autouse=True)
def no_graph():
    """Graph is mocked per test; by default it is unavailable (decoration only)."""
    with mock.patch("searchsvc.clients.relationships", return_value={}) as m:
        yield m


def search(api, q, **params):
    resp = api.get(reverse("searchsvc:search"), {"q": q, **params})
    assert resp.status_code == 200, resp.content
    return resp.json()


def ids(body):
    return [r["id"] for r in body["data"]["results"]]


# ---- the shared normaliser -------------------------------------------------------


def test_normaliser_folds_arabic_variants_digits_and_marks():
    assert normalize_ar("الإسكندرية") == normalize_ar("الاسكندريه") == "الاسكندريه"
    assert normalize_ar("أَحْمَد") == normalize_ar("احمد") == "احمد"
    assert normalize_ar("مستشفى") == normalize_ar("مستشفي")
    assert normalize_ar("سؤال") == "سوال"
    assert normalize_ar("كـــتاب") == "كتاب"
    assert normalize_ar("٢٠٢٦ ۱۲") == "2026 12"
    assert normalize_ar("ﻣﺤﻤﺪ") == "محمد"  # presentation forms (NFKC)
    assert normalize_ar("مح‌مد‏") == "محمد"  # zero-width and bidi marks
    assert normalize_ar("ی ک") == "ي ك"  # Persian yeh and keheh
    assert normalize_ar("  Hello\tWORLD ") == "hello world"
    assert normalize_ar(None) == ""


def test_key_variant_keeps_programming_language_punctuation():
    assert normalize_key("C++") == "c++"
    assert normalize_key("C#") == "c#"
    assert normalize_key("Node.js!") == "node.js"
    assert len({normalize_key(k) for k in ("C", "C#", "C++")}) == 3


# ---- Arabic matching and partial matching ---------------------------------------------


def test_spelling_variants_meet(api):
    public_post("p-alex", "رحلة إلى الإسكندرية هذا الصيف")
    a = acct()
    person(a, "أحمد علي")
    listing("l-alex", "كنبة في الإسكندرية")

    assert "p-alex" in ids(search(api, "اسكندريه"))
    assert "l-alex" in ids(search(api, "اسكندريه", type="marketplace"))
    assert ids(search(api, "احمد", type="people")) == [a]


def test_partial_and_prefix_matching(api):
    a, b = acct(), acct()
    person(a, "Nadia Star", handle="nadia")
    person(b, "Mohamed Nabil", handle="mnabil")

    assert ids(search(api, "nad", type="people")) == [a]
    assert ids(search(api, "nab", type="people")) == [b]  # a word prefix
    assert ids(search(api, "na", type="people"))  # two characters: prefix only
    assert set(ids(search(api, "nabil star", type="people"))) <= {a, b}


def test_misspelling_still_matches(api):
    a = acct()
    person(a, "Alexandria Explorer")
    assert a in ids(search(api, "alexandira", type="people"))


def test_exact_name_ranks_first(api):
    exact, other = acct(), acct()
    person(other, "Mohamed Ahmed")
    person(exact, "Ahmed")
    assert ids(search(api, "ahmed", type="people"))[0] == exact


# ---- keyset pages ------------------------------------------------------------------------


@pytest.mark.parametrize("sort", ["relevance", "recent"])
def test_pages_never_repeat_or_skip(api, sort):
    for i in range(45):
        public_post(f"p{i:02d}", "same words everywhere", at=i % 3)  # many exact ties
    seen, cursor, pages = [], None, 0
    while True:
        params = {"type": "posts", "limit": 10, "sort": sort}
        if cursor:
            params["cursor"] = cursor
        body = search(api, "same words", **params)
        seen += ids(body)
        pages += 1
        cursor = body["page"]["next_cursor"]
        assert body["page"]["has_more"] is bool(cursor)
        if not cursor:
            break
    assert pages == 5
    assert len(seen) == len(set(seen)) == 45


def test_recent_sort_is_newest_first(api):
    public_post("old", "garden party", at=0)
    public_post("new", "garden party", at=50)
    assert ids(search(api, "garden party", type="posts", sort="recent")) == ["new", "old"]


def test_bad_cursor_is_400(api):
    public_post("p1", "hello world")
    resp = api.get(reverse("searchsvc:search"), {"q": "hello", "cursor": "not-a-cursor"})
    assert resp.status_code == 400
    body = search(api, "hello", type="posts", limit=1)
    assert body["page"]["next_cursor"] is None


def test_cursor_from_another_sort_is_400(api):
    for i in range(3):
        public_post(f"c{i}", "cursor test")
    cursor = search(api, "cursor test", limit=1)["page"]["next_cursor"]
    resp = api.get(
        reverse("searchsvc:search"), {"q": "cursor test", "sort": "recent", "cursor": cursor}
    )
    assert resp.status_code == 400


# ---- tabs and filters -------------------------------------------------------------------


def test_tabs_and_types_offered(api):
    body = search(api, "x")
    assert body["data"]["types"] == [
        "all",
        "people",
        "posts",
        "photos",
        "pages",
        "groups",
        "marketplace",
        "events",
        "hashtags",
    ]
    for missing in ("videos", "reels", "companies", "jobs"):
        assert missing not in body["data"]["types"]
        assert search(api, "x", type=missing)["data"]["type"] == "all"


def test_photos_tab_is_image_posts_with_media(api):
    public_post("text", "sunset beach")
    public_post("photo", "sunset beach", type="image", media_ids=[str(uuid.uuid4())])
    assert ids(search(api, "sunset", type="photos")) == ["photo"]
    assert set(ids(search(api, "sunset", type="posts"))) == {"text", "photo"}
    hit = search(api, "sunset", type="photos")["data"]["results"][0]
    assert hit["post_type"] == "image" and len(hit["media_ids"]) == 1


def test_date_category_and_location_filters(api):
    public_post("recent", "market day", created_at=timezone.now().isoformat())
    public_post(
        "ancient", "market day", created_at=(timezone.now() - timedelta(days=60)).isoformat()
    )
    assert ids(search(api, "market day", type="posts", date="week")) == ["recent"]
    today = timezone.now().date()
    assert ids(
        search(
            api,
            "market day",
            type="posts",
            **{"from": str(today - timedelta(days=90)), "to": str(today - timedelta(days=30))},
        )
    ) == ["ancient"]

    listing("cairo", "wooden chair", location="القاهرة")
    listing("alex", "wooden chair", location="الإسكندرية", category="chairs")
    assert ids(search(api, "chair", type="marketplace", location="اسكندريه")) == ["alex"]
    assert ids(search(api, "chair", type="marketplace", category="chairs")) == ["alex"]


def test_listing_result_carries_card_fields(api):
    seller = acct()
    listing("l1", "Red bike", seller=seller, price="250.0000", currency="USD")
    hit = search(api, "bike", type="marketplace")["data"]["results"][0]
    assert hit["seller_id"] == seller
    assert hit["price"] == "250.0000" and hit["currency"] == "USD"
    assert hit["location"] == "Alexandria"
    assert hit["category"] == {"slug": "furniture", "name": "Furniture"}


def test_only_active_listings_are_found(api):
    for status in ("draft", "pending_review", "reserved", "sold", "removed", "archived"):
        listing(f"l-{status}", "vintage lamp", status=status)
    listing("l-active", "vintage lamp")
    assert ids(search(api, "lamp", type="marketplace")) == ["l-active"]


# ---- permissions -------------------------------------------------------------------------


def test_blocked_accounts_are_excluded_both_ways(api, viewer):
    blocker, blocked, free = acct(), acct(), acct()
    for a in (blocker, blocked, free):
        person(a, "Sameer Khan")
        public_post(f"post-{a}", "sameer khan travel notes", author=a)
        listing(f"listing-{a}", "sameer khan guitar", seller=a)
    BlockedPair.objects.create(blocker_id=blocker, blocked_id=viewer)
    BlockedPair.objects.create(blocker_id=viewer, blocked_id=blocked)

    owners = {r["owner_id"] for r in search(api, "sameer khan", limit=50)["data"]["results"]}
    assert owners == {free}
    suggest = api.get(reverse("searchsvc:suggest"), {"q": "sameer"}).json()["data"]["results"]
    assert {r["id"] for r in suggest} == {free}


def test_non_public_profiles_and_private_fields_are_not_returned(api):
    shown, hidden, friends_only = acct(), acct(), acct()
    person(shown, "Laila Hassan")  # no city sent: its field privacy is not public
    person(hidden, "Laila Hassan", visibility="private")
    person(friends_only, "Laila Hassan", visibility="friends_only")
    hits = search(api, "laila", type="people")["data"]["results"]
    assert [h["id"] for h in hits] == [shown]
    assert hits[0]["city"] is None
    assert set(hits[0]) >= {"handle", "display_name", "avatar_media_id", "relationship"}
    assert "visibility" not in hits[0] and "email" not in hits[0]


def test_public_city_is_searchable_by_location(api):
    a, b = acct(), acct()
    person(a, "Omar Said", city="الإسكندرية")
    person(b, "Omar Said")
    assert ids(search(api, "omar", type="people", location="اسكندريه")) == [a]


def test_hidden_groups_never_appear_and_private_ones_show_name_and_description_only(api):
    group("g-pub", "Chess Club")
    group(
        "g-priv",
        "Chess Masters",
        "private",
        description="Strong players only",
        member_ids=["x"],
        rules="secret rules",
    )
    group("g-hid", "Chess Secret", "hidden")
    hits = {h["id"]: h for h in search(api, "chess", type="groups")["data"]["results"]}
    assert set(hits) == {"g-pub", "g-priv"}
    priv = hits["g-priv"]
    assert priv["privacy"] == "private" and priv["description"] == "Strong players only"
    assert "member_ids" not in priv and "rules" not in priv


def test_group_turned_hidden_leaves_search(api):
    group("g1", "Book Lovers")
    assert ids(search(api, "book lovers", type="groups")) == ["g1"]
    group("g1", "Book Lovers", "hidden", at=5, event="group.updated")
    assert ids(search(api, "book lovers", type="groups")) == []
    assert not SearchDocument.objects.filter(doc_type="group").exists()


def test_people_results_carry_relationship_and_permitted_mutuals(api, viewer, no_graph):
    friend, stranger, hidden_lists = acct(), acct(), acct()
    for a in (friend, stranger, hidden_lists):
        person(a, "Karim Adel")
    person(viewer, "Karim Adel")
    no_graph.return_value = {
        friend: {"state": "friends", "following": True, "request_id": None, "mutual_count": 3},
        stranger: {
            "state": "pending_in",
            "following": False,
            "request_id": "r1",
            "mutual_count": 0,
        },
        hidden_lists: {
            "state": "none",
            "following": False,
            "request_id": None,
            "mutual_count": None,
        },
    }
    hits = {h["id"]: h for h in search(api, "karim", type="people")["data"]["results"]}
    assert hits[friend]["relationship"]["state"] == "friends"
    assert hits[friend]["mutual_count"] == 3
    assert hits[stranger]["relationship"] == {
        "state": "pending_in",
        "following": False,
        "request_id": "r1",
    }
    assert hits[hidden_lists]["mutual_count"] is None
    assert hits[viewer]["relationship"]["state"] == "self"
    users = no_graph.call_args.args[1]
    assert viewer not in users and set(users) == {friend, stranger, hidden_lists}


def test_graph_down_returns_results_without_relationships(api):
    a = acct()
    person(a, "Huda Nour")  # the autouse fixture answers like an unavailable graph
    hit = search(api, "huda", type="people")["data"]["results"][0]
    assert hit["relationship"] is None and hit["mutual_count"] is None


def test_graph_client_degrades_to_empty(settings):
    from searchsvc import clients

    with mock.patch("searchsvc.clients.requests.post", side_effect=ConnectionError("down")):
        assert clients.relationships(acct(), [acct()], []) == {}


def test_page_results_carry_follow_state(api, no_graph):
    handlers.on_page_created(
        ev(
            "page.created",
            "pg1",
            {"handle": "bakery", "name": "Nile Bakery", "owner": acct(), "category": "Food"},
        )
    )
    no_graph.return_value = {"pg1": {"following": True, "followers_count": 12}}
    hit = search(api, "bakery", type="pages")["data"]["results"][0]
    assert hit["followers_count"] == 12 and hit["following"] is True
    assert hit["category"] == "Food"
    assert no_graph.call_args.args[2] == ["pg1"]


# ---- event order -------------------------------------------------------------------------


def test_suspended_group_leaves_search(api):
    group("g1", "Gardeners")
    group("g1", "Gardeners", at=5, event="group.deleted", status="suspended", by="moderation")
    assert ids(search(api, "gardeners", type="groups")) == []
    group("g1", "Gardeners", at=9, event="group.updated", status="active")  # appeal approved
    assert ids(search(api, "gardeners", type="groups")) == ["g1"]


def test_stale_group_update_cannot_revive_a_deleted_group(api):
    group("g1", "Runners", at=0)
    group("g1", "Runners", at=10, event="group.deleted")
    group("g1", "Runners", at=5, event="group.updated")  # retried, older than the delete
    assert ids(search(api, "runners", type="groups")) == []
    assert DocState.objects.get(doc_type="group", doc_id="g1").live is False


def test_stale_public_snapshot_cannot_undo_a_hidden_change(api):
    group("g1", "Painters", at=0)
    group("g1", "Painters", "hidden", at=10, event="group.updated")
    group("g1", "Painters", "public", at=5, event="group.updated")
    assert ids(search(api, "painters", type="groups")) == []


def test_delete_wins_a_tie(api):
    group("g1", "Cyclists", at=3, event="group.deleted")
    group("g1", "Cyclists", at=3, event="group.updated")
    assert ids(search(api, "cyclists", type="groups")) == []


def test_stale_profile_event_cannot_republish_a_private_profile(api):
    a = acct()
    person(a, "Rana Saleh", at=0)
    handlers.on_profile_updated(
        ev(
            "profile.updated",
            a,
            {"handle": "rana", "display_name": "Rana Saleh", "visibility": "private"},
            at=10,
        )
    )
    person(a, "Rana Saleh", at=5)
    assert ids(search(api, "rana", type="people")) == []


def test_stale_listing_event_cannot_relist_a_sold_listing(api):
    listing("l1", "Blue sofa", at=0)
    listing("l1", "Blue sofa", status="sold", at=10)
    listing("l1", "Blue sofa", at=5)
    assert ids(search(api, "sofa", type="marketplace")) == []


def test_stale_page_update_cannot_bring_back_a_suspended_page(api):
    owner = acct()
    payload = {"handle": "shop", "name": "Corner Shop", "owner": owner, "category": "Retail"}
    handlers.on_page_created(ev("page.created", "pg", {**payload, "status": "published"}, 0))
    handlers.on_page_updated(ev("page.updated", "pg", {**payload, "status": "suspended"}, 10))
    handlers.on_page_updated(ev("page.updated", "pg", {**payload, "status": "published"}, 5))
    assert ids(search(api, "corner shop", type="pages")) == []


def test_old_listing_updated_payload_is_ignored():
    listing("l1", "Desk")
    handlers.on_listing_updated(
        ev("listing.updated", "l1", {"listing_id": "l1", "changed": ["title"]}, 9)
    )
    assert SearchDocument.objects.get(doc_type="listing").title == "Desk"


def _state(**overrides):
    return {
        "gathering_id": "e1",
        "indexable": True,
        "title": "Ramadan Iftar",
        "description": "Community iftar",
        "location_type": "place",
        "location": "حديقة الأزهر",
        "starts_at": (T0 + timedelta(days=3)).isoformat(),
        "ends_at": None,
        "host_id": acct(),
        "cover_media_id": None,
        "going_count": 4,
        "interested_count": 2,
        "status": "scheduled",
        "updated_at": T0.isoformat(),
        **overrides,
    }


def test_events_follow_posts_current_state(api):
    with mock.patch("searchsvc.clients.gathering_state", return_value=_state()):
        handlers.on_gathering_created(ev("gathering.created", "e1", {"gathering_id": "e1"}))
    hit = search(api, "iftar", type="events")["data"]["results"][0]
    assert hit["id"] == "e1" and hit["going_count"] == 4 and hit["location"] == "حديقة الأزهر"
    assert ids(search(api, "iftar", type="events", location="الازهر")) == ["e1"]

    later = (T0 + timedelta(minutes=5)).isoformat()
    with mock.patch(
        "searchsvc.clients.gathering_state", return_value=_state(indexable=False, updated_at=later)
    ):
        handlers.on_gathering_updated(ev("gathering.updated", "e1", {"gathering_id": "e1"}, 300))
    assert ids(search(api, "iftar", type="events")) == []

    # An older read (a slow handler) cannot put it back.
    with mock.patch("searchsvc.clients.gathering_state", return_value=_state()):
        handlers.on_gathering_updated(ev("gathering.updated", "e1", {"gathering_id": "e1"}, 1))
    assert ids(search(api, "iftar", type="events")) == []


def test_deleted_event_leaves_search_and_rsvp_counts_update(api):
    with mock.patch("searchsvc.clients.gathering_state", return_value=_state()):
        handlers.on_gathering_created(ev("gathering.created", "e1", {"gathering_id": "e1"}))
    handlers.on_gathering_rsvp(
        ev(
            "gathering.rsvp",
            "e1",
            {"gathering_id": "e1", "going_count": 9, "interested_count": 1},
            60,
        )
    )
    handlers.on_gathering_rsvp(
        ev(
            "gathering.rsvp",
            "e1",
            {"gathering_id": "e1", "going_count": 7, "interested_count": 1},
            30,
        )
    )  # older
    assert search(api, "iftar", type="events")["data"]["results"][0]["going_count"] == 9
    handlers.on_gathering_deleted(ev("gathering.deleted", "e1", {"gathering_id": "e1"}, 120))
    assert ids(search(api, "iftar", type="events")) == []


def test_event_state_unavailable_is_retried():
    from searchsvc import clients

    with mock.patch("searchsvc.clients.requests.get", side_effect=ConnectionError("down")):
        with pytest.raises(clients.Unavailable):
            handlers.on_gathering_created(ev("gathering.created", "e9", {"gathering_id": "e9"}))
    assert not SearchDocument.objects.exists()


# ---- suggestions ------------------------------------------------------------------------


def test_suggest_is_bounded_and_one_query(api, viewer, django_assert_max_num_queries):
    for i in range(20):
        person(acct(), f"Yasmin {i}")
    group("g1", "Yasmin fans")
    public_post("p1", "yasmin")  # posts are not suggested
    BlockedPair.objects.create(blocker_id=acct(), blocked_id=viewer)
    with django_assert_max_num_queries(1):
        resp = api.get(reverse("searchsvc:suggest"), {"q": "yasmin"})
    hits = resp.json()["data"]["results"]
    assert len(hits) == 8
    assert {h["type"] for h in hits} <= {"user", "page", "group", "hashtag"}


def test_suggest_with_hash_looks_at_hashtags_only(api):
    public_post("p1", "#coffee time", hashtags=["coffee"])
    person(acct(), "coffee lover")
    hits = api.get(reverse("searchsvc:suggest"), {"q": "#cof"}).json()["data"]["results"]
    assert [(h["type"], h["id"]) for h in hits] == [("hashtag", "coffee")]


def test_search_page_query_count_is_bounded(api, django_assert_max_num_queries):
    for i in range(30):
        public_post(f"p{i}", f"#bulk bulk word {i}", hashtags=["bulk"])
        person(acct(), f"bulk person {i}")
    with django_assert_max_num_queries(2):  # the page, plus hashtag counts
        search(api, "bulk", limit=50)


# ---- recent searches ---------------------------------------------------------------------


def test_recent_searches_are_private_to_their_owner(client_for, viewer):
    me, other = client_for(viewer), client_for(acct())
    url = reverse("searchsvc:recent")
    assert me.post(url, {"query": "  الإسكندرية  "}, format="json").status_code == 201
    entry = me.post(url, {"query": "cats"}, format="json").json()["data"]
    assert [r["query"] for r in me.get(url).json()["data"]] == ["cats", "الإسكندرية"]
    assert other.get(url).json()["data"] == []

    detail = reverse("searchsvc:recent-detail", args=[entry["id"]])
    assert other.delete(detail).status_code == 404
    assert RecentSearch.objects.filter(id=entry["id"]).exists()
    other.delete(url)  # clearing their own history touches nothing of mine
    assert RecentSearch.objects.filter(account_id=viewer).count() == 2

    assert me.delete(detail).status_code == 204
    assert [r["query"] for r in me.get(url).json()["data"]] == ["الإسكندرية"]
    assert me.delete(url).status_code == 204
    assert me.get(url).json()["data"] == []


def test_repeating_a_query_moves_it_up_without_duplicates(api):
    url = reverse("searchsvc:recent")
    for q in ("احمد", "cats", "أحمد"):  # the same query in another spelling
        api.post(url, {"query": q}, format="json")
    rows = api.get(url).json()["data"]
    assert [r["query"] for r in rows] == ["أحمد", "cats"]


def test_history_is_capped(api, viewer):
    url = reverse("searchsvc:recent")
    for i in range(25):
        api.post(url, {"query": f"term {i}"}, format="json")
    assert RecentSearch.objects.filter(account_id=viewer).count() == 20
    assert len(api.get(url).json()["data"]) == 10


def test_entity_entries_follow_what_is_still_searchable(api, viewer):
    a, b = acct(), acct()
    person(a, "Mona Zaki", avatar_media_id="m1")
    person(b, "Mona Lisa")
    url = reverse("searchsvc:recent")
    assert api.post(url, {"doc_type": "user", "doc_id": a}, format="json").status_code == 201
    api.post(url, {"doc_type": "user", "doc_id": b}, format="json")
    rows = api.get(url).json()["data"]
    assert [(r["doc_id"], r["title"]) for r in rows] == [(b, "Mona Lisa"), (a, "Mona Zaki")]
    assert rows[1]["avatar_media_id"] == "m1" and rows[1]["handle"]

    BlockedPair.objects.create(blocker_id=b, blocked_id=viewer)
    handlers.on_profile_updated(
        ev("profile.updated", a, {"handle": "m", "visibility": "private"}, 99)
    )
    assert api.get(url).json()["data"] == []


def test_unknown_or_hidden_entity_cannot_be_recorded(api):
    url = reverse("searchsvc:recent")
    group("g-hid", "Hidden one", "hidden")
    assert api.post(url, {"doc_type": "group", "doc_id": "g-hid"}, format="json").status_code == 404
    assert api.post(url, {"doc_type": "user", "doc_id": acct()}, format="json").status_code == 404
    assert api.post(url, {"doc_type": "nope", "doc_id": "x"}, format="json").status_code == 404
    assert api.post(url, {"query": "   "}, format="json").status_code == 400


def test_recent_searches_need_authentication(client):
    assert client.get(reverse("searchsvc:recent")).status_code == 401


# ---- trending ---------------------------------------------------------------------------


def test_trending_counts_distinct_authors_in_the_window(api):
    # 4b.20-B3: at least 3 distinct authors, and only a bucketed post count
    # (test_trending_floor.py covers the floors and restrictions).
    a, b, c = acct(), acct(), acct()
    public_post("p1", "#nile", author=a, hashtags=["nile"])
    public_post("p2", "#nile", author=a, hashtags=["nile"])
    public_post("p3", "#cairo", author=a, hashtags=["cairo"])
    public_post("p4", "#cairo", author=b, hashtags=["cairo"])
    public_post("p5", "#cairo", author=c, hashtags=["cairo"])
    for i, author in enumerate((a, b, c)):
        public_post(f"o{i}", "#old", author=author, hashtags=["old"])
    PublicPostHashtag.objects.filter(tag="old").update(
        created_at=timezone.now() - timedelta(days=3)
    )
    handlers.on_post_created(
        ev(
            "post.created",
            "p6",
            {"post_id": "p6", "author_id": b, "audience": "friends", "hashtags": ["nile"]},
        )
    )

    day = api.get(reverse("searchsvc:trending"), {"window": "day"}).json()["data"]
    assert day == [{"tag": "cairo", "posts_floor": None, "window": "day"}]
    week = api.get(reverse("searchsvc:trending")).json()["data"]
    assert {t["tag"] for t in week} == {"cairo", "old"}  # nile: one author (p6 is friends-only)


def test_hashtag_results_carry_post_counts(api):
    public_post("p1", "#tea", hashtags=["tea"])
    public_post("p2", "#tea", hashtags=["tea"])
    hit = search(api, "tea", type="hashtags")["data"]["results"][0]
    assert hit["tag"] == "tea" and hit["post_count"] == 2
