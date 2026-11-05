"""Paged reads of an owner's intelligence export for graph's backfills (WP 3.3).

The export is ``tara_common.search_export``'s shape (``{as_of, items, next}``).
Pages are read in primary-key order, at most ``rate`` requests per second.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime

import requests
from django.core.management.base import CommandError
from django.utils.dateparse import parse_datetime

from tara_common.auth import mint_internal_token


@dataclass
class Page:
    as_of: datetime
    items: list[dict]


def pages(
    base_url: str, path: str, owner: str, *, limit: int = 200, rate: float = 20.0
) -> Iterator[Page]:
    url = f"{base_url}/internal/v1/{path}"
    gap = 1.0 / rate if rate > 0 else 0.0
    after = ""
    while True:
        began = time.monotonic()
        token = mint_internal_token(issuer="graph", audience=f"{owner}-internal")
        try:
            resp = requests.get(
                url,
                params={"after": after, "limit": limit},
                headers={"Authorization": f"Bearer {token}"},
                timeout=15,
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise CommandError(f"{owner} export unavailable ({exc}); run again") from exc
        data = resp.json()["data"]
        yield Page(parse_datetime(data["as_of"]), data["items"])
        if not data.get("next"):
            return
        after = data["next"]
        wait = gap - (time.monotonic() - began)
        if wait > 0:
            time.sleep(wait)
