"""Event consumers that keep the search index in sync with source contexts.

Handler names are dedupe keys (``search:<name>``): keep them stable. Every
document type is event-order safe: posts through ``PostIndexState`` (posts.py),
everything else through ``DocState`` (indexing.py).
"""

from __future__ import annotations

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from tara_events import on_event
from tara_events.envelope import EventEnvelope

from . import backend, clients, indexing, posts, restrictions
from .models import BlockedPair, DocState, RecentSearch, SearchDocument

# ---- people and pages (profile service) -----------------------------------------


@on_event("profile.updated")
def on_profile_updated(e: EventEnvelope) -> None:
    doc = indexing.person_doc(e.subject_id, e.payload)
    indexing.apply("user", e.subject_id, indexing.occurred(e), doc)


@on_event("page.created")
def on_page_created(e: EventEnvelope) -> None:
    indexing.apply("page", e.subject_id, indexing.occurred(e), indexing.page_doc(e.payload))
    posts.sync_page_posts(e.subject_id)


@on_event("page.updated")
def on_page_updated(e: EventEnvelope) -> None:
    # Carries the page's full searchable state (name, category, status, owner),
    # so a draft or suspended page leaves search and the owner is never cleared.
    indexing.apply("page", e.subject_id, indexing.occurred(e), indexing.page_doc(e.payload))
    # Its posts follow: parked while it is hidden, back when it is published.
    posts.sync_page_posts(e.subject_id)


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


@on_event("post.hidden")  # the author's account was deactivated
def on_post_hidden(e: EventEnvelope) -> None:
    """Out of the index, without a tombstone: the payload has no audience, so it
    reads as not public. Reactivation's newer ``post.updated`` indexes it again."""
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


# ---- account lifecycle (identity, plan 08 3C) ------------------------------------------
# Deactivation (and a deletion's 30-day grace) parks the person's own documents
# (their person card, their listings, the events they host) under ``~<type>``:
# every query names the real types, so a parked document is never found, and
# reactivation puts it back unchanged. Posts are not parked here: post emits
# ``post.hidden`` for each one it hides (``on_post_hidden`` drops it) and
# ``post.unhidden`` then ``post.updated`` for each one it restores (the
# ``post.updated`` indexes it again). With ``POST_EMIT_HIDE_EVENTS`` off, post
# emits ``post.deleted`` instead. Pages and groups are shared with other
# admins and stay.
PARKED = "~"
PARKABLE = ("listing", "gathering")


def _account(e: EventEnvelope) -> str:
    return str(e.payload.get("account_id") or e.subject_id)


def _own(account_id: str, prefix: str = "") -> Q:
    return Q(doc_type=f"{prefix}user", doc_id=account_id) | Q(
        owner_id=account_id, doc_type__in=[prefix + t for t in PARKABLE]
    )


@on_event("account.deactivated")
def on_account_deactivated(e: EventEnvelope) -> None:
    account_id = _account(e)
    with transaction.atomic():
        for doc in SearchDocument.objects.select_for_update().filter(_own(account_id)):
            kind, doc_id = doc.doc_type, doc.doc_id
            SearchDocument.objects.filter(doc_type=PARKED + kind, doc_id=doc_id).delete()
            SearchDocument.objects.filter(pk=doc.pk).update(doc_type=PARKED + kind)
            if backend.opensearch_enabled():
                transaction.on_commit(lambda k=kind, i=doc_id: backend._os_delete(k, i))  # noqa: SLF001


@on_event("account.reactivated")
def on_account_reactivated(e: EventEnvelope) -> None:
    account_id = _account(e)
    with transaction.atomic():
        for doc in SearchDocument.objects.select_for_update().filter(_own(account_id, PARKED)):
            kind = doc.doc_type[len(PARKED) :]
            state = DocState.objects.filter(doc_type=kind, doc_id=doc.doc_id).first()
            newer = SearchDocument.objects.filter(doc_type=kind, doc_id=doc.doc_id).exists()
            if newer or (state is not None and not state.live):
                # Indexed again, or removed at its source, while parked: that wins.
                doc.delete()
                continue
            SearchDocument.objects.filter(pk=doc.pk).update(doc_type=kind)
            if backend.opensearch_enabled():
                transaction.on_commit(
                    lambda d=doc, k=kind: backend._os_index(  # noqa: SLF001
                        k, d.doc_id, d.title, d.body, d.owner_id, d.extra
                    )
                )


@on_event("account.deleted")
def on_account_deleted(e: EventEnvelope) -> None:
    """Erase the person from search, idempotently: their person card (with a
    tombstone, so a late ``profile.updated`` cannot bring it back), every
    document they own of any type but pages and groups, parked or not, their
    recent searches, others' recent searches that opened them, and block rows.
    Their posts and hashtags leave through post's own ``post.deleted`` events.
    """
    account_id = _account(e)
    with transaction.atomic():
        indexing.apply("user", account_id, timezone.now(), None)
        owned = SearchDocument.objects.filter(
            Q(doc_type__in=["user", PARKED + "user"], doc_id=account_id) | Q(owner_id=account_id)
        ).exclude(doc_type__in=["page", "group"])
        for doc in owned:
            if doc.doc_type.startswith(PARKED):
                doc.delete()
            else:
                backend.delete_document(doc.doc_type, doc.doc_id)
        RecentSearch.objects.filter(
            Q(account_id=account_id) | Q(doc_type="user", doc_id=account_id)
        ).delete()
        BlockedPair.objects.filter(Q(blocker_id=account_id) | Q(blocked_id=account_id)).delete()
        restrictions.forget(account_id)


# ---- moderation (Tara Intelligence 4b.20-B3) ----------------------------------------


@on_event("moderation.actioned")
def on_moderation_actioned(e: EventEnvelope) -> None:
    """A ``restrict`` or ``shadow`` on a user takes their public posts out of the
    trending counts; ``reinstate`` puts them back. Other actions and target
    types are ignored (content removals arrive as ``post.deleted``). Newest
    event wins, so a redelivered or out-of-order event changes nothing."""
    p = e.payload if isinstance(e.payload, dict) else {}
    action = p.get("action")
    if p.get("target_type") != "user":
        return
    if action not in (restrictions.RESTRICTING_ACTIONS | {restrictions.REINSTATE}):
        return
    restrictions.set_restriction(p.get("target_id"), action, p.get("case_id"), indexing.occurred(e))
