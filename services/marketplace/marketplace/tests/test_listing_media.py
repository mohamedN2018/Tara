"""Listing attachments: checked with media before the listing is written.

Until the video pipeline (roadmap 5.7, decision D1) a listing takes photos
only. Media being unreachable fails the request closed.
"""

import uuid

import jwt
import pytest
from django.conf import settings
from django.urls import reverse

from marketplace import media_client, services
from marketplace.media_client import lookup as real_lookup
from marketplace.models import Listing, ListingMedia, OutboxEvent
from tara_common.exceptions import TaraAPIError

pytestmark = pytest.mark.django_db


def _acct() -> str:
    return str(uuid.uuid4())


def _create(client, category, media_ids, **headers):
    return client.post(
        reverse("marketplace:listings"),
        {
            "category_id": str(category.id),
            "title": "Bike",
            "price": "50.00",
            "media_ids": media_ids,
        },
        format="json",
        **headers,
    )


def _error(resp) -> tuple[str, str]:
    err = resp.json()["error"]
    return err["code"], err["details"][0]["code"] if err["details"] else ""


def _nothing_written():
    assert not Listing.objects.exists()
    assert not ListingMedia.objects.exists()
    assert not OutboxEvent.objects.filter(event_type="listing.created").exists()


# ---- accepted -----------------------------------------------------------------


def test_sellers_own_photos_are_attached_in_order(client_for, category, media_stub):
    seller = _acct()
    photos = [media_stub.add(seller), media_stub.add(seller, status="processing")]
    resp = _create(client_for(seller), category, photos)
    assert resp.status_code == 201
    assert [m["media_id"] for m in resp.json()["data"]["media"]] == photos
    assert media_stub.calls == [photos]  # one batch call


def test_listing_without_media_does_not_call_media(client_for, category, media_stub):
    media_stub.down = True  # a text-only listing does not depend on media
    resp = _create(client_for(_acct()), category, [])
    assert resp.status_code == 201
    assert media_stub.calls == []


# ---- video and other refusals -------------------------------------------------


def test_video_is_refused_with_400_and_nothing_is_written(client_for, category, media_stub):
    seller = _acct()
    clip = media_stub.add(seller, kind="video")
    resp = _create(client_for(seller), category, [clip])
    assert resp.status_code == 400
    assert _error(resp) == ("validation_error", "video_not_supported_yet")
    assert resp.json()["error"]["details"][0]["field"] == "media_ids"
    _nothing_written()


def test_one_video_among_photos_refuses_the_whole_listing(client_for, category, media_stub):
    seller = _acct()
    ids = [media_stub.add(seller), media_stub.add(seller, kind="video"), media_stub.add(seller)]
    resp = _create(client_for(seller), category, ids)
    assert resp.status_code == 400
    assert _error(resp) == ("validation_error", "video_not_supported_yet")
    _nothing_written()


def test_service_refuses_video_too(category, media_stub):
    seller = _acct()
    clip = media_stub.add(seller, kind="video")
    data = {"category_id": str(category.id), "title": "Bike", "price": "1", "media_ids": [clip]}
    with pytest.raises(TaraAPIError) as err:
        services.create_listing(seller, data)
    assert err.value.http_status == 400
    _nothing_written()


def test_someone_elses_media_and_an_unknown_id_look_the_same(client_for, category, media_stub):
    seller = _acct()
    theirs = media_stub.add(_acct())
    client = client_for(seller)
    not_owned = _create(client, category, [theirs])
    unknown = _create(client, category, [str(uuid.uuid4())])
    assert not_owned.status_code == unknown.status_code == 400
    assert _error(not_owned) == _error(unknown) == ("validation_error", "media_not_owned")
    assert not_owned.json()["error"]["message"] == unknown.json()["error"]["message"]
    _nothing_written()


def test_someone_elses_video_is_refused_as_not_found_not_as_video(client_for, category, media_stub):
    # Refusing it as a video would tell the seller what another account uploaded.
    theirs = media_stub.add(_acct(), kind="video")
    resp = _create(client_for(_acct()), category, [theirs])
    assert _error(resp) == ("validation_error", "media_not_owned")


@pytest.mark.parametrize("kind", ["audio", "voice", "file"])
def test_non_image_media_is_refused(client_for, category, media_stub, kind):
    seller = _acct()
    resp = _create(client_for(seller), category, [media_stub.add(seller, kind=kind)])
    assert resp.status_code == 400
    assert _error(resp) == ("validation_error", "media_kind_not_allowed")
    _nothing_written()


@pytest.mark.parametrize("status", ["uploading", "failed"])
def test_unfinished_upload_is_refused(client_for, category, media_stub, status):
    seller = _acct()
    resp = _create(client_for(seller), category, [media_stub.add(seller, status=status)])
    assert resp.status_code == 400
    assert _error(resp) == ("validation_error", "media_not_ready")
    _nothing_written()


