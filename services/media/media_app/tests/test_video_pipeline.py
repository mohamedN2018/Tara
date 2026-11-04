"""Step 5 in media: the video pipeline (5.2) and secure playback (5.3).

The clips are made with the image's own ffmpeg (lavfi test sources), so the
real probe, transcode, poster and metadata stripping run end to end against
the in-memory bucket.
"""

from __future__ import annotations

import datetime as dt
import io
import json
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import jwt
import pytest
from django.conf import settings
from django.core.cache import cache
from django.urls import reverse
from PIL import Image

from media_app import playback, storage, transcode
from media_app.models import MediaAsset, MediaVariant, OutboxEvent, UploadSession
from media_app.validation import matches_signature

pytestmark = pytest.mark.django_db

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
LOCATION = "+30.0444+031.2357/"


def _acct() -> str:
    return str(uuid.uuid4())


def _ffmpeg(*args: str) -> None:
    subprocess.run(  # noqa: S603
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args],  # noqa: S607
        check=True,
        timeout=120,
    )


def _ffprobe(path: Path) -> dict:
    out = subprocess.run(  # noqa: S603
        ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],  # noqa: S607
        check=True,
        capture_output=True,
        timeout=60,
    )
    return json.loads(out.stdout)


def _no_source_metadata(info: dict) -> bool:
    """No location tag (``chroma_location`` is a pixel format field, not a place)."""
    tags = [info.get("format", {}).get("tags", {})] + [s.get("tags", {}) for s in info["streams"]]
    text = json.dumps(info)
    return (
        not any("location" in k.lower() for t in tags for k in t)
        and LOCATION not in text
        and "PhoneMaker" not in text
    )


def _clip(tmp_path: Path, *, seconds=3, size="640x360", name="clip.mp4", extra=()) -> bytes:
    """A test-pattern clip with a tone and a phone-style location tag."""
    path = tmp_path / name
    _ffmpeg(
        "-f", "lavfi", "-i", f"testsrc=size={size}:rate=30:duration={seconds}",
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest",
        "-metadata", f"location={LOCATION}", "-metadata", "make=PhoneMaker",
        *extra, str(path),
    )  # fmt: skip
    return path.read_bytes()


@pytest.fixture
def scratch(settings, tmp_path):
    settings.MEDIA_TRANSCODE_SCRATCH_DIR = str(tmp_path / "scratch")
    return Path(settings.MEDIA_TRANSCODE_SCRATCH_DIR)


@pytest.fixture
def eager_commit(django_capture_on_commit_callbacks):
    """Run on_commit callbacks (the transcode enqueue) while the test is in a transaction."""

    def _run(fn):
        with django_capture_on_commit_callbacks(execute=True):
            return fn()

    return _run


def _sign(client, *, size, mime="video/mp4", purpose="post", kind="video"):
    return client.post(
        reverse("media_app:sign-upload"),
        {"kind": kind, "mime": mime, "size": size, "purpose": purpose},
        format="json",
    )


def _upload(client, content: bytes, *, mime="video/mp4") -> str:
    signed = _sign(client, size=len(content), mime=mime)
    assert signed.status_code == 201, signed.content
    media_id = signed.json()["data"]["media_id"]
    storage.write(UploadSession.objects.get(media_id=media_id).staging_key, content, mime)
    return media_id


def _complete(client, media_id):
    return client.post(reverse("media_app:complete-upload", args=[media_id]))


def _outbox(event_type: str) -> int:
    return OutboxEvent.objects.filter(event_type=event_type).count()


def _ready_video(client_for, owner, tmp_path, eager_commit, **clip) -> MediaAsset:
    client = client_for(owner)
    media_id = _upload(client, _clip(tmp_path, **clip))
    resp = eager_commit(lambda: _complete(client, media_id))
    assert resp.status_code == 200, resp.content
    return MediaAsset.objects.get(id=media_id)


# ---- upload: types, caps, quota ---------------------------------------------------


