"""``manage.py intel_candidates`` (WP 3.4 / 3.6): one JSON line per viewer, each run
through retrieval and the eligibility filter, with its own age claims."""

import io
import json
import uuid

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

pytestmark = pytest.mark.django_db


def _run(*args) -> list[dict]:
    out = io.StringIO()
    call_command("intel_candidates", *args, stdout=out)
    return [json.loads(line) for line in out.getvalue().splitlines() if line.strip()]


def test_one_line_per_viewer_with_its_own_age_claims():
    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    rows = _run(a, f"{b}:adult", "--surface", "reels")
    assert [r["viewer"] for r in rows] == [a, b]
    assert [r["limited"] for r in rows] == [True, False]
    assert all(r["surface"] == "reels" and r["config"] == "reels@1" for r in rows)
    assert all(r["items"] == [] for r in rows)


def test_adult_flag_applies_to_every_viewer():
    (row,) = _run(str(uuid.uuid4()), "--adult")
    assert row["limited"] is False


@pytest.mark.parametrize("token", ["not-a-uuid", f"{uuid.uuid4()}:minor"])
def test_bad_viewers_are_refused(token):
    with pytest.raises(CommandError):
        _run(token)
