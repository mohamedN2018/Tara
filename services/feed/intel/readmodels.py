"""Writers of the phase-3 read models (03 sections 2.1, 2.2; WP 3.1).

Every writer is idempotent and newest-wins: it changes a row only when its event is
at least as new as the guard time stored for that part of the row, so a redelivered
or reordered event changes nothing. The bus handlers (``intel.readmodel_handlers``)
and the backfills (WP 3.2, which pass the export's ``as_of`` as their time) share
these functions.

Ids are normalised to UUID strings; an id that is not a UUID is ignored (logged),
never stored.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from django.db import connection, transaction

from . import config, integrity, ports
from .models import (
    AccountRestriction,
    BlockPair,
    ContentRef,
    FanoutCapped,
    MediaRef,
)
from .topics import language

logger = logging.getLogger("tara.intel.readmodels")

# The time a row created by an event that does not order its content takes, so the
# first ordered event always wins over it.
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

State = ContentRef.State
Moderation = ContentRef.Moderation

AUTHOR_TYPES = frozenset({"user", "page"})
POST_TYPES = frozenset({"text", "image", "video", "link", "share", "poll", "reel"})
AUDIENCES = frozenset({"public", "friends", "followers", "only_me", "group"})
REEL_STATES = frozenset({"published", "media_missing", "media_failed", "media_elsewhere"})
GROUP_PRIVACY = frozenset({"public", "private", "hidden"})
GROUP_STATUS = frozenset({"active", "suspended", "deleted"})
MEMBER_STATES = frozenset({"active", "requested", "invited", "banned", "none"})
MEMBER_ROLES = frozenset({"owner", "admin", "moderator", "member"})
PAGE_STATUS = frozenset({"draft", "published", "suspended"})
RESTRICTIONS = frozenset({"restrict", "shadow"})
# Moderation decisions on a post that close its open case.
DECISIONS = frozenset({"remove", "approve", "dismiss", "warn", "restrict", "shadow"})


def uid(value) -> str | None:
    try:
        return str(uuid.UUID(str(value))) if value else None
    except (TypeError, ValueError, AttributeError):
        return None


def _enum(value, allowed: frozenset, default: str = "") -> str:
    return value if isinstance(value, str) and value in allowed else default


def _hashtags(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted({t.strip().lower()[:80] for t in value if isinstance(t, str) and t.strip()})


def _uuids(value) -> list[str]:
    if not isinstance(value, list):
        return []
    out = []
    for v in value:
        u = uid(v)
        if u and u not in out:
            out.append(u)
    return out


def _ts(value) -> datetime | None:
    from django.utils.dateparse import parse_datetime

    if isinstance(value, datetime):
        when = value
    else:
        try:
            when = parse_datetime(value or "")
        except (TypeError, ValueError):
            return None
    if when is None:
        return None
    return when if when.tzinfo else when.replace(tzinfo=UTC)


# ---- content ----------------------------------------------------------------------


def _locked_content(post_id: str, when: datetime) -> tuple[ContentRef, bool]:
    row = ContentRef.objects.select_for_update().filter(post_id=post_id).first()
    if row is not None:
        return row, False
    ContentRef.objects.bulk_create(
        [ContentRef(post_id=post_id, event_at=EPOCH)], ignore_conflicts=True
    )
    return ContentRef.objects.select_for_update().get(post_id=post_id), True


def _fill_identity(row: ContentRef, p: dict) -> None:
    """Fields a post never changes: taken from any event that carries them."""
    if row.author_id is None and uid(p.get("author_id")):
        row.author_id = uid(p.get("author_id"))
    if not row.author_type and p.get("author_type") in AUTHOR_TYPES:
        row.author_type = p["author_type"]
    if not row.type and p.get("type") in POST_TYPES:
        row.type = p["type"]
    if row.group_id is None and uid(p.get("group_id")):
        row.group_id = uid(p.get("group_id"))
    if row.shared_post_id is None and uid(p.get("shared_post_id")):
        row.shared_post_id = uid(p.get("shared_post_id"))
    if row.created_at is None and _ts(p.get("created_at")):
        row.created_at = _ts(p.get("created_at"))
    if row.type == "reel" and not row.reel_state:
        row.reel_state = "published"  # a reel is created published (reels.models)


def _visible_state(row: ContentRef, deleted: bool) -> str:
    if deleted:
        return State.DELETED
    return State.HIDDEN if row.held else State.LIVE


def _apply_content(row: ContentRef, p: dict, when: datetime, *, live: bool) -> bool:
    """Audience, hashtags, media and language from ``p`` when ``when`` is the newest."""
    if when < row.event_at:
        return False
    if "audience" in p:
        row.audience = _enum(p.get("audience"), AUDIENCES)
    if "hashtags" in p:
        row.hashtags = _hashtags(p.get("hashtags"))
    if "media_ids" in p:
        row.media_ids = _uuids(p.get("media_ids"))
    if "excerpt" in p:
        excerpt = p.get("excerpt")
        row.lang = language.detect(excerpt)
        # WP 4.4: the integrity signals of the text (the text itself is not stored).
        block = config.for_surface("home").section("integrity")
        row.simhash = integrity.simhash(excerpt, block["simhash_min_tokens"])
        row.bait_score = integrity.bait_score(excerpt)
    row.event_at = when
    row.state = _visible_state(row, deleted=not live)
    if "excerpt" in p:
        integrity.link_duplicates(row)
    return True


def content_created(p: dict, when: datetime) -> bool:
    """``post.created`` (and the backfill). False when nothing was newer."""
    post_id = uid(p.get("post_id"))
    if post_id is None:
        return False
    with transaction.atomic():
        row, _ = _locked_content(post_id, when)
        _fill_identity(row, p)
        if row.approval_state != "approved":
            row.approval_state = _enum(p.get("approval_state"), {"approved", "pending"}) or (
                "approved" if row.group_id is None else ""
            )
        # A delete stored with a newer time wins (``_apply_content`` refuses the
        # older creation); nothing deletes a post before it is created.
        changed = _apply_content(row, p, when, live=True)
        row.save()
        return changed


def content_updated(p: dict, when: datetime) -> bool:
    """``post.updated``: newest audience and hashtags. An update newer than a delete is
    a moderation approval (post emits ``post.updated`` then), so it revives the post."""
    post_id = uid(p.get("post_id"))
    if post_id is None:
        return False
    with transaction.atomic():
        row, _ = _locked_content(post_id, when)
        _fill_identity(row, p)
        changed = _apply_content(row, p, when, live=True)
        row.save()
        return changed


def content_deleted(post_id, when: datetime) -> bool:
    post_id = uid(post_id)
    if post_id is None:
        return False
    with transaction.atomic():
        row, _ = _locked_content(post_id, when)
        if when < row.event_at:
            return False
        row.event_at = when
        row.state = State.DELETED
        row.save()
        return True


def content_held(p: dict, when: datetime, *, held: bool) -> bool:
    """``post.hidden`` / ``post.unhidden`` (the author deactivated, reactivated)."""
    post_id = uid(p.get("post_id"))
    if post_id is None:
        return False
    with transaction.atomic():
        row, _ = _locked_content(post_id, when)
        _fill_identity(row, p)
        if row.hidden_at is not None and when < row.hidden_at:
            return False
        row.held, row.hidden_at = held, when
        if not held and when >= row.event_at:
            # post sends post.unhidden only for a live post: its payload is current.
            _apply_content(row, p, when, live=True)
        else:
            row.state = _visible_state(row, deleted=row.state == State.DELETED)
        row.save()
        return True


def content_approved(p: dict, when: datetime) -> bool:
    """``post.approved`` / ``group.post.published``: a pending group post goes out.
    Approval only ever moves forward, so order does not matter."""
    post_id = uid(p.get("post_id"))
    if post_id is None:
        return False
    with transaction.atomic():
        row, _ = _locked_content(post_id, when)
        _fill_identity(row, p)
        changed = row.approval_state != "approved"
        row.approval_state = "approved"
        row.save()
        return changed


def reel_state_changed(p: dict, when: datetime) -> bool:
    post_id = uid(p.get("post_id"))
    to_state = _enum(p.get("to_state"), REEL_STATES)
    if post_id is None or not to_state:
        return False
    with transaction.atomic():
        row, _ = _locked_content(post_id, when)
        if row.reel_state_at is not None and when < row.reel_state_at:
            return False
        if row.author_id is None and uid(p.get("author_id")):
            row.author_id = uid(p.get("author_id"))
        if not row.type:
            row.type = "reel"
        row.reel_state, row.reel_state_at = to_state, when
        row.save()
        return True


def post_reported(post_id, when: datetime) -> bool:
    """One more distinct reporter (post keeps one report per reporter and post)."""
    post_id = uid(post_id)
    if post_id is None:
        return False
    with transaction.atomic():
        row, _ = _locked_content(post_id, when)
        if row.moderation_at is not None and when < row.moderation_at:
            return False  # reported before the last decision: already judged
        row.pending_reports += 1
        row.moderation_open = True
        if row.moderation_state == Moderation.OK:
            row.moderation_state = Moderation.PENDING
        row.save()
        return True


def post_moderated(post_id, action: str, when: datetime) -> bool:
    """A moderation decision on a post closes its case and resets the report count."""
    post_id = uid(post_id)
    if post_id is None or action not in DECISIONS:
        return False
    with transaction.atomic():
        row, _ = _locked_content(post_id, when)
        if row.moderation_at is not None and when < row.moderation_at:
            return False
        if action == "remove":
            row.moderation_state = Moderation.REMOVED
        elif row.moderation_state != Moderation.REMOVED or action == "approve":
            row.moderation_state = Moderation.OK
        row.pending_reports, row.moderation_open, row.moderation_at = 0, False, when
        row.save()
        return True


def content_backfill(p: dict, when: datetime) -> bool:
    """One post from post's export (``posts.intel_export``) at the export's ``as_of``.
    The same writers as the events, so a newer event still wins."""
    post_id = uid(p.get("post_id"))
    if post_id is None:
        return False
    with transaction.atomic():
        changed = content_created(p, when)
        content_held(p, when, held=bool(p.get("held")))
        if p.get("reel_state"):
            reel_state_changed({"post_id": post_id, "to_state": p["reel_state"]}, when)
        if p.get("removed"):
            post_moderated(post_id, "remove", when)
            content_deleted(post_id, when)
        row = ContentRef.objects.select_for_update().get(post_id=post_id)
        if row.moderation_at is None or when >= row.moderation_at:
            row.moderation_open = bool(p.get("moderation_open"))
            reports = p.get("open_reports")
            row.pending_reports = reports if isinstance(reports, int) and reports > 0 else 0
            if row.moderation_state != Moderation.REMOVED:
                row.moderation_state = Moderation.PENDING if row.moderation_open else Moderation.OK
            row.save(update_fields=["moderation_open", "pending_reports", "moderation_state"])
        return changed


# ---- media ------------------------------------------------------------------------


def media_quality(top_rung, has_poster: bool, has_audio) -> float:
    """``media_quality`` block of the config: the top rendition's rung score, minus
    the poster and audio penalties, in [0, 1]."""
    block = config.for_surface("home").section("media_quality")
    score = 0.0
    for rung, value in sorted(((int(k), v) for k, v in block["rungs"].items()), reverse=True):
        if top_rung is not None and top_rung >= rung:
            score = float(value)
            break
    if not has_poster:
        score -= block["no_poster_penalty"]
    if has_audio is False:
        score -= block["no_audio_penalty"]
    return round(min(1.0, max(0.0, score)), 4)


def media_processed(media_id, p: dict, when: datetime) -> bool:
    """``media.processed`` for a video. A later event for the same media replaces it."""
    media_id = uid(media_id)
    if media_id is None or p.get("kind") != "video":
        return False
    renditions = [r for r in (p.get("renditions") or []) if isinstance(r, int)]
    top = max(renditions) if renditions else None
    variants = p.get("variants") or []
    has_poster = "poster" in variants
    has_audio = p.get("has_audio") if isinstance(p.get("has_audio"), bool) else None
    with transaction.atomic():
        row = MediaRef.objects.select_for_update().filter(media_id=media_id).first()
        if row is not None and when < row.updated_at:
            return False
        MediaRef.objects.update_or_create(
            media_id=media_id,
            defaults={
                "duration_ms": p.get("duration_ms")
                if isinstance(p.get("duration_ms"), int)
                else None,
                "width": p.get("width") if isinstance(p.get("width"), int) else None,
                "height": p.get("height") if isinstance(p.get("height"), int) else None,
                "top_rung": top,
                "has_poster": has_poster,
                "has_audio": has_audio,
                "quality": media_quality(top, has_poster, has_audio),
                "updated_at": when,
            },
        )
        return True


# ---- relationships ----------------------------------------------------------------


def _execute(sql: str, params) -> int:
    with connection.cursor() as cur:
        cur.execute(sql, params)
        return cur.rowcount


_FRIEND_SQL = """
INSERT INTO intel_friend_edge (account_id, friend_id, active, since, event_at)
VALUES (%s, %s, %s, %s, %s)
ON CONFLICT (account_id, friend_id) DO UPDATE SET
    active = EXCLUDED.active,
    since = CASE WHEN EXCLUDED.active AND NOT intel_friend_edge.active
                 THEN EXCLUDED.since ELSE intel_friend_edge.since END,
    event_at = EXCLUDED.event_at
