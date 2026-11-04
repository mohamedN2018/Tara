"""Account lifecycle consumers (identity 3C): deactivation drops the person's
documents from search until reactivation; deletion erases them."""

import uuid

import pytest
from django.utils import timezone

from searchsvc import handlers
from searchsvc.models import DocState, RecentSearch, SearchDocument
from searchsvc.tests.test_search_v2 import (  # noqa: F401 - no_graph is an autouse fixture
    acct,
    ev,
    ids,
    listing,
    no_graph,
    person,
    public_post,
    search,
)

pytestmark = pytest.mark.django_db


def _event(event_type: str, account_id: str, at: int = 100):
    return ev(event_type, account_id, {"account_id": account_id}, at)


@pytest.fixture
def viewer():
    return acct()


@pytest.fixture
def api(client_for, viewer):
    return client_for(viewer)


def test_deactivation_parks_the_person_and_reactivation_restores(api):
    me, other = acct(), acct()
    person(me, "Hidden Person")
    person(other, "Hidden Other")
    listing_id = str(uuid.uuid4())
    listing(listing_id, "Hidden sofa", seller=me)
    assert me in ids(search(api, "Hidden Person"))
    assert listing_id in ids(search(api, "Hidden sofa"))

    handlers.on_account_deactivated(_event("account.deactivated", me))
    handlers.on_account_deactivated(_event("account.deactivated", me))  # idempotent
    assert me not in ids(search(api, "Hidden Person"))
    assert listing_id not in ids(search(api, "Hidden sofa"))
    assert other in ids(search(api, "Hidden Other"))
    assert SearchDocument.objects.filter(doc_type="~user", doc_id=me).count() == 1

    handlers.on_account_reactivated(_event("account.reactivated", me))
    handlers.on_account_reactivated(_event("account.reactivated", me))
    assert me in ids(search(api, "Hidden Person"))
    assert listing_id in ids(search(api, "Hidden sofa"))
    assert not SearchDocument.objects.filter(doc_type__startswith="~").exists()


def test_hidden_post_leaves_the_index_and_comes_back_with_its_update(api):
    """post.hidden (deactivation) is no tombstone: reactivation's newer
    post.updated indexes the post again, hashtags included."""
    me, post_id = acct(), str(uuid.uuid4())
    public_post(post_id, "Hidden harbour #marina", author=me, hashtags=["marina"], at=10)
    assert post_id in ids(search(api, "Hidden harbour"))

    hidden = {"post_id": post_id, "author_id": me, "reason": "account_deactivated"}
    handlers.on_post_hidden(ev("post.hidden", post_id, hidden, 20))
    handlers.on_post_hidden(ev("post.hidden", post_id, hidden, 20))  # idempotent
    assert post_id not in ids(search(api, "Hidden harbour"))

    updated = {
        "post_id": post_id,
        "author_id": me,
        "audience": "public",
        "excerpt": "Hidden harbour #marina",
        "hashtags": ["marina"],
        "type": "text",
        "media_ids": [],
    }
    handlers.on_post_updated(ev("post.updated", post_id, updated, 30))
    assert post_id in ids(search(api, "Hidden harbour"))
    handlers.on_post_hidden(ev("post.hidden", post_id, hidden, 20))  # stale retry: ignored
    assert post_id in ids(search(api, "Hidden harbour"))


def test_a_removal_while_parked_wins_over_the_parked_copy(api):
    me = acct()
    listing_id = str(uuid.uuid4())
    listing(listing_id, "Sold chair", seller=me)
    handlers.on_account_deactivated(_event("account.deactivated", me))
    listing(listing_id, "Sold chair", seller=me, status="sold", at=200)  # removed at source
    handlers.on_account_reactivated(_event("account.reactivated", me))
    assert listing_id not in ids(search(api, "Sold chair"))
    assert not SearchDocument.objects.filter(doc_id=listing_id).exists()


def test_deletion_erases_documents_history_and_cannot_be_revived(api, viewer):
    me = acct()
    person(me, "Erased Person")
    post_id = str(uuid.uuid4())
    public_post(post_id, "erased words here", author=me)
    RecentSearch.objects.create(
        account_id=me, kind=RecentSearch.Kind.QUERY, query="x", created_at=timezone.now()
    )
    RecentSearch.objects.create(
        account_id=viewer,
        kind=RecentSearch.Kind.ENTITY,
        doc_type="user",
        doc_id=me,
        created_at=timezone.now(),
    )
    handlers.on_account_deactivated(_event("account.deactivated", me))  # parked first

    handlers.on_account_deleted(_event("account.deleted", me, at=300))
    handlers.on_account_deleted(_event("account.deleted", me, at=300))  # idempotent
    assert not SearchDocument.objects.filter(doc_id=me).exists()
    assert not SearchDocument.objects.filter(owner_id=me).exists()
    assert not RecentSearch.objects.filter(account_id=me).exists()
    assert not RecentSearch.objects.filter(doc_id=me).exists()
    assert DocState.objects.get(doc_type="user", doc_id=me).live is False

    # A profile.updated that was still in flight cannot bring the person back.
    person(me, "Erased Person", at=10)
    assert me not in ids(search(api, "Erased Person"))
