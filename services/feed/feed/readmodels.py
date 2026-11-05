"""Read models the ranking and the feed modes need (2A, roadmap 1.7).

Every writer here is safe to run twice: the worker already skips an event id it
has processed, and the edges keep the newest ``occurred_at`` so a retried older
event changes nothing. Reactions and comments are counted the same way: a
per-(post, reactor) and per-comment state keeps the newest event, and the counters
move only when that state flips, so retries that reorder events cannot inflate them.
"""

from __future__ import annotations

import math
import uuid
from datetime import datetime

from django.db import IntegrityError, transaction
from django.db.models import F
from django.db.models.functions import Greatest

from .models import (
    Affinity,
    AuthorRef,
    CommentState,
    FeedItem,
    FollowEdge,
    PostStats,
    ReactionState,
    RelationshipFlag,
)

Kind = RelationshipFlag.Kind

# Flagging hides (spam, sexual) weigh against a post for everyone, softly.
_FLAG_WEIGHT = 0.5


def engagement_score(stats: PostStats | None) -> float:
    """The post's engagement, stored on every one of its feed rows as ``FeedItem.score``."""
    if stats is None:
        return 0.0
    raw = max(stats.reactions, 0) + 2 * max(stats.comments, 0) + 3 * max(stats.shares, 0)
    return round(math.log1p(raw) - _FLAG_WEIGHT * math.log1p(max(stats.flags, 0)), 6)


def refresh_score(post_id) -> int:
    """Copy the post's engagement onto its feed rows (``feed_item_post_idx``).

    Rows that already hold the score are not rewritten. Returns the rows changed.
    """
    score = score_for(post_id)
    return FeedItem.objects.filter(post_id=post_id).exclude(score=score).update(score=score)


def bump_stats(post_id, *, reactions=0, comments=0, shares=0, flags=0, refresh=True) -> None:
    """Add to a post's counters (never below zero) and refresh its feed rows' score.

    ``refresh=False`` leaves the feed rows to the caller (a request defers it to
    ``feed.tasks.refresh_post_score``; the ranking reads ``PostStats`` directly).
    """
    with transaction.atomic():
        PostStats.objects.get_or_create(post_id=post_id)
        PostStats.objects.filter(post_id=post_id).update(
            reactions=Greatest(F("reactions") + reactions, 0),
            comments=Greatest(F("comments") + comments, 0),
            shares=Greatest(F("shares") + shares, 0),
            flags=Greatest(F("flags") + flags, 0),
        )
        if refresh:
            refresh_score(post_id)


def score_for(post_id) -> float:
    return engagement_score(PostStats.objects.filter(post_id=post_id).first())


def bump_affinity(account_id, author_id, delta: int) -> None:
    """``account_id`` interacted with ``author_id``'s content (``delta`` may be -1)."""
    if not account_id or not author_id or str(account_id) == str(author_id):
        return
    with transaction.atomic():
        Affinity.objects.get_or_create(account_id=account_id, author_id=author_id)
        Affinity.objects.filter(account_id=account_id, author_id=author_id).update(
            interactions=Greatest(F("interactions") + delta, 0)
        )


def _uuid_or_none(value):
    try:
        return uuid.UUID(str(value)) if value else None
    except (TypeError, ValueError):
        return None


def _flip(model, lookup: dict, when: datetime, active: bool, extra: dict):
    """Newest-wins ``active`` for one key. Returns ``(delta, row)``: ``delta`` is +1
    when the key turns active, -1 when it stops, 0 for an older, repeated or first
    inactive event. ``extra`` fills fields on creation (and any still empty)."""
    row = model.objects.select_for_update().filter(**lookup).first()
    if row is None:
        try:
            with transaction.atomic():
                row = model.objects.create(**lookup, **extra, active=active, occurred_at=when)
            return (1 if active else 0), row
        except IntegrityError:  # a concurrent first event for this key won
            row = model.objects.select_for_update().get(**lookup)
    if when < row.occurred_at:
        return 0, row
    delta = int(active) - int(row.active)
    row.active, row.occurred_at = active, when
    for key, value in extra.items():
        if value is not None and getattr(row, key) is None:
            setattr(row, key, value)
    row.save()
    return delta, row


