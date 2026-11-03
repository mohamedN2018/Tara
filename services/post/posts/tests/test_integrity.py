"""Review fixes: events that keep read models whole, counters under moderation,
saved collections, bad input and report throttling."""

import uuid

import pytest
from django.urls import reverse

from posts import services
from posts.models import Comment, OutboxEvent, Post, SavedCollection, SavedItem

pytestmark = pytest.mark.django_db


def _acct() -> str:
    return str(uuid.uuid4())


def _payloads(event_type: str) -> list[dict]:
    rows = OutboxEvent.objects.filter(event_type=event_type).order_by("created_at")
    return [r.payload["payload"] for r in rows]


# ---- post.updated carries what search needs -------------------------------------


def test_post_updated_carries_tags_beyond_the_excerpt():
    author = _acct()
    post = services.create_post(author, body="x" * 300 + " #late #early")
    services.edit_post(author, str(post.id), comment_policy="off")
    (payload,) = _payloads("post.updated")
    # The excerpt stops at 280 characters, so search could not find #late in it.
    assert "#late" not in payload["excerpt"]
    assert payload["hashtags"] == ["early", "late"]


def test_approving_a_removed_post_emits_post_updated_so_search_reindexes():
    author = _acct()
    post = services.create_post(author, body="fine after all #tag")
    services.apply_moderation(str(post.id), "remove")
    services.apply_moderation(str(post.id), "remove")  # redelivered by another case
    assert len(_payloads("post.deleted")) == 1

    services.apply_moderation(str(post.id), "approve")
    services.apply_moderation(str(post.id), "approve")
    (payload,) = _payloads("post.updated")
    assert payload["audience"] == "public"
    assert payload["hashtags"] == ["tag"]
    assert payload["new_mentions"] == []
    assert Post.objects.get(id=post.id).moderation_status == Post.ModerationStatus.OK


def test_approving_a_removed_post_that_was_deleted_emits_nothing():
    author = _acct()
    post = services.create_post(author, body="gone")
    services.apply_moderation(str(post.id), "remove")
    services.delete_post(author, str(post.id))
    services.apply_moderation(str(post.id), "approve")
    assert _payloads("post.updated") == []


# ---- comment counters across moderation -----------------------------------------


def _thread():
    author, a, b = _acct(), _acct(), _acct()
    post = services.create_post(author, body="p")
    root = services.add_comment(a, str(post.id), "root")
    reply = services.add_comment(b, str(post.id), "reply", str(root.id))
    return post, root, reply


def test_a_reply_approved_after_its_root_was_deleted_stays_hidden_and_uncounted():
    post, root, reply = _thread()
    services.apply_comment_moderation(str(reply.id), "remove")
    services.delete_comment(str(root.author_id), str(root.id))
    assert Post.objects.get(id=post.id).comment_count == 0

    services.apply_comment_moderation(str(reply.id), "approve")
    assert Post.objects.get(id=post.id).comment_count == 0
    assert Comment.objects.get(id=reply.id).deleted_at is not None


def test_a_reply_approved_under_a_removed_root_comes_back_with_the_root():
    post, root, reply = _thread()
    services.apply_comment_moderation(str(reply.id), "remove")
    services.apply_comment_moderation(str(root.id), "remove")
    assert Post.objects.get(id=post.id).comment_count == 0

    services.apply_comment_moderation(str(reply.id), "approve")
    # Its thread is still hidden, so it is neither shown nor counted yet.
    assert Post.objects.get(id=post.id).comment_count == 0
    assert Comment.objects.get(id=reply.id).deleted_at is not None

    services.apply_comment_moderation(str(root.id), "approve")
    assert Post.objects.get(id=post.id).comment_count == 2
    assert Comment.objects.get(id=root.id).reply_count == 1
    assert Comment.objects.get(id=reply.id).deleted_at is None


# ---- saved ---------------------------------------------------------------------


def test_saving_works_with_two_default_collections(client_for):
    # Two first saves at once could each create a default collection.
    owner = _acct()
    first = SavedCollection.objects.create(owner_id=owner, is_default=True)
    SavedCollection.objects.create(owner_id=owner, is_default=True)
    post = services.create_post(_acct(), body="p")
    resp = client_for(owner).post(reverse("posts:post-save", args=[post.id]))
    assert resp.status_code == 200
    assert SavedItem.objects.get(owner_id=owner).collection_id == first.id


