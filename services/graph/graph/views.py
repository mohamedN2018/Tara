"""Social Graph HTTP API: friends, follows, blocks, relationship lists."""

from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tara_common.responses import data_response

from . import services
from .serializers import (
    FollowCreateSerializer,
    FriendRequestCreateSerializer,
    FriendshipSerializer,
)


def _me(request: Request) -> str:
    return request.user.account_id


# ---- friends ----------------------------------------------------------------


class FriendRequestsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: FriendshipSerializer(many=True)}, tags=["friends"])
    def get(self, request: Request) -> Response:
        outgoing = request.query_params.get("direction") == "outgoing"
        rows = services.list_requests(_me(request), outgoing=outgoing)
        return data_response(FriendshipSerializer(rows, many=True).data)

    @extend_schema(
        request=FriendRequestCreateSerializer,
        responses={201: FriendshipSerializer},
        tags=["friends"],
    )
    def post(self, request: Request) -> Response:
        serializer = FriendRequestCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        friendship = services.send_friend_request(
            _me(request), str(serializer.validated_data["to_user_id"])
        )
        return data_response(FriendshipSerializer(friendship).data, status=status.HTTP_201_CREATED)


class FriendRequestAcceptView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: FriendshipSerializer}, tags=["friends"])
    def post(self, request: Request, request_id: str) -> Response:
        friendship = services.accept_friend_request(_me(request), request_id)
        return data_response(FriendshipSerializer(friendship).data)


class FriendRequestRejectView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={204: None}, tags=["friends"])
    def post(self, request: Request, request_id: str) -> Response:
        services.reject_or_cancel_request(_me(request), request_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class FriendListView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: None}, tags=["friends"])
    def get(self, request: Request) -> Response:
        return data_response({"friends": services.list_friend_ids(_me(request))})


class FriendDeleteView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={204: None}, tags=["friends"])
    def delete(self, request: Request, user_id: str) -> Response:
        services.unfriend(_me(request), user_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---- follows ----------------------------------------------------------------


class FollowView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=FollowCreateSerializer, responses={204: None}, tags=["follows"])
    def post(self, request: Request, user_id: str) -> Response:
        serializer = FollowCreateSerializer(data=request.data or {})
        serializer.is_valid(raise_exception=True)
        services.follow(_me(request), user_id, serializer.validated_data["target_type"])
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(responses={204: None}, tags=["follows"])
    def delete(self, request: Request, user_id: str) -> Response:
        target_type = request.query_params.get("target_type", "user")
        services.unfollow(_me(request), user_id, target_type)
        return Response(status=status.HTTP_204_NO_CONTENT)


class FollowersView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: None}, tags=["follows"])
    def get(self, request: Request) -> Response:
        return data_response({"followers": services.follower_ids(_me(request))})


class FollowingView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: None}, tags=["follows"])
    def get(self, request: Request) -> Response:
        rows = services.following(_me(request))
        return data_response(
            {
                "following": [
                    {"target_id": str(r.target_id), "target_type": r.target_type} for r in rows
                ]
            }
        )


# ---- blocks -----------------------------------------------------------------


class BlockView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={204: None}, tags=["blocks"])
    def post(self, request: Request, user_id: str) -> Response:
        services.block(_me(request), user_id)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(responses={204: None}, tags=["blocks"])
    def delete(self, request: Request, user_id: str) -> Response:
        services.unblock(_me(request), user_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class BlockListView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: None}, tags=["blocks"])
    def get(self, request: Request) -> Response:
        return data_response({"blocked": services.blocked_ids(_me(request))})


# ---- public relationship lists ----------------------------------------------


class SocialFriendsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request: Request, user_id: str) -> Response:
        return data_response({"friends": services.list_friend_ids(user_id)})


class SocialFollowersView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request: Request, user_id: str) -> Response:
        return data_response({"followers": services.follower_ids(user_id)})


class SocialMutualView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request: Request, user_id: str) -> Response:
        return data_response({"mutual": services.mutual_friends(_me(request), user_id)})
