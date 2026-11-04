"""Posts and hashtags reach search only from live public posts (milestone 1.1)."""

import importlib
import io
import uuid
from datetime import UTC, datetime, timedelta
from unittest import mock

import pytest
from django.apps import apps as django_apps
from django.core.management import call_command
from django.urls import reverse

from searchsvc import backend
from searchsvc.handlers import on_post_created, on_post_deleted, on_post_updated
from searchsvc.models import PostIndexState, PublicPostHashtag, SearchDocument
from searchsvc.posts import (
    _purge_hashtag_if_unbacked,
    _restore_hashtag_if_backed,
    _sync_untracked_post,
    reconcile_hashtags,
)
from tara_events.envelope import EventEnvelope

pytestmark = pytest.mark.django_db

T0 = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
AUTHOR = str(uuid.uuid4())
NOT_FOUND = (False, False, False)
FOUND = (True, True, True)


def _event(event_type, post_id, at, payload):
    return EventEnvelope(
        event_type=event_type,
        subject_id=post_id,
        producer="post-service",
        occurred_at=(T0 + timedelta(seconds=at)).isoformat().replace("+00:00", "Z"),
        payload={"post_id": post_id, **payload},
    )


def created(post_id, *, audience="public", hashtags=(), excerpt="", at=0, **extra):
    payload = {"author_id": AUTHOR, "audience": audience, "hashtags": list(hashtags)}
    on_post_created(_event("post.created", post_id, at, {**payload, "excerpt": excerpt, **extra}))


def updated(post_id, *, audience="public", excerpt="", at=1, **extra):
    # An older post-service payload: no `hashtags` key, so tags come from the excerpt.
    payload = {"author_id": AUTHOR, "audience": audience, "excerpt": excerpt}
    on_post_updated(_event("post.updated", post_id, at, {**payload, **extra}))


def deleted(post_id, *, at=2):
    # Same shape for an author delete and a moderator removal (`apply_moderation`).
    on_post_deleted(_event("post.deleted", post_id, at, {}))


@pytest.fixture
def viewer(client_for):
    return client_for(str(uuid.uuid4()))


def _search(client, q, doc_type=None):
    params = {"q": q, **({"type": doc_type} if doc_type else {})}
    resp = client.get(reverse("searchsvc:search"), params)
    assert resp.status_code == 200
    return resp.json()["data"]["results"]


def _autocomplete(client, q):
    resp = client.get(reverse("searchsvc:autocomplete"), {"q": q})
    assert resp.status_code == 200
    return resp.json()["data"]["results"]


def _hashtag_found(client, tag):
    """(in global search, in hashtag search, in autocomplete)."""
    return (
        any(r["type"] == "hashtag" and r["id"] == tag for r in _search(client, tag)),
        any(r["id"] == tag for r in _search(client, tag, "hashtag")),
        any(
            r["type"] == "hashtag" and r["id"] == tag for r in _autocomplete(client, f"#{tag[:4]}")
        ),
    )


def _links():
    return set(PublicPostHashtag.objects.values_list("post_id", "tag"))


def _hashtag_docs():
    return set(SearchDocument.objects.filter(doc_type="hashtag").values_list("doc_id", flat=True))


# ---- non-public posts never reach hashtag search ------------------------------


@pytest.mark.parametrize(
    "audience", ["friends", "followers", "only_me", "close_friends", "group", "", None]
)
def test_hashtag_used_only_in_a_non_public_post_is_never_found(viewer, audience):
    created("p-private", audience=audience, hashtags=["secretplan"], excerpt="meet #secretplan")

    assert _hashtag_found(viewer, "secretplan") == NOT_FOUND
    assert _search(viewer, "secretplan") == []  # nor the post itself
    assert _hashtag_docs() == set()
    assert _links() == set()


def test_public_audience_inside_a_group_is_not_indexed(viewer):
    created("p-group", hashtags=["grouptag"], excerpt="#grouptag", group_id=str(uuid.uuid4()))
    assert _hashtag_found(viewer, "grouptag") == NOT_FOUND
    assert not SearchDocument.objects.exists()


def test_public_post_hashtag_is_found(viewer):
    created("p1", hashtags=["launchday"], excerpt="big news #launchday")
    assert _hashtag_found(viewer, "launchday") == FOUND
    assert _links() == {("p1", "launchday")}


def test_a_friends_post_does_not_keep_a_hashtag_alive(viewer):
    created("pub", hashtags=["shared"], excerpt="#shared")
    created("fr", audience="friends", hashtags=["shared"], excerpt="#shared")
    assert _links() == {("pub", "shared")}

    deleted("pub")
    assert _hashtag_found(viewer, "shared") == NOT_FOUND


