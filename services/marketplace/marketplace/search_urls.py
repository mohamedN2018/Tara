"""Search's backfill export (roadmap 1.15), under ``/internal/v1/search/export/``.

Only active (available) listings, in the same payload shape as the ``listing.*``
events (``services.search_snapshot``).
"""

from django.urls import path

from tara_common.search_export import SearchExportView

from .models import Listing
from .services import search_snapshot

urlpatterns = [
    path(
        "export/listings/",
        SearchExportView.as_view(
            source=lambda: Listing.objects.filter(
                status=Listing.Status.ACTIVE, deleted_at__isnull=True
            ).select_related("category"),
            to_item=lambda listing: (listing.id, search_snapshot(listing)),
        ),
        name="search-export-listings",
    ),
]
