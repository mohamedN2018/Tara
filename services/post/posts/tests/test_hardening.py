"""Milestones 1.1, 1.2 and 1.5 in post: safe edits, reports, video gate, media binding,
and the internal visibility endpoint that media uses for restricted media."""

import time
import uuid

import jwt
import pytest
from django.conf import settings
from django.core.management import call_command
from django.urls import reverse
from rest_framework.test import APIClient

from posts import media_client, services
from posts.clients import Relationship
from posts.media_client import bind as real_bind
from posts.media_client import lookup as real_lookup
from posts.models import BlockedPair, OutboxEvent, Post, PostReport

pytestmark = pytest.mark.django_db


def _acct() -> str:
    return str(uuid.uuid4())


def _rel(**kw):
    return lambda a, b: Relationship(**kw)


def _outbox(event_type: str) -> int:
    return OutboxEvent.objects.filter(event_type=event_type).count()


def _patch(client, post_id, **data):
    return client.patch(reverse("posts:post-detail", args=[post_id]), data, format="json")


def _create(client, **data):
    return client.post(reverse("posts:post-create"), data, format="json")


def _report(client, post_id, reason="spam"):
    return client.post(
        reverse("posts:post-report", args=[post_id]), {"reason": reason}, format="json"
    )


def _error_code(resp) -> str:
    return resp.json()["error"]["code"]


# ---- edit_post refuses moderated posts (1.1) ------------------------------------


def test_patch_on_a_moderator_removed_post_is_404_and_writes_no_update(client_for):
    author = _acct()
    post = services.create_post(author, body="bad", audience="public")
    services.apply_moderation(str(post.id), "remove")

    resp = _patch(client_for(author), post.id, body="sneaky rewrite")

    assert resp.status_code == 404
    assert _outbox("post.updated") == 0
    post.refresh_from_db()
    assert post.body == "bad"


def test_patch_on_a_post_pending_review_is_404(client_for):
    author = _acct()
    post = services.create_post(author, body="under review", audience="public")
    Post.objects.filter(id=post.id).update(moderation_status=Post.ModerationStatus.PENDING)

    assert _patch(client_for(author), post.id, body="changed").status_code == 404
    assert _patch(client_for(author), post.id, audience="friends").status_code == 404
    assert _outbox("post.updated") == 0


def test_patch_on_someone_elses_post_is_404(client_for):
    post = services.create_post(_acct(), body="mine", audience="public")
    assert _patch(client_for(_acct()), post.id, body="yours now").status_code == 404
    assert _outbox("post.updated") == 0


def test_patch_on_a_live_post_still_edits_and_emits(client_for):
    author = _acct()
    post = services.create_post(author, body="v1", audience="public")
    resp = _patch(client_for(author), post.id, body="v2 #fresh")
    assert resp.status_code == 200
    assert resp.json()["data"]["body"] == "v2 #fresh"
    assert _outbox("post.updated") == 1


def test_a_removal_that_lands_during_the_edit_wins(client_for, media_stub, monkeypatch):
    """The post is re-read under a lock after the media call."""
    author = _acct()
    post = services.create_post(author, body="p", media_ids=[media_stub.add(author)])

    def bind_then_moderator_removes(*args, **kwargs):
        Post.objects.filter(id=post.id).update(moderation_status=Post.ModerationStatus.REMOVED)
        return media_stub.bind(*args, **kwargs)

    monkeypatch.setattr(media_client, "bind", bind_then_moderator_removes)

    assert _patch(client_for(author), post.id, audience="friends").status_code == 404
    assert _outbox("post.updated") == 0
    post.refresh_from_db()
    assert post.audience == "public"


def test_patch_needs_body_or_audience(client_for):
    author = _acct()
    post = services.create_post(author, body="p")
    assert _patch(client_for(author), post.id).status_code == 400


# ---- audience edits restrict media first (1.5) -------------------------------------


