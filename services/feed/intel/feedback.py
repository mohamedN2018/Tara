"""FeedbackService: Interested, Not interested, More / Less like this, Mute topic and
Don't recommend this creator (04 WP 7.1, 7.2; 07 WP 7.5-B2; 06 section 10).

``act`` writes, **in one transaction**: the ``intel_feedback_action`` row (with the
exact prior state of every interest row it touches), the ``source=server`` signal
row and the interest change. ``undo`` restores that prior state exactly (it never
recomputes it) and writes the inverse event when there is one.

Effects (``feedback_effects`` in the Home config; decision 20):

=================  ==========================================================
interested         ``+interested`` on each of the item's topics (x confidence)
more_like_this     ``+more_like_this`` on each topic
less_like_this     ``less_like_this`` on each topic
not_interested     ``not_interested_topic`` on each topic and
                   ``not_interested_author`` on the creator (an owner-visible
                   change from phase 2, where it did not touch the author)
mute_topic         explicit ``muted`` row on the chosen topic: 0 recommended
                   items with it (rule E8), connected items with it as primary
                   x ``mute_primary_multiplier``
hide_creator       explicit ``hidden`` row on the creator: 0 recommended items,
                   rails or people suggestions with them (graph hears
                   ``intel.creator.hidden``); a followed creator's connected
                   posts still show
=================  ==========================================================

Sensitive topics (decision 12) get no inferred delta without ``sensitive_inference``;
a mute is the user's explicit choice and is stored. Under ``personalization_off``
only the explicit, protective actions are kept (mute, hide creator): no inferred
delta and no signal row is written.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from django.db import IntegrityError, transaction
from django.utils import timezone

from . import config, interests, metrics, preferences
from .models import EventType, FeedbackAction, ItemType, UserInterest
from .signals.server import record as server_signal
from .topics import classify

ACTIONS = tuple(FeedbackAction.Action.values)
ITEM_TYPES = ("post", "reel", "video", "profile", "page")
POST_ITEMS = ("post", "reel", "video")
_EVENT = {
    "interested": EventType.INTERESTED,
    "not_interested": EventType.NOT_INTERESTED,
    "more_like_this": EventType.MORE_LIKE_THIS,
    "less_like_this": EventType.LESS_LIKE_THIS,
    "mute_topic": EventType.MUTE_TOPIC,
    "hide_creator": EventType.HIDE_CREATOR,
}
_TOPIC_EFFECT = {
    "interested": "interested",
    "more_like_this": "more_like_this",
    "less_like_this": "less_like_this",
    "not_interested": "not_interested_topic",
}


class FeedbackError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Item:
    """What an action needs about its item (resolved and visibility-checked first)."""

    item_type: str
    item_id: str
    author_id: str | None
    topics: tuple[tuple[int, float], ...]


def _uuid() -> uuid.UUID:
    from tara_events.envelope import uuid7

    return uuid7()


def body(row: FeedbackAction) -> dict:
    slugs = [t["slug"] for t in classify.labels(row.topic_ids or [])]
    return {
        "id": str(row.id),
        "action": row.action,
        "item_type": row.item_type,
        "item_id": str(row.item_id),
        "topics": slugs,
        "creator_id": str(row.author_id) if row.author_id else None,
        "created_at": row.created_at.isoformat(),
    }


def _emit_creator_hidden(account_id, creator_id, hidden: bool, at: datetime) -> None:
    from django.conf import settings

    if not getattr(settings, "INTEL_EMIT_R4_EVENTS", True):
        return
    from feed.events import PRODUCER
    from feed.models import OutboxEvent

    from tara_events.envelope import EventEnvelope
    from tara_events.outbox import record_event

    record_event(
        OutboxEvent,
        EventEnvelope(
            event_type="intel.creator.hidden",
            payload={
                "account_id": str(account_id),
                "creator_id": str(creator_id),
                "hidden": hidden,
                "at": at.isoformat(),
            },
            subject_id=str(account_id),
            producer=PRODUCER,
            partition_key=f"account:{account_id}",
        ),
    )


def _sensitive_ids(topic_ids) -> set[int]:
    topics = classify.load_aliases().topics
    return {int(t) for t in topic_ids if topics.get(int(t), {}).get("sensitive")}


def act(
    account_id,
    item: Item,
    action: str,
    *,
    topic_slug: str | None = None,
    surface: str = "",
    now: datetime | None = None,
) -> tuple[FeedbackAction, bool]:
    """Apply ``action``; ``(row, created)``. A live repeat returns the same row."""
    if action not in ACTIONS:
        raise FeedbackError("invalid", f"unknown action {action!r}")
    now = now or timezone.now()
    account = str(account_id)
    topic_ids = [t for t, _ in item.topics]
    chosen: int | None = None
    if action == "mute_topic":
        by_slug = {t["slug"]: tid for tid, t in classify.load_aliases().topics.items()}
        chosen = by_slug.get(topic_slug or "")
        if chosen is None or chosen not in topic_ids:
            raise FeedbackError("invalid_topic", "The topic must be one of the item's topics.")
    if action == "hide_creator" and not item.author_id:
        raise FeedbackError("invalid", "This item has no creator.")
    if item.author_id and item.author_id == account and action in ("hide_creator",):
        raise FeedbackError("invalid", "You cannot hide yourself.")
    live = FeedbackAction.objects.filter(
        account_id=account,
        item_type=item.item_type,
        item_id=item.item_id,
        action=action,
        undone_at__isnull=True,
    ).first()
    if live is not None:
        return live, False

    cfg = config.for_surface("home")
    effects, block = cfg.section("feedback_effects"), cfg.section("interests")
    pref = preferences.get(account)
    off = bool(pref.personalization_off)
    sensitive = set() if pref.sensitive_inference else _sensitive_ids(topic_ids)
    pairs: list[tuple[str, str]] = []
    if action in _TOPIC_EFFECT and not off:
        pairs += [("topic", str(t)) for t in topic_ids if t not in sensitive]
        if action == "not_interested" and item.author_id and item.author_id != account:
            pairs.append(("creator", item.author_id))
    if action == "mute_topic":
        pairs.append(("topic", str(chosen)))
    if action == "hide_creator":
        pairs.append(("creator", item.author_id))
    try:
        with transaction.atomic():
            before = interests.snapshot(account, pairs)
            row = FeedbackAction.objects.create(
                id=_uuid(),
                account_id=account,
                item_type=item.item_type,
                item_id=item.item_id,
                author_id=item.author_id,
                action=action,
                topic_ids=topic_ids,
                topic_id=chosen,
                surface=(surface or "")[:12],
                before=before,
                created_at=now,
            )
            if action in _TOPIC_EFFECT and not off:
                amount = effects[_TOPIC_EFFECT[action]]
                for topic_id, conf in item.topics:
                    if topic_id in sensitive:
                        continue
                    interests.add_inferred(
                        account, "topic", str(topic_id), amount * conf, action, now, block
                    )
                if action == "not_interested" and item.author_id and item.author_id != account:
                    interests.add_inferred(
                        account,
                        "creator",
                        item.author_id,
                        effects["not_interested_author"],
                        action,
                        now,
                        block,
                    )
                interests.invalidate(account)
            elif action == "mute_topic":
                interests.set_explicit(account, "topic", str(chosen), "muted", now)
            elif action == "hide_creator":
                interests.set_explicit(account, "creator", item.author_id, "hidden", now)
                _emit_creator_hidden(account, item.author_id, True, now)
            item_kind = item.item_type if item.item_type in ItemType.values else ItemType.POST
            server_signal(account, _EVENT[action], item_kind, item.item_id, item.author_id)
    except IntegrityError:  # a concurrent identical action won
        return (
            FeedbackAction.objects.get(
                account_id=account,
                item_type=item.item_type,
                item_id=item.item_id,
                action=action,
                undone_at__isnull=True,
            ),
            False,
        )
    metrics.feedback(action, "act")
    return row, True


def undo(account_id, action_id, *, now: datetime | None = None) -> bool:
    """Restore the exact state before the action. False when the id is not the
    caller's live action (the view answers 404)."""
    now = now or timezone.now()
    account = str(account_id)
    with transaction.atomic():
        row = (
            FeedbackAction.objects.select_for_update()
            .filter(id=action_id, account_id=account, undone_at__isnull=True)
            .first()
        )
        if row is None:
            return False
        interests.restore(account, row.before)
        row.undone_at = now
        row.save(update_fields=["undone_at"])
        if row.action == "hide_creator" and row.author_id:
            _emit_creator_hidden(account, row.author_id, False, now)
    metrics.feedback(row.action, "undo")
    return True


