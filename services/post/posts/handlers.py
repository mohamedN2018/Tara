"""Event consumers for the Post service."""

from __future__ import annotations

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from tara_events import on_event
from tara_events.envelope import EventEnvelope

from . import composer, events, groups, services
from .models import (
    BlockedPair,
    Comment,
    CommentReaction,
    Mention,
    PollVote,
    Post,
    PostHashtag,
    PostReaction,
    PostReactionCount,
    PostSettings,
    PostState,
    PostTag,
    SavedCollection,
    SavedItem,
    Share,
)


@on_event("user.blocked")
def on_user_blocked(event: EventEnvelope) -> None:
    """A block is respected both ways on tags too: neither keeps a tag of the
    other on their posts (2C). Idempotent, one transaction."""
    p = event.payload
    with transaction.atomic():
        BlockedPair.objects.get_or_create(blocker_id=p["blocker_id"], blocked_id=p["blocked_id"])
        composer.drop_tags_between(p["blocker_id"], p["blocked_id"])


@on_event("user.unblocked")
def on_user_unblocked(event: EventEnvelope) -> None:
    p = event.payload
    BlockedPair.objects.filter(blocker_id=p["blocker_id"], blocked_id=p["blocked_id"]).delete()


@on_event("moderation.actioned")
def on_moderation_actioned(event: EventEnvelope) -> None:
    p = event.payload
    if p.get("target_type") == "post":
        services.apply_moderation(p["target_id"], p.get("action", ""))
    elif p.get("target_type") == "comment":
        services.apply_comment_moderation(p["target_id"], p.get("action", ""))
    elif p.get("target_type") == "gathering":
        from gatherings.services import apply_moderation as apply_gathering_moderation

        apply_gathering_moderation(p["target_id"], p.get("action", ""))
    elif p.get("target_type") == "story":
        from stories.services import apply_moderation as apply_story_moderation

        apply_story_moderation(p["target_id"], p.get("action", ""))


@on_event("post.deleted")  # also emitted when moderation removes a post
@on_event("post.hidden")  # the author's account was deactivated
def on_post_deleted_restrict_media(event: EventEnvelope) -> None:
    """Outside the delete's transaction, and retried while media is down."""
    services.restrict_media_of_hidden_post(event.payload["post_id"])


@on_event("post.created")
def on_post_created_preview(event: EventEnvelope) -> None:
    services.refresh_link_preview(event.payload["post_id"])


@on_event("post.updated")
def on_post_updated_preview(event: EventEnvelope) -> None:
    services.refresh_link_preview(event.payload["post_id"])


@on_event("post.created")
def on_post_created_mentions(event: EventEnvelope) -> None:
    p = event.payload
    services.notify_mentions(
        actor_id=p["author_id"], post_id=p["post_id"], handles=p.get("mentions", [])
    )


@on_event("post.updated")
def on_post_updated_mentions(event: EventEnvelope) -> None:
    p = event.payload
    services.notify_mentions(
        actor_id=p["author_id"], post_id=p["post_id"], handles=p.get("new_mentions", [])
    )


@on_event("post.created")
def on_post_created_tags(event: EventEnvelope) -> None:
    """People tagged in a post hear about it once it is published (2C)."""
    p = event.payload
    composer.notify_tags(
        actor_id=p["author_id"], post_id=p["post_id"], account_ids=p.get("tagged_ids") or []
    )


@on_event("post.approved")
def on_post_approved_tags(event: EventEnvelope) -> None:
    """A group post held for approval tells its tagged people when it goes out."""
    p = event.payload
    composer.notify_tags(
        actor_id=p["author_id"], post_id=p["post_id"], account_ids=p.get("tagged_ids") or []
    )


@on_event("post.updated")
def on_post_updated_tags(event: EventEnvelope) -> None:
    p = event.payload
    composer.notify_tags(
        actor_id=p["author_id"], post_id=p["post_id"], account_ids=p.get("new_tagged_ids") or []
    )


@on_event("post.commented")
@on_event("comment.replied")
def on_comment_mentions(event: EventEnvelope) -> None:
    p = event.payload
    services.notify_mentions(
        actor_id=p["author"],
        post_id=p["post_id"],
        handles=p.get("mentions", []),
        comment_id=p.get("comment_id"),
    )


@on_event("comment.edited")
def on_comment_edited_mentions(event: EventEnvelope) -> None:
    p = event.payload
    services.notify_mentions(
        actor_id=p["author"],
        post_id=p["post_id"],
        handles=p.get("new_mentions", []),
        comment_id=p.get("comment_id"),
    )


# ---- group read model (profile's group.* events, roadmap 1.11) ----------------------


