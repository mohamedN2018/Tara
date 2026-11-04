"""Administrative notices (``system.notice``): staff tell some accounts something.

A notice goes to at most ``MAX_RECIPIENTS`` accounts that identity knows. The
row, its audit entry and the ``system.notice`` outbox event commit together, so
a notice is either sent and recorded or neither. Notification turns the event
into one ``system.notice`` row per recipient.
"""

from __future__ import annotations

import uuid

from django.conf import settings
from django.db import transaction

from tara_common.exceptions import TaraAPIError
from tara_common.middleware import current_request_id
from tara_events.envelope import EventEnvelope
from tara_events.outbox import record_event

from . import audit, identity_client
from .models import OutboxEvent, SystemNotice

MAX_RECIPIENTS = 50
MAX_BODY = 300
PRODUCER = "admin-service"


def _known(ids: list[str]) -> list[str]:
    """The ids identity knows, in the order asked; any unknown id refuses the notice."""
    summaries = identity_client.account_summaries(ids)
    found = {str(s.get("id") or s.get("account_id")) for s in summaries if isinstance(s, dict)}
    missing = [i for i in ids if i not in found]
    if missing:
        raise TaraAPIError(
            "Some recipients are not accounts.",
            code="validation_error",
            details=[
                {"field": "recipient_ids", "code": "unknown_account", "message": m} for m in missing
            ],
            http_status_code=400,
        )
    return ids


def send(*, actor_id: str, recipient_ids: list, body: str) -> SystemNotice:
    body = (body or "").strip()
    if not body:
        raise TaraAPIError("Write the notice.", code="validation_error", http_status_code=400)
    ids: list[str] = []
    for raw in recipient_ids:
        value = str(uuid.UUID(str(raw)))
        if value not in ids:
            ids.append(value)
    if not ids or len(ids) > MAX_RECIPIENTS:
        raise TaraAPIError(
            f"Send a notice to 1 to {MAX_RECIPIENTS} accounts.",
            code="validation_error",
            http_status_code=400,
        )
    ids = _known(ids)  # outside the transaction: a network call
    with transaction.atomic():
        notice = SystemNotice.objects.create(
            body=body[:MAX_BODY],
            recipient_ids=ids,
            recipient_count=len(ids),
            created_by=actor_id,
        )
        audit.record(
            "system_notice.sent",
            actor_id=actor_id,
            target_type="system_notice",
            target_id=str(notice.id),
            request_id=current_request_id() or "",
            detail={"recipient_count": len(ids)},
        )
        if settings.ADMIN_EMIT_SYSTEM_NOTICES:
            record_event(
                OutboxEvent,
                EventEnvelope(
                    event_type="system.notice",
                    payload={"notice_id": str(notice.id), "recipients": ids, "body": notice.body},
                    subject_id=str(notice.id),
                    producer=PRODUCER,
                    actor_id=str(actor_id),
                    correlation_id=current_request_id(),
                ),
            )
    return notice


def sent():
    return SystemNotice.objects.order_by("-created_at", "-id")
