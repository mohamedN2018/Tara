"""Server-side HEIC (iPhone photos), downloads that never render in the storage
origin, and the clean-up of abandoned uploads."""

import io
import time
import uuid
from datetime import timedelta
from urllib.parse import parse_qs, unquote, urlsplit

import jwt
import pillow_heif
import pytest
from django.conf import settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from media_app import imaging, services, storage, tasks
from media_app.models import MediaAsset, UploadSession
from media_app.validation import matches_signature

pytestmark = pytest.mark.django_db

GPS_IFD = 0x8825
ORIENTATION = 0x0112


def _acct() -> str:
    return str(uuid.uuid4())


def _heic(size=(64, 48), *, orientation=6, mode="RGB") -> bytes:
    """A real HEIC (HEVC-coded, as an iPhone writes it) with GPS EXIF and XMP."""
    pillow_heif.register_heif_opener()
    exif = Image.Exif()
    exif[ORIENTATION] = orientation
    exif[0x010F] = "Apple"
    exif[GPS_IFD] = {1: "N", 2: (30.0, 2.0, 41.0), 3: "E", 4: (31.0, 14.0, 9.0)}
    out = io.BytesIO()
    Image.new(mode, size, "red").save(
        out, format="HEIF", exif=exif.tobytes(), xmp=b"<x:xmpmeta>home</x:xmpmeta>", quality=60
    )
    return out.getvalue()


def _upload(client, content: bytes, *, kind="image", mime="image/heic") -> str:
    signed = client.post(
        reverse("media_app:sign-upload"),
        {"kind": kind, "mime": mime, "size": len(content), "visibility": "private"},
        format="json",
    )
    assert signed.status_code == 201, signed.content
    media_id = signed.json()["data"]["media_id"]
    storage.write(UploadSession.objects.get(media_id=media_id).staging_key, content, mime)
    return media_id


def _complete(client, media_id):
    return client.post(reverse("media_app:complete-upload", args=[media_id]))


def _query(url: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}


def _internal_get(media_id, **params):
    now = int(time.time())
    token = jwt.encode(
        {"iss": "chat", "aud": "media-internal", "iat": now, "exp": now + 30},
        settings.TARA_INTERNAL_JWT_SECRET,
        algorithm="HS256",
    )
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client.get(reverse("internal-media", args=[media_id]), params)


# ---- HEIC signature ---------------------------------------------------------------


@pytest.mark.parametrize("mime", ["image/heic", "image/heif"])
def test_a_real_heic_passes_the_signature_check(mime):
    assert matches_signature(mime, _heic()[:64])


@pytest.mark.parametrize(
    "head",
    [
        b"\x00\x00\x00\x18ftypmif1\x00\x00\x00\x00mif1heic",  # major brand mif1
        b"\x00\x00\x00\x18ftypmsf1\x00\x00\x00\x00msf1hevc",  # an image sequence
        b"\x00\x00\x00\x14ftypheix\x00\x00\x00\x00",  # 10-bit, no compatible brands
    ],
)
def test_every_heif_brand_passes(head):
    assert matches_signature("image/heic", head)


@pytest.mark.parametrize(
    "head",
    [
        b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom",  # an MP4 declared as HEIC
        b"\x00\x00\x00\x10ftypqt  \x00\x00\x00\x00heic",  # brand past the box end
        b"\x00\x00\x00\x08ftypheic",  # a box too short to hold a brand
        b"\xff\xd8\xff\xe0\x00\x10JFIF",  # a JPEG
        b"<!doctype html><svg onload=alert(1)>",
        b"",
    ],
)
def test_other_bytes_are_not_heic(head):
    assert not matches_signature("image/heic", head)


def test_heic_is_an_image_type_only():
    owner = _acct()
    assert services.sign_upload(owner, kind="image", mime="image/heic", size=9, visibility="public")
    assert services.sign_upload(owner, kind="image", mime="IMAGE/HEIF", size=9, visibility="public")
    with pytest.raises(services.TaraAPIError):
        services.sign_upload(owner, kind="file", mime="image/heic", size=9, visibility="public")


# ---- HEIC decoding --------------------------------------------------------------


