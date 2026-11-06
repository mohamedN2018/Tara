"""System-sourced cases from feed's ``intel.integrity.flagged`` (Tara Intelligence WP 7.4).

Choice recorded in docs/intelligence/results/r4-track-b.md: a ``source`` column on
``report`` (``user`` | ``system``) plus a reserved nil reporter id, so the migration
is additive (``reporter_id`` stays NOT NULL) and the API shows ``reporter_id: null``.
"""

from __future__ import annotations

import dataclasses
import uuid

import pytest
from django.urls import reverse

from moderation.handlers import on_integrity_flagged, on_post_reported
from moderation.models import SYSTEM_REPORTER_ID, ModerationCase, Report
from tara_events.envelope import EventEnvelope

pytestmark = pytest.mark.django_db


def _acct() -> str:
    return str(uuid.uuid4())


def _flag(post_id: str, author_id: str, signal: str = "spam_hides", event_id=None):
    envelope = EventEnvelope(
        event_type="intel.integrity.flagged",
        subject_id=post_id,
        producer="feed-service",
        payload={
            "post_id": post_id,
            "author_id": author_id,
            "signal": signal,
            "rate": 0.4,
            "distinct_accounts": 6,
        },
    )
    if event_id:
        envelope = dataclasses.replace(envelope, event_id=event_id)
    on_integrity_flagged(envelope)
    return envelope


def _user_report(post_id: str, reporter: str):
    on_post_reported(
        EventEnvelope(
            event_type="post.reported",
            subject_id=post_id,
            producer="post-service",
            payload={"post_id": post_id, "reporter": reporter, "reason": "spam"},
        )
    )


def test_flag_opens_one_system_case_without_a_reporter(client_for):
    post_id, author = _acct(), _acct()
    _flag(post_id, author)
    cases = ModerationCase.objects.filter(target_type="post", target_id=post_id)
    assert cases.count() == 1
    case = cases.get()
    assert case.system_signal == "spam_hides"
    assert case.report_count == 0  # user report counts are unaffected
    assert str(case.owner_id) == author
    report = Report.objects.get(target_id=post_id)
    assert report.source == Report.Source.SYSTEM
    assert str(report.reporter_id) == SYSTEM_REPORTER_ID
    assert report.evidence == {"signal": "spam_hides", "rate": 0.4, "distinct_accounts": 6}

    staff = client_for(_acct(), roles=["moderator"])
    body = staff.get(reverse("moderation:reports"), {"case": str(case.id)}).json()
    assert [r["source"] for r in body["data"]] == ["system"]
    assert body["data"][0]["reporter_id"] is None  # never shown as a person
    listed = staff.get(reverse("moderation:cases")).json()["data"]
    row = next(c for c in listed if c["id"] == str(case.id))
    assert row["system_signal"] == "spam_hides"
    assert row["report_count"] == 0


def test_redelivery_and_a_second_flag_add_nothing():
    post_id, author = _acct(), _acct()
    first = _flag(post_id, author)
    _flag(post_id, author, event_id=first.event_id)  # redelivery
    _flag(post_id, author, signal="sexual_hides")  # a later flag on the same open case
    assert ModerationCase.objects.filter(target_id=post_id).count() == 1
    assert Report.objects.filter(target_id=post_id).count() == 1
    assert ModerationCase.objects.get(target_id=post_id).system_signal == "spam_hides"


def test_a_user_report_joins_the_same_case_and_counts_alone(client_for):
    post_id, author, reporter, other = _acct(), _acct(), _acct(), _acct()
    _flag(post_id, author)
    _user_report(post_id, reporter)
    _user_report(other, reporter)  # another post: its own case
    case = ModerationCase.objects.get(target_type="post", target_id=post_id)
    assert case.report_count == 1  # only the person counts
    assert Report.objects.filter(target_id=post_id).count() == 2
    mine = client_for(reporter).get(reverse("moderation:my-reports")).json()["data"]
    # Their own two reports, never the system one.
    assert sorted(r["target_id"] for r in mine) == sorted([post_id, other])


def test_user_case_first_then_flag_joins_it():
    post_id, author, reporter = _acct(), _acct(), _acct()
    _user_report(post_id, reporter)
    _flag(post_id, author)
    case = ModerationCase.objects.get(target_type="post", target_id=post_id)
    assert case.report_count == 1
    assert case.system_signal == "spam_hides"
    assert Report.objects.filter(target_id=post_id, source="system").count() == 1


def test_system_report_is_absent_from_every_my_reports(client_for):
    post_id = _acct()
    _flag(post_id, _acct())
    # Nobody owns the nil reporter id; a token for it still sees nothing.
    for who in (_acct(), SYSTEM_REPORTER_ID):
        assert client_for(who).get(reverse("moderation:my-reports")).json()["data"] == []


def test_malformed_flag_is_dropped():
    on_integrity_flagged(
        EventEnvelope(
            event_type="intel.integrity.flagged",
            subject_id="x",
            producer="feed-service",
            payload={"post_id": "not-a-uuid", "signal": "spam_hides"},
        )
    )
    on_integrity_flagged(
        EventEnvelope(
            event_type="intel.integrity.flagged",
            subject_id="x",
            producer="feed-service",
            payload={"post_id": _acct(), "signal": "other"},
        )
    )
    assert ModerationCase.objects.count() == 0


def test_resolved_case_then_new_flag_opens_a_new_case(client_for):
    post_id, author = _acct(), _acct()
    _flag(post_id, author)
    case = ModerationCase.objects.get(target_id=post_id)
    staff = client_for(_acct(), roles=["moderator"])
    resp = staff.post(
        reverse("moderation:case-action", args=[case.id]), {"action": "approve"}, format="json"
    )
    assert resp.status_code in (200, 201), resp.content
    _flag(post_id, author)
    assert ModerationCase.objects.filter(target_id=post_id).count() == 2
    assert Report.objects.filter(target_id=post_id, source="system").count() == 2