# ---- bad input -----------------------------------------------------------------


def test_a_malformed_author_id_is_400_not_500(client_for):
    resp = client_for(_acct()).get(reverse("posts:post-create"), {"author_id": "not-a-uuid"})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "validation_error"


# ---- report throttle -----------------------------------------------------------


def test_post_and_comment_reports_share_one_throttle(client_for, settings):
    settings.POST_REPORT_RATE = "2/min"
    reporter = client_for(_acct())
    author = _acct()
    posts = [services.create_post(author, body=f"p{i}") for i in range(2)]
    comment = services.add_comment(author, str(posts[0].id), "c")
    for post in posts:
        resp = reporter.post(
            reverse("posts:post-report", args=[post.id]), {"reason": "spam"}, format="json"
        )
        assert resp.status_code == 202
    # Another account has its own bucket.
    resp = client_for(_acct()).post(
        reverse("posts:comment-report", args=[comment.id]), {"reason": "spam"}, format="json"
    )
    assert resp.status_code == 202
    resp = reporter.post(
        reverse("posts:comment-report", args=[comment.id]), {"reason": "spam"}, format="json"
    )
    assert resp.status_code == 429
    assert resp.json()["error"]["code"] == "throttled"


# ---- media of hidden posts, and media another post holds ------------------------


def _deleted_event(post_id: str):
    from tara_events.envelope import EventEnvelope

    return EventEnvelope(
        event_type="post.deleted",
        subject_id=post_id,
        producer="post-service",
        payload={"post_id": post_id},
    )


@pytest.mark.parametrize("how", ["deleted", "removed"])
def test_hiding_a_public_post_restricts_its_media_after_the_commit(media_stub, how):
    from posts import handlers

    author = _acct()
    photo = media_stub.add(author)
    post = services.create_post(author, body="p", audience="public", media_ids=[photo])
    assert media_stub.binds[-1]["restricted"] is False
    media_stub.binds.clear()
    if how == "deleted":
        services.delete_post(author, str(post.id))
    else:
        services.apply_moderation(str(post.id), "remove")
    assert media_stub.binds == []  # nothing remote inside the delete itself

    handlers.on_post_deleted_restrict_media(_deleted_event(str(post.id)))
    assert media_stub.binds == [
        {"owner_id": author, "post_id": str(post.id), "ids": [photo], "restricted": True}
    ]


def test_restricting_media_waits_for_media_and_skips_a_post_shown_again(media_stub):
    from posts import handlers
    from tara_common.exceptions import TaraAPIError

    author = _acct()
    post = services.create_post(author, body="p", media_ids=[media_stub.add(author)])
    services.apply_moderation(str(post.id), "remove")
    media_stub.down = True
    with pytest.raises(TaraAPIError):  # the consumer retries the event
        handlers.on_post_deleted_restrict_media(_deleted_event(str(post.id)))

    media_stub.down = False
    services.apply_moderation(str(post.id), "approve")
    media_stub.binds.clear()
    handlers.on_post_deleted_restrict_media(_deleted_event(str(post.id)))  # a late retry
    assert media_stub.binds == []


def test_media_another_post_holds_is_400_media_already_attached(client_for, media_stub):
    author = _acct()
    photo = media_stub.add(author)
    media_stub.elsewhere.add(photo)
    resp = client_for(author).post(
        reverse("posts:post-create"), {"body": "x", "media_ids": [photo]}, format="json"
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "media_already_attached"
    assert Post.objects.count() == 0


def test_narrowing_a_post_whose_media_another_post_holds_is_400(client_for, media_stub):
    author = _acct()
    photo = media_stub.add(author)
    post = services.create_post(author, body="x", audience="public", media_ids=[photo])
    media_stub.elsewhere.add(photo)
    resp = client_for(author).patch(
        reverse("posts:post-detail", args=[post.id]), {"audience": "friends"}, format="json"
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "media_already_attached"
    assert Post.objects.get(id=post.id).audience == "public"
