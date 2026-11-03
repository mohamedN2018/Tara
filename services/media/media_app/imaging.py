"""Image cleaning: drop EXIF (GPS included), XMP and comments, apply orientation.

The cost of an image is checked from its header before any pixels are decoded:
too many pixels per frame, too many frames, or too many pixels across all
frames is rejected (``ImageTooLarge``), so a small file cannot make the worker
allocate gigabytes. Still images are decoded and re-encoded, one frame. GIFs
and animated WebPs are never decoded: their metadata blocks are removed at the
byte level and the frames are copied as they are, so memory stays at the size
of the file whatever the frame count.
"""

from __future__ import annotations

import io
import warnings

from django.conf import settings

from .validation import normalize_mime

# Pillow format names a declared type may decode as (phones save MPO as JPEG).
_DECODES_AS = {
    "image/jpeg": {"JPEG", "MPO"},
    "image/png": {"PNG"},
    "image/webp": {"WEBP"},
    "image/gif": {"GIF"},
}
_SAVE_AS = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP", "image/gif": "GIF"}
# Info that rendering needs; everything else (exif, xmp, comments, text chunks) goes.
_KEEP_INFO = ("transparency", "background", "loop", "duration")


class ImageTooLarge(ValueError):
    """Over the pixel or frame limits; rejected before decoding."""


def _limits() -> tuple[int, int, int]:
    return (
        settings.MEDIA_MAX_IMAGE_PIXELS,
        settings.MEDIA_MAX_FRAMES,
        settings.MEDIA_MAX_ANIMATION_PIXELS,
    )


def _open(content: bytes):
    """Open (header only) and refuse anything over the limits before decoding."""
    from PIL import Image

    max_pixels, max_frames, max_total = _limits()
    Image.MAX_IMAGE_PIXELS = max_pixels
    with warnings.catch_warnings():
        # Pillow only warns between 1x and 2x MAX_IMAGE_PIXELS; make that an error.
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        try:
            image = Image.open(io.BytesIO(content))
        except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
            raise ImageTooLarge(str(exc)) from exc
    width, height = image.size
    frames = getattr(image, "n_frames", 1)  # counted from headers, frames are not decoded
    if width * height > max_pixels:
        image.close()
        raise ImageTooLarge(f"{width}x{height} is over {max_pixels} pixels")
    if frames > max_frames or frames * width * height > max_total:
        image.close()
        raise ImageTooLarge(f"{frames} frames of {width}x{height} is over the animation limits")
    return image


def _scrub(image):
    image.info = {k: v for k, v in image.info.items() if k in _KEEP_INFO}
    return image


def sanitize_image(content: bytes, mime: str) -> bytes:
    """A copy of the image with no metadata and the EXIF orientation applied.

    The pixels are what viewers saw before; only the metadata goes. Raises
    ``ValueError`` (``ImageTooLarge`` included) for anything that is not a
    decodable image of the declared type within the limits.
    """
    from PIL import ImageOps

    mime = normalize_mime(mime)
    target = _SAVE_AS[mime]
    with _open(content) as source:
        if source.format not in _DECODES_AS[mime]:
            raise ValueError(f"{source.format} content declared as {mime}")
        if target == "GIF":
            return strip_gif(content)
        if target == "WEBP" and getattr(source, "n_frames", 1) > 1:
            return strip_webp(content)
        icc = source.info.get("icc_profile")
        params: dict = {"icc_profile": icc} if icc else {}
        image = _scrub(ImageOps.exif_transpose(source))
        if target == "JPEG":
            if image.mode not in ("L", "RGB", "CMYK"):
                image = image.convert("RGB")
            params.update(quality=90, optimize=True)
        elif target == "WEBP":
            params.update(quality=90)
        out = io.BytesIO()
        image.save(out, target, **params)
    return out.getvalue()


def thumbnail(content: bytes, size: int) -> bytes:
    """A JPEG of the first frame, at most ``size`` on each side."""
    from PIL import ImageOps

    with _open(content) as image:
        image.draft("RGB", (size * 2, size * 2))  # JPEG: decode at a reduced scale
        thumb = ImageOps.exif_transpose(image).convert("RGB")
        thumb.thumbnail((size, size))
        out = io.BytesIO()
        thumb.save(out, "JPEG", quality=85)
    return out.getvalue()


# ---- GIF: keep the image data, the frame timing and the loop count -------------------

