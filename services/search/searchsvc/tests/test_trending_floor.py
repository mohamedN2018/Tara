"""Trending hashtags honesty fix (Tara Intelligence 4b.20-B3): an author floor,
restricted and shadowed authors left out, and post counts bucketed on the
server so a raw or small number never leaves the API."""

import io
import uuid
from datetime import UTC, datetime, timedelta
from unittest import mock

import pytest
from django.core.cache import cache
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from searchsvc import handlers, history, restrictions
from searchsvc.models import PublicPostHashtag, SearchAccountRestriction
from tara_events.envelope import EventEnvelope

pytestmark = pytest.mark.django_db

T0 = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
FLOORS = (20, 50, 100, 500, 1000, 5000, 10000)


def acct() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def api(client_for):
    return client_for(acct())


def tag_posts(tag: str, authors: list[str], posts: int | None = None, *, age=timedelta(0)):
    """``posts`` public-post links for ``tag``, spread over ``authors`` (one each by default)."""
    posts = len(authors) if posts is None else posts
    at = timezone.now() - age
    rows = [
        PublicPostHashtag(post_id=uuid.uuid4().hex, tag=tag, author_id=authors[i % len(authors)])
        for i in range(posts)
    ]
    PublicPostHashtag.objects.bulk_create(rows)
    PublicPostHashtag.objects.filter(post_id__in=[r.post_id for r in rows]).update(created_at=at)


def actioned(target_id, action, *, at=0, target_type="user", case_id=None):
    payload = {
        "case_id": case_id or acct(),
        "target_type": target_type,
        "target_id": str(target_id),
        "action": action,
        "owner_id": str(target_id),
    }
    handlers.on_moderation_actioned(
        EventEnvelope(
            event_type="moderation.actioned",
            subject_id=payload["case_id"],
            producer="moderation-service",
            occurred_at=(T0 + timedelta(seconds=at)).isoformat(),
            payload=payload,
        )
    )


def trending(api, **params) -> list[dict]:
    resp = api.get(reverse("searchsvc:trending"), params)
    assert resp.status_code == 200, resp.content
    return resp.json()["data"]


def tags(api, **params) -> list[str]:
    return [t["tag"] for t in trending(api, **params)]


# ---- author floor ------------------------------------------------------------------


def test_a_tag_needs_three_distinct_authors(api):
    a, b, c = acct(), acct(), acct()
    tag_posts("two", [a, b], 30)  # many posts, two people
    tag_posts("three", [a, b, c])
    assert tags(api) == ["three"]


def test_order_is_authors_then_posts_then_tag(api):
    people = [acct() for _ in range(5)]
    tag_posts("four_few", people[:4])
    tag_posts("three_many", people[:3], 60)
    tag_posts("bbb", people[:3], 25)
    tag_posts("aaa", people[:3], 25)
    assert tags(api) == ["four_few", "three_many", "aaa", "bbb"]


# ---- count floors ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("posts", "floor"),
    [
        (0, None),
        (19, None),
        (20, 20),
        (49, 20),
        (50, 50),
        (99, 50),
        (100, 100),
        (499, 100),
        (500, 500),
        (999, 500),
        (1000, 1000),
        (4999, 1000),
        (5000, 5000),
        (9999, 5000),
        (10000, 10000),
        (2_500_000, 10000),
    ],
)
def test_every_floor_boundary(posts, floor, settings):
    assert tuple(settings.SEARCH_TRENDING_COUNT_FLOORS) == FLOORS
    assert history.posts_floor(posts) == floor


@pytest.mark.parametrize(("posts", "floor"), [(19, None), (20, 20), (49, 20), (50, 50)])
def test_the_api_returns_the_floor_never_the_count(api, posts, floor):
    tag_posts("nile", [acct(), acct(), acct()], posts)
    data = trending(api)
    assert data == [{"tag": "nile", "posts_floor": floor, "window": "week"}]


