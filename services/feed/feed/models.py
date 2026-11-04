"""Feed domain models (owns `feed_db`). All rows are DERIVED and rebuildable.

Each FeedItem carries a denormalized post snapshot so the feed read path never
needs a synchronous call to the Post service — the feed stays readable even if
Post is down (graceful degradation, doc 02 §5). Only public posts and the
author's own item keep content (excerpt, media ids) in the snapshot; every other
item holds ids and enums, and the client hydrates it through `/posts/batch/`,
which re-checks visibility (`services.snapshot_for`).
"""

from __future__ import annotations

from django.db import models

from tara_events.envelope import uuid7
from tara_events.models import AbstractOutboxEvent, AbstractProcessedEvent


class FeedItem(models.Model):
    class Reason(models.TextChoices):
        """Why the item reached the recipient. Unfollow removes only FOLLOW items."""

        SELF = "self", "Own post"
        FRIEND = "friend", "Friend of the author"
        FOLLOW = "follow", "Follows the author"

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    recipient_id = models.UUIDField()
    post_id = models.UUIDField()
    author_id = models.UUIDField()
    score = models.FloatField(default=0.0)  # ranking signal (chronological default)
    reason = models.CharField(max_length=40, choices=Reason.choices, default=Reason.FOLLOW)
    snapshot = models.JSONField(default=dict)  # denormalized post data for rendering
    post_created_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "feed_item"
        constraints = [
            models.UniqueConstraint(fields=["recipient_id", "post_id"], name="feed_item_uniq"),
        ]
        indexes = [
            models.Index(fields=["recipient_id", "-post_created_at"], name="feed_recipient_idx"),
            # Every per-post write (score refresh, edit, delete) filters on post_id alone.
            models.Index(fields=["post_id"], name="feed_item_post_idx"),
        ]


class PostState(models.Model):
    """The newest edit or delete applied per post, kept after the delete (a tombstone).

    Retries reorder events. A ``post.created`` retried after the post was deleted
    fans out nothing, one retried after an edit fans out the edited audience and
    excerpt, and an edit older than the stored one is ignored.

    ``hidden`` (``post.hidden`` / ``post.unhidden``, the author's account
    deactivated and reactivated, 3C): the post's rows stay but no feed shows
    them. Ordered by its own ``hidden_at``, so an edit cannot make a hide or an
    unhide look stale.
    """

    post_id = models.UUIDField(primary_key=True)
    occurred_at = models.DateTimeField()
    deleted = models.BooleanField(default=False)
    audience = models.CharField(max_length=16, blank=True, default="")
    excerpt = models.TextField(blank=True, default="")
    hidden = models.BooleanField(default=False)
    hidden_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "post_state"
        indexes = [
            models.Index(
                fields=["post_id"], condition=models.Q(hidden=True), name="post_state_hidden_idx"
            ),
        ]


class PostHide(models.Model):
    """A post the viewer hid from their own feed, and why (2A). Undo deletes the row.

    ``spam`` and ``sexual`` are also kept as moderation signals: moderation has no
    internal intake for them yet (it ingests only ``*.reported`` events from the
    owning services), so they stay here and count in ``PostStats.flags``.
    """

    class Reason(models.TextChoices):
        NOT_INTERESTED = "not_interested", "Not interested"
        SPAM = "spam", "Spam"
        SEXUAL = "sexual", "Sexual content"
        ANNOYING = "annoying", "Annoying"
        DISLIKE_CREATOR = "dislike_creator", "Does not like the creator"
        OTHER = "other", "Other"

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    account_id = models.UUIDField()
    post_id = models.UUIDField()
    author_id = models.UUIDField()
    reason = models.CharField(max_length=20, choices=Reason.choices)
    hidden_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "post_hide"
        constraints = [
            models.UniqueConstraint(fields=["account_id", "post_id"], name="post_hide_uniq"),
        ]
        indexes = [
            models.Index(fields=["account_id", "author_id"], name="post_hide_author_idx"),
            models.Index(fields=["reason", "post_id"], name="post_hide_reason_idx"),
        ]


class AuthorSnooze(models.Model):
    """The viewer keeps an author out of their feed until ``until`` (30 days)."""

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    account_id = models.UUIDField()
    author_id = models.UUIDField()
    until = models.DateTimeField()
    snoozed_at = models.DateTimeField()

    class Meta:
        db_table = "author_snooze"
        constraints = [
            models.UniqueConstraint(fields=["account_id", "author_id"], name="author_snooze_uniq"),
        ]
        indexes = [models.Index(fields=["account_id", "until"], name="author_snooze_until_idx")]