# ---- stale hashtags are purged -------------------------------------------------


def test_editing_a_public_post_to_friends_removes_it_and_its_hashtags(viewer):
    created("p1", hashtags=["launchday"], excerpt="big news #launchday")
    assert [r["id"] for r in _search(viewer, "big news", "post")] == ["p1"]

    updated("p1", audience="friends", excerpt="big news #launchday")

    assert _search(viewer, "big news", "post") == []
    assert _hashtag_found(viewer, "launchday") == NOT_FOUND
    assert _links() == set()
    state = PostIndexState.objects.get(post_id="p1")
    assert (state.public, state.deleted) == (False, False)


def test_an_edit_that_drops_a_hashtag_purges_it(viewer):
    created("p1", hashtags=["keep", "drop"], excerpt="#keep #drop")
    updated("p1", excerpt="#keep and #added")

    assert _links() == {("p1", "keep"), ("p1", "added")}
    assert _hashtag_found(viewer, "drop") == NOT_FOUND
    assert _hashtag_found(viewer, "keep") == FOUND
    assert _hashtag_found(viewer, "added") == FOUND


def test_hashtags_in_an_update_payload_are_authoritative():
    created("p1", hashtags=["old"], excerpt="#old")
    updated("p1", excerpt="the excerpt says #notthis", hashtags=["new"])
    assert _links() == {("p1", "new")}
    assert _hashtag_docs() == {"new"}


def test_hashtag_stays_while_another_public_post_uses_it(viewer):
    created("a", hashtags=["common"], excerpt="#common")
    created("b", hashtags=["common"], excerpt="#common")

    deleted("a")
    assert _hashtag_found(viewer, "common") == FOUND
    deleted("b")
    assert _hashtag_found(viewer, "common") == NOT_FOUND


def test_a_moderator_removal_purges_the_post_and_its_hashtags(viewer):
    created("p1", hashtags=["reported"], excerpt="bad words #reported")
    deleted("p1")  # post-service turns moderation.actioned(remove) into post.deleted

    assert _search(viewer, "bad words") == []
    assert _hashtag_found(viewer, "reported") == NOT_FOUND
    assert PostIndexState.objects.get(post_id="p1").deleted is True


def test_a_truncated_excerpt_does_not_invent_a_partial_hashtag():
    excerpt = "#early " + "x" * 265 + " #travel"
    assert len(excerpt) == 280  # post-service cut `#travelling` here
    created("p1", hashtags=["early"], excerpt="#early")
    updated("p1", excerpt=excerpt)
    assert _links() == {("p1", "early")}


def test_payload_hashtags_are_normalised_and_validated():
    long_tag = "a" * 80  # post-service allows 80; doc_id used to be 64
    created("p1", hashtags=["#Tara", "tara", "bad tag", 42, "", "x" * 81, long_tag, "عربي"])
    assert {t for _, t in _links()} == {"tara", long_tag, "عربي"}
    assert _hashtag_docs() == {"tara", long_tag, "عربي"}


# ---- retries reorder events: the newest fact wins ------------------------------


def test_a_late_older_update_does_not_resurrect_a_deleted_post(viewer):
    created("p1", hashtags=["ghost"], excerpt="boo #ghost", at=0)
    deleted("p1", at=10)
    updated("p1", excerpt="boo #ghost", at=5)  # a retry, older than the delete

    assert _search(viewer, "boo") == []
    assert _hashtag_found(viewer, "ghost") == NOT_FOUND
    assert _links() == set()


def test_a_late_create_does_not_override_a_newer_audience_change(viewer):
    updated("p1", audience="friends", excerpt="#hush", at=10)
    created("p1", hashtags=["hush"], excerpt="#hush", at=0)

    assert _hashtag_found(viewer, "hush") == NOT_FOUND
    assert not SearchDocument.objects.exists()


def test_a_late_create_after_a_delete_is_ignored():
    deleted("p1", at=10)
    created("p1", hashtags=["late"], excerpt="#late", at=10)  # same instant: the delete wins
    assert not SearchDocument.objects.exists()


def test_a_newer_public_edit_after_a_removal_is_indexed_again():
    # An overturned moderation removal, then an edit by the author.
    created("p1", hashtags=["back"], excerpt="#back", at=0)
    deleted("p1", at=5)
    updated("p1", excerpt="#back again", at=10)
    assert _links() == {("p1", "back")}
    assert SearchDocument.objects.filter(doc_type="post", doc_id="p1").exists()


def test_redelivered_create_is_idempotent():
    created("p1", hashtags=["once"], excerpt="#once", at=0)
    created("p1", hashtags=["once"], excerpt="#once", at=0)
    assert _links() == {("p1", "once")}
    assert SearchDocument.objects.count() == 2  # the post and the hashtag


