"""Intelligence WP 3.3 (D5): accounts that were inactive before graph consumed the
lifecycle events are backfilled from identity's export, newest-wins against the
events, and a complete scan marks active again what identity no longer lists."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest import mock

import pytest
from django.core.management import call_command

from graph import handlers, services
from graph.models import AccountRef

pytestmark = pytest.mark.django_db

AS_OF = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)


def _acct() -> str:
    return str(uuid.uuid4())


def _item(account_id: str, *, deactivated=False, suspended=False) -> dict:
    payload = {"account_id": account_id, "deactivated": deactivated, "suspended": suspended}
    return {"id": account_id, "payload": payload}


class _Resp:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        return None

    def json(self):
        return {"data": self._data}


def _run(pages: list[list[dict]], *args):
    responses = [
        _Resp(
            {
                "as_of": (AS_OF + timedelta(seconds=i)).isoformat(),
                "items": items,
                "next": items[-1]["id"] if i < len(pages) - 1 else None,
            }
        )
        for i, items in enumerate(pages)
    ]
    with mock.patch("requests.get", side_effect=responses) as get:
        call_command("intel_backfill_accounts", "--rate", "0", *args)
    return get


def _ref(account_id: str) -> AccountRef:
    return AccountRef.objects.get(account_id=account_id)


def test_listed_accounts_become_inactive_and_leave_fanout_and_suggestions():
    author, suspended, deactivated = _acct(), _acct(), _acct()
    for follower in (suspended, deactivated):
        services.follow(follower, author)

    get = _run([[_item(suspended, suspended=True)], [_item(deactivated, deactivated=True)]])

    assert get.call_count == 2
    assert get.call_args.kwargs["headers"]["Authorization"].startswith("Bearer ")
    assert get.call_args.args[0].endswith("/internal/v1/intel/export/accounts/")
    assert (_ref(suspended).suspended, _ref(suspended).active) == (True, False)
    assert (_ref(deactivated).deactivated, _ref(deactivated).active) == (True, False)
    assert services.inactive_among([author, suspended, deactivated]) == {suspended, deactivated}


def test_both_flags_are_kept_apart():
    account = _acct()
    _run([[_item(account, deactivated=True, suspended=True)]])
    ref = _ref(account)
    assert (ref.deactivated, ref.suspended, ref.active) == (True, True, False)
    # the suspension is lifted: the account is still deactivated
    handlers.set_lifecycle(account, "suspended", False, AS_OF + timedelta(hours=1))
    assert _ref(account).active is False


def test_a_newer_event_wins_over_the_export():
    account = _acct()
    handlers.set_lifecycle(account, "suspended", False, AS_OF + timedelta(minutes=5))  # lifted
    _run([[_item(account, suspended=True)]])
    assert _ref(account).active is True


def test_a_complete_scan_reactivates_what_identity_no_longer_lists():
    lost, still, recent = _acct(), _acct(), _acct()
    handlers.set_lifecycle(lost, "deactivated", True, AS_OF - timedelta(days=1))
    handlers.set_lifecycle(still, "suspended", True, AS_OF - timedelta(days=1))
    # deactivated after the export was read: the scan must not undo it
    handlers.set_lifecycle(recent, "deactivated", True, AS_OF + timedelta(minutes=1))

    _run([[_item(still, suspended=True)]])

    assert _ref(lost).active is True
    assert _ref(still).active is False
    assert _ref(recent).active is False


def test_no_sweep_keeps_unlisted_accounts_inactive():
    lost = _acct()
    handlers.set_lifecycle(lost, "deactivated", True, AS_OF - timedelta(days=1))
    _run([[]], "--no-sweep")
    assert _ref(lost).active is False


def test_rerunning_changes_nothing():
    account = _acct()
    _run([[_item(account, suspended=True)]])
    _run([[_item(account, suspended=True)]])
    assert _ref(account).active is False
    assert AccountRef.objects.filter(account_id=account).count() == 1


# ---- restrictions (moderation's export; rule E11, D14) ----------------------------


def _restriction(account_id: str, action: str = "restrict") -> dict:
    case_id = _acct()
    return {
        "id": case_id,
        "payload": {"account_id": account_id, "action": action, "case_id": case_id},
    }


def _run_restrictions(items: list[dict], *args):
    page = _Resp({"as_of": AS_OF.isoformat(), "items": items, "next": None})
    with mock.patch("requests.get", return_value=page) as get:
        call_command("intel_backfill_restrictions", "--rate", "0", *args)
    return get


def test_standing_restrictions_are_backfilled_and_lost_reinstates_swept():
    shadowed, lifted, recent = _acct(), _acct(), _acct()
    handlers.set_restriction(lifted, "restrict", None, AS_OF - timedelta(days=1))
    handlers.set_restriction(recent, "shadow", None, AS_OF + timedelta(minutes=1))

    get = _run_restrictions([_restriction(shadowed, "shadow"), _restriction(_acct(), "warn")])

    assert get.call_args.args[0].endswith("/internal/v1/intel/export/restrictions/")
    assert _ref(shadowed).restriction == "shadow"
    assert _ref(lifted).restriction == ""
    assert _ref(recent).restriction == "shadow"


def test_a_newer_reinstate_wins_over_the_restrictions_backfill():
    account = _acct()
    handlers.set_restriction(account, "reinstate", None, AS_OF + timedelta(minutes=1))
    _run_restrictions([_restriction(account)])
    assert _ref(account).restriction == ""


def test_restrictions_no_sweep_keeps_them():
    held = _acct()
    handlers.set_restriction(held, "restrict", None, AS_OF - timedelta(days=1))
    _run_restrictions([], "--no-sweep")
    assert _ref(held).restriction == "restrict"