def test_a_large_count_is_the_top_floor(api):
    tag_posts("big", [acct(), acct(), acct()], 10_000)
    assert trending(api)[0]["posts_floor"] == 10000


def test_no_raw_count_key_in_the_response(api):
    tag_posts("cairo", [acct(), acct(), acct()], 33)
    for item in trending(api) + trending(api, window="day"):
        assert set(item) == {"tag", "posts_floor", "window"}
        assert "posts" not in item and "authors" not in item


# ---- windows -----------------------------------------------------------------------


def test_the_window_is_honoured_and_named(api):
    people = [acct(), acct(), acct()]
    tag_posts("today", people, 20)
    tag_posts("earlier", people, 20, age=timedelta(days=3))
    tag_posts("ancient", people, 20, age=timedelta(days=8))
    day = trending(api, window="day")
    assert [(t["tag"], t["window"]) for t in day] == [("today", "day")]
    week = trending(api, window="week")
    assert {t["tag"] for t in week} == {"today", "earlier"}
    assert {t["window"] for t in week} == {"week"}
    assert {t["window"] for t in trending(api, window="year")} == {"week"}  # unknown: the week


# ---- restricted and shadowed authors -----------------------------------------------


@pytest.mark.parametrize("action", ["restrict", "shadow"])
def test_restricted_authors_do_not_count_until_reinstated(api, action):
    a, b, c, d = acct(), acct(), acct(), acct()
    tag_posts("nile", [a, b, c], 21)  # 7 each
    tag_posts("nile", [d])
    assert trending(api) == [{"tag": "nile", "posts_floor": 20, "window": "week"}]
    actioned(a, action, at=1)
    # a's 7 posts leave the count (15 < 20); b, c, d still make 3 authors.
    assert trending(api) == [{"tag": "nile", "posts_floor": None, "window": "week"}]
    actioned(b, action, at=2)
    assert tags(api) == []  # 2 authors left
    actioned(a, "reinstate", at=3)
    actioned(b, "reinstate", at=4)
    assert trending(api) == [{"tag": "nile", "posts_floor": 20, "window": "week"}]


def test_an_out_of_order_or_repeated_event_is_ignored(api):
    a, b, c = acct(), acct(), acct()
    tag_posts("nile", [a, b, c])
    actioned(a, "reinstate", at=10)  # the reinstate arrives first
    actioned(a, "restrict", at=5)  # its older restriction, retried late
    assert tags(api) == ["nile"]
    actioned(a, "shadow", at=20)
    actioned(a, "reinstate", at=15)  # older than the shadow
    assert tags(api) == []
    actioned(a, "shadow", at=20)  # redelivered
    row = SearchAccountRestriction.objects.get(account_id=a)
    assert (row.active, row.kind, row.event_at) == (True, "shadow", T0 + timedelta(seconds=20))


@pytest.mark.parametrize(
    ("action", "target_type"),
    [("warn", "user"), ("dismiss", "user"), ("remove", "user"), ("restrict", "page")],
)
def test_other_actions_and_targets_change_nothing(api, action, target_type):
    a, b, c = acct(), acct(), acct()
    tag_posts("nile", [a, b, c])
    actioned(a, action, target_type=target_type, at=1)
    assert tags(api) == ["nile"]
    assert not SearchAccountRestriction.objects.exists()


def test_a_bad_target_id_is_ignored():
    actioned("not-a-uuid", "restrict")
    assert not SearchAccountRestriction.objects.exists()


def test_the_handler_invalidates_the_cached_answer(api, django_capture_on_commit_callbacks):
    a, b, c = acct(), acct(), acct()
    tag_posts("nile", [a, b, c])
    assert tags(api) == ["nile"]
    assert cache.get(restrictions.trending_cache_key("week")) is not None
    tag_posts("cairo", [a, b, c])
    assert tags(api) == ["nile"]  # cached for SEARCH_TRENDING_CACHE_S
    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        actioned(a, "restrict", at=1)
    assert callbacks  # dropped again after the commit
    assert cache.get(restrictions.trending_cache_key("week")) is None
    assert cache.get(restrictions.trending_cache_key("day")) is None
    assert tags(api) == []


