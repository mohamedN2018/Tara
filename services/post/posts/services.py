"""Post business logic: posts, audience visibility, comments, reactions, shares, saves."""

from __future__ import annotations

import re
import uuid
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Count, Exists, F, Max, OuterRef, Q
from django.db.models.functions import Greatest
from django.utils import timezone

from tara_common.exceptions import Conflict, TaraAPIError
from tara_events.envelope import uuid7

from . import composer, events, linkpreview, media_client, pages
from . import groups as group_rm
from .clients import get_relationship, resolve_handles
from .models import (
    REACTION_TYPES,
    ApprovalState,
    Audience,
    BlockedPair,
    Comment,
    CommentPolicy,
    CommentReaction,
    CommentReport,
    GroupReportReview,
    Hashtag,
    Mention,
    Poll,
    PollOption,
    PollVote,
    Post,
    PostHashtag,
    PostMedia,
    PostReaction,
    PostReactionCount,
    PostReport,
    PostState,
    SavedCollection,
    SavedItem,
    Share,
)

# Not inside a word, a URL fragment or an email address.
_HASHTAG_RE = re.compile(r"(?<![\w/&#])#(\w{1,80})")
_MENTION_RE = re.compile(r"(?<![\w.@/])@([a-zA-Z0-9_]{3,30})")
MAX_MENTION_NOTIFICATIONS = 10
MAX_MEDIA_PER_POST = 10
# Post types that carry exactly one transcoded video (5.2; a reel, 5.5).
_VIDEO_TYPES = {Post.Type.VIDEO, Post.Type.REEL}
# Media still processing are accepted: the composer posts right after upload.
_ATTACHABLE_STATUSES = {"processing", "ready"}
AUDIENCE_RANK = {
    Audience.ONLY_ME: 0,
    Audience.FRIENDS: 1,
    Audience.FOLLOWERS: 2,
    Audience.PUBLIC: 3,
    # Only posts of public groups can be shared (``share``), so a share of one
    # may reach as far as a public post.
    Audience.GROUP: 3,
}
# Recipients per notification event (group.post.published, group.announcement.pinned).
RECIPIENT_CHUNK = 500


def extract_hashtags(body: str) -> list[str]:
    return sorted({m.lower() for m in _HASHTAG_RE.findall(body or "")})


def extract_mentions(body: str) -> list[str]:
    return sorted({m.lower() for m in _MENTION_RE.findall(body or "")})


# ---- visibility -------------------------------------------------------------


def _is_locally_blocked(a: str, b: str) -> bool:
    return BlockedPair.objects.filter(
        Q(blocker_id=a, blocked_id=b) | Q(blocker_id=b, blocked_id=a)
    ).exists()


def blocked_ids(viewer_id: str) -> set[str]:
    """Accounts blocked by, or blocking, the viewer."""
    pairs = BlockedPair.objects.filter(
        Q(blocker_id=viewer_id) | Q(blocked_id=viewer_id)
    ).values_list("blocker_id", "blocked_id")
    return {str(account) for pair in pairs for account in pair} - {str(viewer_id)}


def visible_to_viewer(
    viewer_id: str,
    post: Post,
    rel_cache: dict | None = None,
    blocked: set[str] | None = None,
) -> bool:
    """``rel_cache`` and ``blocked`` avoid per-post lookups when checking many posts."""
    if not post.is_visible:
        return False
    if post.author_type == pages.AUTHOR_TYPE and not _page_visible(viewer_id, post, rel_cache):
        return False  # a draft, suspended or deleted page: its posts are hidden too
    if post.group_id:
        return _group_post_visible(viewer_id, post, rel_cache, blocked)
    if str(post.author_id) == str(viewer_id):
        return True
    if blocked is None:
        if _is_locally_blocked(viewer_id, post.author_id):
            return False
    elif str(post.author_id) in blocked:
        return False
    if post.audience == Audience.ONLY_ME:
        return False
    if post.audience == Audience.PUBLIC:
        return True
    author = str(post.author_id)
    if rel_cache is not None and author in rel_cache:
        rel = rel_cache[author]
    else:
        rel = get_relationship(str(viewer_id), author)
        if rel_cache is not None:
            rel_cache[author] = rel
    if rel.blocked_either_way:
        return False
    if post.audience == Audience.FRIENDS:
        return rel.are_friends
    if post.audience == Audience.FOLLOWERS:
        return rel.are_friends or rel.a_follows_b
    return False


def _page_key(page_id) -> str:
    return f"page:{page_id}"


def _page_visible(viewer_id: str, post: Post, cache: dict | None = None) -> bool:
    """Whether the viewer may see the page that published ``post`` (profile's
    rule for the page itself), once per page per request."""
    key = _page_key(post.author_id)
    if cache is not None and key in cache:
        return cache[key]
    seen = str(post.author_id) in pages.visible_pages(viewer_id, [post.author_id])
    if cache is not None:
        cache[key] = seen
    return seen


def _prefetch_pages(viewer_id: str, posts, cache: dict) -> None:
    """One lookup for every page among ``posts`` (a timeline, the feed batch)."""
    ids = {str(p.author_id) for p in posts if p.author_type == pages.AUTHOR_TYPE}
    ids -= {k.removeprefix("page:") for k in cache if k.startswith("page:")}
    if ids:
        seen = pages.visible_pages(viewer_id, ids)
        cache.update({_page_key(i): i in seen for i in ids})


def _group_access(viewer_id: str, group_id, cache: dict | None = None):
    """The viewer's place in the group (read model), once per group per request."""
    key = f"group:{group_id}"
    if cache is not None and key in cache:
        return cache[key]
    acc = group_rm.access(group_id, viewer_id)
    if cache is not None:
        cache[key] = acc
    return acc


def _group_post_visible(viewer_id: str, post: Post, cache: dict | None, blocked) -> bool:
    """A group post: the group's content rule (public: anyone; private and hidden:
    active members; never a banned account), then blocks with the author both
    ways. A post waiting for approval is seen by its author and the group's staff."""
    acc = _group_access(viewer_id, post.group_id, cache)
    if not group_rm.content_visible(str(viewer_id), acc):
        return False
    viewer, author = str(viewer_id), str(post.author_id)
    if viewer != author:
        if blocked is None:
            if _is_locally_blocked(viewer, author):
                return False
        elif author in blocked:
            return False
    if post.approval_state == ApprovalState.PENDING:
        return viewer == author or acc.is_staff
    return True


def _not_group_member() -> TaraAPIError:
    return TaraAPIError(
        "Only members of the group can do this.", code="not_group_member", http_status_code=403
    )


def require_group_member(account_id: str, group_id):
    """Writes into a group (posting, commenting): profile is asked first, so a
    member removed or banned a moment ago is refused (403; 404 when the group is
    hidden from them). Profile down: the read model decides, failing closed."""
    acc = group_rm.access(group_id, account_id, fresh=True)
    if not group_rm.content_visible(str(account_id), acc):
        raise TaraAPIError("Group not found.", code="not_found", http_status_code=404)
    if not acc.is_member:
        raise _not_group_member()
    return acc


def _require_group_staff(actor_id: str, post: Post):
    """A moderator, admin or owner of the post's group, asked of profile first.
    Someone who cannot see the post gets 404, a member without the role 403."""
    if not post.group_id:
        raise TaraAPIError("Post not found.", code="not_found", http_status_code=404)
    acc = group_rm.access(post.group_id, actor_id, fresh=True)
    if not group_rm.content_visible(str(actor_id), acc):
        raise TaraAPIError("Post not found.", code="not_found", http_status_code=404)
    if not acc.is_staff:
        raise TaraAPIError(
            "Only the group's moderators can do this.",
            code="permission_denied",
            http_status_code=403,
        )
    return acc


def _require_visible(viewer_id: str, post_id: str) -> Post:
    post = Post.objects.filter(id=post_id).first()
    if post is None or not visible_to_viewer(viewer_id, post):
        raise TaraAPIError("Post not found.", code="not_found", http_status_code=404)
    return post


# ---- posts ------------------------------------------------------------------


def _attach_tags_and_mentions(post: Post) -> tuple[list[str], list[str]]:
    tags = extract_hashtags(post.body)
    mentions = extract_mentions(post.body)
    for tag in tags:
        hashtag, _ = Hashtag.objects.get_or_create(tag=tag)
        PostHashtag.objects.get_or_create(post=post, hashtag=hashtag)
    for handle in mentions:
        Mention.objects.create(post=post, mentioned_handle=handle)
    return tags, mentions


def _create_poll(post: Post, spec: dict) -> Poll:
    hours = spec.get("duration_hours")
    poll = Poll.objects.create(
        post=post, closes_at=timezone.now() + timedelta(hours=hours) if hours else None
    )
    PollOption.objects.bulk_create(
        PollOption(poll=poll, text=text, position=i) for i, text in enumerate(spec["options"])
    )
    return poll


