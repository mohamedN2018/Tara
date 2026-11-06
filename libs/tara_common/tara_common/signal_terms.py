"""Hashed search terms for the opt-in search signal (Tara Intelligence WP 8.7-B2).

Owner decision 7: search history is not an interest signal unless the account
opts in. With the opt-in on, search sends feed only ``term_keys(query)``: the
sha256 hex digests of the query's normalized tokens. No query text ever leaves
search. Feed matches the digests against ``alias_key`` of its own topic aliases
and keeps only the matched topic ids; it stores no digest and no text.

Tokens: ``normalize_key(normalize_ar(query))`` split on whitespace, each at
least 2 characters, at most 8 per query, first occurrence order, de-duplicated.
"""

from __future__ import annotations

import hashlib

from tara_common.text import normalize_ar, normalize_key

MIN_TOKEN_LEN = 2
MAX_TERMS = 8


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def tokens(query: str | None) -> list[str]:
    """The normalized tokens of ``query`` (kept inside the calling service)."""
    out: list[str] = []
    for token in normalize_key(normalize_ar(query or "")).split():
        token = token.strip("#")
        if len(token) < MIN_TOKEN_LEN or token in out:
            continue
        out.append(token)
        if len(out) >= MAX_TERMS:
            break
    return out


def term_keys(query: str | None) -> list[str]:
    """sha256 hex of each token of ``query`` (at most ``MAX_TERMS``)."""
    return [_digest(token) for token in tokens(query)]


def alias_key(value_norm: str | None) -> str:
    """The digest a topic alias matches: the same normalization as a token."""
    token = normalize_key(normalize_ar(value_norm or "")).strip("#")
    return _digest(token)