def test_quicktime_is_accepted_for_post_videos_only(client_for):
    client = client_for(_acct())
    assert _sign(client, size=100, mime="video/quicktime").status_code == 201
    assert _sign(client, size=100, mime="video/webm").status_code == 201
    # Chat video is played as uploaded: browsers cannot play most .mov files.
    assert _sign(client, size=100, mime="video/quicktime", purpose="").status_code == 400
    # A purpose is for videos.
    assert _sign(client, size=100, mime="image/png", kind="image").status_code == 400


def test_quicktime_signatures():
    assert matches_signature("video/quicktime", b"\x00\x00\x00\x14ftypqt  " + b"\x00" * 8)
    assert matches_signature("video/quicktime", b"\x00\x00\x00\x08wide\x00\x00\x00\x00mdat")
    assert not matches_signature("video/quicktime", b"<!DOCTYPE html><html>")


def test_per_purpose_size_cap(client_for, settings):
    settings.MEDIA_VIDEO_PURPOSES = {"post": {"max_bytes": 1000, "max_seconds": 60}}
    resp = _sign(client_for(_acct()), size=1001)
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "video_too_large"


def test_daily_quota_per_account(client_for, settings):
    settings.MEDIA_VIDEO_DAILY_UPLOADS = 2
    settings.MEDIA_VIDEO_DAILY_BYTES = 10_000
    owner = client_for(_acct())
    assert _sign(owner, size=100).status_code == 201
    assert _sign(owner, size=100).status_code == 201
    third = _sign(owner, size=100)
    assert third.status_code == 429
    assert third.json()["error"]["code"] == "video_quota_exceeded"
    # Another account has its own quota; bytes count too.
    other = client_for(_acct())
    assert _sign(other, size=10_001).status_code == 429
    assert _sign(other, size=9_000).status_code == 201


def test_html_disguised_as_mp4_fails_and_is_deleted(client_for, memory_storage, eager_commit):
    owner = _acct()
    client = client_for(owner)
    media_id = _upload(client, b"<!DOCTYPE html><html><script>alert(1)</script></html>")
    staging = UploadSession.objects.get(media_id=media_id).staging_key
    resp = eager_commit(lambda: _complete(client, media_id))
    assert resp.status_code == 400
    asset = MediaAsset.objects.get(id=media_id)
    assert asset.status == MediaAsset.Status.FAILED
    assert storage.stat(staging, 8) is None
    assert storage.stat(asset.storage_key, 8) is None
    assert _outbox("media.processed") == 0


# ---- transcode ---------------------------------------------------------------------


@needs_ffmpeg
def test_clip_becomes_ready_with_240p_and_360p_only(
    client_for, memory_storage, eager_commit, scratch, tmp_path
):
    # The source really carries a location (so stripping it is what the test checks).
    src = tmp_path / "src"
    src.mkdir()
    _clip(src)
    assert not _no_source_metadata(_ffprobe(src / "clip.mp4"))
    owner = _acct()
    asset = _ready_video(client_for, owner, tmp_path, eager_commit)
    assert asset.storage_key.startswith(f"videos/{owner}/")
    assert asset.status == MediaAsset.Status.READY, (asset.failure_code, asset.error)
    hls = asset.variants.filter(kind=MediaVariant.Kind.HLS).order_by("height")
    assert [(v.width, v.height) for v in hls] == [(426, 240), (640, 360)]  # never upscaled
    assert abs(asset.duration_ms - 3000) <= 150
    assert (asset.width, asset.height) == (640, 360)

    poster = asset.variants.get(kind=MediaVariant.Kind.POSTER)
    with Image.open(io.BytesIO(storage.read(poster.storage_key))) as img:
        assert img.size == (640, 360) == (poster.width, poster.height)
        assert not img.getexif()

    # No location (or any other source metadata) in what viewers get.
    for v in hls:
        segment = next(ln for ln in v.manifest.splitlines() if ln.endswith(".ts"))
        path = tmp_path / f"{v.height}.ts"
        path.write_bytes(storage.read(f"{v.storage_key}/{segment}"))
        assert _no_source_metadata(_ffprobe(path))

    # The original is gone, the scratch dir is empty, one event was recorded.
    assert storage.stat(asset.storage_key, 8) is None
    assert asset.original_deleted
    assert list(scratch.iterdir()) == []
    assert _outbox("media.processed") == 1
    event = OutboxEvent.objects.get(event_type="media.processed").payload["payload"]
    assert event["renditions"] == [240, 360]
    assert event["purpose"] == "post"