def _bad_request(message: str, code: str = "validation_error") -> TaraAPIError:
    return TaraAPIError(message, code=code, http_status_code=400)


def _check_video(infos: list, post_type: str) -> None:
    """A video post (roadmap 5.2, D1): exactly one video, the author's own,
    transcoded by media's pipeline (``purpose=post``) and ready.

    Media plays it only to viewers post's visibility endpoint lets see the
    post, so the audience, blocks and moderator removal apply to it."""
    if post_type not in _VIDEO_TYPES:
        raise _bad_request("A video needs the video post type.", "video_post_type")
    if len(infos) != 1 or infos[0].kind != "video":
        raise _bad_request("A video post has exactly one video.", "video_post_single")
    if getattr(infos[0], "purpose", "") != "post":
        raise _bad_request("This video cannot be posted.", "media_kind_not_allowed")
    if infos[0].status != "ready":
        raise _bad_request("The video is still processing.", "video_not_ready")


def _check_attachments(author_id: str, media_ids: list[str], post_type: str = "") -> None:
    """Each id is the author's own image, uploaded, and on no other live post.

    A remote read, so callers run it before their write transaction.
    """
    if len(media_ids) > MAX_MEDIA_PER_POST:
        raise _bad_request(f"A post can have at most {MAX_MEDIA_PER_POST} media.")
    if len(set(media_ids)) != len(media_ids):
        raise _bad_request("The same media is attached twice.")
    found = media_client.lookup(media_ids)
    infos = [found.get(m) for m in media_ids]
    # Someone else's media and unknown ids look the same, so neither leaks.
    if any(i is None or i.owner_id != str(author_id) for i in infos):
        raise _bad_request("Media not found.", "media_not_owned")
    if any(i.kind == "video" for i in infos) or post_type in _VIDEO_TYPES:
        _check_video(infos, post_type)
    elif any(i.kind != "image" for i in infos):
        raise _bad_request("Only images can be attached to a post.", "media_kind_not_allowed")
    if any(i.status not in _ATTACHABLE_STATUSES for i in infos):
        raise _bad_request("Media upload is not complete.", "media_not_ready")
    # One media belongs to one post, so its restriction follows one audience.
    if PostMedia.objects.filter(media_id__in=media_ids, post__deleted_at__isnull=True).exists():
        raise _bad_request("Media is already attached to another post.", "media_already_attached")


def _check_bound(result: media_client.BindResult) -> None:
    """400 for media that media would not bind: on another post, or deleted or
    changed hands since the lookup."""
    if result.attached_elsewhere:
        raise _bad_request("Media is already attached to another post.", "media_already_attached")
    if result.skipped:
        raise _bad_request("Media not found.", "media_not_owned")


def create_post(
    author_id: str,
    *,
    body: str = "",
    post_type: str = Post.Type.TEXT,
    audience: str = Audience.PUBLIC,
    media_ids: list[str] | None = None,
    shared_post_id=None,
    author_type: str = "user",
    poll: dict | None = None,
    comment_policy: str = CommentPolicy.EVERYONE,
    group_id=None,
    tagged_ids: list[str] | None = None,
    location: str = "",
    feeling: str = "",
    state: str = PostState.PUBLISHED,
    publish_at=None,
    page_id=None,
    post_id=None,
    on_create=None,
) -> Post:
    """``post_id`` (optional) is the id to create the post with, for a caller
    that binds more media to it first (a reel's cover). ``on_create(post)`` runs
    inside the write transaction, before ``post.created`` is emitted, so a
    domain row that belongs to the post (``reels.Reel``) commits with it.

    With ``page_id`` the post is published as that page (``author_type``
    ``page``, ``author_id`` the page id) once profile says the author may post
    for it; the media stay the author's own uploads. A page post is public,
    published now, and has no group, tags or poll audience of its own.

    Media are checked and bound to the post through media before the write
    transaction opens, so a media outage fails the request (503) instead of
    publishing restricted photos as public.

    With ``group_id`` the author must be an active member (asked of profile);
    the audience is forced to ``group`` whatever the client sent, the media are
    restricted (they follow the group's visibility), and with post approval on a
    plain member's post waits for the group's staff.

    ``state`` ``draft`` or ``scheduled`` (with ``publish_at``) keeps the post
    for its author only, emits nothing, and binds its media restricted; it is
    published later through ``composer`` (2C). Tags are checked here, against
    blocks and each person's "who can tag me" setting."""
    if state not in PostState.values:
        raise _bad_request("Invalid state.")
    uploader_id = str(author_id)
    if page_id:
        if group_id:
            raise _bad_request("Only people post in groups.")
        if state != PostState.PUBLISHED:
            raise _bad_request(
                "Drafts and scheduled posts are not available for pages.",
                "page_drafts_not_supported",
            )
        if tagged_ids:
            raise _bad_request("A page post can't tag people.", "page_tags_not_supported")
        pages.require_poster(str(page_id), uploader_id)
        author_id, author_type, audience = str(page_id), pages.AUTHOR_TYPE, Audience.PUBLIC
    if state != PostState.PUBLISHED and group_id:
        raise _bad_request(
            "Drafts and scheduled posts are not available in groups.", "group_drafts_not_supported"
        )
    if state == PostState.SCHEDULED:
        composer.check_publish_at(publish_at)
    else:
        publish_at = None
    location = composer.clean_location(location)
    feeling = composer.check_feeling(feeling)
    approval = ApprovalState.APPROVED
    if group_id:
        acc = require_group_member(str(author_id), group_id)
        if author_type != "user":
            raise _bad_request("Only people post in groups.")
        audience = Audience.GROUP
        if acc.post_approval and not acc.is_staff:
            approval = ApprovalState.PENDING
    elif audience == Audience.GROUP:
        raise _bad_request("Only a post in a group has the group audience.")
    if audience not in Audience.values:
        raise TaraAPIError("Invalid audience.", code="validation_error", http_status_code=400)
    if comment_policy not in CommentPolicy.values:
        raise _bad_request("Invalid comment policy.")
    if post_type in _VIDEO_TYPES and not media_ids:
        raise _bad_request("A video post needs its video.", "video_required")
    if not body and not media_ids and not shared_post_id and not feeling:
        raise TaraAPIError("Post must have content.", code="validation_error", http_status_code=400)

    tagged = composer.check_tags(author_id, tagged_ids or [])
    media_ids = [str(m) for m in media_ids or []]
    post_id = post_id or uuid7()
    if media_ids:
        _check_attachments(uploader_id, media_ids, post_type)
        # Restricted before the post exists. If the post then fails to commit,
        # the media point at a post that is never visible: owner-only, safe.
        # A draft's media stay restricted until it is published.
        restricted = audience != Audience.PUBLIC or state != PostState.PUBLISHED
        result = media_client.bind(uploader_id, str(post_id), media_ids, restricted=restricted)
        _check_bound(result)

    with transaction.atomic():
        post = Post.objects.create(
            id=post_id,
            author_id=author_id,
            author_type=author_type,
            type=Post.Type.POLL if poll else post_type,
            body=body,
            audience=audience,
            shared_post_id=shared_post_id,
            comment_policy=comment_policy,
            group_id=group_id or None,
            approval_state=approval,
            state=state,
            publish_at=publish_at,
            location=location,
            feeling=feeling,
        )
        if poll:
            _create_poll(post, poll)
        for i, media_id in enumerate(media_ids):
            PostMedia.objects.create(post=post, media_id=media_id, position=i)
        composer.set_tags(post, tagged)
        _attach_tags_and_mentions(post)
        if on_create is not None:
            on_create(post)
        if state == PostState.PUBLISHED:
            emit_created(post)
    return post


def emit_created(post: Post) -> None:
    """``post.created`` (and a group's ``group.post.published``) for a post that
    is published now: on create, or when a draft or scheduled post goes out."""
    author_id = str(post.author_id)
    events.emit(
        "post.created",
        subject_id=str(post.id),
        payload={
            "post_id": str(post.id),
            "author_id": author_id,
            "author_type": post.author_type,
            "type": post.type,
            "audience": post.audience,
            "excerpt": post.body[:280],
            "media_ids": [str(m.media_id) for m in post.media.all()],  # ordered by position
            "hashtags": sorted(post.hashtags.values_list("hashtag__tag", flat=True)),
            "mentions": sorted(set(post.mentions.values_list("mentioned_handle", flat=True))),
            "shared_post_id": str(post.shared_post_id) if post.shared_post_id else None,
            "created_at": post.created_at.isoformat(),
            # Search and feed treat a post with a group as non-public (1.11).
            "group_id": str(post.group_id) if post.group_id else None,
            "approval_state": post.approval_state,
            # People tagged (2C, additive): post notifies them after this commit.
            "tagged_ids": [str(a) for a in post.tags.values_list("account_id", flat=True)],
        },
        actor_id=author_id,
        partition_key=f"author:{author_id}",
    )
    if post.group_id and post.approval_state == ApprovalState.APPROVED:
        _emit_group_post_published(post)


