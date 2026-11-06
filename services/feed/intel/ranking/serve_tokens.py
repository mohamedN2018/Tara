"""Serve tokens: how telemetry is attributed (02 section 12.2, WP 2.3).

Every item in a ranked response carries ``st``, a compact token signed with
HMAC-SHA256 under ``INTEL_SERVE_TOKEN_SECRET`` (feed only: never ``SECRET_KEY``
nor the internal JWT secret, the same rule as ads' ``ADS_SERVE_TOKEN_SECRET``).
It names the viewer, the item, the surface, the config version and variant, the
candidate source, the reason, the position and the item's quantized rule scores.
``POST /feed/signals/`` stamps attribution on a row only from a token that is
valid, unexpired, issued to the same account and for the same item; client
fields never set it. Nothing is written per impression at serve time.

Binary layout (big-endian), base64url without padding, about 100 to 150 chars::

    u8  version (1 or 2)
    16B viewer uuid
    u8  item type code     16B item uuid
    u8  surface code       u16 position (0xFFFF = none)    u32 issued_at (unix s)
    str8 cfg_version  str8 variant  str8 source  str8 reason   (u8 length + ascii)
    u8  n + n bytes scores (each 0..255)
    -- version 2 only (07 WP 4b.16) --
    u8  fmt code (0 = unknown)        u16 primary topic id (0 until phase 6)
    u8  excerpt length bucket (0 = unknown, else 1 + the index in
        ``exposure.length_buckets``)
    8B  author id prefix (zeros = unknown)          u8 visit ordinal (mod 32)
    16B HMAC-SHA256(key, "tara.intel.st.v1" || all of the above), truncated

Version 2 is what ``issue`` writes; a version-1 token keeps validating until it
expires (``TTL_SECONDS``), its version-2 claims then read as unknown (None).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import logging
import struct
import time
import uuid
from dataclasses import dataclass, field

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from ..models import ItemType, Surface

logger = logging.getLogger("tara.intel.serve_tokens")

VERSION = 2
VERSIONS = frozenset({1, 2})
TTL_SECONDS = 24 * 3600
# A token "issued" further in the future than this is refused (clock skew between replicas).
MAX_FUTURE_SKEW_SECONDS = 300
_DOMAIN = b"tara.intel.st.v1"
_MAC_BYTES = 16
_NO_POSITION = 0xFFFF
_MAX_STR = 24
_MAX_SCORES = 16

# Codes are part of the wire format: append only, never reorder.
_ITEM_TYPES = tuple(ItemType.values)
_SURFACES = tuple(Surface.values)
_POST_KINDS = frozenset({ItemType.POST, ItemType.REEL, ItemType.VIDEO})
# The post formats (post's ``Post.Type``); index 0 is "unknown". Append only.
FORMATS = ("unknown", "text", "image", "video", "link", "share", "poll", "reel")
VISIT_ORD_MOD = 32
_AUTHOR_PREFIX = 8

_warned_dev_key = False


def _dev_key() -> bytes:
    """Development only: derived from feed's SECRET_KEY, so it never equals it."""
    return hmac.new(
        settings.SECRET_KEY.encode(), b"intel-serve-token-dev-fallback", hashlib.sha256
    ).digest()


def _key() -> bytes:
    """Fail closed: production never signs without feed's own serve-token secret."""
    global _warned_dev_key
    secret = settings.INTEL_SERVE_TOKEN_SECRET
    if secret and secret in (settings.SECRET_KEY, settings.TARA_INTERNAL_JWT_SECRET):
        raise ImproperlyConfigured(
            "INTEL_SERVE_TOKEN_SECRET must not reuse FEED_SECRET_KEY or INTERNAL_JWT_SECRET."
        )
    if secret:
        return secret.encode()
    if settings.TARA_ENV == "production":
        raise ImproperlyConfigured("INTEL_SERVE_TOKEN_SECRET is required in production.")
    if not _warned_dev_key:
        _warned_dev_key = True
        logger.warning("INTEL_SERVE_TOKEN_SECRET is not set; using a development key.")
    return _dev_key()


@dataclass(frozen=True)
class ServeClaims:
    viewer: str
    item_type: str
    item_id: str
    surface: str
    position: int | None = None
    issued_at: int = 0
    cfg_version: str | None = None
    variant: str | None = None
    source: str | None = None
    reason: str | None = None
    scores: bytes = field(default=b"")
    # Version 2 (07 WP 4b.16); None on a version-1 token.
    version: int = VERSION
    fmt: str | None = None
    topic_id: int | None = None
    length_bucket: int | None = None
    author_prefix: bytes | None = None
    visit_ord: int | None = None


def _str8(value: str | None) -> bytes:
    raw = (value or "").encode("ascii", "strict")[:_MAX_STR]
    return bytes([len(raw)]) + raw


