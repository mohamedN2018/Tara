"""Post business logic: posts, audience visibility, comments, reactions, shares, saves."""

from __future__ import annotations

import re
import uuid
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.db.models import F, Q
from django.db.models.functions import Greatest
from django.utils import timezone

from tara_common.exceptions import Conflict, TaraAPIError
from tara_events.envelope import uuid7

from . import events, linkpreview, media_client
from .clients import get_relationship, resolve_handles
from .models import (
    REACTION_TYPES,
    Audience,
    BlockedPair,
    Comment,
    CommentPolicy,
    CommentReaction,
    CommentReport,
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
    SavedCollection,
    SavedItem,
    Share,
)

# Not inside a word, a URL fragment or an email address.
_HASHTAG_RE = re.compile(r"(?<![\w/&#])#(\w{1,80})")
_MENTION_RE = re.compile(r"(?<![\w.@/])@([a-zA-Z0-9_]{3,30})")
MAX_MENTION_NOTIFICATIONS = 10
MAX_MEDIA_PER_POST = 10
# Media still processing are accepted: the composer posts right after upload.
_ATTACHABLE_STATUSES = {"processing", "ready"}
AUDIENCE_RANK = {
    Audience.ONLY_ME: 0,
    Audience.FRIENDS: 1,
    Audience.FOLLOWERS: 2,
    Audience.PUBLIC: 3,
}


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


def _video_not_supported() -> TaraAPIError:
    # Video posts come with the video pipeline (roadmap step 5, decision D1).
    return _bad_request("Video posts are not supported yet.", "video_not_supported_yet")


def _check_attachments(author_id: str, media_ids: list[str]) -> None:
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
    if any(i.kind == "video" for i in infos):
        raise _video_not_supported()
    if any(i.kind != "image" for i in infos):
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
) -> Post:
    """Media are checked and bound to the post through media before the write
    transaction opens, so a media outage fails the request (503) instead of
    publishing restricted photos as public."""
    if audience not in Audience.values:
        raise TaraAPIError("Invalid audience.", code="validation_error", http_status_code=400)
    if comment_policy not in CommentPolicy.values:
        raise _bad_request("Invalid comment policy.")
    if post_type == Post.Type.VIDEO:
        raise _video_not_supported()
    if not body and not media_ids and not shared_post_id:
        raise TaraAPIError("Post must have content.", code="validation_error", http_status_code=400)

    media_ids = [str(m) for m in media_ids or []]
    post_id = uuid7()
    if media_ids:
        _check_attachments(author_id, media_ids)
        # Restricted before the post exists. If the post then fails to commit,
        # the media point at a post that is never visible: owner-only, safe.
        result = media_client.bind(
            author_id, str(post_id), media_ids, restricted=audience != Audience.PUBLIC
        )
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
        )
        if poll:
            _create_poll(post, poll)
        for i, media_id in enumerate(media_ids):
            PostMedia.objects.create(post=post, media_id=media_id, position=i)
        tags, mentions = _attach_tags_and_mentions(post)
        events.emit(
            "post.created",
            subject_id=str(post.id),
            payload={
                "post_id": str(post.id),
                "author_id": str(author_id),
                "author_type": author_type,
                "type": post.type,
                "audience": audience,
                "excerpt": body[:280],
                "media_ids": media_ids,
                "hashtags": tags,
                "mentions": mentions,
                "shared_post_id": str(shared_post_id) if shared_post_id else None,
                "created_at": post.created_at.isoformat(),
            },
            actor_id=str(author_id),
            partition_key=f"author:{author_id}",
        )
    return post


def _editable_post(author_id: str, post_id: str, *, lock: bool = False) -> Post:
    """The author's own live post. Removed or pending-review posts are 404: an
    edit must not change content a moderator is reviewing or has removed."""
    qs = Post.objects.filter(
        id=post_id,
        author_id=author_id,
        deleted_at__isnull=True,
        moderation_status=Post.ModerationStatus.OK,
    )
    post = (qs.select_for_update() if lock else qs).first()
    if post is None:
        raise TaraAPIError("Post not found.", code="not_found", http_status_code=404)
    return post


