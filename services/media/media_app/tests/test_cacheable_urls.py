"""WP 4c.5-B3 (08 section 7.8): display GETs are signed per time bucket.

Within one bucket of ``MEDIA_DISPLAY_URL_BUCKET_SECONDS`` every request gets the
same URL for an image, a thumb, a display size or a poster, served with
``Cache-Control: private, max-age=<bucket>``, so the browser cache hits across
reloads. Every URL stays valid >= 55 min from the moment it is served, and the
payload says until when (``urls_expire_at``). Downloads and the MP4 keep their
per-request URLs.
"""

from __future__ import annotations

import datetime as dt
import time
import types
import uuid
from urllib.parse import parse_qs, urlsplit

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from media_app import services, storage
from media_app.models import MediaAsset, MediaVariant

pytestmark = pytest.mark.django_db
BUCKET = 3600
T0 = 1_762_000_000 - 1_762_000_000 % BUCKET  # a bucket start


def _acct() -> str:
    return str(uuid.uuid4())


def _query(url: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}


def _photo(owner, *, variants=("thumb", "display_640", "display_1280")) -> MediaAsset:
    asset = MediaAsset.objects.create(
        owner_id=owner,
        kind="image",
        mime="image/jpeg",
        storage_key=f"image/{owner}/{uuid.uuid4()}",
        status=MediaAsset.Status.READY,
        width=1600,
        height=1200,
    )
    sizes = {"thumb": (320, 240), "display_640": (640, 480), "display_1280": (1280, 960)}
    for kind in variants:
        ext = "jpg" if kind == "thumb" else "webp"
        MediaVariant.objects.create(
            media=asset,
            kind=kind,
            storage_key=f"{asset.storage_key}/{kind}.{ext}",
            width=sizes[kind][0],
            height=sizes[kind][1],
        )
    return asset


@pytest.fixture
def clock(monkeypatch, settings):
    """A clock for the signing code only (``time.time`` itself stays real: the
    viewer's token is checked against it)."""
    settings.MEDIA_DISPLAY_URL_BUCKET_SECONDS = BUCKET
    state = {"now": T0 + 10.0}
    fake = types.SimpleNamespace(
        time=lambda: state["now"], strftime=time.strftime, gmtime=time.gmtime
    )
    monkeypatch.setattr(services, "time", fake)
    monkeypatch.setattr(storage, "time", fake)
    return state


def _resolve(client, ids):
    resp = client.post(reverse("media_app:resolve"), {"ids": [str(i) for i in ids]}, format="json")
    assert resp.status_code == 200
    return resp.json()["data"]


def test_two_resolves_in_one_bucket_return_identical_urls(client_for, clock):
    owner = _acct()
    photo = _photo(owner)
    client = client_for(owner)
    first = _resolve(client, [photo.id])
    clock["now"] = T0 + BUCKET - 1  # the last second of the bucket
    second = _resolve(client, [photo.id])
    assert first == second  # byte-identical, URLs and expiry included
    clock["now"] = T0 + BUCKET  # the next bucket
    third = _resolve(client, [photo.id])
    assert third[0]["url"] != first[0]["url"]


def test_every_display_url_is_cacheable_and_valid_at_least_55_minutes(client_for, clock):
    owner = _acct()
    photo = _photo(owner)
    client = client_for(owner)
    for now in (T0, T0 + 1800, T0 + BUCKET - 1):
        clock["now"] = now
        (item,) = _resolve(client, [photo.id])
        urls = [item["url"], *(v["url"] for v in item["variants"])]
        assert len(urls) == 4
        for url in urls:
            query = _query(url)
            assert query["response-cache-control"] == "private, max-age=3600"
            assert int(query["X-Amz-Expires"]) == BUCKET + storage.DISPLAY_URL_MIN_VALID_SECONDS
        assert item["urls_expire_at"] == T0 + BUCKET + 3300
        assert item["urls_expire_at"] - now >= 3300


def test_the_bucket_follows_the_setting(client_for, clock, settings):
    settings.MEDIA_DISPLAY_URL_BUCKET_SECONDS = 600
    owner = _acct()
    clock["now"] = T0 + 650
    (item,) = _resolve(client_for(owner), [_photo(owner).id])
    assert _query(item["url"])["response-cache-control"] == "private, max-age=600"
    assert item["urls_expire_at"] == T0 + 600 + 600 + 3300