@needs_ffmpeg
def test_replayed_steps_publish_media_processed_exactly_once(
    client_for, memory_storage, eager_commit, scratch, tmp_path
):
    asset = _ready_video(client_for, _acct(), tmp_path, eager_commit, seconds=1, size="320x180")
    assert asset.status == MediaAsset.Status.READY
    # A broker redelivery of any step finds the video ready and does nothing.
    transcode.finalize(str(asset.id))
    transcode.finalize(str(asset.id))
    transcode.prepare(str(asset.id))
    transcode.rendition(str(asset.id), 180)
    assert _outbox("media.processed") == 1
    assert MediaAsset.objects.get(id=asset.id).status == MediaAsset.Status.READY


@needs_ffmpeg
def test_too_long_fails_with_code_and_empty_scratch(
    client_for, memory_storage, eager_commit, scratch, tmp_path, settings
):
    settings.MEDIA_VIDEO_PURPOSES = {"post": {"max_bytes": 10**8, "max_seconds": 2}}
    asset = _ready_video(client_for, _acct(), tmp_path, eager_commit, seconds=4, size="320x180")
    assert asset.status == MediaAsset.Status.FAILED
    assert asset.failure_code == "too_long"
    assert list(scratch.iterdir()) == []
    assert not asset.variants.exists()
    assert storage.memory_keys(f"{asset.storage_key}") == []  # outputs and original removed
    failed = OutboxEvent.objects.get(event_type="media.failed").payload["payload"]
    assert failed["code"] == "too_long"
    assert _outbox("media.processed") == 0


@needs_ffmpeg
def test_keep_originals_flag(client_for, memory_storage, eager_commit, scratch, tmp_path, settings):
    settings.MEDIA_KEEP_VIDEO_ORIGINALS = True
    asset = _ready_video(client_for, _acct(), tmp_path, eager_commit, seconds=1, size="320x180")
    assert asset.status == MediaAsset.Status.READY
    assert storage.stat(asset.storage_key, 8) is not None
    assert not asset.original_deleted


@needs_ffmpeg
def test_mp4_fallback_and_portrait_ladder(
    client_for, memory_storage, eager_commit, scratch, tmp_path, settings
):
    settings.MEDIA_VIDEO_MP4_FALLBACK = True
    asset = _ready_video(client_for, _acct(), tmp_path, eager_commit, seconds=1, size="360x640")
    assert asset.status == MediaAsset.Status.READY
    sizes = sorted((v.width, v.height) for v in asset.variants.filter(kind="hls"))
    assert sizes == [(240, 426), (360, 640)]  # the short side follows the ladder
    mp4 = asset.variants.get(kind=MediaVariant.Kind.MP4)
    path = tmp_path / "fallback.mp4"
    path.write_bytes(storage.read(mp4.storage_key))
    head = path.read_bytes()[:4096]
    assert b"moov" in head  # faststart: the index comes first
    assert _no_source_metadata(_ffprobe(path))


def _hdr_clip(tmp_path) -> bytes:
    return _clip(
        tmp_path,
        seconds=1,
        size="320x180",
        name="hdr.mp4",
        extra=(
            "-vf",
            "setparams=color_primaries=bt2020:color_trc=smpte2084:colorspace=bt2020nc,"
            "format=yuv420p",
        ),
    )


