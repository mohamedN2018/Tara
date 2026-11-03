"""Milestone 1.5 in media: restricted post media, EXIF removal, single-use
uploads with real size and ETag, and container signature checks."""

import hashlib
import io
import time
import uuid

import jwt
import pytest
from django.conf import settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from media_app import imaging, services, storage, tasks
from media_app.models import MediaAsset, OutboxEvent, UploadSession
from media_app.post_client import can_view_post as real_can_view_post
from media_app.validation import matches_signature

pytestmark = pytest.mark.django_db

GPS_IFD = 0x8825
ORIENTATION = 0x0112


def _acct() -> str:
    return str(uuid.uuid4())


def _exif_with_gps(orientation: int = 6) -> bytes:
    exif = Image.Exif()
    exif[ORIENTATION] = orientation
    exif[0x010F] = "PhoneMaker"
    exif[GPS_IFD] = {1: "N", 2: (30.0, 2.0, 41.0), 3: "E", 4: (31.0, 14.0, 9.0)}
    return exif.tobytes()


def _jpeg_with_gps(size=(60, 30)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, "red").save(out, "JPEG", exif=_exif_with_gps(), comment=b"home")
    return out.getvalue()


def _upload(client, content: bytes, *, kind="image", mime="image/jpeg", declared=None) -> str:
    """Sign, then do what the browser's presigned PUT does: write the staging key."""
    signed = client.post(
        reverse("media_app:sign-upload"),
        {"kind": kind, "mime": mime, "size": declared or len(content), "visibility": "public"},
        format="json",
    )
    assert signed.status_code == 201
    media_id = signed.json()["data"]["media_id"]
    storage.write(UploadSession.objects.get(media_id=media_id).staging_key, content, mime)
    return media_id


def _complete(client, media_id):
    return client.post(reverse("media_app:complete-upload", args=[media_id]))


def _ready_photo(client_for, owner) -> MediaAsset:
    client = client_for(owner)
    media_id = _upload(client, _jpeg_with_gps())
    assert _complete(client, media_id).status_code == 200
    tasks.process_media(media_id)
    asset = MediaAsset.objects.get(id=media_id)
    assert asset.status == MediaAsset.Status.READY
    return asset


def _internal(audience="media-internal") -> APIClient:
    now = int(time.time())
    token = jwt.encode(
        {"iss": "post", "aud": audience, "iat": now, "exp": now + 30},
        settings.TARA_INTERNAL_JWT_SECRET,
        algorithm="HS256",
    )
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


def _bind(owner, post_id, media_ids, restricted):
    resp = _internal().post(
        reverse("internal-media-bind"),
        {
            "owner_id": str(owner),
            "post_id": str(post_id),
            "media_ids": [str(m) for m in media_ids],
            "restricted": restricted,
        },
        format="json",
    )
    assert resp.status_code == 200, resp.content
    return resp.json()["data"]


def _detail(client, media_id):
    return client.get(reverse("media_app:media-detail", args=[media_id]))


def _download(client, media_id):
    return client.get(reverse("media_app:download-url", args=[media_id]))


def _key_of(url: str) -> str:
    """The storage key a presigned URL points at."""
    path = url.split("?")[0]
    return path.split(f"/{settings.S3_BUCKET}/", 1)[1]


# ---- restricted media: viewers of a friends-only post (1.5) ------------------------


def test_friends_only_post_media_matrix(client_for, memory_storage, post_visibility):
    owner, friend, stranger, blocked, ex_friend = (_acct() for _ in range(5))
    asset = _ready_photo(client_for, owner)
    post_id = uuid.uuid4()
    _bind(owner, post_id, [asset.id], restricted=True)
    post_visibility.allow(friend, post_id)
    post_visibility.allow(ex_friend, post_id)
    post_visibility.revoke(ex_friend, post_id)  # unfriended: post now says no
    # A blocked viewer is not visible per post either (post checks blocks).

    for viewer in (owner, friend):
        detail = _detail(client_for(viewer), asset.id)
        assert detail.status_code == 200
        assert detail.json()["data"]["url"]
        assert _download(client_for(viewer), asset.id).status_code == 200
    for viewer in (stranger, blocked, ex_friend):
        assert _detail(client_for(viewer), asset.id).status_code == 404
        assert _download(client_for(viewer), asset.id).status_code == 404
    # The owner is answered locally; every other viewer goes through post.
    assert {v for v, _ in post_visibility.calls} == {friend, stranger, blocked, ex_friend}
    assert {p for _, p in post_visibility.calls} == {str(post_id)}


