"""Stories business logic: visibility, the tray, create/delete, views, reactions,
reports, moderation and the close friends list (roadmap 1.9).

Rules:

* **One visibility rule** (``visible_to_viewer``). A hidden story is 404, never
  403. Deleted and moderator-removed stories are hidden from everyone, the
  author too. The author always sees their own live story, active or expired
  (the archive). Anyone else sees it only while it is active (24 hours), never
  across a block (either way), and only inside its audience:
  - ``public``: anyone signed in.
  - ``friends``: the author's friends (graph; graph down is "no").
  - ``close_friends``: friends the author put on their close friends list.
* **Media is private.** A photo is bound in media to the story id, restricted,
  so media asks post's visibility endpoint (``posts.internal_views``), which
  applies the same rule: an expired story's photo is 404 to everyone but the
  author. Remote calls (graph, media) run before the write transaction.
* **Events on the bus carry ids and enums only** and are written in the same
  transaction as the change.
"""

from __future__ import annotations

import logging
import uuid
from collections import OrderedDict

import requests
from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F, Q
from django.utils import timezone
from gatherings import graph
from gatherings.models import Gathering
from posts import clients as post_clients
from posts import events, media_client
from posts.clients import get_relationship
from posts.models import BlockedPair, PostMedia

from tara_common.exceptions import TaraAPIError
from tara_events.envelope import uuid7

from .models import (
    BACKGROUNDS,
    MAX_TEXT,
    REACTION_TYPES,
    STORY_TTL,
    CloseFriend,
    ReportReason,
    Story,
    StoryReaction,
    StoryReport,
    StoryView,
)

logger = logging.getLogger("tara.post.stories")

# Stories one account may post within 24 hours (any state but deleted).
MAX_STORIES_PER_DAY = 50
# Accounts shown in the tray (the viewer first, then friends).
MAX_TRAY_AUTHORS = 100
# Public stories from accounts the viewer follows (not friends): how many of
# the most recent such authors are asked about in one graph call.
MAX_FOLLOWED_CANDIDATES = 50
MAX_CLOSE_FRIENDS = 500
MAX_CLOSE_FRIENDS_PER_CALL = 50
_ATTACHABLE_STATUSES = {"processing", "ready"}


# ---- errors ----------------------------------------------------------------------


def _not_found() -> TaraAPIError:
    return TaraAPIError("Story not found.", code="not_found", http_status_code=404)


def _bad_request(message: str, code: str = "validation_error") -> TaraAPIError:
    return TaraAPIError(message, code=code, http_status_code=400)


def _unavailable() -> TaraAPIError:
    return TaraAPIError(
        "Friends could not be checked; try again.",
        code="dependency_unavailable",
        http_status_code=503,
    )


def _emit_enabled() -> bool:
    return bool(getattr(settings, "POST_EMIT_STORY_EVENTS", True))


def _emit(event_type: str, story: Story, payload: dict, *, actor_id: str | None = None) -> None:
    if not _emit_enabled():
        return
    events.emit(
        event_type,
        subject_id=str(story.id),
        payload=payload,
        actor_id=str(actor_id or story.author_id),
        partition_key=f"story:{story.id}",
    )


# ---- visibility ------------------------------------------------------------------


def blocked_ids(account_id: str) -> set[str]:
    """Accounts blocked by, or blocking, the account."""
    pairs = BlockedPair.objects.filter(
        Q(blocker_id=account_id) | Q(blocked_id=account_id)
    ).values_list("blocker_id", "blocked_id")
    return {str(a) for pair in pairs for a in pair} - {str(account_id)}


def _blocked_either_way(a: str, b: str) -> bool:
    return BlockedPair.objects.filter(
        Q(blocker_id=a, blocked_id=b) | Q(blocker_id=b, blocked_id=a)
    ).exists()


def _live() -> Q:
    return Q(deleted_at__isnull=True, moderation_status=Story.ModerationStatus.OK)


def visible_to_viewer(viewer_id: str, story: Story) -> bool:
    """The single rule, also behind media's check for the story's photo."""
    if not story.is_live:
        return False
    viewer, author = str(viewer_id), str(story.author_id)
    if viewer == author:
        return True
    if not story.is_active():
        return False
    if _blocked_either_way(viewer, author):
        return False
    if story.audience == Story.Audience.PUBLIC:
        return True
    rel = get_relationship(viewer, author)  # graph down: not friends (fail closed)
    if not rel.are_friends or rel.blocked_either_way:
        return False
    if story.audience == Story.Audience.FRIENDS:
        return True
    if story.audience == Story.Audience.CLOSE_FRIENDS:
        return CloseFriend.objects.filter(owner_id=author, friend_id=viewer).exists()
    return False


