"""Standing account restrictions for Tara Intelligence (WP 3.2 / 3.3, rule E11),
under ``/internal/v1/intel/export/restrictions/``.

feed (``intel_account_restriction``) and graph (``AccountRef.restriction``) learn
of a ``restrict`` or ``shadow`` on a user from ``moderation.actioned``. A
restriction decided before they consumed it stays unknown to them until the next
event on that account. This export lets them backfill once (and after missed
events).

One item per user case whose decision (its latest action, ``services._decision``)
is ``restrict`` or ``shadow`` and that no appeal overturned:
``{account_id, action, case_id}``. A complete scan therefore also tells the reader
that an account it does not list has no restriction standing (the same rule as
``reinstate``). Ids and the action only, which every consumer of
``moderation.actioned`` already receives; no reason, report or moderator.
Sensitive (a ``shadow`` is never shown to anyone): never routed by the edge, and
an internal token for ``moderation-internal`` is required (``SearchExportView``).
"""

from __future__ import annotations

from django.db.models import OuterRef, Subquery
from django.urls import path

from tara_common.search_export import SearchExportView

from .models import Appeal, ModerationAction, ModerationCase

RESTRICTIONS = (ModerationAction.Action.RESTRICT, ModerationAction.Action.SHADOW)


def _cases():
    decision = (
        ModerationAction.objects.filter(case_id=OuterRef("pk"))
        .order_by("-created_at", "-id")
        .values("action")[:1]
    )
    return (
        ModerationCase.objects.filter(target_type="user")
        .annotate(decision=Subquery(decision))
        .filter(decision__in=RESTRICTIONS)
        .exclude(appeals__status=Appeal.Status.OVERTURNED)
    )


def restriction_item(case: ModerationCase) -> tuple:
    return case.id, {
        "account_id": str(case.target_id),
        "action": case.decision,
        "case_id": str(case.id),
    }


urlpatterns = [
    path(
        "export/restrictions/",
        SearchExportView.as_view(source=_cases, to_item=restriction_item),
        name="intel-export-restrictions",
    ),
]
