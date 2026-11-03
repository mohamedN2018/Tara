"""HTTP idempotency for unsafe writes via the ``Idempotency-Key`` header.

Same key + same request fingerprint within the TTL → the original response is
replayed and the side effect runs exactly once. Same key + DIFFERENT body →
409 ``idempotency_conflict``. See docs/architecture/phase-0/03-api-contracts.md §3.

Each service defines a concrete model subclassing AbstractIdempotencyRecord.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import TYPE_CHECKING

from django.db import IntegrityError, models, transaction
from django.utils import timezone

if TYPE_CHECKING:
    from rest_framework.request import Request
    from rest_framework.response import Response

HEADER = "HTTP_IDEMPOTENCY_KEY"
# A claim still "in progress" after this long belongs to a request that died
# (the worker timeout is 60 s); a retry may take it over. Setting:
# TARA_IDEMPOTENCY_STALE_SECONDS.
DEFAULT_STALE_SECONDS = 60


class AbstractIdempotencyRecord(models.Model):
    key = models.CharField(max_length=200)
    fingerprint = models.CharField(max_length=64)
    response_status = models.PositiveIntegerField(null=True)
    response_body = models.JSONField(null=True)
    in_progress = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    class Meta:
        abstract = True
        constraints = [
            models.UniqueConstraint(fields=["key"], name="%(class)s_key_uniq"),
        ]


def _scoped_key(request: Request, key: str) -> str:
    """The same key from two callers must never replay one caller's response."""
    user = getattr(request, "user", None)
    owner = getattr(user, "account_id", None) or "anon"
    return hashlib.sha256(f"{owner}|{key}".encode()).hexdigest()


def _fingerprint(request: Request) -> str:
    # Use DRF's parsed+cached data so we don't touch the (already-consumed)
    # request body stream, which would raise RawPostDataException.
    try:
        basis = json.dumps(request.data, sort_keys=True, default=str).encode()
    except Exception:  # noqa: BLE001 - fall back to raw body if not parsed
        basis = getattr(request, "body", b"") or b""
    parts = b"|".join([request.method.encode(), request.path.encode(), basis])
    return hashlib.sha256(parts).hexdigest()


def idempotent(
    record_model: type[AbstractIdempotencyRecord],
    request: Request,
    handler: Callable[[], Response],
    *,
    ttl_seconds: int = 86_400,
    stale_after_seconds: int | None = None,
) -> Response:
    """Execute ``handler`` at most once per Idempotency-Key.

    If no key is supplied, the handler simply runs (idempotency is opt-in). A
    claim still in progress after ``stale_after_seconds`` is taken over by the retry.
    """
    from django.conf import settings
    from rest_framework.response import Response

    from tara_common.exceptions import Conflict

    if stale_after_seconds is None:
        stale_after_seconds = int(
            getattr(settings, "TARA_IDEMPOTENCY_STALE_SECONDS", DEFAULT_STALE_SECONDS)
        )

    key = request.META.get(HEADER, "").strip()
    if not key:
        return handler()

    key = _scoped_key(request, key)
    fingerprint = _fingerprint(request)
    record_model.objects.filter(key=key, expires_at__lte=timezone.now()).delete()

    # Try to claim the key.
    try:
        with transaction.atomic():
            record_model.objects.create(
                key=key,
                fingerprint=fingerprint,
                expires_at=timezone.now() + timezone.timedelta(seconds=ttl_seconds),
            )
            claimed = True
    except IntegrityError:
        claimed = False

    if not claimed:
        existing = record_model.objects.filter(key=key).first()
        if existing is None:
            # The request that held the key failed and released it just now.
            raise Conflict(
                "A request with this Idempotency-Key is still being processed.",
                code="conflict",
            )
        if existing.fingerprint != fingerprint:
            raise Conflict(
                "Idempotency-Key reused with a different request.",
                code="idempotency_conflict",
            )
        if existing.in_progress:
            stale_before = timezone.now() - timezone.timedelta(seconds=stale_after_seconds)
            # Conditional on the exact claim seen, so two retries cannot both take it over.
            taken_over = (
                existing.created_at < stale_before
                and record_model.objects.filter(
                    pk=existing.pk, in_progress=True, created_at=existing.created_at
                ).update(created_at=timezone.now())
                == 1
            )
            if not taken_over:
                # A concurrent request with the same key is still running.
                raise Conflict(
                    "A request with this Idempotency-Key is still being processed.",
                    code="conflict",
                )
        else:
            return Response(existing.response_body, status=existing.response_status)

    # We own the key: run the handler, then persist its response.
    try:
        response = handler()
    except Exception:
        # Let the client retry with the same key.
        record_model.objects.filter(key=key).delete()
        raise
    record_model.objects.filter(key=key).update(
        in_progress=False,
        response_status=response.status_code,
        response_body=response.data if hasattr(response, "data") else None,
    )
    return response
