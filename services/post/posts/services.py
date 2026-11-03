"""Post business logic: posts, audience visibility, comments, reactions, shares, saves."""

from __future__ import annotations

import re
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.db.models import F, Q
from django.utils import timezone

from tara_common.exceptions import Conflict, TaraAPIError

from . import events, linkpreview
from .clients import get_relationship, resolve_handles
from .models import (
    REACTION_TYPES,
    Audience,
    BlockedPair,
    Comment,
    Hashtag,
    Mention,
    Poll,
    PollOption,
    PollVote,
    Post,
    PostHashtag,
    PostMedia,
    PostReaction,
    PostReport,
    SavedCollection,
    SavedItem,
    Share,
)

# Not inside a word, a URL fragment or an email address.
_HASHTAG_RE = re.compile(r"(?<![\w/&#])#(\w{1,80})")
_MENTION_RE = re.compile(r"(?<![\w.@/])@([a-zA-Z0-9_]{3,30})")
MAX_MENTION_NOTIFICATIONS = 10
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
) -> Post:
    if audience not in Audience.values:
        raise TaraAPIError("Invalid audience.", code="validation_error", http_status_code=400)
    if not body and not media_ids and not shared_post_id:
        raise TaraAPIError("Post must have content.", code="validation_error", http_status_code=400)

    with transaction.atomic():
        post = Post.objects.create(
            author_id=author_id,
            author_type=author_type,
            type=Post.Type.POLL if poll else post_type,
            body=body,
            audience=audience,
            shared_post_id=shared_post_id,
        )
        if poll:
            _create_poll(post, poll)
        for i, media_id in enumerate(media_ids or []):
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
                "media_ids": [str(m) for m in (media_ids or [])],
                "hashtags": tags,
                "mentions": mentions,
                "shared_post_id": str(shared_post_id) if shared_post_id else None,
                "created_at": post.created_at.isoformat(),
            },
            actor_id=str(author_id),
            partition_key=f"author:{author_id}",
        )
    return post


def edit_post(author_id: str, post_id: str, body: str) -> Post:
    post = Post.objects.filter(id=post_id, author_id=author_id, deleted_at__isnull=True).first()
    if post is None:
        raise TaraAPIError("Post not found.", code="not_found", http_status_code=404)
    with transaction.atomic():
        mentioned_before = set(post.mentions.values_list("mentioned_handle", flat=True))
        post.body = body
        post.save(update_fields=["body", "updated_at"])
        post.hashtags.all().delete()
        post.mentions.all().delete()
        _, mentions = _attach_tags_and_mentions(post)
        events.emit(
            "post.updated",
            subject_id=str(post.id),
            payload={
                "post_id": str(post.id),
                "author_id": str(author_id),
                "audience": post.audience,
                "excerpt": body[:280],
                "new_mentions": sorted(set(mentions) - mentioned_before),
            },
            actor_id=str(author_id),
        )
    return post


def delete_post(author_id: str, post_id: str) -> None:
    post = Post.objects.filter(id=post_id, author_id=author_id, deleted_at__isnull=True).first()
    if post is None:
        raise TaraAPIError("Post not found.", code="not_found", http_status_code=404)
    with transaction.atomic():
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


def get_post(viewer_id: str, post_id: str) -> Post:
    return _require_visible(viewer_id, post_id)


def with_detail(queryset):
    """What the serializer needs per post, loaded once for the whole list."""
    return queryset.select_related("poll").prefetch_related("media", "poll__options")


def author_posts_queryset(author_id: str | None):
    """Posts by one author (a profile timeline); filter with ``only_visible``."""
    if not author_id:
        raise TaraAPIError("author_id is required.", code="validation_error", http_status_code=400)
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
    """Driven by moderation.actioned. Other actions do not change the post."""
    post = Post.objects.filter(id=post_id).first()
    if post is None:
        return
    if action == "remove":
        post.moderation_status = Post.ModerationStatus.REMOVED
        post.save(update_fields=["moderation_status"])
        # Feeds and search drop it the same way they drop a deleted post.
        events.emit(
            "post.deleted",
            subject_id=str(post.id),
            payload={"post_id": str(post.id)},
            actor_id=str(post.author_id),
        )
    elif action == "approve":  # appeal overturned; feeds rebuild as people post
        post.moderation_status = Post.ModerationStatus.OK
        post.save(update_fields=["moderation_status"])


# ---- reactions --------------------------------------------------------------


def react(viewer_id: str, post_id: str, reaction_type: str) -> PostReaction:
    if reaction_type not in REACTION_TYPES:
        raise TaraAPIError("Invalid reaction.", code="validation_error", http_status_code=400)
    post = _require_visible(viewer_id, post_id)
    with transaction.atomic():
        reaction, created = PostReaction.objects.update_or_create(
            post=post, account_id=viewer_id, defaults={"type": reaction_type}
        )
        if created:  # Changing an existing reaction notifies nobody.
            Post.objects.filter(id=post.id).update(reaction_count=F("reaction_count") + 1)
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
    deleted, _ = PostReaction.objects.filter(post_id=post_id, account_id=viewer_id).delete()
    if deleted:
        Post.objects.filter(id=post_id).update(reaction_count=F("reaction_count") - 1)


# ---- comments ---------------------------------------------------------------


def add_comment(viewer_id: str, post_id: str, body: str, parent_id: str | None = None) -> Comment:
    post = _require_visible(viewer_id, post_id)
    parent = None
    if parent_id:
        parent = Comment.objects.filter(id=parent_id, post=post, deleted_at__isnull=True).first()
        if parent is None:
            raise TaraAPIError("Parent comment not found.", code="not_found", http_status_code=404)
        if _is_locally_blocked(viewer_id, parent.author_id):
            raise TaraAPIError("Parent comment not found.", code="not_found", http_status_code=404)
    with transaction.atomic():
        comment = Comment.objects.create(post=post, author_id=viewer_id, parent=parent, body=body)
        for handle in extract_mentions(body):
            Mention.objects.create(comment=comment, mentioned_handle=handle)
        Post.objects.filter(id=post.id).update(comment_count=F("comment_count") + 1)
        event_type = "comment.replied" if parent else "post.commented"
        events.emit(
            event_type,
            subject_id=str(comment.id),
            payload={
                "post_id": str(post.id),
                "comment_id": str(comment.id),
                "author": str(viewer_id),
                "parent_id": str(parent_id) if parent_id else None,
                "parent_author_id": str(parent.author_id) if parent else None,
                "post_author_id": str(post.author_id),
                "mentions": extract_mentions(body),
            },
            actor_id=str(viewer_id),
        )
    return comment


def list_comments(viewer_id: str, post_id: str):
    post = _require_visible(viewer_id, post_id)
    return (
        post.comments.filter(deleted_at__isnull=True)
        .exclude(author_id__in=blocked_ids(viewer_id))
        .order_by("created_at")
    )


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
    collection, _ = SavedCollection.objects.get_or_create(
        owner_id=owner_id, is_default=True, defaults={"name": "Saved"}
    )
    return collection


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
    post = Post.objects.filter(id=post_id).first()
    if post is None:
        raise TaraAPIError("Post not found.", code="not_found", http_status_code=404)
    report = PostReport.objects.create(post=post, reporter_id=viewer_id, reason=reason)
    events.emit(
        "post.reported",
        subject_id=str(post.id),
        payload={"post_id": str(post.id), "reporter": str(viewer_id), "reason": reason},
        actor_id=str(viewer_id),
    )
    return report
