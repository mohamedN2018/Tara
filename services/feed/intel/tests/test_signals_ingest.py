"""WP 2.3: ``POST /api/v1/feed/signals/`` (schema, clamps, dedupe, attribution, origin)."""

import json
import time
import uuid
from datetime import timedelta

import pytest
from django.utils import timezone

from intel.models import SignalFlag, SyntheticAccount
from intel.ranking import serve_tokens as st
from intel.signals import validate

from .helpers import acct, batch, ev, signal_rows

pytestmark = pytest.mark.django_db
URL = "/api/v1/feed/signals/"


def _post(client, body):
    return client.post(URL, data=json.dumps(body), content_type="application/json")


def _send(client_for, account, *events, **kw):
    return _post(client_for(account), batch(*events, **kw))


def test_auth_required():
    from rest_framework.test import APIClient

    resp = _post(APIClient(), batch(ev("post_open", f"post:{uuid.uuid4()}")))
    assert resp.status_code in (401, 403)


def test_valid_batch_is_stored(client_for):
    me, post = acct(), str(uuid.uuid4())
    resp = _send(
        client_for,
        me,
        ev("feed_impression", f"post:{post}", pos=2),
        ev("post_open", f"post:{post}"),
    )
    assert resp.status_code == 202
    assert resp.json()["data"] == {"accepted": 2, "duplicate": False, "rejected": {}}
    rows = sorted(signal_rows(account_id=me), key=lambda r: r["event_type"])
    assert [r["event_type"] for r in rows] == ["feed_impression", "post_open"]
    assert all(r["source"] == "client" and r["data_origin"] == "real" for r in rows)
    assert str(rows[0]["item_id"]) == post and rows[0]["item_type"] == "post"
    # No PII beyond ids: the table has no ip, user agent or free-text column.
    assert not {"ip", "user_agent", "text"} & set(rows[0])


def test_unknown_and_server_only_types_are_rejected(client_for):
    me, item = acct(), f"post:{uuid.uuid4()}"
    resp = _send(
        client_for,
        me,
        ev("made_up", item),
        ev("post_like", item),
        ev("follow", f"profile:{uuid.uuid4()}"),
        ev("post_open", item),
    )
    assert resp.json()["data"]["rejected"] == {"server_only": 2, "unknown_type": 1}
    assert [r["event_type"] for r in signal_rows(account_id=me)] == ["post_open"]


def test_malformed_items_and_fields_are_rejected(client_for):
    me = acct()
    resp = _send(
        client_for,
        me,
        ev("post_open", "post:not-a-uuid"),
        ev("post_open", f"spaceship:{uuid.uuid4()}"),
        ev("post_open", f"post:{uuid.uuid4()}", data_origin="synthetic"),
        ev("video_progress", f"video:{uuid.uuid4()}", watch_ms=10),  # pos_ms missing
        ev("profile_visit", f"post:{uuid.uuid4()}"),  # wrong item kind
    )
    rejected = resp.json()["data"]["rejected"]
    assert rejected == {"item": 2, "unknown_field": 1, "missing_field": 1, "item_type": 1}
    assert signal_rows(account_id=me) == []


def test_unknown_top_level_field_refuses_the_batch(client_for):
    body = batch(ev("post_open", f"post:{uuid.uuid4()}"))
    body["data_origin"] = "synthetic"
    assert _post(client_for(acct()), body).status_code == 400


def test_same_batch_twice_gives_one_set_of_rows(client_for):
    me = acct()
    body = batch(ev("post_open", f"post:{uuid.uuid4()}"), ev("post_open", f"post:{uuid.uuid4()}"))
    first = _post(client_for(me), body).json()["data"]
    again = _post(client_for(me), body).json()["data"]
    assert first["accepted"] == 2 and not first["duplicate"]
    assert again == {"accepted": 0, "duplicate": True, "rejected": {}}
    assert len(signal_rows(account_id=me)) == 2
    # Another account may reuse the id: dedupe is per account.
    other = _post(client_for(acct()), body).json()["data"]
    assert other["accepted"] == 2


