"""WP 4c.5-B3 (08 section 7.8): display sizes of images, and the backfill.

A ready image has its thumb, WebP ``display_640`` / ``display_1280`` copies (longest
side, never upscaled, none for an animated image) and its real width and height,
all read from the pixels (EXIF orientation applied). The backfill gives existing
media the same, idempotently, and never touches an original.
"""

from __future__ import annotations

import io
import json
import uuid
from pathlib import Path

import jsonschema
import pytest
from django.core.management import call_command
from django.urls import reverse
from PIL import Image

from media_app import storage, tasks
from media_app.models import MediaAsset, MediaVariant, OutboxEvent, UploadSession

pytestmark = pytest.mark.django_db
SCHEMA = Path("/opt/tara/libs/tara_events/tara_events/schemas/media.processed.v1.json")


def _acct() -> str:
    return str(uuid.uuid4())


def _jpeg(size, *, orientation=None) -> bytes:
    out = io.BytesIO()
    image = Image.new("RGB", size, "teal")
    if orientation:
        exif = Image.Exif()
        exif[0x0112] = orientation
        image.save(out, "JPEG", exif=exif.tobytes())
    else:
        image.save(out, "JPEG")
    return out.getvalue()


def _png_alpha(size) -> bytes:
    out = io.BytesIO()
    Image.new("RGBA", size, (255, 0, 0, 90)).save(out, "PNG")
    return out.getvalue()


def _gif_animated(size) -> bytes:
    out = io.BytesIO()
    frames = [Image.new("P", size, c) for c in (1, 2, 3)]
    frames[0].save(out, "GIF", save_all=True, append_images=frames[1:], duration=80, loop=0)
    return out.getvalue()


def _process(client, content: bytes, mime: str) -> MediaAsset:
    signed = client.post(
        reverse("media_app:sign-upload"),
        {"kind": "image", "mime": mime, "size": len(content), "visibility": "public"},
        format="json",
    )
    assert signed.status_code == 201, signed.content
    media_id = signed.json()["data"]["media_id"]
    storage.write(UploadSession.objects.get(media_id=media_id).staging_key, content, mime)
    assert client.post(reverse("media_app:complete-upload", args=[media_id])).status_code == 200
    tasks.process_media(media_id)
    asset = MediaAsset.objects.get(id=media_id)
    assert asset.status == MediaAsset.Status.READY
    return asset


def _variants(asset) -> dict[str, MediaVariant]:
    return {v.kind: v for v in MediaVariant.objects.filter(media=asset)}


def _stored(variant) -> Image.Image:
    return Image.open(io.BytesIO(storage.read(variant.storage_key)))


def test_a_new_photo_gets_thumb_and_both_display_sizes_with_real_sizes(client_for, memory_storage):
    owner = _acct()
    client = client_for(owner)
    # 2000x1500 pixels stored sideways (orientation 6): displayed 1500 wide, 2000 tall.
    asset = _process(client, _jpeg((2000, 1500), orientation=6), "image/jpeg")
    assert (asset.width, asset.height) == (1500, 2000)
    found = _variants(asset)
    assert set(found) == {"thumb", "display_640", "display_1280"}
    for kind, size in (("display_640", (480, 640)), ("display_1280", (960, 1280))):
        image = _stored(found[kind])
        assert image.format == "WEBP" and image.size == size, kind
        assert (found[kind].width, found[kind].height) == size
        assert memory_storage._memory[found[kind].storage_key][1] == "image/webp"
    thumb = _stored(found["thumb"])
    assert (found["thumb"].width, found["thumb"].height) == thumb.size == (240, 320)

    data = client.get(reverse("media_app:media-detail", args=[asset.id])).json()["data"]
    assert (data["width"], data["height"]) == (1500, 2000)
    assert [v["kind"] for v in data["variants"]] == ["thumb", "display_640", "display_1280"]
    assert {(v["kind"], v["width"], v["height"]) for v in data["variants"]} == {
        ("thumb", 240, 320),
        ("display_640", 480, 640),
        ("display_1280", 960, 1280),
    }
    assert all("response-content-type=image%2Fwebp" in v["url"] for v in data["variants"][1:])

    row = OutboxEvent.objects.get(event_type="media.processed", payload__subject_id=str(asset.id))
    payload = row.payload["payload"]
    assert payload["variants"] == ["thumb", "display_640", "display_1280"]
    jsonschema.validate(payload, json.loads(SCHEMA.read_text(encoding="utf-8")))


