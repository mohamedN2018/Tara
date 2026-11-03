"""Image cost limits before decoding, metadata removal without decoding
animations, and the EXIF backfill for images that were ready before cleaning."""

import hashlib
import io
import struct
import time
import uuid
import zlib

import pytest
from django.core.management import CommandError, call_command
from django.urls import reverse
from django.utils import timezone
from PIL import Image, ImageFile, ImageSequence

from media_app import imaging, storage, tasks
from media_app.models import MediaAsset, MediaVariant, OutboxEvent

pytestmark = pytest.mark.django_db

GPS_IFD = 0x8825
ORIENTATION = 0x0112


def _acct() -> str:
    return str(uuid.uuid4())


# ---- builders -----------------------------------------------------------------------


def _gif_frames(width: int, height: int, frames: int, *, comment: bytes = b"") -> bytes:
    """A GIF built by hand: many frames cost a few bytes each, so tests stay small.

    Each frame is a 1-pixel LZW stream for a full-canvas descriptor; decoders
    and Pillow's frame counter accept it, which is all the limits look at.
    """
    out = bytearray(b"GIF89a" + struct.pack("<HH", width, height) + b"\x80\x00\x00")
    out += b"\x00\x00\x00\xff\xff\xff"  # 2-colour global table
    out += b"\x21\xff\x0bNETSCAPE2.0\x03\x01\x00\x00\x00"  # loop forever
    if comment:
        out += b"\x21\xfe" + bytes([len(comment)]) + comment + b"\x00"
    for _ in range(frames):
        out += b"\x21\xf9\x04\x04\x05\x00\x00\x00"  # graphic control, 50 ms
        out += b"\x2c" + struct.pack("<HHHH", 0, 0, width, height) + b"\x00"
        out += b"\x02\x02\x44\x01\x00"
    return bytes(out + b"\x3b")


def _gif_with_metadata() -> bytes:
    """A real Pillow GIF, then XMP (with GPS), a comment and junk after the trailer."""
    frames = [Image.new("P", (6, 6), i) for i in (1, 2, 3)]
    for f in frames:
        f.putpalette([0, 0, 0, 255, 0, 0, 0, 255, 0, 0, 0, 255] + [0] * 756)
    out = io.BytesIO()
    frames[0].save(
        out, "GIF", save_all=True, append_images=frames[1:], duration=[50, 60, 70], loop=3
    )
    data = out.getvalue()
    gct = 3 << ((data[10] & 7) + 1) if data[10] & 0x80 else 0
    at = 13 + gct
    xmp = b"<x:xmpmeta>GPSLatitude 30.04N</x:xmpmeta>"
    extra = b"\x21\xff\x0bXMP DataXMP" + bytes([len(xmp)]) + xmp + b"\x00"
    extra += b"\x21\xfe\x08gps home\x00"
    return data[:at] + extra + data[at:] + b"after the trailer: gps"


def _png_header_only(width: int, height: int) -> bytes:
    """A PNG whose IHDR claims ``width`` x ``height``: a decompression bomb's header."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(b"\x00" * 64))
        + chunk(b"IEND", b"")
    )


def _animated_webp_with_metadata() -> bytes:
    exif = Image.Exif()
    exif[0x010F] = "PhoneMaker"
    exif[GPS_IFD] = {1: "N", 2: (30.0, 2.0, 41.0)}
    frames = [Image.new("RGBA", (8, 8), c) for c in ((255, 0, 0, 255), (0, 255, 0, 128))]
    out = io.BytesIO()
    frames[0].save(
        out,
        "WEBP",
        save_all=True,
        append_images=frames[1:],
        duration=[40, 80],
        loop=0,
        lossless=True,
        exif=exif.tobytes(),
        xmp=b"<x:xmpmeta>gps</x:xmpmeta>",
    )
    data = out.getvalue()
    unknown = b"ZZZZ" + struct.pack("<I", 6) + b"gps!!!"  # an unknown chunk at the end
    body = data[12:] + unknown
    return b"RIFF" + struct.pack("<I", 4 + len(body)) + b"WEBP" + body


def _jpeg_with_gps(size=(60, 30)) -> bytes:
    exif = Image.Exif()
    exif[ORIENTATION] = 6
    exif[0x010F] = "PhoneMaker"
    exif[GPS_IFD] = {1: "N", 2: (30.0, 2.0, 41.0), 3: "E", 4: (31.0, 14.0, 9.0)}
    out = io.BytesIO()
    Image.new("RGB", size, "red").save(out, "JPEG", exif=exif.tobytes(), comment=b"home")
    return out.getvalue()


@pytest.fixture
def no_decoding(monkeypatch):
    """Fail the test if any image's pixels are decoded."""
    calls = []

    def load(self):
        calls.append(self.format)
        raise AssertionError(f"{self.format} pixels were decoded")

    monkeypatch.setattr(ImageFile.ImageFile, "load", load)
    return calls


