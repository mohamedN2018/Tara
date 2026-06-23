"""Event consumers that keep the search index in sync with source contexts."""

from __future__ import annotations

from tara_events import on_event
from tara_events.envelope import EventEnvelope

from . import backend


@on_event("profile.updated")
def on_profile_updated(e: EventEnvelope) -> None:
    p = e.payload
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


@on_event("listing.created")
def on_listing_created(e: EventEnvelope) -> None:
    p = e.payload
    backend.index_document(
        "listing",
        p["listing_id"],
        title=p.get("title", ""),
        body=p.get("title", ""),
        owner_id=p.get("seller_id"),
    )


@on_event("listing.status.changed")
def on_listing_status(e: EventEnvelope) -> None:
    p = e.payload
    # Only active listings should be discoverable.
    if p.get("to") != "active":
        backend.delete_document("listing", p["listing_id"])