def test_narrowing_the_audience_restricts_media_before_the_post_changes(
    client_for, media_stub, monkeypatch
):
    author = _acct()
    photo = media_stub.add(author)
    post = services.create_post(author, body="p", audience="public", media_ids=[photo])
    seen_audience = []

    def bind(*args, **kwargs):
        seen_audience.append(Post.objects.get(id=post.id).audience)
        return media_stub.bind(*args, **kwargs)

    monkeypatch.setattr(media_client, "bind", bind)

    resp = _patch(client_for(author), post.id, audience="friends")

    assert resp.status_code == 200
    assert seen_audience == ["public"]  # media restricted while the post was still public
    assert media_stub.binds[-1] == {
        "owner_id": author,
        "post_id": str(post.id),
        "ids": [photo],
        "restricted": True,
    }
    event = OutboxEvent.objects.get(event_type="post.updated").payload["payload"]
    assert event["audience"] == "friends"
    assert Post.objects.get(id=post.id).audience == "friends"


def test_widening_the_audience_needs_no_media_change(client_for, media_stub):
    author = _acct()
    post = services.create_post(
        author, body="p", audience="friends", media_ids=[media_stub.add(author)]
    )
    binds_before = len(media_stub.binds)

    assert _patch(client_for(author), post.id, audience="public").status_code == 200
    assert len(media_stub.binds) == binds_before
    assert Post.objects.get(id=post.id).audience == "public"


def test_a_non_public_audience_is_rebound_even_if_unchanged(client_for, media_stub):
    """A concurrent edit may have widened the post since it was read."""
    author = _acct()
    photo = media_stub.add(author)
    post = services.create_post(author, body="p", audience="friends", media_ids=[photo])
    media_stub.binds.clear()

    assert _patch(client_for(author), post.id, audience="friends").status_code == 200
    assert media_stub.binds == [
        {"owner_id": author, "post_id": str(post.id), "ids": [photo], "restricted": True}
    ]
    # A body-only edit leaves media alone.
    assert _patch(client_for(author), post.id, body="new words").status_code == 200
    assert len(media_stub.binds) == 1


def test_an_idempotent_retry_creates_one_post_and_binds_once(client_for, media_stub):
    author = _acct()
    photo = media_stub.add(author)
    client = client_for(author)
    body = {"body": "x", "audience": "friends", "media_ids": [photo]}
    url = reverse("posts:post-create")
    first = client.post(url, body, format="json", HTTP_IDEMPOTENCY_KEY="k1")
    second = client.post(url, body, format="json", HTTP_IDEMPOTENCY_KEY="k1")
    assert (first.status_code, second.status_code) == (201, 201)
    assert first.json()["data"]["id"] == second.json()["data"]["id"]
    assert Post.objects.count() == 1
    assert len(media_stub.binds) == 1


def test_narrowing_fails_closed_when_media_is_down(client_for, media_stub):
    author = _acct()
    post = services.create_post(
        author, body="p", audience="public", media_ids=[media_stub.add(author)]
    )
    media_stub.down = True

    resp = _patch(client_for(author), post.id, audience="only_me")

    assert resp.status_code == 503
    assert Post.objects.get(id=post.id).audience == "public"
    assert _outbox("post.updated") == 0


def test_a_text_post_changes_audience_without_calling_media(client_for, media_stub):
    author = _acct()
    post = services.create_post(author, body="p", audience="public")
    media_stub.down = True
    assert _patch(client_for(author), post.id, audience="only_me").status_code == 200


def test_a_share_cannot_be_widened_past_its_original(client_for):
    author = _acct()
    original = services.create_post(author, body="o", audience="friends")
    share = services.share(author, str(original.id), audience="only_me")
    client = client_for(author)
    assert _patch(client, share.id, audience="public").status_code == 400
    assert Post.objects.get(id=share.id).audience == "only_me"
    assert _patch(client, share.id, audience="friends").status_code == 200


# ---- reports (1.1, 1.2) ------------------------------------------------------------


def test_reporting_a_post_you_cannot_see_is_404_and_writes_nothing(client_for, monkeypatch):
    post = services.create_post(_acct(), body="friends only", audience="friends")
    monkeypatch.setattr("posts.services.get_relationship", _rel(are_friends=False))

    assert _report(client_for(_acct()), post.id).status_code == 404
    assert PostReport.objects.count() == 0
    assert _outbox("post.reported") == 0


