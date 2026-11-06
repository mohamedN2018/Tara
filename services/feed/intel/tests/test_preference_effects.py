"""04 WP 8.3: each My Algorithm control has a measurable effect in ranking (one case
per control and per discovery toggle). Those whose effect lives outside feed's Home
ranking (people, page and group suggestions) are stored and served for graph,
profile and the web to honour, and change nothing here."""

from datetime import timedelta

import pytest
from feed import ranking
from feed.models import ReactionState

from intel import config, discovery, eligibility, preferences
from intel.ranking import home
from intel.ranking.personal import Personal

from . import variants
from . import world as w
from .helpers import ADULT_CLAIMS, client_with_claims

pytestmark = pytest.mark.django_db
ADULT = {"is_minor": False, "age_band": "25-34"}


def _connections(viewer, n, *, video_every=0):
    for i in range(n):
        f = w.uid()
        kind = "video" if video_every and i % video_every == 0 else "text"
        w.feed_row(viewer, w.post(f, type=kind, age=timedelta(minutes=5 + 4 * i)), f, type=kind)


def _pool(n, *, lang="en", minutes=0):
    out = []
    for i in range(n):
        p = w.post(w.uid(), lang=lang, age=timedelta(hours=1, minutes=minutes + i))
        ReactionState.objects.create(post_id=p, reactor_id=w.uid(), active=True, occurred_at=w.NOW)
        out.append(p)
    return out


def _rank(viewer, cfg, personal):
    return home.rank(
        eligibility.Viewer.from_claims({"sub": viewer, **ADULT}), w.NOW, cfg, personal=personal
    )


def _positions(ranked, kind):
    return [i for i, s in enumerate(ranked.items) if s.feats.type == kind]


def test_formats_more_and_less_move_a_format():
    viewer = w.uid()
    _connections(viewer, 30, video_every=3)
    cfg = config.for_surface("home")  # home@1: the control applies under every version
    base = _positions(_rank(viewer, cfg, Personal()), "video")
    less = _positions(_rank(viewer, cfg, Personal(formats={"video": "less"})), "video")
    more = _positions(_rank(viewer, cfg, Personal(formats={"video": "more"})), "video")
    assert sum(less) > sum(base) > sum(more)


def test_discovery_level_scales_the_recommended_share(redis_hot):
    variants.activate(variants.R15)
    viewer = w.uid()
    _connections(viewer, 80)
    _pool(30)
    cfg = variants.cfg(variants.R15)
    discovery.rebuild(cfg, now=w.NOW)
    shares = {lvl: _rank(viewer, cfg, Personal(discovery_level=lvl)).share for lvl in range(4)}
    assert shares[0] == 0.0
    assert shares[1] == pytest.approx(0.075)
    assert shares[2] == pytest.approx(0.15)
    assert shares[3] == pytest.approx(0.1995)


def test_trending_toggle_removes_the_popular_bucket_and_new_creators_its_source(redis_hot):
    variants.activate(variants.R15)
    viewer = w.uid()
    _connections(viewer, 60)
    _pool(30)
    cfg = variants.cfg(variants.R15)
    discovery.rebuild(cfg, now=w.NOW)
    on = _rank(viewer, cfg, Personal())
    reasons = {s.feats.reason for s in on.items if s.feats.source == discovery.SOURCE}
    assert "rec_popular" in reasons
    off = _rank(viewer, cfg, Personal(discovery_prefs={"trending": False}))
    assert "rec_popular" not in {s.feats.reason for s in off.items if s.feats.source == "discovery"}
    # new_creators off drops that source (rule E12); no Home pool is one yet (R5).
    from intel.retrieval.sources import Candidate

    c = Candidate(w.post(w.uid()), None, "new_creators", "new_creators", w.NOW, "text")
    v = Personal(discovery_prefs={"new_creators": False}).viewer(
        eligibility.Viewer.from_claims({"sub": viewer, **ADULT})
    )
    ctx = eligibility.load_context(v, [c], cfg)
    assert eligibility.evaluate(c, ctx) == "E12"


def test_languages_filter_recommendations_and_other_languages_lifts_it(redis_hot):
    variants.activate(variants.R15)
    viewer = w.uid()
    _connections(viewer, 60)
    _pool(15, lang="ar")
    _pool(15, lang="en", minutes=20)
    cfg = variants.cfg(variants.R15)
    discovery.rebuild(cfg, now=w.NOW)

    def langs(personal):
        ranked = _rank(viewer, cfg, personal)
        return {
            ranked.content[s.feats.post_id]["lang"]
            for s in ranked.items
            if s.feats.source == "discovery"
        }

    assert langs(Personal(languages=frozenset({"ar"}))) == {"ar"}
    assert langs(
        Personal(languages=frozenset({"ar"}), discovery_prefs={"other_languages": True})
    ) == {"ar", "en"}


def test_personalization_off_serves_for_you_chronologically(redis_hot, monkeypatch):
    monkeypatch.setattr("feed.ads_client.feed_sponsored", lambda viewer: None)
    variants.activate(variants.R15)
    viewer = w.uid()
    _connections(viewer, 25)
    _pool(10)
    discovery.rebuild(variants.cfg(variants.R15), now=w.NOW)
    preferences.patch(viewer, {"personalization_off": True})
    client = client_with_claims(viewer, **ADULT_CLAIMS)
    body = client.get("/api/v1/feed/", {"mode": "for_you", "limit": 10}).json()
    recent = client.get("/api/v1/feed/", {"mode": "recent", "limit": 10}).json()
    assert [i["post_id"] for i in body["data"]] == [i["post_id"] for i in recent["data"]]
    assert body["mode"] == "for_you" and body["meta"]["personalization_off"] is True
    assert all(i.get("source") in (None, "connections") for i in body["data"])
    nxt = client.get(
        "/api/v1/feed/", {"mode": "for_you", "limit": 10, "cursor": body["page"]["next_cursor"]}
    )
    assert nxt.status_code == 200 and len(nxt.json()["data"]) == 10
    assert not {i["post_id"] for i in nxt.json()["data"]} & {i["post_id"] for i in body["data"]}


def test_suggestion_toggles_are_served_for_the_other_surfaces(client_for):
    viewer = w.uid()
    client = client_for(viewer)
    body = {
        "discovery_prefs": {
            "people_suggestions": False,
            "page_suggestions": False,
            "group_suggestions": False,
        }
    }
    data = client.patch("/api/v1/feed/preferences/", body, format="json").json()["data"]
    assert data["discovery_prefs"]["people_suggestions"] is False
    assert data["discovery_prefs"]["page_suggestions"] is False
    assert data["discovery_prefs"]["group_suggestions"] is False
    _ = ranking
