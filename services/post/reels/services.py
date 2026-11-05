"""Reels business logic (roadmap 5.5 / 5.8).

The rules a reel follows, all enforced here:

- **What a reel is.** One transcoded video (media's ``purpose=post`` pipeline),
  the author's own and ready, portrait around 9:16 and at most 90 s, measured
  by media after transcoding (never the client's word). A landscape or longer
  clip is refused with ``reel_not_vertical`` / ``reel_too_long`` and stays a
  normal video post. Groups, drafts and scheduling are not offered for reels.
- **Who sees a reel.** Exactly who may see its post (``posts.services``): the
  audience, blocks either way, the page's own visibility, deletion, a
  moderator's removal and a deactivated author all apply. Feeds filter in SQL
  first, then every item is checked with the post rule before it is returned.
- **Feeds.** ``for_you``: recent reels that are public, or from friends, or
  (followers audience) from accounts the viewer follows. ``following``: only
  friends, followed accounts and followed pages. Both leave out the viewer's
  own reels, anyone blocked either way, accounts the viewer muted, and reels
  the viewer marked "not interested". Graph down: no friends or follows (fail
  closed: public reels only); mutes unknown are not applied.
- **Views.** One per viewer per reel per UTC day; the author's are not counted.

Remote calls (media, graph) run before any write transaction.
"""

from __future__ import annotations

import logging
import uuid

import requests
from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Exists, F, OuterRef, Q
from django.utils import timezone
from gatherings import graph
from posts import clients as post_clients
from posts import media_client, pages
from posts import services as post_services
from posts.clients import Relationship
from posts.models import Audience, CommentPolicy, Post, PostMedia, PostState

from tara_common.exceptions import TaraAPIError
from tara_events.envelope import uuid7

from .models import (
    MAX_ASPECT,
    MAX_DURATION_MS,
    MIN_ASPECT,
    PublishState,
    Reel,
    ReelHide,
    ReelView,
)

logger = logging.getLogger("tara.post.reels")

# Recent distinct authors asked about in one graph batch (its limit is 50).
MAX_FOLLOW_CANDIDATES = 50
REEL_AUDIENCES = (Audience.PUBLIC, Audience.FRIENDS, Audience.FOLLOWERS, Audience.ONLY_ME)
TAB_FOR_YOU = "for_you"
TAB_FOLLOWING = "following"
TABS = (TAB_FOR_YOU, TAB_FOLLOWING)
_COVER_STATUSES = {"processing", "ready"}


def _bad_request(message: str, code: str = "validation_error") -> TaraAPIError:
    return TaraAPIError(message, code=code, http_status_code=400)


def _not_found() -> TaraAPIError:
    return TaraAPIError("Reel not found.", code="not_found", http_status_code=404)


def _uuid(value, name: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError) as exc:
        raise _bad_request(f"{name} must be a UUID.") from exc


# ---- the reel rules ----------------------------------------------------------------


def media_problem(author_id: str, info) -> str | None:
    """Why this media cannot be a reel (an error code), or ``None`` when it can.

    ``info`` is media's ``MediaInfo`` (``None`` when media does not know the id).
    Someone else's media and an unknown id read the same, so neither leaks.
    """
    if info is None or info.owner_id != str(author_id):
        return "media_not_owned"
    if info.kind != "video" or (info.purpose or "") != "post":
        return "reel_video_required"
    if info.status != "ready":
        return "reel_video_not_ready"
    width, height, duration = info.width or 0, info.height or 0, info.duration_ms or 0
    if width <= 0 or height <= 0 or duration <= 0:
        return "reel_video_not_ready"  # media has not measured it yet
    if height <= width or not (MIN_ASPECT <= width / height <= MAX_ASPECT):
        return "reel_not_vertical"
    if duration > MAX_DURATION_MS:
        return "reel_too_long"
    return None


_MESSAGES = {
    "media_not_owned": "Media not found.",
    "reel_video_required": "A reel needs one transcoded video.",
    "reel_video_not_ready": "The video is still processing.",
    "reel_not_vertical": "A reel must be a vertical video (around 9:16). Post it as a video.",
    "reel_too_long": f"A reel can be at most {MAX_DURATION_MS // 1000} s. Post it as a video.",
}