WHERE intel_friend_edge.event_at <= EXCLUDED.event_at
"""


def set_friendship(a, b, active: bool, when: datetime, since: datetime | None = None) -> int:
    """``friendship.accepted`` / ``friendship.removed``: both directions."""
    a, b = uid(a), uid(b)
    if a is None or b is None or a == b:
        return 0
    since = since or when
    with transaction.atomic():
        return sum(_execute(_FRIEND_SQL, [x, y, active, since, when]) for x, y in ((a, b), (b, a)))


_GROUP_SQL = """
INSERT INTO intel_group_ref (group_id, privacy, status, category, member_count, event_at)
VALUES (%s, %s, %s, %s, %s, %s)
ON CONFLICT (group_id) DO UPDATE SET
    privacy = EXCLUDED.privacy, status = EXCLUDED.status, category = EXCLUDED.category,
    member_count = CASE WHEN %s THEN EXCLUDED.member_count ELSE intel_group_ref.member_count END,
    event_at = EXCLUDED.event_at
WHERE intel_group_ref.event_at <= EXCLUDED.event_at AND intel_group_ref.status <> 'deleted'
"""


def set_group(p: dict, when: datetime, *, deleted: bool = False) -> int:
    """``group.created`` / ``group.updated`` / ``group.deleted``. A deleted group is a
    tombstone. A moderator's removal arrives as ``group.deleted`` with ``suspended``."""
    group_id = uid(p.get("group_id"))
    if group_id is None:
        return 0
    status = _enum(p.get("status"), GROUP_STATUS, "active")
    if deleted and status == "active":
        status = "deleted"  # an older producer without a status
    count = p.get("member_count")
    has_count = isinstance(count, int) and count >= 0
    return _execute(
        _GROUP_SQL,
        [
            group_id,
            _enum(p.get("privacy"), GROUP_PRIVACY, "hidden"),  # unknown: the strictest
            status,
            str(p.get("category") or "")[:20],
            count if has_count else 0,
            when,
            has_count,
        ],
    )


