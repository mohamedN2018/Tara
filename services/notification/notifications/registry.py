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

CATEGORIES = ("social", "connections", "messages", "marketplace", "pages", "ads")

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


_KINDS = [
    Kind("post.reaction", "social", aggregate=PER_SUBJECT),
    Kind("post.comment", "social", aggregate=PER_SUBJECT),
    Kind("comment.reply", "social"),
    Kind("mention", "social"),
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
    Kind("listing.status", "marketplace"),
    # Registered ahead of their producers (consumer first, emission later).
    Kind("listing.inquiry", "marketplace", aggregate=PER_SUBJECT),
    Kind("page.follow", "pages", aggregate=PER_SUBJECT),
    Kind("ad.review", "ads"),
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
        "message_type",
        "request_id",
        "listing_id",
        "status",
        "page_id",
        "page_handle",
        "campaign_id",
        "decision",
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
    if subject == "conversation" and sid:
        return f"/messages/{sid}"
    if subject == "listing" and sid:
        return f"/marketplace/{sid}"
    if subject == "page" and sid:
        handle = data.get("page_handle")
        return f"/pages/{quote(str(handle), safe='')}" if handle else f"/pages/{sid}"
    if subject in ("campaign", "ad") and sid:
        campaign = data.get("campaign_id")
        return f"/ads/campaigns/{quote(str(campaign), safe='') if campaign else sid}"
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
    ]