def test_sanitized_heic_is_a_jpeg_without_metadata_and_upright():
    clean = Image.open(io.BytesIO(imaging.sanitize_image(_heic(), "image/heic")))
    assert clean.format == "JPEG"
    assert clean.size == (48, 64)  # orientation 6 applied once, not twice
    exif = clean.getexif()
    assert GPS_IFD not in exif and ORIENTATION not in exif and not exif
    assert "xmp" not in clean.info and "exif" not in clean.info
    assert imaging.stored_mime("image/heic") == imaging.stored_mime("image/heif") == "image/jpeg"
    assert imaging.stored_mime("image/png") == "image/png"


def test_a_heic_with_alpha_is_flattened_to_jpeg():
    clean = Image.open(io.BytesIO(imaging.sanitize_image(_heic(mode="RGBA"), "image/heif")))
    assert (clean.format, clean.mode) == ("JPEG", "RGB")


def test_a_heic_over_the_pixel_limit_is_refused_before_decoding(settings):
    settings.MEDIA_MAX_IMAGE_PIXELS = 1000  # the fixture is 64x48 = 3072 pixels
    with pytest.raises(imaging.ImageTooLarge):
        imaging.sanitize_image(_heic(), "image/heic")


def test_a_png_declared_as_heic_is_refused():
    png = io.BytesIO()
    Image.new("RGB", (4, 4)).save(png, "PNG")
    with pytest.raises(ValueError):
        imaging.sanitize_image(png.getvalue(), "image/heic")


def test_an_iphone_photo_uploads_as_heic_and_is_served_as_jpeg(client_for, memory_storage):
    owner = _acct()
    client = client_for(owner)
    media_id = _upload(client, _heic())
    done = _complete(client, media_id)
    assert done.status_code == 200
    assert done.json()["data"]["mime"] == "image/heic"  # until processed

    tasks.process_media(media_id)

    asset = MediaAsset.objects.get(id=media_id)
    assert (asset.status, asset.mime) == (MediaAsset.Status.READY, "image/jpeg")
    stored = storage.read(asset.storage_key)
    assert asset.bytes == len(stored)
    image = Image.open(io.BytesIO(stored))
    assert image.format == "JPEG" and not image.getexif()
    assert memory_storage._memory[asset.storage_key][1] == "image/jpeg"

    data = client.get(reverse("media_app:media-detail", args=[media_id])).json()["data"]
    assert data["mime"] == "image/jpeg"
    assert _query(data["url"])["response-content-type"] == "image/jpeg"
    assert "response-content-disposition" not in _query(data["url"])  # shown in place
    thumb = Image.open(io.BytesIO(storage.read(f"{asset.storage_key}/thumb.jpg")))
    assert thumb.format == "JPEG"


def test_an_over_limit_heic_fails_processing_and_is_never_served(
    client_for, memory_storage, settings
):
    settings.MEDIA_MAX_IMAGE_PIXELS = 1000
    owner = _acct()
    client = client_for(owner)
    media_id = _upload(client, _heic())
    assert _complete(client, media_id).status_code == 200
    tasks.process_media(media_id)
    asset = MediaAsset.objects.get(id=media_id)
    assert (asset.status, asset.mime) == (MediaAsset.Status.FAILED, "image/heic")
    assert client.get(reverse("media_app:download-url", args=[media_id])).status_code == 409


def test_a_jpeg_declared_as_heic_is_rejected_at_completion(client_for, memory_storage):
    jpeg = io.BytesIO()
    Image.new("RGB", (4, 4)).save(jpeg, "JPEG")
    owner = _acct()
    client = client_for(owner)
    media_id = _upload(client, jpeg.getvalue(), mime="image/heic")
    assert _complete(client, media_id).status_code == 400
    assert MediaAsset.objects.get(id=media_id).status == MediaAsset.Status.FAILED


# ---- downloads ------------------------------------------------------------------


def _ready(owner, *, kind, mime) -> MediaAsset:
    media_id = services.sign_upload(owner, kind=kind, mime=mime, size=10, visibility="private")[
        "media_id"
    ]
    MediaAsset.objects.filter(id=media_id).update(status=MediaAsset.Status.READY)
    return MediaAsset.objects.get(id=media_id)


def _disposition(url: str) -> str:
    return _query(url).get("response-content-disposition", "")