def test_public_post_media_stays_public(client_for, memory_storage, post_visibility):
    owner = _acct()
    asset = _ready_photo(client_for, owner)
    _bind(owner, uuid.uuid4(), [asset.id], restricted=False)
    assert _detail(client_for(_acct()), asset.id).status_code == 200
    assert post_visibility.calls == []


def test_restricted_media_without_a_post_is_owner_only(client_for, post_visibility):
    owner = _acct()
    media_id = services.sign_upload(
        owner, kind="image", mime="image/png", size=10, visibility="public"
    )["media_id"]
    MediaAsset.objects.filter(id=media_id).update(restricted=True, post_id=None)
    assert _detail(client_for(_acct()), media_id).status_code == 404
    assert _detail(client_for(owner), media_id).status_code == 200


class _Resp:
    def __init__(self, status=200, visible=None):
        self.status_code, self._visible = status, visible

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)

    def json(self):
        return {"data": {"visible": self._visible}}


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        (_Resp(200, True), True),
        (_Resp(200, False), False),
        (_Resp(200, "yes"), False),  # only a real true counts
        (_Resp(500), False),
        (ConnectionError("post down"), False),
    ],
)
def test_post_client_fails_closed(monkeypatch, answer, expected):
    seen = {}

    def fake_get(url, params, headers, timeout):
        seen.update(url=url, params=params, token=headers["Authorization"].split()[1])
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr("media_app.post_client.requests.get", fake_get)
    viewer, post_id = _acct(), _acct()
    assert real_can_view_post(viewer, post_id) is expected
    assert seen["url"].endswith(f"/internal/v1/posts/{post_id}/visibility/")
    assert seen["params"] == {"viewer_id": viewer}
    claims = jwt.decode(
        seen["token"],
        settings.TARA_INTERNAL_JWT_SECRET,
        algorithms=["HS256"],
        audience="post-internal",
    )
    assert claims["iss"] == "media"


def test_post_client_open_circuit_hides_media(monkeypatch):
    def down(*a, **k):
        raise ConnectionError("post down")

    monkeypatch.setattr("media_app.post_client.requests.get", down)
    for _ in range(5):
        assert real_can_view_post(_acct(), _acct()) is False
    calls = []
    monkeypatch.setattr("media_app.post_client.requests.get", lambda *a, **k: calls.append(1))
    assert real_can_view_post(_acct(), _acct()) is False
    assert calls == []  # the open circuit answered without calling post


def test_restricted_media_is_hidden_when_post_is_down(client_for, memory_storage, monkeypatch):
    owner = _acct()
    asset = _ready_photo(client_for, owner)
    _bind(owner, uuid.uuid4(), [asset.id], restricted=True)

    def down(*a, **k):
        raise ConnectionError("post down")

    monkeypatch.setattr("media_app.post_client.requests.get", down)
    assert _detail(client_for(_acct()), asset.id).status_code == 404
    assert _detail(client_for(owner), asset.id).status_code == 200


# ---- internal bind and batch ----------------------------------------------------------


def test_bind_needs_an_internal_token(client_for):
    url = reverse("internal-media-bind")
    body = {"owner_id": _acct(), "post_id": _acct(), "media_ids": [_acct()], "restricted": True}
    assert APIClient().post(url, body, format="json").status_code == 401
    assert _internal("post-internal").post(url, body, format="json").status_code == 401
    assert client_for(_acct()).post(url, body, format="json").status_code == 401


def test_bind_skips_media_of_other_owners_and_unknown_ids():
    owner, other = _acct(), _acct()
    mine = services.sign_upload(owner, kind="image", mime="image/png", size=1, visibility="public")
    theirs = services.sign_upload(
        other, kind="image", mime="image/png", size=1, visibility="public"
    )
    unknown = _acct()

    result = _bind(owner, _acct(), [mine["media_id"], theirs["media_id"], unknown], True)

    assert result["bound"] == [mine["media_id"]]
    assert set(result["skipped"]) == {theirs["media_id"], unknown}
    untouched = MediaAsset.objects.get(id=theirs["media_id"])
    assert (untouched.restricted, untouched.post_id) == (False, None)