def _chunks(ids: list[str]) -> list[list[str]]:
    return [ids[i : i + RECIPIENT_CHUNK] for i in range(0, len(ids), RECIPIENT_CHUNK)] or [[]]


def _group_recipients(post: Post, *, opted_in_only: bool, exclude: set[str]) -> list[str]:
    """Active members (from the read model), never anyone blocked either way with
    the post's author."""
    hidden = blocked_ids(str(post.author_id)) | exclude
    return [
        a
        for a in group_rm.member_ids(post.group_id, opted_in_only=opted_in_only)
        if a not in hidden
    ]


def _emit_group_event(event_type: str, post: Post, payload: dict, recipients, actor_id) -> None:
    if not settings.POST_EMIT_GROUP_EVENTS:
        return
    payload = {**payload, "handle": group_rm.handle_of(post.group_id)}
    chunks = _chunks(recipients)
    for index, chunk in enumerate(chunks):
        events.emit(
            event_type,
            subject_id=str(post.group_id),
            payload={**payload, "recipients": chunk, "chunk": index, "chunks": len(chunks)},
            actor_id=str(actor_id),
            partition_key=f"group:{post.group_id}",
        )


def _emit_group_post_published(post: Post) -> None:
    """Members who turned on post notifications for the group (off by default)."""
    author = str(post.author_id)
    recipients = _group_recipients(post, opted_in_only=True, exclude={author})
    if not recipients:
        return
    _emit_group_event(
        "group.post.published",
        post,
        {"group_id": str(post.group_id), "post_id": str(post.id), "author_id": author},
        recipients,
        author,
    )


def _editable_post(
    author_id: str, post_id: str, *, lock: bool = False, draft: bool = False
) -> Post:
    """The author's own live post. Removed or pending-review posts are 404: an
    edit must not change content a moderator is reviewing or has removed.
    ``draft`` picks a draft or scheduled post instead of a published one."""
    if draft:
        return composer.get_draft(author_id, post_id, lock=lock)
    qs = Post.objects.filter(
        id=post_id,
        deleted_at__isnull=True,
        moderation_status=Post.ModerationStatus.OK,
        state=PostState.PUBLISHED,
    )
    post = (qs.select_for_update() if lock else qs).first()
    if post is None:
        raise TaraAPIError("Post not found.", code="not_found", http_status_code=404)
    if str(post.author_id) != str(author_id):
        if post.author_type != pages.AUTHOR_TYPE:
            raise TaraAPIError("Post not found.", code="not_found", http_status_code=404)
        # A page's post: its owners, admins and editors (asked of profile on
        # the first read; the locked re-read inside the write trusts that).
        if not lock:
            pages.require_editor(str(post.author_id), str(author_id))
    return post


_UNSET = object()


def edit_post(
    author_id: str,
    post_id: str,
    body: str | None = None,
    *,
    audience: str | None = None,
    comment_policy: str | None = None,
    tagged_ids: list[str] | None = None,
    location: str | None = None,
    feeling: str | None = None,
    draft: bool = False,
    publish_at=_UNSET,
) -> Post:
    """Change the body, the audience, the comment policy, the tags, the
    location, the feeling, or any of them. With ``draft`` the post is the
    author's draft or scheduled post: ``publish_at`` schedules it (a date) or
    turns it back into a draft (``None``), and nothing is emitted.

    Moving to a non-public audience restricts the post's media through media
    before the write transaction (503 if media is down, nothing changes).
    Widening needs no media change: restricted media follow the post's
    visibility, which already lets the wider audience in.
    """
    extras = (tagged_ids, location, feeling)
    nothing = (
        body is None
        and audience is None
        and comment_policy is None
        and all(x is None for x in extras)
        and publish_at is _UNSET
    )
    if nothing:
        raise _bad_request("Nothing to change.")
    if publish_at is not _UNSET and not draft:
        raise _bad_request("Only a draft can be scheduled.")
    if publish_at not in (_UNSET, None):
        composer.check_publish_at(publish_at)
    if audience is not None and audience not in Audience.values:
        raise _bad_request("Invalid audience.")
    if comment_policy is not None and comment_policy not in CommentPolicy.values:
        raise _bad_request("Invalid comment policy.")
    if location is not None:
        location = composer.clean_location(location)
    if feeling is not None:
        feeling = composer.check_feeling(feeling)
    post = _editable_post(author_id, post_id, draft=draft)
    if post.author_type == pages.AUTHOR_TYPE:
        # As when it was published: public, no tags of people.
        if audience not in (None, Audience.PUBLIC):
            raise _bad_request("A page's post is public.", "page_audience")
        if tagged_ids:
            raise _bad_request("A page post can't tag people.", "page_tags_not_supported")
        audience, tagged_ids = None, None
    if tagged_ids is not None:
        tagged_ids = composer.check_tags(
            author_id, tagged_ids, already=post.tags.values_list("account_id", flat=True)
        )
    if post.group_id:
        if audience is not None and audience != Audience.GROUP:
            raise _bad_request("A post in a group keeps the group's audience.", "group_audience")
        audience = None
        require_group_member(str(author_id), post.group_id)  # removed or banned: refused
    elif audience == Audience.GROUP:
        raise _bad_request("Only a post in a group has the group audience.")
    if (
        body is None
        and audience is None
        and comment_policy is None
        and all(x is None for x in extras)
        and publish_at is _UNSET
    ):
        raise _bad_request("Nothing to change.")
    if audience is not None and audience != post.audience and post.shared_post_id:
        original = Post.objects.filter(id=post.shared_post_id).first()
        if original and AUDIENCE_RANK[audience] > AUDIENCE_RANK[original.audience]:
            raise _bad_request("A share cannot reach further than the original post.")
    # A draft's media are restricted already, until it is published.
    if audience is not None and audience != Audience.PUBLIC and not draft:
        # Even when unchanged: a concurrent edit may have widened the post
        # since this read, and binding is idempotent. Skipped ids are deleted,
        # or (posts from before ownership checks) not the author's. Media that
        # another post holds would not follow this audience: refused.
        media_ids = [str(m) for m in post.media.values_list("media_id", flat=True)]
        if media_ids:
            result = media_client.bind(author_id, str(post.id), media_ids, restricted=True)
            if result.attached_elsewhere:
                raise _bad_request(
                    "Media is already attached to another post.", "media_already_attached"
                )

    with transaction.atomic():
        # Removed meanwhile, or (a draft) published by the beat task → 404.
        post = _editable_post(author_id, post_id, lock=True, draft=draft)
        fields = ["updated_at"]
        new_mentions: list[str] = []
        new_tags: list[str] = []
        if audience is not None:
            post.audience = audience
            fields.append("audience")
        if comment_policy is not None:
            post.comment_policy = comment_policy
            fields.append("comment_policy")
        if location is not None:
            post.location = location
            fields.append("location")
        if feeling is not None:
            post.feeling = feeling
            fields.append("feeling")
        if publish_at is not _UNSET:
            post.publish_at = publish_at
            post.state = PostState.SCHEDULED if publish_at else PostState.DRAFT
            fields += ["publish_at", "state"]
        if body is not None:
            mentioned_before = set(post.mentions.values_list("mentioned_handle", flat=True))
            post.body = body
            fields.append("body")
        if draft and not (post.body or post.media.exists() or post.feeling):
            raise _bad_request("Post must have content.")
        post.save(update_fields=fields)
        if body is not None:
            post.hashtags.all().delete()
            post.mentions.all().delete()
            _, mentions = _attach_tags_and_mentions(post)
            new_mentions = sorted(set(mentions) - mentioned_before)
        if tagged_ids is not None:
            new_tags = composer.set_tags(post, tagged_ids)
        if post.is_published:
            _emit_updated(post, new_mentions=new_mentions, new_tagged_ids=new_tags)
    return with_detail(Post.objects.filter(id=post.id)).get()


def _emit_updated(
    post: Post, *, new_mentions: list[str], new_tagged_ids: list[str] | None = None
) -> None:
    """``post.updated`` with the full hashtag list: the excerpt is cut at 280
    characters, so search cannot re-derive the tags that come after it."""
    events.emit(
        "post.updated",
        subject_id=str(post.id),
        payload={
            "post_id": str(post.id),
            "author_id": str(post.author_id),
            "audience": post.audience,
            "comment_policy": post.comment_policy,
            "excerpt": post.body[:280],
            "hashtags": sorted(post.hashtags.values_list("hashtag__tag", flat=True)),
            "new_mentions": new_mentions,
            # People tagged by this edit (2C, additive): post notifies them.
            "new_tagged_ids": new_tagged_ids or [],
            **search_fields(post),
        },
        actor_id=str(post.author_id),
    )


