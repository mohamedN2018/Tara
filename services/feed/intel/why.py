"""'Why am I seeing this?' v2 (02 section 20, WP 4.8).

``explain(viewer, item_type, item_id, token)`` returns the reasons an item was
served to this viewer, or ``None``, which the view turns into one identical 404 for
"no such item", "not visible to you" and "never served to you". Two proofs of
serving are accepted:

- a serve token (``st``) that is valid, unexpired and was issued to this viewer for
  this very item (``serve_tokens.verify``), or
- the item is in one of the viewer's current ranking sessions (session v2, one per
  surface, ``intel.ranking.session.contains``).

Served is not enough: the item must still be visible now. A connection item needs
the viewer's own fan-out row, after hides, snoozes and mutes; any other source goes
back through the eligibility filter (fail closed), with the viewer's age claims.

Factors are honest and the viewer's own: the relationship that brought the item
(fan-out reason, followed page, joined group, a public pool, or a Home discovery
pool: ``rec_popular`` / ``rec_fresh``, WP 4b.6), and in ``for_you``
only, the ranking terms that moved it: the factor codes the session stored at
ranking time when the session proves serving, else the ``home@1`` terms that apply
to the author now (favorite author, frequent interaction, the viewer's own "don't
like" feedback). Nothing about other users' private actions, no integrity
detector names (``explain.visible`` drops them), no experiment names. A topic factor
(phase 6 onwards) never carries a sensitive topic's label: ``topic_factor`` masks it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from django.utils import timezone

from . import config, discovery, eligibility, hot
from .models import ContentRef, ItemType
from .ranking import serve_tokens
from .ranking import session as rank_session
from .retrieval.sources import CONNECTIONS, FOLLOW_PULL, GROUPS, Candidate

POST_KINDS = (ItemType.POST, ItemType.REEL, ItemType.VIDEO)
CHRONOLOGICAL = ("recent", "following", "friends", "favorites")


@dataclass(frozen=True)
class Served:
    source: str  # an eligibility source, or a fan-out reason (self, friend, follow)
    mode: str | None
    surface: str
    cfg_version: str | None
    # Factor names stored in the ranking session (session proof only), else None.
    factors: tuple[str, ...] | None = None
    # The candidate reason when the proof carries it (session v2 entries do).
    reason: str | None = None


# Session factor names -> why codes. ``reason`` is the relationship line; terms not
# listed (freshness, engagement, predictions, quality) are not explained.
SESSION_FACTOR_CODES = {
    "favorite": "favorite",
    "affinity": "interacted_author",
    "dislike": "demoted_feedback",
    "shared_groups": "shared_groups",
    "conversation": "conversation",
}
_AUTHOR_FACTORS = frozenset({"favorite", "interacted_author", "shared_groups", "conversation"})


def topic_factor(slug: str, *, sensitive: bool) -> dict:
    """A topic reason. A sensitive topic is only ever "a topic you follow"."""
    if sensitive:
        return {"code": "rec_topic_sensitive"}
    return {"code": "rec_topic", "topic": slug}


def _from_session(viewer_id, post_id) -> Served | None:
    """The post's entry in one of the viewer's current ranking sessions (v2 packs
    post ids, one key per surface)."""
    for surface in hot.RANK_SURFACES:
        entry = rank_session.contains(surface, viewer_id, post_id)
        if entry is None:
            continue
        try:
            stored = hot.hot().get(rank_session.key(surface, viewer_id)) or {}
        except Exception:  # noqa: BLE001 - the entry is proof enough; the version is a detail
            stored = {}
        names = tuple(name for name, _ in rank_session.factor_names(entry))
        mode = "for_you" if surface == "home" else None
        return Served(entry.source or "", mode, surface, stored.get("cfg"), names, entry.reason)
    return None


def _served(viewer_id, item_type: str, item_id: str, token: str | None) -> Served | None:
    if token:
        claims = serve_tokens.verify(token, viewer_id, item_type, item_id)
        if claims is not None:
            served = Served(claims.source or "", claims.reason, claims.surface, claims.cfg_version)
            if served.source == discovery.SOURCE:
                # The token names the source, not the pool: the session entry does.
                entry = _from_session(viewer_id, item_id)
                if entry is not None and entry.source == discovery.SOURCE:
                    served = Served(
                        served.source,
                        served.mode,
                        served.surface,
                        served.cfg_version,
                        None,
                        entry.reason,
                    )
            return served
    return _from_session(viewer_id, item_id)


def _viewer(claims: dict) -> eligibility.Viewer:
    return eligibility.Viewer.from_claims(claims)


def explain(claims: dict, item_type: str, item_id: str, token: str | None) -> dict | None:
    from feed import ranking
    from feed.models import Affinity, RelationshipFlag
    from feed.readmodels import flagged_ids

    viewer_id = str(claims.get("sub"))
    if item_type not in POST_KINDS:
        return None
    try:
        item_id = str(uuid.UUID(str(item_id)))
    except ValueError:
        return None
    served = _served(viewer_id, item_type, item_id, token)
    if served is None:
        return None

    row = ranking.visible_items(viewer_id).filter(post_id=item_id).first()
    pulled = served.source in eligibility.NON_CONNECTION
    if row is not None:
        candidate = Candidate(
            item_id, str(row.author_id), CONNECTIONS, row.reason, row.post_created_at
        )
        author_type = (row.snapshot or {}).get("author_type") or ""
    elif pulled:
        ref = ContentRef.objects.filter(post_id=item_id).first()
        if ref is None or ref.author_id is None:
            return None  # fail closed: nothing to check visibility against
        reason = served.source
        if served.source == discovery.SOURCE:
            # rec_popular / rec_fresh: from the session entry, else the pool that holds
            # it now; never guessed (a post in neither pool explains as a public pool).
            reason = served.reason or discovery.reason_of(item_id, ref.lang) or served.source
        candidate = Candidate(
            item_id, str(ref.author_id), served.source, reason, ref.created_at, ref.type
        )
        author_type = ref.author_type
    else:
        return None  # a connection item the viewer no longer has (unfollowed, hidden, ...)

    home = config.for_surface("home")
    # The rules themselves, not ``filter``: an explanation is not a serve, so it
    # must not move the eligibility drop counters.
    ctx = eligibility.load_context(_viewer(claims), [candidate], home)
    if eligibility.evaluate(candidate, ctx) is not None:
        return None

    author = candidate.author_id
    factors: list[dict] = [_relationship(candidate, author_type, author, viewer_id)]
    mode = served.mode if served.mode in ("for_you", *CHRONOLOGICAL) else None
    block = home.section("why")
    if served.factors is not None and author != viewer_id:
        for name in served.factors:
            code = SESSION_FACTOR_CODES.get(name)
            if code and all(f["code"] != code for f in factors):
                entry = {"code": code}
                if code in _AUTHOR_FACTORS:
                    entry["author_id"] = author
                factors.append(entry)
        factors = factors[: block["max_factors"]]
    elif mode == "for_you" and author != viewer_id:
        if author in {
            str(t)
            for t in flagged_ids(viewer_id, RelationshipFlag.Kind.FAVORITE).values_list(
                "target_id", flat=True
            )
        }:
            factors.append({"code": "favorite", "author_id": author})
        interactions = (
            Affinity.objects.filter(account_id=viewer_id, author_id=author)
            .values_list("interactions", flat=True)
            .first()
        ) or 0
        if interactions >= block["interacted_min_interactions"]:
            factors.append({"code": "interacted_author", "author_id": author})
        if ranking.author_penalties(viewer_id, [author]).get(author, 0) > 0:
            factors.append({"code": "demoted_feedback"})
        factors = factors[: block["max_factors"]]
    return {
        "item": f"{item_type}:{item_id}",
        "mode": mode,
        "surface": served.surface,
        "cfg_version": served.cfg_version,
        "factors": factors,
        "generated_at": timezone.now().isoformat(),
    }


def _relationship(c: Candidate, author_type: str, author: str, viewer_id: str) -> dict:
    if c.source == CONNECTIONS:
        if author == viewer_id or c.reason == "self":
            return {"code": "self"}
        if c.reason == "friend":
            return {"code": "friend", "author_id": author}
        code = "page_follow" if author_type == "page" else "follow"
        return {"code": code, "author_id": author}
    if c.source == FOLLOW_PULL:
        code = "page_follow" if author_type == "page" else "follow"
        return {"code": code, "author_id": author}
    if c.source == GROUPS:
        return {"code": "group_member"}
    if c.source == discovery.SOURCE and c.reason in discovery.BUCKET_OF:
        return {"code": c.reason}
    return {"code": "public_pool", "format": c.type or "post"}
