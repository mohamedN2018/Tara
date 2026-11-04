"""Feed ranking v1 (roadmap 1.7): a heuristic over freshness, affinity and engagement.

The "for you" mode ranks the viewer's newest ``FEED_RANK_WINDOW`` feed rows once,
on the first page, and keeps the ranked ids as a session in ``redis-hot``. Later
pages read their slice of that list through a signed opaque cursor, so posts that
arrive meanwhile never shift a page or repeat one. When the window runs out the
cursor continues in latest order below the window's oldest row. When the session
is gone (expired, replaced by a newer first page, or ``redis-hot`` down), the
cursor falls back to latest order from the session's start time and the page
says ``fallback: true`` (the client drops posts it already shows).

Score, for one row:

    3 * freshness                   2 ** -(age in hours / 24)
  + reason affinity                 self 0.3, friend 1.0, follow 0.6
  + 1.5 if the viewer favorites the author (about a day of freshness)
  + 0.25 * log(1 + interactions)    the viewer's reactions, comments, shares on the author
  - 0.75 * dislikes (at most 3)     ``dislike_creator`` / ``annoying`` hides of the author
  + 0.5 * engagement                the post's ``PostStats`` (``readmodels.engagement_score``)

With no engagement yet (every post before 1.7) this is close to chronological.
Candidates are the viewer's own fan-out rows (self, friend, follow): nothing is
recommended from outside the viewer's connections, and a row from anywhere else
whose author is ``searchable=false`` is dropped.
"""

from __future__ import annotations

import logging
import math
import uuid
from dataclasses import dataclass
from datetime import datetime

from django.conf import settings
from django.core import signing
from django.core.cache import caches
from django.db.models import Count, Q
from django.utils.dateparse import parse_datetime

from . import feedback, readmodels
from .models import Affinity, FeedItem, PostHide, PostState, PostStats, RelationshipFlag

logger = logging.getLogger("tara.feed.ranking")

Reason = FeedItem.Reason
CONNECTED = (Reason.SELF, Reason.FRIEND, Reason.FOLLOW)
REASON_AFFINITY = {Reason.SELF: 0.3, Reason.FRIEND: 1.0, Reason.FOLLOW: 0.6}

FRESHNESS_WEIGHT = 3.0
HALF_LIFE_HOURS = 24.0
FAVORITE_BONUS = 1.5
INTERACTION_WEIGHT = 0.25
DISLIKE_WEIGHT = 0.75
DISLIKE_CAP = 3
ENGAGEMENT_WEIGHT = 0.5

_SALT = "tara.feed.cursor.v1"
_MAX_ID = "ffffffff-ffff-ffff-ffff-ffffffffffff"


class InvalidCursor(Exception):
    """The cursor was not issued by this service (or was altered)."""


def visible_items(viewer_id):
    """The viewer's feed rows minus what they hid, snoozed or muted, and posts of
    deactivated accounts. Every mode starts here."""
    return (
        FeedItem.objects.filter(recipient_id=viewer_id)
        .exclude(post_id__in=PostState.objects.filter(hidden=True).values("post_id"))
        .exclude(post_id__in=feedback.hidden_post_ids(viewer_id))
        .exclude(author_id__in=feedback.snoozed_author_ids(viewer_id))
        .exclude(author_id__in=readmodels.flagged_ids(viewer_id, RelationshipFlag.Kind.MUTE))
    )


def _candidates(viewer_id):
    return visible_items(viewer_id).exclude(
        Q(author_id__in=readmodels.non_searchable_ids()) & ~Q(reason__in=CONNECTED)
    )


def author_penalties(viewer_id, author_ids) -> dict[str, int]:
    rows = (
        PostHide.objects.filter(
            account_id=viewer_id,
            author_id__in=author_ids,
            reason__in=feedback.AUTHOR_DOWNWEIGHT_REASONS,
        )
        .values("author_id")
        .annotate(n=Count("id"))
    )
    return {str(r["author_id"]): r["n"] for r in rows}


def _sort_key(item: FeedItem, rank: float):
    return (-rank, -item.post_created_at.timestamp(), str(item.id))


def rank_items(viewer_id, now: datetime, window: int | None = None) -> list[FeedItem]:
    """The viewer's newest ``window`` rows, best first. Same rows and ``now``, same order."""
    window = window or settings.FEED_RANK_WINDOW
    items = list(_candidates(viewer_id).order_by("-post_created_at", "-id")[:window])
    authors = {i.author_id for i in items}
    favorites = {
        str(t)
        for t in readmodels.flagged_ids(viewer_id, RelationshipFlag.Kind.FAVORITE).values_list(
            "target_id", flat=True
        )
    }
    interactions = {
        str(a): n
        for a, n in Affinity.objects.filter(
            account_id=viewer_id, author_id__in=authors
        ).values_list("author_id", "interactions")
    }
    dislikes = author_penalties(viewer_id, authors)
    # Live engagement: a flag counted a moment ago weighs in before its feed rows'
    # stored score is refreshed (``feed.tasks.refresh_post_score``).
    engagement = {
        str(s.post_id): readmodels.engagement_score(s)
        for s in PostStats.objects.filter(post_id__in={i.post_id for i in items})
    }

    def score(item: FeedItem) -> float:
        author = str(item.author_id)
        age_h = max((now - item.post_created_at).total_seconds() / 3600.0, 0.0)
        value = FRESHNESS_WEIGHT * math.pow(2.0, -age_h / HALF_LIFE_HOURS)
        value += REASON_AFFINITY.get(item.reason, 0.0)
        if author in favorites:
            value += FAVORITE_BONUS
        value += INTERACTION_WEIGHT * math.log1p(interactions.get(author, 0))
        value -= DISLIKE_WEIGHT * min(dislikes.get(author, 0), DISLIKE_CAP)
        value += ENGAGEMENT_WEIGHT * engagement.get(str(item.post_id), item.score or 0.0)
        return value

    return sorted(items, key=lambda i: _sort_key(i, score(i)))