def eligibility(author_id: str, media_id) -> dict:
    """Whether the author's video can be published as a reel, and its measures.

    The composer asks this once the video is ready, so a landscape or long clip
    is offered as a normal video post instead. ``create_reel`` checks again.
    """
    media_id = _uuid(media_id, "media_id")
    info = media_client.lookup([media_id]).get(media_id)
    code = media_problem(author_id, info)
    if code is None and (
        Reel.objects.filter(media_id=media_id).exists()
        # Already the video of a normal post: create_reel would be refused the same way.
        or PostMedia.objects.filter(media_id=media_id, post__deleted_at__isnull=True).exists()
    ):
        code = "media_already_attached"
    owned = info is not None and info.owner_id == str(author_id)
    return {
        "media_id": media_id,
        "eligible": code is None,
        "code": code,
        "duration_ms": info.duration_ms if owned else None,
        "width": info.width if owned else None,
        "height": info.height if owned else None,
        "max_duration_ms": MAX_DURATION_MS,
    }


def _check_cover(uploader_id: str, cover_id: str, info, video_id: str) -> None:
    if cover_id == video_id:
        raise _bad_request("The cover must be a photo.", "reel_cover_invalid")
    if info is None or info.owner_id != uploader_id:
        raise _bad_request("Media not found.", "media_not_owned")
    if info.kind != "image":
        raise _bad_request("The cover must be a photo.", "reel_cover_invalid")
    if info.status not in _COVER_STATUSES:
        raise _bad_request("Media upload is not complete.", "media_not_ready")
    taken = (
        Reel.objects.filter(cover_media_id=cover_id).exists()
        or PostMedia.objects.filter(media_id=cover_id, post__deleted_at__isnull=True).exists()
    )
    if taken:
        raise _bad_request("Media is already attached to another post.", "media_already_attached")


def create_reel(
    author_id: str,
    *,
    media_id,
    cover_media_id=None,
    caption: str = "",
    audience: str = Audience.PUBLIC,
    comment_policy: str = CommentPolicy.EVERYONE,
    page_id=None,
) -> Post:
    """Publish the author's vertical video as a reel (as a page with ``page_id``,
    once profile says the author may post for it; a page reel is public).

    The post is created through ``posts.services.create_post`` with type
    ``reel``, so audience, media restriction, hashtags, mentions and
    ``post.created`` (feed fan-out at publish time) work as for any post; the
    ``Reel`` row commits in the same transaction. A cover photo is bound to the
    post *restricted* before the post exists, so it always follows the post's
    visibility (narrowed audience, deletion, removal) without another call.
    """
    uploader = str(author_id)
    media_id = _uuid(media_id, "media_id")
    cover_id = _uuid(cover_media_id, "cover_media_id") if cover_media_id else None
    if audience not in REEL_AUDIENCES:
        raise _bad_request("Invalid audience.")
    ids = [media_id] + ([cover_id] if cover_id else [])
    found = media_client.lookup(ids)
    info = found.get(media_id)
    code = media_problem(uploader, info)
    if code:
        raise _bad_request(_MESSAGES[code], code)
    if Reel.objects.filter(media_id=media_id).exists():
        raise _bad_request("Media is already attached to another post.", "media_already_attached")
    if page_id and cover_id:
        pages.require_poster(str(page_id), uploader)  # 404 / 403 before the cover is bound
    post_id = uuid7()
    if cover_id:
        _check_cover(uploader, cover_id, found.get(cover_id), media_id)
        result = media_client.bind(uploader, str(post_id), [cover_id], restricted=True)
        post_services._check_bound(result)  # noqa: SLF001 - same service

    def _with_reel(post: Post) -> None:
        Reel.objects.create(
            post=post,
            author_id=post.author_id,
            author_type=post.author_type,
            media_id=media_id,
            cover_media_id=cover_id,
            duration_ms=info.duration_ms,
            width=info.width,
            height=info.height,
            created_at=post.created_at,
        )

    try:
        return post_services.create_post(
            uploader,
            body=caption.strip(),
            post_type=Post.Type.REEL,
            audience=audience,
            media_ids=[media_id],
            comment_policy=comment_policy,
            page_id=page_id,
            post_id=post_id,
            on_create=_with_reel,
        )
    except IntegrityError as exc:  # the same video published twice at once
        raise _bad_request(
            "Media is already attached to another post.", "media_already_attached"
        ) from exc


# ---- graph -------------------------------------------------------------------------


