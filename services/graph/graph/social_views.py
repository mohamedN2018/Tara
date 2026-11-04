"""Relationship privacy, counts, suggestions, mute, restrict and favorites
(roadmap 1.6, plan 08 track 2D). Everything here lives under ``/api/v1/social/``,
which the edge already routes to graph.

Every endpoint that is not about another account's lists is owner-only: it acts
on the signed-in account and never takes an owner id.
"""

from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tara_common.responses import data_response

from . import preferences, services, suggestions
from .serializers import DismissSerializer, RelationshipSettingsSerializer


def _me(request: Request) -> str:
    return str(request.user.account_id)


class RelationshipSettingsView(APIView):
    """``GET``/``PATCH`` the signed-in account's list and request privacy."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: RelationshipSettingsSerializer}, tags=["social"])
    def get(self, request: Request) -> Response:
        row = services.relationship_settings(_me(request))
        return data_response(RelationshipSettingsSerializer(row).data)

    @extend_schema(
        request=RelationshipSettingsSerializer,
        responses={200: RelationshipSettingsSerializer},
        tags=["social"],
    )
    def patch(self, request: Request) -> Response:
        serializer = RelationshipSettingsSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        row = services.update_relationship_settings(_me(request), serializer.validated_data)
        return data_response(RelationshipSettingsSerializer(row).data)


class SocialFollowingView(APIView):
    """What another account follows, gated by its ``follow_lists_visibility``."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: None, 404: None}, tags=["social"])
    def get(self, request: Request, user_id: str) -> Response:
        me = _me(request)
        services.ensure_lists_visible(me, user_id, "follows")
        rows = services.following(user_id, viewer_id=me)
        return data_response(
            {
                "following": [
                    {"target_id": str(r.target_id), "target_type": r.target_type} for r in rows
                ]
            }
        )


class SocialCountsView(APIView):
    """Friends, followers and following counts, gated by ``counts_visibility``.
    The mutual count is included only while the friend list is visible."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: None, 404: None}, tags=["social"])
    def get(self, request: Request, user_id: str) -> Response:
        me, owner = _me(request), str(user_id)
        services.ensure_lists_visible(me, owner, "counts")
        body = services.relationship_counts(owner, viewer_id=me)
        mutual = None
        if me != owner and owner in services.lists_visible_to(me, [owner]):
            mutual = len(services.mutual_friends(me, owner))
        body["mutual_count"] = mutual
        return data_response(body)


class PeopleSuggestionsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: None}, tags=["suggestions"])
    def get(self, request: Request) -> Response:
        limit = suggestions._limit(request.query_params.get("limit"), 10)
        return data_response({"results": suggestions.people(_me(request), limit)})


class PageSuggestionsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: None}, tags=["suggestions"])
    def get(self, request: Request) -> Response:
        limit = suggestions._limit(request.query_params.get("limit"), 5)
        return data_response({"results": suggestions.pages(_me(request), limit)})


class DismissSuggestionView(APIView):
    """``POST`` hides a person (default) or a page from the viewer's suggestions;
    ``DELETE`` undoes it. ``target_type`` comes in the body or the query."""

    permission_classes = [IsAuthenticated]

    def _target_type(self, request: Request) -> str:
        raw = request.data if isinstance(request.data, dict) and request.data else None
        serializer = DismissSerializer(data=raw or request.query_params)
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data["target_type"]

    @extend_schema(request=DismissSerializer, responses={204: None}, tags=["suggestions"])
    def post(self, request: Request, target_id: str) -> Response:
        suggestions.dismiss(_me(request), str(target_id), self._target_type(request))
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(responses={204: None}, tags=["suggestions"])
    def delete(self, request: Request, target_id: str) -> Response:
        suggestions.undismiss(_me(request), str(target_id), self._target_type(request))
        return Response(status=status.HTTP_204_NO_CONTENT)


def _preference_views(kind: str, key: str) -> tuple[type[APIView], type[APIView]]:
    """List view and add/remove view for one owner-private preference."""

    class ListView(APIView):
        permission_classes = [IsAuthenticated]

        @extend_schema(responses={200: None}, tags=["preferences"], operation_id=f"{key}_list")
        def get(self, request: Request) -> Response:
            return data_response({key: preferences.target_ids(kind, _me(request))})

    class ItemView(APIView):
        permission_classes = [IsAuthenticated]

        @extend_schema(responses={204: None}, tags=["preferences"], operation_id=f"{key}_add")
        def post(self, request: Request, user_id: str) -> Response:
            preferences.add(kind, _me(request), str(user_id))
            return Response(status=status.HTTP_204_NO_CONTENT)

        @extend_schema(responses={204: None}, tags=["preferences"], operation_id=f"{key}_remove")
        def delete(self, request: Request, user_id: str) -> Response:
            preferences.remove(kind, _me(request), str(user_id))
            return Response(status=status.HTTP_204_NO_CONTENT)

    ListView.__name__ = f"{key.title()}ListView"
    ItemView.__name__ = f"{key.title()}ItemView"
    return ListView, ItemView


MutesView, MuteView = _preference_views("mute", "muted")
RestrictsView, RestrictView = _preference_views("restrict", "restricted")
FavoritesView, FavoriteView = _preference_views("favorite", "favorites")
