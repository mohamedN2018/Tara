from __future__ import annotations

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from . import services
from .models import FeedItem


class FeedItemSerializer(serializers.ModelSerializer):
    # Public posts and the viewer's own posts carry the stored excerpt and media
    # ids; every other item carries ids and enums only (hydrate via /posts/batch/).
    snapshot = serializers.SerializerMethodField()

    class Meta:
        model = FeedItem
        fields = ["id", "post_id", "author_id", "reason", "score", "snapshot", "post_created_at"]

    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_snapshot(self, item: FeedItem) -> dict:
        return services.snapshot_for(item.snapshot, item.recipient_id, item.author_id)