# ---- item resolution -----------------------------------------------------------------


def resolve_item(claims: dict, item_type: str, item_id, token: str | None) -> Item | None:
    """The item, if the viewer may give feedback on it; None is one identical 404.

    A post, reel or video: served to the viewer (serve token or ranking session) or
    on their own feed, and still visible now (``why.visible_served``, fail closed).
    A profile or page (``hide_creator`` only): a known account with no block either
    way, not the viewer."""
    from . import why

    if item_type not in ITEM_TYPES:
        return None
    try:
        item_id = str(uuid.UUID(str(item_id)))
    except ValueError:
        return None
    viewer = str(claims.get("sub"))
    if item_type in POST_ITEMS:
        found = why.visible_served(claims, item_type, item_id, token, require_served=False)
        if found is None:
            return None
        topics = tuple(classify.topics_of([item_id]).get(item_id, []))
        return Item(item_type, item_id, found.candidate.author_id, topics)
    from feed.models import AuthorRef

    from .eligibility import _BLOCKED_ONE_SQL  # noqa: PLC2701

    if item_id == viewer:
        return None
    ref = AuthorRef.objects.filter(account_id=item_id).first()
    if ref is None or not ref.active:
        return None
    if (item_type == "page") != (ref.kind == "page"):
        return None
    from django.db import connection

    with connection.cursor() as cur:
        cur.execute(_BLOCKED_ONE_SQL, [viewer, item_id, item_id, viewer])
        if cur.fetchone():
            return None
    return Item(item_type, item_id, item_id, ())


def item_for_system(item_type: str, item_id, author_id) -> Item:
    """An item named by a trusted bus event (``reel.hidden``): no visibility check."""
    item_id = str(item_id)
    topics = tuple(classify.topics_of([item_id]).get(item_id, []))
    return Item(item_type, item_id, str(author_id) if author_id else None, topics)


def muted_and_hidden(account_id) -> tuple[list[int], list[dict]]:
    """``(muted topic ids, [{account_id, hidden_at}])`` for the profile view."""
    rows = UserInterest.objects.filter(
        account_id=account_id, source="explicit", polarity__in=("muted", "hidden")
    ).values_list("dim", "key", "polarity", "updated_at")
    muted, hidden = [], []
    for dim, key, polarity, at in rows:
        if dim == "topic" and polarity == "muted":
            muted.append(int(key))
        elif dim == "creator" and polarity == "hidden":
            hidden.append({"account_id": key, "hidden_at": at.isoformat()})
    return muted, hidden
