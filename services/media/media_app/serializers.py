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
