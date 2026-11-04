"""Account status and administrative notices (track T7).

* ``moderation.actioned`` -> ``moderation.decision`` to the content's owner when
  a moderator removed it, warned them or restricted the account. A shadow
  restriction is never announced (telling its subject would defeat it), nor
  are approvals and dismissals, which did nothing to the owner. A reversal
  (``approve`` after an overturned appeal) is told by ``moderation.appeal``.
* ``appeal.resolved`` -> ``moderation.appeal`` to the appellant: upheld or overturned.
* ``system.notice`` -> ``system.notice`` to each recipient, with the staff's text.

The rows link to the Support inbox (``/support``), where the case and its
appeal live. No actor is named: decisions come from "the Tara team".
Imported by ``handlers`` so the consumer registers them.
"""

from __future__ import annotations

from tara_events import on_event
from tara_events.envelope import EventEnvelope

from .services import notify

ANNOUNCED_DECISIONS = frozenset({"remove", "warn", "restrict"})


@on_event("moderation.actioned")
def on_moderation_decision(e: EventEnvelope) -> None:
    p = e.payload if isinstance(e.payload, dict) else {}
    owner, action, case_id = p.get("owner_id"), p.get("action"), p.get("case_id")
    if not owner or not case_id or action not in ANNOUNCED_DECISIONS:
        return
    notify(
        owner,
        "moderation.decision",
        subject_ref=f"case:{case_id}",
        body=f"moderation decision: {action}",
        data={"case_id": case_id, "decision": action, "target_type": p.get("target_type")},
    )


@on_event("appeal.resolved")
def on_appeal_resolved(e: EventEnvelope) -> None:
    p = e.payload if isinstance(e.payload, dict) else {}
    account, case_id, status = p.get("account_id"), p.get("case_id"), p.get("status")
    if not account or not case_id or status not in ("upheld", "overturned"):
        return  # events from before account_id was added reach nobody
    notify(
        account,
        "moderation.appeal",
        subject_ref=f"case:{case_id}",
        body=f"your appeal was {status}",
        data={"case_id": case_id, "status": status, "target_type": p.get("target_type")},
    )


@on_event("system.notice")
def on_system_notice(e: EventEnvelope) -> None:
    p = e.payload if isinstance(e.payload, dict) else {}
    notice_id, body = p.get("notice_id") or e.subject_id, str(p.get("body") or "").strip()
    if not notice_id or not body:
        return
    for recipient in p.get("recipients") or []:
        notify(
            recipient,
            "system.notice",
            subject_ref=f"notice:{notice_id}",
            group_key=f"notice:{notice_id}",
            body=body,
            data={"notice_id": notice_id},
        )
