"""What may be uploaded, and checking the bytes really are that."""

from __future__ import annotations

ALLOWED_MIME = {
    "image": {"image/png", "image/jpeg", "image/webp", "image/gif"},
    "video": {"video/mp4", "video/webm"},
    "audio": {"audio/mpeg", "audio/ogg", "audio/mp4", "audio/webm", "audio/wav"},
    "voice": {"audio/ogg", "audio/mp4", "audio/webm", "audio/mpeg"},
    "file": {"application/pdf"},
}

SIGNATURES = {
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/gif": (b"GIF87a", b"GIF89a"),
    "application/pdf": (b"%PDF-",),
}


def normalize_mime(mime: str) -> str:
    return mime.split(";")[0].strip().lower()


def is_allowed(kind: str, mime: str) -> bool:
    return normalize_mime(mime) in ALLOWED_MIME.get(kind, set())


def matches_signature(mime: str, head: bytes) -> bool:
    mime = normalize_mime(mime)
    if mime == "image/webp":
        return head[:4] == b"RIFF" and head[8:12] == b"WEBP"
    signatures = SIGNATURES.get(mime)
    # Audio and video containers vary too much for a simple prefix check.
    return head.startswith(signatures) if signatures else True
