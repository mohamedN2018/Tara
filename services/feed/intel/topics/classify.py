"""The rule-based topic classifier (04 WP 6.2, 02 section 14). No model, no LLM.

Rules, each giving a confidence per topic; a topic keeps its highest:

1. **hashtag**: a curated ``hashtag`` alias, ``topics.hashtag_confidence`` (0.9) x the
   alias weight;
2. **page**: a post by a page inherits its page category's topic
   (``topics.category_confidence``, 0.6);
3. **group**: a post in a group inherits its group category's topic (0.6), except
   ``general`` and ``other``, which name no topic;
4. **lexicon**: normalized tokens (and adjacent token pairs) of the excerpt against
   the ``keyword`` aliases (``lexicons/{ar,en}.txt``). A topic needs
   ``lexicon_min_hits`` (2) distinct terms, or one term marked ``strong``;
   confidence ``lexicon_base + lexicon_step x (hits - 1)``, capped at ``lexicon_cap``;
5. **inherited**: a shared post inherits the original's topics x ``inherit_factor``.

Topics below ``min_confidence`` are dropped and at most ``max_topics`` are kept
(highest confidence first). Arabic is normalized with ``tara_common.text``, plus a
light clitic strip (``و``, ``ال``, ``وال``, ``بال``, ``لل``, ``فال``) so
"والبرمجة" meets "برمجة". The excerpt itself is never stored, only the topics.

Every threshold is in the Home config's ``topics`` block (decision 20).
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from django.db import connection, transaction
from django.utils import timezone

from tara_common.text import normalize_ar, normalize_key

from .. import config, metrics

logger = logging.getLogger("tara.intel.topics")

ALIAS_TTL_S = 300.0
_PREFIXES = ("وال", "بال", "فال", "لل", "ال", "و")
_EDGE = ".-/+#"
_lock = threading.Lock()
_cache: dict[str, object] = {}


@dataclass(frozen=True)
class Found:
    topic_id: int
    confidence: float
    source: str


@dataclass
class Aliases:
    hashtag: dict[str, tuple[int, float]]
    page: dict[str, int]
    group: dict[str, int]
    keyword: dict[str, tuple[int, bool]]
    topics: dict[int, dict]


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def load_aliases(force: bool = False) -> Aliases:
    """Active aliases and topics, cached in process for ``ALIAS_TTL_S``."""
    now = time.monotonic()
    with _lock:
        hit = _cache.get("aliases")
        if hit and not force and hit[0] > now:  # type: ignore[index]
            return hit[1]  # type: ignore[index]
    with connection.cursor() as cur:
        cur.execute(
            "SELECT a.kind, a.value_norm, a.topic_id, a.weight, a.strong FROM intel_topic_alias a "
            "JOIN intel_topic t ON t.id = a.topic_id AND t.status = 'active' "
            "WHERE a.status = 'active'"
        )
        rows = cur.fetchall()
        cur.execute(
            "SELECT id, slug, label_ar, label_en, sensitive, allow_minors, parent_id "
            "FROM intel_topic WHERE status = 'active'"
        )
        topics = {
            int(r[0]): {
                "id": int(r[0]),
                "slug": r[1],
                "label_ar": r[2],
                "label_en": r[3],
                "sensitive": bool(r[4]),
                "allow_minors": bool(r[5]),
                "parent_id": r[6],
            }
            for r in cur.fetchall()
        }
    found = Aliases({}, {}, {}, {}, topics)
    for kind, value, topic_id, weight, strong in rows:
        if kind == "hashtag":
            found.hashtag[value] = (int(topic_id), float(weight))
        elif kind == "page_category":
            found.page[value] = int(topic_id)
        elif kind == "group_category":
            found.group[value] = int(topic_id)
        elif kind == "keyword":
            found.keyword[value] = (int(topic_id), bool(strong))
    with _lock:
        _cache["aliases"] = (now + ALIAS_TTL_S, found)
    return found


def tokens(text: str | None) -> list[str]:
    out = []
    for raw in normalize_key(normalize_ar(text or "")).split():
        token = raw.strip(_EDGE)
        if token:
            out.append(token)
    return out


def _variants(token: str) -> Iterable[str]:
    yield token
    for prefix in _PREFIXES:
        if token.startswith(prefix) and len(token) - len(prefix) >= 2:
            yield token[len(prefix) :]


def lexicon_hits(text: str | None, keyword: dict) -> dict[int, tuple[set[str], bool]]:
    """``{topic_id: (distinct terms hit, any strong)}`` over tokens and adjacent pairs."""
    toks = tokens(text)
    hits: dict[int, tuple[set[str], bool]] = {}

    def hit(term: str) -> bool:
        entry = keyword.get(term)
        if entry is None:
            return False
        topic_id, strong = entry
        terms, any_strong = hits.get(topic_id, (set(), False))
        terms.add(term)
        hits[topic_id] = (terms, any_strong or strong)
        return True

    for i, token in enumerate(toks):
        for v in _variants(token):
            if hit(v):
                break
        if i + 1 < len(toks):
            pair = f"{token} {toks[i + 1]}"
            for v in _variants(pair):
                if hit(v):
                    break
    return hits


def classify(
    *,
    excerpt: str | None,
    hashtags: Iterable[str] = (),
    page_category: str | None = None,
    group_category: str | None = None,
    inherited: Iterable[tuple[int, float]] = (),
    kept_lexicon: Iterable[tuple[int, float]] = (),
    aliases: Aliases | None = None,
    block: dict | None = None,
) -> list[Found]:
    """The topics of one post (pure: every input is passed in)."""
    a = aliases or load_aliases()
    b = block or config.for_surface("home").section("topics")
    best: dict[int, Found] = {}

    def offer(topic_id: int, confidence: float, source: str) -> None:
        if topic_id not in a.topics:
            return
        confidence = round(min(max(confidence, 0.0), 1.0), 4)
        current = best.get(topic_id)
        if current is None or confidence > current.confidence:
            best[topic_id] = Found(topic_id, confidence, source)

    for tag in hashtags or ():
        entry = a.hashtag.get(normalize_key(normalize_ar(tag)).lstrip("#"))
        if entry:
            offer(entry[0], b["hashtag_confidence"] * entry[1], "hashtag")
    if page_category:
        topic_id = a.page.get(page_category)
        if topic_id is not None:
            offer(topic_id, b["category_confidence"], "page")
    if group_category:
        topic_id = a.group.get(group_category)
        if topic_id is not None:
            offer(topic_id, b["category_confidence"], "group")
    if excerpt is not None:
        for topic_id, (terms, strong) in lexicon_hits(excerpt, a.keyword).items():
            n = len(terms)
            if n < b["lexicon_min_hits"] and not strong:
                continue
            offer(
                topic_id,
                min(b["lexicon_base"] + b["lexicon_step"] * (n - 1), b["lexicon_cap"]),
                "lexicon",
            )
    else:
        for topic_id, confidence in kept_lexicon:
            offer(int(topic_id), float(confidence), "lexicon")
    for topic_id, confidence in inherited:
        offer(int(topic_id), float(confidence) * b["inherit_factor"], "inherited")
    kept = [f for f in best.values() if f.confidence >= b["min_confidence"]]
    kept.sort(key=lambda f: (-f.confidence, f.topic_id))
    return kept[: b["max_topics"]]


# ---- storage ----------------------------------------------------------------------

_CONTEXT_SQL = """
SELECT c.author_id, c.author_type, c.group_id, c.shared_post_id, c.hashtags,
       p.category_norm, g.category