# ---- data fix for rows written before the rule existed ------------------------


def test_migration_drops_hashtags_no_public_post_backs():
    # Before 0003: post documents (public only) and hashtag documents from every audience.
    backend.index_document("post", "pub", body="hello #visible, #AlsoVisible", owner_id=AUTHOR)
    for tag in ["visible", "alsovisible", "friendsonly", "editedaway"]:
        backend.index_document("hashtag", tag, title=f"#{tag}")
    migration = importlib.import_module("searchsvc.migrations.0004_purge_nonpublic_hashtags")

    migration.forwards(django_apps, None)
    migration.forwards(django_apps, None)  # re-running is safe

    assert _hashtag_docs() == {"visible", "alsovisible"}
    assert _links() == {("pub", "visible"), ("pub", "alsovisible")}


def test_reconcile_command_purges_orphans_and_restores_missing_documents():
    created("p1", hashtags=["real"], excerpt="#real")
    SearchDocument.objects.filter(doc_type="hashtag", doc_id="real").delete()  # lost earlier
    backend.index_document("hashtag", "orphan", title="#orphan")  # an old-code indexer wrote it
    backend.index_document("post", "legacy", body="old #legacytag", owner_id=AUTHOR)

    out = io.StringIO()
    call_command("reconcile_hashtags", stdout=out)

    assert _hashtag_docs() == {"real", "legacytag"}
    assert ("legacy", "legacytag") in _links()
    assert (
        "posts purged: 0, links added: 1, links removed: 0, "
        "hashtags purged: 1, hashtags restored: 2"
    ) in out.getvalue()


# ---- the deploy: old search-consumer still runs after migration 0004 -----------
# Dokploy migrates in the new `search` container; the old `search-consumer` keeps
# consuming until it is recreated. These copy what that pre-0003 code wrote: post
# documents only, never links, and hashtag documents for every audience.


def old_code_created(post_id, *, audience="public", hashtags=(), excerpt=""):
    if audience == "public":
        backend.index_document("post", post_id, body=excerpt, owner_id=AUTHOR)
    for tag in hashtags:
        backend.index_document("hashtag", tag, title=f"#{tag}")


def old_code_updated(post_id, *, audience="public", excerpt=""):
    if audience == "public":
        backend.index_document("post", post_id, body=excerpt, owner_id=AUTHOR)
    else:
        backend.delete_document("post", post_id)


def old_code_deleted(post_id):
    backend.delete_document("post", post_id)


def migrate_0004():
    importlib.import_module("searchsvc.migrations.0004_purge_nonpublic_hashtags").forwards(
        django_apps, None
    )


def _all_zero(result):
    return all(v == 0 for v in result.values())


def test_reconcile_drops_a_post_old_code_deleted_during_the_deploy(viewer):
    old_code_created("legacy", hashtags=["leak"], excerpt="#leak")
    migrate_0004()
    assert _links() == {("legacy", "leak")}
    old_code_deleted("legacy")  # author delete or moderator removal, old consumer

    result = reconcile_hashtags()

    assert _hashtag_found(viewer, "leak") == NOT_FOUND
    assert _links() == set()
    assert _hashtag_docs() == set()
    assert (result["links_removed"], result["hashtags_purged"]) == (1, 1)
    assert _all_zero(reconcile_hashtags())  # idempotent


def test_reconcile_drops_a_post_old_code_made_friends_only(viewer):
    old_code_created("legacy", hashtags=["hush"], excerpt="quiet #hush")
    migrate_0004()
    old_code_updated("legacy", audience="friends", excerpt="quiet #hush")

    reconcile_hashtags()

    assert _hashtag_found(viewer, "hush") == NOT_FOUND
    assert _search(viewer, "quiet") == []
    assert _links() == set()


def test_reconcile_drops_a_tag_old_code_edited_away(viewer):
    old_code_created("legacy", hashtags=["keep", "gone"], excerpt="#keep #gone")
    migrate_0004()
    assert _links() == {("legacy", "keep"), ("legacy", "gone")}
    old_code_updated("legacy", excerpt="#keep")

    result = reconcile_hashtags()

    assert _links() == {("legacy", "keep")}
    assert _hashtag_found(viewer, "gone") == NOT_FOUND
    assert _hashtag_found(viewer, "keep") == FOUND
    assert result == {
        "posts_purged": 0,
        "links_added": 0,
        "links_removed": 1,
        "hashtags_purged": 1,
        "hashtags_restored": 0,
        "page_posts_parked": 0,
        "page_posts_restored": 0,
    }
    assert _all_zero(reconcile_hashtags())