_MEMBER_SQL = """
INSERT INTO intel_group_membership
    (account_id, group_id, state, role, notify_posts, joined_at, event_at)
VALUES (%s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (account_id, group_id) DO UPDATE SET
    state = EXCLUDED.state, role = EXCLUDED.role, notify_posts = EXCLUDED.notify_posts,
    joined_at = CASE WHEN EXCLUDED.state = 'active' AND intel_group_membership.state <> 'active'
                     THEN EXCLUDED.joined_at
                     WHEN EXCLUDED.state = 'active' THEN intel_group_membership.joined_at
                     ELSE NULL END,
    event_at = EXCLUDED.event_at
WHERE intel_group_membership.event_at <= EXCLUDED.event_at
"""


def set_membership(p: dict, when: datetime, joined_at: datetime | None = None) -> int:
    """``group.member.changed`` (the state and role after the change)."""
    group_id, account_id = uid(p.get("group_id")), uid(p.get("account_id"))
    if group_id is None or account_id is None:
        return 0
    state = _enum(p.get("state"), MEMBER_STATES, "none")
    return _execute(
        _MEMBER_SQL,
        [
            account_id,
            group_id,
            state,
            _enum(p.get("role"), MEMBER_ROLES) if state != "none" else "",
            bool(p.get("notify_posts")) and state == "active",
            (joined_at or when) if state == "active" else None,
            when,
        ],
    )