@pytest.mark.parametrize(
    ("kind", "mime"),
    [("file", "application/pdf"), ("audio", "audio/mpeg"), ("voice", "audio/ogg")],
)
def test_files_and_audio_download_instead_of_rendering(client_for, kind, mime):
    owner = _acct()
    asset = _ready(owner, kind=kind, mime=mime)
    for url in (
        client_for(owner)
        .get(reverse("media_app:media-detail", args=[asset.id]))
        .json()["data"]["url"],
        client_for(owner)
        .get(reverse("media_app:download-url", args=[asset.id]))
        .json()["data"]["download_url"],
        _internal_get(asset.id).json()["data"]["url"],
    ):
        assert _disposition(url).startswith("attachment; ")
        assert _query(url)["response-content-type"] == mime


@pytest.mark.parametrize(("kind", "mime"), [("image", "image/png"), ("video", "video/mp4")])
def test_images_and_videos_are_shown_in_place(kind, mime):
    asset = _ready(_acct(), kind=kind, mime=mime)
    url = _internal_get(asset.id).json()["data"]["url"]
    assert _disposition(url) == ""
    assert _query(url)["response-content-type"] == mime


def test_chat_names_the_download_and_the_name_is_made_safe():
    asset = _ready(_acct(), kind="file", mime="application/pdf")
    url = _internal_get(asset.id, filename="../../عقد الإيجار.pdf").json()["data"]["url"]
    disposition = _disposition(url)
    assert disposition.startswith('attachment; filename="download.pdf"; ')
    assert unquote(disposition.split("filename*=UTF-8''", 1)[1]) == "عقد الإيجار.pdf"


@pytest.mark.parametrize(
    ("requested", "expected"),
    [
        ("report.pdf", "report.pdf"),
        ("C:\\Users\\me\\report.PDF", "report.pdf"),
        ("invoice\u202efdp.exe", "invoicefdp.pdf"),  # a bidi override cannot fake the type
        ('a"b;c\r\nSet-Cookie: x.pdf', 'a"b;cSet-Cookie: x.pdf'),  # no header splitting
        ("payload.html", "payload.pdf"),  # the extension follows the real type
        ("...", None),
        ("", None),
    ],
)
def test_download_filenames(requested, expected):
    asset = _ready(_acct(), kind="file", mime="application/pdf")
    assert services.download_filename(asset, requested) == (expected or f"{asset.id}.pdf")


def test_the_fallback_name_is_quoted_ascii_and_the_full_name_is_encoded():
    header = services.attachment_disposition('a"b;c%d.pdf')
    assert header == "attachment; filename=\"abcd.pdf\"; filename*=UTF-8''a%22b%3Bc%25d.pdf"
    assert "\r" not in services.attachment_disposition("x\r\ny.pdf")


def test_s3_signs_the_response_overrides_into_the_url(settings):
    """The real presigner (no network): MinIO/S3 only honour signed overrides."""
    settings.STORAGE_BACKEND = "s3"
    settings.S3_PUBLIC_ENDPOINT_URL = "https://media.example.test"
    storage._client.cache_clear()
    try:
        asset = _ready(_acct(), kind="file", mime="application/pdf")
        url = services.asset_url(asset, filename="تقرير.pdf")
    finally:
        storage._client.cache_clear()
    query = _query(url)
    assert url.startswith(f"https://media.example.test/{settings.S3_BUCKET}/{asset.storage_key}?")
    assert query["response-content-type"] == "application/pdf"
    assert query["response-content-disposition"].startswith('attachment; filename="download.pdf"')
    assert "X-Amz-Signature" in query


# ---- abandoned uploads -----------------------------------------------------------


def _signed_upload(owner, content=b"\x89PNG\r\n\x1a\n...") -> str:
    media_id = services.sign_upload(
        owner, kind="image", mime="image/png", size=len(content), visibility="public"
    )["media_id"]
    storage.write(UploadSession.objects.get(media_id=media_id).staging_key, content, "image/png")
    return media_id


def _age(media_id, *, hours):
    UploadSession.objects.filter(media_id=media_id).update(
        expires_at=timezone.now() - timedelta(hours=hours)
    )