def search_fields(post: Post) -> dict:
    """Additive ``post.updated`` fields (search v2, 1.15): what ``post.created``
    already carries, so a post that becomes public is indexed with its type,
    photos and date. Ids and enums only."""
    return {
        "type": post.type,
        "author_type": post.author_type,
        "media_ids": [str(m.media_id) for m in post.media.all()],  # ordered by position
        "created_at": post.created_at.isoformat(),
    }


def delete_post(author_id: str, post_id: str) -> None:
    """The author deletes their post; in a group, its moderators, admins and
    owners may delete any post too (asked of profile first)."""
    by = "author"
    # Drafts and scheduled posts are deleted through ``composer.delete_draft``.
    candidate = Post.objects.filter(
        id=post_id, deleted_at__isnull=True, state=PostState.PUBLISHED
    ).first()
    if candidate is not None and str(candidate.author_id) != str(author_id):
        if candidate.author_type == pages.AUTHOR_TYPE:
            pages.require_moderator(str(candidate.author_id), str(author_id))
            by = "page"
        elif not candidate.group_id:
            raise TaraAPIError("Post not found.", code="not_found", http_status_code=404)
        else:
            _require_group_staff(str(author_id), candidate)
            by = "group"
    with transaction.atomic():
        # Locked: a concurrent delete waits, then finds nothing, so the
        # original's share_count goes down once.
        qs = Post.objects.select_for_update().filter(
            id=post_id, deleted_at__isnull=True, state=PostState.PUBLISHED
        )
        if by == "author":
            qs = qs.filter(author_id=author_id)
        post = qs.first()
        if post is None:
            raise TaraAPIError("Post not found.", code="not_found", http_status_code=404)
        post.deleted_at = timezone.now()
        post.save(update_fields=["deleted_at"])
        if post.shared_post_id:
            Post.objects.filter(id=post.shared_post_id, share_count__gt=0).update(
                share_count=F("share_count") - 1
            )
        payload = {"post_id": str(post.id)}
        if by == "group":
            payload.update(by="group", group_id=str(post.group_id))
        events.emit(
            "post.deleted",
            subject_id=str(post.id),
            payload=payload,
            actor_id=str(author_id),
        )


def restrict_media_of_hidden_post(post_id: str) -> None:
    """Driven by the post's own ``post.deleted`` (author delete or moderator
    removal), after that commit: restricted media follow the post's visibility,
    so once the post is hidden nobody but the owner gets them. A public post's
    media were not restricted until now. Raises 503 while media is down, so the
    consumer retries; an approved removal needs no call back, since restricted
    media open up with the post.
    """
    post = Post.objects.filter(id=post_id).first()
    if post is None or post.is_visible:
        return  # gone, or shown again by the time this ran
    media_ids = [str(m) for m in post.media.values_list("media_id", flat=True)]
    if not media_ids:
        return
    if post.author_type != pages.AUTHOR_TYPE:
        media_client.bind(str(post.author_id), str(post.id), media_ids, restricted=True)
        return
    # A page post's media belong to the editors who uploaded them.
    owners: dict[str, list[str]] = {}
    for media_id, info in media_client.lookup(media_ids).items():
        owners.setdefault(info.owner_id, []).append(media_id)
    for owner_id, ids in owners.items():
        media_client.bind(owner_id, str(post.id), ids, restricted=True)


def get_post(viewer_id: str, post_id: str) -> Post:
    return _require_visible(viewer_id, post_id)


def with_detail(queryset):
    """What the serializer needs per post, loaded once for the whole list."""
    return queryset.select_related("poll").prefetch_related(
        "media", "poll__options", "reaction_counts", "tags"
    )


def author_posts_queryset(author_id: str | None):
    """Posts by one author (a profile timeline); filter with ``only_visible``."""
    if not author_id:
        raise TaraAPIError("author_id is required.", code="validation_error", http_status_code=400)
    try:
        author_id = str(uuid.UUID(str(author_id)))
    except ValueError as exc:
        raise _bad_request("author_id must be a UUID.") from exc
    # Group posts stay in their group: never on the author's timeline (1.11).
    return with_detail(
        Post.objects.filter(
            author_id=author_id,
            deleted_at__isnull=True,
            group_id__isnull=True,
            state=PostState.PUBLISHED,
        )
    )


# Profile timeline filters (plan 08, profile track): ``?year=``, ``?media=photo``
# (posts with photos, no video or reel) and ``?media=album`` (two photos or more).
TIMELINE_MEDIA = ("photo", "album")


def _parse_year(year) -> int | None:
    if year in (None, ""):
        return None
    try:
        value = int(str(year))
    except ValueError as exc:
        raise _bad_request("year must be a number.") from exc
    if not 1970 <= value <= 9999:
        raise _bad_request("year is out of range.")
    return value


def filter_timeline(queryset, *, year=None, media: str | None = None):
    """Narrow a timeline queryset by the year it was posted and its photos."""
    value = _parse_year(year)
    if value is not None:
        queryset = queryset.filter(created_at__year=value)
    if media in (None, ""):
        return queryset
    if media not in TIMELINE_MEDIA:
        raise _bad_request("media must be photo or album.")
    queryset = queryset.exclude(type__in=[Post.Type.VIDEO, Post.Type.REEL]).filter(
        Exists(PostMedia.objects.filter(post=OuterRef("pk")))
    )
    if media == "album":
        queryset = queryset.annotate(photo_count=Count("media", distinct=True)).filter(
            photo_count__gte=2
        )
    return queryset


def tagged_posts_queryset(account_id: str | None):
    """Posts by other people that tag ``account_id`` (a profile's "Posted by:
    others" and "Photos of you"); filter with ``only_visible``. Group posts stay
    in their group, and an author blocked either way with the tagged person is
    left out (the viewer's own blocks are applied by ``only_visible``)."""
    try:
        account_id = str(uuid.UUID(str(account_id)))
    except (TypeError, ValueError) as exc:
        raise _bad_request("tagged_id must be a UUID.") from exc
    blocked = blocked_ids(account_id)
    return with_detail(
        Post.objects.filter(
            tags__account_id=account_id,
            deleted_at__isnull=True,
            group_id__isnull=True,
            state=PostState.PUBLISHED,
        )
        .exclude(author_id=account_id)
        .exclude(author_id__in=blocked)
    )


def hashtag_posts_queryset(tag: str):
    """Posts carrying a hashtag; filter with ``only_visible``."""
    return with_detail(
        Post.objects.filter(
            hashtags__hashtag__tag=tag.lstrip("#").lower(),
            deleted_at__isnull=True,
            state=PostState.PUBLISHED,
        )
    )


def video_posts_queryset(author_id: str | None = None):
    """Published video posts outside groups, newest first (optionally one
    author's); filter with ``only_visible``."""
    qs = Post.objects.filter(
        type=Post.Type.VIDEO,
        deleted_at__isnull=True,
        group_id__isnull=True,
        state=PostState.PUBLISHED,
    )
    if author_id:
        try:
            qs = qs.filter(author_id=str(uuid.UUID(str(author_id))))
        except ValueError as exc:
            raise _bad_request("author_id must be a UUID.") from exc
    return with_detail(qs)


def only_visible(viewer_id: str, posts) -> list[Post]:
    posts = list(posts)
    rel_cache: dict = {}
    _prefetch_pages(viewer_id, posts, rel_cache)
    blocked = blocked_ids(viewer_id)
    return [p for p in posts if visible_to_viewer(viewer_id, p, rel_cache, blocked)]


def posts_by_ids(viewer_id: str, post_ids: list) -> list[Post]:
    """The posts the viewer may see, in the order requested. Others are left out."""
    posts = with_detail(Post.objects.filter(id__in=post_ids))
    by_id = {p.id: p for p in only_visible(viewer_id, posts)}
    return [by_id[i] for i in post_ids if i in by_id]


def viewer_state(viewer_id: str, posts: list[Post]) -> dict:
    """The viewer's own state for a list of posts, and the originals they may see."""
    ids = [p.id for p in posts]
    poll_ids = [p.poll.id for p in posts if p.type == Post.Type.POLL and hasattr(p, "poll")]
    shared_ids = {p.shared_post_id for p in posts if p.shared_post_id}
    originals = only_visible(viewer_id, with_detail(Post.objects.filter(id__in=shared_ids)))
    blocked = blocked_ids(viewer_id)
    top = composer.top_comments([p.id for p in posts if p.is_published], blocked)
    top_list = [c for comments in top.values() for c in comments]
    return {
        "blocked": blocked,
        "top_comments": top,
        "comment_reactions": comment_reactions_of(viewer_id, top_list) if top_list else {},
        "votes": dict(
            PollVote.objects.filter(poll_id__in=poll_ids, account_id=viewer_id).values_list(
                "poll_id", "option_id"
            )
        ),
        "shared": {p.id: p for p in originals},
        "reactions": dict(
            PostReaction.objects.filter(post_id__in=ids, account_id=viewer_id).values_list(
                "post_id", "type"
            )
        ),
        "saved": set(
            SavedItem.objects.filter(
                owner_id=viewer_id, item_type="post", item_id__in=ids
            ).values_list("item_id", flat=True)
        ),
    }