# Application extensions that rendering needs: the loop count and the ICC profile.
_GIF_KEEP_APPS = {b"NETSCAPE2.0", b"ANIMEXTS1.0", b"ICCRGBG1012"}
_GIF_GRAPHIC_CONTROL = 0xF9
_GIF_APPLICATION = 0xFF


def _gif_sub_blocks(data: bytes, pos: int) -> int:
    """The position after the data sub-blocks that start at ``pos``."""
    while True:
        size = data[pos]
        pos += 1 + size
        if size == 0:
            return pos


def _gif_color_table(flags: int) -> int:
    return 3 << ((flags & 0x07) + 1) if flags & 0x80 else 0


def strip_gif(content: bytes) -> bytes:
    """The GIF with comment, plain-text and other application blocks removed.

    Image data, graphic-control (timing, transparency), the loop count and the
    ICC profile are copied byte for byte. Bytes after the trailer go too.
    """
    data = content
    if data[:6] not in (b"GIF87a", b"GIF89a") or len(data) < 13:
        raise ValueError("not a GIF")
    try:
        pos = 13 + _gif_color_table(data[10])
        out = bytearray(data[:pos])
        while pos < len(data):
            intro = data[pos]
            if intro == 0x3B:  # trailer
                break
            if intro == 0x2C:  # image descriptor, color table, LZW size, image data
                start = pos + 10 + _gif_color_table(data[pos + 9]) + 1
                end = _gif_sub_blocks(data, start)
                out += data[pos:end]
            elif intro == 0x21:  # extension
                label = data[pos + 1]
                end = _gif_sub_blocks(data, pos + 2)
                keep = label == _GIF_GRAPHIC_CONTROL or (
                    label == _GIF_APPLICATION
                    and data[pos + 2] == 11
                    and data[pos + 3 : pos + 14] in _GIF_KEEP_APPS
                )
                if keep:
                    out += data[pos:end]
            else:
                raise ValueError(f"unexpected GIF block 0x{intro:02x}")
            if end > len(data):
                raise ValueError("truncated GIF")
            pos = end
    except IndexError as exc:
        raise ValueError("truncated GIF") from exc
    out.append(0x3B)
    return bytes(out)


# ---- WebP: keep the bitstreams, animation and ICC; drop EXIF, XMP and unknown chunks ----

_WEBP_KEEP = {b"VP8 ", b"VP8L", b"VP8X", b"ALPH", b"ANIM", b"ANMF", b"ICCP"}
_ANMF_KEEP = {b"ALPH", b"VP8 ", b"VP8L"}
_VP8X_EXIF, _VP8X_XMP = 0x08, 0x04
_ANMF_HEADER = 16


def _riff_chunks(data: bytes, pos: int, end: int):
    """(fourcc, chunk bytes padded to even length) for each chunk in [pos, end)."""
    while pos < end:
        if pos + 8 > end:
            raise ValueError("truncated WebP chunk")
        fourcc = data[pos : pos + 4]
        size = int.from_bytes(data[pos + 4 : pos + 8], "little")
        if pos + 8 + size > end:
            raise ValueError("truncated WebP chunk")
        yield fourcc, data[pos : pos + 8 + size] + (b"\0" if size & 1 else b"")
        pos += 8 + size + (size & 1)


def _riff_chunk(fourcc: bytes, payload: bytes) -> bytes:
    return fourcc + len(payload).to_bytes(4, "little") + payload


def strip_webp(content: bytes) -> bytes:
    """The WebP with its EXIF, XMP and unknown chunks removed, frames as they are."""
    data = content
    if data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        raise ValueError("not a WebP")
    end = min(len(data), 8 + int.from_bytes(data[4:8], "little"))
    body = bytearray()
    for fourcc, chunk in _riff_chunks(data, 12, end):
        if fourcc not in _WEBP_KEEP:
            continue
        if fourcc == b"VP8X":
            flags = chunk[8] & ~(_VP8X_EXIF | _VP8X_XMP)
            chunk = chunk[:8] + bytes([flags]) + chunk[9:]
        elif fourcc == b"ANMF":
            frame = bytearray(chunk[8 : 8 + _ANMF_HEADER])
            payload_end = 8 + int.from_bytes(chunk[4:8], "little")
            for sub, sub_chunk in _riff_chunks(chunk, 8 + _ANMF_HEADER, payload_end):
                if sub in _ANMF_KEEP:
                    frame += sub_chunk
            chunk = _riff_chunk(b"ANMF", bytes(frame))
        body += chunk
    return _riff_chunk(b"RIFF", b"WEBP" + bytes(body))
