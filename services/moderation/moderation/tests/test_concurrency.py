"""Milestone 1.2 races, run as two real transactions on two connections.

The first transaction does its work and stays open; the second starts and has
to wait on the first's row lock or index entry; then the first commits.
"""

import threading
import time
import uuid

import pytest
from django.db import connection, transaction

from moderation import services
from moderation.models import Appeal, ModerationAction, ModerationCase, OutboxEvent, Report
from tara_common.exceptions import Conflict

pytestmark = pytest.mark.django_db(transaction=True)

WAIT = 15  # seconds; generous, so a slow CI box does not flake


def _acct() -> str:
    return str(uuid.uuid4())


def _race(first, second, hold: float = 0.5) -> dict:
    """Run ``first`` in an open transaction, then ``second``; commit ``first`` after ``hold``."""
    first_done, release = threading.Event(), threading.Event()
    out: dict = {"errors": []}

    def run_first():
        try:
            with transaction.atomic():
                out["first"] = first()
                first_done.set()
                release.wait(WAIT)
        except Exception as exc:  # noqa: BLE001 - reported by the assertions
            out["errors"].append(exc)
            first_done.set()
        finally:
            connection.close()

    def run_second():
        try:
            first_done.wait(WAIT)
            out["second"] = second()
        except Exception as exc:  # noqa: BLE001 - reported by the assertions
            out["second_error"] = exc
        finally:
            connection.close()

    t1 = threading.Thread(target=run_first)
    t2 = threading.Thread(target=run_second)
    t1.start()
    assert first_done.wait(WAIT)
    t2.start()
    time.sleep(hold)  # the second is now blocked on the first's uncommitted row
    release.set()
    t1.join(WAIT)
    t2.join(WAIT)
    assert not t1.is_alive() and not t2.is_alive(), "a transaction never finished"
    assert not out["errors"], out["errors"]
    return out


def test_two_concurrent_first_reports_open_one_case(monkeypatch):
    target = _acct()
    lookups: list[tuple[str, bool]] = []
    real_lookup = services._locked_open_case

    def spy(target_type, target_id):
        case = real_lookup(target_type, target_id)
        lookups.append((threading.current_thread().name, case is None))
        return case

    monkeypatch.setattr(services, "_locked_open_case", spy)

    def report():
        return services.ingest_report(reporter_id=_acct(), target_type="post", target_id=target)

    out = _race(report, report)

    assert "second_error" not in out, out.get("second_error")
    assert out["second"].id == out["first"].id
    case = ModerationCase.objects.get(target_type="post", target_id=target)
    assert case.report_count == 2
    assert Report.objects.filter(target_id=target).count() == 2
    # The second report saw no case, lost the insert, and joined on its retry.
    second_thread = [name for name, _ in lookups if name != lookups[0][0]]
    assert len(second_thread) == 2
    assert [empty for name, empty in lookups if name == second_thread[0]] == [True, False]


def test_two_concurrent_actions_emit_one_moderation_actioned():
    case = services.ingest_report(reporter_id=_acct(), target_type="post", target_id=_acct())

    out = _race(
        lambda: services.take_action(str(case.id), _acct(), "remove"),
        lambda: services.take_action(str(case.id), _acct(), "dismiss"),
    )

    assert isinstance(out.get("second_error"), Conflict)
    assert ModerationAction.objects.filter(case=case).count() == 1
    assert ModerationAction.objects.get(case=case).action == "remove"
    assert OutboxEvent.objects.filter(event_type="moderation.actioned").count() == 1


def test_assign_waits_for_a_concurrent_action_and_then_refuses():
    case = services.ingest_report(reporter_id=_acct(), target_type="post", target_id=_acct())

    out = _race(
        lambda: services.take_action(str(case.id), _acct(), "remove"),
        lambda: services.assign(str(case.id), _acct()),
    )

    assert isinstance(out.get("second_error"), Conflict)
    case.refresh_from_db()
    assert case.state == ModerationCase.State.RESOLVED
    assert case.assigned_to is None


def test_two_concurrent_overturns_on_one_target_restore_it_once():
    """Two cases removed one post; both appeals are overturned at the same time.

    Each overturn locks all of the target's cases, so the second waits, then
    sees the first's overturn and emits the single restore. Without that lock
    the second would read the first's appeal as still open, count its removal
    as standing, and the post would stay removed after both were overturned.
    """
    owner, post = _acct(), _acct()
    appeals = []
    for _ in range(2):
        case = services.ingest_report(
            reporter_id=_acct(), target_type="post", target_id=post, owner_id=owner
        )
        services.take_action(str(case.id), _acct(), "remove")
        appeals.append(services.file_appeal(str(case.id), owner, "please"))

    out = _race(
        lambda: services.resolve_appeal(str(appeals[0].id), _acct(), "overturned"),
        lambda: services.resolve_appeal(str(appeals[1].id), _acct(), "overturned"),
    )

    assert "second_error" not in out, out.get("second_error")
    assert set(Appeal.objects.values_list("status", flat=True)) == {Appeal.Status.OVERTURNED}
    actions = [
        e.payload["payload"]["action"]
        for e in OutboxEvent.objects.filter(event_type="moderation.actioned").order_by(
            "created_at", "id"
        )
    ]
    assert actions == ["remove", "remove", "approve"]


def test_two_concurrent_appeals_create_one():
    owner = _acct()
    case = services.ingest_report(
        reporter_id=_acct(), target_type="post", target_id=_acct(), owner_id=owner
    )
    services.take_action(str(case.id), _acct(), "remove")

    out = _race(
        lambda: services.file_appeal(str(case.id), owner, "first"),
        lambda: services.file_appeal(str(case.id), owner, "second"),
    )

    assert isinstance(out.get("second_error"), Conflict)
    assert Appeal.objects.filter(case=case).count() == 1
    assert OutboxEvent.objects.filter(event_type="appeal.created").count() == 1
