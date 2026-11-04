"""The composer's extras (2C): people tags, location, feeling, drafts, scheduling,
and the comment preview (``top_comments``) of a list of posts.

Drafts and scheduled posts are seen by nobody but their author, and only through
``/posts/drafts/``: ``Post.is_visible`` is false for them, so every public read
path (detail, batch, timelines, hashtags, search export, media visibility)
already answers 404 or leaves them out. Nothing is emitted for a draft. Publishing
(by the author, or by the beat task at ``publish_at``) emits the normal
``post.created`` at that moment, as if the post had just been written.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import F, Q, Window
from django.db.models.functions import RowNumber
from django.utils import timezone

from tara_common.exceptions import TaraAPIError

from . import events, media_client
from .models import (
    FEELINGS,
    ApprovalState,
    Audience,
    Comment,
    Post,
    PostSettings,
    PostState,
    PostTag,
    TagPolicy,
)

logger = logging.getLogger("tara.post.composer")

MAX_TAGS = 20
LOCATION_MAX = 120
MAX_SCHEDULE_AHEAD = timedelta(days=75)
TOP_COMMENTS = 2
PUBLISH_BATCH = 100
MAX_TAG_NOTIFICATIONS = MAX_TAGS

# Control and invisible formatting characters (bidi overrides and isolates can
# make a place name read as something else), never kept in a location.
_BIDI = {chr(c) for c in (*range(0x202A, 0x202F), *range(0x2066, 0x206A), 0x200E, 0x200F)}
# Joiners are formatting characters too, but text needs them: ZWNJ keeps Persian,
# Urdu and Kurdish letters apart, ZWJ builds emoji sequences.
_JOINERS = {"\u200c", "\u200d"}
_JOINER_RUN = re.compile("[\u200c\u200d]{2,}")
_LOOSE_JOINER = re.compile("(?<!\\S)[\u200c\u200d]+|[\u200c\u200d]+(?!\\S)")
_SPACES = re.compile(r"\s+")


def _bad_request(message: str, code: str = "validation_error") -> TaraAPIError:
    return TaraAPIError(message, code=code, http_status_code=400)


def _not_found() -> TaraAPIError:
    return TaraAPIError("Post not found.", code="not_found", http_status_code=404)


# ---- location, feeling, publish_at ----------------------------------------------


def clean_location(value: str | None) -> str:
    """Free text: control and bidi characters removed (ZWNJ and ZWJ kept between
    characters), spaces collapsed, at most
    ``LOCATION_MAX`` characters (400 beyond that, never cut silently)."""
    text = "".join(
        ch
        for ch in unicodedata.normalize("NFC", value or "")
        if ch not in _BIDI
        and (ch in " \t\n" or ch in _JOINERS or unicodedata.category(ch)[0] != "C")
    )
    # A joiner only means something between two characters: runs collapse to one,
    # and one left at either end (or beside a space) goes.
    text = _JOINER_RUN.sub(lambda m: m.group(0)[-1], text)
    text = _LOOSE_JOINER.sub("", text)
    text = _SPACES.sub(" ", text).strip()
    if len(text) > LOCATION_MAX:
        raise _bad_request(
            f"A location has at most {LOCATION_MAX} characters.", "location_too_long"
        )
    return text


def check_feeling(value: str | None) -> str:
    key = (value or "").strip()
    if key and key not in FEELINGS:
        raise _bad_request("Unknown feeling or activity.", "invalid_feeling")
    return key


def check_publish_at(value, *, now=None):
    """In the future, and no more than 75 days ahead."""
    now = now or timezone.now()
    if value is None:
        raise _bad_request("publish_at is required.")
    if value <= now:
        raise _bad_request("publish_at must be in the future.", "publish_at_past")
    if value > now + MAX_SCHEDULE_AHEAD:
        raise _bad_request("publish_at is more than 75 days ahead.", "publish_at_too_far")
    return value


# ---- the "who can tag me" setting ---------------------------------------------------


def get_settings(account_id: str) -> dict:
    row = PostSettings.objects.filter(account_id=account_id).first()
    return {"who_can_tag": row.who_can_tag if row else TagPolicy.FRIENDS}


def update_settings(account_id: str, *, who_can_tag: str) -> dict:
    if who_can_tag not in TagPolicy.values:
        raise _bad_request("Invalid tag setting.")
    PostSettings.objects.update_or_create(
        account_id=account_id, defaults={"who_can_tag": who_can_tag}
    )
    return get_settings(account_id)


def _tag_not_allowed() -> TaraAPIError:
    # One answer for a block either way, a "nobody" setting and a non-friend under
    # "friends", so a refusal never tells the author that someone blocked them.
    return _bad_request("You can't tag this person.", "tag_not_allowed")


def check_tags(author_id: str, tagged_ids, *, already=()) -> list[str]:
    """The accounts to tag, de-duplicated and in order, without the author.

    Accounts already tagged on the post (``already``) are kept without a new
    check. Each new one must not be blocked either way, and must allow it:
    ``nobody`` never, ``friends`` (the default) only the author's friends,
    ``everyone`` anyone. Graph down means "not friends" (fail closed). A remote
    read, so callers run it before their write transaction.
    """
    from . import services

    author = str(author_id)
    ids = [i for i in dict.fromkeys(str(t) for t in tagged_ids or []) if i != author]
    if len(ids) > MAX_TAGS:
        raise _bad_request(f"A post can tag at most {MAX_TAGS} people.", "too_many_tags")
    kept = {str(a) for a in already}
    blocked = services.blocked_ids(author)
    # A tag kept from before goes, silently, once either side blocked the other.
    ids = [i for i in ids if i not in kept or i not in blocked]
    new = [i for i in ids if i not in kept]
    if not new:
        return ids
    policies = dict(
        PostSettings.objects.filter(account_id__in=new).values_list("account_id", "who_can_tag")
    )
    policies = {str(k): v for k, v in policies.items()}
    for account in new:
        policy = policies.get(account, TagPolicy.FRIENDS)
        if account in blocked or policy == TagPolicy.NOBODY:
            raise _tag_not_allowed()
        rel = services.get_relationship(author, account)
        if rel.blocked_either_way or (policy == TagPolicy.FRIENDS and not rel.are_friends):
            raise _tag_not_allowed()
    return ids


def set_tags(post: Post, ids: list[str]) -> list[str]:
    """Make the post's tags exactly ``ids``; returns the ones added. Call inside
    the write transaction, after ``check_tags``."""
    before = {str(a) for a in post.tags.values_list("account_id", flat=True)}
    wanted = set(ids)
    PostTag.objects.filter(post=post).exclude(account_id__in=wanted).delete()
    added = [i for i in ids if i not in before]
    PostTag.objects.bulk_create(
        [PostTag(post=post, account_id=a) for a in added], ignore_conflicts=True
    )
    return added


def tagged_ids_of(post: Post) -> list[str]:
    return [str(t.account_id) for t in post.tags.all()]


def remove_my_tag(viewer_id: str, post_id: str) -> None:
    """The tagged person takes their tag off a post, always: also after they
    blocked the author or lost the post's audience, and on a draft or scheduled
    post (being tagged, they already know it exists). Someone not tagged gets
    204 on a post they can see and 404 otherwise, as before."""
    from . import services

    deleted, _ = PostTag.objects.filter(post_id=post_id, account_id=viewer_id).delete()
    if not deleted:
        services._require_visible(viewer_id, post_id)


def drop_tags_between(a: str, b: str) -> int:
    """Remove the tags of either account on the other's posts (on a block)."""
    deleted, _ = PostTag.objects.filter(
        Q(post__author_id=a, account_id=b) | Q(post__author_id=b, account_id=a)
    ).delete()
    return deleted


