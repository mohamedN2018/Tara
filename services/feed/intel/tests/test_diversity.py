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
