"""Bus handlers that build the phase-3 read models (WP 3.1; 03 sections 2.1, 2.2).

Each one is registered under its own ``intel_rm_*`` name, so the worker runs it once
per event id (``ProcessedEvent``) next to feed's own handlers for the same event, and
every writer (``intel.readmodels``) is newest-wins, so redelivery and reordering
change nothing.

The read models are structural (who may see what), not analytics: synthetic and
test accounts' posts, friendships and blocks are stored like any other, because an
eligibility rule that did not know a block would leak content (fail closed). Their
behaviour never reaches these tables.
"""

from __future__ import annotations

import logging

from tara_events import on_event
from tara_events.envelope import EventEnvelope

from . import ports, readmodels

logger = logging.getLogger("tara.intel.readmodels")


def _when(event: EventEnvelope):
    from feed.services import occurred_at  # one parser for every feed handler

    return occurred_at(event.occurred_at)


# ---- content (intel_content_ref) ----------------------------------------------------


def _classify(p: dict) -> None:
    """R4 WP 6.2: the post's topics from the event's excerpt (never stored), its
    hashtags, its page or group category and its original's topics."""
    from .topics import classify

    post_id = readmodels.uid(p.get("post_id"))
    if post_id is None:
        return
    excerpt = p.get("excerpt") if "excerpt" in p else None
    if excerpt is None and "hashtags" not in p:
        return  # nothing the classifier reads changed
    try:
        classify.classify_post(post_id, excerpt)
    except Exception:  # noqa: BLE001 - topics are derived data; never fail the read model
        logger.exception("topic classification failed", extra={"post_id": post_id})


@on_event("post.created")
def intel_rm_post_created(event: EventEnvelope) -> None:
    readmodels.content_created(event.payload, _when(event))
    _classify({**event.payload, "excerpt": event.payload.get("excerpt") or ""})


@on_event("post.updated")
def intel_rm_post_updated(event: EventEnvelope) -> None:
    readmodels.content_updated(event.payload, _when(event))
    _classify(event.payload)


@on_event("post.deleted")  # also a moderator's removal
def intel_rm_post_deleted(event: EventEnvelope) -> None:
    readmodels.content_deleted(event.payload.get("post_id") or event.subject_id, _when(event))


@on_event("post.hidden")
def intel_rm_post_hidden(event: EventEnvelope) -> None:
    readmodels.content_held(event.payload, _when(event), held=True)


@on_event("post.unhidden")
def intel_rm_post_unhidden(event: EventEnvelope) -> None:
    readmodels.content_held(event.payload, _when(event), held=False)


@on_event("post.approved")
@on_event("group.post.published")  # chunked: every chunk says the same thing
def intel_rm_post_approved(event: EventEnvelope) -> None:
    readmodels.content_approved(event.payload, _when(event))


@on_event("reel.state.changed")
def intel_rm_reel_state_changed(event: EventEnvelope) -> None:
    readmodels.reel_state_changed(event.payload, _when(event))


@on_event("post.reported")
def intel_rm_post_reported(event: EventEnvelope) -> None:
    readmodels.post_reported(event.payload.get("post_id"), _when(event))


@on_event("moderation.actioned")
def intel_rm_moderation_actioned(event: EventEnvelope) -> None:
    """A decision on a post (its case closes) or on a user (rule E11)."""
    p = event.payload
    target_type, action, when = p.get("target_type"), p.get("action") or "", _when(event)
    if target_type == "post":
        readmodels.post_moderated(p.get("target_id"), action, when)
    elif target_type == "user":
        if action in readmodels.RESTRICTIONS:
            readmodels.set_restriction(p.get("target_id"), action, p.get("case_id"), True, when)
        elif action == "reinstate":  # WP 3.3b
            readmodels.set_restriction(p.get("target_id"), "", p.get("case_id"), False, when)


@on_event("media.processed")
def intel_rm_media_processed(event: EventEnvelope) -> None:
    readmodels.media_processed(event.subject_id, event.payload, _when(event))


# ---- relationships ----------------------------------------------------------------


@on_event("friendship.accepted")
def intel_rm_friendship_accepted(event: EventEnvelope) -> None:
    p = event.payload
    readmodels.set_friendship(p.get("a"), p.get("b"), True, _when(event))


@on_event("friendship.removed")
def intel_rm_friendship_removed(event: EventEnvelope) -> None:
    p = event.payload
    readmodels.set_friendship(p.get("a"), p.get("b"), False, _when(event))


@on_event("user.blocked")
def intel_rm_user_blocked(event: EventEnvelope) -> None:
    p = event.payload
    readmodels.set_block(p.get("blocker_id"), p.get("blocked_id"), True, _when(event))


@on_event("user.unblocked")
def intel_rm_user_unblocked(event: EventEnvelope) -> None:
    p = event.payload
    readmodels.set_block(p.get("blocker_id"), p.get("blocked_id"), False, _when(event))


@on_event("group.created")
@on_event("group.updated")
def intel_rm_group_changed(event: EventEnvelope) -> None:
    readmodels.set_group(event.payload, _when(event))


@on_event("group.deleted")  # also a moderator's removal (status suspended)
def intel_rm_group_deleted(event: EventEnvelope) -> None:
    readmodels.set_group(event.payload, _when(event), deleted=True)


@on_event("group.member.changed")
def intel_rm_group_member_changed(event: EventEnvelope) -> None:
    readmodels.set_membership(event.payload, _when(event))
    # R4 (06 section 7): joining or leaving is an interest signal on the group's
    # category (event_weights group_join / group_leave), one bus row per change.
    p = event.payload
    state, previous = p.get("state"), p.get("previous_state")
    kind = None
    if state == "active" and previous != "active":
        kind = "group_join"
    elif previous == "active" and state != "active":
        kind = "group_leave"
    if kind:
        from . import handlers

        handlers._record(event, kind, p.get("account_id"), "group", p.get("group_id"))  # noqa: SLF001


@on_event("page.created")
@on_event("page.updated")
def intel_rm_page_changed(event: EventEnvelope) -> None:
    readmodels.set_page(event.subject_id, event.payload, _when(event))


# ---- author lifecycle (author_ref, rule E6) ----------------------------------------


def _lifecycle(event: EventEnvelope, flag: str, value: bool) -> None:
    account_id = readmodels.uid(event.payload.get("account_id") or event.subject_id)
    if account_id is None:
        return
    ports.set_author_lifecycle(account_id, flag, value, _when(event))


@on_event("account.deactivated")
def intel_rm_account_deactivated(event: EventEnvelope) -> None:
    _lifecycle(event, "deactivated", True)


@on_event("account.reactivated")
def intel_rm_account_reactivated(event: EventEnvelope) -> None:
    _lifecycle(event, "deactivated", False)


@on_event("account.suspended")
def intel_rm_account_suspended(event: EventEnvelope) -> None:
    _lifecycle(event, "suspended", True)


@on_event("account.unsuspended")
def intel_rm_account_unsuspended(event: EventEnvelope) -> None:
    _lifecycle(event, "suspended", False)


@on_event("account.registered")
def intel_rm_account_registered(event: EventEnvelope) -> None:
    """WP 4.4: the account's registration time (suspect engagement, ``integrity``)."""
    account_id = readmodels.uid(event.subject_id)
    if account_id is not None:
        ports.set_registered_at(account_id, _when(event))
