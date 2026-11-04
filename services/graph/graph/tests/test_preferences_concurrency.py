"""Review #8: preference writes for one owner are serialised, so concurrent
requests cannot break mute/favorite exclusion, the favorites cap, or a block."""

import threading
import uuid
from unittest import mock

import pytest
from django.db import connection

from graph import events, preferences, services
from graph.models import FavoriteRelation, MuteRelation, OutboxEvent
from tara_common.exceptions import TaraAPIError

pytestmark = pytest.mark.django_db(transaction=True)

#: How long the second writer gets to finish while the first one is paused.
#: With the lock it stays blocked; without it, it commits well inside this.
GRACE = 1.5


def _acct() -> str:
    return str(uuid.uuid4())


def _run(fn, *args):
    """Run ``fn`` in its own thread (own DB connection, own transaction)."""
    out: dict = {}

    def target():
        try:
            out["result"] = fn(*args)
        except Exception as exc:  # noqa: BLE001 - surfaced to the test
            out["error"] = exc
        finally:
            connection.close()

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    return thread, out


def _race(first, second, pause_on: str):
    """Start ``first`` and hold it open at ``pause_on`` (an event type just
    written to the outbox, or ``"on_block"`` once block() has run it): its
    writes are done but not committed. Run ``second`` meanwhile, then let both
    finish. Returns both outcomes and whether ``second`` had to wait."""
    paused, release = threading.Event(), threading.Event()
    real_emit, real_on_block = events.emit, preferences.on_block

    def hold_if(point):
        if point == pause_on and not paused.is_set():
            paused.set()
            assert release.wait(15), "test never released the first writer"

    def emit(event_type, *args, **kwargs):
        real_emit(event_type, *args, **kwargs)
        hold_if(event_type)

    def on_block(*args):
        real_on_block(*args)
        hold_if("on_block")

    with (
        mock.patch.object(events, "emit", side_effect=emit),
        mock.patch.object(preferences, "on_block", side_effect=on_block),
    ):
        t1, out1 = _run(*first)
        assert paused.wait(15), out1
        t2, out2 = _run(*second)
        t2.join(GRACE)
        second_blocked = t2.is_alive()
        release.set()
        t1.join(15)
        t2.join(15)
    assert not t1.is_alive() and not t2.is_alive()
    return out1, out2, second_blocked


def test_concurrent_mute_and_favorite_leave_only_the_last_one():
    me, other = _acct(), _acct()
    out1, out2, blocked = _race(
        (preferences.add, "mute", me, other),
        (preferences.add, "favorite", me, other),
        pause_on="relationship.muted",
    )
    assert out1 == {"result": True} and out2 == {"result": True}
    assert blocked, "the favorite did not wait for the mute's transaction"
    assert not MuteRelation.objects.filter(account_id=me, target_id=other).exists()
    assert FavoriteRelation.objects.filter(account_id=me, target_id=other).exists()
    types = list(OutboxEvent.objects.order_by("created_at").values_list("event_type", flat=True))
    assert types == ["relationship.muted", "relationship.unmuted", "relationship.favorited"]


def test_concurrent_favorites_cannot_pass_the_cap():
    me = _acct()
    FavoriteRelation.objects.bulk_create(
        FavoriteRelation(account_id=me, target_id=_acct())
        for _ in range(preferences.MAX_FAVORITES - 1)
    )
    out1, out2, _ = _race(
        (preferences.add, "favorite", me, _acct()),
        (preferences.add, "favorite", me, _acct()),
        pause_on="relationship.favorited",
    )
    assert out1 == {"result": True}
    assert isinstance(out2.get("error"), TaraAPIError)
    assert out2["error"].code == "favorites_limit"
    assert FavoriteRelation.objects.filter(account_id=me).count() == preferences.MAX_FAVORITES


def test_a_block_during_a_favorite_still_ends_the_favorite():
    me, other = _acct(), _acct()
    out1, out2, blocked = _race(
        (preferences.add, "favorite", me, other),
        (services.block, other, me),
        pause_on="relationship.favorited",
    )
    assert blocked, "the block did not wait for the favorite's transaction"
    assert out1 == {"result": True} and "error" not in out2
    assert not FavoriteRelation.objects.filter(account_id=me, target_id=other).exists()


def test_a_favorite_during_a_block_is_404():
    me, other = _acct(), _acct()
    out1, out2, blocked = _race(
        (services.block, other, me),
        (preferences.add, "favorite", me, other),
        pause_on="on_block",
    )
    assert blocked, "the favorite did not wait for the block's transaction"
    assert "error" not in out1
    assert isinstance(out2.get("error"), TaraAPIError)
    assert out2["error"].code == "not_found"
    assert not FavoriteRelation.objects.exists()