FROM intel_content_ref c
LEFT JOIN intel_page_ref p ON p.page_id = c.author_id
LEFT JOIN intel_group_ref g ON g.group_id = c.group_id
WHERE c.post_id = %s
"""


def classify_post(post_id, excerpt: str | None, *, now: datetime | None = None) -> list[Found]:
    """Classify a stored ``intel_content_ref`` row and replace its topics. ``excerpt``
    None (an edit that did not carry the text) keeps the lexicon topics it had."""
    post_id = str(post_id)
    with transaction.atomic(), connection.cursor() as cur:
        cur.execute(_CONTEXT_SQL, [post_id])
        row = cur.fetchone()
        if row is None:
            return []
        _author, _author_type, _group, shared, hashtags, page_cat, group_cat = row
        inherited = []
        if shared:
            cur.execute(
                "SELECT topic_id, confidence FROM intel_content_topic WHERE post_id = %s",
                [str(shared)],
            )
            inherited = cur.fetchall()
        kept = []
        if excerpt is None:
            cur.execute(
                "SELECT topic_id, confidence FROM intel_content_topic "
                "WHERE post_id = %s AND source = 'lexicon'",
                [post_id],
            )
            kept = cur.fetchall()
        found = classify(
            excerpt=excerpt,
            hashtags=hashtags or [],
            page_category=page_cat or None,
            group_category=group_cat or None,
            inherited=inherited,
            kept_lexicon=kept,
        )
        cur.execute("DELETE FROM intel_content_topic WHERE post_id = %s", [post_id])
        when = now or timezone.now()
        for f in found:
            cur.execute(
                "INSERT INTO intel_content_topic "
                "(post_id, topic_id, confidence, source, classified_at) "
                "VALUES (%s, %s, %s, %s, %s)",
                [post_id, f.topic_id, f.confidence, f.source, when],
            )
    metrics.topics_classified(bool(found))
    return found


def topics_of(post_ids: Iterable[str]) -> dict[str, list[tuple[int, float]]]:
    """``{post_id: [(topic_id, confidence)]}`` best first (one statement)."""
    ids = sorted({str(p) for p in post_ids})
    if not ids:
        return {}
    with connection.cursor() as cur:
        cur.execute(
            "SELECT post_id, topic_id, confidence FROM intel_content_topic "
            "WHERE post_id = ANY(%s::uuid[]) ORDER BY post_id, confidence DESC, topic_id",
            [ids],
        )
        out: dict[str, list[tuple[int, float]]] = {}
        for post_id, topic_id, confidence in cur.fetchall():
            out.setdefault(str(post_id), []).append((int(topic_id), float(confidence)))
    return out


def topics_with_labels(post_ids: Iterable[str]) -> tuple[dict, dict]:
    """``({post_id: [(topic_id, confidence)]}, {topic_id: labels})`` in one statement
    (a served page: no taxonomy cache read on the request path)."""
    ids = sorted({str(p) for p in post_ids})
    if not ids:
        return {}, {}
    with connection.cursor() as cur:
        cur.execute(
            "SELECT ct.post_id, ct.topic_id, ct.confidence, t.slug, t.label_ar, t.label_en "
            "FROM intel_content_topic ct JOIN intel_topic t ON t.id = ct.topic_id "
            "AND t.status = 'active' WHERE ct.post_id = ANY(%s::uuid[]) "
            "ORDER BY ct.post_id, ct.confidence DESC, ct.topic_id",
            [ids],
        )
        found: dict[str, list[tuple[int, float]]] = {}
        labels: dict[int, dict] = {}
        for post_id, topic_id, confidence, slug, label_ar, label_en in cur.fetchall():
            found.setdefault(str(post_id), []).append((int(topic_id), float(confidence)))
            labels[int(topic_id)] = {"slug": slug, "label_ar": label_ar, "label_en": label_en}
    return found, labels


def labels(topic_ids: Iterable[int]) -> list[dict]:
    """``[{slug, label_ar, label_en}]`` of active topics, in the given order."""
    topics = load_aliases().topics
    out = []
    for topic_id in topic_ids:
        t = topics.get(int(topic_id))
        if t:
            out.append({"slug": t["slug"], "label_ar": t["label_ar"], "label_en": t["label_en"]})
    return out
