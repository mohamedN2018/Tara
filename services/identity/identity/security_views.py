"""Account-security endpoints: sign-in providers, Google, change password and
email, and Telegram phone verification. Logic lives in account_security.py and
telegram.py; these views only validate input and shape responses."""

from __future__ import annotations

import hmac

from django.conf import settings
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tara_common.exceptions import TaraAPIError
from tara_common.responses import data_response

from . import account_security, telegram
from .google import google_enabled
from .serializers import (
    AccountSerializer,
    ChangeEmailSerializer,
    ChangePasswordSerializer,
    ConfirmEmailChangeSerializer,
    GoogleLinkSerializer,
    GoogleSignInSerializer,
    GoogleUnlinkSerializer,
    SecurityOverviewSerializer,
    TokenResponseSerializer,
)
from .views import NO_AUTH, _client_meta, _get_account, _set_refresh_cookie, _token_body


def _session_id(request: Request) -> str | None:
    return getattr(request.user, "claims", {}).get("sid")


class AuthProvidersView(APIView):
    """Which sign-in methods the SPA should offer. Public values only."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    @extend_schema(responses={200: OpenApiResponse(description="Enabled providers")}, tags=["auth"])
    def get(self, _request: Request) -> Response:
        google_on = google_enabled()
        telegram_on = telegram.telegram_enabled()
        return data_response(
            {
                "password": True,
                "google": {
                    "enabled": google_on,
                    "client_id": settings.GOOGLE_CLIENT_ID if google_on else "",
                },
                "telegram": {
                    "enabled": telegram_on,
                    "bot_username": settings.TELEGRAM_BOT_USERNAME if telegram_on else "",
                },
            }
        )


class GoogleSignInView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = NO_AUTH
    throttle_scope = "auth_login"

    @extend_schema(
        request=GoogleSignInSerializer, responses={200: TokenResponseSerializer}, tags=["auth"]
    )
    def post(self, request: Request) -> Response:
        serializer = GoogleSignInSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        meta = _client_meta(request)
        issued, created = account_security.google_sign_in(
            credential=data["credential"],
            language=data["language"],
            theme=data["theme"],
            ip_region=meta["ip_region"],
            user_agent=meta["user_agent"],
            correlation_id=meta["correlation_id"],
        )
        response = data_response(
            {**_token_body(issued), "created": created},
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )
        _set_refresh_cookie(response, issued.refresh_token)
        return response


class GoogleLinkView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_scope = "auth_password"

    @extend_schema(
        request=GoogleLinkSerializer, responses={200: SecurityOverviewSerializer}, tags=["account"]
    )
    def post(self, request: Request) -> Response:
        account = _get_account(request)
        serializer = GoogleLinkSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        account_security.link_google(
            account,
            credential=serializer.validated_data["credential"],
            password=serializer.validated_data.get("password", ""),
            ip_region=_client_meta(request)["ip_region"],
        )
        return data_response(account_security.security_overview(account))

    @extend_schema(
        request=GoogleUnlinkSerializer,
        responses={200: SecurityOverviewSerializer},
        tags=["account"],
    )
    def delete(self, request: Request) -> Response:
        account = _get_account(request)
        serializer = GoogleUnlinkSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        account_security.unlink_google(
            account,
            password=serializer.validated_data.get("password", ""),
            ip_region=_client_meta(request)["ip_region"],
        )
        return data_response(account_security.security_overview(account))


class SecurityOverviewView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: SecurityOverviewSerializer}, tags=["account"])
    def get(self, request: Request) -> Response:
        return data_response(account_security.security_overview(_get_account(request)))


class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_scope = "auth_password"

    @extend_schema(
        request=ChangePasswordSerializer,
        responses={200: OpenApiResponse(description="Changed; other sessions signed out.")},
        tags=["account"],
    )
    def post(self, request: Request) -> Response:
        account = _get_account(request)
        serializer = ChangePasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        revoked = account_security.change_password(
            account,
            current_password=serializer.validated_data["current_password"],
            new_password=serializer.validated_data["new_password"],
            current_session_id=_session_id(request),
            ip_region=_client_meta(request)["ip_region"],
        )
        return data_response({"detail": "Password changed.", "revoked_sessions": revoked})


class ChangeEmailView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_scope = "auth_password"

    @extend_schema(
        request=ChangeEmailSerializer,
        responses={202: OpenApiResponse(description="Confirmation link sent to the new address.")},
        tags=["account"],
    )
    def post(self, request: Request) -> Response:
        account = _get_account(request)
        serializer = ChangeEmailSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        record = account_security.request_email_change(
            account,
            new_email=serializer.validated_data["new_email"],
            password=serializer.validated_data["password"],
            ip_region=_client_meta(request)["ip_region"],
        )
        return data_response(
            {
                "detail": "Check the new address for a confirmation link.",
                "pending_email": record.new_email,
                "expires_at": record.expires_at.isoformat(),
            },
            status=status.HTTP_202_ACCEPTED,
        )

    @extend_schema(responses={204: None}, tags=["account"])
    def delete(self, request: Request) -> Response:
        account_security.cancel_email_change(_get_account(request))
        return Response(status=status.HTTP_204_NO_CONTENT)


class ConfirmEmailChangeView(APIView):
    """Opened from the link in the email: the token is the proof, no session needed."""

    permission_classes = [AllowAny]
    authentication_classes = NO_AUTH
    throttle_scope = "auth_password"

    @extend_schema(
        request=ConfirmEmailChangeSerializer, responses={200: AccountSerializer}, tags=["auth"]
    )
    def post(self, request: Request) -> Response:
        serializer = ConfirmEmailChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        account = account_security.confirm_email_change(
            raw_token=serializer.validated_data["token"],
            correlation_id=_client_meta(request)["correlation_id"],
        )
        return data_response(AccountSerializer(account).data)


class PhoneView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: SecurityOverviewSerializer}, tags=["account"])
    def delete(self, request: Request) -> Response:
        account = _get_account(request)
        telegram.remove_phone(account)
        return data_response(account_security.security_overview(account))


class TelegramPhoneStartView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_scope = "auth_password"

    @extend_schema(
        request=None,
        responses={200: OpenApiResponse(description="Bot deep link for phone verification")},
        tags=["account"],
    )
    def post(self, request: Request) -> Response:
        if not telegram.telegram_enabled():
            raise TaraAPIError(
                "Phone verification is not enabled.", code="not_found", http_status_code=404
            )
        account = _get_account(request)
        link, expires_in = telegram.start_phone_verification(account)
        return data_response(
            {
                "deep_link": link,
                "bot_username": settings.TELEGRAM_BOT_USERNAME,
                "expires_in": expires_in,
            }
        )


class TelegramWebhookView(APIView):
    """Telegram POSTs bot updates here. Answers 200 to any authentic update (so
    Telegram does not retry it); handling is best-effort and never raises."""

    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_classes: list = []

    @extend_schema(exclude=True)
    def post(self, request: Request) -> Response:
        if not telegram.telegram_enabled():
            raise TaraAPIError("Not found.", code="not_found", http_status_code=404)
        expected = settings.TELEGRAM_WEBHOOK_SECRET
        sent = request.META.get("HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN", "")
        if not hmac.compare_digest(sent.encode(), expected.encode()):
            raise TaraAPIError(
                "Invalid webhook secret.", code="permission_denied", http_status_code=403
            )
        telegram.handle_update(request.data)
        return data_response({"ok": True})