def test_rebinding_the_same_post_never_lifts_a_restriction():
    owner, post_id = _acct(), _acct()
    media_id = services.sign_upload(
        owner, kind="image", mime="image/png", size=1, visibility="public"
    )["media_id"]
    _bind(owner, post_id, [media_id], True)
    _bind(owner, post_id, [media_id], False)  # late, reordered call for an older audience
    asset = MediaAsset.objects.get(id=media_id)
    assert (asset.restricted, str(asset.post_id)) == (True, post_id)


def test_binding_to_a_new_post_follows_that_post(post_liveness):
    """A post that failed after binding leaves a ghost; the next post takes over."""
    owner, ghost, real = _acct(), _acct(), _acct()
    media_id = services.sign_upload(
        owner, kind="image", mime="image/png", size=1, visibility="public"
    )["media_id"]
    _bind(owner, ghost, [media_id], True)
    post_liveness.answers[ghost] = False  # post: never committed (or deleted)
    _bind(owner, real, [media_id], False)
    asset = MediaAsset.objects.get(id=media_id)
    assert (asset.restricted, str(asset.post_id)) == (False, real)
    assert post_liveness.calls == [(owner, ghost)]


@pytest.mark.parametrize("answer", [True, None], ids=["live", "post-down"])
def test_media_of_a_live_post_cannot_be_bound_to_another(post_liveness, answer):
    """One media, one post: moving it would change who can see the first post's photo."""
    owner, first, second = _acct(), _acct(), _acct()
    media_id = services.sign_upload(
        owner, kind="image", mime="image/png", size=1, visibility="public"
    )["media_id"]
    _bind(owner, first, [media_id], True)
    post_liveness.answers[first] = answer
    result = _bind(owner, second, [media_id], False)
    assert result == {"bound": [], "skipped": [media_id], "attached_elsewhere": [media_id]}
    asset = MediaAsset.objects.get(id=media_id)
    assert (asset.restricted, str(asset.post_id)) == (True, first)


def test_binding_fresh_media_or_the_same_post_never_asks_post(post_liveness):
    owner, post_id = _acct(), _acct()
    media_id = services.sign_upload(
        owner, kind="image", mime="image/png", size=1, visibility="public"
    )["media_id"]
    _bind(owner, post_id, [media_id], False)
    _bind(owner, post_id, [media_id], True)
    assert post_liveness.calls == []


def test_bind_validates_its_payload():
    url = reverse("internal-media-bind")
    too_many = {
        "owner_id": _acct(),
        "post_id": _acct(),
        "media_ids": [_acct() for _ in range(21)],
        "restricted": True,
    }
    assert _internal().post(url, too_many, format="json").status_code == 400
    no_flag = {"owner_id": _acct(), "post_id": _acct(), "media_ids": [_acct()]}
    assert _internal().post(url, no_flag, format="json").status_code == 400


def test_batch_lookup_reports_owner_kind_status_and_binding():
    owner, post_id = _acct(), _acct()
    photo = services.sign_upload(owner, kind="image", mime="image/png", size=1, visibility="public")
    clip = services.sign_upload(owner, kind="video", mime="video/mp4", size=1, visibility="public")
    gone = services.sign_upload(owner, kind="image", mime="image/png", size=1, visibility="public")
    MediaAsset.objects.filter(id=gone["media_id"]).update(deleted_at=timezone.now())
    _bind(owner, post_id, [photo["media_id"]], True)
    url = reverse("internal-media-batch")

    assert APIClient().post(url, {"ids": []}, format="json").status_code == 401
    resp = _internal().post(
        url,
        {"ids": [photo["media_id"], clip["media_id"], gone["media_id"], _acct()]},
        format="json",
    )

    rows = {r["id"]: r for r in resp.json()["data"]}
    assert set(rows) == {photo["media_id"], clip["media_id"]}
    assert rows[photo["media_id"]]["restricted"] is True
    assert rows[photo["media_id"]]["post_id"] == post_id
    assert (rows[clip["media_id"]]["kind"], rows[clip["media_id"]]["status"]) == (
        "video",
        "uploading",
    )
    assert rows[clip["media_id"]]["owner_id"] == owner
    assert "url" not in rows[photo["media_id"]]


# ---- EXIF removal (1.5) -----------------------------------------------------------------