def test_reconcile_adds_a_tag_old_code_edited_in_and_drops_friends_only_tags(viewer):
    old_code_created("legacy", hashtags=["first"], excerpt="#first")
    migrate_0004()
    old_code_updated("legacy", excerpt="#first #second")
    old_code_created("fr", audience="friends", hashtags=["friendsonly"], excerpt="#friendsonly")

    reconcile_hashtags()

    assert _links() == {("legacy", "first"), ("legacy", "second")}
    assert _hashtag_found(viewer, "second") == FOUND
    assert _hashtag_found(viewer, "friendsonly") == NOT_FOUND


def test_after_the_deploy_the_new_consumer_cleans_a_legacy_post_by_itself(viewer):
    old_code_created("legacy", hashtags=["bye"], excerpt="#bye")
    migrate_0004()
    deleted("legacy")
    assert _links() == set()
    assert _hashtag_found(viewer, "bye") == NOT_FOUND


def test_reconcile_drops_links_of_a_tracked_post_old_code_deleted(viewer):
    # The new consumer indexed it, then an old one deleted only the post document.
    created("p1", hashtags=["tracked"], excerpt="#tracked")
    old_code_deleted("p1")

    reconcile_hashtags()

    assert _links() == set()
    assert _hashtag_found(viewer, "tracked") == NOT_FOUND


@pytest.mark.parametrize("hide", ["friends", "deleted"])
def test_reconcile_drops_a_post_and_links_the_indexer_marked_hidden(viewer, hide):
    created("p1", hashtags=["stale"], excerpt="leaky #stale", at=0)
    if hide == "friends":
        updated("p1", audience="friends", excerpt="leaky #stale", at=5)
    else:
        deleted("p1", at=5)
    # An old consumer then replays a public edit: it ignores the tombstone.
    old_code_updated("p1", excerpt="leaky #stale")
    PublicPostHashtag.objects.create(post_id="p1", tag="stale", author_id=AUTHOR)
    backend.index_document("hashtag", "stale", title="#stale")
    assert _search(viewer, "leaky", "post") != []

    result = reconcile_hashtags()

    assert _search(viewer, "leaky") == []
    assert _hashtag_found(viewer, "stale") == NOT_FOUND
    assert _links() == set()
    assert (result["posts_purged"], result["links_removed"]) == (1, 1)


def test_reconcile_keeps_payload_hashtags_beyond_the_excerpt(viewer):
    # Tracked posts are not rebuilt from the excerpt: post.created's list is complete.
    created("p1", hashtags=["beyond"], excerpt="no tags in the first 280 characters")

    assert _all_zero(reconcile_hashtags())
    assert _links() == {("p1", "beyond")}
    assert _hashtag_found(viewer, "beyond") == FOUND


def test_reconcile_leaves_a_post_the_consumer_tracked_meanwhile():
    created("p1", hashtags=["beyond"], excerpt="plain")
    assert _sync_untracked_post("p1") == (0, 0)
    assert _links() == {("p1", "beyond")}


def test_reconcile_rechecks_before_purging_or_restoring_a_hashtag():
    created("p1", hashtags=["live"], excerpt="#live")
    assert _purge_hashtag_if_unbacked("live") is False  # a public post uses it now
    assert "live" in _hashtag_docs()

    assert _restore_hashtag_if_backed("gone") is False  # its last post went away
    assert "gone" not in _hashtag_docs()


# ---- OpenSearch accelerator ----------------------------------------------------


def test_opensearch_purge_happens_only_after_commit(settings, django_capture_on_commit_callbacks):
    settings.SEARCH_USE_OPENSEARCH = True
    client = mock.MagicMock()
    with mock.patch("searchsvc.backend._os_client", return_value=client):
        with django_capture_on_commit_callbacks(execute=True):
            created("p1", hashtags=["ostag"], excerpt="#ostag")
        with django_capture_on_commit_callbacks(execute=False) as callbacks:
            updated("p1", audience="friends", excerpt="#ostag")
        client.delete.assert_not_called()
        for callback in callbacks:
            callback()

    removed = {c.kwargs["id"] for c in client.delete.call_args_list}
    assert {"post:p1", "hashtag:ostag"} <= removed


def test_reconcile_clears_hashtags_only_opensearch_still_holds(
    settings, django_capture_on_commit_callbacks
):
    settings.SEARCH_USE_OPENSEARCH = True
    client = mock.MagicMock()
    client.search.return_value = {"hits": {"hits": [{"_source": {"doc_id": "osorphan"}}]}}
    with (
        mock.patch("searchsvc.backend._os_client", return_value=client),
        django_capture_on_commit_callbacks(execute=True),
    ):
        reconcile_hashtags()

    assert "hashtag:osorphan" in {c.kwargs["id"] for c in client.delete.call_args_list}