def test_too_many_or_duplicate_media_are_refused_without_asking_media(
    client_for, category, media_stub
):
    seller = _acct()
    client = client_for(seller)
    eleven = [media_stub.add(seller) for _ in range(services.MAX_MEDIA_PER_LISTING + 1)]
    too_many = _create(client, category, eleven)
    assert too_many.status_code == 400
    assert _error(too_many) == ("validation_error", "too_many_media")
    photo = media_stub.add(seller)
    twice = _create(client, category, [photo, photo])
    assert twice.status_code == 400
    assert _error(twice) == ("validation_error", "duplicate_media")
    assert media_stub.calls == []
    _nothing_written()


# ---- media down ---------------------------------------------------------------


def test_media_down_fails_closed_with_503(client_for, category, media_stub):
    seller = _acct()
    photo = media_stub.add(seller)
    media_stub.down = True
    resp = _create(client_for(seller), category, [photo])
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "dependency_unavailable"
    _nothing_written()


def test_503_releases_the_idempotency_key_so_a_retry_succeeds(client_for, category, media_stub):
    seller = _acct()
    photo = media_stub.add(seller)
    client = client_for(seller)
    media_stub.down = True
    assert _create(client, category, [photo], HTTP_IDEMPOTENCY_KEY="k1").status_code == 503
    media_stub.down = False
    retry = _create(client, category, [photo], HTTP_IDEMPOTENCY_KEY="k1")
    assert retry.status_code == 201
    assert Listing.objects.count() == 1


def test_editing_a_listing_runs_the_same_media_check(client_for, category, media_stub):
    # Editing the photos is no way around the check: a video is refused as on create.
    seller = _acct()
    client = client_for(seller)
    listing_id = _create(client, category, []).json()["data"]["id"]
    clip = media_stub.add(seller, kind="video")
    resp = client.patch(
        reverse("marketplace:listing-detail", args=[listing_id]),
        {"title": "New", "media_ids": [clip]},
        format="json",
    )
    assert resp.status_code == 400
    assert _error(resp) == ("validation_error", "video_not_supported_yet")
    assert not ListingMedia.objects.exists()
    assert Listing.objects.get(id=listing_id).title == "Bike"


# ---- the media client itself --------------------------------------------------


class _Resp:
    def __init__(self, body, status=200):
        self._body, self.status_code = body, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)

    def json(self):
        return self._body


def test_client_asks_the_internal_batch_endpoint_with_a_short_lived_token(monkeypatch):
    owner, photo = _acct(), _acct()
    sent = []

    def fake_post(url, json, headers, timeout):
        sent.append((url, json, headers, timeout))
        return _Resp(
            {"data": [{"id": photo, "owner_id": owner, "kind": "image", "status": "ready"}]}
        )

    monkeypatch.setattr("marketplace.media_client.requests.post", fake_post)
    info = real_lookup([photo])[photo]
    assert (info.owner_id, info.kind, info.status) == (owner, "image", "ready")

    url, body, headers, timeout = sent[0]
    assert url == f"{settings.MEDIA_INTERNAL_URL}/internal/v1/media/batch/"
    assert body == {"ids": [photo]}
    assert timeout == settings.MEDIA_CALL_TIMEOUT
    token = jwt.decode(
        headers["Authorization"].removeprefix("Bearer "),
        settings.TARA_INTERNAL_JWT_SECRET,
        algorithms=["HS256"],
        audience="media-internal",
    )
    assert token["iss"] == "marketplace"
    assert token["exp"] - token["iat"] <= 30


@pytest.mark.parametrize(
    "answer",
    [
        _Resp({"error": {"code": "unauthenticated"}}, status=401),
        _Resp({"data": [{"id": "x"}]}),  # a row without owner or kind
        _Resp({"unexpected": True}),
    ],
)
def test_client_fails_closed_on_errors_and_malformed_answers(monkeypatch, answer):
    monkeypatch.setattr("marketplace.media_client.requests.post", lambda *a, **k: answer)
    with pytest.raises(TaraAPIError) as err:
        real_lookup([_acct()])
    assert err.value.http_status == 503
    assert err.value.code == "dependency_unavailable"


def test_client_opens_the_circuit_after_repeated_failures(monkeypatch):
    calls = []

    def broken(*a, **k):
        calls.append(1)
        raise ConnectionError("media down")

    monkeypatch.setattr("marketplace.media_client.requests.post", broken)
    for _ in range(6):
        with pytest.raises(TaraAPIError) as err:
            real_lookup([_acct()])
        assert err.value.http_status == 503
    assert len(calls) == media_client._breaker.failure_threshold  # the sixth never left