def test_gps_exif_is_gone_from_the_served_image(client_for, memory_storage, post_visibility):
    owner, friend = _acct(), _acct()
    original = _jpeg_with_gps(size=(60, 30))
    assert Image.open(io.BytesIO(original)).getexif().get_ifd(GPS_IFD)  # the fixture has GPS
    asset = _ready_photo(client_for, owner)
    post_id = uuid.uuid4()
    _bind(owner, post_id, [asset.id], True)
    post_visibility.allow(friend, post_id)

    data = _detail(client_for(friend), asset.id).json()["data"]
    served = storage.read(_key_of(data["url"]))
    image = Image.open(io.BytesIO(served))
    assert dict(image.getexif()) == {}  # no EXIF block at all: no GPS, no maker, no orientation
    assert b"Exif" not in served[:2048]
    assert b"home" not in served  # the JPEG comment went too
    assert image.size == (30, 60)  # orientation 6 was applied to the pixels
    thumb = Image.open(io.BytesIO(storage.read(_key_of(data["variants"][0]["url"]))))
    assert dict(thumb.getexif()) == {}

    asset.refresh_from_db()
    assert asset.bytes == len(served)  # the size of what is stored now
    assert asset.etag == f'"{hashlib.md5(served, usedforsecurity=False).hexdigest()}"'


def _png_with_metadata() -> bytes:
    from PIL.PngImagePlugin import PngInfo

    info = PngInfo()
    info.add_text("Location", "30.04N 31.23E")
    info.add_itxt("XML:com.adobe.xmp", "<x:xmpmeta>gps</x:xmpmeta>")
    out = io.BytesIO()
    Image.new("RGBA", (8, 8), (0, 0, 255, 128)).save(
        out, "PNG", pnginfo=info, exif=_exif_with_gps(1)
    )
    return out.getvalue()


def _webp_with_exif() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (8, 4)).save(
        out, "WEBP", exif=_exif_with_gps(6), xmp=b"<x:xmpmeta>gps</x:xmpmeta>"
    )
    return out.getvalue()


def _animated_gif() -> bytes:
    frames = [Image.new("RGB", (6, 6), c) for c in ("red", "green", "blue")]
    out = io.BytesIO()
    frames[0].save(
        out,
        "GIF",
        save_all=True,
        append_images=frames[1:],
        duration=[50, 60, 70],
        loop=0,
        comment=b"gps here",
    )
    return out.getvalue()


@pytest.mark.parametrize(
    ("mime", "make"),
    [
        ("image/png", _png_with_metadata),
        ("image/webp", _webp_with_exif),
        ("image/gif", _animated_gif),
    ],
)
def test_sanitize_drops_metadata_in_every_format(mime, make):
    clean = imaging.sanitize_image(make(), mime)
    image = Image.open(io.BytesIO(clean))
    assert dict(image.getexif()) == {}
    assert not any(
        k in image.info for k in ("exif", "xmp", "XML:com.adobe.xmp", "Location", "comment")
    )
    assert b"gps" not in clean.lower()


def test_sanitize_keeps_what_rendering_needs():
    gif = Image.open(io.BytesIO(imaging.sanitize_image(_animated_gif(), "image/gif")))
    assert gif.n_frames == 3
    rgba = Image.open(io.BytesIO(imaging.sanitize_image(_png_with_metadata(), "image/png")))
    assert rgba.mode == "RGBA" and rgba.getpixel((0, 0)) == (0, 0, 255, 128)
    webp = Image.open(io.BytesIO(imaging.sanitize_image(_webp_with_exif(), "image/webp")))
    assert webp.size == (4, 8)  # orientation applied


def test_sanitize_refuses_content_of_another_type():
    out = io.BytesIO()
    Image.new("RGB", (4, 4)).save(out, "PNG")
    with pytest.raises(ValueError):
        imaging.sanitize_image(out.getvalue(), "image/jpeg")


def test_an_undecodable_image_fails_processing(client_for, memory_storage):
    owner = _acct()
    client = client_for(owner)
    media_id = _upload(client, b"\xff\xd8\xff" + b"not really a jpeg" * 10)
    assert _complete(client, media_id).status_code == 200
    tasks.process_media(media_id)
    asset = MediaAsset.objects.get(id=media_id)
    assert asset.status == MediaAsset.Status.FAILED
    assert OutboxEvent.objects.filter(event_type="media.failed").exists()
    assert _detail(client, media_id).json()["data"]["url"] is None  # never served


# ---- single-use uploads, real size, ETag (1.5) -------------------------------------------