def test_a_blocked_viewer_cannot_report(client_for):
    author, viewer = _acct(), _acct()
    post = services.create_post(author, body="public", audience="public")
    BlockedPair.objects.create(blocker_id=author, blocked_id=viewer)
    assert _report(client_for(viewer), post.id).status_code == 404
    assert _outbox("post.reported") == 0


def test_reporting_a_removed_or_unknown_post_is_404(client_for):
    post = services.create_post(_acct(), body="bad", audience="public")
    services.apply_moderation(str(post.id), "remove")
    assert _report(client_for(_acct()), post.id).status_code == 404
    assert _report(client_for(_acct()), uuid.uuid4()).status_code == 404
    assert _outbox("post.reported") == 0


def test_repeat_reports_are_deduped_and_carry_the_owner(client_for):
    author, reporter = _acct(), _acct()
    post = services.create_post(author, body="spam", audience="public")
    client = client_for(reporter)

    assert _report(client, post.id, "spam").status_code == 202
    assert _report(client, post.id, "still spam").status_code == 202

    assert PostReport.objects.filter(post=post, reporter_id=reporter).count() == 1
    events = OutboxEvent.objects.filter(event_type="post.reported")
    assert events.count() == 1
    payload = events.get().payload["payload"]
    assert payload == {
        "post_id": str(post.id),
        "reporter": reporter,
        "reason": "spam",
        "owner_id": author,
    }


def test_two_reporters_make_two_reports(client_for):
    post = services.create_post(_acct(), body="spam", audience="public")
    _report(client_for(_acct()), post.id)
    _report(client_for(_acct()), post.id)
    assert PostReport.objects.filter(post=post).count() == 2
    assert _outbox("post.reported") == 2


def test_a_friend_can_report_a_friends_only_post(client_for, monkeypatch):
    post = services.create_post(_acct(), body="f", audience="friends")
    monkeypatch.setattr("posts.services.get_relationship", _rel(are_friends=True))
    assert _report(client_for(_acct()), post.id).status_code == 202


# ---- video gate and attachment checks (1.5) ------------------------------------------


def test_video_posts_are_refused_until_the_video_pipeline(client_for):
    resp = _create(client_for(_acct()), body="watch", type="video")
    assert resp.status_code == 400
    assert _error_code(resp) == "video_not_supported_yet"
    assert Post.objects.count() == 0
    assert _outbox("post.created") == 0


def test_a_video_media_is_refused_and_never_bound(client_for, media_stub):
    author = _acct()
    clip = media_stub.add(author, kind="video")
    resp = _create(client_for(author), body="clip", type="image", media_ids=[clip])
    assert resp.status_code == 400
    assert _error_code(resp) == "video_not_supported_yet"
    assert media_stub.binds == []
    assert Post.objects.count() == 0


@pytest.mark.parametrize("owner", ["someone else", "nobody"])
def test_media_you_do_not_own_is_refused(client_for, media_stub, owner):
    author = _acct()
    media_id = media_stub.add(_acct()) if owner == "someone else" else _acct()
    resp = _create(client_for(author), body="x", media_ids=[media_id])
    assert resp.status_code == 400
    assert _error_code(resp) == "media_not_owned"
    assert media_stub.binds == []


@pytest.mark.parametrize(
    ("kind", "status", "code"),
    [
        ("audio", "ready", "media_kind_not_allowed"),
        ("file", "ready", "media_kind_not_allowed"),
        ("image", "uploading", "media_not_ready"),
        ("image", "failed", "media_not_ready"),
    ],
)
def test_attachments_must_be_uploaded_images(client_for, media_stub, kind, status, code):
    author = _acct()
    resp = _create(
        client_for(author), body="x", media_ids=[media_stub.add(author, kind=kind, status=status)]
    )
    assert resp.status_code == 400
    assert _error_code(resp) == code


def test_a_still_processing_image_can_be_attached(client_for, media_stub):
    author = _acct()
    photo = media_stub.add(author, status="processing")
    assert _create(client_for(author), body="x", media_ids=[photo]).status_code == 201


def test_media_count_is_capped_and_duplicates_refused(client_for, media_stub):
    author = _acct()
    eleven = [media_stub.add(author) for _ in range(11)]
    assert _create(client_for(author), body="x", media_ids=eleven).status_code == 400
    one = media_stub.add(author)
    assert _create(client_for(author), body="x", media_ids=[one, one]).status_code == 400
    assert Post.objects.count() == 0