def test_downloads_and_the_mp4_keep_per_request_urls(client_for, clock, settings):
    owner = _acct()
    pdf = MediaAsset.objects.create(
        owner_id=owner,
        kind="file",
        mime="application/pdf",
        storage_key=f"file/{owner}/{uuid.uuid4()}",
        status=MediaAsset.Status.READY,
    )
    data = services.asset_payload(pdf)
    query = _query(data["url"])
    assert "response-cache-control" not in query
    assert query["response-content-disposition"].startswith("attachment;")
    assert data["urls_expire_at"] == int(clock["now"]) + settings.SIGNED_URL_TTL

    video = MediaAsset.objects.create(
        owner_id=owner,
        kind="video",
        purpose="post",
        mime="video/mp4",
        storage_key=f"videos/{owner}/{uuid.uuid4()}",
        status=MediaAsset.Status.READY,
    )
    for kind, name in (("poster", "poster.jpg"), ("mp4", "fallback.mp4")):
        MediaVariant.objects.create(
            media=video, kind=kind, storage_key=f"{video.storage_key}/{name}"
        )
    data = services.asset_payload(video)
    assert data["url"] is None  # a transcoded original is never served
    by_kind = {v["kind"]: _query(v["url"]) for v in data["variants"]}
    assert by_kind["poster"]["response-cache-control"] == "private, max-age=3600"
    assert "response-cache-control" not in by_kind["mp4"]
    # The earliest expiry wins: the MP4's.
    assert data["urls_expire_at"] == int(clock["now"]) + settings.SIGNED_URL_TTL


def test_no_urls_no_expiry(client_for):
    owner = _acct()
    asset = MediaAsset.objects.create(
        owner_id=owner,
        kind="image",
        mime="image/jpeg",
        storage_key=f"image/{owner}/{uuid.uuid4()}",
        status=MediaAsset.Status.PROCESSING,
    )
    data = services.asset_payload(asset)
    assert data["url"] is None and data["urls_expire_at"] is None
    assert "width" not in data  # unknown: never invented


def test_resolve_costs_the_same_queries_with_more_variants(client_for, clock):
    """The display sizes add no query: 3 photos cost the same with 1 or 3 variants
    each (the batch prefetches them), and the same as before WP 4c.5-B3 (measured on
    the previous build: 2 queries for this call)."""
    owner = _acct()
    client = client_for(owner)
    lean = [_photo(owner, variants=("thumb",)) for _ in range(3)]
    full = [_photo(owner) for _ in range(3)]
    counts = []
    for photos in (lean, full):
        with CaptureQueriesContext(connection) as ctx:
            _resolve(client, [p.id for p in photos])
        counts.append(len(ctx.captured_queries))
    assert counts[0] == counts[1] == RESOLVE_QUERIES


# Measured on the build before this WP (same call, same fixtures).
RESOLVE_QUERIES = 2


def test_the_s3_signature_matches_boto3_with_the_cache_override(settings, monkeypatch):
    import botocore.auth

    settings.STORAGE_BACKEND = "s3"
    settings.S3_ENDPOINT_URL = "http://minio:9000"
    settings.S3_PUBLIC_ENDPOINT_URL = "https://tara.example"
    settings.S3_ACCESS_KEY, settings.S3_SECRET_KEY = "AKIDEXAMPLE", "secret/with+chars"
    storage._client.cache_clear()
    monkeypatch.setattr(
        botocore.auth,
        "get_current_datetime",
        lambda *a, **k: dt.datetime.fromtimestamp(T0, dt.UTC).replace(tzinfo=None),
    )
    try:
        key = "image/o/i/display_640.webp"
        expected = storage._client(public=True).generate_presigned_url(
            "get_object",
            Params={
                "Bucket": settings.S3_BUCKET,
                "Key": key,
                "ResponseContentType": "image/webp",
                "ResponseCacheControl": "private, max-age=3600",
            },
            ExpiresIn=6900,
        )
        ours = storage.presign_get_at(
            key,
            signed_at=T0,
            expires=6900,
            content_type="image/webp",
            cache_control="private, max-age=3600",
        )
        assert parse_qs(urlsplit(ours).query) == parse_qs(urlsplit(expected).query)
        assert urlsplit(ours)._replace(query="") == urlsplit(expected)._replace(query="")
    finally:
        storage._client.cache_clear()