@needs_ffmpeg
def test_hdr_is_rejected_with_a_clear_code(
    client_for, memory_storage, eager_commit, scratch, tmp_path, settings
):
    settings.MEDIA_VIDEO_HDR_MODE = "reject"
    owner = _acct()
    client = client_for(owner)
    media_id = _upload(client, _hdr_clip(tmp_path))
    eager_commit(lambda: _complete(client, media_id))
    asset = MediaAsset.objects.get(id=media_id)
    assert (asset.status, asset.failure_code) == (MediaAsset.Status.FAILED, "hdr_unsupported")


@needs_ffmpeg
def test_hdr_is_tone_mapped(client_for, memory_storage, eager_commit, scratch, tmp_path):
    client = client_for(_acct())
    media_id = _upload(client, _hdr_clip(tmp_path))
    eager_commit(lambda: _complete(client, media_id))
    asset = MediaAsset.objects.get(id=media_id)
    assert asset.status == MediaAsset.Status.READY, (asset.failure_code, asset.error)
    assert asset.video_meta["probe"]["hdr"] is True
    rendition = asset.variants.filter(kind="hls").first()
    segment = next(ln for ln in rendition.manifest.splitlines() if ln.endswith(".ts"))
    path = tmp_path / "sdr.ts"
    path.write_bytes(storage.read(f"{rendition.storage_key}/{segment}"))
    stream = next(s for s in _ffprobe(path)["streams"] if s["codec_type"] == "video")
    assert stream.get("color_transfer") != "smpte2084"


@needs_ffmpeg
def test_a_step_that_runs_too_long_is_killed(
    client_for, memory_storage, eager_commit, scratch, tmp_path, settings
):
    settings.MEDIA_TRANSCODE_STEP_TIMEOUT = 0.001
    asset = _ready_video(client_for, _acct(), tmp_path, eager_commit, seconds=1, size="320x180")
    assert (asset.status, asset.failure_code) == (MediaAsset.Status.FAILED, "timeout")
    assert list(scratch.iterdir()) == []


def test_at_most_three_attempts_per_step(client_for, memory_storage, settings):
    owner = _acct()
    asset = MediaAsset.objects.create(
        owner_id=owner,
        kind="video",
        purpose="post",
        mime="video/mp4",
        storage_key=f"videos/{owner}/x",
        status=MediaAsset.Status.PROCESSING,
        video_meta={"tries": {"prepare": 3}},
    )
    transcode.prepare(str(asset.id))
    asset.refresh_from_db()
    assert (asset.status, asset.failure_code) == (MediaAsset.Status.FAILED, "too_many_attempts")


def test_not_a_video_fails_as_unreadable(client_for, memory_storage, eager_commit, scratch):
    """Right signature, garbage after it: ffprobe refuses it, nothing leaks."""
    if shutil.which("ffprobe") is None:
        pytest.skip("needs ffprobe")
    client = client_for(_acct())
    media_id = _upload(client, b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 4096)
    eager_commit(lambda: _complete(client, media_id))
    asset = MediaAsset.objects.get(id=media_id)
    assert (asset.status, asset.failure_code) == (MediaAsset.Status.FAILED, "unreadable")
    assert list(scratch.iterdir()) == []


# ---- playback ----------------------------------------------------------------------


def _ready_row(owner, *, post_id=None) -> MediaAsset:
    """A transcoded video as the transcoder leaves it (no ffmpeg needed)."""
    asset = MediaAsset.objects.create(
        owner_id=owner,
        kind="video",
        purpose="post",
        mime="video/mp4",
        storage_key=f"videos/{owner}/{uuid.uuid4()}",
        status=MediaAsset.Status.READY,
        duration_ms=3000,
        width=640,
        height=360,
        post_id=post_id,
        video_meta={"probe": {"has_audio": True}},
    )
    manifest = (
        "#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:4\n#EXT-X-PLAYLIST-TYPE:VOD\n"
        "#EXTINF:3.000000,\nseg_00000.ts\n#EXT-X-ENDLIST\n"
    )
    for w, h in ((426, 240), (640, 360)):
        MediaVariant.objects.create(
            media=asset,
            kind="hls",
            storage_key=f"{asset.storage_key}/hls/{h}",
            width=w,
            height=h,
            bitrate=500_000,
            manifest=manifest,
        )
    MediaVariant.objects.create(
        media=asset, kind="poster", storage_key=f"{asset.storage_key}/poster.jpg", width=640,
        height=360,
    )  # fmt: skip
    return asset


