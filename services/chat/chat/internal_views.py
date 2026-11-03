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

from .models import ConversationMember


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
    permission_classes = [AllowAny]
    authentication_classes: list = []

    def get(self, request: Request, conversation_id: str, account_id: str) -> Response:
        _require_internal(request)
        is_member = ConversationMember.objects.filter(
            conversation_id=conversation_id, account_id=account_id, left_at__isnull=True
        ).exists()
        return data_response({"is_member": is_member})
