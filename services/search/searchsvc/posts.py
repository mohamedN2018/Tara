"""Post and hashtag indexing: only live PUBLIC posts reach the index.

Invariant: a hashtag document exists only while at least one live public post
carries the tag (a ``PublicPostHashtag`` row). Friends, followers, only-me,
close-friends and group posts never create one. A post that is deleted, removed
by moderation (post-service emits ``post.deleted`` for that), made non-public or
edited to drop a tag releases its rows, and a hashtag document goes with its
last row. Search, autocomplete and anything built on hashtag documents (or on
``PublicPostHashtag``, e.g. trending) therefore only ever see public usage.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime

from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from tara_events.envelope import EventEnvelope

from . import backend
from .models import PostIndexState, PublicPostHashtag, SearchDocument

logger = logging.getLogger("tara.search.posts")

PUBLIC = "public"
# post-service truncates `excerpt` to this many characters (`body[:280]`).
EXCERPT_LIMIT = 280
# Mirrors post-service `extract_hashtags` so a derived tag matches the stored one.
_HASHTAG_RE = re.compile(r"(?<![\w/&#])#(\w{1,80})")
_TAG_RE = re.compile(r"\w{1,80}")


def is_public(payload: dict) -> bool:
    """Fail closed: anything but an explicit public, non-group audience is private."""
    return payload.get("audience") == PUBLIC and not payload.get("group_id")


def clean_tags(raw) -> set[str]:
    """Normalise a payload's hashtag list; drop anything that is not a valid tag."""
    tags = set()
    for tag in raw if isinstance(raw, list) else []:
        if not isinstance(tag, str):
            continue
        tag = tag.strip().lstrip("#").lower()
        if _TAG_RE.fullmatch(tag):
            tags.add(tag)
    return tags


def tags_from_excerpt(excerpt: str) -> set[str]:
    """Hashtags in an excerpt, minus a trailing one the truncation may have cut short."""
    excerpt = excerpt or ""
    truncated = len(excerpt) >= EXCERPT_LIMIT
    return {
        m.group(1).lower()
        for m in _HASHTAG_RE.finditer(excerpt)
        if not (truncated and m.end() == len(excerpt))
    }


def tags_for(payload: dict) -> set[str]:
    # `post.created` and `post.updated` carry the full list. Older `post.updated`
    # events do not, so their tags are re-derived from the excerpt: an edit that
    # drops a tag then drops it here too, instead of leaving a stale link behind.
    if isinstance(payload.get("hashtags"), list):
        return clean_tags(payload["hashtags"])
    return tags_from_excerpt(payload.get("excerpt", ""))


def _occurred_at(e: EventEnvelope) -> datetime:
    try:
        when = parse_datetime(e.occurred_at)
    except (TypeError, ValueError):
        when = None
    if when is None:
        return timezone.now()
    if timezone.is_naive(when):
        when = when.replace(tzinfo=UTC)
    return when


def apply_post_event(e: EventEnvelope, *, deleted: bool = False) -> None:
    """Apply post.created / post.updated / post.deleted, newest fact wins."""
    p = e.payload
    post_id = str(p.get("post_id") or e.subject_id)
    occurred = _occurred_at(e)
    public = not deleted and is_public(p)
    with transaction.atomic():
        state, created = PostIndexState.objects.select_for_update().get_or_create(
            post_id=post_id,
            defaults={"occurred_at": occurred, "public": public, "deleted": deleted},
        )
        if not created:
            if occurred < state.occurred_at or (state.deleted and occurred == state.occurred_at):
                logger.info("ignored stale %s for post %s", e.event_type, post_id)
                return
            state.occurred_at, state.public, state.deleted = occurred, public, deleted
            state.save(update_fields=["occurred_at", "public", "deleted"])

        author_id = p.get("author_id") or None
        if public:
            backend.index_document("post", post_id, **post_doc(post_id, p, author_id))
            set_post_hashtags(post_id, tags_for(p), author_id=author_id)
        else:
            backend.delete_document("post", post_id)
            set_post_hashtags(post_id, set())


# Post types whose media are photos: the "photos" search tab.
PHOTO_TYPES = {"image"}
MAX_MEDIA_IDS = 4


