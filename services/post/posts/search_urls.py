"""Search's internal reads (roadmap 1.15), under ``/internal/v1/search/``.

- ``gatherings/<id>/``: one event's indexable state. The ``gathering.*``
  payloads carry ids, enums and times only (never the title or place), so
  search reads the text here when an event changes. ``indexable`` is true only
  for a live, scheduled, public event outside any group. ``updated_at`` orders
  the reads. 404 only when the event never existed.
- ``export/posts/`` and ``export/gatherings/``: the backfill, in the same shape
  as ``post.updated`` and the state above.
"""

from __future__ import annotations

import uuid

from django.db import transaction
from django.urls import path
from django.utils.decorators import method_decorator
from gatherings.models import Gathering
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tara_common.exceptions import TaraAPIError
from tara_common.responses import data_response
from tara_common.search_export import SearchExportView
from tara_common.stats import require_internal_token

from .models import Audience, Post
from .services import search_fields

MAX_DESCRIPTION = 300


def gathering_state(g: Gathering) -> dict:
    indexable = (
        g.is_visible
        and g.audience == Gathering.Audience.PUBLIC
        and g.group_id is None
        and g.status == Gathering.Status.SCHEDULED
    )
    state = {
        "gathering_id": str(g.id),
        "indexable": indexable,
        "updated_at": g.updated_at.isoformat(),
    }
    if indexable:  # the text only leaves post for an event anyone may see
        state.update(
            {
                "title": g.title,
                "description": g.description[:MAX_DESCRIPTION],
                "location_type": g.location_type,
                "location": g.location if g.location_type == Gathering.LocationType.PLACE else "",
                "starts_at": g.starts_at.isoformat(),
                "ends_at": g.ends_at.isoformat() if g.ends_at else None,
                "host_id": str(g.host_id),
                "cover_media_id": str(g.cover_media_id) if g.cover_media_id else None,
                "going_count": g.going_count,
                "interested_count": g.interested_count,
                "status": g.status,
            }
        )
    return state


@method_decorator(transaction.non_atomic_requests, name="dispatch")  # read-only
class GatheringSearchStateView(APIView):
    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_classes: list = []  # internal: no per-IP throttle (roadmap 3.3)

    def get(self, request: Request, gathering_id: uuid.UUID) -> Response:
        require_internal_token(request, "post-internal")
        g = Gathering.objects.filter(id=gathering_id).first()
        if g is None:
            raise TaraAPIError("Not found.", code="not_found", http_status_code=404)
        return data_response(gathering_state(g))


def _public_posts():
    return Post.objects.filter(
        deleted_at__isnull=True,
        moderation_status=Post.ModerationStatus.OK,
        audience=Audience.PUBLIC,
        group_id__isnull=True,
    ).prefetch_related("hashtags__hashtag", "media")


def _post_item(post: Post) -> tuple:
    return post.id, {
        "post_id": str(post.id),
        "author_id": str(post.author_id),
        "audience": post.audience,
        "excerpt": post.body[:280],
        "hashtags": sorted(h.hashtag.tag for h in post.hashtags.all()),
        **search_fields(post),
    }


def _public_gatherings():
    return Gathering.objects.filter(
        deleted_at__isnull=True,
        moderation_status=Gathering.ModerationStatus.OK,
        audience=Gathering.Audience.PUBLIC,
        status=Gathering.Status.SCHEDULED,
        group_id__isnull=True,
    )


urlpatterns = [
    path(
        "gatherings/<uuid:gathering_id>/",
        GatheringSearchStateView.as_view(),
        name="search-gathering-state",
    ),
    path(
        "export/posts/",
        SearchExportView.as_view(source=_public_posts, to_item=_post_item),
        name="search-export-posts",
    ),
    path(
        "export/gatherings/",
        SearchExportView.as_view(
            source=_public_gatherings, to_item=lambda g: (g.id, gathering_state(g))
        ),
        name="search-export-gatherings",
    ),
]
