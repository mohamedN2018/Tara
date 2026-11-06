"""WP 4c.6-B3 (08 section 7.9): a thumb-sized poster for the feed.

A new transcode writes ``poster_480`` (JPEG, short side 480, never upscaled) next to
``poster.jpg``; the playback payload carries ``poster_480_url`` (bucketed and
cacheable like every display GET; null when there is none). ``poster_url`` and the
access rules are unchanged: a viewer who may not watch still gets a 404.
"""

from __future__ import annotations

import io
import shutil
import subprocess
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from django.urls import reverse
from PIL import Image

from media_app import storage
from media_app.models import MediaAsset, MediaVariant, UploadSession

pytestmark = pytest.mark.django_db
needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")


def _acct() -> str:
    return str(uuid.uuid4())


def _clip(tmp_path: Path, size: str) -> bytes:
    path = tmp_path / f"clip-{size}.mp4"
    subprocess.run(  # noqa: S603
        [  # noqa: S607
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"testsrc=size={size}:rate=30:duration=1",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
        timeout=120,
    )  # fmt: skip
    return path.read_bytes()


@pytest.fixture
def scratch(settings, tmp_path):
    settings.MEDIA_TRANSCODE_SCRATCH_DIR = str(tmp_path / "scratch")


@pytest.fixture
def eager_commit(django_capture_on_commit_callbacks):
    def _run(fn):
        with django_capture_on_commit_callbacks(execute=True):
            return fn()

    return _run


def _ready_video(client, content: bytes, eager_commit) -> MediaAsset:
    signed = client.post(
        reverse("media_app:sign-upload"),
        {"kind": "video", "mime": "video/mp4", "size": len(content), "purpose": "post"},
        format="json",
    )
    assert signed.status_code == 201, signed.content
    media_id = signed.json()["data"]["media_id"]
    storage.write(UploadSession.objects.get(media_id=media_id).staging_key, content, "video/mp4")
    resp = eager_commit(lambda: client.post(reverse("media_app:complete-upload", args=[media_id])))
    assert resp.status_code == 200, resp.content
    asset = MediaAsset.objects.get(id=media_id)
    assert asset.status == MediaAsset.Status.READY, asset.error
    return asset


def _playback(client, media_id):
    return client.get(reverse("media_app:playback", args=[media_id]))


@needs_ffmpeg
def test_a_new_transcode_writes_poster_480_and_the_payload_serves_it(
    client_for, memory_storage, eager_commit, scratch, tmp_path
):
    owner = _acct()
    client = client_for(owner)
    asset = _ready_video(client, _clip(tmp_path, "1280x720"), eager_commit)
    variants = {v.kind: v for v in asset.variants.all()}
    small = variants["poster_480"]
    assert small.storage_key == f"{asset.storage_key}/poster_480.jpg"
    image = Image.open(io.BytesIO(storage.read(small.storage_key)))
    assert image.format == "JPEG" and image.size == (853, 480) == (small.width, small.height)
    assert (variants["poster"].width, variants["poster"].height) == (1280, 720)

    data = _playback(client, asset.id).json()["data"]
    assert data["poster_url"] and data["poster_480_url"]
    assert "poster_480.jpg" in data["poster_480_url"]
    query = {k: v[0] for k, v in parse_qs(urlsplit(data["poster_480_url"]).query).items()}
    assert query["response-cache-control"].startswith("private, max-age=")
    assert "poster_480.jpg" not in data["poster_url"]
    # The batch lookup carries it too.
    batch = client.post(
        reverse("media_app:playback-resolve"), {"ids": [str(asset.id)]}, format="json"
    ).json()["data"]
    assert batch[0]["poster_480_url"] == data["poster_480_url"]


@needs_ffmpeg
def test_a_small_poster_is_never_upscaled(
    client_for, memory_storage, eager_commit, scratch, tmp_path
):
    owner = _acct()
    client = client_for(owner)
    asset = _ready_video(client, _clip(tmp_path, "640x360"), eager_commit)
    assert not asset.variants.filter(kind="poster_480").exists()
    assert not storage.memory_keys(f"{asset.storage_key}/poster_480")
    data = _playback(client, asset.id).json()["data"]
    assert data["poster_url"] and data["poster_480_url"] is None


def _ready_row(owner, *, post_id=None, with_small=True) -> MediaAsset:
    asset = MediaAsset.objects.create(
        owner_id=owner,
        kind="video",
        purpose="post",
        mime="video/mp4",
        storage_key=f"videos/{owner}/{uuid.uuid4()}",
        status=MediaAsset.Status.READY,
        post_id=post_id,
    )
    MediaVariant.objects.create(
        media=asset, kind="poster", storage_key=f"{asset.storage_key}/poster.jpg", width=1280,
        height=720,
    )  # fmt: skip
    if with_small:
        MediaVariant.objects.create(
            media=asset, kind="poster_480", storage_key=f"{asset.storage_key}/poster_480.jpg",
            width=853, height=480,
        )  # fmt: skip
    return asset


def test_the_field_is_null_for_an_older_video(client_for):
    owner = _acct()
    asset = _ready_row(owner, with_small=False)
    data = _playback(client_for(owner), asset.id).json()["data"]
    assert "poster_480_url" in data and data["poster_480_url"] is None
    assert data["poster_url"]


def test_the_404_rules_are_unchanged(client_for, post_visibility):
    owner, stranger, allowed = _acct(), _acct(), _acct()
    post_id = uuid.uuid4()
    asset = _ready_row(owner, post_id=post_id)
    post_visibility.allow(allowed, post_id)
    assert _playback(client_for(stranger), asset.id).status_code == 404
    on_no_post = _ready_row(owner)
    assert _playback(client_for(allowed), on_no_post.id).status_code == 404
    data = _playback(client_for(allowed), asset.id).json()["data"]
    assert data["poster_480_url"]
    # The batch leaves the forbidden one out, as before.
    batch = client_for(stranger).post(
        reverse("media_app:playback-resolve"), {"ids": [str(asset.id)]}, format="json"
    )
    assert batch.json()["data"] == []
