from __future__ import annotations

from rest_framework import serializers

from .models import MediaAsset


class SignUploadSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=MediaAsset.Kind.values)
    mime = serializers.CharField(max_length=120)
    size = serializers.IntegerField(min_value=1)
    visibility = serializers.ChoiceField(
        choices=MediaAsset.Visibility.values, default=MediaAsset.Visibility.PUBLIC
    )
    # A video for a post is transcoded to HLS (5.2); empty: served as uploaded (chat).
    purpose = serializers.ChoiceField(
        choices=MediaAsset.Purpose.values, default="", allow_blank=True, required=False
    )


# One call per page render; the client coalesces its lookups into batches of this size.
MAX_BATCH_IDS = 100


class ResolveSerializer(serializers.Serializer):
    ids = serializers.ListField(
        child=serializers.UUIDField(), allow_empty=True, max_length=MAX_BATCH_IDS
    )