def post_doc(post_id: str, p: dict, author_id) -> dict:
    """Document fields for a public post. ``post.updated`` from before 1.15 has no
    type, media or creation time: those are kept from the existing document."""
    previous = (
        SearchDocument.objects.filter(doc_type="post", doc_id=post_id)
        .values_list("extra", flat=True)
        .first()
    ) or {}
    post_type = p.get("type") or previous.get("post_type") or "text"
    media = p.get("media_ids")
    media = [str(m) for m in media][:MAX_MEDIA_IDS] if isinstance(media, list) else None
    if media is None:
        media = previous.get("media_ids") or []
    created_at = p.get("created_at") or previous.get("created_at")
    photo = post_type in PHOTO_TYPES and bool(media)
    return {
        "title": "",
        "body": p.get("excerpt", ""),
        "owner_id": author_id,
        "category": "photo" if photo else post_type,
        "source_at": _parse(created_at),
        "extra": {
            "author_type": p.get("author_type") or previous.get("author_type") or "user",
            "post_type": post_type,
            "media_ids": media,
            "created_at": created_at,
        },
    }


def _parse(value) -> datetime | None:
    try:
        moment = parse_datetime(value) if value else None
    except (TypeError, ValueError):
        return None
    if moment is not None and timezone.is_naive(moment):
        moment = moment.replace(tzinfo=UTC)
    return moment


def set_post_hashtags(post_id: str, tags: set[str], *, author_id=None) -> None:
    """Make the post's public hashtag links exactly ``tags``; purge orphaned documents."""
    current = set(PublicPostHashtag.objects.filter(post_id=post_id).values_list("tag", flat=True))
    affected = sorted(current | tags)
    if not affected:
        return
    # Lock the affected hashtag documents, in one fixed order so two posts never
    # deadlock, so "last link gone -> drop the document" cannot race another post.
    list(
        SearchDocument.objects.select_for_update()
        .filter(doc_type="hashtag", doc_id__in=affected)
        .order_by("doc_id")
        .values_list("id", flat=True)
    )
    removed = current - tags
    if removed:
        PublicPostHashtag.objects.filter(post_id=post_id, tag__in=removed).delete()
    PublicPostHashtag.objects.bulk_create(
        [PublicPostHashtag(post_id=post_id, tag=t, author_id=author_id) for t in tags - current],
        ignore_conflicts=True,
    )
    for tag in sorted(tags):
        backend.index_document("hashtag", tag, **hashtag_doc(tag))
    if removed:
        still_used = set(
            PublicPostHashtag.objects.filter(tag__in=removed).values_list("tag", flat=True)
        )
        for tag in sorted(removed - still_used):
            backend.delete_document("hashtag", tag)


def hashtag_doc(tag: str) -> dict:
    return {"title": f"#{tag}", "body": "", "extra": {"tag": tag}}


_CHUNK = 500
_HIDDEN = Q(public=False) | Q(deleted=True)


def reconcile_hashtags() -> dict:
    """Rebuild the public links, then make hashtag documents match them. Idempotent.

    Links are rebuilt, not just topped up: during a deploy the old consumer keeps
    running after migration 0004 and deletes or re-indexes post documents without
    touching the links, so a link alone proves nothing.

    1. Posts the indexer marked non-public or deleted lose their post document and
       links (only reachable if an older indexer wrote after the new one).
    2. Posts with no ``PostIndexState`` row (only old code indexed them) get links
       exactly equal to the tags in their post document: extra links go.
    3. Links of a post with no post document go (the post was deleted or made
       non-public). The indexer writes both in one transaction, so a live public
       post always has its document.
    4. Only then: hashtag documents no link backs are deleted (Postgres and
       OpenSearch), and linked tags whose document is missing get it back.

    Each repair locks what the consumer locks and re-checks, so running it next to
    the live consumer never resurrects anything.
    """
    posts_purged, links_removed = _drop_hidden_posts()
    links_added, removed = _rebuild_untracked_links()
    links_removed += removed
    post_doc = SearchDocument.objects.filter(doc_type="post", doc_id=OuterRef("post_id"))
    links_removed += PublicPostHashtag.objects.filter(~Exists(post_doc)).delete()[0]

    linked = set(PublicPostHashtag.objects.values_list("tag", flat=True).distinct())
    indexed = set(
        SearchDocument.objects.filter(doc_type="hashtag").values_list("doc_id", flat=True)
    )
    orphans = indexed - linked
    if backend.opensearch_enabled():
        orphans |= backend.os_doc_ids("hashtag") - linked
    purged = sum(_purge_hashtag_if_unbacked(tag) for tag in sorted(orphans))
    restored = sum(_restore_hashtag_if_backed(tag) for tag in sorted(linked - indexed))
    return {
        "posts_purged": posts_purged,
        "links_added": links_added,
        "links_removed": links_removed,
        "hashtags_purged": purged,
        "hashtags_restored": restored,
    }


