"""Admin's event consumer: audit-worthy decisions from other services (roadmap 8.1).

Each handler turns one event into one ``AuditEntry``. The worker runs it inside
the idempotency guard's transaction, and ``source_event_id`` is unique, so a
redelivery never adds a row. Handler names are dedupe keys: never rename them.

Only ids and enums are copied (``audit.clean_detail`` with an explicit key
list). A malformed event is still recorded with what it has, or skipped; it
never raises, because a retry cannot repair it and it would only dead-letter.
"""

from __future__ import annotations

import logging

from tara_events.dispatch import on_event
from tara_events.envelope import EventEnvelope

from . import audit

logger = logging.getLogger("tara.admin.handlers")


def _payload(env: EventEnvelope) -> dict:
    return env.payload if isinstance(env.payload, dict) else {}


def _record(
    env: EventEnvelope,
    action: str,
    *,
    target_type: str,
    target_id,
    detail_keys: tuple[str, ...],
) -> None:
    payload = _payload(env)
    audit.record(
        action,
        actor_id=env.actor_id,
        actor_name=env.producer,
        target_type=target_type,
        target_id=str(target_id or ""),
        request_id=env.correlation_id or "",
        detail=audit.clean_detail(payload, detail_keys),
        occurred_at=audit.parse_occurred_at(env.occurred_at),
        source_event_id=env.event_id,
    )


@on_event("account.role.granted")
def audit_role_granted(env: EventEnvelope) -> None:
    _record(
        env,
        "role.granted",
        target_type="account",
        target_id=_payload(env).get("account_id") or env.subject_id,
        detail_keys=("role",),
    )


@on_event("account.role.revoked")
def audit_role_revoked(env: EventEnvelope) -> None:
    _record(
        env,
        "role.revoked",
        target_type="account",
        target_id=_payload(env).get("account_id") or env.subject_id,
        detail_keys=("role",),
    )


@on_event("capability.matrix.changed")
def audit_capability_changed(env: EventEnvelope) -> None:
    _record(
        env,
        "capability.changed",
        target_type="role",
        target_id=_payload(env).get("role") or env.subject_id,
        detail_keys=("capability", "state", "previous"),
    )


@on_event("moderation.actioned")
def audit_moderation_actioned(env: EventEnvelope) -> None:
    _record(
        env,
        "moderation.actioned",
        target_type=str(_payload(env).get("target_type") or "case"),
        target_id=_payload(env).get("target_id") or env.subject_id,
        detail_keys=("case_id", "action", "appeal_id"),
    )


@on_event("appeal.resolved")
def audit_appeal_resolved(env: EventEnvelope) -> None:
    _record(
        env,
        "appeal.resolved",
        target_type="appeal",
        target_id=_payload(env).get("appeal_id") or env.subject_id,
        detail_keys=("case_id", "target_type", "status", "reversal"),
    )


@on_event("ad.review.decided")
def audit_ad_review_decided(env: EventEnvelope) -> None:
    _record(
        env,
        "ad.review.decided",
        target_type="ad_creative",
        target_id=_payload(env).get("creative_id") or env.subject_id,
        detail_keys=("decision",),
    )
