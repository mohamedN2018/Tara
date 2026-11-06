"""Tara Intelligence event handlers, registered in feed's consumer (``consume_events``).

WP 2.5: domain events the client must never report (reactions, comments, shares,
saves, reports, follows, mutes, blocks) become ``intel_signal_event`` rows with
``source=bus``: exactly one row per event, redelivery included, because the worker
runs each handler once per event id (``ProcessedEvent``, keyed by the handler's
name; every name here starts with ``intel_`` so it never collides with feed's).

WP 2.10: ``account.deleted`` erases every ``intel_*`` row of the account and its
``redis-hot`` keys, and takes its posts out of every discovery pool at once.
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

from tara_events import on_event
from tara_events.envelope import EventEnvelope

from . import deletion, origin
from .models import EventType, ItemType, SignalSource
from .signals import store

logger = logging.getLogger("tara.intel.handlers")


def _when(event: EventEnvelope):
    from feed.services import occurred_at  # one parser for every feed handler

    return occurred_at(event.occurred_at)


def _record(
    event: EventEnvelope,
    event_type: str,
    account_id,
    item_type: str,
    item_id,
    author_id=None,
) -> bool:
    """One bus row for ``account_id``. False when nothing is stored (missing ids, or a
    registered synthetic account in an environment that refuses synthetic rows)."""
    if not account_id or not item_id:
        logger.warning("bus signal without ids; skipped", extra={"event_type": event.event_type})
        return False
    from . import preferences

    if preferences.personalization_off(account_id):
        return False  # R4: no bus row under personalization_off (decision 24)
    resolution = origin.resolve(account_id)
    if resolution.refused:
        return False
    with transaction.atomic():
        store.insert_row(
            store.SignalRow(
                account_id=account_id,
                event_type=event_type,
                item_type=item_type,
                item_id=item_id,
                author_id=author_id or None,
                source=SignalSource.BUS,
                data_origin=resolution.origin,
                occurred_at=_when(event),
                received_at=timezone.now(),
            )
        )
    if item_type == ItemType.POST and event_type in _SI_BUS:
        try:
            session_vector_bus(account_id, event_type, item_id)
        except Exception:  # noqa: BLE001 - the vector is best-effort
            logger.warning("session vector update failed", exc_info=True)
    return True


def _target_kind(target_type: str | None) -> str:
    return ItemType.PAGE if target_type == "page" else ItemType.PROFILE


@on_event("post.reacted")
def intel_on_post_reacted(event: EventEnvelope) -> None:
    p = event.payload
    _record(
        event,
        EventType.POST_LIKE,
        p.get("reactor"),
        ItemType.POST,
        p.get("post_id"),
        p.get("author_id"),
    )


@on_event("post.unreacted")
def intel_on_post_unreacted(event: EventEnvelope) -> None:
    p = event.payload
    _record(
        event,
        EventType.POST_UNLIKE,
        p.get("reactor"),
        ItemType.POST,
        p.get("post_id"),
        p.get("author_id"),
    )


@on_event("post.commented")
def intel_on_post_commented(event: EventEnvelope) -> None:
    p = event.payload
    _record(
        event,
        EventType.POST_COMMENT,
        p.get("author"),
        ItemType.POST,
        p.get("post_id"),
        p.get("post_author_id"),
    )


@on_event("comment.replied")
def intel_on_comment_replied(event: EventEnvelope) -> None:
    p = event.payload
    _record(
        event,
        EventType.POST_COMMENT,
        p.get("author"),
        ItemType.POST,
        p.get("post_id"),
        p.get("post_author_id"),
    )


@on_event("post.shared")
def intel_on_post_shared(event: EventEnvelope) -> None:
    p = event.payload
    _record(
        event,
        EventType.POST_SHARE,
        p.get("sharer"),
        ItemType.POST,
        p.get("post_id"),
        p.get("author_id"),
    )


@on_event("post.saved")
def intel_on_post_saved(event: EventEnvelope) -> None:
    """``post.saved`` (post, behind ``POST_EMIT_SAVE_EVENTS``): ids only, feed only."""
    p = event.payload
    _record(
        event,
        EventType.POST_SAVE,
        p.get("account_id"),
        ItemType.POST,
        p.get("post_id"),
        p.get("author_id"),
    )


@on_event("post.unsaved")
def intel_on_post_unsaved(event: EventEnvelope) -> None:
    p = event.payload
    _record(
        event,
        EventType.POST_UNSAVE,
        p.get("account_id"),
        ItemType.POST,
        p.get("post_id"),
        p.get("author_id"),
    )


@on_event("post.reported")
def intel_on_post_reported(event: EventEnvelope) -> None:
    """The reporter's own signal. Reporter ids never surface in any per-author view."""
    p = event.payload
    _record(
        event,
        EventType.POST_REPORT,
        p.get("reporter"),
        ItemType.POST,
        p.get("post_id"),
        p.get("owner_id"),
    )


