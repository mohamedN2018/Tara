"""Event consumers that keep the search index in sync with source contexts.

Handler names are dedupe keys (``search:<name>``): keep them stable. Every
document type is event-order safe: posts through ``PostIndexState`` (posts.py),
everything else through ``DocState`` (indexing.py).
"""

from __future__ import annotations

from tara_events import on_event
from tara_events.envelope import EventEnvelope

from . import clients, indexing, posts
from .models import BlockedPair

# ---- people and pages (profile service) -----------------------------------------


@on_event("profile.updated")
def on_profile_updated(e: EventEnvelope) -> None:
    doc = indexing.person_doc(e.subject_id, e.payload)
    indexing.apply("user", e.subject_id, indexing.occurred(e), doc)


@on_event("page.created")
def on_page_created(e: EventEnvelope) -> None:
    indexing.apply("page", e.subject_id, indexing.occurred(e), indexing.page_doc(e.payload))


@on_event("page.updated")
def on_page_updated(e: EventEnvelope) -> None:
    # Carries the page's full searchable state (name, category, status, owner),
    # so a draft or suspended page leaves search and the owner is never cleared.
    indexing.apply("page", e.subject_id, indexing.occurred(e), indexing.page_doc(e.payload))


# ---- groups (profile `groups` app) ------------------------------------------------


def _group(e: EventEnvelope, *, deleted: bool = False) -> None:
    group_id = str(e.payload.get("group_id") or e.subject_id)
    doc = None if deleted else indexing.group_doc(e.payload)
    indexing.apply("group", group_id, indexing.occurred(e), doc)


@on_event("group.created")
def on_group_created(e: EventEnvelope) -> None:
    _group(e)


@on_event("group.updated")
def on_group_updated(e: EventEnvelope) -> None:
    _group(e)  # a change to hidden removes the document


@on_event("group.deleted")
def on_group_deleted(e: EventEnvelope) -> None:
    _group(e, deleted=True)


# ---- posts and hashtags ------------------------------------------------------------
# Only live public posts, and hashtags from them, are indexed (see posts.py).


@on_event("post.created")
def on_post_created(e: EventEnvelope) -> None:
    posts.apply_post_event(e)


@on_event("post.deleted")  # also emitted when moderation removes a post
def on_post_deleted(e: EventEnvelope) -> None:
    posts.apply_post_event(e, deleted=True)


@on_event("post.updated")
def on_post_updated(e: EventEnvelope) -> None:
    posts.apply_post_event(e)


# ---- events (post `gatherings` app) -------------------------------------------------
# The payloads carry ids, enums and times only, so the handler reads the event's
# current state from post. That state is always the newest, and its `updated_at`
# orders concurrent handlers, so a retried old event cannot revive anything.


def _gathering(e: EventEnvelope) -> None:
    gathering_id = str(e.payload.get("gathering_id") or e.subject_id)
    state = clients.gathering_state(gathering_id)  # raises Unavailable: retried
    if state is None:  # gone for good
        indexing.apply("gathering", gathering_id, indexing.occurred(e), None)
        return
    version = indexing.when(state.get("updated_at")) or indexing.occurred(e)
    indexing.apply("gathering", gathering_id, version, indexing.gathering_doc(state))


@on_event("gathering.created")
def on_gathering_created(e: EventEnvelope) -> None:
    _gathering(e)


@on_event("gathering.updated")
def on_gathering_updated(e: EventEnvelope) -> None:
    if e.payload.get("chunk", 0):
        return  # recipient chunks after the first carry the same state
    _gathering(e)


@on_event("gathering.cancelled")
def on_gathering_cancelled(e: EventEnvelope) -> None:
    if e.payload.get("chunk", 0):
        return
    _gathering(e)


@on_event("gathering.deleted")
def on_gathering_deleted(e: EventEnvelope) -> None:
    gathering_id = str(e.payload.get("gathering_id") or e.subject_id)
    indexing.apply("gathering", gathering_id, indexing.occurred(e), None)


@on_event("gathering.rsvp")
def on_gathering_rsvp(e: EventEnvelope) -> None:
    gathering_id = str(e.payload.get("gathering_id") or e.subject_id)
    indexing.refresh_gathering_counts(gathering_id, e.payload, indexing.occurred(e))


# ---- listings (marketplace) ---------------------------------------------------------


def _listing(e: EventEnvelope) -> None:
    p = e.payload
    listing_id = str(p.get("listing_id") or e.subject_id)
    if "status" not in p and "to" not in p:
        return  # a pre-1.15 `listing.updated` ({listing_id, changed}): nothing to apply
    snapshot = {**p, "status": p.get("status") or p.get("to")}
    indexing.apply("listing", listing_id, indexing.occurred(e), indexing.listing_doc(snapshot))


@on_event("listing.created")
def on_listing_created(e: EventEnvelope) -> None:
    _listing(e)  # a draft: records the state, indexes nothing


@on_event("listing.updated")
def on_listing_updated(e: EventEnvelope) -> None:
    _listing(e)


@on_event("listing.status.changed")
def on_listing_status(e: EventEnvelope) -> None:
    _listing(e)


# ---- blocks (graph) -------------------------------------------------------------------


@on_event("user.blocked")
def on_user_blocked(e: EventEnvelope) -> None:
    p = e.payload
    BlockedPair.objects.get_or_create(blocker_id=p["blocker_id"], blocked_id=p["blocked_id"])


@on_event("user.unblocked")
def on_user_unblocked(e: EventEnvelope) -> None:
    p = e.payload
    BlockedPair.objects.filter(blocker_id=p["blocker_id"], blocked_id=p["blocked_id"]).delete()