def apply_moderation(post_id: str, action: str) -> None:
    """Driven by moderation.actioned. Other actions do not change the post.

    ``remove`` hides the post and emits ``post.deleted``, so feeds and search drop
    it as they drop a deleted post. ``approve`` (an overturned removal) shows it
    again and emits ``post.updated``, so search indexes it again. Feed rows are
    not rebuilt; the post shows on the author's profile.
    """
    post = Post.objects.select_for_update().filter(id=post_id).first()
    if post is None:
        return
    removed = post.moderation_status == Post.ModerationStatus.REMOVED
    if action == "remove" and not removed:
        post.moderation_status = Post.ModerationStatus.REMOVED
        post.save(update_fields=["moderation_status"])
        events.emit(
            "post.deleted",
            subject_id=str(post.id),
            payload={"post_id": str(post.id)},
            actor_id=str(post.author_id),
        )
    elif action == "approve" and post.moderation_status != Post.ModerationStatus.OK:
        post.moderation_status = Post.ModerationStatus.OK
        post.save(update_fields=["moderation_status"])
        if post.deleted_at is None:
            _emit_updated(post, new_mentions=[])


# ---- reactions --------------------------------------------------------------


def _bump_type_count(post_id, reaction_type: str, delta: int) -> None:
    if delta > 0:
        PostReactionCount.objects.get_or_create(post_id=post_id, type=reaction_type)
        PostReactionCount.objects.filter(post_id=post_id, type=reaction_type).update(
            count=F("count") + delta
        )
    else:
        PostReactionCount.objects.filter(post_id=post_id, type=reaction_type).update(
            count=Greatest(F("count") + delta, 0)
        )


def react(viewer_id: str, post_id: str, reaction_type: str) -> PostReaction:
    """Add or change the viewer's reaction. Only a new reaction notifies anyone."""
    if reaction_type not in REACTION_TYPES:
        raise TaraAPIError("Invalid reaction.", code="validation_error", http_status_code=400)
    post = _require_visible(viewer_id, post_id)
    with transaction.atomic():
        reaction = (
            PostReaction.objects.select_for_update().filter(post=post, account_id=viewer_id).first()
        )
        if reaction is not None:
            if reaction.type != reaction_type:
                _bump_type_count(post.id, reaction.type, -1)
                _bump_type_count(post.id, reaction_type, +1)
                reaction.type = reaction_type
                reaction.save(update_fields=["type"])
            return reaction
        try:
            with transaction.atomic():
                reaction = PostReaction.objects.create(
                    post=post, account_id=viewer_id, type=reaction_type
                )
        except IntegrityError:  # a concurrent first reaction won; treat this as a change
            reaction = PostReaction.objects.select_for_update().get(post=post, account_id=viewer_id)
            if reaction.type != reaction_type:
                _bump_type_count(post.id, reaction.type, -1)
                _bump_type_count(post.id, reaction_type, +1)
                reaction.type = reaction_type
                reaction.save(update_fields=["type"])
            return reaction
        Post.objects.filter(id=post.id).update(reaction_count=F("reaction_count") + 1)
        _bump_type_count(post.id, reaction_type, +1)
        events.emit(
            "post.reacted",
            subject_id=str(post.id),
            payload={
                "post_id": str(post.id),
                "reactor": str(viewer_id),
                "reaction_type": reaction_type,
                "author_id": str(post.author_id),
            },
            actor_id=str(viewer_id),
        )
    return reaction


def unreact(viewer_id: str, post_id: str) -> None:
    """Remove the viewer's reaction. Always allowed: it only removes the viewer's own data."""
    with transaction.atomic():
        reaction = (
            PostReaction.objects.select_for_update()
            .select_related("post")
            .filter(post_id=post_id, account_id=viewer_id)
            .first()
        )
        if reaction is None:
            return
        reaction_type, post = reaction.type, reaction.post
        reaction.delete()
        Post.objects.filter(id=post.id).update(reaction_count=Greatest(F("reaction_count") - 1, 0))
        _bump_type_count(post.id, reaction_type, -1)
        events.emit(
            "post.unreacted",
            subject_id=str(post.id),
            payload={
                "post_id": str(post.id),
                "reactor": str(viewer_id),
                "reaction_type": reaction_type,
                "author_id": str(post.author_id),
            },
            actor_id=str(viewer_id),
        )


def list_reactions(viewer_id: str, post_id: str, reaction_type: str | None = None):
    """Who reacted, newest first. 404 when the viewer cannot see the post; accounts
    blocked either way are left out."""
    if reaction_type and reaction_type not in REACTION_TYPES:
        raise _bad_request("Invalid reaction.")
    post = _require_visible(viewer_id, post_id)
    qs = PostReaction.objects.filter(post=post).exclude(account_id__in=blocked_ids(viewer_id))
    if reaction_type:
        qs = qs.filter(type=reaction_type)
    return qs.order_by("-created_at")


def list_share_posts(viewer_id: str, post_id: str):
    """Shares of a post, newest first, as the sharers' own posts. 404 when the
    viewer cannot see the original. Filter the page with ``only_visible``: a
    share is listed only to someone who could open it."""
    post = _require_visible(viewer_id, post_id)
    return (
        Post.objects.filter(
            shared_post_id=post.id,
            deleted_at__isnull=True,
            moderation_status=Post.ModerationStatus.OK,
        )
        .exclude(author_id__in=blocked_ids(viewer_id))
        .order_by("-created_at")
    )


# ---- comments ---------------------------------------------------------------


def _comment_not_found() -> TaraAPIError:
    return TaraAPIError("Comment not found.", code="not_found", http_status_code=404)


def _check_comment_policy(viewer_id: str, post: Post) -> None:
    """The post's comment policy, checked on every new comment and reply."""
    if post.comment_policy == CommentPolicy.OFF:
        raise TaraAPIError(
            "Comments are turned off for this post.",
            code="comments_disabled",
            http_status_code=403,
        )
    if post.comment_policy == CommentPolicy.FRIENDS and str(viewer_id) != str(post.author_id):
        if not get_relationship(str(viewer_id), str(post.author_id)).are_friends:
            raise TaraAPIError(
                "Only the author's friends can comment on this post.",
                code="comments_friends_only",
                http_status_code=403,
            )


def visible_comment(viewer_id: str, comment_id: str) -> Comment:
    """A live comment on a post the viewer can see, by someone the viewer has not
    blocked (and who has not blocked the viewer). Anything else is 404."""
    comment = (
        Comment.objects.select_related("post", "parent")
        .filter(id=comment_id, deleted_at__isnull=True)
        .first()
    )
    if comment is None or (comment.parent_id and comment.parent.deleted_at is not None):
        raise _comment_not_found()
    if not visible_to_viewer(viewer_id, comment.post):
        raise _comment_not_found()
    if str(comment.author_id) != str(viewer_id) and _is_locally_blocked(
        viewer_id, comment.author_id
    ):
        raise _comment_not_found()
    return comment


def add_comment(viewer_id: str, post_id: str, body: str, reply_to_id: str | None = None) -> Comment:
    """A root comment, or a reply to ``reply_to_id`` (a root or a reply).

    Replies are flattened onto the thread root: ``parent`` is the root and
    ``reply_to`` is the comment answered. The target must be on this post, so a
    client can never attach a reply to another post's thread.
    """
    post = _require_visible(viewer_id, post_id)
    target = root = None
    if reply_to_id:
        target = (
            Comment.objects.select_related("parent")
            .filter(id=reply_to_id, post=post, deleted_at__isnull=True)
            .first()
        )
        if target is None or _is_locally_blocked(viewer_id, target.author_id):
            raise TaraAPIError("Parent comment not found.", code="not_found", http_status_code=404)
        root = target.parent if target.parent_id else target
        if root.deleted_at is not None or _is_locally_blocked(viewer_id, root.author_id):
            raise TaraAPIError("Parent comment not found.", code="not_found", http_status_code=404)
    if post.group_id:  # only members talk in a group; a ban a moment ago counts
        require_group_member(str(viewer_id), post.group_id)
        if post.approval_state == ApprovalState.PENDING:
            raise _bad_request("This post is waiting for approval.", "post_pending")
    _check_comment_policy(viewer_id, post)
    mentions = extract_mentions(body)
    with transaction.atomic():
        comment = Comment.objects.create(
            post=post, author_id=viewer_id, parent=root, reply_to=target, body=body
        )
        for handle in mentions:
            Mention.objects.create(comment=comment, mentioned_handle=handle)
        Post.objects.filter(id=post.id).update(comment_count=F("comment_count") + 1)
        if root is not None:
            Comment.objects.filter(id=root.id).update(reply_count=F("reply_count") + 1)
        events.emit(
            "comment.replied" if target else "post.commented",
            subject_id=str(comment.id),
            payload={
                "post_id": str(post.id),
                "comment_id": str(comment.id),
                "author": str(viewer_id),
                # The thread root: replies are flattened onto it.
                "parent_id": str(root.id) if root else None,
                # Whoever was answered: the reply notification goes to them.
                "parent_author_id": str(target.author_id) if target else None,
                "reply_to_id": str(target.id) if target else None,
                "root_author_id": str(root.author_id) if root else None,
                "post_author_id": str(post.author_id),
                "mentions": mentions,
            },
            actor_id=str(viewer_id),
        )
    return comment