def test_an_abandoned_upload_fails_and_its_staging_object_goes(client_for, memory_storage):
    owner = _acct()
    stale, recent, fresh = _signed_upload(owner), _signed_upload(owner), _signed_upload(owner)
    _age(stale, hours=2)
    _age(recent, hours=0.5)  # inside the grace hour: the client may still complete it

    assert tasks.expire_stale_uploads() == 1

    asset = MediaAsset.objects.get(id=stale)
    assert (asset.status, asset.error) == (MediaAsset.Status.FAILED, "The upload expired.")
    staging = UploadSession.objects.get(media_id=stale).staging_key
    assert storage.stat(staging, 1) is None
    for other in (recent, fresh):
        assert MediaAsset.objects.get(id=other).status == MediaAsset.Status.UPLOADING
        assert storage.stat(UploadSession.objects.get(media_id=other).staging_key, 1)
    assert _complete(client_for(owner), stale).status_code == 409
    assert tasks.expire_stale_uploads() == 0  # done once


def test_a_claimed_or_completed_upload_is_never_expired(client_for, memory_storage):
    owner = _acct()
    completed, claimed = _signed_upload(owner), _signed_upload(owner)
    assert _complete(client_for(owner), completed).status_code == 200
    UploadSession.objects.filter(media_id=claimed).update(completed_at=timezone.now())
    _age(completed, hours=5)
    _age(claimed, hours=5)
    assert tasks.expire_stale_uploads() == 0
    assert MediaAsset.objects.get(id=claimed).status == MediaAsset.Status.UPLOADING


def test_the_expiry_task_is_scheduled():
    schedule = settings.CELERY_BEAT_SCHEDULE["expire-stale-uploads"]
    assert schedule["task"] == tasks.expire_stale_uploads.name


class _LifecycleClient:
    def __init__(self, rules=None, error=None):
        self.rules, self.error, self.puts = rules, error, []

    def get_bucket_lifecycle_configuration(self, Bucket):  # noqa: N803 - boto3's names
        from botocore.exceptions import ClientError

        if self.rules is None:
            raise ClientError({"Error": {"Code": "NoSuchLifecycleConfiguration"}}, "Get")
        return {"Rules": self.rules}

    def put_bucket_lifecycle_configuration(self, Bucket, LifecycleConfiguration):  # noqa: N803
        if self.error:
            raise self.error
        self.puts.append(LifecycleConfiguration["Rules"])
        self.rules = LifecycleConfiguration["Rules"]


def test_the_bucket_expires_staging_objects_and_keeps_other_rules():
    other = {"ID": "ops-rule", "Filter": {"Prefix": "logs/"}, "Status": "Enabled"}
    client = _LifecycleClient(rules=[other])
    storage.ensure_staging_expiry(client)
    (rules,) = client.puts
    assert rules[0] == other
    assert rules[1]["Filter"] == {"Prefix": "staging/"}
    assert rules[1]["Expiration"] == {"Days": 1}
    storage.ensure_staging_expiry(client)  # already there: nothing is written
    assert len(client.puts) == 1

    fresh = _LifecycleClient()
    storage.ensure_staging_expiry(fresh)
    assert [r["ID"] for r in fresh.puts[0]] == [storage.STAGING_RULE_ID]


def test_a_bucket_that_refuses_lifecycle_rules_does_not_stop_the_service():
    storage.ensure_staging_expiry(_LifecycleClient(error=RuntimeError("AccessDenied")))


# ---- processing retries a storage outage, never a bad file ------------------------


def _processing(client_for, content: bytes, mime: str) -> str:
    owner = _acct()
    client = client_for(owner)
    media_id = _upload(client, content, mime=mime)
    assert _complete(client, media_id).status_code == 200
    return media_id


def _png() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (8, 8), "blue").save(out, "PNG")
    return out.getvalue()


def test_a_storage_outage_is_retried_until_it_passes(client_for, memory_storage, monkeypatch):
    media_id = _processing(client_for, _png(), "image/png")
    real_read, calls = storage.read, []

    def flaky_read(key):
        calls.append(key)
        if len(calls) <= 2:
            raise ConnectionError("minio restarting")
        return real_read(key)

    monkeypatch.setattr(storage, "read", flaky_read)
    tasks.process_media.apply(args=[media_id])
    assert MediaAsset.objects.get(id=media_id).status == MediaAsset.Status.READY


