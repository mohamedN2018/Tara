"""Search v2 query engine: pg_trgm over Arabic-normalised columns (roadmap 1.15).

Why trigrams and not Postgres full-text search: the indexed text is short (names,
handles, titles, and a post's 280-character excerpt), and what users type is
often part of a word, a misspelling or another Arabic spelling. Trigram
``similarity`` / ``word_similarity`` on the ``normalize_ar`` columns matches all
of those (``اسكندريه`` -> ``الإسكندرية``, ``احمد`` -> ``أحمد``, ``ahmd`` ->
``ahmed``), and one GIN index per column serves ``LIKE``, ``%`` and ``<%``.
Full-text search matches whole lexemes only, Postgres's ``arabic`` stemmer does
not fold the spelling variants above, and a second index with its own ranking
scale would have to be merged with this one. Revisit it (or OpenSearch with an
Arabic analyzer, deferred in the roadmap) when long-form text is indexed.

Paging is keyset on ``(round(score, 6), id)`` (or ``(source time, id)`` for
"most recent"). The shared ``CursorPagination`` repeats rows on ties; this one
compares the full key, so no row is ever returned twice and none is skipped.
Permissions are applied in SQL before paging: documents owned by an account in
a block with the viewer, either way, never match.
"""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from django.db.models import BooleanField, CharField, DecimalField, Exists, OuterRef, Q, QuerySet
from django.db.models.expressions import RawSQL
from django.db.models.functions import Cast, Coalesce
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .backend import norm
from .models import BlockedPair, SearchDocument

# Tabs the platform has today, in display order. Videos, reels, companies and
# jobs are added here when their content exists; until then they are not offered.
TABS = ["all", "people", "posts", "photos", "pages", "groups", "marketplace", "events", "hashtags"]
TAB_TYPES = {
    "people": ["user"],
    "posts": ["post"],
    "photos": ["post"],
    "pages": ["page"],
    "groups": ["group"],
    "marketplace": ["listing"],
    "events": ["gathering"],
    "hashtags": ["hashtag"],
}
ALL_TYPES = ["user", "page", "group", "post", "listing", "gathering", "hashtag"]
# Document type names (and the old SPA's "listings") are accepted as tab names.
ALIASES = {
    "user": "people",
    "post": "posts",
    "page": "pages",
    "group": "groups",
    "listing": "marketplace",
    "listings": "marketplace",
    "gathering": "events",
    "hashtag": "hashtags",
}
SUGGEST_TYPES = ["user", "page", "group", "hashtag"]
DATE_PRESETS = {"day": 1, "week": 7, "month": 31, "year": 366}
SORTS = ("relevance", "recent")
MAX_QUERY = 100
MIN_TRIGRAM_QUERY = 3  # shorter queries cannot use the trigram index: prefix match


def resolve_tab(raw: str | None) -> str:
    tab = ALIASES.get(raw or "", raw or "all")
    return tab if tab in TABS else "all"


@dataclass
class Filters:
    sort: str = "relevance"
    since: datetime | None = None
    until: datetime | None = None
    category: str = ""
    location: str = ""
    photos_only: bool = False
    extra: dict = field(default_factory=dict)


def _day(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def parse_filters(params, tab: str) -> Filters:
    """Contextual filters from query params; unknown or malformed values are ignored."""
    f = Filters()
    sort = params.get("sort") or "relevance"
    f.sort = sort if sort in SORTS else "relevance"
    preset = params.get("date")
    if preset in DATE_PRESETS:
        f.since = timezone.now() - timedelta(days=DATE_PRESETS[preset])
    start, end = _day(params.get("from")), _day(params.get("to"))
    tz = timezone.get_current_timezone()
    if start:
        f.since = datetime.combine(start, datetime.min.time(), tzinfo=tz)
    if end:
        f.until = datetime.combine(end + timedelta(days=1), datetime.min.time(), tzinfo=tz)
    f.category = (params.get("category") or "").strip()[:80]
    f.location = (params.get("location") or "").strip()[:80]
    f.photos_only = tab == "photos"
    return f


# ---- cursor ---------------------------------------------------------------------


class BadCursor(ValueError):
    pass


def encode_cursor(sort: str, key, doc_pk: int) -> str:
    raw = json.dumps({"o": sort, "k": str(key), "i": doc_pk}, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(token: str, sort: str):
    try:
        raw = json.loads(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)))
        if raw["o"] != sort or not isinstance(raw["i"], int):
            raise BadCursor("cursor does not match this query")
        if sort == "recent":
            key = parse_datetime(raw["k"])
            if key is None:
                raise BadCursor("bad cursor time")
        else:
            key = Decimal(raw["k"])
        return key, raw["i"]
    except (ValueError, KeyError, TypeError, binascii.Error, InvalidOperation) as exc:
        raise BadCursor(str(exc)) from exc


# ---- matching -------------------------------------------------------------------


