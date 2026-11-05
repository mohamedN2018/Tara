"""An overturned restrict/shadow on an account (or page) reinstates it (intelligence WP 3.3b).

``reinstate`` means "no restriction stands on this target any more", so it is
emitted only when no other case's restrict/shadow on the same target still
stands, and never for content, warnings or a page removal.
"""

import json
import uuid
from pathlib import Path

import jsonschema
import pytest

from moderation import services
from moderation.models import Appeal, ModerationAuditLog, ModerationCase, OutboxEvent

pytestmark = pytest.mark.django_db

# The installed package carries no schemas; the image copies them here.
_SCHEMAS = Path("/opt/tara/libs/tara_events/tara_events/schemas")


def _acct() -> str:
    return str(uuid.uuid4())


def _decided(target_type: str, target_id: str, action: str) -> ModerationCase:
    case = services.ingest_report(
        reporter_id=_acct(), target_type=target_type, target_id=target_id, owner_id=target_id
    )
    services.take_action(str(case.id), _acct(), action)
    return case


def _overturn(case: ModerationCase) -> Appeal:
    appeal = services.file_appeal(str(case.id), str(case.owner_id), "please")
    return services.resolve_appeal(str(appeal.id), _acct(), "overturned")


def _actions() -> list[str]:
    rows = OutboxEvent.objects.filter(event_type="moderation.actioned").order_by("created_at", "id")
    return [r.payload["payload"]["action"] for r in rows]


def _schema(name: str) -> dict:
    if not _SCHEMAS.exists():
        pytest.skip("schemas are copied into the image at /opt/tara/libs")
    return json.loads((_SCHEMAS / f"{name}.v1.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("target_type", "action"), [("user", "restrict"), ("user", "shadow"), ("page", "restrict")]
)
def test_an_overturned_restriction_emits_reinstate(target_type, action):
    target = _acct()
    case = _decided(target_type, target, action)
    _overturn(case)

    assert _actions() == [action, "reinstate"]
    reversal = OutboxEvent.objects.filter(event_type="moderation.actioned").last()
    payload = reversal.payload["payload"]
    assert payload == {
        "case_id": str(case.id),
        "target_type": target_type,
        "target_id": target,
        "action": "reinstate",
        "owner_id": target,
    }
    jsonschema.validate(payload, _schema("moderation.actioned"))
    after = ModerationAuditLog.objects.get(case=case, action="appeal:overturned").after
    assert after == {"status": "overturned", "reversal": "reinstate"}
    resolved = OutboxEvent.objects.get(event_type="appeal.resolved")
    assert resolved.payload["payload"]["reversal"] == "reinstate"
    jsonschema.validate(resolved.payload["payload"], _schema("appeal.resolved"))


@pytest.mark.parametrize(("first", "second"), [("restrict", "shadow"), ("shadow", "restrict")])
def test_another_cases_restriction_keeps_the_account_restricted(first, second):
    # Consumers drop every restriction of the account on reinstate, so undoing
    # one case while another restrict or shadow stands must emit nothing.
    user = _acct()
    a = _decided("user", user, first)
    b = _decided("user", user, second)

    _overturn(a)
    assert _actions() == [first, second]
    after = ModerationAuditLog.objects.get(case=a, action="appeal:overturned").after
    assert after == {"status": "overturned", "reversal": None, "kept_by_case": str(b.id)}

    _overturn(b)
    assert _actions() == [first, second, "reinstate"]


def test_a_warning_on_the_account_does_not_keep_a_restriction():
    user = _acct()
    _decided("user", user, "warn")
    case = _decided("user", user, "restrict")
    _overturn(case)
    assert _actions() == ["warn", "restrict", "reinstate"]


def test_an_upheld_appeal_does_not_reinstate():
    user = _acct()
    case = _decided("user", user, "shadow")
    appeal = services.file_appeal(str(case.id), user, "please")
    services.resolve_appeal(str(appeal.id), _acct(), "upheld")
    assert _actions() == ["shadow"]


def test_the_flag_off_audits_the_overturn_and_emits_nothing(settings):
    settings.MODERATION_EMIT_REINSTATE = False
    user = _acct()
    case = _decided("user", user, "restrict")
    _overturn(case)
    assert _actions() == ["restrict"]
    after = ModerationAuditLog.objects.get(case=case, action="appeal:overturned").after
    assert after == {"status": "overturned", "reversal": None}


def test_reinstate_is_not_a_moderator_action():
    case = services.ingest_report(reporter_id=_acct(), target_type="user", target_id=_acct())
    with pytest.raises(services.TaraAPIError):
        services.take_action(str(case.id), _acct(), "reinstate")