def notify_tags(*, actor_id: str, post_id: str, account_ids: list[str]) -> int:
    """Run by post's consumer of its own ``post.created`` / ``post.updated``, after
    that commit: ``post.tagged`` for each tagged person who can open the post,
    who is not blocked either way, and who is still tagged. A group post waiting
    for approval tells nobody yet: its ``post.approved`` does, once."""
    from . import services

    if not settings.POST_EMIT_TAG_EVENTS:
        return 0
    post = Post.objects.filter(id=post_id).first()
    if post is None or not post.is_visible or not account_ids:
        return 0
    if post.approval_state == ApprovalState.PENDING:
        return 0
    still = {str(a) for a in post.tags.values_list("account_id", flat=True)}
    sent = 0
    for account in list(dict.fromkeys(str(a) for a in account_ids))[:MAX_TAG_NOTIFICATIONS]:
        if account == str(actor_id) or account not in still:
            continue
        if services._is_locally_blocked(actor_id, account):
            continue
        if not services.visible_to_viewer(account, post):
            continue
        with transaction.atomic():
            events.emit(
                "post.tagged",
                subject_id=str(post.id),
                payload={
                    "post_id": str(post.id),
                    "author_id": str(actor_id),
                    "recipient": account,
                },
                actor_id=str(actor_id),
                partition_key=f"post:{post.id}",
            )
        sent += 1
    return sent


# ---- drafts and scheduled posts -----------------------------------------------------

UNPUBLISHED = (PostState.DRAFT, PostState.SCHEDULED)


def live_for_author(viewer_id: str, post: Post) -> bool:
    """The author's own draft or scheduled post, not deleted or removed. Only for
    media's internal visibility check; the public API keeps answering 404."""
    return (
        str(post.author_id) == str(viewer_id)
        and post.state in UNPUBLISHED
        and post.deleted_at is None
        and post.moderation_status != Post.ModerationStatus.REMOVED
    )