def _like_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _match_sql(qn: str) -> tuple[str, list, str, list]:
    """(WHERE condition, params, score expression, params) for the normalised query.

    The condition only uses operators the GIN trigram indexes serve. The score
    takes the best of title similarity, word similarity in the title, and word
    similarity in the body (weighted lower), plus a bonus for an exact title, a
    title prefix and a word prefix, so "Ahmed" ranks above "Mohamed Ahmed".
    """
    esc = _like_escape(qn)
    prefix, word_prefix, inside = f"{esc}%", f"% {esc}%", f"%{esc}%"
    bonus = (
        "CASE WHEN title_norm = %s THEN 0.6 WHEN title_norm LIKE %s THEN 0.35"
        " WHEN title_norm LIKE %s THEN 0.2 ELSE 0 END"
    )
    bonus_params = [qn, prefix, word_prefix]
    if len(qn) < MIN_TRIGRAM_QUERY:
        cond = "(title_norm LIKE %s OR title_norm LIKE %s)"
        return cond, [prefix, word_prefix], f"0.4 + {bonus}", bonus_params
    cond = (
        "(title_norm LIKE %s OR title_norm %% %s OR %s <%% title_norm"
        " OR body_norm LIKE %s OR %s <%% body_norm)"
    )
    score = (
        "GREATEST(similarity(title_norm, %s), word_similarity(%s, title_norm),"
        " 0.8 * word_similarity(%s, body_norm),"
        " CASE WHEN body_norm LIKE %s THEN 0.5 ELSE 0 END)"
        f" + {bonus}"
    )
    return (
        cond,
        [inside, qn, qn, inside, qn],
        score,
        [qn, qn, qn, inside, *bonus_params],
    )


def _visible(qs: QuerySet, viewer_id: str) -> QuerySet:
    """Drop documents whose owner is in a block with the viewer, either way (in SQL).

    A post published as a page is owned by the page, so it also goes when the
    page's owner is in a block with the viewer: post answers 404 for it then
    (profile's page visibility), and search must not show its excerpt either.
    """
    blocked = BlockedPair.objects.filter(
        Q(blocker_id=viewer_id, blocked_id=OuterRef("owner_id"))
        | Q(blocked_id=viewer_id, blocker_id=OuterRef("owner_id"))
    )
    blocked_owner_pages = SearchDocument.objects.filter(
        Q(owner_id__in=BlockedPair.objects.filter(blocker_id=viewer_id).values("blocked_id"))
        | Q(owner_id__in=BlockedPair.objects.filter(blocked_id=viewer_id).values("blocker_id")),
        doc_type="page",
        doc_id=Cast(OuterRef("owner_id"), CharField()),
    )
    return qs.filter(~Exists(blocked)).filter(~Q(doc_type="post") | ~Exists(blocked_owner_pages))


def _matching(qn: str, viewer_id: str, doc_types: list[str]) -> QuerySet:
    cond, cond_params, score, score_params = _match_sql(qn)
    qs = SearchDocument.objects.filter(doc_type__in=doc_types)
    # Constant SQL from `_match_sql`; the query text only ever travels as a parameter.
    qs = qs.filter(RawSQL(cond, cond_params, output_field=BooleanField()))  # noqa: S611
    qs = _visible(qs, viewer_id)
    return qs.annotate(
        score=RawSQL(  # noqa: S611 - constant SQL, bound parameters
            f"round(({score})::numeric, 6)", score_params, output_field=DecimalField()
        )
    )


def _apply_filters(qs: QuerySet, f: Filters) -> QuerySet:
    if f.photos_only:
        qs = qs.filter(category="photo")
    if f.since or f.until:
        qs = qs.annotate(when=Coalesce("source_at", "created_at"))
        if f.since:
            qs = qs.filter(when__gte=f.since)
        if f.until:
            qs = qs.filter(when__lt=f.until)
    if f.category:
        qs = qs.filter(category__iexact=f.category)
    if f.location:
        loc = norm(f.location, 160)
        if loc:
            qs = qs.filter(location_norm__contains=loc)
    return qs


def search(
    q: str,
    *,
    viewer_id: str,
    doc_types: list[str] | None = None,
    filters: Filters | None = None,
    cursor: str | None = None,
    limit: int = 20,
) -> tuple[list[SearchDocument], str | None]:
    """One keyset page of matching documents and the next cursor (None at the end).

    Raises ``BadCursor`` for a cursor that is malformed or from another sort.
    """
    f = filters or Filters()
    qn = norm(q, MAX_QUERY)
    if not qn:
        return [], None
    qs = _apply_filters(_matching(qn, viewer_id, doc_types or ALL_TYPES), f)
    if f.sort == "recent":
        qs = qs.annotate(sort_at=Coalesce("source_at", "created_at"))
        if cursor:
            key, pk = decode_cursor(cursor, "recent")
            qs = qs.filter(Q(sort_at__lt=key) | Q(sort_at=key, id__lt=pk))
        qs = qs.order_by("-sort_at", "-id")
    else:
        if cursor:
            key, pk = decode_cursor(cursor, "relevance")
            qs = qs.filter(Q(score__lt=key) | Q(score=key, id__lt=pk))
        qs = qs.order_by("-score", "-id")
    rows = list(qs[: limit + 1])
    if len(rows) <= limit:
        return rows, None
    rows = rows[:limit]
    last = rows[-1]
    key = last.sort_at.isoformat() if f.sort == "recent" else last.score
    return rows, encode_cursor(f.sort, key, last.id)


def suggest(q: str, *, viewer_id: str, limit: int = 8) -> list[SearchDocument]:
    """Autocomplete over people, pages, groups and hashtags: one SQL query.

    A query starting with ``#`` looks at hashtags only.
    """
    raw = (q or "").strip()
    types = ["hashtag"] if raw.startswith("#") else SUGGEST_TYPES
    qn = norm(raw, MAX_QUERY)
    if not qn:
        return []
    return list(_matching(qn, viewer_id, types).order_by("-score", "-id")[:limit])