@pytest.mark.parametrize(
    ("size", "kinds", "dims"),
    [
        ((500, 300), {"thumb"}, {}),  # smaller than 640: nothing made, nothing invented
        ((800, 600), {"thumb", "display_640"}, {"display_640": (640, 480)}),
        (
            (1280, 720),  # exactly 1280: a copy at its own size, never larger
            {"thumb", "display_640", "display_1280"},
            {"display_640": (640, 360), "display_1280": (1280, 720)},
        ),
    ],
)
def test_never_upscaled(client_for, memory_storage, size, kinds, dims):
    asset = _process(client_for(_acct()), _jpeg(size), "image/jpeg")
    assert (asset.width, asset.height) == size
    found = _variants(asset)
    assert set(found) == kinds
    for kind, expected in dims.items():
        assert _stored(found[kind]).size == expected == (found[kind].width, found[kind].height)


def test_transparency_is_kept_in_the_webp(client_for, memory_storage):
    asset = _process(client_for(_acct()), _png_alpha((900, 700)), "image/png")
    image = _stored(_variants(asset)["display_640"])
    assert image.mode == "RGBA" and image.size == (640, 498)


def test_an_animated_gif_keeps_its_animation_no_still_copies(client_for, memory_storage):
    asset = _process(client_for(_acct()), _gif_animated((900, 700)), "image/gif")
    assert (asset.width, asset.height) == (900, 700)
    assert set(_variants(asset)) == {"thumb"}


# ---- the backfill ------------------------------------------------------------------


def _legacy(owner, content, mime="image/jpeg") -> MediaAsset:
    """A ready image from before WP 4c.5-B3: no size, a thumb only."""
    asset = MediaAsset.objects.create(
        owner_id=owner,
        kind="image",
        mime=mime,
        storage_key=f"image/{owner}/{uuid.uuid4()}",
        status=MediaAsset.Status.READY,
        bytes=len(content),
    )
    storage.write(asset.storage_key, content, mime)
    MediaVariant.objects.create(
        media=asset, kind="thumb", storage_key=f"{asset.storage_key}/thumb.jpg", width=320
    )
    return asset


def _legacy_video(owner, poster_size) -> MediaAsset:
    asset = MediaAsset.objects.create(
        owner_id=owner,
        kind="video",
        purpose="post",
        mime="video/mp4",
        storage_key=f"videos/{owner}/{uuid.uuid4()}",
        status=MediaAsset.Status.READY,
        width=poster_size[0],
        height=poster_size[1],
    )
    key = f"{asset.storage_key}/poster.jpg"
    storage.write(key, _jpeg(poster_size), "image/jpeg")
    MediaVariant.objects.create(
        media=asset, kind="poster", storage_key=key, width=poster_size[0], height=poster_size[1]
    )
    return asset


def _run(*args) -> str:
    out = io.StringIO()
    call_command("media_backfill_display_variants", *args, stdout=out)
    return out.getvalue()