# ---- limits before decoding ----------------------------------------------------------


def test_the_reviewers_gif_is_rejected_before_any_frame_is_decoded(no_decoding):
    """800x600 x 600 frames (288 MP) used to OOM a 256 MB worker; now it fails fast."""
    gif = _gif_frames(800, 600, 600)
    started = time.monotonic()
    with pytest.raises(imaging.ImageTooLarge):
        imaging.sanitize_image(gif, "image/gif")
    assert time.monotonic() - started < 2
    assert no_decoding == []


def test_too_many_frames_is_rejected_even_when_small(settings, no_decoding):
    settings.MEDIA_MAX_FRAMES = 50
    with pytest.raises(imaging.ImageTooLarge):
        imaging.sanitize_image(_gif_frames(4, 4, 51), "image/gif")
    assert len(imaging.strip_gif(_gif_frames(4, 4, 50))) > 0  # the cap itself is allowed


def test_a_normal_animated_gif_passes_without_decoding_its_frames(no_decoding):
    """480x270 x 300 frames (38.9 MP) reached 208 MB RSS before; now no frame is decoded."""
    gif = _gif_frames(480, 270, 300, comment=b"gps 30.04N")
    clean = imaging.sanitize_image(gif, "image/gif")
    assert no_decoding == []
    assert b"gps" not in clean
    assert len(clean) <= len(gif)
    with Image.open(io.BytesIO(clean)) as image:
        assert (image.size, image.n_frames) == ((480, 270), 300)


def test_too_many_pixels_in_one_frame_is_rejected(settings):
    settings.MEDIA_MAX_IMAGE_PIXELS = 100
    out = io.BytesIO()
    Image.new("RGB", (11, 10)).save(out, "PNG")
    with pytest.raises(imaging.ImageTooLarge):
        imaging.sanitize_image(out.getvalue(), "image/png")
    with pytest.raises(imaging.ImageTooLarge):
        imaging.thumbnail(out.getvalue(), 32)
    small = io.BytesIO()
    Image.new("RGB", (10, 10)).save(small, "PNG")
    assert imaging.sanitize_image(small.getvalue(), "image/png")


@pytest.mark.parametrize("side", [8000, 100_000])  # 1.3x and 200x the 50 MP limit
def test_a_decompression_bomb_header_raises_instead_of_warning(side, no_decoding):
    with pytest.raises(imaging.ImageTooLarge):
        imaging.sanitize_image(_png_header_only(side, side), "image/png")
    assert no_decoding == []


def test_an_over_limit_gif_fails_processing_and_is_never_served(client_for, memory_storage):
    owner = _acct()
    client = client_for(owner)
    gif = _gif_frames(800, 600, 600)
    signed = client.post(
        reverse("media_app:sign-upload"),
        {"kind": "image", "mime": "image/gif", "size": len(gif)},
        format="json",
    ).json()["data"]
    from media_app.models import UploadSession

    storage.write(
        UploadSession.objects.get(media_id=signed["media_id"]).staging_key, gif, "image/gif"
    )
    assert (
        client.post(reverse("media_app:complete-upload", args=[signed["media_id"]])).status_code
        == 200
    )

    tasks.process_media(signed["media_id"])

    asset = MediaAsset.objects.get(id=signed["media_id"])
    assert asset.status == MediaAsset.Status.FAILED
    assert "animation limits" in asset.error
    failed = OutboxEvent.objects.get(event_type="media.failed")
    assert failed.payload["subject_id"] == str(asset.id)
    detail = client.get(reverse("media_app:media-detail", args=[asset.id])).json()["data"]
    assert detail["url"] is None