def set_reaction(post_id, reactor_id, author_id, active: bool, when: datetime) -> int:
    """``post.reacted`` / ``post.unreacted``: count the reaction only when it flips."""
    reactor = _uuid_or_none(reactor_id)
    if reactor is None:  # no reactor to key on: a plain delta, as before
        delta = 1 if active else -1
        bump_stats(post_id, reactions=delta)
        return delta
    from intel import integrity

    with transaction.atomic():
        # WP 4.4: a reaction from a brand-new account or inside a burst is excluded
        # from the rates (never penalized); thresholds in the home config.
        suspect = integrity.suspect_reaction(reactor, when) if active else None
        delta, row = _flip(
            ReactionState, {"post_id": post_id, "reactor_id": reactor}, when, active, {}
        )
        if delta == 1 and row.suspect != bool(suspect):
            row.suspect = bool(suspect)
            row.save(update_fields=["suspect"])
        if delta and row.suspect:
            return 0  # stored, never counted: its unreact subtracts nothing either
        if delta:
            bump_stats(post_id, reactions=delta)
            bump_affinity(reactor, author_id, delta)
    return delta


def set_comments(
    post_id, comment_ids, active: bool, when: datetime, *, author_id=None, post_author_id=None
) -> int:
    """Comment created, replied, deleted or restored: ``PostStats.comments`` moves
    once per comment that flips, and so does its author's affinity to the post's
    author. ``author_id`` / ``post_author_id`` describe the first id only."""
    total = 0
    with transaction.atomic():
        for n, raw in enumerate(comment_ids):
            cid = _uuid_or_none(raw)
            if cid is None:  # no comment id to key on: a plain delta, as before
                delta = 1 if active else -1
                total += delta
                if n == 0:
                    bump_affinity(author_id, post_author_id, delta)
                continue
            extra = {"post_id": post_id, "author_id": None, "post_author_id": None}
            if n == 0:
                extra["author_id"] = _uuid_or_none(author_id)
                extra["post_author_id"] = _uuid_or_none(post_author_id)
            delta, row = _flip(CommentState, {"comment_id": cid}, when, active, extra)
            if delta:
                total += delta
                bump_affinity(row.author_id, row.post_author_id, delta)
        if total:
            bump_stats(post_id, comments=total)
    return total


def _apply_newest(model, lookup: dict, when: datetime, values: dict) -> bool:
    """Upsert ``values`` unless the stored row is from a newer event."""
    with transaction.atomic():
        row = model.objects.select_for_update().filter(**lookup).first()
        if row is None:
            model.objects.create(**lookup, **values, occurred_at=when)
            return True
        if when < row.occurred_at:
            return False
        for key, value in values.items():
            setattr(row, key, value)
        row.occurred_at = when
        row.save()
        return True


def set_flag(actor_id, target_id, kind: str, active: bool, when: datetime) -> bool:
    """Record a mute or favorite edge from Graph's ``relationship.*`` events."""
    if not actor_id or not target_id or str(actor_id) == str(target_id):
        return False
    return _apply_newest(
        RelationshipFlag,
        {"actor_id": actor_id, "target_id": target_id, "kind": kind},
        when,
        {"active": active},
    )


def set_follow(follower_id, target_id, target_type: str, active: bool, when: datetime) -> bool:
    return _apply_newest(
        FollowEdge,
        {"follower_id": follower_id, "target_id": target_id},
        when,
        {"target_type": target_type or "user", "active": active},
    )


def set_searchable(account_id, searchable: bool, when: datetime) -> bool:
    return _apply_newest(AuthorRef, {"account_id": account_id}, when, {"searchable": searchable})


def forget_pair(a, b) -> None:
    """A block: nothing either side built up toward the other keeps counting."""
    for x, y in ((a, b), (b, a)):
        Affinity.objects.filter(account_id=x, author_id=y).delete()
        RelationshipFlag.objects.filter(actor_id=x, target_id=y, kind=Kind.FAVORITE).update(
            active=False
        )
        FollowEdge.objects.filter(follower_id=x, target_id=y).update(active=False)


def flagged_ids(actor_id, kind: str):
    """Ids ``actor_id`` currently mutes or favorites (a subquery)."""
    return RelationshipFlag.objects.filter(actor_id=actor_id, kind=kind, active=True).values(
        "target_id"
    )


def followed_ids(follower_id):
    return FollowEdge.objects.filter(follower_id=follower_id, active=True).values("target_id")


def non_searchable_ids():
    return AuthorRef.objects.filter(searchable=False).values("account_id")