# ---- cursor and session --------------------------------------------------------


def encode_cursor(data: dict) -> str:
    return signing.dumps(data, salt=_SALT, compress=True)


def decode_cursor(token: str) -> dict:
    try:
        data = signing.loads(token, salt=_SALT)
    except signing.BadSignature as exc:
        raise InvalidCursor from exc
    if not isinstance(data, dict) or data.get("k") not in ("r", "l"):
        raise InvalidCursor
    return data


def _session_key(viewer_id) -> str:
    return f"feed:rank:{viewer_id}"


def _hot():
    return caches[settings.FEED_HOT_CACHE]


def save_session(viewer_id, session: dict) -> bool:
    """One session per viewer (a new first page replaces it). False if redis-hot refused."""
    try:
        _hot().set(_session_key(viewer_id), session, timeout=settings.FEED_RANK_SESSION_TTL)
        return True
    except Exception:  # noqa: BLE001 - a full or down redis-hot only costs the ranking
        logger.warning("ranking session not stored; latest fallback", exc_info=True)
        return False


def load_session(viewer_id, sid: str) -> dict | None:
    try:
        session = _hot().get(_session_key(viewer_id))
    except Exception:  # noqa: BLE001
        logger.warning("ranking session unreadable; latest fallback", exc_info=True)
        return None
    if not isinstance(session, dict) or session.get("sid") != sid:
        return None
    return session


def _pack(ids) -> str:
    return "".join(uuid.UUID(str(i)).hex for i in ids)


def _unpack(packed: str) -> list[str]:
    return [str(uuid.UUID(packed[i : i + 32])) for i in range(0, len(packed), 32)]


# ---- pages ---------------------------------------------------------------------


@dataclass
class Page:
    items: list[FeedItem]
    next_cursor: str | None
    fallback: bool = False

    @property
    def has_more(self) -> bool:
        return self.next_cursor is not None


def _latest_cursor(item_or_key) -> str:
    if isinstance(item_or_key, FeedItem):
        at, ident = item_or_key.post_created_at.isoformat(), str(item_or_key.id)
    else:
        at, ident = item_or_key
    return encode_cursor({"k": "l", "t": at, "i": ident})


def _latest_page(viewer_id, at: str, ident: str, size: int, *, fallback: bool) -> Page:
    when = parse_datetime(at)
    if when is None:
        raise InvalidCursor
    rows = list(
        _candidates(viewer_id)
        .filter(Q(post_created_at__lt=when) | Q(post_created_at=when, id__lt=ident))
        .order_by("-post_created_at", "-id")[: size + 1]
    )
    more = len(rows) > size
    rows = rows[:size]
    return Page(rows, _latest_cursor(rows[-1]) if more and rows else None, fallback)


def _ranked_cursor(sid: str, offset: int, as_of: str) -> str:
    return encode_cursor({"k": "r", "s": sid, "o": offset, "a": as_of})


def _after_slice(session: dict, sid: str, end: int, as_of: str) -> str | None:
    if end < session["n"]:
        return _ranked_cursor(sid, end, as_of)
    if session.get("edge"):  # the window was full: older rows continue in latest order
        return _latest_cursor(tuple(session["edge"]))
    return None


def first_page(viewer_id, size: int, now: datetime) -> Page:
    ranked = rank_items(viewer_id, now)
    sid, as_of = uuid.uuid4().hex, now.isoformat()
    edge = None
    if len(ranked) >= settings.FEED_RANK_WINDOW:
        oldest = min(ranked, key=lambda i: (i.post_created_at, str(i.id)))
        edge = [oldest.post_created_at.isoformat(), str(oldest.id)]
    session = {"sid": sid, "ids": _pack(i.id for i in ranked), "n": len(ranked), "edge": edge}
    page = ranked[:size]
    if save_session(viewer_id, session):
        return Page(page, _after_slice(session, sid, len(page), as_of))
    # No session: later pages go on in latest order from now (the client drops repeats).
    more = len(ranked) > size or edge is not None
    return Page(page, _latest_cursor((as_of, _MAX_ID)) if more else None, fallback=True)


def next_page(viewer_id, token: str, size: int) -> Page:
    data = decode_cursor(token)
    if data["k"] == "l":
        return _latest_page(viewer_id, data["t"], data["i"], size, fallback=False)
    sid, offset, as_of = data.get("s"), int(data.get("o", 0)), data.get("a", "")
    session = load_session(viewer_id, sid)
    if session is None:
        return _latest_page(viewer_id, as_of, _MAX_ID, size, fallback=True)
    ids = _unpack(session["ids"])[offset : offset + size]
    rows = {str(i.id): i for i in _candidates(viewer_id).filter(id__in=ids)}
    return Page(
        [rows[i] for i in ids if i in rows], _after_slice(session, sid, offset + len(ids), as_of)
    )