def test_the_answer_is_cached_per_window(api, settings):
    people = [acct(), acct(), acct()]
    tag_posts("nile", people)
    assert tags(api, window="day") == ["nile"]
    assert tags(api, window="week") == ["nile"]
    tag_posts("cairo", people)
    assert tags(api, window="day") == ["nile"]
    cache.delete(restrictions.trending_cache_key("day"))
    assert set(tags(api, window="day")) == {"nile", "cairo"}
    assert tags(api, window="week") == ["nile"]  # its own entry, still cached


def test_a_cache_outage_still_answers():
    tag_posts("nile", [acct(), acct(), acct()])
    with (
        mock.patch.object(history.cache, "get", side_effect=ConnectionError),
        mock.patch.object(history.cache, "set", side_effect=ConnectionError),
    ):
        assert [t["tag"] for t in history.trending("week")] == ["nile"]


def test_account_deleted_removes_the_row():
    a = acct()
    actioned(a, "restrict", at=1)
    assert SearchAccountRestriction.objects.filter(account_id=a).exists()
    handlers.on_account_deleted(
        EventEnvelope(
            event_type="account.deleted",
            subject_id=a,
            producer="identity-service",
            occurred_at=T0.isoformat(),
            payload={"account_id": a},
        )
    )
    assert not SearchAccountRestriction.objects.filter(account_id=a).exists()


def test_trending_needs_authentication(client):
    assert client.get(reverse("searchsvc:trending")).status_code == 401


# ---- backfill ----------------------------------------------------------------------


class _Resp:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        return None

    def json(self):
        return {"data": self._data}


def test_backfill_applies_the_export_and_sweeps_lost_reinstates(settings):
    settings.MODERATION_INTERNAL_URL = "http://moderation:8000"
    listed, stale, newer = acct(), acct(), acct()
    actioned(stale, "restrict", at=1)  # moderation no longer lists it
    as_of = timezone.now()
    actioned(newer, "reinstate")  # occurred at T0: older than as_of, so the export wins
    pages = [
        {
            "as_of": as_of.isoformat(),
            "items": [
                {"id": acct(), "payload": {"account_id": listed, "action": "shadow"}},
                {"id": acct(), "payload": {"account_id": newer, "action": "restrict"}},
                {"id": acct(), "payload": {"account_id": "junk", "action": "restrict"}},
            ],
            "next": "x",
        },
        {"as_of": as_of.isoformat(), "items": [], "next": None},
    ]
    calls = []

    def fake_get(url, params, headers, timeout):
        calls.append((url, params["after"], headers["Authorization"].startswith("Bearer ")))
        return _Resp(pages[len(calls) - 1])

    out = io.StringIO()
    with mock.patch("requests.get", side_effect=fake_get):
        call_command("search_backfill_restrictions", "--rate", "0", stdout=out)
    assert calls[0] == ("http://moderation:8000/internal/v1/intel/export/restrictions/", "", True)
    assert calls[1][1] == "x"
    rows = SearchAccountRestriction.objects.filter(active=True).values_list("account_id", flat=True)
    active = {str(a) for a in rows}
    assert active == {listed, newer}
    assert "listed 2, applied 2, swept 1, active 2" in out.getvalue()
    assert listed not in out.getvalue()  # counts only, never ids


def test_backfill_reports_an_unreachable_export():
    from django.core.management.base import CommandError
    from requests import ConnectionError as RequestsConnectionError

    with (
        mock.patch("requests.get", side_effect=RequestsConnectionError("down")),
        pytest.raises(CommandError),
    ):
        call_command("search_backfill_restrictions", stdout=io.StringIO())