def test_the_presigned_put_targets_a_staging_key(client_for, memory_storage):
    owner = _acct()
    signed = (
        client_for(owner)
        .post(
            reverse("media_app:sign-upload"),
            {"kind": "image", "mime": "image/jpeg", "size": 10},
            format="json",
        )
        .json()["data"]
    )
    session = UploadSession.objects.get(media_id=signed["media_id"])
    assert session.staging_key == f"staging/{signed['storage_key']}"
    assert _key_of(signed["upload_url"]) == session.staging_key


def test_completion_records_the_real_size_and_etag(client_for, memory_storage):
    owner = _acct()
    client = client_for(owner)
    content = b"%PDF-1.7\n" + b"x" * 5000
    media_id = _upload(client, content, kind="file", mime="application/pdf", declared=10)

    assert _complete(client, media_id).status_code == 200

    asset = MediaAsset.objects.get(id=media_id)
    assert asset.status == MediaAsset.Status.PROCESSING
    assert asset.bytes == len(content)  # not the declared 10
    assert asset.etag == f'"{hashlib.md5(content, usedforsecurity=False).hexdigest()}"'
    assert storage.read(asset.storage_key) == content
    assert storage.stat(UploadSession.objects.get(media_id=media_id).staging_key, 8) is None
    event = OutboxEvent.objects.get(event_type="media.uploaded").payload["payload"]
    assert event["bytes"] == len(content)


def test_completing_twice_is_409(client_for, memory_storage):
    owner = _acct()
    client = client_for(owner)
    media_id = _upload(client, _jpeg_with_gps())
    assert _complete(client, media_id).status_code == 200
    again = _complete(client, media_id)
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "upload_already_completed"
    assert OutboxEvent.objects.filter(event_type="media.uploaded").count() == 1


def test_completing_twice_is_409_on_the_fake_backend_too(client_for):
    owner = _acct()
    media_id = services.sign_upload(
        owner, kind="image", mime="image/png", size=10, visibility="public"
    )["media_id"]
    assert _complete(client_for(owner), media_id).status_code == 200
    assert _complete(client_for(owner), media_id).status_code == 409


def test_only_the_owner_can_complete(client_for, memory_storage):
    media_id = _upload(client_for(_acct()), _jpeg_with_gps())
    assert _complete(client_for(_acct()), media_id).status_code == 404


def test_a_put_replayed_after_completion_does_not_change_the_object(client_for, memory_storage):
    owner = _acct()
    client = client_for(owner)
    media_id = _upload(client, _jpeg_with_gps())
    assert _complete(client, media_id).status_code == 200
    asset = MediaAsset.objects.get(id=media_id)
    verified = storage.read(asset.storage_key)

    # The presigned URL is still valid for its TTL; replay it with other bytes.
    storage.write(
        UploadSession.objects.get(media_id=media_id).staging_key, b"<html>evil", "image/jpeg"
    )

    assert storage.read(asset.storage_key) == verified
    assert _complete(client, media_id).status_code == 409  # and it cannot be re-verified
    tasks.process_media(media_id)
    assert b"evil" not in storage.read(asset.storage_key)


def test_a_renamed_exe_declared_as_mp4_is_rejected(client_for, memory_storage):
    owner = _acct()
    client = client_for(owner)
    exe = b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff\x00\x00" + b"\x00" * 64
    media_id = _upload(client, exe, kind="video", mime="video/mp4")

    resp = _complete(client, media_id)

    assert resp.status_code == 400
    asset = MediaAsset.objects.get(id=media_id)
    assert asset.status == MediaAsset.Status.FAILED
    assert storage.stat(asset.storage_key, 8) is None  # never reached the real key
    assert storage.stat(UploadSession.objects.get(media_id=media_id).staging_key, 8) is None
    assert not OutboxEvent.objects.filter(event_type="media.uploaded").exists()
    assert _complete(client, media_id).status_code == 409  # the session is used up


def test_a_real_mp4_passes(client_for, memory_storage):
    owner = _acct()
    client = client_for(owner)
    mp4 = b"\x00\x00\x00\x20ftypisom\x00\x00\x02\x00isomiso2avc1mp41" + b"\x00" * 64
    media_id = _upload(client, mp4, kind="video", mime="video/mp4")
    assert _complete(client, media_id).status_code == 200


def test_html_declared_as_webm_is_rejected(client_for, memory_storage):
    owner = _acct()
    client = client_for(owner)
    media_id = _upload(
        client, b"<!doctype html><script>alert(1)</script>", kind="video", mime="video/webm"
    )
    assert _complete(client, media_id).status_code == 400