@on_event("user.followed")
def intel_on_user_followed(event: EventEnvelope) -> None:
    p = event.payload
    _record(
        event,
        EventType.FOLLOW,
        p.get("follower"),
        _target_kind(p.get("target_type")),
        p.get("target"),
        p.get("target"),
    )


@on_event("user.unfollowed")
def intel_on_user_unfollowed(event: EventEnvelope) -> None:
    p = event.payload
    _record(
        event,
        EventType.UNFOLLOW,
        p.get("follower"),
        _target_kind(p.get("target_type")),
        p.get("target"),
        p.get("target"),
    )


@on_event("relationship.muted")
def intel_on_relationship_muted(event: EventEnvelope) -> None:
    p = event.payload
    _record(
        event,
        EventType.MUTE,
        p.get("actor_id"),
        ItemType.PROFILE,
        p.get("target_id"),
        p.get("target_id"),
    )


@on_event("relationship.unmuted")
def intel_on_relationship_unmuted(event: EventEnvelope) -> None:
    p = event.payload
    _record(
        event,
        EventType.UNMUTE,
        p.get("actor_id"),
        ItemType.PROFILE,
        p.get("target_id"),
        p.get("target_id"),
    )


@on_event("user.blocked")
def intel_on_user_blocked(event: EventEnvelope) -> None:
    p = event.payload
    _record(
        event,
        EventType.BLOCK,
        p.get("blocker_id"),
        ItemType.PROFILE,
        p.get("blocked_id"),
        p.get("blocked_id"),
    )


@on_event("user.unblocked")
def intel_on_user_unblocked(event: EventEnvelope) -> None:
    p = event.payload
    _record(
        event,
        EventType.UNBLOCK,
        p.get("blocker_id"),
        ItemType.PROFILE,
        p.get("blocked_id"),
        p.get("blocked_id"),
    )


@on_event("account.deleted")
def intel_on_account_deleted(event: EventEnvelope) -> None:
    """Erase the account from Tara Intelligence (idempotent; Redis down -> retried)."""
    account_id = event.payload.get("account_id") or event.subject_id
    counts = deletion.erase_account(account_id)
    logger.info("intel erased account", extra={"account_id": str(account_id), **counts})


# ---- R4 consumers (04 WP 5.5, 6.6/6.7, 7.2; 07 WP 6.5-B2, 8.7-B2) -----------------------

_SI_BUS = {
    EventType.POST_LIKE: "explicit_weight",
    EventType.POST_COMMENT: "explicit_weight",
    EventType.POST_SHARE: "explicit_weight",
    EventType.POST_SAVE: "explicit_weight",
    EventType.POST_REPORT: "negative_weight",
    EventType.POST_HIDE: "negative_weight",
}


