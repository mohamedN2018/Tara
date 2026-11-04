"""What a member may learn about moderation: their own account status and their reports.

Two reads, both scoped to the signed-in account:

* **My cases** - decisions that did something to the member's own content or
  account (removed, warned, restricted), with the reason the moderator shared,
  whether it can still be appealed and how an appeal went. A shadow restriction
  is never listed: telling its subject would defeat it. Open cases are never
  listed either, so being reported is not news to the reported.
* **My reports** - what the member reported, and whether the case it joined is
  still being reviewed or what came of it, as a coarse outcome (``actioned`` or
  ``no_action``). Never who else reported, who decided, or the reason.

The queue staff see lives in ``services``; nothing here takes a capability.
"""

from __future__ import annotations

from django.db.models import OuterRef, Q, Subquery

from .models import Appeal, ModerationAction, ModerationCase, Report

# Decisions the owner is told about. ``shadow`` is deliberately absent.
VISIBLE_DECISIONS = ("remove", "restrict", "warn")
# What a reporter learns about the case their report joined.
_ACTIONED = frozenset({"remove", "restrict", "shadow", "warn"})


def _latest_action(field: str):
    return Subquery(
        ModerationAction.objects.filter(case=OuterRef("pk"))
        .order_by("-created_at", "-id")
        .values(field)[:1]
    )


def my_cases(account_id):
    """Resolved cases about ``account_id`` whose decision did something visible, newest first."""
    return (
        ModerationCase.objects.filter(owner_id=account_id, state=ModerationCase.State.RESOLVED)
        .annotate(
            decision=_latest_action("action"),
            decision_reason=_latest_action("reason"),
            decided_at=_latest_action("created_at"),
            appeal_status=Subquery(
                Appeal.objects.filter(case=OuterRef("pk"))
                .order_by("-created_at")
                .values("status")[:1]
            ),
            appealed_at=Subquery(
                Appeal.objects.filter(case=OuterRef("pk"))
                .order_by("-created_at")
                .values("created_at")[:1]
            ),
        )
        .filter(decision__in=VISIBLE_DECISIONS)
        .order_by("-updated_at", "-id")
    )


def my_reports(reporter_id):
    """The reports ``reporter_id`` filed, newest first."""
    return Report.objects.filter(reporter_id=reporter_id).order_by("-created_at", "-id")


def report_outcomes(reports) -> dict:
    """``{report_id: (state, outcome)}`` for one page of reports.

    A report joins the open case of its target, which was opened at or before
    the report. So the case a report belongs to is the target's newest case
    opened no later than the report. Cases of one page are read in one query.
    """
    reports = list(reports)
    if not reports:
        return {}
    targets = Q()
    for r in reports:
        targets |= Q(target_type=r.target_type, target_id=r.target_id)
    cases = list(
        ModerationCase.objects.filter(targets)
        .annotate(decision=_latest_action("action"))
        .order_by("created_at", "id")
        .values("target_type", "target_id", "created_at", "state", "decision")
    )
    out: dict = {}
    for r in reports:
        joined = None
        for case in cases:
            if (
                case["target_type"] == r.target_type
                and case["target_id"] == r.target_id
                and case["created_at"] <= r.created_at
            ):
                joined = case  # ascending: the last match is the newest
        if joined is None:
            out[r.id] = ("open", None)
        elif joined["state"] != ModerationCase.State.RESOLVED:
            out[r.id] = (joined["state"], None)
        else:
            out[r.id] = (
                "resolved",
                "actioned" if joined["decision"] in _ACTIONED else "no_action",
            )
    return out


def summary(*, moderator_id, with_appeals: bool) -> dict:
    """Counts for the console overview."""
    unresolved = ModerationCase.objects.exclude(state=ModerationCase.State.RESOLVED)
    data = {
        "open": unresolved.filter(state=ModerationCase.State.OPEN).count(),
        "in_review": unresolved.filter(state=ModerationCase.State.IN_REVIEW).count(),
        "assigned_to_me": unresolved.filter(assigned_to=moderator_id).count(),
    }
    if with_appeals:
        data["open_appeals"] = Appeal.objects.filter(status=Appeal.Status.OPEN).count()
    return data
