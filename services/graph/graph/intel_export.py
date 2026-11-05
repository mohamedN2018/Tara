"""Feed's Tara Intelligence backfill (WP 3.2), under ``/internal/v1/intel/export/``.

Feed builds ``intel_friend_edge``, ``follow_edge`` and ``intel_block_pair`` from the
graph events; these exports let it rebuild them after missed events (D6, the
``FollowEdge`` drift) in one paged scan per kind, instead of one ``fanout/`` call
per account. Ids and times only. Never routed by the edge; an internal token for
``graph-internal`` is required (``SearchExportView``).

- ``friendships/``: accepted friendships ``{a, b, accepted_at}`` (``a`` < ``b``);
- ``follows/``: ``{follower, target, target_type, created_at}`` (users and pages);
- ``blocks/``: ``{blocker_id, blocked_id, created_at}``.
"""

from __future__ import annotations

from django.urls import path

from tara_common.search_export import SearchExportView

from .models import BlockRelation, FollowRelation, Friendship


def _iso(value) -> str | None:
    return value.isoformat() if value else None


def _friendship(f: Friendship) -> tuple:
    return f.id, {
        "a": str(f.account_low_id),
        "b": str(f.account_high_id),
        "accepted_at": _iso(f.accepted_at or f.created_at),
    }


def _follow(f: FollowRelation) -> tuple:
    return f.id, {
        "follower": str(f.follower_id),
        "target": str(f.target_id),
        "target_type": f.target_type,
        "created_at": _iso(f.created_at),
    }


def _block(b: BlockRelation) -> tuple:
    return b.id, {
        "blocker_id": str(b.blocker_id),
        "blocked_id": str(b.blocked_id),
        "created_at": _iso(b.created_at),
    }


urlpatterns = [
    path(
        "export/friendships/",
        SearchExportView.as_view(
            source=lambda: Friendship.objects.filter(status=Friendship.Status.ACCEPTED),
            to_item=_friendship,
        ),
        name="intel-export-friendships",
    ),
    path(
        "export/follows/",
        SearchExportView.as_view(source=FollowRelation.objects.all, to_item=_follow),
        name="intel-export-follows",
    ),
    path(
        "export/blocks/",
        SearchExportView.as_view(source=BlockRelation.objects.all, to_item=_block),
        name="intel-export-blocks",
    ),
]
