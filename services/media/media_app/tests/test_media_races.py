"""Review wave 2 in media: lifting a published draft's restriction (#4), one
prepare per video (#9), a race-safe daily quota (#10) and a binding declared
size (#11)."""

from __future__ import annotations

import threading
import time
import uuid
from datetime import timedelta

import pytest
from django.db import connection
from django.urls import reverse
from django.utils import timezone

from media_app import post_client, services, storage, transcode
from media_app.models import MediaAsset, UploadSession
from media_app.post_client import post_is_public as real_post_is_public
from tara_common.exceptions import TaraAPIError

MP4 = b"\x00\x00\x00\x20ftypisom\x00\x00\x02\x00isomiso2avc1mp41" + b"\x00" * 64


def _acct() -> str:
    return str(uuid.uuid4())


def _photo(owner: str) -> str:
    return services.sign_upload(owner, kind="image", mime="image/png", size=1, visibility="public")[
        "media_id"
    ]


# ---- #4: a draft published as public opens its media -------------------------------


@pytest.mark.django_db
def test_publishing_a_public_draft_lifts_the_restriction(post_publicity):
    owner, post_id = _acct(), _acct()
    media_id = _photo(owner)
    services.bind_to_post(owner, post_id, [media_id], restricted=True)  # the draft
    post_publicity.answers[post_id] = True  # published, public

    result = services.bind_to_post(owner, post_id, [media_id], restricted=False)

    asset = MediaAsset.objects.get(id=media_id)
    assert (asset.restricted, str(asset.post_id)) == (False, post_id)
    assert result["bound"] == [media_id]
    assert post_publicity.calls == [post_id]


@pytest.mark.django_db
@pytest.mark.parametrize("answer", [False, None])
def test_the_restriction_stays_unless_post_says_public_now(post_publicity, answer):
    """A late call for an older, wider audience, or post not answering."""
    owner, post_id = _acct(), _acct()
    media_id = _photo(owner)
    services.bind_to_post(owner, post_id, [media_id], restricted=True)
    post_publicity.answers[post_id] = answer

    services.bind_to_post(owner, post_id, [media_id], restricted=False)

    assert MediaAsset.objects.get(id=media_id).restricted is True


@pytest.mark.django_db
def test_a_tightening_saved_while_post_answers_wins(post_publicity):
    """Post said public, but the audience was narrowed (and the media
    tightened) after post was asked: the stale lift is ignored."""
    owner, post_id = _acct(), _acct()
    media_id = _photo(owner)
    services.bind_to_post(owner, post_id, [media_id], restricted=True)
    post_publicity.answers[post_id] = True

    def narrowed():
        time.sleep(0.002)
        MediaAsset.objects.filter(id=media_id).update(updated_at=timezone.now())

    post_publicity.on_call = narrowed

    services.bind_to_post(owner, post_id, [media_id], restricted=False)

    assert MediaAsset.objects.get(id=media_id).restricted is True


@pytest.mark.django_db
def test_post_is_not_asked_when_nothing_is_restricted(post_publicity):
    owner, post_id = _acct(), _acct()
    media_id = _photo(owner)
    services.bind_to_post(owner, post_id, [media_id], restricted=False)  # a public post
    services.bind_to_post(owner, post_id, [media_id], restricted=False)  # edited, still public
    assert MediaAsset.objects.get(id=media_id).restricted is False
    assert post_publicity.calls == []


@pytest.mark.django_db
def test_another_owner_cannot_lift_a_restriction(post_publicity):
    owner, post_id = _acct(), _acct()
    media_id = _photo(owner)
    services.bind_to_post(owner, post_id, [media_id], restricted=True)
    post_publicity.answers[post_id] = True
    services.bind_to_post(_acct(), post_id, [media_id], restricted=False)
    assert MediaAsset.objects.get(id=media_id).restricted is True