def require_visible(viewer_id: str, story_id) -> Story:
    story = Story.objects.filter(id=story_id).first()
    if story is None or not visible_to_viewer(viewer_id, story):
        raise _not_found()
    return story


def _own(author_id: str, story_id, *, lock: bool = False) -> Story:
    """The author's own live story (active or expired); anything else is 404."""
    qs = Story.objects.filter(_live(), id=story_id, author_id=author_id)
    story = (qs.select_for_update() if lock else qs).first()
    if story is None:
        raise _not_found()
    return story


# ---- reads -----------------------------------------------------------------------


def viewer_state(viewer_id: str, stories: list[Story]) -> dict:
    ids = [s.id for s in stories]
    return {
        "seen": set(
            StoryView.objects.filter(story_id__in=ids, viewer_id=viewer_id).values_list(
                "story_id", flat=True
            )
        ),
        "reactions": dict(
            StoryReaction.objects.filter(story_id__in=ids, account_id=viewer_id).values_list(
                "story_id", "reaction"
            )
        ),
    }


def followed_ids(viewer_id: str, candidates: list[str]) -> set[str]:
    """Which of ``candidates`` the viewer follows, from graph's relationship
    batch (which leaves out anyone in a block either way). Graph down: none,
    so the tray falls back to friends only (fail closed)."""
    if not candidates:
        return set()

    def _call() -> set[str]:
        resp = requests.post(
            f"{settings.GRAPH_INTERNAL_URL}/internal/v1/relationships/batch/",
            json={"viewer_id": str(viewer_id), "users": candidates, "pages": []},
            headers={"Authorization": f"Bearer {post_clients._internal_token()}"},
            timeout=settings.GRAPH_CALL_TIMEOUT,
        )
        resp.raise_for_status()
        results = resp.json().get("data", {}).get("results", {}) or {}
        return {str(k) for k, v in results.items() if isinstance(v, dict) and v.get("following")}

    try:
        return post_clients._breaker.call(_call)
    except Exception:  # noqa: BLE001 - circuit open, timeout, error: friends only
        logger.warning("graph follow lookup failed", exc_info=True)
        return set()


def tray(viewer_id: str) -> tuple[list[dict], dict]:
    """Active stories the viewer may see, grouped by author: the viewer's own
    first, then authors with stories the viewer has not seen, newest first.
    Returns the groups and the viewer's state (seen, reactions) for them.

    The tray covers the viewer, their friends, and the public stories of
    accounts they follow (graph). It fails closed, one graph lookup at a time:
    if only the follow lookup fails, the tray holds the viewer's own and their
    friends' stories (no followed accounts); if the friends lookup also fails
    (graph down), only the viewer's own stories. Each group's stories run
    oldest first.
    """
    viewer = str(viewer_id)
    blocked = blocked_ids(viewer)
    friends = graph.friend_ids(viewer) or set()
    friends -= blocked
    friends.discard(viewer)
    now = timezone.now()
    # Authors with a live public story who are not friends: ask graph which of
    # the most recent ones the viewer follows.
    candidates: list[str] = []
    for author in (
        Story.objects.filter(_live(), expires_at__gt=now, audience=Story.Audience.PUBLIC)
        .exclude(author_id__in=[viewer, *friends, *blocked])
        .order_by("-created_at")
        .values_list("author_id", flat=True)[: MAX_FOLLOWED_CANDIDATES * 10]
    ):
        author = str(author)
        if author not in candidates:
            candidates.append(author)
            if len(candidates) >= MAX_FOLLOWED_CANDIDATES:
                break
    followed = followed_ids(viewer, candidates) - blocked - friends - {viewer}
    close_of = {
        str(o)
        for o in CloseFriend.objects.filter(
            friend_id=viewer, owner_id__in=list(friends)
        ).values_list("owner_id", flat=True)
    }
    qs = (
        Story.objects.filter(_live(), expires_at__gt=now)
        .filter(
            Q(author_id=viewer)
            | Q(
                author_id__in=list(friends),
                audience__in=(Story.Audience.PUBLIC, Story.Audience.FRIENDS),
            )
            | Q(author_id__in=list(close_of), audience=Story.Audience.CLOSE_FRIENDS)
            | Q(author_id__in=list(followed), audience=Story.Audience.PUBLIC)
        )
        .order_by("author_id", "created_at", "id")
    )
    groups: OrderedDict[str, list[Story]] = OrderedDict()
    for story in qs:
        groups.setdefault(str(story.author_id), []).append(story)
    stories = [s for group in groups.values() for s in group]
    state = viewer_state(viewer, stories)
    result = []
    for author, items in groups.items():
        result.append(
            {
                "author_id": author,
                "stories": items,
                "has_unseen": author != viewer and any(s.id not in state["seen"] for s in items),
                "latest_at": max(s.created_at for s in items),
            }
        )
    result.sort(key=lambda g: g["latest_at"], reverse=True)
    result.sort(key=lambda g: (g["author_id"] != viewer, not g["has_unseen"]))
    return result[:MAX_TRAY_AUTHORS], state


