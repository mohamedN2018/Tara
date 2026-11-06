"""WP 4.5: the diversity re-ranker. On synthetic data: at most 2 posts per author per
page, no 3 consecutive posts of one format when alternatives exist, no page shorter
than the page size; constraints relax in a fixed order; deterministic."""

import random

import pytest

from intel import config
from intel.ranking import diversity
from intel.ranking.diversity import Item

BLOCK = config.store.defaults("home", 2)["diversity"]
PAGE = BLOCK["page_size"]


def _synthetic(n=200, authors=40, seed=1):
    """A ranked list where the best items cluster: the top 30 come from 3 prolific
    authors, and formats arrive in runs of 7 (the worst case for a feed)."""
    rng = random.Random(seed)
    items = []
    for i in range(n):
        author = f"a{i % 3}" if i < 30 else f"a{rng.randrange(authors)}"
        kind = "video" if (i // 7) % 2 == 0 else rng.choice(["text", "image"])
        items.append(
            Item(key=i, score=100.0 - i * 0.1 + rng.random() * 0.05, author=author, type=kind)
        )
    return sorted(items, key=lambda it: -it.score)


def _pages(items, size=PAGE):
    return [items[i : i + size] for i in range(0, len(items), size)]


@pytest.mark.parametrize("seed", range(8))
def test_constraints_hold_on_synthetic_data(seed):
    items = _synthetic(seed=seed)
    out = diversity.rerank(items, BLOCK)
    assert sorted(i.key for i in out) == sorted(i.key for i in items)  # nothing lost or added
    pages = _pages(out)
    for page in pages[:-1]:
        assert len(page) == PAGE  # never short
    # Every page but the last (which takes whatever is left) holds the author cap.
    for n, page in enumerate(pages[:-1]):
        per_author = {}
        for it in page:
            per_author[it.author] = per_author.get(it.author, 0) + 1
        assert max(per_author.values()) <= BLOCK["max_per_author_page"], (n, per_author)
    # No 3 consecutive items of one format (max_same_format_run = 2) while
    # alternatives remain within the window.
    for page in pages[:5]:
        types = [it.type for it in page]
        for k in range(len(types) - 2):
            assert len(set(types[k : k + 3])) > 1, (types, k)


def test_the_input_without_reranking_breaks_the_rules():
    """The synthetic list really is hard: plain score order violates both rules."""
    head = _synthetic()[:PAGE]
    counts = {}
    for it in head:
        counts[it.author] = counts.get(it.author, 0) + 1
    assert max(counts.values()) > BLOCK["max_per_author_page"]
    types = [it.type for it in head]
    assert any(len(set(types[k : k + 3])) == 1 for k in range(len(types) - 2))


def test_deterministic():
    items = _synthetic(seed=3)
    assert [i.key for i in diversity.rerank(items, BLOCK)] == [
        i.key for i in diversity.rerank(items, BLOCK)
    ]


def test_relaxation_order_format_then_topic_then_author():
    # One author, one format only: every constraint must relax, the page stays full.
    items = [Item(key=i, score=10 - i, author="solo", type="video") for i in range(25)]
    out = diversity.rerank(items, BLOCK)
    assert [i.key for i in out] == list(range(25))  # score order kept

    # Two authors, one format: the format rule cannot hold and relaxes first; the
    # author rule still separates the first two slots.
    items = [Item(key=i, score=10 - i * 0.01, author=f"a{i % 2}", type="text") for i in range(10)]
    out = diversity.rerank(items, BLOCK)
    assert len(out) == 10 and out[0].author != out[1].author


def test_format_is_relaxed_before_author():
    # Videos by many authors, texts by one author. The page needs a text to break the
    # video run; when the only text author is exhausted, videos continue.
    items = [Item(key=f"v{i}", score=50 - i, author=f"v{i}", type="video") for i in range(20)]
    items += [Item(key=f"t{i}", score=10 - i, author="writer", type="text") for i in range(5)]
    items.sort(key=lambda it: -it.score)
    out = diversity.rerank(items, BLOCK)
    page = out[:PAGE]
    assert sum(it.author == "writer" for it in page) == BLOCK["max_per_author_page"]
    assert len(page) == PAGE


def test_topics_cap_their_share_of_a_page():
    block = {**BLOCK, "max_topic_share": 0.25}
    items = [
        Item(
            key=i,
            score=100 - i,
            author=f"a{i}",
            type=["text", "image"][i % 2],
            topics=frozenset({"football"} if i < 15 else {f"t{i}"}),
        )
        for i in range(40)
    ]
    page = diversity.rerank(items, block)[:PAGE]
    assert sum("football" in it.topics for it in page) <= 0.25 * PAGE


def test_lambda_zero_and_no_conflicts_keep_the_score_order():
    items = [
        Item(key=i, score=100 - i, author=f"a{i}", type=["text", "image", "video"][i % 3])
        for i in range(30)
    ]
    assert [i.key for i in diversity.rerank(items, {**BLOCK, "lambda": 0.0})] == list(range(30))


def test_metrics():
    items = _synthetic()
    before = diversity.metrics(items)
    after = diversity.metrics(diversity.rerank(items, BLOCK))
    assert after["distinct_authors"] > before["distinct_authors"]
    assert after["longest_format_run"] <= before["longest_format_run"]


def test_format_runs_and_author_gaps_do_not_continue_across_pages():
    """The viewer scrolls one list: the tail of page 1 counts on page 2."""
    items = _synthetic(n=400, seed=5)
    out = diversity.rerank(items, BLOCK)
    run = BLOCK["max_same_format_run"]
    gap = BLOCK["author_gap"]
    for edge in range(PAGE, len(out) - PAGE, PAGE):
        window = out[edge - run : edge + 1]
        assert len({it.type for it in window}) > 1, edge
        head = out[edge - gap : edge + 1]
        assert len({it.author for it in head}) == len(head), edge


def test_alternatives_past_the_window_keep_the_author_cap():
    """The window (3 x page) holds one prolific author only; other authors exist
    further down. The cap holds instead of relaxing (when alternatives exist)."""
    size = 10
    block = {**BLOCK, "page_size": size}
    items = [Item(key=f"p{i}", score=1000 - i, author="prolific", type="text") for i in range(40)]
    items += [Item(key=f"o{i}", score=100 - i, author=f"o{i}", type="text") for i in range(40)]
    out = diversity.rerank(items, block)
    for start in range(0, 40, size):
        page = out[start : start + size]
        assert sum(it.author == "prolific" for it in page) <= block["max_per_author_page"]
    # The prolific author's best items still lead: the first slot is theirs.
    assert out[0].key == "p0"
    assert sorted(i.key for i in out) == sorted(i.key for i in items)


# ---- home@2b (07 WP 4b.10) ---------------------------------------------------------------


def _v2b_block():
    import json

    with (config.store.DEFAULTS_DIR / "home.v2b.json").open(encoding="utf-8") as fh:
        return json.load(fh)["diversity"]


def test_home_v2b_keeps_the_author_cap_and_the_run_of_two():
    block = _v2b_block()
    assert block == BLOCK  # 4b.10: the WP 4.5 vs 02:347 run length was settled in phase 4
    for seed in range(8):
        out = diversity.rerank(_synthetic(seed=seed), block)
        for page in _pages(out[: 3 * PAGE]):  # the pages where alternatives exist
            authors = [i.author for i in page]
            assert max(authors.count(a) for a in set(authors)) <= block["max_per_author_page"]
            assert len(set(authors)) >= 8
        types = [i.type for i in out[: 3 * PAGE]]
        runs = [types[i : i + 3] for i in range(len(types) - 2)]
        assert not any(len(set(r)) == 1 for r in runs)


def test_recommended_slots_keep_the_rules_and_the_exact_share():
    """home.mix takes, at each recommended slot, the best pool item that keeps the
    author cap, the author gap and the format run on the merged list; the share of
    every page stays exactly floor(share x page) (decision 23's cap is never exceeded)."""
    from types import SimpleNamespace

    from intel.ranking import home

    block = _v2b_block()

    def item(key, author, kind, value=0.0):
        return SimpleNamespace(
            key=key, value=value, feats=SimpleNamespace(author_id=author, type=kind)
        )

    conn = [item(f"c{i}", f"a{i % 12}", ["text", "image"][i % 2]) for i in range(60)]
    # Pool items: three prolific strangers first, all videos, then varied ones.
    recs = [item(f"r{i}", f"s{i % 3}", "video") for i in range(12)]
    recs += [item(f"q{i}", f"t{i}", ["text", "image", "link"][i % 3]) for i in range(30)]
    for share in (0.10, 0.15, 0.30):
        out, _cu = home.mix(conn, recs, share, 0, home._fits(block))
        for start in range(0, 60, 20):
            page = out[start : start + 20]
            assert sum(1 for p in page if p.key[0] in "rq") == int(20 * share + 1e-9)
            authors = [p.feats.author_id for p in page]
            assert max(authors.count(a) for a in set(authors)) <= block["max_per_author_page"]
            assert len(set(authors)) >= 8
        kinds = [p.feats.type for p in out[:60]]
        assert not any(len(set(kinds[i : i + 3])) == 1 for i in range(len(kinds) - 2))


def test_recommended_slots_inside_the_re_ranker_keep_pages_whole():
    """The path home.rank takes (diversity on): the connection items are diversified
    around the claimed slots, so a prolific friend never gets 3 on a page because the
    recommendations shifted the page boundaries."""
    from types import SimpleNamespace

    from intel.ranking import home

    block = _v2b_block()

    def item(key, author, kind, value):
        return SimpleNamespace(
            key=key, value=value, feats=SimpleNamespace(author_id=author, type=kind)
        )

    # The worst case: one friend dominates the top of the connection list.
    conn = [
        item(f"c{i}", "f0" if i < 30 else f"a{i % 15}", ["text", "image"][i % 2], 100 - i)
        for i in range(120)
    ]
    recs = [item(f"r{i}", f"s{i}", ["video", "link"][i % 2], 50 - i) for i in range(40)]
    for share in (0.10, 0.15, 0.30):
        out, cu = home._mix_diverse(conn, recs, share, 10, block)
        # A tail follows the last connection item only while pool items are left.
        left = 40 - sum(1 for p in out if p.key[0] == "r" and out.index(p) < (cu or len(out)))
        assert (cu is not None) == (left > 0)
        for start in range(0, 100, 20):
            page = out[start : start + 20]
            assert sum(1 for p in page if p.key[0] == "r") == int(20 * share + 1e-9)
            authors = [p.feats.author_id for p in page]
            assert max(authors.count(a) for a in set(authors)) <= block["max_per_author_page"]
        kinds = [p.feats.type for p in out[:100]]
        assert not any(len(set(kinds[i : i + 3])) == 1 for i in range(len(kinds) - 2))


# ---- R3 verifier: the per-slot predicate and the seen-item contest --------------------------


@pytest.mark.parametrize("seed", range(6))
def test_the_page_predicate_answers_like_the_ok_methods(seed):
    """``_Page.predicate`` reads the page state once per slot; it must give exactly the
    answers of ``ok_author``, ``ok_format`` and ``ok_topic`` for every relaxation level."""
    rng = random.Random(seed)
    for run, gap in ((2, 0), (2, 1), (3, 2), (0, 0)):
        block = {**BLOCK, "max_same_format_run": run, "author_gap": gap}
        page = diversity._Page(block)
        pool = [
            Item(
                key=i,
                score=0.0,
                author=f"a{rng.randrange(5)}",
                type=rng.choice(["text", "video"]),
                topics=frozenset({f"t{rng.randrange(3)}"}) if rng.random() < 0.5 else frozenset(),
            )
            for i in range(40)
        ]
        for it in pool[:12]:
            for k in range(len(diversity.RELAX_ORDER) + 1):
                names = diversity.RELAX_ORDER[k:]
                keeps = page.predicate(names)
                for other in pool:
                    expected = all(getattr(page, f"ok_{n}")(other) for n in names)
                    assert keeps(other) is expected
            page.add(it)


def _scored(key, author, kind, value):
    from types import SimpleNamespace

    return SimpleNamespace(
        key=key,
        value=value,
        feats=SimpleNamespace(post_id=key, author_id=author, type=kind),
    )


def _capped_world():
    """06 scenario C's worst case (R3 harness): every unseen connection item belongs to
    one friend (``f0``, capped at 2 per page); the other friends' items were all seen
    (``m`` < ``revisit.min_m``, so their ``score'`` is low); unseen pool items score
    higher than those seen items."""
    conn = [_scored(f"u{i}", "f0", ["text", "image"][i % 2], 5.0 - i * 0.01) for i in range(40)]
    conn += [_scored(f"s{i}", f"a{i}", ["text", "image"][i % 2], 1.0 - i * 0.01) for i in range(30)]
    conn.sort(key=lambda s: -s.value)
    recs = [_scored(f"r{i}", f"p{i}", ["video", "link"][i % 2], 3.0 - i * 0.01) for i in range(60)]
    demoted = frozenset(f"s{i}" for i in range(30))
    return conn, recs, demoted


def test_a_seen_connection_item_yields_its_slot_to_a_better_pool_item():
    from intel.ranking import home

    block = _v2b_block()
    conn, recs, demoted = _capped_world()
    before, _ = home._mix_diverse(conn, recs, 0.15, 10, block)
    after, _ = home._mix_diverse(conn, recs, 0.15, 10, block, demoted)
    first = lambda out: [p.key for p in out[:20]]  # noqa: E731
    assert any(k.startswith("s") for k in first(before))  # the R3 harness finding
    assert not any(k.startswith("s") for k in first(after))  # rotation by score x m
    for out in (before, after):
        page = out[:20]
        authors = [p.feats.author_id for p in page]
        assert len(page) == 20
        assert max(authors.count(a) for a in set(authors)) <= block["max_per_author_page"]
    # Every item is still served exactly once (nothing dropped or duplicated).
    assert sorted(p.key for p in after) == sorted(p.key for p in before)


def test_the_contest_never_runs_in_the_control_arm():
    """The control (no continuation, ``tail`` 0) keeps its decision-23 share: no pool
    item takes a seen item's slot, so the order is the one without ``demoted``."""
    from intel.ranking import home

    block = _v2b_block()
    conn, recs, demoted = _capped_world()
    plain, _ = home._mix_diverse(conn, recs, 0.15, 0, block)
    with_seen, _ = home._mix_diverse(conn, recs, 0.15, 0, block, demoted)
    assert [p.key for p in with_seen] == [p.key for p in plain]