def _drop_hidden_posts() -> tuple[int, int]:
    hidden = PostIndexState.objects.filter(_HIDDEN).values("post_id")
    candidates = set(
        SearchDocument.objects.filter(doc_type="post", doc_id__in=hidden).values_list(
            "doc_id", flat=True
        )
    ) | set(PublicPostHashtag.objects.filter(post_id__in=hidden).values_list("post_id", flat=True))
    posts = links = 0
    for post_id in sorted(candidates):
        with transaction.atomic():
            # Same first lock as `apply_post_event`, so a concurrent event waits for us.
            state = PostIndexState.objects.select_for_update().filter(post_id=post_id).first()
            if state is None or (state.public and not state.deleted):
                continue  # made public again meanwhile: the consumer owns it
            if SearchDocument.objects.filter(doc_type="post", doc_id=post_id).exists():
                backend.delete_document("post", post_id)
                posts += 1
            links += PublicPostHashtag.objects.filter(post_id=post_id).delete()[0]
    return posts, links


def _rebuild_untracked_links() -> tuple[int, int]:
    """Links of posts only old code indexed = the tags in their post document."""
    untracked = ~Exists(PostIndexState.objects.filter(post_id=OuterRef("doc_id")))
    added = removed = 0
    last = None
    while True:
        qs = SearchDocument.objects.filter(untracked, doc_type="post")
        if last is not None:
            qs = qs.filter(doc_id__gt=last)
        chunk = list(qs.order_by("doc_id").values_list("doc_id", "body")[:_CHUNK])
        if not chunk:
            return added, removed
        last = chunk[-1][0]
        have: dict[str, set[str]] = {post_id: set() for post_id, _ in chunk}
        for post_id, tag in PublicPostHashtag.objects.filter(post_id__in=list(have)).values_list(
            "post_id", "tag"
        ):
            have[post_id].add(tag)
        for post_id, body in chunk:
            if tags_from_excerpt(body) != have[post_id]:
                a, r = _sync_untracked_post(post_id)
                added, removed = added + a, removed + r


def _sync_untracked_post(post_id: str) -> tuple[int, int]:
    with transaction.atomic():
        # The consumer locks (or deletes) this row before it touches the post's links.
        doc = (
            SearchDocument.objects.select_for_update()
            .filter(doc_type="post", doc_id=post_id)
            .only("body", "owner_id")
            .first()
        )
        if doc is None or PostIndexState.objects.filter(post_id=post_id).exists():
            return 0, 0  # handled meanwhile; a link left without a document goes in step 3
        want = tags_from_excerpt(doc.body)
        have = set(PublicPostHashtag.objects.filter(post_id=post_id).values_list("tag", flat=True))
        extra, missing = have - want, want - have
        if extra:
            PublicPostHashtag.objects.filter(post_id=post_id, tag__in=extra).delete()
        PublicPostHashtag.objects.bulk_create(
            [PublicPostHashtag(post_id=post_id, tag=t, author_id=doc.owner_id) for t in missing],
            ignore_conflicts=True,
        )
        return len(missing), len(extra)


def _purge_hashtag_if_unbacked(tag: str) -> bool:
    with transaction.atomic():
        # A post adding this tag locks the document first (`set_post_hashtags`).
        list(
            SearchDocument.objects.select_for_update()
            .filter(doc_type="hashtag", doc_id=tag)
            .values_list("id", flat=True)
        )
        if PublicPostHashtag.objects.filter(tag=tag).exists():
            return False  # a public post started using it meanwhile
        backend.delete_document("hashtag", tag)
        return True


def _restore_hashtag_if_backed(tag: str) -> bool:
    with transaction.atomic():
        # Hold a backing link: a post dropping it waits, then removes the document itself.
        backing = PublicPostHashtag.objects.select_for_update().filter(tag=tag)
        if not list(backing.values_list("id", flat=True)[:1]):
            return False  # its last public post went away meanwhile
        backend.index_document("hashtag", tag, **hashtag_doc(tag))
        return True