def _mac(key: bytes, body: bytes) -> bytes:
    return hmac.new(key, _DOMAIN + body, hashlib.sha256).digest()[:_MAC_BYTES]


def format_code(fmt: str | None) -> int:
    return FORMATS.index(fmt) if fmt in FORMATS else 0


def length_bucket(excerpt: str | None, buckets: list[dict]) -> int:
    """0 when the excerpt is unknown (stripped from the snapshot, or no buckets), else
    1 + the index of the first ``exposure.length_buckets`` entry whose ``max_chars``
    holds it (the last one when none does)."""
    if not isinstance(excerpt, str) or not buckets:
        return 0
    n = len(excerpt)
    for i, bucket in enumerate(buckets):
        if n <= int(bucket["max_chars"]):
            return i + 1
    return len(buckets)


def author_prefix(author_id) -> bytes:
    """The first 8 bytes of the author's uuid; zeros when unknown."""
    try:
        return uuid.UUID(str(author_id)).bytes[:_AUTHOR_PREFIX]
    except (TypeError, ValueError, AttributeError):
        return bytes(_AUTHOR_PREFIX)


def quantize(scores) -> bytes:
    """Rule scores in [0, 1] as one byte each (the served-prediction log, ``pred``)."""
    out = bytearray()
    for s in list(scores)[:_MAX_SCORES]:
        out.append(max(0, min(255, round(float(s) * 255))))
    return bytes(out)


def issue(
    viewer,
    item_type: str,
    item_id,
    surface: str,
    *,
    position: int | None = None,
    cfg_version: str | None = None,
    variant: str | None = None,
    source: str | None = None,
    reason: str | None = None,
    scores: bytes = b"",
    now: float | None = None,
    fmt: str | None = None,
    topic_id: int = 0,
    length_bucket: int = 0,
    author_id=None,
    visit_ord: int | None = None,
    version: int = VERSION,
) -> str:
    if version not in VERSIONS:
        raise ValueError(f"unknown serve token version {version}")
    issued = int(now if now is not None else time.time())
    pos = _NO_POSITION if position is None else max(0, min(int(position), _NO_POSITION - 1))
    v2 = b""
    if version >= 2:
        v2 = b"".join(
            [
                bytes([format_code(fmt)]),
                struct.pack(">H", max(0, min(int(topic_id or 0), 0xFFFF))),
                bytes([max(0, min(int(length_bucket or 0), 255))]),
                author_prefix(author_id) if author_id else bytes(_AUTHOR_PREFIX),
                bytes([int(visit_ord or 0) % VISIT_ORD_MOD]),
            ]
        )
    body = b"".join(
        [
            bytes([version]),
            uuid.UUID(str(viewer)).bytes,
            bytes([_ITEM_TYPES.index(item_type)]),
            uuid.UUID(str(item_id)).bytes,
            bytes([_SURFACES.index(surface)]),
            struct.pack(">HI", pos, issued),
            _str8(cfg_version),
            _str8(variant),
            _str8(source),
            _str8(reason),
            bytes([len(scores[:_MAX_SCORES])]),
            bytes(scores[:_MAX_SCORES]),
            v2,
        ]
    )
    token = body + _mac(_key(), body)
    return base64.urlsafe_b64encode(token).rstrip(b"=").decode()


class _Reader:
    def __init__(self, raw: bytes) -> None:
        self.raw, self.at = raw, 0

    def take(self, n: int) -> bytes:
        if self.at + n > len(self.raw):
            raise ValueError("short token")
        out = self.raw[self.at : self.at + n]
        self.at += n
        return out

    def str8(self) -> str | None:
        value = self.take(self.take(1)[0]).decode("ascii")
        return value or None


