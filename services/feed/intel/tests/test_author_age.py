"""WP 4b.14: the author age class comes from the account's own token claims on its feed
requests, maps like ``Viewer.limited``, is written once per change (a redis-hot memo
makes the steady state free), never stores a date of birth, and is captured whatever
the personalization setting."""

from unittest import mock

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from feed.models import AuthorRef

from intel import age, hot
from intel.models import UserPreference

from . import world as w
from .helpers import client_with_claims

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    ("claims", "expected"),
    [
        ({"is_minor": False, "age_band": "25-34"}, "adult"),
        ({"is_minor": False, "age_band": "18-24"}, "adult"),
        ({"is_minor": False, "age_band": "45+"}, "adult"),
        ({"is_minor": True, "age_band": "13-17"}, "minor"),
        ({"is_minor": True}, "minor"),
        ({"is_minor": False, "age_band": "unknown"}, "unknown"),
        ({"is_minor": False}, "unknown"),
        ({"age_band": "25-34"}, "unknown"),  # no is_minor claim: not proven adult
        ({}, "unknown"),
        (None, "unknown"),
    ],
)
def test_claims_map_to_a_class(claims, expected):
    assert age.class_of(claims) == expected


def _class(account):
    return AuthorRef.objects.filter(account_id=account).values_list("age_class", flat=True).first()


def _writes(ctx):
    return [
        q["sql"]
        for q in ctx.captured_queries
        if q["sql"].lstrip().upper().startswith(("UPDATE", "INSERT"))
    ]


def test_first_capture_creates_the_row_and_changes_update_it():
    me = w.uid()
    assert age.capture(me, {"is_minor": True}) == "minor"
    assert _class(me) == "minor"
    age.capture(me, {"is_minor": False, "age_band": "25-34"})
    assert _class(me) == "adult"
    # Only the class: no date of birth, no band, nothing else from the token.
    cols = {f.name for f in AuthorRef._meta.get_fields()}
    assert not {"dob", "date_of_birth", "birth_date", "age_band"} & cols


def test_an_existing_author_row_keeps_its_other_fields():
    me = w.uid()
    w.author(me, active=False, searchable=False)
    age.capture(me, {"is_minor": False, "age_band": "35-44"})
    row = AuthorRef.objects.get(account_id=me)
    assert (row.age_class, row.active, row.searchable) == ("adult", False, False)


def test_one_write_on_change_and_none_in_steady_state(redis_hot):
    me = w.uid()
    adult = {"is_minor": False, "age_band": "25-34"}
    with CaptureQueriesContext(connection) as first:
        age.capture(me, adult)
    assert len(_writes(first)) == 1  # the insert
    with CaptureQueriesContext(connection) as steady:
        for _ in range(5):
            age.capture(me, adult)
    assert steady.captured_queries == []  # the memo answers: no SQL at all
    with CaptureQueriesContext(connection) as change:
        age.capture(me, {"is_minor": True})
    assert len(_writes(change)) == 1 and _class(me) == "minor"
    memo = hot.raw_client().get(redis_hot.make_key(hot.age_key(me)))
    assert memo == b"minor"


def test_a_lost_memo_costs_one_read_and_no_write():
    me = w.uid()
    age.capture(me, {"is_minor": True})
    # No redis-hot raw client in this test (local memory cache): every call re-checks.
    with CaptureQueriesContext(connection) as ctx:
        age.capture(me, {"is_minor": True})
    reads = [q for q in ctx.captured_queries if q["sql"].lstrip().upper().startswith("SELECT")]
    assert _writes(ctx) == [] and len(reads) == 1
    assert AuthorRef.objects.filter(account_id=me).count() == 1


def test_captured_on_feed_requests_even_with_personalization_off():
    me = w.uid()
    UserPreference.objects.create(account_id=me, personalization_off=True)
    client = client_with_claims(me, is_minor=True, age_band="13-17")
    assert client.get("/api/v1/feed/").status_code == 200
    assert _class(me) == "minor"
    adult = client_with_claims(me, is_minor=False, age_band="25-34")
    assert adult.get("/api/v1/feed/", {"mode": "for_you"}).status_code == 200
    assert _class(me) == "adult"


def test_a_failed_write_never_fails_the_feed(client_for):
    me = w.uid()
    with mock.patch.object(age, "store", side_effect=RuntimeError("db down")):
        assert client_for(me).get("/api/v1/feed/", {"mode": "for_you"}).status_code == 200
    assert age.capture(me, {}) == "unknown"