def author_stories(viewer_id: str, author_id) -> list[Story]:
    """One author's active stories the viewer may see, oldest first (a profile's
    story ring, or a link to one story). Nothing hidden is told apart from none."""
    try:
        author = str(uuid.UUID(str(author_id)))
    except ValueError as exc:
        raise _bad_request("author_id must be a UUID.") from exc
    candidates = list(
        Story.objects.filter(_live(), author_id=author, expires_at__gt=timezone.now()).order_by(
            "created_at", "id"
        )
    )
    if not candidates:
        return []
    viewer = str(viewer_id)
    if viewer == author:
        return candidates
    if _blocked_either_way(viewer, author):
        return []
    audiences = {Story.Audience.PUBLIC}
    if any(s.audience != Story.Audience.PUBLIC for s in candidates):
        rel = get_relationship(viewer, author)
        if rel.are_friends and not rel.blocked_either_way:
            audiences.add(Story.Audience.FRIENDS)
            if CloseFriend.objects.filter(owner_id=author, friend_id=viewer).exists():
                audiences.add(Story.Audience.CLOSE_FRIENDS)
    return [s for s in candidates if s.audience in audiences]


def archive_queryset(author_id: str):
    """Every live story of the author, active or expired, newest first."""
    return Story.objects.filter(_live(), author_id=author_id).order_by("-created_at", "-id")


def viewers_queryset(author_id: str, story_id):
    """Who saw the author's story, newest first. The author only (404 for anyone
    else); accounts blocked either way are left out."""
    story = _own(author_id, story_id)
    return (
        StoryView.objects.filter(story=story)
        .exclude(viewer_id__in=list(blocked_ids(str(author_id))))
        .order_by("-viewed_at", "-id")
    ), story


def reactions_of(story: Story, viewer_ids: list) -> dict:
    return {
        str(a): r
        for a, r in StoryReaction.objects.filter(
            story=story, account_id__in=viewer_ids
        ).values_list("account_id", "reaction")
    }


# ---- writes ----------------------------------------------------------------------


def _check_photo(author_id: str, story_id: str, media_id: str) -> None:
    """The author's own image, uploaded, and attached nowhere else. Then bound to
    the story and restricted, so media asks post before serving it to anyone but
    the author. Remote calls: run before the write transaction."""
    info = media_client.lookup([media_id]).get(media_id)
    if info is None or info.owner_id != str(author_id):
        raise _bad_request("Media not found.", "media_not_owned")
    if info.kind != "image":
        raise _bad_request("A story photo must be an image.", "media_kind_not_allowed")
    if info.status not in _ATTACHABLE_STATUSES:
        raise _bad_request("Media upload is not complete.", "media_not_ready")
    elsewhere = (
        PostMedia.objects.filter(media_id=media_id, post__deleted_at__isnull=True).exists()
        or Gathering.objects.filter(cover_media_id=media_id, deleted_at__isnull=True).exists()
        or Story.objects.filter(media_id=media_id, deleted_at__isnull=True).exists()
    )
    if elsewhere:
        raise _bad_request("Media is already attached elsewhere.", "media_already_attached")
    result = media_client.bind(str(author_id), str(story_id), [media_id], restricted=True)
    if result.attached_elsewhere:
        raise _bad_request("Media is already attached elsewhere.", "media_already_attached")
    if result.skipped:
        raise _bad_request("Media not found.", "media_not_owned")


