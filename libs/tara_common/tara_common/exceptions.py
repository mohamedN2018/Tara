"""Uniform error envelope + DRF exception handler.

Every error across every service looks like:

    {
      "error": {
        "code": "validation_error",
        "message": "Human-readable summary.",
        "request_id": "req_...",
        "details": [{"field": "...", "code": "...", "message": "..."}]
      }
    }

`code` is a stable machine string clients switch on. See
docs/architecture/phase-0/03-api-contracts.md §5.
"""

from __future__ import annotations

from typing import Any

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.http import Http404
from rest_framework import status as http_status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

# Map DRF's default_code (and a few of ours) to stable machine codes + HTTP status.
_CODE_TO_STATUS: dict[str, int] = {
    "validation_error": http_status.HTTP_400_BAD_REQUEST,
    "parse_error": http_status.HTTP_400_BAD_REQUEST,
    "unauthenticated": http_status.HTTP_401_UNAUTHORIZED,
    "authentication_failed": http_status.HTTP_401_UNAUTHORIZED,
    "permission_denied": http_status.HTTP_403_FORBIDDEN,
    "not_found": http_status.HTTP_404_NOT_FOUND,
    "method_not_allowed": http_status.HTTP_405_METHOD_NOT_ALLOWED,
    "conflict": http_status.HTTP_409_CONFLICT,
    "idempotency_conflict": http_status.HTTP_409_CONFLICT,
    "unsupported_media_type": http_status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
    "rate_limited": http_status.HTTP_429_TOO_MANY_REQUESTS,
    "throttled": http_status.HTTP_429_TOO_MANY_REQUESTS,
    "dependency_unavailable": http_status.HTTP_503_SERVICE_UNAVAILABLE,
    "internal_error": http_status.HTTP_500_INTERNAL_SERVER_ERROR,
}


class TaraAPIError(Exception):
    """Raise to return a controlled error envelope from anywhere in a view stack."""

    code = "internal_error"
    message = "An unexpected error occurred."
    http_status = http_status.HTTP_500_INTERNAL_SERVER_ERROR

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        details: list[dict[str, Any]] | None = None,
        http_status_code: int | None = None,
    ) -> None:
        self.message = message or self.message
        self.code = code or self.code
        self.details = details or []
        if http_status_code is not None:
            self.http_status = http_status_code
        elif code in _CODE_TO_STATUS:
            self.http_status = _CODE_TO_STATUS[code]
        super().__init__(self.message)


class Conflict(TaraAPIError):
    code = "conflict"
    message = "The request conflicts with the current state."
    http_status = http_status.HTTP_409_CONFLICT


class DependencyUnavailable(TaraAPIError):
    code = "dependency_unavailable"
    message = "A required dependency is temporarily unavailable."
    http_status = http_status.HTTP_503_SERVICE_UNAVAILABLE


def _normalize_drf_code(default_code: str | None) -> str:
    mapping = {
        "invalid": "validation_error",
        "not_authenticated": "unauthenticated",
    }
    if not default_code:
        return "internal_error"
    return mapping.get(default_code, default_code)


def _flatten_drf_detail(detail: Any) -> list[dict[str, Any]]:
    """Turn DRF's nested validation detail into a flat list of field errors."""
    out: list[dict[str, Any]] = []

    def walk(node: Any, field: str | None) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, key if field is None else f"{field}.{key}")
        elif isinstance(node, (list, tuple)):
            for item in node:
                walk(item, field)
        else:
            code = getattr(node, "code", None) or "invalid"
            out.append(
                {
                    "field": field,
                    "code": "validation_error" if code == "invalid" else code,
                    "message": str(node),
                }
            )

    walk(detail, None)
    return out


def tara_exception_handler(exc: Exception, context: dict) -> Response | None:
    """DRF EXCEPTION_HANDLER. Produces the uniform error envelope."""
    request = context.get("request")
    request_id = getattr(request, "request_id", None) if request else None

    # Our own controlled errors
    if isinstance(exc, TaraAPIError):
        body = {
            "error": {
                "code": exc.code,
                "message": exc.message,
                "request_id": request_id,
                "details": exc.details,
            }
        }
        return Response(body, status=exc.http_status)

    # Bridge a couple of Django-native exceptions DRF doesn't handle by default
    if isinstance(exc, Http404):
        exc_code, exc_status, message = "not_found", 404, "Resource not found."
        return Response(
            {
                "error": {
                    "code": exc_code,
                    "message": message,
                    "request_id": request_id,
                    "details": [],
                }
            },
            status=exc_status,
        )
    if isinstance(exc, DjangoPermissionDenied):
        return Response(
            {
                "error": {
                    "code": "permission_denied",
                    "message": "You do not have permission to perform this action.",
                    "request_id": request_id,
                    "details": [],
                }
            },
            status=403,
        )

    # Let DRF build the base response, then reshape it.
    response = drf_exception_handler(exc, context)
    if response is None:
        return None  # unhandled -> Django 500 (logged); never leak internals

    default_code = getattr(getattr(exc, "detail", None), "code", None) or getattr(
        exc, "default_code", None
    )
    code = _normalize_drf_code(default_code)
    details = _flatten_drf_detail(getattr(exc, "detail", None))
    # Pick a human message: first detail or DRF's string detail
    message = details[0]["message"] if details else str(getattr(exc, "detail", "Request failed."))

    retry_after = response.headers.get("Retry-After")
    body = {
        "error": {
            "code": code,
            "message": message,
            "request_id": request_id,
            "details": details if len(details) > 1 else [],
        }
    }
    new_response = Response(body, status=response.status_code)
    if retry_after is not None:
        new_response["Retry-After"] = retry_after
    return new_response