def decode(token: str, *, now: float | None = None) -> ServeClaims | None:
    """The claims of a genuine, unexpired token, else None (never raises on bad input)."""
    if not isinstance(token, str) or not token or len(token) > 512:
        return None
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
    except (binascii.Error, ValueError):
        return None
    if len(raw) <= _MAC_BYTES:
        return None
    body, mac = raw[:-_MAC_BYTES], raw[-_MAC_BYTES:]
    if not hmac.compare_digest(mac, _mac(_key(), body)):
        return None
    try:
        r = _Reader(body)
        version = r.take(1)[0]
        if version not in VERSIONS:
            return None
        viewer = str(uuid.UUID(bytes=r.take(16)))
        item_type = _ITEM_TYPES[r.take(1)[0]]
        item_id = str(uuid.UUID(bytes=r.take(16)))
        surface = _SURFACES[r.take(1)[0]]
        pos, issued = struct.unpack(">HI", r.take(6))
        cfg_version, variant, source, reason = r.str8(), r.str8(), r.str8(), r.str8()
        scores = r.take(r.take(1)[0])
        extra: dict = {}
        if version >= 2:
            fmt_code = r.take(1)[0]
            (topic,) = struct.unpack(">H", r.take(2))
            bucket = r.take(1)[0]
            prefix = r.take(_AUTHOR_PREFIX)
            visit = r.take(1)[0]
            extra = {
                "fmt": FORMATS[fmt_code] if fmt_code < len(FORMATS) else None,
                "topic_id": topic,
                "length_bucket": bucket,
                "author_prefix": prefix,
                "visit_ord": visit % VISIT_ORD_MOD,
            }
        if r.at != len(body):
            return None
    except (ValueError, IndexError, UnicodeDecodeError, struct.error):
        return None
    current = now if now is not None else time.time()
    if issued > current + MAX_FUTURE_SKEW_SECONDS or current - issued > TTL_SECONDS:
        return None
    return ServeClaims(
        viewer=viewer,
        item_type=item_type,
        item_id=item_id,
        surface=surface,
        position=None if pos == _NO_POSITION else pos,
        issued_at=issued,
        cfg_version=cfg_version,
        variant=variant,
        source=source,
        reason=reason,
        scores=scores,
        version=version,
        **extra,
    )


def verify(
    token: str, viewer, item_type: str, item_id, *, now: float | None = None
) -> ServeClaims | None:
    """The claims only when the token was issued to ``viewer`` for this very item."""
    claims = decode(token, now=now)
    if claims is None:
        return None
    try:
        same_viewer = claims.viewer == str(uuid.UUID(str(viewer)))
        same_item = claims.item_id == str(uuid.UUID(str(item_id)))
    except (TypeError, ValueError):
        return None
    # Posts, reels and videos share post ids: a video post served in Home and
    # reported by the video player as ``video:<id>`` is the same item.
    same_kind = claims.item_type == item_type or (
        claims.item_type in _POST_KINDS and item_type in _POST_KINDS
    )
    if not (same_viewer and same_item and same_kind):
        return None
    return claims


# The Home config version a ranked page carried before the versioned store (WP 4.1).
# A ranked page now names the version that actually ranked it (``cfg_version``).
HOME_RANKED_CFG = "home@1"


def stamp_home_items(
    viewer,
    items: list[dict],
    mode: str,
    *,
    offset: int | None,
    ranked: bool,
    cfg_version: str | None = None,
    visit_ord: int | None = None,
    topics: dict | None = None,
):
    """Give each Home item its serve token ``st`` (in place).

    ``offset`` is the absolute position of the first item when it is known (ranked
    pages), else positions stay unset. ``ranked`` pages carry the config version
    that ranked them (``cfg_version``, else ``home@1``); the chronological modes and
    the latest-order fallback carry none. The token's source is the item's
    candidate ``source`` for a pulled item (``follow_pull``, ``groups``), else the
    connection's fan-out reason (``self``, ``friend``, ``follow``), as before.

    Token v2 (07 WP 4b.16): ``fmt`` and the excerpt length bucket come from the
    item's serialized snapshot, so a snapshot whose excerpt was stripped for this
    viewer carries bucket 0 (unknown) and reveals nothing beyond what was served;
    ``visit_ord`` is the viewer's visit ordinal when the caller knows it.
    """
    now = time.time()
    buckets = _length_buckets()
    for i, item in enumerate(items):
        snap = item.get("snapshot") or {}
        source = item.get("source")
        if source in (None, "", "connections"):
            source = item.get("reason") or None
        item["st"] = issue(
            viewer,
            ItemType.POST,
            item["post_id"],
            Surface.HOME,
            position=None if offset is None else offset + i,
            cfg_version=(cfg_version or HOME_RANKED_CFG) if ranked else None,
            source=source,
            reason=mode,
            now=now,
            fmt=snap.get("type"),
            length_bucket=length_bucket(snap.get("excerpt"), buckets),
            author_id=item.get("author_id") or snap.get("author_id"),
            visit_ord=visit_ord,
            # R4: the primary topic (``topics.attach.primary``), so ingest updates the
            # session vector without a read (06 section 4.4).
            topic_id=(topics or {}).get(str(item["post_id"]), 0),
        )
    return items


def _length_buckets() -> list[dict]:
    """``exposure.length_buckets`` of the active Home config; empty when it cannot be
    read (the tokens then say "unknown", never a guess)."""
    from .. import config

    try:
        buckets = config.for_surface("home").get("exposure.length_buckets")
    except Exception:  # noqa: BLE001 - a token without a bucket is still a valid token
        logger.warning("exposure.length_buckets unreadable; tokens carry no bucket")
        return []
    return list(buckets) if isinstance(buckets, list) else []
