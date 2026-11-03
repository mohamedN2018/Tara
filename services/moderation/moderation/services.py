"""Moderation business logic: intake reports → cases → moderator actions → events."""

from __future__ import annotations

import logging
import uuid

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F

from tara_common.exceptions import Conflict, TaraAPIError

from . import events
from .models import Appeal, ModerationAction, ModerationAuditLog, ModerationCase, Report

logger = logging.getLogger("tara.moderation")

OPEN_STATES = (ModerationCase.State.OPEN, ModerationCase.State.IN_REVIEW)

# What a moderator may do to each kind of target. Content can be removed or
# approved; accounts can be restricted or shadow-restricted; anything can be
# dismissed or answered with a warning to its owner. A pair outside this table
# has no meaning for the owning service, so it is refused instead of emitted.
_CONTENT_ACTIONS = frozenset({"remove", "approve", "warn", "dismiss"})
ACTIONS_BY_TARGET: dict[str, frozenset[str]] = {
    "post": _CONTENT_ACTIONS,
    "comment": _CONTENT_ACTIONS,
    "message": _CONTENT_ACTIONS,
    "listing": _CONTENT_ACTIONS,
    "listing_review": _CONTENT_ACTIONS,
    "gathering": _CONTENT_ACTIONS,  # an event (post service, 1.13)
    "group": _CONTENT_ACTIONS,  # a group (profile service, 1.11): remove suspends it
    "page": frozenset({"remove", "restrict", "warn", "dismiss"}),
    "user": frozenset({"restrict", "shadow", "warn", "dismiss"}),
}
# A case on a target type nobody listed above can still be closed.
_FALLBACK_ACTIONS = frozenset({"dismiss"})

# Decisions that did something to the owner; only these can be appealed.
APPEALABLE_ACTIONS = frozenset({"remove", "restrict", "shadow", "warn"})

# What an overturned appeal sends to the owning service: the inverse of the
# original decision on that target type. Only a content removal has one in the
# shared vocabulary (``approve`` restores it). A warning never touched the
# content, and users and pages have no reinstate action yet, so overturning
# those is recorded in the audit log and emits nothing: an ``approve`` there
# would restore content that another case removed.
REVERSALS: dict[tuple[str, str], str] = {
    (target_type, "remove"): "approve"
    for target_type in (
        "post",
        "comment",
        "message",
        "listing",
        "listing_review",
        "gathering",
        "group",
    )
}


def _not_found(what: str = "Case") -> TaraAPIError:
    return TaraAPIError(f"{what} not found.", code="not_found", http_status_code=404)


def _as_uuid(value) -> uuid.UUID | None:
    """Parse an optional id from an event or token; anything malformed is None."""
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


def allowed_actions(target_type: str) -> frozenset[str]:
    return ACTIONS_BY_TARGET.get(target_type, _FALLBACK_ACTIONS)


# ---- report intake ----------------------------------------------------------


def _locked_open_case(target_type: str, target_id: str) -> ModerationCase | None:
    return (
        ModerationCase.objects.select_for_update()
        .filter(target_type=target_type, target_id=target_id, state__in=OPEN_STATES)
        .first()
    )


def _open_case_for_update(target_type: str, target_id: str) -> tuple[ModerationCase, bool]:
    """Return the target's open case, locked, creating it if needed: (case, created).

    Two first reports for the same target can both see no open case. The partial
    unique index ``one_open_case_per_target`` lets only one insert win; the loser
    gets an ``IntegrityError`` inside its savepoint and joins the winner's case.
    """
    for _ in range(3):
        case = _locked_open_case(target_type, target_id)
        if case is not None:
            return case, False
        try:
            with transaction.atomic():  # savepoint: the caller's transaction survives
                return ModerationCase.objects.create(
                    target_type=target_type, target_id=target_id
                ), True
        except IntegrityError:
            logger.info(
                "concurrent first report; joining the open case",
                extra={"target_type": target_type},
            )
    raise Conflict("The case for this target is changing; try again.", code="conflict")