def test_an_object_larger_than_the_limit_is_rejected_at_completion(
    client_for, memory_storage, settings
):
    settings.MAX_UPLOAD_BYTES = 1000
    owner = _acct()
    client = client_for(owner)
    media_id = _upload(
        client, b"%PDF-" + b"x" * 2000, kind="file", mime="application/pdf", declared=500
    )
    assert _complete(client, media_id).status_code == 400
    assert MediaAsset.objects.get(id=media_id).status == MediaAsset.Status.FAILED


def test_completing_without_uploading_is_rejected(client_for, memory_storage):
    owner = _acct()
    media_id = services.sign_upload(
        owner, kind="image", mime="image/png", size=10, visibility="public"
    )["media_id"]
    assert _complete(client_for(owner), media_id).status_code == 400


def test_an_object_swapped_during_verification_is_rejected(client_for, memory_storage, monkeypatch):
    owner = _acct()
    client = client_for(owner)
    media_id = _upload(client, _jpeg_with_gps())

    def swapped(*a, **k):
        raise storage.ObjectChanged("staging")

    monkeypatch.setattr(storage, "copy", swapped)
    assert _complete(client, media_id).status_code == 400
    asset = MediaAsset.objects.get(id=media_id)
    assert asset.status == MediaAsset.Status.FAILED
    assert storage.stat(asset.storage_key, 8) is None


def test_a_storage_outage_lets_the_client_retry(client_for, memory_storage, monkeypatch):
    owner = _acct()
    client = client_for(owner)
    media_id = _upload(client, _jpeg_with_gps())
    real_stat = storage.stat

    def outage(*a, **k):
        raise ConnectionError("minio down")

    monkeypatch.setattr(storage, "stat", outage)
    assert _complete(client, media_id).status_code == 503
    assert MediaAsset.objects.get(id=media_id).status == MediaAsset.Status.UPLOADING

    monkeypatch.setattr(storage, "stat", real_stat)
    assert _complete(client, media_id).status_code == 200


def test_a_session_signed_before_staging_keys_is_verified_in_place(client_for, memory_storage):
    owner = _acct()
    media_id = services.sign_upload(
        owner, kind="image", mime="image/jpeg", size=10, visibility="public"
    )["media_id"]
    UploadSession.objects.filter(media_id=media_id).update(staging_key="")
    asset = MediaAsset.objects.get(id=media_id)
    storage.write(asset.storage_key, _jpeg_with_gps(), "image/jpeg")
    assert _complete(client_for(owner), media_id).status_code == 200
    assert MediaAsset.objects.get(id=media_id).bytes == len(_jpeg_with_gps())


# ---- container signatures (1.5) ---------------------------------------------------------


@pytest.mark.parametrize(
    ("mime", "head"),
    [
        ("video/mp4", b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00"),
        ("audio/mp4", b"\x00\x00\x00\x1cftypM4A \x00\x00\x00\x00"),
        ("video/webm", b"\x1a\x45\xdf\xa3\x9f\x42\x86\x81\x01"),
        ("audio/webm;codecs=opus", b"\x1a\x45\xdf\xa3\x9f\x42\x86\x81\x01"),
        ("audio/ogg", b"OggS\x00\x02\x00\x00"),
        ("audio/mpeg", b"ID3\x04\x00\x00\x00\x00"),
        ("audio/mpeg", b"\xff\xfb\x90\x64\x00"),
        ("audio/wav", b"RIFF\x24\x08\x00\x00WAVEfmt "),
        ("image/webp", b"RIFF\x24\x08\x00\x00WEBPVP8 "),
    ],
)
def test_real_containers_pass(mime, head):
    assert matches_signature(mime, head)


@pytest.mark.parametrize(
    ("mime", "head"),
    [
        ("video/mp4", b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00"),  # a Windows .exe
        ("video/mp4", b"<!doctype html><html>"),
        ("video/mp4", b"\x1a\x45\xdf\xa3\x9f\x42\x86\x81"),  # webm declared as mp4
        ("video/webm", b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00"),
        ("audio/ogg", b"<svg onload=alert(1)>"),
        ("audio/mpeg", b"<html>"),
        ("audio/wav", b"RIFF\x24\x08\x00\x00WEBPVP8 "),
        ("video/mp4", b""),
        ("application/x-unknown", b"anything"),
    ],
)
def test_other_bytes_fail(mime, head):
    assert not matches_signature(mime, head)