# ---- GIF and animated WebP: metadata out, frames untouched -----------------------------


def _frames(content: bytes) -> list[tuple[bytes, int]]:
    with Image.open(io.BytesIO(content)) as image:
        return [
            (f.convert("RGBA").tobytes(), f.info.get("duration"))
            for f in ImageSequence.Iterator(image)
        ]


def test_gif_metadata_goes_and_frames_timing_and_loop_stay():
    original = _gif_with_metadata()
    clean = imaging.sanitize_image(original, "image/gif")

    assert b"XMP DataXMP" not in clean and b"gps" not in clean.lower()
    assert clean.endswith(b"\x3b")  # nothing after the trailer
    assert _frames(clean) == _frames(original)  # same pixels, same durations
    with Image.open(io.BytesIO(clean)) as image:
        assert image.info.get("loop") == 3
        assert "comment" not in image.info and "xmp" not in image.info


def test_a_gif_without_a_trailer_gets_one_and_a_truncated_gif_fails():
    whole = _gif_frames(4, 4, 2)
    assert imaging.strip_gif(whole[:-1]) == whole
    with pytest.raises(ValueError):
        imaging.strip_gif(whole[:-4])  # cut inside the last frame's data
    with pytest.raises(ValueError):
        imaging.strip_gif(whole[:19] + b"\x99junk")  # header, colour table, a bad block


def test_animated_webp_loses_exif_xmp_and_unknown_chunks_but_keeps_its_frames():
    original = _animated_webp_with_metadata()
    assert b"Exif" in original or b"EXIF" in original
    clean = imaging.sanitize_image(original, "image/webp")

    assert b"EXIF" not in clean and b"XMP " not in clean and b"ZZZZ" not in clean
    assert b"gps" not in clean.lower() and b"PhoneMaker" not in clean
    assert struct.unpack("<I", clean[4:8])[0] == len(clean) - 8  # RIFF size rewritten
    vp8x = clean.index(b"VP8X")
    assert clean[vp8x + 8] & 0x0C == 0  # EXIF and XMP flags cleared
    with Image.open(io.BytesIO(clean)) as image:
        assert image.n_frames == 2
        assert dict(image.getexif()) == {}
        assert "xmp" not in image.info
    assert _frames(clean) == _frames(original)


# ---- backfill: images that were READY before cleaning ----------------------------------


def _legacy_image(content: bytes, *, mime="image/jpeg", **fields) -> MediaAsset:
    """A row as it was before 1.5: READY, no ETag, the original upload in storage."""
    owner = _acct()
    key = f"media/{owner}/{uuid.uuid4()}"
    asset = MediaAsset.objects.create(
        owner_id=owner,
        kind=fields.pop("kind", MediaAsset.Kind.IMAGE),
        storage_key=key,
        bytes=len(content),
        mime=mime,
        status=fields.pop("status", MediaAsset.Status.READY),
        **fields,
    )
    storage.write(key, content, mime)
    return asset


def _run(*args) -> str:
    out = io.StringIO()
    call_command("sanitize_existing_images", *args, stdout=out, stderr=out)
    return out.getvalue()


