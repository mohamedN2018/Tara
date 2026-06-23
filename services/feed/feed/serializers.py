from __future__ import annotations

from rest_framework import serializers

from .models import FeedItem


class FeedItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = FeedItem
        fields = ["id", "post_id", "author_id", "reason", "score", "snapshot", "post_created_at"]