_PAGE_SQL = """
INSERT INTO intel_page_ref (page_id, owner_id, status, deleted, event_at)
VALUES (%s, %s, %s, %s, %s)
ON CONFLICT (page_id) DO UPDATE SET
    owner_id = COALESCE(EXCLUDED.owner_id, intel_page_ref.owner_id),
    status = EXCLUDED.status, deleted = EXCLUDED.deleted, event_at = EXCLUDED.event_at
WHERE intel_page_ref.event_at <= EXCLUDED.event_at
"""


def set_page(page_id, p: dict, when: datetime) -> int:
    """``page.created`` / ``page.updated``: the page's status, deletion and owner.
    The page id is an author too: its ``author_ref`` says so (``kind=page``)."""
    page_id = uid(page_id)
    if page_id is None:
        return 0
    with transaction.atomic():
        n = _execute(
            _PAGE_SQL,
            [
                page_id,
                uid(p.get("owner")),
                _enum(p.get("status"), PAGE_STATUS, "draft"),  # unknown: not published
                bool(p.get("deleted")),
                when,
            ],
        )
        ports.mark_page_author(page_id)
        return n


def _pair(a: str, b: str) -> tuple[str, str, bool]:
    """``(low, high, a_is_low)``."""
    return (a, b, True) if a < b else (b, a, False)


