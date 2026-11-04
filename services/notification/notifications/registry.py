"""The notification kind registry: one place for category, channels, grouping and links.

Every kind the service writes is declared here. The registry decides:

* the **category** (preferences can be set per kind or per category),
* the **default channels** (``in_app`` and ``push``) when the user set nothing,
* **aggregation**: whether events of the kind merge into one unread row, keyed
  per subject (``"X and 3 others reacted to your post"``) or per recipient
  (``"X and 3 others started following you"``), and for how long a row stays open,
* the **resolutions** a client may record (the outcome of an inline action),
* the **deep link** the app and the push notification open (``build_url``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any
from urllib.parse import quote

CHANNELS = ("in_app", "push")

CATEGORIES = (
    "social",
    "connections",
    "messages",
    "marketplace",
    "pages",
    "ads",
    "groups",
    "account",
)

# Aggregation scopes.
PER_SUBJECT = "subject"  # one open row per (recipient, kind, subject_ref)
PER_RECIPIENT = "recipient"  # one open row per (recipient, kind)


@dataclass(frozen=True)
class Kind:
    name: str
    category: str
    in_app: bool = True
    push: bool = True
    aggregate: str | None = None
    # An open aggregate older than this (by its first event) is closed, and the
    # next event starts a new row.
    window: timedelta = timedelta(hours=24)
    # Push again when an event merges into an open row (otherwise only the
    # first event of a row is pushed; the in-app row still updates live).
    push_on_merge: bool = False
    # Outcomes of an inline action the client may record on the row.
    resolutions: frozenset[str] = field(default_factory=frozenset)
    # False while no consumer writes this kind: Settings does not offer a
    # toggle that would do nothing (``describe`` leaves it out).
    live: bool = True


_KINDS = [
    Kind("post.reaction", "social", aggregate=PER_SUBJECT),
    Kind("post.comment", "social", aggregate=PER_SUBJECT),
    Kind("comment.reply", "social"),
    Kind("mention", "social"),
    Kind("post.tag", "social"),  # tagged in a post (2C)
    Kind("video.ready", "social"),  # your uploaded video finished processing (5.2)
    Kind("post.share", "social", aggregate=PER_SUBJECT),
    Kind(
        "friend.request",
        "connections",
        resolutions=frozenset({"accepted", "declined", "expired"}),
    ),
    Kind("friend.accepted", "connections"),
    Kind(
        "follow",
        "connections",
        aggregate=PER_RECIPIENT,
        resolutions=frozenset({"followed_back"}),
    ),
    # One row per conversation until it is read (by the user or by `message.read`).
    Kind(
        "message",
        "messages",
        aggregate=PER_SUBJECT,
        window=timedelta(days=7),
        push_on_merge=True,
    ),
    # A message to a Page you help run (its team is not in the conversation):
    # one row per thread, opening the page inbox on it.
    Kind(
        "message.page",
        "pages",
        aggregate=PER_SUBJECT,
        window=timedelta(days=7),
        push_on_merge=True,
    ),
    # Calls (3.7). `call` is the push-only ring: no rows, but its push setting
    # silences ringing. `call.missed` is the in-app row; its own push is off by
    # default because the ring push is replaced by a missed-call push instead.
    Kind("call", "messages", in_app=False, push=True),
    Kind("call.missed", "messages", push=False),
    Kind("listing.status", "marketplace"),
    # A buyer's first inquiry on a listing (`marketplace.inquiry.created`, commerce_handlers).
    Kind("listing.inquiry", "marketplace", aggregate=PER_SUBJECT),
    # Registered ahead of their producers, and hidden from Settings until a
    # consumer writes them: `user.followed` names no page owner, and
    # `ad.review.decided` names no advertiser.
    Kind("page.follow", "pages", aggregate=PER_SUBJECT, live=False),
    Kind("ad.review", "ads", live=False),
    # Events (gatherings in post, 1.13). New RSVPs reach the host as one row per event.
    Kind("gathering.invite", "social"),
    Kind("gathering.reminder", "social"),
    Kind("gathering.update", "social"),
    Kind("gathering.cancel", "social"),
    Kind("gathering.rsvp", "social", aggregate=PER_SUBJECT),
    # Groups (profile 1.11; posts and announcements from post). Requests reach the
    # group's staff as one row per group; new posts only reach members who turned
    # them on for that group (``notify_posts``, off by default).
    Kind("group.invite", "groups", resolutions=frozenset({"joined", "declined", "expired"})),
    Kind("group.request", "groups", aggregate=PER_SUBJECT),
    Kind("group.approved", "groups"),
    Kind("group.post", "groups", aggregate=PER_SUBJECT),
    Kind("group.role", "groups"),
    Kind("group.announcement", "groups"),
    # Stories (post 1.9): reactions reach the author as one row per story.
    Kind("story.reaction", "social", aggregate=PER_SUBJECT),
    # Account status (T7): decisions on your content or account, the outcome of
    # your appeal, and notices from the Tara team. Rows open the Support inbox.
    Kind("moderation.decision", "account"),
    Kind("moderation.appeal", "account"),
    Kind("system.notice", "account"),
]

KINDS: dict[str, Kind] = {k.name: k for k in _KINDS}

# Kinds written before the registry existed fall back to this.
_UNKNOWN = Kind("unknown", "social")

# `data` is stored for the client (labels, links, inline actions). It is never
# put on the event bus, holds ids and short codes only, and stays under 1 KB.
DATA_KEYS = frozenset(
    {
        "post_id",
        "comment_id",
        "parent_id",
        "share_post_id",
        "reaction_type",
        "conversation_id",
        "message_id",
        "message_count",
        "message_type",
        "call_id",
        "call_kind",
        "request_id",
        "listing_id",
        "status",
        "page_id",
        "page_handle",
        "campaign_id",
        "decision",
        "gathering_id",
        "window",
        "group_id",
        "group_handle",
        "role",
        "story_id",
        "case_id",
        "target_type",
        "notice_id",
        # A page or support team's reply is from the Page / Tara Support (chat).
        "sender_kind",
        "sender_name",
        # A message to a Page: which page's inbox it is in.
        "page_name",
    }
)
MAX_DATA_BYTES = 1024
MAX_DATA_VALUE = 120


def get(kind: str) -> Kind:
    return KINDS.get(kind, _UNKNOWN)


def category_of(kind: str) -> str:
    return get(kind).category


def preference_keys() -> frozenset[str]:
    """Keys a preference map may hold: every kind and every category."""
    return frozenset(KINDS) | frozenset(CATEGORIES)


def channel_enabled(prefs: dict | None, kind: str, channel: str) -> bool:
    """Lookup order: the user's choice for the kind, then for its category, then the default."""
    spec = get(kind)
    prefs = prefs if isinstance(prefs, dict) else {}
    for key in (kind, spec.category):
        chosen = prefs.get(key)
        if isinstance(chosen, dict) and isinstance(chosen.get(channel), bool):
            return chosen[channel]
    return getattr(spec, channel, True)