def test_a_heic_retried_after_cleaning_is_not_cleaned_as_heic_again(
    client_for, memory_storage, monkeypatch
):
    """The thumbnail write fails after the clean JPEG replaced the HEIC."""
    media_id = _processing(client_for, _heic(), "image/heic")
    real_write, failed = storage.write, []

    def flaky_write(key, content, mime):
        if key.endswith("/thumb.jpg") and not failed:
            failed.append(key)
            raise ConnectionError("minio restarting")
        return real_write(key, content, mime)

    monkeypatch.setattr(storage, "write", flaky_write)
    tasks.process_media.apply(args=[media_id])
    asset = MediaAsset.objects.get(id=media_id)
    assert failed and (asset.status, asset.mime) == (MediaAsset.Status.READY, "image/jpeg")


def test_a_lasting_outage_fails_after_the_declared_retries(client_for, memory_storage, monkeypatch):
    media_id = _processing(client_for, _png(), "image/png")
    before = MediaAsset.objects.get(id=media_id).updated_at
    calls = []

    def down(key):
        calls.append(key)
        raise ConnectionError("minio down")

    monkeypatch.setattr(storage, "read", down)
    tasks.process_media.apply(args=[media_id])
    asset = MediaAsset.objects.get(id=media_id)
    assert len(calls) == tasks.process_media.max_retries + 1
    assert asset.status == MediaAsset.Status.FAILED
    assert asset.updated_at > before  # the failed state is dated


def test_a_bad_file_fails_at_once(client_for, memory_storage, monkeypatch):
    media_id = _processing(client_for, b"\x89PNG\r\n\x1a\nnot really", "image/png")
    real_read, calls = storage.read, []
    monkeypatch.setattr(storage, "read", lambda key: calls.append(key) or real_read(key))
    tasks.process_media.apply(args=[media_id])
    assert MediaAsset.objects.get(id=media_id).status == MediaAsset.Status.FAILED
    assert len(calls) == 1


@pytest.mark.parametrize(
    ("exc", "transient"),
    [
        (ConnectionError("x"), True),
        (TimeoutError("x"), True),
        (ValueError("bad image"), False),
        (imaging.ImageTooLarge("big"), False),
        (OSError("cannot identify image file"), False),  # PIL's UnidentifiedImageError
    ],
)
def test_what_counts_as_an_outage(exc, transient):
    assert tasks.is_transient(exc) is transient


def test_s3_errors_are_outages_only_when_s3_says_so():
    from botocore.exceptions import ClientError, EndpointConnectionError

    def client_error(code, status):
        return ClientError(
            {"Error": {"Code": code}, "ResponseMetadata": {"HTTPStatusCode": status}}, "GetObject"
        )

    assert tasks.is_transient(EndpointConnectionError(endpoint_url="http://minio:9000"))
    assert tasks.is_transient(client_error("InternalError", 500))
    assert tasks.is_transient(client_error("SlowDown", 503))
    assert not tasks.is_transient(client_error("NoSuchKey", 404))
    assert not tasks.is_transient(client_error("AccessDenied", 403))


# ---- a deleted public post: the call post makes ------------------------------------


def test_restricting_a_deleted_public_posts_media_hides_it(
    client_for, memory_storage, post_visibility, post_liveness
):
    """Post's delete: ``bind(author, post, its media, restricted=True)``. Media then
    asks post, which says a deleted post is visible to nobody: only the owner sees it."""
    owner, stranger, post_id, next_post = _acct(), _acct(), _acct(), _acct()
    media_id = _processing(client_for, _png(), "image/png")
    asset = MediaAsset.objects.get(id=media_id)
    MediaAsset.objects.filter(id=media_id).update(owner_id=owner, visibility="public")
    tasks.process_media(media_id)
    services.bind_to_post(owner, post_id, [media_id], restricted=False)  # a public post
    detail = reverse("media_app:media-detail", args=[asset.id])
    assert client_for(stranger).get(detail).status_code == 200

    result = services.bind_to_post(owner, post_id, [media_id], restricted=True)  # on delete

    assert result["bound"] == [media_id]
    assert client_for(stranger).get(detail).status_code == 404
    assert (
        client_for(stranger).get(reverse("media_app:download-url", args=[asset.id])).status_code
        == 404
    )
    assert client_for(owner).get(detail).status_code == 200
    # The owner can still post the photo again: the deleted post lets it go.
    post_liveness.answers[post_id] = False
    services.bind_to_post(owner, next_post, [media_id], restricted=False)
    assert client_for(stranger).get(detail).status_code == 200