def create_story(
    author_id: str,
    *,
    kind: str,
    audience: str,
    text: str = "",
    background: str = BACKGROUNDS[0],
    media_id=None,
) -> Story:
    text = (text or "").strip()
    if kind not in Story.Kind.values:
        raise _bad_request("Unknown story kind.")
    if audience not in Story.Audience.values:
        raise _bad_request("Unknown audience.")
    if background not in BACKGROUNDS:
        raise _bad_request("Unknown background.")
    if len(text) > MAX_TEXT:
        raise _bad_request("The text is too long.", "text_too_long")
    if kind == Story.Kind.TEXT:
        if not text:
            raise _bad_request("A text story needs text.", "text_required")
        media_id = None
    elif not media_id:
        raise _bad_request("A photo story needs a photo.", "media_required")
    since = timezone.now() - STORY_TTL
    recent = Story.objects.filter(
        author_id=author_id, deleted_at__isnull=True, created_at__gte=since
    ).count()
    if recent >= MAX_STORIES_PER_DAY:
        raise _bad_request("You've shared the most stories allowed for today.", "story_limit")

    story_id = uuid7()
    if media_id:
        _check_photo(author_id, str(story_id), str(media_id))
    with transaction.atomic():
        story = Story.objects.create(
            id=story_id,
            author_id=author_id,
            kind=kind,
            media_id=media_id,
            text=text,
            background=background,
            audience=audience,
        )
    return story


def delete_story(author_id: str, story_id) -> None:
    """The author's own story only (404 otherwise). Its photo stays restricted to
    the deleted story, so nobody but the author can open it again."""
    with transaction.atomic():
        story = _own(author_id, story_id, lock=True)
        story.deleted_at = timezone.now()
        story.save(update_fields=["deleted_at"])
        _emit(
            "story.deleted",
            story,
            {"story_id": str(story.id), "author_id": str(story.author_id)},
        )


def mark_viewed(viewer_id: str, story_id) -> Story:
    """Record the first view by someone other than the author (idempotent)."""
    story = require_visible(viewer_id, story_id)
    if str(viewer_id) == str(story.author_id):
        return story
    with transaction.atomic():
        _, created = StoryView.objects.get_or_create(story=story, viewer_id=viewer_id)
        if created:
            Story.objects.filter(id=story.id).update(view_count=F("view_count") + 1)
    story.refresh_from_db()
    return story


def react(viewer_id: str, story_id, reaction: str) -> Story:
    """React (or change the reaction). Not on one's own story. The author hears
    about the first reaction of each account (``story.reacted``)."""
    if reaction not in REACTION_TYPES:
        raise _bad_request("Unknown reaction.")
    story = require_visible(viewer_id, story_id)
    if str(viewer_id) == str(story.author_id):
        raise _bad_request("You can't react to your own story.", "cannot_react_own")
    with transaction.atomic():
        story = Story.objects.select_for_update().get(id=story.id)
        _, viewed = StoryView.objects.get_or_create(story=story, viewer_id=viewer_id)
        row = StoryReaction.objects.filter(story=story, account_id=viewer_id).first()
        bumps = {"view_count": F("view_count") + 1} if viewed else {}
        if row is None:
            StoryReaction.objects.create(story=story, account_id=viewer_id, reaction=reaction)
            bumps["reaction_count"] = F("reaction_count") + 1
            _emit(
                "story.reacted",
                story,
                {
                    "story_id": str(story.id),
                    "author_id": str(story.author_id),
                    "reactor": str(viewer_id),
                    "reaction_type": reaction,
                },
                actor_id=str(viewer_id),
            )
        elif row.reaction != reaction:
            row.reaction = reaction
            row.save(update_fields=["reaction", "updated_at"])
        if bumps:
            Story.objects.filter(id=story.id).update(**bumps)
    story.refresh_from_db()
    return story


def unreact(viewer_id: str, story_id) -> Story:
    story = require_visible(viewer_id, story_id)
    with transaction.atomic():
        story = Story.objects.select_for_update().get(id=story.id)
        deleted, _ = StoryReaction.objects.filter(story=story, account_id=viewer_id).delete()
        if deleted:
            Story.objects.filter(id=story.id, reaction_count__gt=0).update(
                reaction_count=F("reaction_count") - 1
            )
    story.refresh_from_db()
    return story


