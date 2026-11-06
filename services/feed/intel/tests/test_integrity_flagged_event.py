"""04 WP 7.4: ``intel.integrity.flagged.v1`` when spam or sexual hides of a post cross
``integrity.spam_flag_rate_threshold`` from at least ``integrity.flag_min_accounts``
accounts; at most once per post and signal per ``flag_cooldown_h``; no hider named;
off with ``INTEL_EMIT_R4_EVENTS``."""

import json
from datetime import timedelta
from pathlib import Path

import pytest
from django.utils import timezone
from feed.models import OutboxEvent

from intel import integrity_flags
from intel.models import IntegrityFlag

from . import world as w

pytestmark = pytest.mark.django_db
SCHEMA = Path("/opt/tara/libs/tara_events/tara_events/schemas/intel.integrity.flagged.v1.json")


def _events():
    return [
        e.payload["payload"]
        for e in OutboxEvent.objects.filter(event_type="intel.integrity.flagged")
    ]


def _hide_by(n, post_id, author, client_for, reason="spam"):
    for _ in range(n):
        viewer = w.uid()
        w.feed_row(viewer, post_id, author)
        client_for(viewer).post("/api/v1/feed/hide/", {"post_id": post_id, "reason": reason})


def test_crossing_the_threshold_emits_once_per_cooldown(client_for, settings):
    author = w.uid()
    p = w.post(author)
    _hide_by(2, p, author, client_for)
    assert _events() == []  # 2 accounts < flag_min_accounts 3
    _hide_by(1, p, author, client_for)
    events = _events()
    assert len(events) == 1
    assert events[0] == {
        "post_id": p,
        "author_id": author,
        "signal": "spam_hides",
        "rate": 1.0,
        "distinct_accounts": 3,
    }
    _hide_by(2, p, author, client_for)
    assert len(_events()) == 1  # inside the 24 h cooldown
    IntegrityFlag.objects.filter(post_id=p).update(flagged_at=timezone.now() - timedelta(hours=25))
    _hide_by(1, p, author, client_for)
    assert len(_events()) == 2
    if SCHEMA.exists():
        jsonschema = pytest.importorskip("jsonschema")
        spec = json.loads(SCHEMA.read_text(encoding="utf-8"))
        for e in _events():
            jsonschema.validate(e, spec)


def test_below_the_rate_or_other_reasons_or_flag_off_emit_nothing(client_for, settings):
    author = w.uid()
    p = w.post(author)
    for _ in range(400):  # a large reach: 3 spam hides is a rate far below the threshold
        w.feed_row(w.uid(), p, author)
    _hide_by(3, p, author, client_for)
    q = w.post(author)
    _hide_by(3, q, author, client_for, reason="annoying")
    assert _events() == []
    settings.INTEL_EMIT_R4_EVENTS = False
    r = w.post(author)
    _hide_by(3, r, author, client_for, reason="sexual")
    assert _events() == []
    assert integrity_flags.check(r, author, "sexual") is False
