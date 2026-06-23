"""Feed fan-out-on-write + read.

On `post.created`, resolve the author's audience from Graph and write a FeedItem
(with a denormalized snapshot) into each recipient's feed. High-follower accounts
are capped (FANOUT_MAX_RECIPIENTS) — a real system switches those to
fan-out-on-read (Phase 9); we log what was dropped rather than silently truncate.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from . import events
from .clients import fanout_audience
from .models import FeedItem

logger = logging.getLogger("tara.feed.services")


def _snapshot(payload: dict) -> dict:
    return {
        "post_id": payload["post_id"],
        "author_id": payload["author_id"],
        "author_type": payload.get("author_type", "user"),
        "type": payload.get("type", "text"),
        "excerpt": payload.get("excerpt", ""),
        "media_ids": payload.get("media_ids", []),
        "created_at": payload.get("created_at"),
    }


def fan_out_post(payload: dict) -> int:
    """Distribute a created post to recipient feeds. Returns count of new items."""
    author_id = payload["author_id"]
    post_id = payload["post_id"]
    audience = payload.get("audience", "public")
    created_at = parse_datetime(payload.get("created_at") or "") or timezone.now()

    if audience == "only_me":
        recipients = {author_id}
    else:
        data = fanout_audience(author_id)  # raises GraphUnavailable -> consumer retries
        followers = set(data.get("followers", []))
        friends = set(data.get("friends", []))
        if audience == "friends":
            recipients = friends
        elif audience == "followers":
            recipients = followers
        else:  # public
            recipients = followers | friends
        recipients.add(author_id)  # authors see their own posts

    recipients = list(recipients)
    if len(recipients) > settings.FANOUT_MAX_RECIPIENTS:
        logger.warning(
            "fan-out capped",
            extra={
                "post_id": post_id,
                "total": len(recipients),
                "cap": settings.FANOUT_MAX_RECIPIENTS,
            },
        )
        recipients = recipients[: settings.FANOUT_MAX_RECIPIENTS]

    existing = {
        str(r)
        for r in FeedItem.objects.filter(post_id=post_id, recipient_id__in=recipients).values_list(
            "recipient_id", flat=True
        )
    }
    snapshot = _snapshot(payload)
    new_recipients = [r for r in recipients if str(r) not in existing]
    if not new_recipients:
        return 0

    with transaction.atomic():
        FeedItem.objects.bulk_create(
            [
                FeedItem(
                    recipient_id=r,
                    post_id=post_id,
                    author_id=author_id,
                    reason="self" if str(r) == str(author_id) else "follow",
                    snapshot=snapshot,
                    post_created_at=created_at,
                )
                for r in new_recipients
            ],
            ignore_conflicts=True,
        )
        for r in new_recipients:
            events.emit(
                "feed.item.added",
                subject_id=str(post_id),
                payload={"recipient": str(r), "post_id": str(post_id), "author_id": str(author_id)},
                partition_key=f"recipient:{r}",
            )
    return len(new_recipients)


def remove_author_from_recipient(recipient_id: str, author_id: str) -> None:
    FeedItem.objects.filter(recipient_id=recipient_id, author_id=author_id).delete()


def home_feed(recipient_id: str):
    return FeedItem.objects.filter(recipient_id=recipient_id).order_by("-post_created_at")
