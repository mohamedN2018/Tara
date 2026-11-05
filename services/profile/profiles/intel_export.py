"""Feed's Tara Intelligence backfill (WP 3.2), under ``/internal/v1/intel/export/``.

Feed keeps ``intel_group_ref``, ``intel_group_membership`` and ``intel_page_ref``
from the ``group.*`` and ``page.*`` events; these exports rebuild them. Unlike
search's exports they include hidden, suspended and deleted groups and draft,
suspended and deleted pages, because feed must know what is *not* visible (its
eligibility rules fail closed on an unknown group or page). No group name, handle
or description, and no page text: ids, enums, counts and times only. Never routed
by the edge; an internal token for ``profile-internal`` is required.

- ``groups/``: ``{group_id, privacy, status, category, member_count}``;
- ``group-members/``: ``{group_id, account_id, role, state, notify_posts, joined_at}``
  (one row per relation: no row means no relation);
- ``pages/``: ``{owner, status, deleted}`` keyed by the page id.
"""

from __future__ import annotations

from django.urls import path

from tara_common.search_export import SearchExportView

from .models import Page


def _groups():
    from groups.models import Group

    return Group.objects.all()


def _group(group) -> tuple:
    return group.id, {
        "group_id": str(group.id),
        "privacy": group.privacy,
        "status": "deleted" if group.deleted_at else group.status,
        "category": group.category,
        "member_count": group.member_count,
    }


def _members():
    from groups.models import GroupMember

    return GroupMember.objects.all()


def _member(m) -> tuple:
    return m.id, {
        "group_id": str(m.group_id),
        "account_id": str(m.account_id),
        "role": m.role,
        "state": m.state,
        "notify_posts": m.notify_posts,
        "joined_at": m.joined_at.isoformat() if m.joined_at else None,
    }


def _page(page: Page) -> tuple:
    return page.id, {
        "owner": str(page.owner_account_id),
        "status": page.status,
        "deleted": page.deleted_at is not None,
    }


urlpatterns = [
    path(
        "export/groups/",
        SearchExportView.as_view(source=_groups, to_item=_group),
        name="intel-export-groups",
    ),
    path(
        "export/group-members/",
        SearchExportView.as_view(source=_members, to_item=_member),
        name="intel-export-group-members",
    ),
    path(
        "export/pages/",
        SearchExportView.as_view(source=Page.objects.all, to_item=_page),
        name="intel-export-pages",
    ),
]
