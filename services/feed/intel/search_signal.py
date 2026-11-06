"""The opt-in search signal, feed side (07 WP 8.7-B2, owner decision 7).

Search sends ``search.queried.v1`` only while feed told it the account opted in
(``intel.search_signal.changed``), and the event carries only
``tara_common.signal_terms.term_keys``: sha256 digests of the normalized tokens. Feed
matches them against ``signal_terms.alias_key`` of its own ``keyword`` and ``hashtag``
aliases (computed in process from the alias table, never stored) and keeps the
matched **topic ids** of the last ``session_interest.search_queries`` searches in the
account's ``feed:si`` (``q``), for the current visit only (the hash's TTL). It stores
no digest, no text and no SQL row. Sensitive topics are dropped without the decision-12
opt-in.
"""

from __future__ import annotations

import re
import threading
import time

from tara_common.signal_terms import alias_key

from . import hot, preferences, session_ctx
from .topics import classify

_TTL_S = 300.0
_lock = threading.Lock()
_index: dict[str, object] = {}
_HEX = re.compile(r"^[0-9a-f]{64}$")


def digest_index() -> dict[str, int]:
    """``{alias_key(value_norm): topic_id}`` over the keyword and hashtag aliases."""
    now = time.monotonic()
    with _lock:
        hit = _index.get("idx")
        if hit and hit[0] > now:  # type: ignore[index]
            return hit[1]  # type: ignore[index]
    aliases = classify.load_aliases()
    idx: dict[str, int] = {}
    for value, (topic_id, _w) in aliases.hashtag.items():
        idx.setdefault(alias_key(value), topic_id)
    for value, (topic_id, _strong) in aliases.keyword.items():
        idx.setdefault(alias_key(value), topic_id)
    with _lock:
        _index["idx"] = (now + _TTL_S, idx)
    return idx


def clear_cache() -> None:
    with _lock:
        _index.clear()


def topics_for(term_keys: list[str], sensitive_ok: bool) -> list[int]:
    idx = digest_index()
    topics = classify.load_aliases().topics
    out: list[int] = []
    for key in term_keys[:8]:
        if not isinstance(key, str) or not _HEX.match(key):
            continue
        topic_id = idx.get(key)
        if topic_id is None or topic_id in out:
            continue
        if topics.get(topic_id, {}).get("sensitive") and not sensitive_ok:
            continue
        out.append(topic_id)
    return out


def record(account_id, term_keys: list[str], cfg) -> list[int]:
    """Push one search's topics into ``feed:si.q`` (the last N searches)."""
    pref = preferences.get(account_id)
    found = topics_for(term_keys, bool(pref.sensitive_inference))
    if not found:
        return []
    block = cfg.section("session_interest")
    keep = int(block["search_queries"])
    if keep <= 0:
        return []
    raw = hot.raw_client()
    previous: list[str] = []
    if raw is not None:
        try:
            stored = raw.hget(hot.hot().make_key(hot.session_interest_key(account_id)), "q")
            if stored:
                previous = (stored.decode() if isinstance(stored, bytes) else stored).split(";")
        except Exception:  # noqa: BLE001 - best-effort
            previous = []
    entries = [",".join(str(t) for t in found), *[p for p in previous if p]][:keep]
    session_ctx.si_set_field(account_id, "q", ";".join(entries), int(block["ttl_s"]), create=True)
    return found
