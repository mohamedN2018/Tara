"""WP 3.1 / 3.3b: ``moderation.actioned`` on a user keeps ``intel_account_restriction``
(rule E11); ``reinstate`` lifts it; ``warn`` and ``dismiss`` change nothing."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

import intel.handlers  # noqa: F401 - registers the read-model handlers
from intel.models import AccountRestriction

from .helpers import acct, deliver, event

pytestmark = pytest.mark.django_db
T0 = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)


def act(account, action, minutes, case=None):
    payload = {
        "case_id": case or str(uuid.uuid4()),
        "target_type": "user",
        "target_id": account,
        "action": action,
    }
    deliver(
        event("moderation.actioned", payload, at=T0 + timedelta(minutes=minutes)),
        times=2,
        only_intel=True,
    )


@pytest.mark.parametrize("kind", ["restrict", "shadow"])
def test_restrict_and_shadow_are_stored(kind):
    a = acct()
    act(a, kind, 0)
    row = AccountRestriction.objects.get(account_id=a)
    assert (row.kind, row.active) == (kind, True)


def test_reinstate_lifts_it_and_an_older_replay_does_not_restore_it():
    a = acct()
    act(a, "shadow", 0)
    act(a, "reinstate", 10)
    act(a, "shadow", 5)  # the original action, redelivered late
    assert AccountRestriction.objects.get(account_id=a).active is False


def test_a_reinstate_seen_first_refuses_its_older_restriction():
    a = acct()
    act(a, "reinstate", 10)
    act(a, "restrict", 0)
    assert AccountRestriction.objects.get(account_id=a).active is False


def test_a_new_restriction_after_a_reinstate_applies():
    a = acct()
    act(a, "restrict", 0)
    act(a, "reinstate", 10)
    act(a, "shadow", 20)
    row = AccountRestriction.objects.get(account_id=a)
    assert (row.kind, row.active) == ("shadow", True)


@pytest.mark.parametrize("action", ["warn", "dismiss", "remove", "approve"])
def test_other_actions_on_a_user_change_nothing(action):
    a = acct()
    act(a, action, 0)
    assert not AccountRestriction.objects.filter(account_id=a).exists()
    act(a, "restrict", 1)
    act(a, action, 2)
    assert AccountRestriction.objects.get(account_id=a).active is True


def test_actions_on_other_targets_never_restrict_an_account():
    a = acct()
    deliver(
        event(
            "moderation.actioned",
            {
                "case_id": str(uuid.uuid4()),
                "target_type": "post",
                "target_id": a,
                "action": "restrict",
            },
            at=T0,
        ),
        only_intel=True,
    )
    assert not AccountRestriction.objects.exists()