def edit_post(
    author_id: str,
    post_id: str,
    body: str | None = None,
    *,
    audience: str | None = None,
    comment_policy: str | None = None,
) -> Post:
    """Change the body, the audience, the comment policy, or any of them.

    Moving to a non-public audience restricts the post's media through media
    before the write transaction (503 if media is down, nothing changes).
    Widening needs no media change: restricted media follow the post's
    visibility, which already lets the wider audience in.
    """
    if body is None and audience is None and comment_policy is None:
        raise _bad_request("Nothing to change.")
    if audience is not None and audience not in Audience.values:
        raise _bad_request("Invalid audience.")
    if comment_policy is not None and comment_policy not in CommentPolicy.values:
        raise _bad_request("Invalid comment policy.")
    post = _editable_post(author_id, post_id)
    if audience is not None and audience != post.audience and post.shared_post_id:
        original = Post.objects.filter(id=post.shared_post_id).first()
        if original and AUDIENCE_RANK[audience] > AUDIENCE_RANK[original.audience]:
            raise _bad_request("A share cannot reach further than the original post.")
    if audience is not None and audience != Audience.PUBLIC:
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
        post = _editable_post(author_id, post_id, lock=True)  # removed meanwhile → 404
        fields = ["updated_at"]
        new_mentions: list[str] = []
        if audience is not None:
            post.audience = audience
            fields.append("audience")
        if comment_policy is not None:
            post.comment_policy = comment_policy
            fields.append("comment_policy")
        if body is not None:
            mentioned_before = set(post.mentions.values_list("mentioned_handle", flat=True))
            post.body = body
            fields.append("body")
        post.save(update_fields=fields)
        if body is not None:
            post.hashtags.all().delete()
            post.mentions.all().delete()
            _, mentions = _attach_tags_and_mentions(post)
            new_mentions = sorted(set(mentions) - mentioned_before)
        _emit_updated(post, new_mentions=new_mentions)
    return post


def _emit_updated(post: Post, *, new_mentions: list[str]) -> None:
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
        },
        actor_id=str(post.author_id),
    )


def delete_post(author_id: str, post_id: str) -> None:
    with transaction.atomic():
        # Locked: a concurrent delete waits, then finds nothing, so the
        # original's share_count goes down once.
        post = (
            Post.objects.select_for_update()
            .filter(id=post_id, author_id=author_id, deleted_at__isnull=True)
            .first()
        )
        if post is None:
            raise TaraAPIError("Post not found.", code="not_found", http_status_code=404)
        post.deleted_at = timezone.now()
        post.save(update_fields=["deleted_at"])
        if post.shared_post_id:
            Post.objects.filter(id=post.shared_post_id, share_count__gt=0).update(
                share_count=F("share_count") - 1
            )
        events.emit(
            "post.deleted",
            subject_id=str(post.id),
            payload={"post_id": str(post.id)},
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
    if media_ids:
        media_client.bind(str(post.author_id), str(post.id), media_ids, restricted=True)


def get_post(viewer_id: str, post_id: str) -> Post:
    return _require_visible(viewer_id, post_id)


def with_detail(queryset):
    """What the serializer needs per post, loaded once for the whole list."""
    return queryset.select_related("poll").prefetch_related(
        "media", "poll__options", "reaction_counts"
    )


def author_posts_queryset(author_id: str | None):
    """Posts by one author (a profile timeline); filter with ``only_visible``."""
    if not author_id:
        raise TaraAPIError("author_id is required.", code="validation_error", http_status_code=400)
    try:
        author_id = str(uuid.UUID(str(author_id)))
    except ValueError as exc:
        raise _bad_request("author_id must be a UUID.") from exc
    return with_detail(Post.objects.filter(author_id=author_id, deleted_at__isnull=True))


def hashtag_posts_queryset(tag: str):
    """Posts carrying a hashtag; filter with ``only_visible``."""
    return with_detail(
        Post.objects.filter(hashtags__hashtag__tag=tag.lstrip("#").lower(), deleted_at__isnull=True)
    )


def only_visible(viewer_id: str, posts) -> list[Post]:
    rel_cache: dict = {}
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
    return {
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
    audience = audience or post.audience
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
