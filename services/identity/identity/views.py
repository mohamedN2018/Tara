"""Identity HTTP API (DRF). Views stay thin; logic lives in services.py."""

from __future__ import annotations

from django.conf import settings
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tara_common.exceptions import TaraAPIError
from tara_common.responses import data_response
from tara_resilience.idempotency import idempotent

from . import services
from .models import Account, IdempotencyRecord
from .serializers import (
    AccountSerializer,
    AccountUpdateSerializer,
    LoginSerializer,
    PasswordForgotSerializer,
    PasswordResetSerializer,
    RefreshSerializer,
    RegisterSerializer,
    SessionSerializer,
    TokenResponseSerializer,
    VerifyEmailSerializer,
)
from .tokens import build_jwks

REFRESH_COOKIE = "refresh_token"
REFRESH_COOKIE_PATH = "/api/v1/auth"


# ---- helpers ----------------------------------------------------------------


def _client_meta(request: Request) -> dict[str, str]:
    return {
        "ip_region": request.META.get("HTTP_X_GEO_REGION", ""),  # set by edge; never raw IP
        "user_agent": request.META.get("HTTP_USER_AGENT", ""),
        "correlation_id": getattr(request, "request_id", None),
    }


def _set_refresh_cookie(response: Response, raw: str) -> None:
    response.set_cookie(
        REFRESH_COOKIE,
        raw,
        max_age=settings.REFRESH_TOKEN_TTL_SECONDS,
        httponly=True,
        secure=not settings.DEBUG,
        samesite="Strict",
        path=REFRESH_COOKIE_PATH,
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_COOKIE_PATH)


def _token_body(issued: services.IssuedTokens) -> dict:
    return {
        "access_token": issued.access_token,
        "token_type": "Bearer",
        "expires_in": issued.access_expires_in,
        "refresh_token": issued.refresh_token,
    }


def _get_account(request: Request) -> Account:
    account = Account.objects.filter(id=request.user.id).first()
    if account is None or not account.is_usable:
        raise TaraAPIError("Account not found.", code="not_found", http_status_code=404)
    return account


# ---- auth endpoints ---------------------------------------------------------


class RegisterView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = "auth_register"

    @extend_schema(
        request=RegisterSerializer,
        responses={201: OpenApiResponse(description="Account created; verification email sent.")},
        tags=["auth"],
    )
    def post(self, request: Request) -> Response:
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        meta = _client_meta(request)

        def handler() -> Response:
            account = services.register(
                email=data["email"],
                password=data["password"],
                language=data["language"],
                theme=data["theme"],
                display_name=data["display_name"],
                handle=data["handle"],
                ip_region=meta["ip_region"],
                user_agent=meta["user_agent"],
                correlation_id=meta["correlation_id"],
            )
            return data_response(
                {"account_id": str(account.id), "email": account.email, "status": account.status},
                status=status.HTTP_201_CREATED,
            )

        return idempotent(IdempotencyRecord, request, handler)


class LoginView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = "auth_login"

    @extend_schema(request=LoginSerializer, responses={200: TokenResponseSerializer}, tags=["auth"])
    def post(self, request: Request) -> Response:
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        meta = _client_meta(request)
        issued = services.login(
            email=serializer.validated_data["email"],
            password=serializer.validated_data["password"],
            ip_region=meta["ip_region"],
            user_agent=meta["user_agent"],
            correlation_id=meta["correlation_id"],
        )
        response = data_response(_token_body(issued))
        _set_refresh_cookie(response, issued.refresh_token)
        return response


class RefreshView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = "auth_refresh"

    @extend_schema(
        request=RefreshSerializer, responses={200: TokenResponseSerializer}, tags=["auth"]
    )
    def post(self, request: Request) -> Response:
        serializer = RefreshSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        raw = serializer.validated_data.get("refresh_token") or request.COOKIES.get(REFRESH_COOKIE)
        if not raw:
            raise TaraAPIError(
                "No refresh token provided.", code="unauthenticated", http_status_code=401
            )
        issued = services.refresh(refresh_token=raw)
        response = data_response(_token_body(issued))
        _set_refresh_cookie(response, issued.refresh_token)
        return response


class LogoutView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(request=RefreshSerializer, responses={204: None}, tags=["auth"])
    def post(self, request: Request) -> Response:
        raw = request.data.get("refresh_token") if hasattr(request, "data") else None
        raw = raw or request.COOKIES.get(REFRESH_COOKIE)
        session_id = (
            getattr(request.user, "claims", {}).get("sid")
            if request.user.is_authenticated
            else None
        )
        services.logout(refresh_token=raw, session_id=session_id)
        response = Response(status=status.HTTP_204_NO_CONTENT)
        _clear_refresh_cookie(response)
        return response


class VerifyEmailView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(request=VerifyEmailSerializer, responses={200: AccountSerializer}, tags=["auth"])
    def post(self, request: Request) -> Response:
        serializer = VerifyEmailSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        account = services.verify_email(raw_token=serializer.validated_data["token"])
        return data_response(AccountSerializer(account).data)


class PasswordForgotView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = "auth_password"

    @extend_schema(request=PasswordForgotSerializer, responses={202: None}, tags=["auth"])
    def post(self, request: Request) -> Response:
        serializer = PasswordForgotSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.request_password_reset(email=serializer.validated_data["email"])
        # Always 202 — never disclose whether the email exists.
        return data_response(
            {"detail": "If the email exists, a reset link has been sent."},
            status=status.HTTP_202_ACCEPTED,
        )


class PasswordResetView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = "auth_password"

    @extend_schema(request=PasswordResetSerializer, responses={200: None}, tags=["auth"])
    def post(self, request: Request) -> Response:
        serializer = PasswordResetSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.reset_password(
            raw_token=serializer.validated_data["token"],
            new_password=serializer.validated_data["password"],
        )
        return data_response({"detail": "Password updated. Please sign in again."})


# ---- account & sessions -----------------------------------------------------


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: AccountSerializer}, tags=["account"])
    def get(self, request: Request) -> Response:
        return data_response(AccountSerializer(_get_account(request)).data)

    @extend_schema(
        request=AccountUpdateSerializer, responses={200: AccountSerializer}, tags=["account"]
    )
    def patch(self, request: Request) -> Response:
        account = _get_account(request)
        serializer = AccountUpdateSerializer(account, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return data_response(AccountSerializer(account).data)


class SessionListView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: SessionSerializer(many=True)}, tags=["account"])
    def get(self, request: Request) -> Response:
        account = _get_account(request)
        current_sid = getattr(request.user, "claims", {}).get("sid")
        sessions = services.list_sessions(account)
        data = SessionSerializer(
            sessions, many=True, context={"current_session_id": current_sid}
        ).data
        return data_response(data)


class SessionDeleteView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={204: None}, tags=["account"])
    def delete(self, request: Request, session_id: str) -> Response:
        account = _get_account(request)
        services.revoke_session_by_id(account, session_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class JWKSView(APIView):
    permission_classes = [AllowAny]
    authentication_classes: list = []

    @extend_schema(
        responses={200: OpenApiResponse(description="JSON Web Key Set")}, tags=["wellknown"]
    )
    def get(self, _request: Request) -> Response:
        return Response(build_jwks())