def test_the_backfill_fills_sizes_and_display_variants_once(memory_storage):
    owner = _acct()
    big = _legacy(owner, _jpeg((1600, 1200)))
    small = _legacy(owner, _jpeg((400, 300)))
    gif = _legacy(owner, _gif_animated((800, 600)), "image/gif")
    hd = _legacy_video(owner, (1280, 720))
    tiny = _legacy_video(owner, (320, 180))
    originals = {a.id: storage.read(a.storage_key) for a in (big, small, gif)}
    poster_before = storage.read(f"{hd.storage_key}/poster.jpg")

    assert "would process 3 images and 1 videos" in _run("--dry-run")
    assert MediaVariant.objects.count() == 5  # a dry run writes nothing

    out = _run("--batch", "2")
    assert "processed 3 images and 1 videos (3 variants written)" in out
    assert "1 already done; 0 failed; 5 looked at" in out
    for asset, size in ((big, (1600, 1200)), (small, (400, 300)), (gif, (800, 600))):
        asset.refresh_from_db()
        assert (asset.width, asset.height) == size
    assert set(_variants(big)) == {"thumb", "display_640", "display_1280"}
    assert set(_variants(small)) == {"thumb"}
    assert set(_variants(gif)) == {"thumb"}
    small_poster = _variants(hd)["poster_480"]
    assert (small_poster.width, small_poster.height) == (853, 480)
    assert _stored(small_poster).size == (853, 480)
    assert set(_variants(tiny)) == {"poster"}  # under 480: never upscaled
    # Originals and the existing poster are untouched; nothing else was written.
    assert all(storage.read(a.storage_key) == originals[a.id] for a in (big, small, gif))
    assert storage.read(f"{hd.storage_key}/poster.jpg") == poster_before
    assert not OutboxEvent.objects.exists()

    again = _run()
    assert "processed 0 images and 0 videos (0 variants written); 5 already done" in again


def test_the_backfill_limit_bounds_the_run(memory_storage):
    owner = _acct()
    for _ in range(3):
        _legacy(owner, _jpeg((900, 600)))
    assert "1 looked at" in _run("--limit", "1")
    assert MediaVariant.objects.filter(kind="display_640").count() == 1
    assert "processed 2 images" in _run()


def test_the_backfill_survives_a_missing_object(memory_storage):
    owner = _acct()
    lost = _legacy(owner, _jpeg((900, 600)))
    storage.delete(lost.storage_key)
    ok = _legacy(owner, _jpeg((900, 600)))
    out = _run()
    assert "processed 1 images" in out and "1 failed" in out
    assert set(_variants(ok)) == {"thumb", "display_640"}


def test_the_backfill_records_the_real_size_of_an_old_thumbnail_row(memory_storage):
    """Rows written before WP 4c.5-B3 say 320 x 320 whatever the image: the backfill
    reads the thumbnail object's real size (the object is not rewritten), and a
    square image's true 320 x 320 thumbnail is left as it is."""
    owner = _acct()

    def old(size):
        content = _jpeg(size)
        asset = _legacy(owner, content)
        thumb = asset.variants.get(kind="thumb")
        storage.write(thumb.storage_key, tasks._thumbnail(content), "image/jpeg")
        thumb.height = 320
        thumb.save(update_fields=["height"])
        return asset, thumb

    wide, wide_thumb = old((1600, 1200))
    square, square_thumb = old((900, 900))
    _run()  # sizes and display copies
    MediaVariant.objects.filter(pk=wide_thumb.pk).update(width=320, height=320)
    displays = {
        v.kind: storage.read(v.storage_key)
        for v in MediaVariant.objects.filter(media=wide, kind__startswith="display")
    }
    thumb_bytes = storage.read(wide_thumb.storage_key)

    # Only the thumbnail row is out of date: it is fixed, nothing is re-encoded.
    assert "processed 1 images and 0 videos (0 variants written); 1 already done" in _run()
    wide_thumb.refresh_from_db()
    square_thumb.refresh_from_db()
    assert (wide_thumb.width, wide_thumb.height) == (320, 240)
    assert (square_thumb.width, square_thumb.height) == (320, 320)
    assert storage.read(wide_thumb.storage_key) == thumb_bytes
    assert set(displays) == {"display_640", "display_1280"}
    assert all(
        storage.read(v.storage_key) == displays[v.kind]
        for v in MediaVariant.objects.filter(media=wide, kind__startswith="display")
    )
    assert "processed 0 images and 0 videos (0 variants written); 2 already done" in _run()
    assert {wide.id, square.id} == set(
        MediaVariant.objects.filter(kind="thumb").values_list("media_id", flat=True)
    )
