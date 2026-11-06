"""Feed fan-out-on-write + read.

On `post.created`, resolve the author's audience from Graph and write a FeedItem
(with a denormalized snapshot) into each recipient's feed, labelled with why it
got there: `self` (the author), `friend` or `follow`. High-follower accounts are
capped (FANOUT_MAX_RECIPIENTS) — a real system switches those to
fan-out-on-read (Phase 9); we log what was dropped rather than silently
truncate. The author's own item is never dropped, and friends go before
followers.

Who receives what (matches Post's `visible_to_viewer`):

    public, followers -> author + friends + followers
    friends           -> author + friends
    only_me, unknown  -> author only (fail closed)

Every other row is backed by the relationship its reason names: fan-out labels
it, and unfollow, unfriend, new friendships and blocks keep it true. That is what
lets an edit that narrows the audience drop the rows it no longer reaches from
the feed's own data, with no Graph call (`_drop_rows_outside`).
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from intel import readmodels as intel_readmodels

from . import events, ranking, readmodels
from .clients import GraphUnavailable, Relationship, fanout_audience, relationship
from .models import FeedItem, PostState, RelationshipFlag

logger = logging.getLogger("tara.feed.services")

Reason = FeedItem.Reason

# Audiences fanned out beyond the author. Anything else (only_me, or an audience
# this service does not know yet) reaches the author alone.
_FRIENDS_ONLY = "friends"
_FRIENDS_AND_FOLLOWERS = frozenset({"public", "followers"})

# What any recipient may see of a post they might no longer be allowed to open:
# ids and enums only, never the excerpt or the media ids.
_ID_KEYS = ("post_id", "author_id", "author_type", "type", "audience", "created_at")

_IN_CHUNK = 1000


def _norm(account_id) -> str:
    return str(uuid.UUID(str(account_id)))


def _snapshot(payload: dict) -> dict:
    return {
        "post_id": payload["post_id"],
        "author_id": payload["author_id"],
        "author_type": payload.get("author_type", "user"),
        "type": payload.get("type", "text"),
        "audience": payload.get("audience", "public"),
        "excerpt": payload.get("excerpt", ""),
        "media_ids": payload.get("media_ids", []),
        # Topic signal for Tara Intelligence (WP 2.7). Content, like the excerpt: only
        # public items and the author's own keep it (``snapshot_for``).
        "hashtags": _hashtags(payload.get("hashtags")),
        "created_at": payload.get("created_at"),
    }


def _hashtags(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted({str(t) for t in value if isinstance(t, str) and t})


def shows_content(snapshot: dict, recipient_id, author_id) -> bool:
    """Content stays only on public posts and on the author's own item.

    Anything else may have become invisible to the recipient since fan-out (an
    unfriend, an audience change); the client hydrates it through
    `/posts/batch/`, which checks visibility now. A page's post keeps ids only
    too: the page may have been set back to draft, suspended or deleted since.
    """
    if str(recipient_id) == str(author_id):
        return True
    return snapshot.get("audience") == "public" and snapshot.get("author_type", "user") != "page"


def snapshot_for(snapshot: dict, recipient_id, author_id) -> dict:
    """The part of ``snapshot`` that ``recipient_id`` may be given."""
    if shows_content(snapshot, recipient_id, author_id):
        return snapshot
    return {k: snapshot[k] for k in _ID_KEYS if k in snapshot}


def _recipients(author_id: str, audience: str, author_type: str = "user") -> list[tuple[str, str]]:
    """``[(recipient, reason)]``: the author first, then friends, then followers
    (a page's followers for a post published as a page)."""
    out = [(author_id, Reason.SELF)]
    if audience != _FRIENDS_ONLY and audience not in _FRIENDS_AND_FOLLOWERS:
        if audience != "only_me":
            logger.warning("unknown audience; author only", extra={"audience": audience})
        return out

    # raises GraphUnavailable -> consumer retries
    data = (
        fanout_audience(author_id)
        if author_type == "user"
        else fanout_audience(author_id, target_type=author_type)
    )
    friends = {_norm(x) for x in data.get("friends", [])} - {author_id}
    out += [(r, Reason.FRIEND) for r in sorted(friends)]
    if audience in _FRIENDS_AND_FOLLOWERS:
        followers = {_norm(x) for x in data.get("followers", [])} - friends - {author_id}
        out += [(r, Reason.FOLLOW) for r in sorted(followers)]
    return out


def occurred_at(value) -> datetime:
    """An event's ``occurred_at`` as an aware datetime (now, if unreadable)."""
    try:
        when = parse_datetime(value or "")
    except (TypeError, ValueError):
        when = None
    if when is None:
        return timezone.now()
    return when.replace(tzinfo=UTC) if timezone.is_naive(when) else when


def record_post_state(
    post_id: str,
    when: datetime,
    *,
    deleted: bool = False,
    audience=None,
    excerpt=None,
    hashtags=None,
) -> bool:
    """Store a post's newest edit or delete. False when ``when`` is older than
    what is stored: the event is stale and must change nothing."""
    with transaction.atomic():
        state, created = PostState.objects.select_for_update().get_or_create(
            post_id=post_id,
            defaults={
                "occurred_at": when,
                "deleted": deleted,
                "audience": audience or "",
                "excerpt": excerpt or "",
                "hashtags": _hashtags(hashtags) if hashtags is not None else None,
            },
        )
        if created:
            return True
        if when < state.occurred_at:
            return False
        state.occurred_at, state.deleted = when, deleted
        if audience is not None:
            state.audience = audience
        if excerpt is not None:
            state.excerpt = excerpt
        if hashtags is not None:
            state.hashtags = _hashtags(hashtags)
        state.save()
        return True


def fan_out_post(payload: dict) -> int:
    """Distribute a created post to recipient feeds. Returns count of new items.

    Any stored state is newer than the creation (an edit or a delete processed
    before a retried ``post.created``), so it wins over the payload.
    """
    author_id = _norm(payload["author_id"])
    post_id = payload["post_id"]
    state = PostState.objects.filter(post_id=post_id).first()
    if state is not None:
        if state.deleted:
            logger.info("post deleted before its fan-out; skipped", extra={"post_id": post_id})
            return 0
        payload = {
            **payload,
            "audience": state.audience or payload.get("audience"),
            "excerpt": state.excerpt,
            "hashtags": state.hashtags if state.hashtags is not None else payload.get("hashtags"),
        }
    audience = payload.get("audience", "public")
    created_at = parse_datetime(payload.get("created_at") or "") or timezone.now()

    recipients = _recipients(author_id, audience, payload.get("author_type") or "user")
    cap = max(settings.FANOUT_MAX_RECIPIENTS, 1)  # the author's own item always fits
    total = len(recipients)
    if total > cap:
        logger.warning("fan-out capped", extra={"post_id": post_id, "total": total, "cap": cap})
        recipients = recipients[:cap]  # the author is first, so it is always kept

    existing = {
        str(r)
        for r in FeedItem.objects.filter(
            post_id=post_id, recipient_id__in=[r for r, _ in recipients]
        ).values_list("recipient_id", flat=True)
    }
    new = [(r, reason) for r, reason in recipients if r not in existing]
    if not new:
        return 0

    snapshot = _snapshot(payload)
    score = readmodels.score_for(post_id)  # engagement may be counted before the fan-out ran
    with transaction.atomic():
        FeedItem.objects.bulk_create(
            [
                FeedItem(
                    recipient_id=r,
                    post_id=post_id,
                    author_id=author_id,
                    reason=reason,
                    snapshot=snapshot_for(snapshot, r, author_id),
                    score=score,
                    post_created_at=created_at,
                )
                for r, reason in new
            ],
            ignore_conflicts=True,
        )
        if total > cap:
            # Tara Intelligence follow_pull (WP 3.4) reaches the followers left out.
            intel_readmodels.record_fanout_capped(
                post_id, author_id, audience, total, cap, created_at
            )
        # One summary event: only the realtime bridge consumes it, and it pushes
        # to each recipient's socket itself.
        events.emit(
            "feed.item.added",
            subject_id=str(post_id),
            payload={
                "recipients": [r for r, _ in new],
                "post_id": str(post_id),
                "author_id": author_id,
            },
            partition_key=f"post:{post_id}",
        )
    return len(new)


def remove_author_from_recipient(recipient_id: str, author_id: str) -> None:
    FeedItem.objects.filter(recipient_id=recipient_id, author_id=author_id).delete()


def remove_follow_items(follower_id: str, author_id: str) -> int:
    """After an unfollow, drop only what the follow brought in (never friend items)."""
    deleted, _ = FeedItem.objects.filter(
        recipient_id=follower_id, author_id=author_id, reason=Reason.FOLLOW
    ).delete()
    return deleted


def hold_post(post_id: str, when: datetime) -> bool:
    """``post.hidden``: keep the post's rows, show them nowhere. False when stale."""
    with transaction.atomic():
        state, created = PostState.objects.select_for_update().get_or_create(
            post_id=post_id, defaults={"occurred_at": when, "hidden": True, "hidden_at": when}
        )
        if created:
            return True
        if state.hidden_at is not None and when < state.hidden_at:
            return False
        state.hidden, state.hidden_at = True, when
        state.save(update_fields=["hidden", "hidden_at"])
        return True


def release_post(payload: dict, when: datetime) -> int:
    """``post.unhidden``: show the kept rows again and fan the post out to anyone
    who has no row for it (rows a ``post.deleted`` from an older release dropped,
    or a fan-out the hide cut short). Returns the count of new rows; nothing when
    the event is stale.

    The payload is the post as it is at ``when``, so it replaces an older stored
    audience and excerpt. A stored delete older than ``when`` is the one an older
    release emitted on deactivation: post sends ``post.unhidden`` only for a post
    that is live, so it is undone too.
    """
    post_id = payload["post_id"]
    with transaction.atomic():
        state, created = PostState.objects.select_for_update().get_or_create(
            post_id=post_id,
            defaults={
                "occurred_at": when,
                "hidden": False,
                "hidden_at": when,
                "audience": payload.get("audience") or "",
                "excerpt": payload.get("excerpt") or "",
                "hashtags": _hashtags(payload["hashtags"]) if "hashtags" in payload else None,
            },
        )
        if not created:
            if state.hidden_at is not None and when < state.hidden_at:
                logger.info("stale post.unhidden ignored", extra={"post_id": post_id})
                return 0
            state.hidden, state.hidden_at = False, when
            if when >= state.occurred_at:
                state.occurred_at, state.deleted = when, False
                state.audience = payload.get("audience") or state.audience
                state.excerpt = payload.get("excerpt", state.excerpt)
                if "hashtags" in payload:
                    state.hashtags = _hashtags(payload["hashtags"])
            state.save()
    return fan_out_post(payload)


def remove_post(post_id: str, when: datetime | None = None) -> None:
    if record_post_state(post_id, when or timezone.now(), deleted=True):
        FeedItem.objects.filter(post_id=post_id).delete()


def _drop_rows_outside(post_id: str, audience: str) -> int:
    """Delete the rows of ``post_id`` that ``audience`` no longer reaches.

    Decided from the rows alone (see the module docstring): public and followers
    keep everyone, since friends and followers both qualify; friends keeps the
    `friend` rows; only_me, or an audience this service does not know, keeps the
    author alone. A legacy row still labelled `follow` between friends can only
    be over-deleted. There is no re-fan-out, so a later widening edit does not
    bring deleted rows back; the post still shows on the author's profile.
    """
    if audience in _FRIENDS_AND_FOLLOWERS:
        return 0
    rows = FeedItem.objects.filter(post_id=post_id).exclude(recipient_id=F("author_id"))
    if audience == _FRIENDS_ONLY:
        rows = rows.exclude(reason=Reason.FRIEND)
    elif audience != "only_me":
        logger.warning("unknown audience on edit; author only", extra={"audience": audience})
    deleted, _ = rows.delete()
    return deleted


def update_post_excerpt(
    post_id: str,
    excerpt: str,
    audience: str | None = None,
    media_ids: list | None = None,
    when: datetime | None = None,
    hashtags: list | None = None,
) -> None:
    """Follow an edit: drop the rows the new audience no longer reaches, refresh the rest.

    ``audience`` None means the edit did not say (the stored one stays). Rows
    that may not show content keep ids only. A row whose content comes back (the
    post became public) gets its media ids from ``media_ids`` when the event
    carries them, else from the author's own item, which always keeps the full
    snapshot; with neither, they stay absent and the client hydrates the media.
    """
    if not record_post_state(
        post_id, when or timezone.now(), audience=audience, excerpt=excerpt, hashtags=hashtags
    ):
        logger.info("stale post.updated ignored", extra={"post_id": post_id})
        return
    if audience is not None:
        _drop_rows_outside(post_id, audience)
    items = list(FeedItem.objects.filter(post_id=post_id))
    if not isinstance(media_ids, list):
        media_ids = next(
            (
                i.snapshot["media_ids"]
                for i in items
                if str(i.recipient_id) == str(i.author_id)
                and isinstance(i.snapshot.get("media_ids"), list)
            ),
            None,
        )
    for item in items:
        snapshot = {**item.snapshot, "excerpt": excerpt}
        if audience is not None:
            snapshot["audience"] = audience
        if media_ids is not None:
            snapshot["media_ids"] = media_ids
        if hashtags is not None:
            snapshot["hashtags"] = _hashtags(hashtags)
        item.snapshot = snapshot_for(snapshot, item.recipient_id, item.author_id)
    FeedItem.objects.bulk_update(items, ["snapshot"], batch_size=500)


def _ex_friend_cleanup(recipient: str, author: str, *, still_follows: bool) -> None:
    items = FeedItem.objects.filter(recipient_id=recipient, author_id=author)
    if not still_follows:
        # No connection left: like after an unfollow, none of the author's posts
        # stay. A kept `friend` row would also survive a later edit to friends
        # or followers, for someone who is neither.
        items.delete()
        return
    items.filter(snapshot__audience=_FRIENDS_ONLY).delete()
    # What is left now reached them through the follow.
    items.filter(reason=Reason.FRIEND).update(reason=Reason.FOLLOW)


def apply_unfriend(a: str, b: str) -> None:
    """After an unfriend, each side keeps only what it may still see as a follower.

    A side that still follows the other keeps its public and followers-audience
    items, relabelled `follow`; friends-audience items go. A side that does not
    follow loses all of the other's items, public ones too, as after an
    unfollow. The current relationship comes from Graph; if Graph cannot
    answer, nobody is assumed to follow (fail closed — feed rows are derived
    and rebuildable).
    """
    try:
        rel = relationship(a, b)
    except GraphUnavailable:
        logger.warning("graph unavailable on unfriend; assuming no follows", exc_info=True)
        rel = Relationship()
    if rel.are_friends:
        return  # friends again since: the event is stale
    _ex_friend_cleanup(a, b, still_follows=rel.a_follows_b)
    _ex_friend_cleanup(b, a, still_follows=rel.b_follows_a)


def label_friend_items(a: str, b: str) -> int:
    """After a new friendship, items each side got by following are friend items.

    Raises GraphUnavailable (the consumer retries): until then the label stays
    `follow`, which only ever over-deletes on a later unfollow.
    """
    if not relationship(a, b).are_friends:
        return 0  # unfriended since: the event is stale
    changed = 0
    for recipient, author in ((a, b), (b, a)):
        changed += FeedItem.objects.filter(
            recipient_id=recipient, author_id=author, reason=Reason.FOLLOW
        ).update(reason=Reason.FRIEND)
    return changed


def relabel_friend_items_for(
    recipient_id: str, friend_ids: list[str], *, dry_run: bool = False
) -> int:
    """One-off data fix: `follow` items whose author is a friend become `friend`."""
    changed = 0
    for i in range(0, len(friend_ids), _IN_CHUNK):
        items = FeedItem.objects.filter(
            recipient_id=recipient_id,
            author_id__in=friend_ids[i : i + _IN_CHUNK],
            reason=Reason.FOLLOW,
        )
        changed += items.count() if dry_run else items.update(reason=Reason.FRIEND)
    return changed


MODES = ("for_you", "recent", "favorites", "following", "friends")
# What the web client asked for before modes existed, and the Home default until
# the phase-4b rotation ships (owner decisions 5 and 25). A viewer's remembered
# mode (``intel_user_preference.default_mode``, WP 4.6) wins over it.
DEFAULT_MODE = "recent"


def home_feed(recipient_id: str, mode: str = DEFAULT_MODE):
    """The chronological modes (``for_you`` is ranked: see ``ranking``).

    ``recent`` is the old order, ``favorites`` keeps authors the viewer favorites
    in Graph, ``following`` keeps accounts and pages the viewer follows, and
    ``friends`` keeps the rows that reached the viewer as a friend of the author
    (``reason=friend``, WP 4.6). Every mode leaves out what the viewer hid,
    snoozed or muted.
    """
    items = ranking.visible_items(recipient_id)
    if mode == "favorites":
        items = items.filter(
            author_id__in=readmodels.flagged_ids(recipient_id, RelationshipFlag.Kind.FAVORITE)
        )
    elif mode == "following":
        items = items.filter(
            Q(reason=Reason.FOLLOW) | Q(author_id__in=readmodels.followed_ids(recipient_id))
        ).exclude(author_id=recipient_id)
    elif mode == "friends":
        items = items.filter(reason=Reason.FRIEND).exclude(author_id=recipient_id)
    # ``-id`` breaks ties in ``post_created_at`` (keyset pages, WP 4c.8-B3).
    return items.order_by("-post_created_at", "-id")


# Realtime "new posts" peek (D4, WP 4.7): the newest rows above ``since``,
# chronological for every mode, never ranked. It reads only: no ranking session
# is written or replaced and no ads call is made.


def peek(recipient_id: str, mode: str, since: datetime | None, size: int, max_since_hours):
    """``(rows, new_count)`` for the pill. ``for_you`` peeks its own candidates,
    the viewer's fan-out rows; the chronological modes peek themselves. ``since``
    is clamped to ``max_since_hours`` ago (``peek.max_since_hours`` in the config)."""
    if mode == "for_you":
        items = ranking.visible_items(recipient_id)
    else:
        items = home_feed(recipient_id, mode)
    floor = timezone.now() - timedelta(hours=max_since_hours)
    if since is None or since < floor:
        since = floor
    # Rows that reached the viewer after ``since`` (fan-out time, not post time:
    # a post written just before the first page but fanned out after it counts).
    items = items.filter(created_at__gt=since, post_created_at__gt=floor)
    rows = list(items.order_by("-post_created_at", "-id")[:size])
    count = len(rows) if len(rows) < size else items.count()
    return rows, count
