"""Serve tokens: how telemetry is attributed (02 section 12.2, WP 2.3).

Every item in a ranked response carries ``st``, a compact token signed with
HMAC-SHA256 under ``INTEL_SERVE_TOKEN_SECRET`` (feed only: never ``SECRET_KEY``
nor the internal JWT secret, the same rule as ads' ``ADS_SERVE_TOKEN_SECRET``).
It names the viewer, the item, the surface, the config version and variant, the
candidate source, the reason, the position and the item's quantized rule scores.
``POST /feed/signals/`` stamps attribution on a row only from a token that is
valid, unexpired, issued to the same account and for the same item; client
fields never set it. Nothing is written per impression at serve time.

Binary layout (big-endian), base64url without padding, about 100 to 130 chars::

    u8  version (1)
    16B viewer uuid
    u8  item type code     16B item uuid
    u8  surface code       u16 position (0xFFFF = none)    u32 issued_at (unix s)
    str8 cfg_version  str8 variant  str8 source  str8 reason   (u8 length + ascii)
    u8  n + n bytes scores (each 0..255)
    16B HMAC-SHA256(key, "tara.intel.st.v1" || all of the above), truncated
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

VERSION = 1
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


def _str8(value: str | None) -> bytes:
    raw = (value or "").encode("ascii", "strict")[:_MAX_STR]
    return bytes([len(raw)]) + raw


def _mac(key: bytes, body: bytes) -> bytes:
    return hmac.new(key, _DOMAIN + body, hashlib.sha256).digest()[:_MAC_BYTES]


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
) -> str:
    issued = int(now if now is not None else time.time())
    pos = _NO_POSITION if position is None else max(0, min(int(position), _NO_POSITION - 1))
    body = b"".join(
        [
            bytes([VERSION]),
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
        if r.take(1)[0] != VERSION:
            return None
        viewer = str(uuid.UUID(bytes=r.take(16)))
        item_type = _ITEM_TYPES[r.take(1)[0]]
        item_id = str(uuid.UUID(bytes=r.take(16)))
        surface = _SURFACES[r.take(1)[0]]
        pos, issued = struct.unpack(">HI", r.take(6))
        cfg_version, variant, source, reason = r.str8(), r.str8(), r.str8(), r.str8()
        scores = r.take(r.take(1)[0])
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


# The Home config version that today's ``feed/ranking.py`` constants are (04 WP 4.1:
# ``home@1`` is a params file of exactly those constants).
HOME_RANKED_CFG = "home@1"


def stamp_home_items(viewer, items: list[dict], mode: str, *, offset: int | None, ranked: bool):
    """Give each Home item its serve token ``st`` (in place).

    ``offset`` is the absolute position of the first item when it is known (ranked
    pages), else positions stay unset. ``ranked`` pages carry ``home@1``; the
    chronological modes and the latest-order fallback carry no config version.
    """
    now = time.time()
    for i, item in enumerate(items):
        item["st"] = issue(
            viewer,
            ItemType.POST,
            item["post_id"],
            Surface.HOME,
            position=None if offset is None else offset + i,
            cfg_version=HOME_RANKED_CFG if ranked else None,
            source=item.get("reason") or None,
            reason=mode,
            now=now,
        )
    return items