def edit_comment(viewer_id: str, comment_id: str, body: str) -> Comment:
    """The author changes their comment's text. 404 for anyone else, and once the
    post is out of the author's sight."""
    comment = visible_comment(viewer_id, comment_id)
    if str(comment.author_id) != str(viewer_id):
        raise _comment_not_found()
    with transaction.atomic():
        comment = (
            Comment.objects.select_for_update()
            .filter(id=comment.id, deleted_at__isnull=True)
            .first()
        )
        if comment is None:
            raise _comment_not_found()
        before = set(comment.mentions.values_list("mentioned_handle", flat=True))
        comment.body = body
        comment.edited_at = timezone.now()
        comment.save(update_fields=["body", "edited_at"])
        comment.mentions.all().delete()
        mentions = extract_mentions(body)
        for handle in mentions:
            Mention.objects.create(comment=comment, mentioned_handle=handle)
        events.emit(
            "comment.edited",
            subject_id=str(comment.id),
            payload={
                "post_id": str(comment.post_id),
                "comment_id": str(comment.id),
                "author": str(viewer_id),
                "new_mentions": sorted(set(mentions) - before),
            },
            actor_id=str(viewer_id),
        )
    return Comment.objects.select_related("reply_to").get(id=comment.id)


def _remove_comment(comment: Comment, *, actor_id: str, by: str) -> int:
    """Soft-delete a comment, and the whole thread when it is a root. Keeps
    ``comment_count`` and the root's ``reply_count`` right, and returns the
    post's new ``comment_count``. Call inside a transaction."""
    locked = Comment.objects.select_for_update().filter(id=comment.id).first()
    if locked is None or locked.deleted_at is not None:  # a concurrent delete won
        return Post.objects.get(id=comment.post_id).comment_count
    comment = locked
    ids = [comment.id]
    if comment.parent_id is None:
        ids += list(
            Comment.objects.filter(parent=comment, deleted_at__isnull=True).values_list(
                "id", flat=True
            )
        )
    changes: dict = {"deleted_at": timezone.now()}
    if by == "moderation":
        changes["moderation_status"] = Comment.ModerationStatus.REMOVED
    Comment.objects.filter(id__in=ids).update(**changes)
    Post.objects.filter(id=comment.post_id).update(
        comment_count=Greatest(F("comment_count") - len(ids), 0)
    )
    if comment.parent_id:
        Comment.objects.filter(id=comment.parent_id).update(
            reply_count=Greatest(F("reply_count") - 1, 0)
        )
    post = Post.objects.get(id=comment.post_id)
    events.emit(
        "comment.deleted",
        subject_id=str(comment.id),
        payload={
            "post_id": str(post.id),
            "comment_id": str(comment.id),
            "author_id": str(comment.author_id),
            "post_author_id": str(post.author_id),
            "parent_id": str(comment.parent_id) if comment.parent_id else None,
            "removed_ids": [str(i) for i in ids],
            "by": by,  # author | post_author | moderation
        },
        actor_id=str(actor_id),
    )
    return post.comment_count


def delete_comment(viewer_id: str, comment_id: str) -> int:
    """The comment's author or the post's author may delete it (a root takes its
    replies with it). Returns the post's new ``comment_count``. Someone who can
    see the comment but may not delete it gets 403, anyone else 404."""
    comment = (
        Comment.objects.select_related("post")
        .filter(id=comment_id, deleted_at__isnull=True, post__deleted_at__isnull=True)
        .first()
    )
    if comment is None:
        raise _comment_not_found()
    if str(comment.author_id) == str(viewer_id):
        by = "author"
    elif str(comment.post.author_id) == str(viewer_id):
        by = "post_author"
    elif comment.post.group_id:
        visible_comment(viewer_id, comment_id)  # 404 when hidden
        _require_group_staff(str(viewer_id), comment.post)  # 403 without the role
        by = "group_moderator"
    else:
        visible_comment(viewer_id, comment_id)  # 404 when hidden
        raise TaraAPIError(
            "Only the comment's author or the post's author can delete it.",
            code="permission_denied",
            http_status_code=403,
        )
    with transaction.atomic():
        return _remove_comment(comment, actor_id=viewer_id, by=by)


def apply_comment_moderation(comment_id: str, action: str) -> None:
    """Driven by moderation.actioned for comments. ``remove`` hides the comment
    (and its thread, for a root); ``approve`` (an overturned removal) brings
    back exactly what that removal hid."""
    comment = Comment.objects.filter(id=comment_id).first()
    if comment is None:
        return
    with transaction.atomic():
        if action == "remove":
            _remove_comment(comment, actor_id=str(comment.author_id), by="moderation")
            return
        if action != "approve":
            return
        comment = Comment.objects.select_for_update().get(id=comment.id)
        if comment.moderation_status != Comment.ModerationStatus.REMOVED:
            return
        if comment.parent_id:
            root = Comment.objects.select_for_update().get(id=comment.parent_id)
            if root.deleted_at is not None:
                # Its thread is gone, so it stays hidden and uncounted. Under a
                # root that moderation removed it joins that removal, and comes
                # back (and is counted) if that is overturned too.
                if root.moderation_status == Comment.ModerationStatus.REMOVED:
                    Comment.objects.filter(id=comment.id).update(deleted_at=root.deleted_at)
                return
        # The rows that one removal hid share its timestamp.
        hidden = Comment.objects.filter(
            Q(id=comment.id) | Q(parent=comment),
            moderation_status=Comment.ModerationStatus.REMOVED,
            deleted_at=comment.deleted_at,
        )
        ids = list(hidden.values_list("id", flat=True))
        hidden.update(deleted_at=None, moderation_status=Comment.ModerationStatus.OK)
        Post.objects.filter(id=comment.post_id).update(comment_count=F("comment_count") + len(ids))
        if comment.parent_id:
            Comment.objects.filter(id=comment.parent_id).update(reply_count=F("reply_count") + 1)
        else:  # recounted: a reply removed on its own may have joined this removal
            live = Comment.objects.filter(parent=comment, deleted_at__isnull=True).count()
            Comment.objects.filter(id=comment.id).update(reply_count=live)
        events.emit(
            "comment.restored",
            subject_id=str(comment.id),
            payload={
                "post_id": str(comment.post_id),
                "comment_id": str(comment.id),
                "restored_ids": [str(i) for i in ids],
            },
            actor_id=str(comment.author_id),
        )


def list_comments(viewer_id: str, post_id: str):
    """Thread roots, oldest first. Replies are paged per root (``list_replies``),
    so a reply can never land on a page without its root."""
    post = _require_visible(viewer_id, post_id)
    return (
        post.comments.filter(parent__isnull=True, deleted_at__isnull=True)
        .exclude(author_id__in=blocked_ids(viewer_id))
        .select_related("reply_to")
        .order_by("created_at")
    )


def list_replies(viewer_id: str, root_id: str):
    """One thread's replies, oldest first. 404 when the root is hidden from the viewer."""
    root = visible_comment(viewer_id, root_id)
    return (
        Comment.objects.filter(parent=root, deleted_at__isnull=True)
        .exclude(author_id__in=blocked_ids(viewer_id))
        .select_related("reply_to")
        .order_by("created_at")
    )


def comment_reactions_of(viewer_id: str, comments) -> dict:
    """``{comment_id: type}`` for the viewer's own reactions on these comments."""
    return dict(
        CommentReaction.objects.filter(
            comment_id__in=[c.id for c in comments], account_id=viewer_id
        ).values_list("comment_id", "type")
    )