def test_publicity_is_asked_as_a_stranger(monkeypatch):
    asked = []
    monkeypatch.setattr(post_client, "_visible", lambda v, p: asked.append((v, p)) or True)
    assert real_post_is_public("p1") is True  # the autouse stub replaced the attribute
    assert asked == [("00000000-0000-0000-0000-000000000000", "p1")]


# ---- #9: one prepare per video -----------------------------------------------------------


def _uploaded_video(owner: str, **extra) -> MediaAsset:
    return MediaAsset.objects.create(
        owner_id=owner,
        kind="video",
        purpose="post",
        mime="video/mp4",
        storage_key=f"videos/{owner}/{uuid.uuid4()}",
        status=MediaAsset.Status.UPLOADED,
        **extra,
    )


@pytest.mark.django_db
def test_queued_duplicates_of_prepare_never_fail_a_healthy_video(settings):
    """The transcoder was down: the beat resent prepare three times behind the
    first message. The first claims the video; the resends are skipped, cost
    no try, and do not reach too_many_attempts."""
    settings.MEDIA_TRANSCODE_MAX_ATTEMPTS = 3
    asset = _uploaded_video(_acct())
    assert transcode._begin(str(asset.id), "prepare", "m1") is not None  # M1 is running

    for task_id in ("m2", "m3", "m4"):
        transcode.prepare.apply(args=[str(asset.id)], task_id=task_id)

    asset.refresh_from_db()
    assert asset.status == MediaAsset.Status.PROCESSING
    assert asset.video_meta["tries"] == {"prepare": 1}
    assert asset.video_meta["prepare_task"] == "m1"


@pytest.mark.django_db
def test_a_retry_of_the_claiming_prepare_still_runs_and_counts():
    asset = _uploaded_video(_acct())
    assert transcode._begin(str(asset.id), "prepare", "m1") is not None
    again = transcode._begin(str(asset.id), "prepare", "m1")  # task.retry / redelivery
    assert again is not None
    assert again.video_meta["tries"] == {"prepare": 2}


@pytest.mark.django_db
def test_no_prepare_runs_once_the_chain_was_started():
    asset = _uploaded_video(_acct())
    assert transcode._begin(str(asset.id), "prepare", "m1") is not None
    transcode._mark_chain_started(asset.pk)
    assert transcode._begin(str(asset.id), "prepare", "m1") is None
    asset.refresh_from_db()
    assert asset.video_meta["tries"] == {"prepare": 1}
    assert asset.video_meta["chain_started"] is True


@pytest.mark.django_db
def test_requeue_resends_once_with_an_expiry(monkeypatch):
    sent = []
    monkeypatch.setattr(
        transcode.prepare, "apply_async", lambda args=None, *rest, **kw: sent.append((args, kw))
    )
    stalled = _uploaded_video(_acct())
    fresh = _uploaded_video(_acct())
    MediaAsset.objects.filter(pk=stalled.pk).update(updated_at=timezone.now() - timedelta(hours=1))

    assert transcode.requeue_stalled_videos() == 1
    assert transcode.requeue_stalled_videos() == 0  # not again on the next run

    assert len(sent) == 1
    args, kw = sent[0]
    assert args == (str(stalled.id),)
    assert kw["expires"] <= timezone.now() + transcode.STALLED_AFTER
    stalled.refresh_from_db()
    assert stalled.status == MediaAsset.Status.UPLOADED
    assert "queued_at" in stalled.video_meta
    assert "tries" not in stalled.video_meta  # a resend costs no try
    fresh.refresh_from_db()
    assert "queued_at" not in fresh.video_meta


@pytest.mark.django_db
def test_requeue_skips_a_video_claimed_meanwhile(monkeypatch):
    sent = []
    monkeypatch.setattr(
        transcode.prepare, "apply_async", lambda args=None, *rest, **kw: sent.append(args)
    )
    asset = _uploaded_video(_acct())
    MediaAsset.objects.filter(pk=asset.pk).update(updated_at=timezone.now() - timedelta(hours=1))
    real_filter = MediaAsset.objects.filter

    def claim_then_filter(*a, **k):
        if k.get("status") == MediaAsset.Status.UPLOADED and "pk" in k:
            real_filter(pk=asset.pk).update(status=MediaAsset.Status.PROCESSING)
        return real_filter(*a, **k)

    monkeypatch.setattr(MediaAsset.objects, "filter", claim_then_filter)
    transcode.requeue_stalled_videos()
    assert sent == []