def ingest_report(
    *,
    reporter_id: str,
    target_type: str,
    target_id: str,
    reason: str = "",
    owner_id: str | None = None,
) -> ModerationCase:
    """Record a report and attach it to the open case for that target (created if none).

    ``owner_id`` is who the reported content belongs to. Old events do not carry
    it, so it is optional; the first report that knows it fills it in.
    """
    target_id = str(target_id)
    owner = _as_uuid(owner_id)
    with transaction.atomic():
        case, created = _open_case_for_update(target_type, target_id)
        if owner is not None and case.owner_id is None:
            case.owner_id = owner
            case.save(update_fields=["owner_id", "updated_at"])
        # The case row is locked, so this check cannot race a second report.
        if (
            not created
            and Report.objects.filter(
                reporter_id=reporter_id, target_type=target_type, target_id=target_id
            ).exists()
        ):
            return case  # one person cannot inflate a case
        Report.objects.create(
            reporter_id=reporter_id,
            target_type=target_type,
            target_id=target_id,
            reason=reason[:200],
        )
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


# ---- moderator workflow -----------------------------------------------------


def _case_for_update(case_id: str) -> ModerationCase:
    case = ModerationCase.objects.select_for_update().filter(id=case_id).first()
    if case is None:
        raise _not_found()
    return case


def take_action(case_id: str, moderator_id: str, action: str, reason: str = "") -> ModerationAction:
    if action not in ModerationAction.Action.values:
        raise TaraAPIError("Invalid action.", code="validation_error", http_status_code=400)

    with transaction.atomic():
        # The lock makes a second, concurrent action wait and then see RESOLVED,
        # so each case emits exactly one moderation.actioned.
        case = _case_for_update(case_id)
        if case.state == ModerationCase.State.RESOLVED:
            raise Conflict("This case is already resolved.", code="conflict")
        if action not in allowed_actions(case.target_type):
            raise TaraAPIError(
                f"'{action}' does not apply to a {case.target_type}.",
                code="validation_error",
                http_status_code=400,
            )
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
    """Claim an open or in-review case. A resolved case is never reopened."""
    with transaction.atomic():
        case = _case_for_update(case_id)
        if case.state not in OPEN_STATES:
            raise Conflict("Only open or in-review cases can be assigned.", code="conflict")
        before = {
            "state": case.state,
            "assigned_to": str(case.assigned_to) if case.assigned_to else None,
        }
        case.assigned_to = moderator_id
        case.state = ModerationCase.State.IN_REVIEW
        case.save(update_fields=["assigned_to", "state", "updated_at"])
        ModerationAuditLog.objects.create(
            case=case,
            actor_id=moderator_id,
            action="assign",
            before=before,
            after={"state": case.state, "assigned_to": str(moderator_id)},
        )
    return case


# ---- appeals ----------------------------------------------------------------


def _decision(case: ModerationCase) -> str | None:
    """The action that resolved ``case`` (a case is actioned once)."""
    return case.actions.order_by("-created_at", "-id").values_list("action", flat=True).first()


def _reversal(case: ModerationCase) -> tuple[str | None, uuid.UUID | None]:
    """What overturning ``case``'s decision emits: ``(inverse, None)``, or
    ``(None, standing_case_id)`` when another case's decision keeps it in force.

    The caller holds the locks on every existing case of the target, so a
    concurrent overturn of, or action on, one of them waits for this answer.
    """
    decision = _decision(case)
    inverse = REVERSALS.get((case.target_type, decision))
    if inverse is None:
        return None, None
    # The latest content decision of the target's other cases is what stands
    # once this one is undone. Decisions overturned on appeal no longer count.
    standing = (
        ModerationAction.objects.filter(
            case__target_type=case.target_type,
            case__target_id=case.target_id,
            action__in=(decision, inverse),
        )
        .exclude(case_id=case.id)
        .exclude(case__appeals__status=Appeal.Status.OVERTURNED)
        .order_by("-created_at", "-id")
        .first()
    )
    if standing is not None and standing.action == decision:
        return None, standing.case_id
    return inverse, None


def file_appeal(case_id: str, account_id: str, text: str) -> Appeal:
    """Only the owner of the moderated content may appeal, once, after a decision."""
    with transaction.atomic():
        case = ModerationCase.objects.select_for_update().filter(id=case_id).first()
        account = _as_uuid(account_id)
        # Anyone but the owner learns nothing: not whether the case exists, nor its state.
        if case is None or case.owner_id is None or case.owner_id != account:
            raise _not_found()
        if case.state != ModerationCase.State.RESOLVED:
            raise Conflict("Only resolved cases can be appealed.", code="conflict")
        if _decision(case) not in APPEALABLE_ACTIONS:
            raise Conflict("This decision took no action, so it cannot be appealed.")
        # The case row is locked, so two appeals cannot both pass this check.
        if Appeal.objects.filter(case=case).exists():
            raise Conflict("This case has already been appealed.", code="conflict")
        appeal = Appeal.objects.create(case=case, account_id=account, text=text)
        events.emit(
            "appeal.created",
            subject_id=str(appeal.id),
            payload={"case_id": str(case.id), "account_id": str(account)},
            actor_id=str(account),
        )
    return appeal