def report(viewer_id: str, story_id, reason: str) -> StoryReport:
    """404 (nothing written) when the reporter cannot see the story; the author
    cannot report their own; one report per account, a repeat emits nothing."""
    if reason not in ReportReason.values:
        raise _bad_request("Invalid reason.")
    story = require_visible(viewer_id, story_id)
    if str(viewer_id) == str(story.author_id):
        raise _bad_request("You can't report your own story.", "cannot_report_own")
    existing = StoryReport.objects.filter(story=story, reporter_id=viewer_id).first()
    if existing is not None:
        return existing
    try:
        with transaction.atomic():
            row = StoryReport.objects.create(story=story, reporter_id=viewer_id, reason=reason)
            _emit(
                "story.reported",
                story,
                {
                    "story_id": str(story.id),
                    "reporter": str(viewer_id),
                    "reason": reason,
                    "owner_id": str(story.author_id),
                },
                actor_id=str(viewer_id),
            )
    except IntegrityError:  # a concurrent duplicate won the unique constraint
        return StoryReport.objects.get(story=story, reporter_id=viewer_id)
    return row


def apply_moderation(story_id: str, action: str) -> None:
    """``moderation.actioned`` with ``target_type=story``: ``remove`` hides the
    story everywhere (the author too) and emits ``story.deleted``; ``approve`` (an
    overturned removal) shows it again. Idempotent."""
    with transaction.atomic():
        story = Story.objects.select_for_update().filter(id=story_id).first()
        if story is None:
            return
        removed = story.moderation_status == Story.ModerationStatus.REMOVED
        if action == "remove" and not removed:
            story.moderation_status = Story.ModerationStatus.REMOVED
            story.save(update_fields=["moderation_status"])
            _emit(
                "story.deleted",
                story,
                {"story_id": str(story.id), "author_id": str(story.author_id), "by": "moderation"},
            )
        elif action == "approve" and removed:
            story.moderation_status = Story.ModerationStatus.OK
            story.save(update_fields=["moderation_status"])


# ---- close friends ---------------------------------------------------------------


def close_friends_queryset(owner_id: str):
    """The owner's list, newest first, without accounts blocked either way."""
    return (
        CloseFriend.objects.filter(owner_id=owner_id)
        .exclude(friend_id__in=list(blocked_ids(str(owner_id))))
        .order_by("-created_at", "-id")
    )


def add_close_friends(owner_id: str, account_ids: list[str]) -> list[str]:
    """Add friends to the list; returns who was newly added. Only current friends
    (400 ``not_friend``); graph down is 503 and nothing is written."""
    owner = str(owner_id)
    ids = list(OrderedDict.fromkeys(str(a) for a in account_ids))
    if not ids:
        raise _bad_request("Pick at least one friend.")
    if len(ids) > MAX_CLOSE_FRIENDS_PER_CALL:
        raise _bad_request(f"At most {MAX_CLOSE_FRIENDS_PER_CALL} at a time.")
    if owner in ids:
        raise _bad_request("You can't add yourself.", "not_friend")
    friends = graph.friend_ids(owner)
    if friends is None:
        raise _unavailable()
    blocked = blocked_ids(owner)
    if any(a not in friends or a in blocked for a in ids):
        raise _bad_request("Only friends can be close friends.", "not_friend")
    with transaction.atomic():
        existing = {
            str(f)
            for f in CloseFriend.objects.filter(owner_id=owner, friend_id__in=ids).values_list(
                "friend_id", flat=True
            )
        }
        new = [a for a in ids if a not in existing]
        if CloseFriend.objects.filter(owner_id=owner).count() + len(new) > MAX_CLOSE_FRIENDS:
            raise _bad_request("Your close friends list is full.", "close_friends_full")
        CloseFriend.objects.bulk_create(
            [CloseFriend(owner_id=owner, friend_id=a) for a in new], ignore_conflicts=True
        )
    return new


def remove_close_friend(owner_id: str, friend_id) -> None:
    CloseFriend.objects.filter(owner_id=owner_id, friend_id=friend_id).delete()


def drop_between(a: str, b: str) -> int:
    """After a block: neither keeps the other on their close friends list."""
    deleted, _ = CloseFriend.objects.filter(
        Q(owner_id=a, friend_id=b) | Q(owner_id=b, friend_id=a)
    ).delete()
    return deleted


def drop_after_unfriend(a: str, b: str) -> int:
    """After ``friendship.removed``. Retries reorder events, so graph is asked
    first: friends again means nothing is dropped; no answer raises (retry)."""
    rel = get_relationship(str(a), str(b))
    if rel.degraded:
        raise TaraAPIError(
            "Graph is unavailable; retry the unfriend clean-up.",
            code="dependency_unavailable",
            http_status_code=503,
        )
    if rel.are_friends:
        return 0
    return drop_between(a, b)