class RelationshipFlag(models.Model):
    """Graph's mute and favorite edges (``relationship.*`` events), newest event wins."""

    class Kind(models.TextChoices):
        MUTE = "mute", "Muted"
        FAVORITE = "favorite", "Favorite"

    id = models.BigAutoField(primary_key=True)
    actor_id = models.UUIDField()
    target_id = models.UUIDField()
    kind = models.CharField(max_length=10, choices=Kind.choices)
    active = models.BooleanField(default=True)
    occurred_at = models.DateTimeField()

    class Meta:
        db_table = "relationship_flag"
        constraints = [
            models.UniqueConstraint(
                fields=["actor_id", "target_id", "kind"], name="relationship_flag_uniq"
            ),
        ]
        indexes = [models.Index(fields=["actor_id", "kind", "active"], name="rel_flag_actor_idx")]


class FollowEdge(models.Model):
    """Who the viewer follows (``user.followed`` / ``user.unfollowed``), newest event wins.

    Built from events, so follows made before it existed are only known through the
    ``follow`` label of their feed rows; the ``following`` mode reads both.
    """

    id = models.BigAutoField(primary_key=True)
    follower_id = models.UUIDField()
    target_id = models.UUIDField()
    target_type = models.CharField(max_length=10, default="user")
    active = models.BooleanField(default=True)
    occurred_at = models.DateTimeField()

    class Meta:
        db_table = "follow_edge"
        constraints = [
            models.UniqueConstraint(fields=["follower_id", "target_id"], name="follow_edge_uniq"),
        ]
        indexes = [models.Index(fields=["follower_id", "active"], name="follow_edge_follower_idx")]


class PostStats(models.Model):
    """Engagement counted from post's events, the ranking's engagement signal."""

    post_id = models.UUIDField(primary_key=True)
    reactions = models.IntegerField(default=0)
    comments = models.IntegerField(default=0)
    shares = models.IntegerField(default=0)
    flags = models.IntegerField(default=0)  # spam / sexual hides
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "post_stats"


class Affinity(models.Model):
    """How often ``account_id`` reacted to, commented on or shared ``author_id``'s posts."""

    id = models.BigAutoField(primary_key=True)
    account_id = models.UUIDField()
    author_id = models.UUIDField()
    interactions = models.IntegerField(default=0)

    class Meta:
        db_table = "affinity"
        constraints = [
            models.UniqueConstraint(fields=["account_id", "author_id"], name="affinity_uniq"),
        ]


class ReactionState(models.Model):
    """Whether ``reactor_id`` currently reacts to ``post_id``, newest event wins.

    The counters move only when this flips, so an unreact handled before its
    (retried) react leaves ``PostStats.reactions`` and ``Affinity`` unchanged.
    """

    id = models.BigAutoField(primary_key=True)
    post_id = models.UUIDField()
    reactor_id = models.UUIDField()
    active = models.BooleanField(default=True)
    occurred_at = models.DateTimeField()

    class Meta:
        db_table = "reaction_state"
        constraints = [
            models.UniqueConstraint(fields=["post_id", "reactor_id"], name="reaction_state_uniq"),
        ]


class CommentState(models.Model):
    """Whether a comment is live (created or restored) or deleted, newest event wins.

    ``PostStats.comments`` moves only when this flips, so a redelivered or
    reordered ``comment.deleted`` / ``comment.restored`` counts once.
    """

    comment_id = models.UUIDField(primary_key=True)
    post_id = models.UUIDField()
    author_id = models.UUIDField(null=True, blank=True)
    post_author_id = models.UUIDField(null=True, blank=True)
    active = models.BooleanField(default=True)
    occurred_at = models.DateTimeField()

    class Meta:
        db_table = "comment_state"


class AuthorRef(models.Model):
    """An author's discoverability (``UserProfile.searchable`` via ``profile.updated``)."""

    account_id = models.UUIDField(primary_key=True)
    searchable = models.BooleanField(default=True)
    occurred_at = models.DateTimeField()

    class Meta:
        db_table = "author_ref"


class OutboxEvent(AbstractOutboxEvent):
    class Meta(AbstractOutboxEvent.Meta):
        abstract = False
        db_table = "outbox_event"


class ProcessedEvent(AbstractProcessedEvent):
    class Meta(AbstractProcessedEvent.Meta):
        abstract = False
        db_table = "processed_event"
