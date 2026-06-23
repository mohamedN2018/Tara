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
