"""``post_batch_dropped_total{caller,surface,src}`` (intelligence WP 3.6): every
id a hydration batch was asked for and did not return is counted on the
server, labelled by the caller's hints; the hints never change the answer and
cannot grow the label set."""

import uuid

import pytest
from django.urls import reverse
from prometheus_client import REGISTRY

from posts import hydration, services

pytestmark = pytest.mark.django_db

METRIC = "post_batch_dropped_total"


def _acct() -> str:
    return str(uuid.uuid4())


def _count(surface: str, src: str, caller: str = "web") -> float:
    value = REGISTRY.get_sample_value(METRIC, {"caller": caller, "surface": surface, "src": src})
    return value or 0.0


def _batch(client, ids, **hints):
    resp = client.post(reverse("posts:post-batch"), {"ids": ids, **hints}, format="json")
    assert resp.status_code == 200, resp.content
    return [p["id"] for p in resp.json()["data"]]


@pytest.fixture
def posts():
    author = _acct()
    visible = str(services.create_post(author, body="public", audience="public").id)
    private = str(services.create_post(author, body="mine", audience="only_me").id)
    gone = services.create_post(author, body="gone", audience="public")
    services.delete_post(author, str(gone.id))
    return visible, private, str(gone.id)


def test_every_dropped_id_is_counted_under_its_hints(client_for, posts):
    visible, private, gone = posts
    before = _count("home", "discovery")
    ids = _batch(client_for(_acct()), [visible, private, gone], surface="home", src="discovery")
    assert ids == [visible]
    assert _count("home", "discovery") - before == 2


def test_a_per_id_source_list_labels_each_drop(client_for, posts):
    visible, private, gone = posts
    before = {s: _count("home", s) for s in ("friend", "follow_pull", "trending")}
    _batch(
        client_for(_acct()),
        [visible, private, gone],
        surface="home",
        src=["friend", "follow_pull", "trending"],
    )
    after = {s: _count("home", s) for s in before}
    assert {s: after[s] - before[s] for s in before} == {
        "friend": 0,
        "follow_pull": 1,
        "trending": 1,
    }


def test_no_hints_are_counted_as_none(client_for, posts):
    _, private, _ = posts
    before = _count("none", "none")
    _batch(client_for(_acct()), [private])
    assert _count("none", "none") - before == 1


def test_unknown_or_malformed_hints_fold_into_bounded_labels(client_for, posts):
    _, private, gone = posts
    viewer = client_for(_acct())
    other_before = _count("other", "other")
    _batch(viewer, [private], surface="<script>", src="x" * 300)
    _batch(viewer, [gone], surface=5, src={"nested": True})
    assert _count("other", "other") - other_before == 2

    # A list that does not match ids is ignored as a whole.
    none_before = _count("reels", "none")
    _batch(viewer, [private, gone], surface="reels", src=["reels"])
    assert _count("reels", "none") - none_before == 2


def test_a_fully_returned_batch_counts_nothing(client_for, posts):
    visible, _, _ = posts
    before = _count("home", "connections")
    assert _batch(client_for(_acct()), [visible, visible], surface="home", src="connections") == [
        visible,
        visible,
    ]
    assert _count("home", "connections") == before


def test_a_repeated_dropped_id_is_counted_once():
    tally = hydration.record_drops(["a", "a", "b"], ["b"], {"surface": "home", "src": "video"})
    assert tally == {("home", "video"): 1}


def test_the_label_vocabulary_is_bounded():
    # Every label value the counter can carry: a client cannot add one.
    surfaces = hydration.SURFACES | {hydration.NONE, hydration.OTHER}
    sources = hydration.SOURCES | {hydration.NONE, hydration.OTHER}
    for raw in ("home", "", None, "x" * 50, 3, ["a"], {"b": 1}):
        assert hydration._label(raw, hydration.SURFACES) in surfaces  # noqa: SLF001
        assert hydration._label(raw, hydration.SOURCES) in sources  # noqa: SLF001
    assert hydration.DISCOVERY_SOURCES <= hydration.SOURCES


def test_reels_batch_counts_its_drops_too(client_for):
    private = str(services.create_post(_acct(), body="not a reel", audience="public").id)
    before = _count("reels", "reels")
    resp = client_for(_acct()).post(
        reverse("reels:reel-batch"),
        {"ids": [private], "surface": "reels", "src": "reels"},
        format="json",
    )
    assert resp.status_code == 200 and resp.json()["data"] == []
    assert _count("reels", "reels") - before == 1


def test_counts_live_in_the_shared_cache_so_every_worker_reports_them(client_for, posts):
    # Another gunicorn worker has its own registry but the same cache: what
    # one worker counted is what any worker's /metrics shows.
    _, private, _ = posts
    _batch(client_for(_acct()), [private], surface="video", src="video")
    assert hydration.counts()[("web", "video", "video")] >= 1
    other_worker = hydration.DropCollector()
    samples = {
        tuple(s.labels[k] for k in ("caller", "surface", "src")): s.value
        for family in other_worker.collect()
        for s in family.samples
        if s.name == METRIC
    }
    assert samples[("web", "video", "video")] == hydration.counts()[("web", "video", "video")]


def test_a_cache_failure_never_fails_the_batch(client_for, posts, monkeypatch):
    visible, private, _ = posts

    class Down:
        def __getattr__(self, name):
            def fail(*args, **kwargs):
                raise ConnectionError("redis down")

            return fail

    monkeypatch.setattr(hydration, "cache", Down())
    assert _batch(client_for(_acct()), [visible, private], surface="home", src="friend") == [
        visible
    ]
    assert list(hydration.DropCollector().collect())[0].samples == []