@on_event("group.created")
@on_event("group.updated")
@on_event("group.deleted")  # also a moderator's removal (status "suspended")
def on_group_changed(event: EventEnvelope) -> None:
    payload = dict(event.payload)
    if event.event_type == "group.deleted" and payload.get("status") == "active":
        payload["status"] = "deleted"  # an older producer without a status
    groups.apply_group_event(payload, event.occurred_at)


@on_event("group.member.changed")
def on_group_member_changed(event: EventEnvelope) -> None:
    groups.apply_member_event(event.payload, event.occurred_at)


# ---- account lifecycle (identity, plan 08 3C) ------------------------------------------
# Deactivation (and a deletion's 30-day grace) hides the account's own posts
# from everyone: its published user posts move to ``HELD``, a state no read
# path shows (``Post.is_visible`` needs ``published``; drafts, scheduling and
# studio list only their own states). Each one that was visible emits
# ``post.hidden``: feed keeps its rows but stops showing them, search drops
# the post, post restricts its media; notifications about it are kept (they
# open a 404 meanwhile). Reactivation moves exactly the held posts back and
# emits ``post.unhidden`` (feed shows the rows again and fans the post out to
# anyone missing it) and then ``post.updated`` (search indexes it again), so
# it is the exact reverse. With ``POST_EMIT_HIDE_EVENTS`` off (an install
# whose feed does not consume the pair yet) deactivation emits ``post.deleted``
# instead, which feed and notification cannot undo. Not a ``PostState`` choice
# on purpose: no client or form can ever set it.
HELD = "held"


def _account(event: EventEnvelope) -> str:
    return str(event.payload.get("account_id") or event.subject_id)


def _visible_ids(qs) -> list:
    return list(
        qs.filter(deleted_at__isnull=True)
        .exclude(moderation_status=Post.ModerationStatus.REMOVED)
        .values_list("id", flat=True)
    )


@on_event("account.deactivated")
def on_account_deactivated(event: EventEnvelope) -> None:
    account_id = _account(event)
    with transaction.atomic():
        live = Post.objects.select_for_update().filter(
            author_id=account_id, author_type="user", state=PostState.PUBLISHED
        )
        shown = _visible_ids(live)
        live.update(state=HELD)
        hide = settings.POST_EMIT_HIDE_EVENTS
        for post_id in shown:
            events.emit(
                "post.hidden" if hide else "post.deleted",
                subject_id=str(post_id),
                payload=(
                    {
                        "post_id": str(post_id),
                        "author_id": account_id,
                        "reason": "account_deactivated",
                    }
                    if hide
                    else {"post_id": str(post_id)}
                ),
                actor_id=account_id,
            )


@on_event("account.reactivated")
def on_account_reactivated(event: EventEnvelope) -> None:
    account_id = _account(event)
    with transaction.atomic():
        held = Post.objects.select_for_update().filter(author_id=account_id, state=HELD)
        shown = _visible_ids(held)
        held.update(state=PostState.PUBLISHED)
        for post in Post.objects.filter(id__in=shown).prefetch_related("media"):
            if settings.POST_EMIT_HIDE_EVENTS:
                events.emit(
                    "post.unhidden",
                    subject_id=str(post.id),
                    payload=_unhidden_payload(post),
                    actor_id=account_id,
                )
            services._emit_updated(post, new_mentions=[])  # noqa: SLF001 - same service


def _unhidden_payload(post: Post) -> dict:
    """What feed needs to fan the post out again (``post.created``'s fan-out fields)."""
    return {
        "post_id": str(post.id),
        "author_id": str(post.author_id),
        "author_type": post.author_type,
        "type": post.type,
        "audience": post.audience,
        "excerpt": post.body[:280],
        "media_ids": [str(m.media_id) for m in post.media.all()],  # ordered by position
        "created_at": post.created_at.isoformat(),
        "group_id": str(post.group_id) if post.group_id else None,
        "reason": "account_reactivated",
    }


