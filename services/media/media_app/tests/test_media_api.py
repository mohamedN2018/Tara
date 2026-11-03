"""Media API: signed upload -> complete -> process -> ready, + access control."""

import time
import uuid

import jwt
import pytest
from django.conf import settings
from django.urls import reverse

from media_app import services, tasks
from media_app.models import MediaAsset, OutboxEvent

pytestmark = pytest.mark.django_db


def _acct() -> str:
    return str(uuid.uuid4())


def test_sign_complete_process_flow(client_for):
    owner = _acct()
    client = client_for(owner)

    sign = client.post(
        reverse("media_app:sign-upload"),
        {"kind": "image", "mime": "image/jpeg", "size": 1024, "visibility": "public"},
        format="json",
    )
    assert sign.status_code == 201
    media_id = sign.json()["data"]["media_id"]
    assert "upload_url" in sign.json()["data"]

    complete = client.post(reverse("media_app:complete-upload", args=[media_id]))
    assert complete.status_code == 200
    assert MediaAsset.objects.get(id=media_id).status == MediaAsset.Status.PROCESSING
    assert OutboxEvent.objects.filter(event_type="media.uploaded").exists()

    # Run the (placeholder) processing task directly (on_commit doesn't fire in tests).
    tasks.process_media(media_id)
    asset = MediaAsset.objects.get(id=media_id)
    assert asset.status == MediaAsset.Status.READY
    assert asset.variants.filter(kind="thumb").exists()
    assert OutboxEvent.objects.filter(event_type="media.processed").exists()


def test_size_limit_rejected(client_for):
    resp = client_for(_acct()).post(
        reverse("media_app:sign-upload"),
        {"kind": "image", "mime": "image/jpeg", "size": settings.MAX_UPLOAD_BYTES + 1},
        format="json",
    )
    assert resp.status_code == 400


def test_private_media_hidden_from_non_owner(client_for):
    owner = _acct()
    result = services.sign_upload(
        owner, kind="file", mime="application/pdf", size=10, visibility="private"
    )
    media_id = result["media_id"]

    # Owner can see it; a stranger gets 404 (no existence disclosure).
    assert (
        client_for(owner).get(reverse("media_app:media-detail", args=[media_id])).status_code == 200
    )
    assert (
        client_for(_acct()).get(reverse("media_app:media-detail", args=[media_id])).status_code
        == 404
    )


def test_download_url_requires_ready(client_for):
    owner = _acct()
    media_id = services.sign_upload(
        owner, kind="image", mime="image/png", size=10, visibility="public"
    )["media_id"]
    # Not ready yet -> 409.
    assert (
        client_for(owner).get(reverse("media_app:download-url", args=[media_id])).status_code == 409
    )


def test_internal_media_requires_token(client_for):
    owner = _acct()
    media_id = services.sign_upload(
        owner, kind="image", mime="image/png", size=10, visibility="public"
    )["media_id"]
    from rest_framework.test import APIClient

    anon = APIClient()
    url = reverse("internal-media", args=[media_id])
    assert anon.get(url).status_code == 401

    now = int(time.time())
    token = jwt.encode(
        {"iss": "post", "aud": "media-internal", "iat": now, "exp": now + 30},
        settings.TARA_INTERNAL_JWT_SECRET,
        algorithm="HS256",
    )
    anon.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    ok = anon.get(url)
    assert ok.status_code == 200
    assert ok.json()["data"]["owner_id"] == owner


# ---- upload validation -------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "mime"),
    [("image", "text/html"), ("image", "image/svg+xml"), ("file", "application/x-msdownload")],
)
def test_unsafe_types_are_refused(kind, mime):
    from media_app import services
    from tara_common.exceptions import TaraAPIError

    with pytest.raises(TaraAPIError):
        services.sign_upload(
            "01a19eed-9326-7fd4-a005-3fb0712a234c",
            kind=kind,
            mime=mime,
            size=10,
            visibility="public",
        )


def test_signature_check_rejects_html_named_png():
    from media_app.validation import matches_signature

    assert not matches_signature("image/png", b"<html><script>")
    assert matches_signature("image/png", b"\x89PNG\r\n\x1a\n....")
    assert matches_signature("audio/webm; codecs=opus", b"anything")


def test_thumbnail_is_a_small_jpeg():
    import io

    from PIL import Image

    from media_app.tasks import _thumbnail

    source = io.BytesIO()
    Image.new("RGB", (1000, 500), "red").save(source, "PNG")
    thumb = Image.open(io.BytesIO(_thumbnail(source.getvalue())))
    assert thumb.format == "JPEG"
    assert max(thumb.size) == 320
