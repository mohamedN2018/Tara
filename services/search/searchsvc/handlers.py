"""Event consumers that keep the search index in sync with source contexts."""

from __future__ import annotations

from tara_events import on_event
from tara_events.envelope import EventEnvelope

from . import backend
from .models import BlockedPair


@on_event("profile.updated")
def on_profile_updated(e: EventEnvelope) -> None:
    p = e.payload
    if p.get("visibility", "public") != "public":
        backend.delete_document("user", e.subject_id)
        return
    title = " ".join(filter(None, [p.get("handle"), p.get("display_name")]))
    backend.index_document("user", e.subject_id, title=title, body="", owner_id=e.subject_id)


@on_event("page.created")
def on_page_created(e: EventEnvelope) -> None:
    p = e.payload
    backend.index_document(
        "page",
        e.subject_id,
        title=p.get("name", p.get("handle", "")),
        body=p.get("handle", ""),
        owner_id=p.get("owner"),
    )


@on_event("post.created")
def on_post_created(e: EventEnvelope) -> None:
    p = e.payload
    if p.get("audience") == "public":  # only public posts are searchable
        backend.index_document(
            "post", p["post_id"], title="", body=p.get("excerpt", ""), owner_id=p.get("author_id")
        )
    for tag in p.get("hashtags", []):
        backend.index_document("hashtag", tag, title=f"#{tag}", body="")


@on_event("post.deleted")
def on_post_deleted(e: EventEnvelope) -> None:
    backend.delete_document("post", e.payload.get("post_id", e.subject_id))


@on_event("post.updated")
def on_post_updated(e: EventEnvelope) -> None:
    p = e.payload
    if p.get("audience") == "public":
        backend.index_document(
            "post", p["post_id"], title="", body=p.get("excerpt", ""), owner_id=p.get("author_id")
        )
    else:
        backend.delete_document("post", p["post_id"])


@on_event("listing.status.changed")
def on_listing_status(e: EventEnvelope) -> None:
    p = e.payload
    # Only active listings are discoverable, so drafts never reach the index.
    if p.get("to") == "active":
        title = p.get("title", "")
        backend.index_document(
            "listing", p["listing_id"], title=title, body=title, owner_id=p.get("seller_id")
        )
    else:
        backend.delete_document("listing", p["listing_id"])


@on_event("user.blocked")
def on_user_blocked(e: EventEnvelope) -> None:
    p = e.payload
    BlockedPair.objects.get_or_create(blocker_id=p["blocker_id"], blocked_id=p["blocked_id"])


@on_event("user.unblocked")
def on_user_unblocked(e: EventEnvelope) -> None:
    p = e.payload
    BlockedPair.objects.filter(blocker_id=p["blocker_id"], blocked_id=p["blocked_id"]).delete()
