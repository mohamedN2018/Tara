"""Posts published as a page follow the page in live search (fix round 3, track C).

A page that goes to draft, is suspended or is deleted takes its posts (and their
hashtag links, counts and trending) out of the index; publishing it again brings
them back. Event order and repeats never leak a hidden page's post.
"""

import io
import uuid
from datetime import timedelta

import pytest
from django.core.management import call_command

from searchsvc import handlers, history, indexing
from searchsvc.models import PublicPostHashtag, SearchDocument
from searchsvc.posts import PARKED_POST, reconcile_page_posts
from searchsvc.tests.test_search_v2 import (  # noqa: F401 - no_graph is an autouse fixture
    T0,
    acct,
    ev,
    ids,
    no_graph,
    public_post,
    search,
)

pytestmark = pytest.mark.django_db

HIDDEN_STATES = [
    pytest.param({"status": "draft"}, id="draft"),
    pytest.param({"status": "suspended"}, id="suspended"),
    pytest.param({"deleted": True}, id="deleted"),
]


@pytest.fixture
def viewer():
    return acct()


@pytest.fixture
def api(client_for, viewer):
    return client_for(viewer)


def page_event(page_id, at, *, event="page.updated", status="published", deleted=False):
    payload = {
        "handle": f"pg{page_id[:8]}",
        "name": "Nile Books",
        "owner": acct(),
        "category": "books",
        "location": "",
        "status": status,
        "avatar_media_id": None,
        "deleted": deleted,
        "changed": ["status"],
    }
    fn = handlers.on_page_created if event == "page.created" else handlers.on_page_updated
    fn(ev(event, page_id, payload, at))


def page_post(post_id, page_id, excerpt, *, at=1, tags=()):
    public_post(post_id, excerpt, author=page_id, at=at, author_type="page", hashtags=list(tags))


def post_ids(api, q):
    return ids(search(api, q, type="posts"))


def tag_docs():
    return set(SearchDocument.objects.filter(doc_type="hashtag").values_list("doc_id", flat=True))


def tag_count(api, tag):
    results = search(api, f"#{tag}", type="hashtags")["data"]["results"]
    return {r["tag"]: r["post_count"] for r in results}.get(tag, 0)


@pytest.mark.parametrize("hidden", HIDDEN_STATES)
def test_hidden_page_takes_its_posts_out_and_republish_restores(api, hidden):
    page = str(uuid.uuid4())
    page_event(page, 0, event="page.created")
    page_post("pp1", page, "Booksale tonight #nilebooks", tags=["nilebooks"])
    public_post("up1", "Booksale at home #nilebooks", hashtags=["nilebooks"], at=1)
    assert set(post_ids(api, "booksale")) == {"pp1", "up1"}
    assert tag_count(api, "nilebooks") == 2

    page_event(page, 10, **hidden)
    page_event(page, 10, **hidden)  # a redelivered event is a no-op
    assert post_ids(api, "booksale") == ["up1"]
    assert tag_count(api, "nilebooks") == 1  # only the user's post backs it now
    assert {r["tag"]: r["posts"] for r in history.trending()}["nilebooks"] == 1
    assert SearchDocument.objects.filter(doc_type=PARKED_POST, doc_id="pp1").count() == 1
    assert not PublicPostHashtag.objects.filter(post_id="pp1").exists()

    page_event(page, 20)  # published (or undeleted by staff) again
    page_event(page, 20)
    assert set(post_ids(api, "booksale")) == {"pp1", "up1"}
    assert tag_count(api, "nilebooks") == 2
    assert not SearchDocument.objects.filter(doc_type=PARKED_POST).exists()


def test_hidden_tag_only_used_by_the_page_disappears_and_returns(api):
    page = str(uuid.uuid4())
    page_event(page, 0, event="page.created")
    page_post("pp1", page, "Only here #pageonlytag", tags=["pageonlytag"])
    assert "pageonlytag" in tag_docs()

    page_event(page, 10, status="draft")
    assert "pageonlytag" not in tag_docs()
    assert ids(search(api, "#pageonlytag", type="hashtags")) == []

    page_event(page, 20)
    assert "pageonlytag" in tag_docs()


def test_a_post_written_or_edited_while_the_page_is_hidden_stays_out(api):
    page = str(uuid.uuid4())
    page_event(page, 0, event="page.created")
    page_post("pp1", page, "Old words", at=1)
    page_event(page, 10, status="draft")

    # The team edits a post and publishes a new one while the page is a draft.
    handlers.on_post_updated(
        ev(
            "post.updated",
            "pp1",
            {
                "post_id": "pp1",
                "author_id": page,
                "audience": "public",
                "excerpt": "Edited words #edited",
                "hashtags": ["edited"],
                "author_type": "page",
            },
            11,
        )
    )
    page_post("pp2", page, "Fresh words", at=12)
    assert post_ids(api, "words") == []
    assert "edited" not in tag_docs()

    page_event(page, 20)
    assert set(post_ids(api, "words")) == {"pp1", "pp2"}
    assert search(api, "edited words", type="posts")["data"]["results"][0]["snippet"] == (
        "Edited words #edited"
    )
    assert "edited" in tag_docs()


def test_a_post_deleted_while_parked_is_not_restored(api):
    page = str(uuid.uuid4())
    page_event(page, 0, event="page.created")
    page_post("pp1", page, "Gone soon", tags=["gonesoon"])
    page_event(page, 10, status="suspended")
    handlers.on_post_deleted(ev("post.deleted", "pp1", {"post_id": "pp1", "author_id": page}, 11))
    assert not SearchDocument.objects.filter(doc_id="pp1").exists()

    page_event(page, 20)
    assert post_ids(api, "gone soon") == []
    assert "gonesoon" not in tag_docs()


def test_a_stale_published_event_does_not_bring_the_posts_back(api):
    page = str(uuid.uuid4())
    page_event(page, 0, event="page.created")
    page_post("pp1", page, "Stale check")
    page_event(page, 20, status="draft")
    page_event(page, 10)  # older than the draft: a retried earlier event
    assert post_ids(api, "stale check") == []


def test_other_pages_and_people_are_untouched(api):
    hidden, shown = str(uuid.uuid4()), str(uuid.uuid4())
    for p in (hidden, shown):
        page_event(p, 0, event="page.created")
    page_post("hp", hidden, "Shared topic hidden")
    page_post("sp", shown, "Shared topic shown")
    public_post("up", "Shared topic person")
    page_event(hidden, 10, status="draft")
    assert set(post_ids(api, "shared topic")) == {"sp", "up"}


def test_unknown_page_is_left_alone(api):
    # Search never saw this page's events: its posts are indexed as before.
    page_post("pp1", str(uuid.uuid4()), "Unknown page post")
    assert post_ids(api, "unknown page post") == ["pp1"]


def test_reconcile_parks_posts_indexed_before_the_rule(api):
    page = str(uuid.uuid4())
    page_event(page, 0, event="page.created")
    page_post("pp1", page, "Legacy leak #legacyleak", tags=["legacyleak"])
    # An older indexer applied the draft to the page only.
    indexing.apply("page", page, T0 + timedelta(seconds=10), None)
    assert post_ids(api, "legacy leak") == ["pp1"]

    out = io.StringIO()
    call_command("reconcile_hashtags", stdout=out)
    assert "page posts parked: 1, page posts restored: 0" in out.getvalue()
    assert post_ids(api, "legacy leak") == []
    assert "legacyleak" not in tag_docs()
    assert reconcile_page_posts() == {"parked": 0, "restored": 0}  # idempotent
