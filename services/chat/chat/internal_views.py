"""Service-to-service API. Not routed by the gateway."""

from __future__ import annotations

import jwt
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tara_common.auth import verify_internal_token
from tara_common.exceptions import TaraAPIError
from tara_common.responses import data_response

from . import services


def _require_internal(request: Request) -> None:
    header = request.headers.get("Authorization", "")
    token = header.removeprefix("Bearer ").strip()
    try:
        verify_internal_token(token, expected_audience="chat-internal")
    except jwt.PyJWTError as exc:
        raise TaraAPIError(
            "Invalid internal token.", code="authentication_failed", http_status_code=401
        ) from exc


class MembershipView(APIView):
    """Realtime's subscribe check: true for an active member, false across a
    block in a two-person thread. Every caller is the same service, so the
    per-IP API throttle would refuse subscriptions under load."""

    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_classes: list = []

    def get(self, request: Request, conversation_id: str, account_id: str) -> Response:
        _require_internal(request)
        return data_response(
            {"is_member": services.may_subscribe(str(account_id), str(conversation_id))}
        )


class PresencePeersView(APIView):
    """Accounts allowed to see this account's presence, as far as chat knows
    (DM peers, never blocked pairs). Realtime adds friends from graph."""

    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_classes: list = []

    def get(self, request: Request, account_id: str) -> Response:
        _require_internal(request)
        return data_response({"peers": services.presence_peers(str(account_id))})