def react_comment(viewer_id: str, comment_id: str, reaction_type: str) -> Comment:
    """Add or change the viewer's reaction to a comment; only a new one emits."""
    if reaction_type not in REACTION_TYPES:
        raise _bad_request("Invalid reaction.")
    comment = visible_comment(viewer_id, comment_id)
    with transaction.atomic():
        try:
            with transaction.atomic():
                _, created = CommentReaction.objects.update_or_create(
                    comment=comment, account_id=viewer_id, defaults={"type": reaction_type}
                )
        except IntegrityError:  # a concurrent first reaction won
            created = False
            CommentReaction.objects.filter(comment=comment, account_id=viewer_id).update(
                type=reaction_type
            )
        if created:
            Comment.objects.filter(id=comment.id).update(reaction_count=F("reaction_count") + 1)
            events.emit(
                "comment.reacted",
                subject_id=str(comment.id),
                payload={
                    "post_id": str(comment.post_id),
                    "comment_id": str(comment.id),
                    "reactor": str(viewer_id),
                    "reaction_type": reaction_type,
                    "author_id": str(comment.author_id),
                },
                actor_id=str(viewer_id),
            )
    comment.refresh_from_db(fields=["reaction_count"])
    return comment


def unreact_comment(viewer_id: str, comment_id: str) -> None:
    """Always allowed: it only removes the viewer's own reaction."""
    with transaction.atomic():
        deleted, _ = CommentReaction.objects.filter(
            comment_id=comment_id, account_id=viewer_id
        ).delete()
        if deleted:
            Comment.objects.filter(id=comment_id).update(
                reaction_count=Greatest(F("reaction_count") - 1, 0)
            )


def report_comment(viewer_id: str, comment_id: str, reason: str) -> CommentReport:
    """As for posts: 404 (nothing written) when the reporter cannot see the
    comment, and one report per account per comment."""
    comment = visible_comment(viewer_id, comment_id)
    existing = CommentReport.objects.filter(comment=comment, reporter_id=viewer_id).first()
    if existing is not None:
        return existing
    try:
        with transaction.atomic():
            report = CommentReport.objects.create(
                comment=comment, reporter_id=viewer_id, reason=reason
            )
            events.emit(
                "comment.reported",
                subject_id=str(comment.id),
                payload={
                    "comment_id": str(comment.id),
                    "post_id": str(comment.post_id),
                    "reporter": str(viewer_id),
                    "reason": reason,
                    "owner_id": str(comment.author_id),
                },
                actor_id=str(viewer_id),
            )
    except IntegrityError:  # a concurrent duplicate won the unique constraint
        return CommentReport.objects.get(comment=comment, reporter_id=viewer_id)
    return report


# ---- shares -----------------------------------------------------------------


def share(viewer_id: str, post_id: str, *, body: str = "", audience: str | None = None) -> Post:
    """Create the sharer's own post pointing at the original.

    Sharing a share points at the first post. The new post cannot reach further
    than the original, and readers see the original only if they could anyway
    (``viewer_state`` checks each one), so a share never widens who can read it.
    """
    post = _require_visible(viewer_id, post_id)
    if post.shared_post_id:
        post = _require_visible(viewer_id, post.shared_post_id)
    if post.group_id:
        acc = group_rm.access(post.group_id, viewer_id)
        if acc is None or acc.privacy != "public":
            raise _bad_request(
                "Posts of private and hidden groups cannot be shared.", "group_post_not_shareable"
            )
    if audience == Audience.GROUP:
        raise _bad_request("A share cannot have the group audience.")
    audience = audience or (Audience.PUBLIC if post.group_id else post.audience)
    if AUDIENCE_RANK[audience] > AUDIENCE_RANK[post.audience]:
        raise TaraAPIError(
            "A share cannot reach further than the original post.",
            code="validation_error",
            http_status_code=400,
        )
    with transaction.atomic():
        shared = create_post(
            viewer_id,
            body=body,
            post_type=Post.Type.SHARE,
            audience=audience,
            shared_post_id=post.id,
        )
        Share.objects.create(post=post, account_id=viewer_id)
        Post.objects.filter(id=post.id).update(share_count=F("share_count") + 1)
        events.emit(
            "post.shared",
            subject_id=str(post.id),
            payload={
                "post_id": str(post.id),
                "share_post_id": str(shared.id),
                "sharer": str(viewer_id),
                "author_id": str(post.author_id),
            },
            actor_id=str(viewer_id),
        )
    return shared


# ---- polls ------------------------------------------------------------------


def vote(viewer_id: str, post_id: str, option_id: str) -> Post:
    post = _require_visible(viewer_id, post_id)
    poll = Poll.objects.filter(post=post).first()
    if poll is None:
        raise TaraAPIError("This post has no poll.", code="not_found", http_status_code=404)
    if poll.closes_at and poll.closes_at <= timezone.now():
        raise Conflict("This poll has closed.", code="conflict")
    option = poll.options.filter(id=option_id).first()
    if option is None:
        raise TaraAPIError("Option not found.", code="not_found", http_status_code=404)
    try:
        with transaction.atomic():
            PollVote.objects.create(poll=poll, option=option, account_id=viewer_id)
            PollOption.objects.filter(id=option.id).update(vote_count=F("vote_count") + 1)
    except IntegrityError as exc:
        raise Conflict("You have already voted.", code="conflict") from exc
    return with_detail(Post.objects.filter(id=post.id)).get()


# ---- link previews and mentions (run by the event consumer) ------------------


def refresh_link_preview(post_id: str) -> None:
    """Build the preview from the first URL in the post; the client never supplies one."""
    post = Post.objects.filter(id=post_id, deleted_at__isnull=True).first()
    if post is None:
        return
    url = linkpreview.first_url(post.body)
    current = post.link_preview or {}
    if not url:
        preview = None
    elif current.get("source_url") == url:
        return
    else:
        preview = linkpreview.fetch_preview(url)
        if preview:
            preview["source_url"] = url
    Post.objects.filter(id=post_id).update(link_preview=preview)


def notify_mentions(
    *,
    actor_id: str,
    post_id: str,
    handles: list[str],
    comment_id: str | None = None,
) -> int:
    """Tell mentioned accounts, but only those who can actually open the post."""
    post = Post.objects.filter(id=post_id).first()
    handles = list(dict.fromkeys(handles))[:MAX_MENTION_NOTIFICATIONS]
    if post is None or not handles:
        return 0
    sent = 0
    for account in resolve_handles(handles).values():
        if account == str(actor_id) or _is_locally_blocked(actor_id, account):
            continue
        if not visible_to_viewer(account, post):
            continue
        with transaction.atomic():
            events.emit(
                "user.mentioned",
                subject_id=str(post_id),
                payload={
                    "recipient": account,
                    "actor": str(actor_id),
                    "post_id": str(post_id),
                    "comment_id": comment_id,
                },
                actor_id=str(actor_id),
            )
        sent += 1
    return sent


# ---- saved content ----------------------------------------------------------


def _default_collection(owner_id: str) -> SavedCollection:
    # Not get_or_create: nothing makes the default unique, so two first saves at
    # once can both create one, and get() then fails on every later save.
    collection = (
        SavedCollection.objects.filter(owner_id=owner_id, is_default=True)
        .order_by("created_at", "id")
        .first()
    )
    return collection or SavedCollection.objects.create(
        owner_id=owner_id, is_default=True, name="Saved"
    )


def save_item(owner_id: str, item_type: str, item_id: str) -> SavedItem:
    collection = _default_collection(owner_id)
    item, _ = SavedItem.objects.get_or_create(
        owner_id=owner_id,
        item_type=item_type,
        item_id=item_id,
        defaults={"collection": collection},
    )
    return item


def unsave_item(owner_id: str, item_type: str, item_id: str) -> None:
    SavedItem.objects.filter(owner_id=owner_id, item_type=item_type, item_id=item_id).delete()


def list_saved(owner_id: str, item_type: str | None = None):
    qs = SavedItem.objects.filter(owner_id=owner_id)
    if item_type:
        qs = qs.filter(item_type=item_type)
    return qs.order_by("-created_at")


# ---- reports ----------------------------------------------------------------


def report_post(viewer_id: str, post_id: str, reason: str) -> PostReport:
    """Only a post the reporter can see may be reported (404 otherwise, nothing
    written). A repeat report by the same account returns the first one and
    emits nothing."""
    post = _require_visible(viewer_id, post_id)
    existing = PostReport.objects.filter(post=post, reporter_id=viewer_id).first()
    if existing is not None:
        return existing
    try:
        with transaction.atomic():
            report = PostReport.objects.create(post=post, reporter_id=viewer_id, reason=reason)
            events.emit(
                "post.reported",
                subject_id=str(post.id),
                payload={
                    "post_id": str(post.id),
                    "reporter": str(viewer_id),
                    "reason": reason,
                    "owner_id": str(post.author_id),
                },
                actor_id=str(viewer_id),
            )
    except IntegrityError:  # a concurrent duplicate won the unique constraint
        return PostReport.objects.get(post=post, reporter_id=viewer_id)
    return report


# ---- groups (roadmap 1.11) --------------------------------------------------------