def test_a_legacy_ready_jpeg_loses_its_gps_and_a_second_run_is_a_no_op(
    client_for, memory_storage, monkeypatch
):
    original = _jpeg_with_gps()
    asset = _legacy_image(original)
    assert Image.open(io.BytesIO(storage.read(asset.storage_key))).getexif().get_ifd(GPS_IFD)

    assert "cleaned 1 images; 0 failed" in _run()

    served = storage.read(asset.storage_key)
    image = Image.open(io.BytesIO(served))
    assert dict(image.getexif()) == {}
    assert b"home" not in served
    assert image.size == (30, 60)  # orientation applied to the pixels
    asset.refresh_from_db()
    assert asset.status == MediaAsset.Status.READY
    assert asset.bytes == len(served)
    assert asset.etag == f'"{hashlib.md5(served, usedforsecurity=False).hexdigest()}"'
    thumb = MediaVariant.objects.get(media=asset, kind=MediaVariant.Kind.THUMB)
    assert dict(Image.open(io.BytesIO(storage.read(thumb.storage_key))).getexif()) == {}

    # What a viewer is handed now is the clean copy.
    data = (
        client_for(str(asset.owner_id))
        .get(reverse("media_app:media-detail", args=[asset.id]))
        .json()["data"]
    )
    assert data["url"] and asset.storage_key in data["url"]

    writes = []
    monkeypatch.setattr(storage, "write", lambda *a, **k: writes.append(a) or '"x"')
    assert "cleaned 0 images; 0 failed" in _run()
    assert writes == []


def test_backfill_keeps_an_existing_thumbnail_row(memory_storage):
    asset = _legacy_image(_jpeg_with_gps())
    MediaVariant.objects.create(
        media=asset, kind=MediaVariant.Kind.THUMB, storage_key=f"{asset.storage_key}/thumb.jpg"
    )
    _run()
    assert MediaVariant.objects.filter(media=asset).count() == 1
    assert storage.read(f"{asset.storage_key}/thumb.jpg")


def test_backfill_selects_only_legacy_ready_images(memory_storage):
    gps = _jpeg_with_gps()
    legacy = _legacy_image(gps)
    already_clean = _legacy_image(gps, etag='"done"')  # cleaned by the new pipeline
    deleted = _legacy_image(gps, deleted_at=timezone.now())
    processing = _legacy_image(gps, status=MediaAsset.Status.PROCESSING)
    video = _legacy_image(b"\x00\x00\x00\x18ftypmp42", mime="video/mp4", kind="video")

    assert "cleaned 1 images" in _run()

    assert storage.read(legacy.storage_key) != gps
    for untouched in (already_clean, deleted, processing):
        assert storage.read(untouched.storage_key) == gps
        untouched.refresh_from_db()
        assert untouched.etag in ('"done"', "")
    video.refresh_from_db()
    assert video.etag == ""


def test_backfill_dry_run_changes_nothing(memory_storage):
    gps = _jpeg_with_gps()
    asset = _legacy_image(gps)
    assert "would clean 1 images" in _run("--dry-run")
    assert storage.read(asset.storage_key) == gps
    asset.refresh_from_db()
    assert asset.etag == ""


def test_backfill_walks_every_batch(memory_storage):
    assets = [_legacy_image(_jpeg_with_gps()) for _ in range(3)]
    assert "cleaned 3 images" in _run("--batch", "1")
    assert all(MediaAsset.objects.get(id=a.id).etag for a in assets)


def test_backfill_reports_failures_and_goes_on(memory_storage):
    missing = _legacy_image(_jpeg_with_gps())
    storage.delete(missing.storage_key)
    broken = _legacy_image(b"\xff\xd8\xff not a jpeg")
    good = _legacy_image(_jpeg_with_gps())

    out = _run()

    assert "cleaned 1 images; 2 failed" in out
    assert str(missing.id) in out and str(broken.id) in out
    for row in (missing, broken):
        row.refresh_from_db()
        assert (row.status, row.etag) == (MediaAsset.Status.READY, "")  # retried next run
    good.refresh_from_db()
    assert good.etag


def test_backfill_can_hide_what_it_cannot_clean(client_for, memory_storage):
    broken = _legacy_image(b"\xff\xd8\xff not a jpeg")
    assert "0 images; 1 failed" in _run("--hide-failed")
    broken.refresh_from_db()
    assert broken.status == MediaAsset.Status.FAILED
    assert broken.error.startswith("not cleaned:")
    data = (
        client_for(str(broken.owner_id))
        .get(reverse("media_app:media-detail", args=[broken.id]))
        .json()["data"]
    )
    assert data["url"] is None


def test_backfill_refuses_the_fake_backend():
    with pytest.raises(CommandError):
        _run()
