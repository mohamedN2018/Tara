"""Milestone 1.3: flattened threads, paged replies, edit/delete, comment
reactions, the per-post comment policy and comment reports."""

import uuid

import pytest
from django.urls import reverse

from posts import handlers, services
from posts.clients import Relationship
from posts.models import BlockedPair, Comment, CommentReport, OutboxEvent, Post
from tara_common.exceptions import TaraAPIError
from tara_events.envelope import EventEnvelope

pytestmark = pytest.mark.django_db


def _acct() -> str:
    return str(uuid.uuid4())


def _rel(**kw):
    return lambda a, b: Relationship(**kw)


def _payload(event_type: str) -> dict:
    return OutboxEvent.objects.filter(event_type=event_type).latest("created_at").payload["payload"]


def _count(event_type: str) -> int:
    return OutboxEvent.objects.filter(event_type=event_type).count()


def _walk(client, url, limit=2):
    items, cursor = [], None
    for _ in range(30):
        resp = client.get(url, {"limit": limit, **({"cursor": cursor} if cursor else {})})
        assert resp.status_code == 200, resp.content
        body = resp.json()
        items += body["data"]
        cursor = body["page"]["next_cursor"]
        if not cursor:
            return items
    raise AssertionError("pagination did not end")


def _replies_url(comment_id):
    return reverse("posts:comment-replies", args=[comment_id])


def _comment_url(comment_id):
    return reverse("posts:comment-detail", args=[comment_id])


# ---- flattening ----------------------------------------------------------------


def test_a_reply_to_a_reply_is_flattened_onto_the_root(client_for):
    author, a, b = _acct(), _acct(), _acct()
    post = services.create_post(author, body="p")
    root = services.add_comment(a, str(post.id), "root")
    first = services.add_comment(b, str(post.id), "first", str(root.id))

    resp = client_for(a).post(_replies_url(first.id), {"body": "second"}, format="json")
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["parent_id"] == str(root.id)
    assert data["reply_to_id"] == str(first.id)
    assert data["reply_to_author_id"] == b

    stored = Comment.objects.get(id=data["id"])
    assert stored.parent_id == root.id and stored.reply_to_id == first.id
    root.refresh_from_db()
    assert root.reply_count == 2
    # The notification goes to the person answered, not the thread root's author.
    payload = _payload("comment.replied")
    assert payload["parent_id"] == str(root.id)
    assert payload["parent_author_id"] == b
    assert payload["reply_to_id"] == str(first.id)
    assert payload["root_author_id"] == a


def test_reply_to_id_on_the_post_endpoint_is_flattened_too(client_for):
    author = _acct()
    post = services.create_post(author, body="p")
    root = services.add_comment(author, str(post.id), "root")
    reply = services.add_comment(author, str(post.id), "r1", str(root.id))
    resp = client_for(author).post(
        reverse("posts:post-comments", args=[post.id]),
        {"body": "r2", "reply_to_id": str(reply.id)},
        format="json",
    )
    assert resp.status_code == 201
    assert resp.json()["data"]["parent_id"] == str(root.id)


def test_the_post_comes_from_the_target_never_from_the_client(client_for):
    author = _acct()
    post_a = services.create_post(author, body="a")
    post_b = services.create_post(author, body="b")
    on_a = services.add_comment(author, str(post_a.id), "on a")
    # Naming post B with a comment from post A cannot join the two.
    resp = client_for(author).post(
        reverse("posts:post-comments", args=[post_b.id]),
        {"body": "x", "reply_to_id": str(on_a.id)},
        format="json",
    )
    assert resp.status_code == 404
    assert not Comment.objects.filter(post=post_b).exists()


def test_reply_to_a_deleted_root_is_404(client_for):
    author = _acct()
    post = services.create_post(author, body="p")
    root = services.add_comment(author, str(post.id), "root")
    reply = services.add_comment(author, str(post.id), "r", str(root.id))
    services.delete_comment(author, str(root.id))
    resp = client_for(author).post(_replies_url(reply.id), {"body": "x"}, format="json")
    assert resp.status_code == 404


# ---- paginated replies ---------------------------------------------------------------


def test_comment_list_has_only_roots_and_replies_page_without_duplicates(client_for):
    author = _acct()
    post = services.create_post(author, body="p")
    root = services.add_comment(author, str(post.id), "root")
    replies = [
        str(services.add_comment(author, str(post.id), f"r{i}", str(root.id)).id) for i in range(5)
    ]
    other_root = services.add_comment(author, str(post.id), "root 2")
    client = client_for(author)

    roots = _walk(client, reverse("posts:post-comments", args=[post.id]))
    assert [c["id"] for c in roots] == [str(root.id), str(other_root.id)]
    assert roots[0]["reply_count"] == 5

    got = _walk(client, _replies_url(root.id))
    assert [c["id"] for c in got] == replies
    assert len({c["id"] for c in got}) == 5