@on_event("account.deleted")
def on_account_deleted(event: EventEnvelope) -> None:
    """Erase what the account wrote and did in post, idempotently.

    - its user posts (any state): body, place, feeling and link preview wiped,
      hashtags, mentions and tags on them removed, soft-deleted; each one not
      already deleted emits ``post.deleted`` (feed, search, media restriction);
    - its comments: body wiped, soft-deleted (replies by others stay);
    - its reactions, poll votes, shares, saved items and collections, tags of
      it on others' posts and its post settings: deleted, with the post
      reaction and poll counters recomputed;
    - its stories: deleted with their views, reactions and reports.

    What remains: the bare post and comment rows (ids, dates, counters) as
    tombstones; post reports it filed (moderation evidence); event RSVPs and
    events it hosts (``gatherings``); posts it published as a page (the page's
    content); the media files themselves (media service).
    """
    account_id = _account(event)
    now = timezone.now()
    with transaction.atomic():
        posts = Post.objects.select_for_update().filter(author_id=account_id, author_type="user")
        live_ids = list(posts.filter(deleted_at__isnull=True).values_list("id", flat=True))
        PostHashtag.objects.filter(post__in=posts).delete()
        Mention.objects.filter(post__in=posts).delete()
        PostTag.objects.filter(post__in=posts).delete()
        posts.update(body="", location="", feeling="", link_preview=None)
        posts.filter(deleted_at__isnull=True).update(deleted_at=now)
        for post_id in live_ids:
            events.emit(
                "post.deleted",
                subject_id=str(post_id),
                payload={"post_id": str(post_id)},
                actor_id=None,
            )

        comments = Comment.objects.filter(author_id=account_id)
        Mention.objects.filter(comment__in=comments).delete()
        comments.update(body="")
        comments.filter(deleted_at__isnull=True).update(deleted_at=now)

        reacted = list(
            PostReaction.objects.filter(account_id=account_id).values_list("post_id", flat=True)
        )
        PostReaction.objects.filter(account_id=account_id).delete()
        for post_id in set(reacted):
            counts = dict(
                PostReaction.objects.filter(post_id=post_id)
                .values_list("type")
                .annotate(n=Count("id"))
                .values_list("type", "n")
            )
            PostReactionCount.objects.filter(post_id=post_id).exclude(
                type__in=list(counts)
            ).delete()
            for kind, n in counts.items():
                PostReactionCount.objects.update_or_create(
                    post_id=post_id, type=kind, defaults={"count": n}
                )
            Post.objects.filter(id=post_id).update(reaction_count=sum(counts.values()))

        comment_ids = set(
            CommentReaction.objects.filter(account_id=account_id).values_list(
                "comment_id", flat=True
            )
        )
        CommentReaction.objects.filter(account_id=account_id).delete()
        for comment_id in comment_ids:
            Comment.objects.filter(id=comment_id).update(
                reaction_count=CommentReaction.objects.filter(comment_id=comment_id).count()
            )

        votes = list(
            PollVote.objects.filter(account_id=account_id).values_list("option_id", flat=True)
        )
        PollVote.objects.filter(account_id=account_id).delete()
        from .models import PollOption

        for option_id in set(votes):
            PollOption.objects.filter(id=option_id).update(
                vote_count=PollVote.objects.filter(option_id=option_id).count()
            )

        Share.objects.filter(account_id=account_id).delete()
        PostTag.objects.filter(account_id=account_id).delete()
        SavedItem.objects.filter(owner_id=account_id).delete()
        SavedCollection.objects.filter(owner_id=account_id).delete()
        PostSettings.objects.filter(account_id=account_id).delete()
        BlockedPair.objects.filter(Q(blocker_id=account_id) | Q(blocked_id=account_id)).delete()

        from stories.models import Story

        Story.objects.filter(author_id=account_id).delete()


@on_event("feed.recommendations.reset")
def on_recommendations_reset(event: EventEnvelope) -> None:
    """Feed's "Reset recommendations" (Tara Intelligence WP 8.4-B2): keep the newest
    ``reset_at``, so the reels seen order ignores the views before it. Idempotent;
    an older redelivery never moves it back."""
    from django.utils.dateparse import parse_datetime
    from reels.models import ReelsReset

    p = event.payload
    account_id, reset_at = p.get("account_id"), parse_datetime(str(p.get("reset_at") or ""))
    if not account_id or reset_at is None:
        return
    with transaction.atomic():
        row, created = ReelsReset.objects.select_for_update().get_or_create(
            account_id=account_id, defaults={"reset_at": reset_at}
        )
        if not created and reset_at > row.reset_at:
            row.reset_at = reset_at
            row.save(update_fields=["reset_at", "updated_at"])


@on_event("intel.creator.hidden")
def on_creator_hidden(event: EventEnvelope) -> None:
    """ "Don't recommend this creator" and its undo for the reels for_you tab
    (Tara Intelligence WP 7.5-B2); the newest choice wins, redelivery is harmless."""
    import uuid

    from django.utils.dateparse import parse_datetime
    from reels.models import ReelsHiddenCreator

    p = event.payload
    try:
        account_id = uuid.UUID(str(p.get("account_id")))
        creator_id = uuid.UUID(str(p.get("creator_id")))
    except (TypeError, ValueError):
        return
    hidden, at = p.get("hidden"), parse_datetime(str(p.get("at") or ""))
    if not isinstance(hidden, bool) or at is None:
        return
    with transaction.atomic():
        row, created = ReelsHiddenCreator.objects.select_for_update().get_or_create(
            account_id=account_id,
            creator_id=creator_id,
            defaults={"hidden": hidden, "event_at": at},
        )
        if not created and at > row.event_at:
            row.hidden, row.event_at = hidden, at
            row.save(update_fields=["hidden", "event_at"])
