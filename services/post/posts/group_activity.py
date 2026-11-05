"""When each group last had a post (plan 08, social shell): the groups rail's
"last active" line.

Only groups whose content the viewer may read are answered; any other id is
left out, so the answer never tells a hidden or forbidden group apart from a
missing one."""

from __future__ import annotations

import uuid

from django.db.models import Max

from tara_common.exceptions import TaraAPIError

from . import groups as group_rm
from .models import ApprovalState, Post, PostState

#: Group ids per request (the rail shows at most a dozen).
MAX_GROUP_IDS = 20


def parse_ids(raw: str) -> list[str]:
    """Comma-separated UUIDs, deduplicated in order; 400 on a bad or long list."""
    out: list[str] = []
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            value = str(uuid.UUID(part))
        except ValueError as exc:
            raise TaraAPIError(
                "ids must be group UUIDs.", code="validation_error", http_status_code=400
            ) from exc
        if value not in out:
            out.append(value)
    if len(out) > MAX_GROUP_IDS:
        raise TaraAPIError(
            f"At most {MAX_GROUP_IDS} groups at a time.",
            code="validation_error",
            http_status_code=400,
        )
    return out


def last_post_times(viewer_id: str, group_ids: list[str]) -> dict[str, str | None]:
    """``{group_id: ISO time of the newest published post or None}`` for the
    groups among ``group_ids`` whose content the viewer may read. The same posts
    as the group's discussion feed: published, approved, not removed, and not by
    anyone blocked either way with the viewer."""
    from .services import blocked_ids  # services imports a lot; keep this module light

    viewer_id = str(viewer_id)
    visible = [
        gid
        for gid in group_ids
        if group_rm.content_visible(viewer_id, group_rm.access(gid, viewer_id))
    ]
    if not visible:
        return {}
    rows = (
        Post.objects.filter(
            group_id__in=visible,
            deleted_at__isnull=True,
            state=PostState.PUBLISHED,
            approval_state=ApprovalState.APPROVED,
        )
        .exclude(moderation_status=Post.ModerationStatus.REMOVED)
        .exclude(author_id__in=list(blocked_ids(viewer_id)))
        .values("group_id")
        .annotate(last=Max("created_at"))
    )
    latest = {str(r["group_id"]): r["last"] for r in rows}
    return {gid: (latest[gid].isoformat() if latest.get(gid) else None) for gid in visible}