@pytest.mark.parametrize(
    ("audience", "restricted"),
    [("public", False), ("friends", True), ("followers", True), ("only_me", True)],
)
def test_media_are_bound_to_the_post_before_it_is_written(
    client_for, media_stub, audience, restricted
):
    author = _acct()
    photo = media_stub.add(author)
    resp = _create(client_for(author), body="x", audience=audience, media_ids=[photo])
    assert resp.status_code == 201
    post_id = resp.json()["data"]["id"]
    assert media_stub.calls == ["lookup", "bind"]
    assert media_stub.binds == [
        {"owner_id": author, "post_id": post_id, "ids": [photo], "restricted": restricted}
    ]


def test_media_outage_fails_the_post_closed(client_for, media_stub):
    author = _acct()
    photo = media_stub.add(author)
    media_stub.down = True
    resp = _create(client_for(author), body="x", audience="friends", media_ids=[photo])
    assert resp.status_code == 503
    assert Post.objects.count() == 0
    assert _outbox("post.created") == 0


def test_a_text_post_does_not_need_media(client_for, media_stub):
    media_stub.down = True
    assert _create(client_for(_acct()), body="just text").status_code == 201
    assert media_stub.calls == []


def test_a_media_belongs_to_one_live_post(client_for, media_stub):
    author = _acct()
    photo = media_stub.add(author)
    client = client_for(author)
    first = _create(client, body="a", audience="friends", media_ids=[photo]).json()["data"]

    again = _create(client, body="b", audience="public", media_ids=[photo])
    assert again.status_code == 400
    assert _error_code(again) == "media_already_attached"

    services.delete_post(author, first["id"])
    assert _create(client, body="b", audience="public", media_ids=[photo]).status_code == 201


def test_media_that_changed_hands_after_the_lookup_is_refused(client_for, media_stub, monkeypatch):
    author = _acct()
    photo = media_stub.add(author)
    skipped = media_client.BindResult(skipped=[photo], attached_elsewhere=[])
    monkeypatch.setattr(media_client, "bind", lambda *a, **k: skipped)  # media skipped it
    resp = _create(client_for(author), body="x", media_ids=[photo])
    assert resp.status_code == 400
    assert _error_code(resp) == "media_not_owned"
    assert Post.objects.count() == 0


# ---- the internal visibility endpoint (media asks it for restricted media) ----------


def _internal(audience="post-internal") -> APIClient:
    now = int(time.time())
    token = jwt.encode(
        {"iss": "media", "aud": audience, "iat": now, "exp": now + 30},
        settings.TARA_INTERNAL_JWT_SECRET,
        algorithm="HS256",
    )
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


def _visible(post_id, viewer, client=None) -> bool:
    resp = (client or _internal()).get(
        reverse("internal-post-visibility", args=[post_id]), {"viewer_id": viewer}
    )
    assert resp.status_code == 200
    return resp.json()["data"]["visible"]


def test_visibility_endpoint_needs_an_internal_token(client_for):
    post = services.create_post(_acct(), body="p", audience="public")
    url = reverse("internal-post-visibility", args=[post.id])
    assert APIClient().get(url, {"viewer_id": _acct()}).status_code == 401
    assert _internal("media-internal").get(url, {"viewer_id": _acct()}).status_code == 401
    # A user token is not an internal token.
    assert client_for(_acct()).get(url, {"viewer_id": _acct()}).status_code == 401
    assert _internal().get(url, {"viewer_id": "not-a-uuid"}).status_code == 400


def test_visibility_matrix_for_a_friends_only_post(monkeypatch):
    author, friend, stranger, blocked, ex_friend = (_acct() for _ in range(5))
    post = services.create_post(author, body="friends only", audience="friends")
    friends_now = {friend, blocked}  # graph still says friends; the block wins
    monkeypatch.setattr(
        "posts.services.get_relationship",
        lambda a, b: Relationship(are_friends=a in friends_now),
    )
    BlockedPair.objects.create(blocker_id=author, blocked_id=blocked)

    assert _visible(post.id, author) is True
    assert _visible(post.id, friend) is True
    assert _visible(post.id, stranger) is False
    assert _visible(post.id, blocked) is False
    assert _visible(post.id, ex_friend) is False  # after the unfriend graph says no