def _playback(client, media_id):
    return client.get(reverse("media_app:playback", args=[media_id]))


def _get(url_path: str):
    from rest_framework.test import APIClient

    return APIClient().get(f"/api/v1/{url_path}")


def test_owner_plays_through_tokenised_playlists(client_for):
    owner = _acct()
    asset = _ready_row(owner)
    resp = _playback(client_for(owner), asset.id)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["hls_url"].startswith(f"media/{asset.id}/hls/master.m3u8?token=")
    assert data["poster_url"]
    master = _get(data["hls_url"])
    assert master.status_code == 200
    assert master["Content-Type"] == playback.PLAYLIST_TYPE
    assert "private" in master["Cache-Control"]
    body = master.content.decode()
    assert "RESOLUTION=426x240" in body and "RESOLUTION=640x360" in body
    assert 'CODECS="avc1.4d401e,mp4a.40.2"' in body
    token = parse_qs(urlsplit(data["hls_url"]).query)["token"][0]
    rendition = _get(f"media/{asset.id}/hls/360.m3u8?token={token}")
    assert rendition.status_code == 200
    seg = next(ln for ln in rendition.content.decode().splitlines() if ln.startswith("http"))
    assert f"{asset.storage_key}/hls/360/seg_00000.ts" in seg
    assert _get(f"media/{asset.id}/hls/720.m3u8?token={token}").status_code == 404


def test_tampered_expired_and_foreign_tokens_are_refused(client_for, settings):
    owner = _acct()
    asset = _ready_row(owner)
    other = _ready_row(owner)
    token = playback.issue_token(owner, str(asset.id))
    head, payload, sig = token.split(".")
    tampered = f"{head}.{payload}.{sig[:-2]}{'AA' if not sig.endswith('AA') else 'BB'}"
    assert _get(f"media/{asset.id}/hls/master.m3u8?token={tampered}").status_code == 401
    assert _get(f"media/{asset.id}/hls/master.m3u8").status_code == 401
    forged = jwt.encode(
        {"aud": "media-playback", "sub": owner, "mid": str(asset.id), "exp": time.time() + 60},
        "not-the-secret",
        algorithm="HS256",
    )
    assert _get(f"media/{asset.id}/hls/master.m3u8?token={forged}").status_code == 401
    # A token for another video does not open this one.
    assert _get(f"media/{other.id}/hls/master.m3u8?token={token}").status_code == 401
    settings.MEDIA_PLAYBACK_TOKEN_TTL = -5
    expired = playback.issue_token(owner, str(asset.id))
    assert _get(f"media/{asset.id}/hls/master.m3u8?token={expired}").status_code == 401
    assert _get(f"media/{asset.id}/hls/360.m3u8?token={expired}").status_code == 401


def test_another_accounts_media_id_is_404(client_for):
    asset = _ready_row(_acct())  # in a composer, on no post yet
    stranger = _acct()
    assert _playback(client_for(stranger), asset.id).status_code == 404
    assert (
        client_for(stranger).get(reverse("media_app:media-detail", args=[asset.id])).status_code
        == 404
    )
    token = playback.issue_token(stranger, str(asset.id))
    assert _get(f"media/{asset.id}/hls/master.m3u8?token={token}").status_code == 404
    assert _playback(client_for(_acct()), uuid.uuid4()).status_code == 404