def test_replies_of_a_hidden_post_are_404(client_for, monkeypatch):
    monkeypatch.setattr("posts.services.get_relationship", _rel())
    author = _acct()
    post = services.create_post(author, body="p", audience="friends")
    root = services.add_comment(author, str(post.id), "root")
    resp = client_for(_acct()).get(_replies_url(root.id))
    assert resp.status_code == 404


def test_replies_hide_blocked_authors_and_a_blocked_root_is_404(client_for):
    viewer, author, blocked = _acct(), _acct(), _acct()
    post = services.create_post(author, body="p")
    root = services.add_comment(author, str(post.id), "root")
    ok = services.add_comment(author, str(post.id), "ok", str(root.id))
    services.add_comment(blocked, str(post.id), "hidden", str(root.id))
    blocked_root = services.add_comment(blocked, str(post.id), "blocked root")
    BlockedPair.objects.create(blocker_id=viewer, blocked_id=blocked)
    client = client_for(viewer)

    resp = client.get(_replies_url(root.id))
    assert [c["id"] for c in resp.json()["data"]] == [str(ok.id)]
    assert client.get(_replies_url(blocked_root.id)).status_code == 404


# ---- edit and delete -------------------------------------------------------------------


def test_author_edits_a_comment(client_for):
    author = _acct()
    post = services.create_post(author, body="p")
    comment = services.add_comment(author, str(post.id), "old @alice")
    resp = client_for(author).patch(
        _comment_url(comment.id), {"body": "new @alice @bob"}, format="json"
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["body"] == "new @alice @bob"
    assert data["edited_at"]
    payload = _payload("comment.edited")
    assert payload["new_mentions"] == ["bob"]


def test_only_the_author_can_edit(client_for):
    author, post_author = _acct(), _acct()
    post = services.create_post(post_author, body="p")
    comment = services.add_comment(author, str(post.id), "mine")
    resp = client_for(post_author).patch(_comment_url(comment.id), {"body": "x"}, format="json")
    assert resp.status_code == 404
    assert _count("comment.edited") == 0


def test_deleting_a_reply_decrements_both_counts(client_for):
    author = _acct()
    post = services.create_post(author, body="p")
    root = services.add_comment(author, str(post.id), "root")
    reply = services.add_comment(author, str(post.id), "r", str(root.id))

    resp = client_for(author).delete(_comment_url(reply.id))
    assert resp.status_code == 200
    assert resp.json()["data"]["comment_count"] == 1
    root.refresh_from_db()
    assert root.reply_count == 0
    assert Post.objects.get(id=post.id).comment_count == 1
    assert _payload("comment.deleted")["removed_ids"] == [str(reply.id)]


def test_deleting_a_root_removes_its_thread(client_for):
    author, other = _acct(), _acct()
    post = services.create_post(author, body="p")
    root = services.add_comment(other, str(post.id), "root")
    services.add_comment(author, str(post.id), "r1", str(root.id))
    services.add_comment(other, str(post.id), "r2", str(root.id))
    services.add_comment(author, str(post.id), "other root")

    # The post's author may delete someone else's comment.
    resp = client_for(author).delete(_comment_url(root.id))
    assert resp.status_code == 200
    assert resp.json()["data"]["comment_count"] == 1
    assert Comment.objects.filter(post=post, deleted_at__isnull=True).count() == 1
    payload = _payload("comment.deleted")
    assert len(payload["removed_ids"]) == 3
    assert payload["by"] == "post_author"


def test_a_stranger_cannot_delete(client_for):
    author, commenter, stranger = _acct(), _acct(), _acct()
    post = services.create_post(author, body="p")
    comment = services.add_comment(commenter, str(post.id), "c")
    assert client_for(stranger).delete(_comment_url(comment.id)).status_code == 403

    hidden = services.create_post(author, body="p", audience="only_me")
    mine = services.add_comment(author, str(hidden.id), "c")
    assert client_for(stranger).delete(_comment_url(mine.id)).status_code == 404
    assert _count("comment.deleted") == 0
    assert Post.objects.get(id=post.id).comment_count == 1


def test_delete_twice_does_not_decrement_twice():
    author = _acct()
    post = services.create_post(author, body="p")
    comment = services.add_comment(author, str(post.id), "c")
    services.delete_comment(author, str(comment.id))
    with pytest.raises(TaraAPIError) as exc:
        services.delete_comment(author, str(comment.id))
    assert exc.value.http_status == 404
    assert Post.objects.get(id=post.id).comment_count == 0
    assert _count("comment.deleted") == 1


def test_moderation_remove_and_approve_round_trip():
    author = _acct()
    post = services.create_post(author, body="p")
    root = services.add_comment(author, str(post.id), "root")
    services.add_comment(author, str(post.id), "r", str(root.id))
    event = lambda action: EventEnvelope(  # noqa: E731
        event_type="moderation.actioned",
        payload={"target_type": "comment", "target_id": str(root.id), "action": action},
        subject_id=str(uuid.uuid4()),
        producer="moderation-service",
    )
    handlers.on_moderation_actioned(event("remove"))
    assert Post.objects.get(id=post.id).comment_count == 0
    assert _payload("comment.deleted")["by"] == "moderation"

    handlers.on_moderation_actioned(event("approve"))
    assert Post.objects.get(id=post.id).comment_count == 2
    assert Comment.objects.filter(post=post, deleted_at__isnull=True).count() == 2


# ---- comment reactions -----------------------------------------------------------------


def test_comment_reactions(client_for):
    author, reactor = _acct(), _acct()
    post = services.create_post(author, body="p")
    comment = services.add_comment(author, str(post.id), "c")
    client = client_for(reactor)
    url = reverse("posts:comment-reactions", args=[comment.id])

    assert client.post(url, {"type": "love"}, format="json").json()["data"]["reaction_count"] == 1
    assert client.post(url, {"type": "haha"}, format="json").json()["data"]["reaction_count"] == 1
    assert _count("comment.reacted") == 1
    listed = client.get(reverse("posts:post-comments", args=[post.id])).json()["data"][0]
    assert listed["my_reaction"] == "haha"
    assert listed["reaction_count"] == 1

    assert client.delete(url).status_code == 204
    assert client.delete(url).status_code == 204  # idempotent
    comment.refresh_from_db()
    assert comment.reaction_count == 0


def test_cannot_react_to_a_hidden_comment(client_for, monkeypatch):
    monkeypatch.setattr("posts.services.get_relationship", _rel())
    author = _acct()
    post = services.create_post(author, body="p", audience="friends")
    comment = services.add_comment(author, str(post.id), "c")
    resp = client_for(_acct()).post(
        reverse("posts:comment-reactions", args=[comment.id]), {"type": "like"}, format="json"
    )
    assert resp.status_code == 404


# ---- comment policy ----------------------------------------------------------------------


def _comment(client, post_id, body="hi"):
    return client.post(
        reverse("posts:post-comments", args=[post_id]), {"body": body}, format="json"
    )


def test_policy_off_blocks_comments_and_replies(client_for):
    author = _acct()
    post = services.create_post(author, body="p")
    root = services.add_comment(author, str(post.id), "before")
    resp = client_for(author).patch(
        reverse("posts:post-detail", args=[post.id]), {"comment_policy": "off"}, format="json"
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["comment_policy"] == "off"

    other = client_for(_acct())
    assert _comment(other, post.id).json()["error"]["code"] == "comments_disabled"
    assert other.post(_replies_url(root.id), {"body": "x"}, format="json").status_code == 403
    assert Post.objects.get(id=post.id).comment_count == 1
    # Existing comments stay readable.
    assert len(other.get(reverse("posts:post-comments", args=[post.id])).json()["data"]) == 1


def test_policy_friends_is_enforced_server_side(client_for, monkeypatch):
    author, friend, stranger = _acct(), _acct(), _acct()
    monkeypatch.setattr(
        "posts.services.get_relationship", lambda a, b: Relationship(are_friends=a == friend)
    )
    resp = client_for(author).post(
        reverse("posts:post-create"), {"body": "p", "comment_policy": "friends"}, format="json"
    )
    post_id = resp.json()["data"]["id"]
    assert _comment(client_for(friend), post_id).status_code == 201
    assert _comment(client_for(author), post_id).status_code == 201
    blocked = _comment(client_for(stranger), post_id)
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "comments_friends_only"


def test_invalid_policy_is_400(client_for):
    resp = client_for(_acct()).post(
        reverse("posts:post-create"), {"body": "p", "comment_policy": "maybe"}, format="json"
    )
    assert resp.status_code == 400


# ---- comment reports ----------------------------------------------------------------------


def _report(client, comment_id):
    return client.post(
        reverse("posts:comment-report", args=[comment_id]), {"reason": "spam"}, format="json"
    )


def test_report_comment_emits_once_with_the_owner(client_for):
    author, reporter = _acct(), _acct()
    post = services.create_post(author, body="p")
    comment = services.add_comment(author, str(post.id), "bad")
    client = client_for(reporter)
    assert _report(client, comment.id).status_code == 202
    assert _report(client, comment.id).status_code == 202
    assert CommentReport.objects.count() == 1
    assert _count("comment.reported") == 1
    payload = _payload("comment.reported")
    assert payload == {
        "comment_id": str(comment.id),
        "post_id": str(post.id),
        "reporter": reporter,
        "reason": "spam",
        "owner_id": author,
    }


def test_reporting_a_comment_you_cannot_see_is_404_and_writes_nothing(client_for, monkeypatch):
    monkeypatch.setattr("posts.services.get_relationship", _rel())
    author, stranger = _acct(), _acct()
    post = services.create_post(author, body="p", audience="friends")
    comment = services.add_comment(author, str(post.id), "c")
    assert _report(client_for(stranger), comment.id).status_code == 404

    public = services.create_post(author, body="p")
    blocked_comment = services.add_comment(author, str(public.id), "c")
    BlockedPair.objects.create(blocker_id=author, blocked_id=stranger)
    assert _report(client_for(stranger), blocked_comment.id).status_code == 404

    services.delete_comment(author, str(comment.id))
    assert _report(client_for(author), comment.id).status_code == 404
    assert _count("comment.reported") == 0
    assert CommentReport.objects.count() == 0
