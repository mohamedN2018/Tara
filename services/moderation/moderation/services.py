"""Moderation business logic: intake reports → cases → moderator actions → events."""

from __future__ import annotations

from django.db import transaction
from django.db.models import F

from tara_common.exceptions import TaraAPIError

from . import events
from .models import Appeal, ModerationAction, ModerationAuditLog, ModerationCase, Report


def ingest_report(
    *, reporter_id: str, target_type: str, target_id: str, reason: str = ""
) -> ModerationCase:
    """Record a report and attach it to the open case for that target (created if none)."""
    open_case = ModerationCase.objects.filter(
        target_type=target_type,
        target_id=str(target_id),
        state__in=[ModerationCase.State.OPEN, ModerationCase.State.IN_REVIEW],
    ).first()
    already_reported = Report.objects.filter(
        reporter_id=reporter_id, target_type=target_type, target_id=str(target_id)
    ).exists()
    if open_case and already_reported:
        return open_case  # one person cannot inflate a case

    with transaction.atomic():
        Report.objects.create(
            reporter_id=reporter_id,
            target_type=target_type,
            target_id=str(target_id),
            reason=reason,
        )
        case = ModerationCase.objects.filter(
            target_type=target_type,
            target_id=str(target_id),
            state__in=[ModerationCase.State.OPEN, ModerationCase.State.IN_REVIEW],
        ).first()
        if case is None:
            case = ModerationCase.objects.create(target_type=target_type, target_id=str(target_id))
        ModerationCase.objects.filter(id=case.id).update(report_count=F("report_count") + 1)
        case.refresh_from_db()
    return case


def queue(state: str | None = None):
    qs = ModerationCase.objects.all()
    if state:
        qs = qs.filter(state=state)
    else:
        qs = qs.exclude(state=ModerationCase.State.RESOLVED)
    return qs.order_by("-report_count", "-created_at", "-id")


def take_action(case_id: str, moderator_id: str, action: str, reason: str = "") -> ModerationAction:
    if action not in ModerationAction.Action.values:
        raise TaraAPIError("Invalid action.", code="validation_error", http_status_code=400)
    case = ModerationCase.objects.filter(id=case_id).first()
    if case is None:
        raise TaraAPIError("Case not found.", code="not_found", http_status_code=404)

    with transaction.atomic():
        before = {"state": case.state}
        record = ModerationAction.objects.create(
            case=case, moderator_id=moderator_id, action=action, reason=reason
        )
        case.state = ModerationCase.State.RESOLVED
        case.save(update_fields=["state", "updated_at"])
        ModerationAuditLog.objects.create(
            case=case,
            actor_id=moderator_id,
            action=f"action:{action}",
            before=before,
            after={"state": case.state},
        )
        # Tell the owning content service to enforce the decision.
        events.emit(
            "moderation.actioned",
            subject_id=str(case.id),
            payload={
                "case_id": str(case.id),
                "target_type": case.target_type,
                "target_id": case.target_id,
                "action": action,
            },
            actor_id=str(moderator_id),
        )
    return record


def assign(case_id: str, moderator_id: str) -> ModerationCase:
    case = ModerationCase.objects.filter(id=case_id).first()
    if case is None:
        raise TaraAPIError("Case not found.", code="not_found", http_status_code=404)
    case.assigned_to = moderator_id
    case.state = ModerationCase.State.IN_REVIEW
    case.save(update_fields=["assigned_to", "state", "updated_at"])
    return case


def file_appeal(case_id: str, account_id: str, text: str) -> Appeal:
    case = ModerationCase.objects.filter(id=case_id).first()
    if case is None:
        raise TaraAPIError("Case not found.", code="not_found", http_status_code=404)
    appeal = Appeal.objects.create(case=case, account_id=account_id, text=text)
    events.emit(
        "appeal.created",
        subject_id=str(appeal.id),
        payload={"case_id": str(case.id), "account_id": str(account_id)},
        actor_id=str(account_id),
    )
    return appeal


def resolve_appeal(appeal_id: str, moderator_id: str, status: str) -> Appeal:
    if status not in (Appeal.Status.UPHELD, Appeal.Status.OVERTURNED):
        raise TaraAPIError("Invalid appeal status.", code="validation_error", http_status_code=400)
    appeal = Appeal.objects.select_related("case").filter(id=appeal_id).first()
    if appeal is None:
        raise TaraAPIError("Appeal not found.", code="not_found", http_status_code=404)
    appeal.status = status
    appeal.save(update_fields=["status"])
    ModerationAuditLog.objects.create(
        case=appeal.case,
        actor_id=moderator_id,
        action=f"appeal:{status}",
        before={},
        after={"status": status},
    )
    if status == Appeal.Status.OVERTURNED:
        events.emit(
            "moderation.actioned",
            subject_id=str(appeal.case.id),
            payload={
                "case_id": str(appeal.case.id),
                "target_type": appeal.case.target_type,
                "target_id": appeal.case.target_id,
                "action": "approve",
            },
            actor_id=str(moderator_id),
        )
    return appeal


# ---- inbound report events --------------------------------------------------

_REPORT_EVENT_TARGETS = {
    "post.reported": ("post", "post_id"),
    "listing.reported": ("listing", "listing_id"),
    "message.reported": ("message", "message_id"),
}


def ingest_report_event(event_type: str, payload: dict) -> None:
    target_type, id_key = _REPORT_EVENT_TARGETS[event_type]
    ingest_report(
        reporter_id=payload.get("reporter", payload.get("reporter_id", "")),
        target_type=target_type,
        target_id=payload.get(id_key, payload.get("post_id", "")),
        reason=payload.get("reason", ""),
    )