def appeals(status: str | None = None):
    """The appeal queue, oldest first; open appeals unless ``status`` says otherwise."""
    return (
        Appeal.objects.filter(status=status or Appeal.Status.OPEN)
        .select_related("case")
        .order_by("created_at", "id")
    )


def resolve_appeal(appeal_id: str, moderator_id: str, status: str) -> Appeal:
    if status not in (Appeal.Status.UPHELD, Appeal.Status.OVERTURNED):
        raise TaraAPIError("Invalid appeal status.", code="validation_error", http_status_code=400)
    with transaction.atomic():
        # Lock only the appeal here (FOR UPDATE OF appeal): the case rows are
        # locked next, all of the target's at once and in id order, so two
        # overturns on one target wait for each other instead of deadlocking.
        appeal = (
            Appeal.objects.select_for_update(of=("self",))
            .select_related("case")
            .filter(id=appeal_id)
            .first()
        )
        if appeal is None:
            raise _not_found("Appeal")
        if appeal.status != Appeal.Status.OPEN:
            # Re-resolving would emit a second reversal.
            raise Conflict("This appeal is already resolved.", code="conflict")
        case = appeal.case
        list(
            ModerationCase.objects.select_for_update()
            .filter(target_type=case.target_type, target_id=case.target_id)
            .order_by("id")
            .values_list("id", flat=True)
        )
        appeal.status = status
        appeal.save(update_fields=["status"])
        after: dict = {"status": status}
        reversal = None
        if status == Appeal.Status.OVERTURNED:
            reversal, standing_case = _reversal(case)
            after["reversal"] = reversal
            if standing_case is not None:
                after["kept_by_case"] = str(standing_case)
        ModerationAuditLog.objects.create(
            case=case,
            actor_id=moderator_id,
            action=f"appeal:{status}",
            before={"status": Appeal.Status.OPEN},
            after=after,
        )
        if reversal is not None:
            events.emit(
                "moderation.actioned",
                subject_id=str(case.id),
                payload={
                    "case_id": str(case.id),
                    "target_type": case.target_type,
                    "target_id": case.target_id,
                    "action": reversal,
                },
                actor_id=str(moderator_id),
            )
        # An upheld appeal, or an overturn with nothing to reverse, emits no
        # moderation.actioned, so without this event the decision is invisible
        # outside moderation. Ids and enums only: never the appeal's text.
        if settings.MODERATION_EMIT_AUDIT_EVENTS:
            events.emit(
                "appeal.resolved",
                subject_id=str(appeal.id),
                payload={
                    "appeal_id": str(appeal.id),
                    "case_id": str(case.id),
                    "target_type": case.target_type,
                    "status": status,
                    "reversal": reversal,
                },
                actor_id=str(moderator_id),
            )
    return appeal


# ---- inbound report events --------------------------------------------------

_REPORT_EVENT_TARGETS = {
    "post.reported": ("post", "post_id"),
    "comment.reported": ("comment", "comment_id"),
    "listing.reported": ("listing", "listing_id"),
    "message.reported": ("message", "message_id"),
    "marketplace.review.reported": ("listing_review", "review_id"),
    "gathering.reported": ("gathering", "gathering_id"),
    "group.reported": ("group", "group_id"),
}


def ingest_report_event(event_type: str, payload: dict) -> None:
    target_type, id_key = _REPORT_EVENT_TARGETS[event_type]
    reporter = _as_uuid(payload.get("reporter") or payload.get("reporter_id"))
    target_id = payload.get(id_key)
    if reporter is None or not target_id:
        # Retrying cannot fix a malformed event, and a report without a reporter
        # cannot be deduped, so drop it instead of dead-lettering.
        logger.warning(
            "report event without reporter or target skipped", extra={"event": event_type}
        )
        return
    ingest_report(
        reporter_id=str(reporter),
        target_type=target_type,
        target_id=str(target_id),
        reason=str(payload.get("reason") or ""),
        owner_id=payload.get("owner_id"),  # absent on events from before 1.2
    )