GROUP_VIEWS = ("discussion", "featured", "pending", "media")
MAX_GROUP_REPORTS = 100


def _group_uuid(group_id) -> str:
    try:
        return str(uuid.UUID(str(group_id)))
    except ValueError as exc:
        raise _bad_request("group_id must be a UUID.") from exc


def group_posts_queryset(viewer_id: str, group_id, view: str = "discussion"):
    """One group's posts, filtered in SQL before paging (one access check for the
    whole page). 404 when the viewer may not read the group's content.

    ``discussion``: published posts, newest first. ``featured``: pinned
    announcements, newest pin first. ``pending``: posts waiting for approval
    (the staff see all of them, others only their own). ``media``: published
    posts with photos."""
    if view not in GROUP_VIEWS:
        raise _bad_request(f"view must be one of {', '.join(GROUP_VIEWS)}.")
    group_id = _group_uuid(group_id)
    acc = group_rm.access(group_id, viewer_id)
    if not group_rm.content_visible(str(viewer_id), acc):
        raise TaraAPIError("Group not found.", code="not_found", http_status_code=404)
    qs = (
        Post.objects.filter(group_id=group_id, deleted_at__isnull=True)
        .exclude(moderation_status=Post.ModerationStatus.REMOVED)
        .exclude(author_id__in=list(blocked_ids(str(viewer_id))))
    )
    if view == "pending":
        qs = qs.filter(approval_state=ApprovalState.PENDING)
        if not acc.is_staff:
            qs = qs.filter(author_id=viewer_id)
        return with_detail(qs.order_by("-created_at", "-id"))
    qs = qs.filter(approval_state=ApprovalState.APPROVED)
    if view == "featured":
        return with_detail(qs.filter(pinned_at__isnull=False).order_by("-pinned_at", "-id"))
    if view == "media":
        qs = qs.filter(Exists(PostMedia.objects.filter(post=OuterRef("pk"))))
    return with_detail(qs.order_by("-created_at", "-id"))


def _staff_post(actor_id: str, post_id: str, *, pending: bool | None = None) -> Post:
    post = Post.objects.filter(id=post_id, deleted_at__isnull=True).first()
    if post is None or not post.group_id or not post.is_visible:
        raise TaraAPIError("Post not found.", code="not_found", http_status_code=404)
    _require_group_staff(actor_id, post)
    if pending is not None and (post.approval_state == ApprovalState.PENDING) != pending:
        raise TaraAPIError(
            "This post is not waiting for approval." if pending else "Approve this post first.",
            code="conflict",
            http_status_code=409,
        )
    return post


def approve_group_post(actor_id: str, post_id: str) -> Post:
    """A moderator, admin or owner publishes a waiting post. Members who opted in
    hear about it then, and so do the people tagged in it (``post.approved``,
    which post consumes itself: nobody is told of a tag while the post waits)."""
    _staff_post(actor_id, post_id, pending=True)
    with transaction.atomic():
        post = Post.objects.select_for_update().get(id=post_id)
        if post.approval_state != ApprovalState.PENDING or post.deleted_at is not None:
            raise TaraAPIError("Post not found.", code="not_found", http_status_code=404)
        post.approval_state = ApprovalState.APPROVED
        post.save(update_fields=["approval_state", "updated_at"])
        _emit_group_post_published(post)
        if settings.POST_EMIT_GROUP_EVENTS:
            events.emit(
                "post.approved",
                subject_id=str(post.id),
                payload={
                    "post_id": str(post.id),
                    "group_id": str(post.group_id),
                    "author_id": str(post.author_id),
                    "approved_by": str(actor_id),
                    "tagged_ids": composer.tagged_ids_of(post),
                },
                actor_id=str(actor_id),
                partition_key=f"post:{post.id}",
            )
    return with_detail(Post.objects.filter(id=post.id)).get()


def decline_group_post(actor_id: str, post_id: str) -> None:
    """A waiting post that is declined is deleted (the author is not told)."""
    _staff_post(actor_id, post_id, pending=True)
    with transaction.atomic():
        post = Post.objects.select_for_update().filter(id=post_id, deleted_at__isnull=True).first()
        if post is None or post.approval_state != ApprovalState.PENDING:
            raise TaraAPIError("Post not found.", code="not_found", http_status_code=404)
        post.deleted_at = timezone.now()
        post.save(update_fields=["deleted_at"])
        events.emit(
            "post.deleted",
            subject_id=str(post.id),
            payload={"post_id": str(post.id), "by": "group", "group_id": str(post.group_id)},
            actor_id=str(actor_id),
        )


def pin_group_post(actor_id: str, post_id: str, *, pin: bool) -> Post:
    """Pin a published post as an announcement (members are told), or unpin it."""
    _staff_post(actor_id, post_id, pending=False)
    with transaction.atomic():
        post = Post.objects.select_for_update().get(id=post_id)
        if pin and post.pinned_at is None:
            post.pinned_at = timezone.now()
            post.save(update_fields=["pinned_at", "updated_at"])
            recipients = _group_recipients(post, opted_in_only=False, exclude={str(actor_id)})
            _emit_group_event(
                "group.announcement.pinned",
                post,
                {
                    "group_id": str(post.group_id),
                    "post_id": str(post.id),
                    "author_id": str(post.author_id),
                },
                recipients,
                actor_id,
            )
        elif not pin and post.pinned_at is not None:
            post.pinned_at = None
            post.save(update_fields=["pinned_at", "updated_at"])
    return with_detail(Post.objects.filter(id=post.id)).get()


def _require_group_staff_for(actor_id: str, group_id: str):
    acc = group_rm.access(group_id, actor_id, fresh=True)
    if not group_rm.content_visible(str(actor_id), acc):
        raise TaraAPIError("Group not found.", code="not_found", http_status_code=404)
    if not acc.is_staff:
        raise TaraAPIError(
            "Only the group's moderators can do this.",
            code="permission_denied",
            http_status_code=403,
        )
    return acc


def _report_item(target_type: str, row, post_id: str) -> dict:
    return {
        "target_type": target_type,
        "target_id": str(row.id),
        "post_id": post_id,
        "author_id": str(row.author_id),
        "excerpt": row.body[:280],
        "report_count": row.n,
        "reasons": sorted(set(row.reports.values_list("reason", flat=True)[:20]))[:5],
        "last_reported_at": row.last,
    }


def group_reported_content(actor_id: str, group_id) -> list[dict]:
    """Posts and comments of the group that members reported, for the group's
    staff: the newest report first, leaving out what a moderator already kept
    (until it is reported again) and what is already gone."""
    group_id = _group_uuid(group_id)
    _require_group_staff_for(actor_id, group_id)
    reviewed = {
        (r.target_type, str(r.target_id)): r.reviewed_at
        for r in GroupReportReview.objects.filter(group_id=group_id)
    }
    hidden = blocked_ids(str(actor_id))
    posts = (
        Post.objects.filter(group_id=group_id, deleted_at__isnull=True, reports__isnull=False)
        .exclude(moderation_status=Post.ModerationStatus.REMOVED)
        .annotate(n=Count("reports", distinct=True), last=Max("reports__created_at"))
        .order_by("-last")[:MAX_GROUP_REPORTS]
    )
    comments = (
        Comment.objects.filter(
            post__group_id=group_id, deleted_at__isnull=True, reports__isnull=False
        )
        .annotate(n=Count("reports", distinct=True), last=Max("reports__created_at"))
        .order_by("-last")[:MAX_GROUP_REPORTS]
    )
    items = [_report_item("post", p, str(p.id)) for p in posts] + [
        _report_item("comment", c, str(c.post_id)) for c in comments
    ]

    def keep(item: dict) -> bool:
        seen = reviewed.get((item["target_type"], item["target_id"]))
        return item["author_id"] not in hidden and (seen is None or seen < item["last_reported_at"])

    items = sorted(filter(keep, items), key=lambda i: i["last_reported_at"], reverse=True)
    for item in items:
        item["last_reported_at"] = item["last_reported_at"].isoformat()
    return items[:MAX_GROUP_REPORTS]


def dismiss_group_report(actor_id: str, group_id, target_type: str, target_id: str) -> None:
    """Keep a reported post or comment: it leaves the queue until reported again."""
    if target_type not in ("post", "comment"):
        raise _bad_request("target_type must be post or comment.")
    group_id = _group_uuid(group_id)
    _require_group_staff_for(actor_id, group_id)
    in_group = (
        Post.objects.filter(id=target_id, group_id=group_id)
        if target_type == "post"
        else Comment.objects.filter(id=target_id, post__group_id=group_id)
    )
    if not in_group.exists():
        raise TaraAPIError("Not found.", code="not_found", http_status_code=404)
    GroupReportReview.objects.update_or_create(
        target_type=target_type,
        target_id=target_id,
        defaults={"group_id": group_id, "reviewed_by": actor_id},
    )