# ---- #10: the daily quota under parallel requests ----------------------------------------


@pytest.mark.django_db(transaction=True)
def test_parallel_requests_cannot_both_take_the_last_slot(settings, monkeypatch):
    """T1 has counted and not yet committed when T2 counts. Without a
    per-account lock T2 sees no row and passes too."""
    if connection.vendor != "postgresql":
        pytest.skip("needs PostgreSQL")
    settings.MEDIA_VIDEO_DAILY_UPLOADS = 1
    settings.MEDIA_VIDEO_DAILY_BYTES = 10_000
    owner = _acct()
    t1_counted = threading.Event()
    real_save = MediaAsset.save

    def slow_save(self, *a, **k):
        if threading.current_thread().name == "t1" and self.purpose and self._state.adding:
            t1_counted.set()
            time.sleep(0.8)  # T2 starts counting meanwhile
        return real_save(self, *a, **k)

    monkeypatch.setattr(MediaAsset, "save", slow_save)
    outcomes: dict[str, str] = {}

    def sign(name: str) -> None:
        try:
            services.sign_upload(
                owner, kind="video", mime="video/mp4", size=100, visibility="public",
                purpose="post",
            )  # fmt: skip
            outcomes[name] = "ok"
        except TaraAPIError as exc:
            outcomes[name] = exc.code
        finally:
            connection.close()

    t1 = threading.Thread(target=sign, args=("t1",), name="t1")
    t1.start()
    assert t1_counted.wait(10)
    t2 = threading.Thread(target=sign, args=("t2",), name="t2")
    t2.start()
    t1.join(15)
    t2.join(15)

    assert outcomes == {"t1": "ok", "t2": "video_quota_exceeded"}
    assert MediaAsset.objects.filter(owner_id=owner).count() == 1


# ---- #11: the declared size binds a transcoded video ---------------------------------------


def _signed_video(client, size: int) -> str:
    resp = client.post(
        reverse("media_app:sign-upload"),
        {"kind": "video", "mime": "video/mp4", "size": size, "purpose": "post"},
        format="json",
    )
    assert resp.status_code == 201, resp.content
    return resp.json()["data"]["media_id"]


@pytest.mark.django_db
def test_a_video_larger_than_declared_is_refused_and_deleted(client_for, memory_storage):
    """Declaring 1 byte to slip under the daily byte quota, then PUTting more."""
    owner = _acct()
    client = client_for(owner)
    media_id = _signed_video(client, 1)
    staging = UploadSession.objects.get(media_id=media_id).staging_key
    storage.write(staging, MP4, "video/mp4")

    resp = client.post(reverse("media_app:complete-upload", args=[media_id]))

    assert resp.status_code == 400
    asset = MediaAsset.objects.get(id=media_id)
    assert asset.status == MediaAsset.Status.FAILED
    assert asset.bytes == 1  # what the quota was charged
    assert storage.stat(staging, 8) is None
    assert storage.stat(asset.storage_key, 8) is None


@pytest.mark.django_db
def test_a_video_of_its_declared_size_completes(client_for, memory_storage):
    owner = _acct()
    client = client_for(owner)
    media_id = _signed_video(client, len(MP4))
    storage.write(UploadSession.objects.get(media_id=media_id).staging_key, MP4, "video/mp4")
    resp = client.post(reverse("media_app:complete-upload", args=[media_id]))
    assert resp.status_code == 200, resp.content
    assert MediaAsset.objects.get(id=media_id).status == MediaAsset.Status.UPLOADED
