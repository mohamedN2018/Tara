"""What may be uploaded, and checking the bytes really are that."""

from __future__ import annotations

ALLOWED_MIME = {
    # HEIC/HEIF (iPhone photos) are decoded on the server and stored as JPEG.
    "image": {"image/png", "image/jpeg", "image/webp", "image/gif", "image/heic", "image/heif"},
    "video": {"video/mp4", "video/webm"},
    "audio": {"audio/mpeg", "audio/ogg", "audio/mp4", "audio/webm", "audio/wav"},
    "voice": {"audio/ogg", "audio/mp4", "audio/webm", "audio/mpeg"},
    "file": {"application/pdf"},
}

# How many leading bytes the checks below need.
HEAD_BYTES = 64

SIGNATURES = {
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/gif": (b"GIF87a", b"GIF89a"),
    "application/pdf": (b"%PDF-",),
}

_EBML = b"\x1a\x45\xdf\xa3"  # Matroska / WebM
_OGG = b"OggS"


def normalize_mime(mime: str) -> str:
    return mime.split(";")[0].strip().lower()


def is_allowed(kind: str, mime: str) -> bool:
    return normalize_mime(mime) in ALLOWED_MIME.get(kind, set())


def _is_iso_bmff(head: bytes) -> bool:
    """MP4 / M4A: the first box is ``ftyp`` (4-byte size, then the box type)."""
    return len(head) >= 12 and head[4:8] == b"ftyp"


# ``ftyp`` brands of HEVC-coded HEIF still images and sequences (ISO/IEC 23008-12).
HEIF_BRANDS = frozenset({b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1"})


def _is_heif(head: bytes) -> bool:
    """An ``ftyp`` box whose major or a compatible brand is a HEIF brand.

    The box is size (4), ``ftyp`` (4), major brand (4), minor version (4), then
    compatible brands, 4 bytes each, up to the box size.
    """
    if not _is_iso_bmff(head):
        return False
    box_end = min(int.from_bytes(head[:4], "big"), len(head))
    if box_end < 16:
        return False
    brands = [head[8:12]] + [head[i : i + 4] for i in range(16, box_end - 3, 4)]
    return any(brand in HEIF_BRANDS for brand in brands)


def _is_mp3(head: bytes) -> bool:
    if head.startswith(b"ID3"):
        return True
    # An MPEG audio frame starts with 11 set sync bits.
    return len(head) >= 2 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0


def _is_riff(head: bytes, form: bytes) -> bool:
    return head[:4] == b"RIFF" and head[8:12] == form


_CONTAINER_CHECKS = {
    "image/webp": lambda h: _is_riff(h, b"WEBP"),
    "image/heic": _is_heif,
    "image/heif": _is_heif,
    "audio/wav": lambda h: _is_riff(h, b"WAVE"),
    "video/mp4": _is_iso_bmff,
    "audio/mp4": _is_iso_bmff,
    "video/webm": lambda h: h.startswith(_EBML),
    "audio/webm": lambda h: h.startswith(_EBML),
    "audio/ogg": lambda h: h.startswith(_OGG),
    "audio/mpeg": _is_mp3,
}


def matches_signature(mime: str, head: bytes) -> bool:
    """True when the first bytes of the file are what ``mime`` claims.

    Every allowed type has a check; an unknown type never passes.
    """
    mime = normalize_mime(mime)
    check = _CONTAINER_CHECKS.get(mime)
    if check is not None:
        return bool(check(head))
    signatures = SIGNATURES.get(mime)
    return bool(signatures) and head.startswith(signatures)