def set_block(blocker, blocked, active: bool, when: datetime) -> bool:
    """``user.blocked`` / ``user.unblocked``: one direction of the pair."""
    blocker, blocked = uid(blocker), uid(blocked)
    if blocker is None or blocked is None or blocker == blocked:
        return False
    low, high, blocker_is_low = _pair(blocker, blocked)
    flag, at = ("low_blocks", "low_at") if blocker_is_low else ("high_blocks", "high_at")
    with transaction.atomic():
        row = BlockPair.objects.select_for_update().filter(low=low, high=high).first()
        if row is None:
            # An unblock seen first still stores its time, so its block, retried
            # later with an older time, is refused.
            BlockPair.objects.create(low=low, high=high, since=when, **{flag: active, at: when})
            return True
        stored_at = getattr(row, at)
        if stored_at is not None and when < stored_at:
            return False
        setattr(row, flag, active)
        setattr(row, at, when)
        # With both flags off the row stays as a tombstone of the newest times, so
        # a replayed block older than its unblock is still refused.
        row.save()
        return True


def set_restriction(account_id, kind: str, case_id, active: bool, when: datetime) -> bool:
    """``moderation.actioned`` on a user: ``restrict`` / ``shadow`` set it, ``reinstate``
    lifts it (rule E11). ``warn`` and ``dismiss`` change nothing."""
    account_id = uid(account_id)
    if account_id is None or (active and kind not in RESTRICTIONS):
        return False
    with transaction.atomic():
        row = AccountRestriction.objects.select_for_update().filter(account_id=account_id).first()
        if row is None:
            # A reinstate seen first is stored inactive, so its older restriction,
            # retried later, is refused.
            AccountRestriction.objects.create(
                account_id=account_id,
                kind=kind if active else "",
                case_id=uid(case_id),
                active=active,
                since=when,
                event_at=when,
            )
            return True
        if when < row.event_at:
            return False
        if active:
            if not row.active:
                row.since = when
            row.kind, row.case_id = kind, uid(case_id) or row.case_id
        row.active, row.event_at = active, when
        row.save()
        return True


def record_fanout_capped(post_id, author_id, audience: str, total: int, cap: int, created_at):
    """Written by ``feed.services.fan_out_post`` in its own transaction when it truncates."""
    FanoutCapped.objects.bulk_create(
        [
            FanoutCapped(
                post_id=post_id,
                author_id=author_id,
                audience=audience or "",
                total=total,
                cap=cap,
                created_at=created_at,
            )
        ],
        ignore_conflicts=True,
    )