def test_audience_and_blocks_come_from_post_even_when_public(client_for, post_visibility):
    owner, friend, stranger = _acct(), _acct(), _acct()
    post_id = str(uuid.uuid4())
    asset = _ready_row(owner, post_id=post_id)
    asset.visibility = "public"
    asset.save()
    post_visibility.allow(friend, post_id)
    assert _playback(client_for(friend), asset.id).status_code == 200
    # Followers-only post, a non-follower; or a public post and a blocked viewer:
    # post says "not visible" either way.
    assert _playback(client_for(stranger), asset.id).status_code == 404
    token = playback.issue_token(stranger, str(asset.id))
    assert _get(f"media/{asset.id}/hls/master.m3u8?token={token}").status_code == 404
    assert _get(f"media/{asset.id}/hls/240.m3u8?token={token}").status_code == 404
    assert (stranger, post_id) in post_visibility.calls


def test_moderator_removal_stops_playback_within_the_window(client_for, post_visibility, settings):
    owner, viewer = _acct(), _acct()
    post_id = str(uuid.uuid4())
    asset = _ready_row(owner, post_id=post_id)
    post_visibility.allow(viewer, post_id)
    url = _playback(client_for(viewer), asset.id).json()["data"]["hls_url"]
    token = parse_qs(urlsplit(url).query)["token"][0]
    rendition = _get(f"media/{asset.id}/hls/360.m3u8?token={token}").content.decode()
    seg = next(ln for ln in rendition.splitlines() if ln.startswith("http"))
    query = parse_qs(urlsplit(seg).query)
    signed = dt.datetime.strptime(query["X-Amz-Date"][0], "%Y%m%dT%H%M%SZ").replace(tzinfo=dt.UTC)
    expires_at = signed.timestamp() + int(query["X-Amz-Expires"][0])
    assert time.time() < expires_at <= time.time() + settings.MEDIA_HLS_URL_WINDOW_SECONDS
    # The moderator removes the post: post now answers "not visible". Once the
    # short access cache lapses, playlists are refused; segment URLs already
    # handed out expire within the window above.
    post_visibility.revoke(viewer, post_id)
    cache.clear()
    assert _get(f"media/{asset.id}/hls/master.m3u8?token={token}").status_code == 404
    assert _get(f"media/{asset.id}/hls/360.m3u8?token={token}").status_code == 404


def test_segment_urls_are_stable_within_a_bucket(settings):
    settings.MEDIA_HLS_URL_WINDOW_SECONDS = 300
    a = playback.segment_window(1_000_050)  # a bucket (150 s) starts here
    b = playback.segment_window(1_000_199)
    c = playback.segment_window(1_000_200)
    assert a == b and a != c
    assert a[0] == 1_000_050 and a[0] + a[1] >= 1_000_199 + 150


def test_original_is_never_served_for_transcoded_video(client_for):
    owner = _acct()
    asset = _ready_row(owner)
    detail = (
        client_for(owner).get(reverse("media_app:media-detail", args=[asset.id])).json()["data"]
    )
    assert detail["url"] is None
    assert detail["purpose"] == "post" and detail["duration_ms"] == 3000
    assert {v["kind"] for v in detail["variants"]} == {"poster"}  # HLS goes through playlists
    dl = client_for(owner).get(reverse("media_app:download-url", args=[asset.id]))
    assert dl.status_code == 404


def test_owner_sees_processing_and_failure_others_see_nothing(client_for, post_visibility):
    owner, viewer = _acct(), _acct()
    post_id = str(uuid.uuid4())
    asset = _ready_row(owner, post_id=post_id)
    asset.status, asset.failure_code = MediaAsset.Status.FAILED, "too_long"
    asset.save()
    post_visibility.allow(viewer, post_id)
    mine = _playback(client_for(owner), asset.id).json()["data"]
    assert (mine["status"], mine["failure_code"], mine["hls_url"]) == ("failed", "too_long", None)
    assert _playback(client_for(viewer), asset.id).status_code == 404


def test_internal_lookup_reports_purpose(client_for):
    from media_app import services

    asset = _ready_row(_acct())
    row = services.internal_lookup([str(asset.id)])[0]
    assert (row["kind"], row["status"], row["purpose"]) == ("video", "ready", "post")