def _relations(viewer_id: str, users: list[str], pages_: list[str]) -> dict | None:
    """Graph's batch relationships (friend state, follows; pages followed).
    Accounts in a block either way are absent. ``None`` when graph is down."""
    if not users and not pages_:
        return {}

    def _call() -> dict:
        resp = requests.post(
            f"{settings.GRAPH_INTERNAL_URL}/internal/v1/relationships/batch/",
            json={
                "viewer_id": str(viewer_id),
                "users": users[:MAX_FOLLOW_CANDIDATES],
                "pages": pages_[:MAX_FOLLOW_CANDIDATES],
            },
            headers={"Authorization": f"Bearer {post_clients._internal_token()}"},
            timeout=settings.GRAPH_CALL_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json().get("data", {}).get("results", {}) or {}

    try:
        return post_clients._breaker.call(_call)
    except Exception:  # noqa: BLE001 - circuit open, timeout, error: fail closed
        logger.warning("graph relationship batch failed", exc_info=True)
        return None


def muted_ids(viewer_id: str) -> set[str]:
    """Accounts the viewer muted (graph's preferences). Unknown while graph is
    down: a mute is a preference, not a privacy rule, so nothing is hidden then."""

    def _call() -> set[str]:
        resp = requests.get(
            f"{settings.GRAPH_INTERNAL_URL}/internal/v1/preferences/{viewer_id}/",
            headers={"Authorization": f"Bearer {post_clients._internal_token()}"},
            timeout=settings.GRAPH_CALL_TIMEOUT,
        )
        resp.raise_for_status()
        return {str(a) for a in resp.json().get("data", {}).get("muted", []) or []}

    try:
        return post_clients._breaker.call(_call)
    except Exception:  # noqa: BLE001
        logger.warning("graph preferences lookup failed", exc_info=True)
        return set()


# ---- reading -----------------------------------------------------------------------


def _live():
    """Reels whose post could be shown to someone: published, outside groups,
    not deleted, not removed, and (reconcile job) with their video still there.
    The per-viewer rule runs after this."""
    return (
        Reel.objects.filter(
            publish_state=PublishState.PUBLISHED,
            post__deleted_at__isnull=True,
            post__state=PostState.PUBLISHED,
            post__group_id__isnull=True,
        )
        .exclude(post__moderation_status=Post.ModerationStatus.REMOVED)
        .select_related("post", "post__poll")
        .prefetch_related("post__media", "post__reaction_counts", "post__tags")
    )


def _recent_authors(qs, author_type: str, exclude: set[str]) -> list[str]:
    out: list[str] = []
    rows = (
        qs.filter(author_type=author_type)
        .exclude(author_id__in=list(exclude))
        .order_by("-created_at")
        .values_list("author_id", flat=True)[: MAX_FOLLOW_CANDIDATES * 10]
    )
    for author in rows:
        author = str(author)
        if author not in out:
            out.append(author)
            if len(out) >= MAX_FOLLOW_CANDIDATES:
                break
    return out


class FeedContext:
    """What one feed request knows about the viewer: blocks, mutes, friends and
    follows (from graph), reused as the visibility cache for every item."""

    def __init__(self, viewer_id: str, *, tab: str):
        self.viewer = str(viewer_id)
        self.blocked = post_services.blocked_ids(self.viewer)
        self.muted = muted_ids(self.viewer) - self.blocked
        self.friends = (graph.friend_ids(self.viewer) or set()) - self.blocked - {self.viewer}
        self.rel_cache: dict = {}
        skip = self.blocked | self.muted | self.friends | {self.viewer}
        base = Reel.objects.filter(
            publish_state=PublishState.PUBLISHED,
            post__deleted_at__isnull=True,
            post__state=PostState.PUBLISHED,
        )
        users = _recent_authors(
            base if tab == TAB_FOLLOWING else base.filter(post__audience=Audience.FOLLOWERS),
            "user",
            skip,
        )
        page_ids = _recent_authors(base, pages.AUTHOR_TYPE, skip) if tab == TAB_FOLLOWING else []
        results = _relations(self.viewer, users, page_ids)
        self.followed: set[str] = set()
        self.followed_pages: set[str] = set()
        if results is not None:
            for account in users:
                row = results.get(account)
                if row is None:  # a block either way: graph says nothing
                    self.rel_cache[account] = Relationship(blocked_either_way=True)
                    continue
                if row.get("following"):
                    self.followed.add(account)
                if row.get("state") == "friends":
                    self.friends.add(account)
            self.followed_pages = {p for p in page_ids if (results.get(p) or {}).get("following")}
        for account in self.friends | self.followed:
            self.rel_cache[account] = Relationship(
                are_friends=account in self.friends, a_follows_b=account in self.followed
            )

    def visible(self, reels: list[Reel]) -> list[Reel]:
        posts = [r.post for r in reels]
        post_services._prefetch_pages(self.viewer, posts, self.rel_cache)  # noqa: SLF001
        return [
            r
            for r in reels
            if post_services.visible_to_viewer(self.viewer, r.post, self.rel_cache, self.blocked)
        ]


def feed_queryset(ctx: FeedContext, tab: str):
    """The tab's candidates, newest first, before the per-item visibility check."""
    not_hidden = ~Exists(ReelHide.objects.filter(reel=OuterRef("pk"), account_id=ctx.viewer))
    qs = _live().filter(not_hidden).exclude(author_id__in=[ctx.viewer, *ctx.blocked, *ctx.muted])
    friends, followed = list(ctx.friends), list(ctx.followed)
    if tab == TAB_FOLLOWING:
        qs = qs.filter(
            Q(author_type="user", author_id__in=friends + followed)
            | Q(author_type=pages.AUTHOR_TYPE, author_id__in=list(ctx.followed_pages))
        )
    else:
        qs = qs.filter(
            Q(post__audience=Audience.PUBLIC)
            | Q(author_id__in=friends, post__audience__in=(Audience.FRIENDS, Audience.FOLLOWERS))
            | Q(author_id__in=followed, post__audience=Audience.FOLLOWERS)
        )
    return qs.order_by("-created_at", "-post_id")


def author_queryset(author_id) -> object:
    """One profile's or page's reels, newest first (the Reels tab)."""
    author = _uuid(author_id, "author_id")
    return _live().filter(author_id=author).order_by("-created_at", "-post_id")


def visible_reels(viewer_id: str, reels: list[Reel]) -> list[Reel]:
    """The reels of a profile tab the viewer may see (the post rule, per item)."""
    posts = post_services.only_visible(viewer_id, [r.post for r in reels])
    seen = {p.id for p in posts}
    return [r for r in reels if r.post_id in seen]


def get_reel(viewer_id: str, reel_id) -> Reel:
    """One reel the viewer may see; anything else (hidden, deleted, not a reel) is 404."""
    reel = _live().filter(post_id=_uuid(reel_id, "reel_id")).first()
    if reel is None or not post_services.visible_to_viewer(str(viewer_id), reel.post):
        raise _not_found()
    return reel


# ---- views and "not interested" ----------------------------------------------------


def record_view(viewer_id: str, reel_id) -> tuple[Reel, bool]:
    """Count the viewer once per reel per UTC day (never the author)."""
    reel = get_reel(viewer_id, reel_id)
    viewer = str(viewer_id)
    if viewer == str(reel.author_id):
        return reel, False
    with transaction.atomic():
        _, created = ReelView.objects.get_or_create(
            reel=reel, viewer_id=viewer, day=timezone.now().date()
        )
        if created:
            Reel.objects.filter(pk=reel.pk).update(view_count=F("view_count") + 1)
    reel.refresh_from_db(fields=["view_count"])
    return reel, created


def hide(viewer_id: str, reel_id) -> None:
    reel = get_reel(viewer_id, reel_id)
    if str(reel.author_id) == str(viewer_id):
        raise _bad_request("You can't hide your own reel.", "reel_own")
    ReelHide.objects.get_or_create(reel=reel, account_id=str(viewer_id))


def unhide(viewer_id: str, reel_id) -> None:
    """Undo "not interested". A reel the viewer can no longer see is 404."""
    reel = get_reel(viewer_id, reel_id)
    ReelHide.objects.filter(reel=reel, account_id=str(viewer_id)).delete()


def views_today(viewer_id: str, reels: list[Reel]) -> set:
    """Which of these reels the viewer already watched today."""
    return set(
        ReelView.objects.filter(
            reel__in=reels, viewer_id=str(viewer_id), day=timezone.now().date()
        ).values_list("reel_id", flat=True)
    )