def test_fifty_event_cap(client_for):
    events = [ev("post_open", f"post:{uuid.uuid4()}") for _ in range(51)]
    assert _send(client_for, acct(), *events).status_code == 400
    assert _send(client_for, acct(), *events[:50]).status_code == 202


def test_body_over_32kb_is_refused(client_for):
    big = batch(ev("post_open", f"post:{uuid.uuid4()}", st="x" * 500))
    big["events"] *= 50
    raw = json.dumps(big)
    assert len(raw) > validate.MAX_BATCH_BYTES
    resp = client_for(acct()).post(URL, data=raw, content_type="application/json")
    assert resp.status_code == 413


def test_ts_is_clamped_to_receive_time(client_for):
    me = acct()
    _send(
        client_for,
        me,
        ev("post_open", f"post:{uuid.uuid4()}", ts=timezone.now() + timedelta(days=3)),
        ev("post_open", f"post:{uuid.uuid4()}", ts=timezone.now() - timedelta(hours=2)),
    )
    kept, clamped = sorted(signal_rows(account_id=me), key=lambda r: r["occurred_at"])
    assert clamped["flags"] & SignalFlag.TS_CLAMPED
    assert clamped["occurred_at"] == clamped["received_at"]
    assert not kept["flags"] & SignalFlag.TS_CLAMPED
    assert kept["received_at"] - kept["occurred_at"] > timedelta(hours=1)


def test_watch_ms_is_clamped(client_for):
    """A play already watched to the ceiling (earlier, honestly) cannot report more."""
    from intel.signals import store

    me, item_id, session = acct(), uuid.uuid4(), uuid.uuid4()
    ceiling = validate.watch_ceiling_ms(None)
    earlier = timezone.now() - timedelta(minutes=5)
    for event_type, watch in (("video_start", None), ("video_progress", ceiling)):
        store.insert_row(
            store.SignalRow(
                account_id=me,
                event_type=event_type,
                item_type="video",
                item_id=item_id,
                source="client",
                data_origin="real",
                occurred_at=earlier,
                received_at=earlier,
                session_id=session,
                watch_ms=watch,
                play_index=1,
            )
        )
    data = _send(
        client_for,
        me,
        ev("video_progress", f"video:{item_id}", watch_ms=ceiling + 50_000, pos_ms=1),
        session=str(session),
    ).json()["data"]
    assert data["accepted"] == 1
    row = signal_rows(account_id=me)[-1]
    assert row["watch_ms"] == ceiling and row["flags"] & SignalFlag.WATCH_CLAMPED


def test_watch_overclaim_is_dropped(client_for):
    me, item, session = acct(), f"reel:{uuid.uuid4()}", str(uuid.uuid4())
    events = [ev("video_start", item, play_index=1)]
    # 5 s steps up to 100 s claimed at once: only 66 s (60 s + 10 %) fit the window.
    events += [
        ev("video_progress", item, watch_ms=ms, pos_ms=ms) for ms in range(5000, 100_001, 5000)
    ]
    data = _send(client_for, me, *events, session=session).json()["data"]
    kept = [r for r in signal_rows(account_id=me) if r["event_type"] == "video_progress"]
    assert max(r["watch_ms"] for r in kept) <= 66_000
    assert data["rejected"]["watch_overclaim"] == 20 - len(kept)
    # The next batch in the same window cannot claim more either.
    more = _send(
        client_for, me, ev("video_progress", item, watch_ms=70_000, pos_ms=1), session=session
    ).json()["data"]
    assert more["rejected"] == {"watch_overclaim": 1}


def test_honest_watching_is_accepted(client_for):
    me, item, session = acct(), f"video:{uuid.uuid4()}", str(uuid.uuid4())
    data = _send(
        client_for,
        me,
        ev("video_start", item, play_index=1),
        ev("video_progress", item, watch_ms=5000, pos_ms=5000),
        ev("video_progress", item, watch_ms=10_000, pos_ms=10_000),
        session=session,
    ).json()["data"]
    assert data == {"accepted": 3, "duplicate": False, "rejected": {}}


