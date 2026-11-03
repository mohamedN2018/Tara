"""Request correlation middleware.

Attaches a request id (from the inbound `X-Request-Id` or freshly generated) to
every request and response, and binds it for structured logging. This id is the
correlation_id propagated into events and traces.
"""

from __future__ import annotations

import re
import uuid

REQUEST_ID_HEADER = "HTTP_X_REQUEST_ID"
RESPONSE_HEADER = "X-Request-Id"
# A client-supplied id ends up in logs, response headers and the outbox's
# correlation_id column (120 chars), so anything else is replaced.
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,100}$")


def _new_request_id() -> str:
    return f"req_{uuid.uuid4().hex}"


class RequestIDMiddleware:
    """Django middleware: ensure every request carries a correlation id."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        incoming = request.META.get(REQUEST_ID_HEADER, "").strip()
        request_id = incoming if _VALID_REQUEST_ID.match(incoming) else _new_request_id()
        request.request_id = request_id

        # Bind to logging context if tara_observability is installed.
        try:
            from tara_observability.logging import bind_request_id

            bind_request_id(request_id)
        except Exception:  # noqa: S110,BLE001 - observability must never break requests
            pass

        response = self.get_response(request)
        response[RESPONSE_HEADER] = request_id
        return response
