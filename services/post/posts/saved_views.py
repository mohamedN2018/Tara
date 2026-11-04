"""Saved collections HTTP API (track T4). Owner-only: another account's ids are 404."""

from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tara_common.responses import data_response

from . import saved
from .models import SavedCollection
from .serializers import SavedItemSerializer


def _me(request: Request) -> str:
    return request.user.account_id


class SavedCollectionSerializer(serializers.ModelSerializer):
    item_count = serializers.SerializerMethodField()

    class Meta:
        model = SavedCollection
        fields = ["id", "name", "is_default", "item_count", "created_at"]

    def get_item_count(self, obj: SavedCollection) -> int:
        return int(getattr(obj, "item_count", 0) or 0)


class CollectionNameSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200, allow_blank=True)


class MoveSerializer(serializers.Serializer):
    collection_id = serializers.UUIDField(allow_null=True)


class SavedCollectionsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: SavedCollectionSerializer(many=True)}, tags=["saved"])
    def get(self, request: Request) -> Response:
        """My collections: the default one first, then mine oldest first."""
        rows = saved.list_collections(_me(request))
        return data_response(SavedCollectionSerializer(rows, many=True).data)

    @extend_schema(
        request=CollectionNameSerializer,
        responses={201: SavedCollectionSerializer},
        tags=["saved"],
    )
    def post(self, request: Request) -> Response:
        body = CollectionNameSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        collection = saved.create_collection(_me(request), body.validated_data["name"])
        return data_response(
            SavedCollectionSerializer(collection).data, status=status.HTTP_201_CREATED
        )


class SavedCollectionDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=CollectionNameSerializer, responses={200: SavedCollectionSerializer}, tags=["saved"]
    )
    def patch(self, request: Request, collection_id) -> Response:
        body = CollectionNameSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        collection = saved.rename_collection(
            _me(request), collection_id, body.validated_data["name"]
        )
        return data_response(SavedCollectionSerializer(collection).data)

    @extend_schema(responses={204: None}, tags=["saved"])
    def delete(self, request: Request, collection_id) -> Response:
        """Its items move back to the default collection."""
        saved.delete_collection(_me(request), collection_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class SavedItemDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=MoveSerializer, responses={200: SavedItemSerializer}, tags=["saved"])
    def patch(self, request: Request, saved_id) -> Response:
        """Move a saved item to another of my collections (null: the default one)."""
        body = MoveSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        item = saved.move_saved_item(_me(request), saved_id, body.validated_data["collection_id"])
        return data_response(SavedItemSerializer(item).data)