def session_vector_bus(account_id, event_type: str, post_id, now=None) -> bool:
    """06 section 4.4: a bus consumption (like, comment, share, save) adds
    ``explicit_weight`` to the account's ``feed:si``; a report or a hide subtracts
    ``negative_weight``. One read of the item's topic, format and author (the bus has
    no serve token). Nothing for ``personalization_off``; a sensitive topic is not
    counted without the opt-in."""
    from django.db import connection

    from . import config, preferences, session_ctx
    from .ranking import serve_tokens
    from .topics import classify

    key = _SI_BUS.get(event_type)
    if key is None or not account_id or not post_id:
        return False
    pref = preferences.get(account_id)
    if pref.personalization_off:
        return False
    with connection.cursor() as cur:
        cur.execute(
            "SELECT c.type, c.author_id, (SELECT topic_id FROM intel_content_topic t "
            "WHERE t.post_id = c.post_id ORDER BY confidence DESC, topic_id LIMIT 1) "
            "FROM intel_content_ref c WHERE c.post_id = %s",
            [str(post_id)],
        )
        row = cur.fetchone()
    if row is None:
        return False
    kind, author, topic_id = row
    block = config.for_surface("home").section("session_interest")
    topics = classify.load_aliases().topics
    sensitive = bool(topic_id and topics.get(int(topic_id), {}).get("sensitive"))
    deltas = session_ctx.si_deltas(
        topic_id=topic_id,
        fmt=kind,
        author_prefix=serve_tokens.author_prefix(author) if author else None,
        weight=block[key],
        sensitive=sensitive and not pref.sensitive_inference,
    )
    return session_ctx.si_update(account_id, deltas, 1, now or timezone.now(), block)


@on_event("account.updated")
def intel_on_account_updated(event: EventEnvelope) -> None:
    """The account language read model (WP 6.6/6.7): the cold-start language of
    recommended items. Newest wins; only ``language`` is read (never DOB or gender)."""
    from django.db import connection

    p = event.payload
    account = p.get("account_id") or event.subject_id
    language = p.get("language")
    if not account or "language" not in (p.get("changed") or []) or language not in ("ar", "en"):
        return
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO intel_account_language (account_id, language, event_at) "
            "VALUES (%s, %s, %s) ON CONFLICT (account_id) DO UPDATE SET "
            "language = EXCLUDED.language, event_at = EXCLUDED.event_at "
            "WHERE intel_account_language.event_at <= EXCLUDED.event_at",
            [str(account), language, _when(event)],
        )


@on_event("intel.experiment.exposed")
def intel_on_experiment_exposed(event: EventEnvelope) -> None:
    """WP 5.5: another service served an account an experiment variant for the first
    time; one ``intel_experiment_exposure`` row (idempotent)."""
    from . import experiments

    p = event.payload
    if not p.get("experiment_key") or not p.get("account_id") or not p.get("variant"):
        return
    from feed.services import occurred_at

    experiments.record_exposure(
        p["experiment_key"],
        p["account_id"],
        p["variant"],
        str(p.get("surface") or ""),
        when=occurred_at(p.get("exposed_at")) if p.get("exposed_at") else _when(event),
    )


@on_event("search.queried")
def intel_on_search_queried(event: EventEnvelope) -> None:
    """WP 8.7-B2 (decision 7): only while the account's own ``search_signal`` is on (and
    personalization is not off), the hashed terms are matched to topic ids through the
    keyword and hashtag aliases; the topics of the last ``search_queries`` searches go
    into ``feed:si`` for the current visit. No digest and no text is stored."""
    from . import config, preferences, search_signal

    p = event.payload
    account = p.get("account_id")
    if not account:
        return
    pref = preferences.get(account)
    if not pref.search_signal or pref.personalization_off:
        return
    search_signal.record(account, p.get("term_keys") or [], config.for_surface("home"))


@on_event("reel.hidden")
def intel_on_reel_hidden(event: EventEnvelope) -> None:
    """WP 7.2: hiding a reel is "Not interested" on it (topics -4, creator -2)."""
    from . import feedback

    p = event.payload
    viewer, post_id = p.get("viewer_id"), p.get("post_id")
    if not viewer or not post_id:
        return
    item = feedback.item_for_system("reel", post_id, p.get("author_id"))
    try:
        feedback.act(viewer, item, "not_interested", surface="reels")
    except feedback.FeedbackError:
        logger.warning("reel.hidden not applied", extra={"post_id": str(post_id)})


# Phase 3 read models (WP 3.1): registered with this module, so the consumer's
# ``import intel.handlers`` binds their event types too.
from . import readmodel_handlers  # noqa: E402, F401