def test_bucket_signing_matches_boto3(settings, monkeypatch):
    """The deterministic presigner signs exactly what boto3 would at that instant."""
    import botocore.auth

    settings.STORAGE_BACKEND = "s3"
    settings.S3_ENDPOINT_URL = "http://minio:9000"
    settings.S3_PUBLIC_ENDPOINT_URL = "https://tara.example"
    settings.S3_ACCESS_KEY, settings.S3_SECRET_KEY = "AKIDEXAMPLE", "secret/with+chars"
    storage._client.cache_clear()
    at = 1_762_000_000
    monkeypatch.setattr(
        botocore.auth,
        "get_current_datetime",
        lambda *a, **k: dt.datetime.fromtimestamp(at, dt.UTC).replace(tzinfo=None),
    )
    try:
        key = "videos/o/i/hls/360/seg_00001.ts"
        expected = storage._client(public=True).generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.S3_BUCKET, "Key": key, "ResponseContentType": "video/mp2t"},
            ExpiresIn=300,
        )
        ours = storage.presign_get_at(key, signed_at=at, expires=300, content_type="video/mp2t")
        assert parse_qs(urlsplit(ours).query) == parse_qs(urlsplit(expected).query)
        assert urlsplit(ours)._replace(query="") == urlsplit(expected)._replace(query="")
    finally:
        storage._client.cache_clear()


def test_gunicorn_logger_skips_hls_paths():
    from config.gunicorn_logger import Logger

    calls = []

    class _Fake(Logger):
        def __init__(self):
            pass

    logger = _Fake()
    import gunicorn.glogging

    original = gunicorn.glogging.Logger.access
    gunicorn.glogging.Logger.access = lambda self, *a: calls.append(a)
    try:
        logger.access(None, None, {"PATH_INFO": "/api/v1/media/x/hls/master.m3u8"}, 0)
        logger.access(None, None, {"PATH_INFO": "/api/v1/media/x/"}, 0)
    finally:
        gunicorn.glogging.Logger.access = original
    assert len(calls) == 1


def test_transcode_tasks_route_to_their_own_queue():
    from config.celery import app

    route = app.amqp.router.route({}, "media.video.rendition")
    assert route["queue"].name == settings.MEDIA_TRANSCODE_QUEUE
    queue = next(q for q in settings.CELERY_TASK_QUEUES if q.name == settings.MEDIA_TRANSCODE_QUEUE)
    assert queue.queue_arguments["x-consumer-timeout"] > 30 * 60 * 1000


def test_event_payloads_match_their_schemas(client_for, memory_storage, eager_commit):
    """media.uploaded / processed / failed stay within their JSON Schemas (additive fields)."""
    schemas = Path("/opt/tara/libs/tara_events/tara_events/schemas")
    if not schemas.exists():
        pytest.skip("schemas are copied into the image at /opt/tara/libs")
    owner = _acct()
    asset = _ready_row(owner)
    MediaAsset.objects.filter(pk=asset.pk).update(
        status=MediaAsset.Status.PROCESSING, video_meta={"rungs": [240, 360], "probe": {}}
    )
    transcode.finalize(str(asset.id))
    other = _ready_row(owner)
    MediaAsset.objects.filter(pk=other.pk).update(status=MediaAsset.Status.PROCESSING)
    transcode.fail(str(other.id), "too_long", "4.0s is over the 2s limit")
    client = client_for(owner)
    media_id = _upload(client, b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64)
    with patch_prepare():
        assert _complete(client, media_id).status_code == 200
    for event_type in ("media.uploaded", "media.processed", "media.failed"):
        schema = json.loads((schemas / f"{event_type}.v1.json").read_text())
        for row in OutboxEvent.objects.filter(event_type=event_type):
            payload = row.payload["payload"]
            assert set(schema["required"]) <= set(payload) <= set(schema["properties"]), event_type


def patch_prepare():
    """Keep the transcoder out of a test that only completes an upload."""
    from unittest import mock

    return mock.patch("media_app.transcode.prepare.delay")
