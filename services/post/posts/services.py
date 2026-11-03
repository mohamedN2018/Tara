"""Post business logic: posts, audience visibility, comments, reactions, shares, saves."""

from __future__ import annotations

import re

from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from tara_common.exceptions import TaraAPIError

from . import events
from .clients import get_relationship
from .models import (
    REACTION_TYPES,
    Audience,
    BlockedPair,
    Comment,
    Hashtag,
    Mention,
    Post,
    PostHashtag,
    PostMedia,
    PostReaction,
    PostReport,
    SavedCollection,
    SavedItem,
    Share,
)

_HASHTAG_RE = re.compile(r"#(\w{1,80})")
_MENTION_RE = re.compile(r"@([a-zA-Z0-9_]{3,30})")


def extract_hashtags(body: str) -> list[str]:
    return sorted({m.lower() for m in _HASHTAG_RE.findall(body or "")})


def extract_mentions(body: str) -> list[str]:
    return sorted({m.lower() for m in _MENTION_RE.findall(body or "")})


# ---- visibility -------------------------------------------------------------


def _is_locally_blocked(a: str, b: str) -> bool:
    return BlockedPair.objects.filter(
        Q(blocker_id=a, blocked_id=b) | Q(blocker_id=b, blocked_id=a)
    ).exists()


def visible_to_viewer(viewer_id: str, post: Post, rel_cache: dict | None = None) -> bool:
    """``rel_cache`` keeps one Graph call per author when checking many posts."""
    if not post.is_visible:
        return False
    if str(post.author_id) == str(viewer_id):
        return True
    if _is_locally_blocked(viewer_id, post.author_id):
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


def create_post(
    author_id: str,
    *,
    body: str = "",
    post_type: str = Post.Type.TEXT,
    audience: str = Audience.PUBLIC,
    media_ids: list[str] | None = None,
    shared_post_id: str | None = None,
    link_preview: dict | None = None,
    author_type: str = "user",
) -> Post:
    if audience not in Audience.values:
        raise TaraAPIError("Invalid audience.", code="validation_error", http_status_code=400)
    if not body and not media_ids and not shared_post_id:
        raise TaraAPIError("Post must have content.", code="validation_error", http_status_code=400)

    with transaction.atomic():
        post = Post.objects.create(
            author_id=author_id,
            author_type=author_type,
            type=post_type,
            body=body,
            audience=audience,
            shared_post_id=shared_post_id,
            link_preview=link_preview,
        )
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
        post.body = body
        post.save(update_fields=["body", "updated_at"])
        post.hashtags.all().delete()
        post.mentions.all().delete()
        _attach_tags_and_mentions(post)
        events.emit(
            "post.updated",
            subject_id=str(post.id),
            payload={"post_id": str(post.id), "excerpt": body[:280]},
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
        events.emit(
            "post.deleted",
            subject_id=str(post.id),
            payload={"post_id": str(post.id)},
            actor_id=str(author_id),
        )


def get_post(viewer_id: str, post_id: str) -> Post:
    return _require_visible(viewer_id, post_id)


def author_posts_queryset(author_id: str | None):
    """Posts by one author (a profile timeline); filter with ``only_visible``."""
    if not author_id:
        raise TaraAPIError("author_id is required.", code="validation_error", http_status_code=400)
    return Post.objects.filter(author_id=author_id, deleted_at__isnull=True).prefetch_related(
        "media"
    )


def only_visible(viewer_id: str, posts) -> list[Post]:
    rel_cache: dict = {}
    return [p for p in posts if visible_to_viewer(viewer_id, p, rel_cache)]


def posts_by_ids(viewer_id: str, post_ids: list) -> list[Post]:
    """The posts the viewer may see, in the order requested. Others are left out."""
    posts = Post.objects.filter(id__in=post_ids).prefetch_related("media")
    by_id = {p.id: p for p in only_visible(viewer_id, posts)}
    return [by_id[i] for i in post_ids if i in by_id]


def viewer_state(viewer_id: str, posts: list[Post]) -> dict:
    """The viewer's own reaction and saved flag for a list of posts."""
    ids = [p.id for p in posts]
    return {
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


# ---- reactions --------------------------------------------------------------


def react(viewer_id: str, post_id: str, reaction_type: str) -> PostReaction:
    if reaction_type not in REACTION_TYPES:
        raise TaraAPIError("Invalid reaction.", code="validation_error", http_status_code=400)
    post = _require_visible(viewer_id, post_id)
    with transaction.atomic():
        reaction, created = PostReaction.objects.update_or_create(
            post=post, account_id=viewer_id, defaults={"type": reaction_type}
        )
        if created:
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
                "post_author_id": str(post.author_id),
            },
            actor_id=str(viewer_id),
        )
    return comment


def list_comments(viewer_id: str, post_id: str):
    post = _require_visible(viewer_id, post_id)
    return post.comments.filter(deleted_at__isnull=True).order_by("created_at")


# ---- shares -----------------------------------------------------------------


def share(viewer_id: str, post_id: str) -> Share:
    post = _require_visible(viewer_id, post_id)
    with transaction.atomic():
        share_row = Share.objects.create(post=post, account_id=viewer_id)
        Post.objects.filter(id=post.id).update(share_count=F("share_count") + 1)
        events.emit(
            "post.shared",
            subject_id=str(post.id),
            payload={"post_id": str(post.id), "sharer": str(viewer_id)},
            actor_id=str(viewer_id),
        )
    return share_row


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