def test_complete_needs_a_start_and_rewatch_needs_a_complete(client_for):
    me, item, session = acct(), f"video:{uuid.uuid4()}", str(uuid.uuid4())
    first = _send(
        client_for,
        me,
        ev("video_complete", item, watch_ms=3000),
        ev("video_rewatch", item, play_index=2),
        session=session,
    ).json()["data"]
    assert first["rejected"] == {"complete_without_start": 1, "rewatch_without_complete": 1}
    _send(client_for, me, ev("video_start", item, play_index=1), session=session)
    second = _send(
        client_for,
        me,
        ev("video_complete", item, watch_ms=3000),
        ev("video_rewatch", item, play_index=2),
        session=session,
    ).json()["data"]
    assert second == {"accepted": 2, "duplicate": False, "rejected": {}}
    # Another session has no start for it.
    other = _send(client_for, me, ev("video_complete", item, watch_ms=3000)).json()["data"]
    assert other["rejected"] == {"complete_without_start": 1}


def test_skip_and_reel_view_rules(client_for):
    me, reel = acct(), f"reel:{uuid.uuid4()}"
    data = _send(
        client_for,
        me,
        ev("video_skip", reel, watch_ms=1500),
        ev("video_skip", reel, watch_ms=2500),
        ev("reel_view", reel, watch_ms=900),
        ev("video_rewatch", reel, play_index=1),
    ).json()["data"]
    assert data["accepted"] == 1
    assert data["rejected"] == {"invalid_skip": 1, "short_view": 1, "invalid_rewatch": 1}


def test_valid_serve_token_attributes_the_row(client_for):
    me, post = acct(), str(uuid.uuid4())
    token = st.issue(
        me,
        "post",
        post,
        "home",
        position=7,
        cfg_version="home@1",
        variant="b",
        source="friend",
        reason="for_you",
        scores=st.quantize([0.5, 0.25]),
    )
    _send(client_for, me, ev("feed_impression", f"post:{post}", pos=99, st=token))
    row = signal_rows(account_id=me)[0]
    assert row["attributed"] is True
    assert (row["surface"], row["position"], row["cfg_version"], row["variant"]) == (
        "home",
        7,
        "home@1",
        "b",
    )
    assert row["rank_source"] == "friend"
    assert bytes(row["pred"]) == st.quantize([0.5, 0.25])
    assert row["flags"] == 0


def test_forged_or_foreign_token_is_unattributed(client_for):
    me, post = acct(), str(uuid.uuid4())
    foreign = st.issue(acct(), "post", post, "home", cfg_version="home@1", variant="b")
    other_item = st.issue(me, "post", str(uuid.uuid4()), "home", cfg_version="home@1")
    _send(
        client_for,
        me,
        ev("post_open", f"post:{post}", st=foreign),
        ev("post_open", f"post:{post}", st=other_item),
        ev("post_open", f"post:{post}", st="forged"),
    )
    rows = signal_rows(account_id=me)
    assert len(rows) == 3
    for row in rows:
        assert row["attributed"] is False
        assert row["cfg_version"] is None and row["variant"] is None
        assert row["flags"] & SignalFlag.INELIGIBLE_ITEM


def test_client_cfg_and_variant_are_ignored(client_for):
    me = acct()
    body = batch(ev("post_open", f"post:{uuid.uuid4()}", cfg="home@9", variant="treatment"))
    body["cfg"], body["variant"] = "home@9", "treatment"
    assert _post(client_for(me), body).json()["data"]["accepted"] == 1
    row = signal_rows(account_id=me)[0]
    assert row["cfg_version"] is None and row["variant"] is None and row["attributed"] is False


def test_unattributed_surface_hint_is_limited(client_for):
    me = acct()
    _send(
        client_for,
        me,
        ev("post_open", f"post:{uuid.uuid4()}", surface="profile"),
        ev("post_open", f"post:{uuid.uuid4()}", surface="home"),
    )
    surfaces = sorted(str(r["surface"]) for r in signal_rows(account_id=me))
    assert surfaces == ["None", "profile"]


