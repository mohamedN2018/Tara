"""07 WP 6.5-B2 (06 section 4.4): the session interest vector ``feed:si``.

- ingest folds consumption-grade events from the serve-token v2 attributes (topic,
  format, author prefix): no read; an open or a consumed dwell counts, an impression
  adds nothing, a dwell-only consumption counts ``dwell_only_weight`` (0.3) against
  1.0, a skip subtracts weakly; a hide (and a report) subtracts 1.0 in the consumer;
- the 20-minute half-life, ``min_events`` before ``session_rel`` moves anything;
- nothing is written under ``personalization_off``; sensitive topics not counted
  without the opt-in.
"""

import json
import time
import uuid
from datetime import timedelta

import pytest
from django.utils import timezone

from intel import config, hot, session_ctx
from intel.models import UserPreference
from intel.ranking import serve_tokens as st

from . import r4
from . import world as w
from .helpers import batch, ev

pytestmark = pytest.mark.django_db
URL = "/api/v1/feed/signals/"


def _block():
    return config.for_surface("home").section("session_interest")


def _vector(redis_hot, account):
    raw = hot.raw_client().hgetall(redis_hot.make_key(hot.session_interest_key(account)))
    return session_ctx.si_decode(raw, timezone.now(), _block())


def _send(client, *events):
    resp = client.post(
        URL,
        data=json.dumps(batch(*events, session=str(uuid.uuid4()))),
        content_type="application/json",
    )
    assert resp.status_code == 202, resp.content
    return resp.json()["data"]


def _token(me, post_id, topic_id, fmt="text", author=None):
    # Issued 5 minutes ago: a dwell can never exceed the time since the serve.
    return st.issue(
        me, "post", post_id, "home", reason="for_you", fmt=fmt, topic_id=topic_id,
        author_id=author or w.uid(), now=time.time() - 300,
    )  # fmt: skip


def test_ingest_folds_consumption_without_a_read(redis_hot, client_for):
    ids = r4.seed()
    me = w.uid()
    client = client_for(me)
    cooking = ids["cooking"]
    posts = [str(uuid.uuid4()) for _ in range(4)]
    _send(
        client,
        ev("feed_impression", f"post:{posts[0]}", st=_token(me, posts[0], cooking)),
        ev("post_open", f"post:{posts[1]}", st=_token(me, posts[1], cooking)),
        ev("feed_dwell", f"post:{posts[2]}", dwell_ms=30_000, st=_token(me, posts[2], cooking)),
    )
    v = _vector(redis_hot, me)
    # open 1.0 + dwell-only consumption 0.3; the impression added nothing.
    assert v["topic"][cooking] == pytest.approx(1.3, abs=0.01)
    assert v["n"] == 2 and v["format"]["text"] == pytest.approx(1.3, abs=0.01)


def test_half_life_and_min_events():
    block = _block()
    now = timezone.now()
    minute = session_ctx.si_minute(now)
    raw = {b"t:5": f"2.0:{minute - 20}".encode(), b"n": b"2"}
    v = session_ctx.si_decode(raw, now, block)
    assert v["topic"][5] == pytest.approx(1.0, abs=1e-3)  # one 20-minute half-life
    assert session_ctx.session_rel([(5, 1.0)], v, block) == 0.0  # 2 < min_events 3
    v["n"] = 3
    assert session_ctx.session_rel([(5, 1.0)], v, block) == pytest.approx(
        __import__("math").tanh(1.0 / 3.0), abs=1e-3
    )


def test_hide_subtracts_and_off_writes_nothing(redis_hot, client_for):
    ids = r4.seed()
    me, author = w.uid(), w.uid()
    p = w.post(author)
    w.feed_row(me, p, author)
    r4.tag(p, (ids["travel"], 0.9))
    client_for(me).post("/api/v1/feed/hide/", {"post_id": p, "reason": "not_interested"})
    v = _vector(redis_hot, me)
    assert v["topic"][ids["travel"]] == pytest.approx(-1.0, abs=0.01)
    off = w.uid()
    UserPreference.objects.create(account_id=off, personalization_off=True)
    q = str(uuid.uuid4())
    _send(client_for(off), ev("post_open", f"post:{q}", st=_token(off, q, ids["travel"])))
    assert not hot.raw_client().exists(redis_hot.make_key(hot.session_interest_key(off)))


def test_sensitive_topic_is_not_counted_without_opt_in(redis_hot, client_for):
    ids = r4.seed()
    me, opted = w.uid(), w.uid()
    UserPreference.objects.create(account_id=opted, sensitive_inference=True)
    for account in (me, opted):
        p = str(uuid.uuid4())
        _send(
            client_for(account), ev("post_open", f"post:{p}", st=_token(account, p, ids["quran"]))
        )
    assert ids["quran"] not in _vector(redis_hot, me)["topic"]
    assert _vector(redis_hot, me)["n"] == 1  # the event counted, its topic did not
    assert _vector(redis_hot, opted)["topic"][ids["quran"]] == pytest.approx(1.0, abs=0.01)
    _ = timedelta
