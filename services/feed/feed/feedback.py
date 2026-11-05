"""Hide a post and snooze an author (2A): the viewer's own feedback on their feed.

A hide takes the post out of every mode and every page for that viewer, and its
reason feeds the ranking: ``dislike_creator`` and ``annoying`` push the author
down in the viewer's "for you" feed (``ranking.author_penalties``), ``spam`` and
``sexual`` also count against the post for everyone (``PostStats.flags``). A
snooze keeps an author out of the viewer's feed for ``feedback.snooze_days`` days
(home config, 30 in ``home@1``; Tara Intelligence WP 4.1).
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from tara_common.exceptions import TaraAPIError

from . import readmodels, tasks
from .models import AuthorSnooze, FeedItem, PostHide, PostState

FLAG_REASONS = frozenset({PostHide.Reason.SPAM, PostHide.Reason.SEXUAL})
AUTHOR_DOWNWEIGHT_REASONS = frozenset({PostHide.Reason.DISLIKE_CREATOR, PostHide.Reason.ANNOYING})


def _snooze_days() -> int:
    from intel import config

    return config.for_surface("home").get("feedback.snooze_days")


def _not_found() -> TaraAPIError:
    return TaraAPIError("Post not found.", code="not_found", http_status_code=404)


def _flag_delta(old: str | None, new: str | None) -> int:
    return int(new in FLAG_REASONS) - int(old in FLAG_REASONS)


def hide_post(viewer_id, post_id, reason: str) -> PostHide:
    """Hide ``post_id`` from ``viewer_id``'s feed. Idempotent; a new reason replaces the old.

    Only a post that reached the viewer's feed can be hidden; anything else is a
    404, so the endpoint tells nobody whether a post exists.
    """
    item = FeedItem.objects.filter(recipient_id=viewer_id, post_id=post_id).first()
    if item is None or PostState.objects.filter(post_id=post_id, hidden=True).exists():
        raise _not_found()  # a deactivated author's post is hidden: as if absent
    mine = PostHide.objects.select_for_update().filter(account_id=viewer_id, post_id=post_id)
    with transaction.atomic():
        hide = mine.first()
        if hide is None:
            try:
                with transaction.atomic():
                    hide = PostHide.objects.create(
                        account_id=viewer_id,
                        post_id=post_id,
                        author_id=item.author_id,
                        reason=reason,
                    )
                delta = _flag_delta(None, reason)
            except IntegrityError:  # a concurrent hide won: this one is a change
                hide = mine.get()
                delta = _flag_delta(hide.reason, reason)
                hide = _change_reason(hide, reason)
        else:
            delta = _flag_delta(hide.reason, reason)
            hide = _change_reason(hide, reason)
        if delta:
            _bump_flags(post_id, delta)
    return hide


def _change_reason(hide: PostHide, reason: str) -> PostHide:
    if hide.reason != reason:
        hide.reason = reason
        hide.save(update_fields=["reason"])
    return hide


def unhide_post(viewer_id, post_id) -> None:
    """Undo a hide. Always 204: it only removes the viewer's own row."""
    with transaction.atomic():
        hide = (
            PostHide.objects.select_for_update()
            .filter(account_id=viewer_id, post_id=post_id)
            .first()
        )
        if hide is None:
            return
        reason = hide.reason
        hide.delete()
        if reason in FLAG_REASONS:
            _bump_flags(post_id, -1)


def _bump_flags(post_id, delta: int) -> None:
    """Count the flag now; rewrite the post's feed rows' score after the commit, in
    the background, so the request never scans or locks every recipient's row."""
    readmodels.bump_stats(post_id, flags=delta, refresh=False)
    tasks.refresh_score_after_commit(post_id)


def snooze_author(viewer_id, author_id) -> AuthorSnooze:
    """Keep ``author_id`` out of the viewer's feed for 30 days; again restarts the 30 days."""
    if str(uuid.UUID(str(author_id))) == str(uuid.UUID(str(viewer_id))):
        raise TaraAPIError(
            "You cannot snooze yourself.", code="cannot_snooze_self", http_status_code=400
        )
    now = timezone.now()
    snooze, _ = AuthorSnooze.objects.update_or_create(
        account_id=viewer_id,
        author_id=author_id,
        defaults={"until": now + timedelta(days=_snooze_days()), "snoozed_at": now},
    )
    return snooze


def unsnooze_author(viewer_id, author_id) -> None:
    AuthorSnooze.objects.filter(account_id=viewer_id, author_id=author_id).delete()


def active_snoozes(viewer_id):
    return AuthorSnooze.objects.filter(account_id=viewer_id, until__gt=timezone.now())


def hidden_post_ids(viewer_id):
    return PostHide.objects.filter(account_id=viewer_id).values("post_id")


def snoozed_author_ids(viewer_id):
    return active_snoozes(viewer_id).values("author_id")