@pytest.mark.parametrize(
    ("label", "accept", "expected"),
    [
        (None, True, "real"),
        ("seed-2026-11", True, "synthetic"),
        ("test-integration", True, "test"),
        ("seed-2026-11", False, None),
    ],
)
def test_data_origin_comes_from_the_registry_only(client_for, settings, label, accept, expected):
    from intel import origin

    settings.INTEL_ACCEPT_SYNTHETIC = accept
    me = acct()
    if label:
        SyntheticAccount.objects.create(account_id=me, label=label)
        origin.clear_cache()
    data = _send(client_for, me, ev("post_open", f"post:{uuid.uuid4()}")).json()["data"]
    rows = signal_rows(account_id=me)
    if expected is None:
        assert rows == [] and data["rejected"] == {"synthetic_not_accepted": 1}
    else:
        assert [r["data_origin"] for r in rows] == [expected]


def test_impression_without_position_is_kept(client_for):
    """A card seen off a ranked surface (a profile, a group) has no feed position;
    a served one takes its position from the token, never from the client."""
    me, post, served = acct(), str(uuid.uuid4()), str(uuid.uuid4())
    token = st.issue(me, "post", served, "home", reason="recent")  # chronological: no position
    data = _send(
        client_for,
        me,
        ev("feed_impression", f"post:{post}", surface="profile"),
        ev("feed_impression", f"post:{served}", st=token, pos=3),
    ).json()["data"]
    assert data == {"accepted": 2, "duplicate": False, "rejected": {}}
    rows = {str(r["item_id"]): r for r in signal_rows(account_id=me)}
    assert rows[post]["position"] is None and rows[post]["surface"] == "profile"
    assert rows[post]["attributed"] is False
    assert rows[served]["attributed"] is True and rows[served]["position"] is None


# ---- R3 WP 4b.2: feed_dwell ------------------------------------------------------------


def test_feed_dwell_is_stored_with_its_dwell(client_for):
    me, post = acct(), str(uuid.uuid4())
    token = st.issue(me, "post", post, "home", reason="recent", now=time.time() - 120)
    data = _send(client_for, me, ev("feed_dwell", f"post:{post}", st=token, dwell_ms=4_200)).json()[
        "data"
    ]
    assert data == {"accepted": 1, "duplicate": False, "rejected": {}}
    row = signal_rows(account_id=me)[0]
    assert (row["event_type"], row["watch_ms"], row["attributed"]) == ("feed_dwell", 4_200, True)


def test_feed_dwell_over_the_wall_clock_is_dropped(client_for):
    me = acct()
    young, old = str(uuid.uuid4()), str(uuid.uuid4())
    # Served 10 s ago: 60 s of dwell is impossible.
    token = st.issue(me, "post", young, "home", reason="recent", now=time.time() - 10)
    data = _send(
        client_for,
        me,
        ev("feed_dwell", f"post:{young}", st=token, dwell_ms=60_000),
        ev("feed_dwell", f"post:{old}", dwell_ms=validate.MAX_DWELL_MS + 1),  # > 10 min
        ev("feed_dwell", f"post:{uuid.uuid4()}", dwell_ms=validate.MAX_DWELL_MS),
    ).json()["data"]
    assert data["accepted"] == 1
    assert data["rejected"] == {"dwell_overclaim": 2}


def test_feed_dwell_once_per_item_in_a_batch(client_for):
    me, post = acct(), f"post:{uuid.uuid4()}"
    data = _send(
        client_for,
        me,
        ev("feed_dwell", post, dwell_ms=2_000),
        ev("feed_dwell", post, dwell_ms=9_000),
    ).json()["data"]
    assert (data["accepted"], data["rejected"]) == (1, {"duplicate_dwell": 1})
    assert [r["watch_ms"] for r in signal_rows(account_id=me)] == [2_000]


def test_feed_dwell_shape(client_for):
    me = acct()
    data = _send(
        client_for,
        me,
        ev("feed_dwell", f"post:{uuid.uuid4()}"),  # dwell_ms missing
        ev("feed_dwell", f"profile:{uuid.uuid4()}", dwell_ms=10),  # not a post kind
        ev("post_open", f"post:{uuid.uuid4()}", dwell_ms=10),  # field of another type
    ).json()["data"]
    assert data["accepted"] == 0
    assert data["rejected"] == {"missing_field": 1, "item_type": 1, "unknown_field": 1}
