"""Search indexer + query/autocomplete tests (Postgres backend)."""

import uuid

import pytest
from django.urls import reverse

from searchsvc import backend
from searchsvc.handlers import on_listing_status, on_post_created, on_profile_updated
from searchsvc.models import SearchDocument
from tara_events.envelope import EventEnvelope

pytestmark = pytest.mark.django_db


def test_profile_indexed_and_searchable(client_for):
    acct = str(uuid.uuid4())
    on_profile_updated(
        EventEnvelope(
            event_type="profile.updated",
            subject_id=acct,
            producer="profile-service",
            payload={"handle": "nadia", "display_name": "Nadia Star"},
        )
    )
    assert SearchDocument.objects.filter(doc_type="user").count() == 1
    resp = client_for(str(uuid.uuid4())).get(
        reverse("searchsvc:search"), {"q": "nadia", "type": "users"}
    )
    # "users" is not a valid doc_type (it's "user") -> type ignored, still matches.
    assert any(r["title"].startswith("nadia") for r in resp.json()["data"]["results"])


def test_public_post_indexed_private_not(client_for):
    author = str(uuid.uuid4())
    on_post_created(
        EventEnvelope(
            event_type="post.created",
            subject_id="p1",
            producer="post-service",
            payload={
                "post_id": "p1",
                "author_id": author,
                "audience": "public",
                "excerpt": "hello searchable world",
                "hashtags": ["tara"],
            },
        )
    )
    on_post_created(
        EventEnvelope(
            event_type="post.created",
            subject_id="p2",
            producer="post-service",
            payload={
                "post_id": "p2",
                "author_id": author,
                "audience": "friends",
                "excerpt": "secret private",
                "hashtags": [],
            },
        )
    )
    assert SearchDocument.objects.filter(doc_type="post").count() == 1  # only public
    assert SearchDocument.objects.filter(doc_type="hashtag", doc_id="tara").exists()

    resp = client_for(str(uuid.uuid4())).get(
        reverse("searchsvc:search"), {"q": "searchable", "type": "post"}
    )
    assert len(resp.json()["data"]["results"]) == 1
    assert resp.json()["data"]["degraded"] is False


def test_listing_deindexed_when_not_active():
    backend.index_document("listing", "l1", title="Bike", body="Bike", owner_id=None)
    on_listing_status(
        EventEnvelope(
            event_type="listing.status.changed",
            subject_id="l1",
            producer="marketplace-service",
            payload={"listing_id": "l1", "from": "active", "to": "sold"},
        )
    )
    assert not SearchDocument.objects.filter(doc_type="listing", doc_id="l1").exists()


def test_autocomplete(client_for):
    backend.index_document("user", "u1", title="naomi", body="")
    backend.index_document("user", "u2", title="nathan", body="")
    backend.index_document("user", "u3", title="bob", body="")
    resp = client_for(str(uuid.uuid4())).get(reverse("searchsvc:autocomplete"), {"q": "na"})
    titles = {r["title"] for r in resp.json()["data"]["results"]}
    assert titles == {"naomi", "nathan"}


# ---- what must never be found ------------------------------------------------


def _event(event_type, payload, subject=None):
    return EventEnvelope(
        event_type=event_type,
        subject_id=subject or payload.get("listing_id", "s"),
        producer="test",
        payload=payload,
    )


def test_listing_is_searchable_only_while_active():
    from searchsvc.handlers import on_listing_status
    from searchsvc.models import SearchDocument

    payload = {"listing_id": "l1", "title": "chair", "seller_id": None}
    on_listing_status(_event("listing.status.changed", {**payload, "to": "active"}))
    assert SearchDocument.objects.filter(doc_id="l1").exists()
    on_listing_status(_event("listing.status.changed", {**payload, "to": "sold"}))
    assert not SearchDocument.objects.filter(doc_id="l1").exists()


def test_private_profile_leaves_the_index():
    from searchsvc.handlers import on_profile_updated
    from searchsvc.models import SearchDocument

    subject = "01a19eed-9326-7fd4-a005-3fb0712a234c"
    on_profile_updated(_event("profile.updated", {"handle": "h"}, subject))
    assert SearchDocument.objects.filter(doc_type="user").exists()
    on_profile_updated(_event("profile.updated", {"handle": "h", "visibility": "private"}, subject))
    assert not SearchDocument.objects.filter(doc_type="user").exists()


def test_blocked_people_are_not_returned():
    from searchsvc import backend
    from searchsvc.models import BlockedPair

    viewer = "01a19eed-9326-7fd4-a005-3fb0712a234c"
    owner = "01a19eed-9326-7fd4-a005-3fb0712a234d"
    backend.index_document("post", "p1", body="findme", owner_id=owner)
    assert backend.query("findme", viewer_id=viewer)[0]
    BlockedPair.objects.create(blocker_id=owner, blocked_id=viewer)
    assert backend.query("findme", viewer_id=viewer)[0] == []
