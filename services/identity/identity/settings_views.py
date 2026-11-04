"""Settings-centre endpoints (plan 08 wave 3C): two-factor authentication,
login activity, recognised devices, deactivation, and the birthday and gender
another person may see. Logic lives in two_factor.py and account_center.py."""

from __future__ import annotations

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tara_common.responses import data_response

from . import account_center, two_factor
from .serializers import (
    DeactivateSerializer,
    PersonalDetailsSerializer,
    ReauthSerializer,
    TwoFactorCodeSerializer,
    TwoFactorDisableSerializer,
)
from .views import _clear_refresh_cookie, _client_meta, _get_account


def _session_id(request: Request) -> str | None:
    return getattr(request.user, "claims", {}).get("sid")


def _region(request: Request) -> str:
    return _client_meta(request)["ip_region"]


class TwoFactorView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: OpenApiResponse(description="2FA status")}, tags=["account"])
    def get(self, request: Request) -> Response:
        return data_response(two_factor.status(_get_account(request)))


class TwoFactorSetupView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_scope = "account_security"

    @extend_schema(
        request=ReauthSerializer,
        responses={200: OpenApiResponse(description="Secret and otpauth URI, shown once")},
        tags=["account"],
    )
    def post(self, request: Request) -> Response:
        serializer = ReauthSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return data_response(
            two_factor.start_setup(
                _get_account(request),
                password=serializer.validated_data.get("password", ""),
                ip_region=_region(request),
            )
        )


class TwoFactorConfirmView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_scope = "account_security"

    @extend_schema(
        request=TwoFactorCodeSerializer,
        responses={200: OpenApiResponse(description="2FA on; the recovery codes, shown once")},
        tags=["account"],
    )
    def post(self, request: Request) -> Response:
        serializer = TwoFactorCodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        account = _get_account(request)
        codes = two_factor.confirm_setup(
            account, code=serializer.validated_data["code"], ip_region=_region(request)
        )
        return data_response({**two_factor.status(account), "recovery_codes": codes})


class TwoFactorDisableView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_scope = "account_security"

    @extend_schema(
        request=TwoFactorDisableSerializer,
        responses={200: OpenApiResponse(description="2FA off")},
        tags=["account"],
    )
    def post(self, request: Request) -> Response:
        serializer = TwoFactorDisableSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        account = _get_account(request)
        two_factor.disable(
            account,
            password=serializer.validated_data.get("password", ""),
            code=serializer.validated_data["code"],
            ip_region=_region(request),
        )
        return data_response(two_factor.status(account))


class RecoveryCodesView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_scope = "account_security"

    @extend_schema(
        request=ReauthSerializer,
        responses={
            200: OpenApiResponse(description="New recovery codes; the old ones stop working")
        },
        tags=["account"],
    )
    def post(self, request: Request) -> Response:
        serializer = ReauthSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        account = _get_account(request)
        codes = two_factor.regenerate_recovery_codes(
            account,
            password=serializer.validated_data.get("password", ""),
            ip_region=_region(request),
        )
        return data_response({**two_factor.status(account), "recovery_codes": codes})


class SecurityActivityView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={200: OpenApiResponse(description="The owner's login and security activity")},
        tags=["account"],
    )
    def get(self, request: Request) -> Response:
        return data_response(
            account_center.security_activity(
                _get_account(request), before=request.query_params.get("before") or None
            )
        )


class DeviceListView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={200: OpenApiResponse(description="Recognised devices")}, tags=["account"]
    )
    def get(self, request: Request) -> Response:
        return data_response(
            account_center.devices(_get_account(request), current_session_id=_session_id(request))
        )


class DeviceDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={204: None}, tags=["account"])
    def delete(self, request: Request, device_id: str) -> Response:
        account_center.remove_device(
            _get_account(request),
            str(device_id),
            current_session_id=_session_id(request),
            ip_region=_region(request),
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class DeactivateView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_scope = "account_security"

    @extend_schema(
        request=DeactivateSerializer,
        responses={200: OpenApiResponse(description="Deactivated and signed out everywhere")},
        tags=["account"],
    )
    def post(self, request: Request) -> Response:
        serializer = DeactivateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        meta = _client_meta(request)
        revoked = account_center.deactivate(
            _get_account(request),
            password=serializer.validated_data.get("password", ""),
            confirm=serializer.validated_data["confirm"],
            ip_region=meta["ip_region"],
            correlation_id=meta["correlation_id"],
        )
        response = data_response({"status": "deactivated", "revoked_sessions": revoked})
        _clear_refresh_cookie(response)
        return response


class DeleteAccountView(APIView):
    """Schedule the account's deletion: hidden and signed out now, erased after
    30 days unless the owner signs in before then."""

    permission_classes = [IsAuthenticated]
    throttle_scope = "account_security"

    @extend_schema(
        request=DeactivateSerializer,
        responses={200: OpenApiResponse(description="Deletion scheduled; signed out everywhere")},
        tags=["account"],
    )
    def post(self, request: Request) -> Response:
        serializer = DeactivateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        meta = _client_meta(request)
        result = account_center.schedule_deletion(
            _get_account(request),
            password=serializer.validated_data.get("password", ""),
            confirm=serializer.validated_data["confirm"],
            ip_region=meta["ip_region"],
            correlation_id=meta["correlation_id"],
        )
        response = data_response({"status": "deletion_scheduled", **result})
        _clear_refresh_cookie(response)
        return response


class PersonalDetailsView(APIView):
    """Birthday (day and month) and gender of an account, as the caller may see them."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: PersonalDetailsSerializer}, tags=["account"])
    def get(self, request: Request, account_id: str) -> Response:
        return data_response(account_center.personal_details(str(request.user.id), str(account_id)))
