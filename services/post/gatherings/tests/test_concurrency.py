"""Capacity and reminders under real concurrency: separate threads, separate
connections, as in ``posts/tests/test_concurrency.py``."""

import threading
import time
import uuid
from datetime import timedelta

import pytest
from django.db import connection, transaction
from django.utils import timezone
from posts.models import OutboxEvent

from gatherings import services
from gatherings.models import Gathering, GatheringReminderLog, GatheringRSVP
from gatherings.tests.conftest import acct, make_event
from tara_common.exceptions import TaraAPIError

pytestmark = pytest.mark.django_db(transaction=True)

WAIT = 15  # seconds; generous, so a slow CI box does not flake


def test_two_rsvps_for_the_last_seat_never_both_win():
    """The first takes the seat inside an open transaction; the second must wait on
    the event's row lock, then sees the seat gone and gets ``event_full``."""
    g = make_event(acct(), capacity=1)
    first_guest, second_guest = acct(), acct()
    first_done, release = threading.Event(), threading.Event()
    out: dict = {"errors": []}

    def first():
        try:
            with transaction.atomic():
                services.rsvp(first_guest, g.id, "going")
                first_done.set()
                release.wait(WAIT)
        except Exception as exc:  # noqa: BLE001 - reported by the assertions
            out["errors"].append(exc)
            first_done.set()
        finally:
            connection.close()

    def second():
        try:
            first_done.wait(WAIT)
            services.rsvp(second_guest, g.id, "going")
            out["second"] = "won"
        except Exception as exc:  # noqa: BLE001 - reported by the assertions
            out["second_error"] = exc
        finally:
            connection.close()

    t1, t2 = threading.Thread(target=first), threading.Thread(target=second)
    t1.start()
    assert first_done.wait(WAIT)
    t2.start()
    time.sleep(0.5)  # the second is now blocked on the first's uncommitted lock
    assert t2.is_alive(), "the second RSVP did not wait for the lock"
    release.set()
    t1.join(WAIT)
    t2.join(WAIT)
    assert not t1.is_alive() and not t2.is_alive()
    assert not out["errors"], out["errors"]
    error = out.get("second_error")
    assert isinstance(error, TaraAPIError) and error.code == "event_full", out

    g.refresh_from_db()
    assert g.going_count == 1
    assert list(GatheringRSVP.objects.values_list("account_id", "status")) == [
        (uuid.UUID(first_guest), "going")
    ]
    assert OutboxEvent.objects.filter(event_type="gathering.rsvp").count() == 1


def test_a_crowd_racing_for_three_seats_fills_exactly_three():
    capacity, crowd = 3, 8
    g = make_event(acct(), capacity=capacity)
    start = threading.Barrier(crowd)
    results: list = []
    lock = threading.Lock()

    def guest():
        account = acct()
        try:
            start.wait(WAIT)
            services.rsvp(account, g.id, "going")
            outcome = "going"
        except TaraAPIError as exc:
            outcome = exc.code
        finally:
            connection.close()
        with lock:
            results.append(outcome)

    threads = [threading.Thread(target=guest) for _ in range(crowd)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(WAIT)
    assert sorted(results) == sorted(["going"] * capacity + ["event_full"] * (crowd - capacity))
    g = Gathering.objects.get(id=g.id)
    assert g.going_count == capacity
    assert GatheringRSVP.objects.filter(gathering=g, status="going").count() == capacity
    assert OutboxEvent.objects.filter(event_type="gathering.rsvp").count() == capacity


def test_two_reminder_runs_at_once_send_each_window_once():
    g = make_event(acct(), starts_at=timezone.now() + timedelta(minutes=40))
    for _ in range(3):
        services.rsvp(acct(), g.id, "going")
    start = threading.Barrier(2)
    sent: list = []

    def run():
        try:
            start.wait(WAIT)
            sent.append(services.send_due_reminders())
        finally:
            connection.close()

    threads = [threading.Thread(target=run) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(WAIT)
    assert sum(sent) == 1
    assert GatheringReminderLog.objects.filter(gathering=g).count() == 1
    assert OutboxEvent.objects.filter(event_type="gathering.reminder").count() == 1
