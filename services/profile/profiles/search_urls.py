"""Search's backfill export (roadmap 1.15), under ``/internal/v1/search/export/``.

Only what search may index: public, live profiles; published, live pages; and
live public or private groups (never hidden ones), in the same payload shape as
``profile.updated``, ``page.updated`` and ``group.updated``.
"""

from django.urls import path

from tara_common.search_export import SearchExportView

from .models import Page, UserProfile, Visibility
from .services import page_search_payload, profile_search_payload


def _groups():
    from groups.models import Group, Privacy

    return Group.objects.filter(
        deleted_at__isnull=True,
        status=Group.Status.ACTIVE,
        privacy__in=[Privacy.PUBLIC, Privacy.PRIVATE],
    )


def _group_item(group):
    from groups.services import group_payload

    return group.id, group_payload(group)


urlpatterns = [
    path(
        "export/people/",
        SearchExportView.as_view(
            source=lambda: UserProfile.objects.filter(
                deleted_at__isnull=True, visibility=Visibility.PUBLIC
            ),
            to_item=lambda p: (p.account_id, profile_search_payload(p, changed=[])),
        ),
        name="search-export-people",
    ),
    path(
        "export/pages/",
        SearchExportView.as_view(
            source=lambda: Page.objects.filter(
                deleted_at__isnull=True, status=Page.Status.PUBLISHED
            ),
            to_item=lambda p: (p.id, page_search_payload(p)),
        ),
        name="search-export-pages",
    ),
    path(
        "export/groups/",
        SearchExportView.as_view(source=_groups, to_item=_group_item),
        name="search-export-groups",
    ),
]