def drafts_queryset(author_id: str, state: str | None = None):
    """The author's drafts and scheduled posts, last changed first."""
    from . import services

    if state and state not in UNPUBLISHED:
        raise _bad_request("state must be draft or scheduled.")
    qs = Post.objects.filter(author_id=author_id, deleted_at__isnull=True, state__in=UNPUBLISHED)
    if state:
        qs = qs.filter(state=state)
    return services.with_detail(qs.order_by("-updated_at", "-id"))


def get_draft(author_id: str, post_id: str, *, lock: bool = False) -> Post:
    """The author's own draft or scheduled post; anyone else (and a published
    post) gets 404."""
    qs = Post.objects.filter(
        id=post_id,
        author_id=author_id,
        deleted_at__isnull=True,
        state__in=UNPUBLISHED,
        moderation_status=Post.ModerationStatus.OK,
    )
    post = (qs.select_for_update() if lock else qs).first()
    if post is None:
        raise _not_found()
    return post


def delete_draft(author_id: str, post_id: str) -> None:
    """Never published, so nobody else heard of it: no event. Its media stay
    restricted to the author."""
    with transaction.atomic():
        post = get_draft(author_id, post_id, lock=True)
        post.deleted_at = timezone.now()
        post.save(update_fields=["deleted_at", "updated_at"])


def _publish_locked(post: Post, now) -> None:
    """Publish a locked draft or scheduled post, inside the caller's transaction:
    ``created_at`` becomes now (a poll's duration starts then too), and the
    normal ``post.created`` is emitted."""
    from . import services

    poll = getattr(post, "poll", None) if post.type == Post.Type.POLL else None
    if poll is not None and poll.closes_at:
        poll.closes_at = poll.closes_at + (now - post.created_at)
        poll.save(update_fields=["closes_at"])
    Post.objects.filter(id=post.id).update(
        state=PostState.PUBLISHED, publish_at=None, created_at=now, updated_at=now
    )
    post.state, post.publish_at, post.created_at = PostState.PUBLISHED, None, now
    services.emit_created(post)
    if post.audience == Audience.PUBLIC:
        transaction.on_commit(lambda: _open_media(post))


def _open_media(post: Post) -> None:
    """A draft's media were bound restricted; once it is public they need not be.
    Best effort after the commit: restricted media follow the post's visibility,
    so if media is down they are still shown to everyone who can see the post."""
    media_ids = [str(m) for m in post.media.values_list("media_id", flat=True)]
    if not media_ids:
        return
    try:
        media_client.bind(str(post.author_id), str(post.id), media_ids, restricted=False)
    except Exception:  # noqa: BLE001 - never undo a publication over media
        logger.warning("could not lift the restriction on a published draft's media", exc_info=True)


def publish_draft(author_id: str, post_id: str) -> Post:
    """The author publishes a draft or a scheduled post now."""
    from . import services

    with transaction.atomic():
        post = get_draft(author_id, post_id, lock=True)  # the beat task won: 404
        _publish_locked(post, timezone.now())
    return services.with_detail(Post.objects.filter(id=post.id)).get()


def publish_due(*, now=None, batch: int = PUBLISH_BATCH) -> int:
    """Publish the scheduled posts whose time has come (the beat task, every
    minute, and once when a worker starts, for posts whose time passed while
    nothing ran). Rows are taken with ``SKIP LOCKED`` and their state changes in
    the same transaction, so two workers never publish the same post twice."""
    now = now or timezone.now()
    published = 0
    while True:
        with transaction.atomic():
            rows = list(
                Post.objects.select_for_update(skip_locked=True, of=("self",))
                .select_related("poll")
                .filter(
                    state=PostState.SCHEDULED,
                    publish_at__lte=now,
                    deleted_at__isnull=True,
                    moderation_status=Post.ModerationStatus.OK,
                )
                .order_by("publish_at", "id")[:batch]
            )
            for post in rows:
                _publish_locked(post, now)
        published += len(rows)
        if len(rows) < batch:
            return published


# ---- top comments ---------------------------------------------------------------------


def top_comments(post_ids: list, blocked: set[str]) -> dict:
    """``{post_id: [comment, ...]}``: up to two live thread roots per post, most
    reacted first, never by anyone blocked either way with the viewer. One query
    for the whole list (a window function), however many posts."""
    if not post_ids:
        return {}
    rows = (
        Comment.objects.filter(post_id__in=post_ids, parent__isnull=True, deleted_at__isnull=True)
        .exclude(moderation_status=Comment.ModerationStatus.REMOVED)
        .exclude(author_id__in=list(blocked))
        .annotate(
            rank=Window(
                RowNumber(),
                partition_by=[F("post_id")],
                order_by=[F("reaction_count").desc(), F("created_at").asc(), F("id").asc()],
            )
        )
        .filter(rank__lte=TOP_COMMENTS)
        .order_by("post_id", "rank")
    )
    out: dict = {}
    for comment in rows:
        out.setdefault(comment.post_id, []).append(comment)
    return out


def drafts_filter() -> Q:
    """Published posts only (for querysets that page in SQL before filtering)."""
    return Q(state=PostState.PUBLISHED)