def test_visibility_fails_closed_when_graph_is_down(monkeypatch):
    post = services.create_post(_acct(), body="f", audience="friends")
    monkeypatch.setattr("posts.services.get_relationship", lambda a, b: Relationship.unknown())
    assert _visible(post.id, _acct()) is False


def test_removed_deleted_and_unknown_posts_are_not_visible():
    author = _acct()
    removed = services.create_post(author, body="r", audience="public")
    services.apply_moderation(str(removed.id), "remove")
    deleted = services.create_post(author, body="d", audience="public")
    services.delete_post(author, str(deleted.id))
    public = services.create_post(author, body="p", audience="public")

    assert _visible(removed.id, _acct()) is False
    assert _visible(deleted.id, _acct()) is False
    assert _visible(uuid.uuid4(), _acct()) is False
    assert _visible(public.id, _acct()) is True


# ---- the media client itself --------------------------------------------------------


class _Resp:
    def __init__(self, data, status=200):
        self._data, self.status_code = data, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)

    def json(self):
        return {"data": self._data}


def test_client_lookup_and_bind_parse_media_responses(monkeypatch):
    sent = []
    owner, photo = _acct(), _acct()

    def fake_post(url, json, headers, timeout):
        sent.append((url, json))
        if url.endswith("/media/batch/"):
            return _Resp([{"id": photo, "owner_id": owner, "kind": "image", "status": "ready"}])
        return _Resp(
            {
                "bound": json["media_ids"][:1],
                "skipped": json["media_ids"][1:],
                "attached_elsewhere": json["media_ids"][1:2],
            }
        )

    monkeypatch.setattr("posts.media_client.requests.post", fake_post)

    info = real_lookup([photo])[photo]
    assert (info.owner_id, info.kind, info.status) == (owner, "image", "ready")
    many = [_acct() for _ in range(25)]
    result = real_bind(owner, _acct(), many, restricted=True)
    binds = [body for url, body in sent if url.endswith("/media/bind/")]
    assert [len(b["media_ids"]) for b in binds] == [20, 5]  # chunked to media's limit
    assert all(b["restricted"] is True for b in binds)
    assert result.skipped == many[1:20] + many[21:]
    assert result.attached_elsewhere == [many[1], many[21]]
    token = jwt.decode(
        media_client._internal_token(),
        settings.TARA_INTERNAL_JWT_SECRET,
        algorithms=["HS256"],
        audience="media-internal",
    )
    assert token["iss"] == "post"


def test_client_raises_503_on_errors_and_open_circuit(monkeypatch):
    def broken(*a, **k):
        raise ConnectionError("media down")

    monkeypatch.setattr("posts.media_client.requests.post", broken)
    for _ in range(6):  # the sixth call meets an open circuit
        with pytest.raises(services.TaraAPIError) as err:
            real_lookup([_acct()])
        assert err.value.http_status == 503


# ---- backfill command ------------------------------------------------------------------


def test_restrict_post_media_backfills_non_public_posts(media_stub):
    author = _acct()
    friends = services.create_post(
        author, body="f", audience="friends", media_ids=[media_stub.add(author)]
    )
    gone = services.create_post(
        author, body="g", audience="only_me", media_ids=[media_stub.add(author)]
    )
    services.delete_post(author, str(gone.id))
    services.create_post(author, body="p", audience="public", media_ids=[media_stub.add(author)])
    services.create_post(author, body="text only", audience="friends")
    media_stub.binds.clear()

    call_command("restrict_post_media", "--dry-run")
    assert media_stub.binds == []

    call_command("restrict_post_media", "--batch", "1")
    assert {b["post_id"] for b in media_stub.binds} == {str(friends.id), str(gone.id)}
    assert all(b["restricted"] for b in media_stub.binds)


def test_restrict_post_media_keeps_going_when_media_is_down(media_stub, capsys):
    author = _acct()
    services.create_post(author, body="f", audience="friends", media_ids=[media_stub.add(author)])
    media_stub.down = True
    call_command("restrict_post_media")
    assert "1 failed" in capsys.readouterr().out