def aggregate_key(kind: str, subject_ref: str) -> str:
    """The open-row key for an aggregated kind, or ``""`` when the kind does not aggregate."""
    spec = get(kind)
    if spec.aggregate == PER_SUBJECT and subject_ref:
        return f"{kind}|{subject_ref}"
    if spec.aggregate == PER_RECIPIENT:
        return kind
    return ""


def closed_key(key: str, notification_id: Any) -> str:
    """Key for a closed aggregate: unique to its row, so it never blocks a new one."""
    return f"{key}~{notification_id}"


def clean_data(data: dict | None) -> dict:
    """Keep whitelisted keys with short scalar values, under ``MAX_DATA_BYTES``."""
    out: dict[str, Any] = {}
    for key, value in (data or {}).items():
        if key not in DATA_KEYS or value is None:
            continue
        if isinstance(value, bool | int):
            out[key] = value
        elif isinstance(value, str) and value:
            out[key] = value[:MAX_DATA_VALUE]
    while out and len(json.dumps(out, separators=(",", ":")).encode()) > MAX_DATA_BYTES:
        out.popitem()
    return out


def _ref(ref: str) -> tuple[str, str]:
    kind, _, value = (ref or "").partition(":")
    return kind, quote(value, safe="")


def build_url(
    kind: str,
    *,
    subject_ref: str = "",
    target_ref: str = "",
    actor_id: Any = None,
    actor_count: int = 0,
    data: dict | None = None,
) -> str:
    """The in-app path a click on this notification opens (always a same-origin path)."""
    data = data or {}
    subject, sid = _ref(subject_ref)
    target, tid = _ref(target_ref)

    if kind == "follow" and actor_count > 1:
        return "/connections?tab=followers"
    if kind == "post.share" and actor_count <= 1 and data.get("share_post_id"):
        return f"/posts/{quote(str(data['share_post_id']), safe='')}"
    if subject == "post" and sid:
        url = f"/posts/{sid}"
        return f"{url}?comment={tid}" if target == "comment" and tid else url
    if kind == "message.page" and sid and data.get("page_id"):
        page = quote(str(data["page_id"]), safe="")
        return f"/pages/id/{page}/inbox?conversation={sid}"
    if subject == "conversation" and sid:
        return f"/messages/{sid}"
    if subject == "group" and sid:
        handle = data.get("group_handle")
        return f"/groups/{quote(str(handle), safe='')}" if handle else f"/groups/{sid}"
    if subject == "story" and sid:
        return f"/stories/{sid}"
    if subject == "gathering" and sid:
        return f"/events/{sid}"
    if subject == "listing" and sid:
        return f"/marketplace/{sid}"
    if subject == "page" and sid:
        handle = data.get("page_handle")
        return f"/pages/{quote(str(handle), safe='')}" if handle else f"/pages/id/{sid}"
    if subject in ("campaign", "ad") and sid:
        campaign = data.get("campaign_id")
        return f"/ads/campaigns/{quote(str(campaign), safe='') if campaign else sid}"
    if subject == "case" and sid:
        return f"/support?case={sid}"
    if subject == "notice" and sid:
        return "/support?tab=notices"
    if subject == "account" and sid:
        return f"/u/id/{sid}"
    if actor_id:
        return f"/u/id/{quote(str(actor_id), safe='')}"
    return "/notifications"


def url_for(notification) -> str:
    return build_url(
        notification.kind,
        subject_ref=notification.subject_ref,
        target_ref=notification.target_ref,
        actor_id=notification.actor_id,
        actor_count=notification.actor_count,
        data=notification.data,
    )


def describe() -> list[dict]:
    """The registry as the Settings screen needs it."""
    return [
        {
            "kind": k.name,
            "category": k.category,
            "defaults": {"in_app": k.in_app, "push": k.push},
            "aggregates": k.aggregate is not None,
            "resolutions": sorted(k.resolutions),
        }
        for k in _KINDS
        if k.live
    ]
