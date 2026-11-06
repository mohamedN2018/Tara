"""Stage 4b: the diversity re-ranker (02 section 17; WP 4.5).

Greedy MMR-style selection, page by page. For each page it considers the best
``window_factor × page_size`` remaining items and picks, slot by slot,

    argmax_i  score_i − λ · max_sim(i, picked on this page)

subject to three constraints:

- **author**: at most ``max_per_author_page`` items of one author per page, and no
  two items of one author within ``author_gap`` slots;
- **topic**: no topic above ``max_topic_share`` of the page (topics arrive in
  phase 6; until then items carry none and the rule never binds);
- **format**: no run longer than ``max_same_format_run`` items of one type.

The format run and the author gap read the list as the viewer scrolls it: the tail
of the previous page counts, so a run never continues across a page boundary (the
per-page author cap starts again on every page). When no candidate in the window
satisfies every constraint, the rest of the list is searched, in score order, for
the best item that does ("when alternatives exist", WP 4.5); only when none exists
do the constraints relax, in a fixed order (format, then topic, then author), with
the same window-then-rest search at each level, so **a page is never short**: if
anything is left, the slot is filled. ``sim(i, j) = w_a·[same author] + w_t·jaccard(topics) +
w_f·[same type]`` (``sim_weights``). Deterministic: ties go to the earlier item of
the input order. Every number comes from the config's ``diversity`` block.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

RELAX_ORDER = ("format", "topic", "author")


@dataclass(frozen=True)
class Item:
    key: Any  # the caller's object
    score: float
    author: str
    type: str
    topics: frozenset = frozenset()


def _jaccard(a: frozenset, b: frozenset) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


class _Page:
    def __init__(self, block: dict, before: Sequence[Item] = ()):
        self.b = block
        # The end of the previous pages: format runs and author gaps span pages.
        self.seq: list[Item] = list(before)  # ``before`` then this page's picks
        self.picked: list[Item] = []
        self.authors: Counter = Counter()
        self.topics: Counter = Counter()

    def sim_pair(self, it: Item, p: Item) -> float:
        w = self.b["sim_weights"]
        return (
            w["author"] * (it.author == p.author)
            + w["topics"] * _jaccard(it.topics, p.topics)
            + w["type"] * (it.type == p.type)
        )

    def ok_author(self, it: Item) -> bool:
        if self.authors[it.author] >= self.b["max_per_author_page"]:
            return False
        gap = self.b["author_gap"]
        return not gap or all(p.author != it.author for p in self.seq[-gap:])

    def ok_topic(self, it: Item) -> bool:
        if not it.topics:
            return True
        cap = self.b["max_topic_share"] * self.b["page_size"]
        return all(self.topics[t] + 1 <= cap for t in it.topics)

    def ok_format(self, it: Item) -> bool:
        run = self.b["max_same_format_run"]
        tail = self.seq[-run:]
        return not (len(tail) == run and all(p.type == it.type for p in tail))

    def predicate(self, names: Sequence[str]) -> Callable[[Item], bool]:
        """``it -> all(ok_<name>(it) for name in names)`` with the page's state read
        once per slot (the blocked authors and format), not once per candidate: the
        same answer as the ``ok_*`` methods, at a set lookup per item (R3 verifier,
        first-page p95)."""
        b = self.b
        blocked_authors: set | None = None
        if "author" in names:
            cap = b["max_per_author_page"]
            blocked_authors = {a for a, n in self.authors.items() if n >= cap}
            gap = b["author_gap"]
            if gap:
                blocked_authors.update(p.author for p in self.seq[-gap:])
        block_all, blocked_type = False, None
        if "format" in names:
            run = b["max_same_format_run"]
            tail = self.seq[-run:]
            if len(tail) == run:
                types = {p.type for p in tail}
                if not types:
                    block_all = True  # ``all([])``: what ``ok_format`` answers here
                elif len(types) == 1:
                    blocked_type = next(iter(types))
        topic = "topic" in names
        ok_topic = self.ok_topic

        def ok(it: Item) -> bool:
            if blocked_authors is not None and it.author in blocked_authors:
                return False
            if block_all or (blocked_type is not None and it.type == blocked_type):
                return False
            return not topic or ok_topic(it)

        return ok

    def add(self, it: Item) -> None:
        self.picked.append(it)
        self.seq.append(it)
        self.authors[it.author] += 1
        for t in it.topics:
            self.topics[t] += 1


class _Beyond:
    """Authors and formats of the items past the window, kept exact as items are
    picked, so a search past the window is skipped when it cannot succeed."""

    def __init__(self, remaining: list[Item], window: int):
        self.window = window
        self.authors = Counter(it.author for it in remaining[window:])
        self.types = Counter(it.type for it in remaining[window:])

    def _drop(self, it: Item) -> None:
        for counter, value in ((self.authors, it.author), (self.types, it.type)):
            counter[value] -= 1
            if counter[value] <= 0:
                del counter[value]

    def take(self, remaining: list[Item], index: int) -> Item:
        it = remaining.pop(index)
        if index >= self.window:
            self._drop(it)
        elif len(remaining) >= self.window:
            self._drop(remaining[self.window - 1])  # it just entered the window
        return it

    def may_hold(self, page: _Page, names: Sequence[str]) -> bool:
        """False when no item past the window can keep the ``names`` constraints."""
        if not self.authors:
            return False
        b = page.b
        if "author" in names:
            blocked = {a for a, n in page.authors.items() if n >= b["max_per_author_page"]}
            if b["author_gap"]:
                blocked |= {p.author for p in page.seq[-b["author_gap"] :]}
            if not (self.authors.keys() - blocked):
                return False
        if "format" in names:
            tail = page.seq[-b["max_same_format_run"] :]
            if len(tail) == b["max_same_format_run"] and len({p.type for p in tail}) == 1:
                if not (self.types.keys() - {tail[0].type}):
                    return False
        return True


Insert = Callable[[int, "_Page"], "Item | None"]
# ``relief(position, page, names)``: an outside item keeping the constraints ``names``.
Relief = Callable[[int, "_Page", Sequence[str]], "Item | None"]
# ``contest(position, page, picked)``: an outside item that takes the slot instead of
# ``picked`` (it must keep every constraint and score higher), or None.
Contest = Callable[[int, "_Page", "Item"], "Item | None"]


def _place(page: _Page, extra: Item, out: list, window: Sequence[Item], best_sim: dict) -> None:
    """An outside item (``insert`` / ``relief``) takes the slot as is."""
    page.add(extra)
    out.append(extra)
    for it in window:
        s = page.sim_pair(it, extra)
        if s > best_sim.get(id(it), 0.0):
            best_sim[id(it)] = s


def rerank(
    items: Sequence[Item],
    block: dict,
    page_size: int | None = None,
    insert: Insert | None = None,
    relief: Relief | None = None,
    contest: Contest | None = None,
) -> list[Item]:
    """``items`` (best first) re-ordered page by page. Same input, same output.

    ``insert(position, page)`` (07 WP 4b.6) may claim a slot for an item from outside
    ``items`` (a recommended pool item): it is placed as is, counts on its page like
    any pick, and the re-ranker goes on around it. ``relief(position, page, names)``
    is asked when no item of ``items`` keeps the constraints ``names`` at a slot,
    before one more is relaxed: an outside item it returns (one that keeps them)
    takes the slot, so the author cap and the format run hold "when alternatives
    exist" outside ``items`` too (R1 verifier, 07 WP 4b.10). ``contest(position, page,
    picked)`` is asked after a pick: an outside item it returns takes the slot and
    ``picked`` stays for a later one (R3 verifier: a pool item that scores above an
    already-seen connection item, 06 section 5.4). Without any nothing changes."""
    size = page_size or block["page_size"]
    block = {**block, "page_size": size}
    window = block["window_factor"] * size
    remaining = list(items)
    beyond = _Beyond(remaining, window)
    out: list[Item] = []
    lam = block["lambda"]
    carry = max(block["max_same_format_run"], block["author_gap"])
    while remaining:
        page = _Page(block, out[-carry:] if carry else ())
        best_sim: dict[int, float] = {}  # id(item) -> max sim to this page's picks

        for _ in range(size):
            extra = insert(len(out), page) if insert is not None and remaining else None
            if extra is not None:
                _place(page, extra, out, remaining[:window], best_sim)
                continue
            if not remaining:
                break
            pool = remaining[:window]
            choice = None
            for relaxed in range(len(RELAX_ORDER) + 1):
                names = RELAX_ORDER[relaxed:]
                keeps = page.predicate(names)
                allowed = [(i, it) for i, it in enumerate(pool) if keeps(it)]
                if allowed:
                    choice = max(
                        allowed,
                        key=lambda t: (t[1].score - lam * best_sim.get(id(t[1]), 0.0), -t[0]),
                    )
                    break
                # Past the window, best score first: an alternative that keeps these
                # constraints beats relaxing one (items there carry no MMR penalty).
                if beyond.may_hold(page, names):
                    choice = next(
                        (
                            (i, it)
                            for i, it in enumerate(remaining[window:], start=window)
                            if keeps(it)
                        ),
                        None,
                    )
                    if choice is not None:
                        break
                if relief is not None and names:
                    # Nothing in ``items`` keeps these constraints here: an outside
                    # item that does beats relaxing one more.
                    extra = relief(len(out), page, names)
                    if extra is not None:
                        break
            if choice is None and extra is not None:
                _place(page, extra, out, remaining[:window], best_sim)
                continue
            index, chosen = choice
            if contest is not None:
                extra = contest(len(out), page, chosen)
                if extra is not None:
                    _place(page, extra, out, remaining[:window], best_sim)
                    continue
            picked = beyond.take(remaining, index)
            page.add(picked)
            out.append(picked)
            for it in remaining[:window]:
                s = page.sim_pair(it, picked)
                if s > best_sim.get(id(it), 0.0):
                    best_sim[id(it)] = s
    return out


def metrics(items: Sequence[Item], per: int = 20) -> dict:
    """Diversity of a ranked list (02 section 17): distinct authors per ``per`` items
    and the longest same-format run."""
    head = list(items[:per])
    longest = run = 0
    prev = None
    for it in items:
        run = run + 1 if it.type == prev else 1
        prev = it.type
        longest = max(longest, run)
    return {"distinct_authors": len({i.author for i in head}), "longest_format_run": longest}
