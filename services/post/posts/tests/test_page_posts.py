"""Posting as a page (track T3): profile says who may act for the page, the post
is stored as the page's, its media stay the editor's own uploads, and the
page's staff delete its posts. Also: unsaving any kind of saved item."""

import time
import uuid

import jwt
import pytest
from django.conf import settings
from django.core.cache import cache
from django.urls import reverse
from rest_framework.test import APIClient

from posts import pages, services
from posts.models import OutboxEvent, Post, SavedItem
from tara_common.exceptions import TaraAPIError

pytestmark = pytest.mark.django_db


def _acct() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def profile_pages(monkeypatch):
    """Profile's page access answers: ``profile_pages.roles[(page, account)] = role``."""

    class _Pages:
        def __init__(self):
            self.roles: dict[tuple[str, str], str] = {}
            self.status: dict[str, str] = {}
            self.deleted: set[str] = set()
            self.down = False
            self.calls = 0
            self.visibility_calls = 0

        def fetch(self, page_id, account_id):
            self.calls += 1
            if self.down:
                raise pages._unavailable()
            page_id, account_id = str(page_id), str(account_id)
            if page_id not in self.status or page_id in self.deleted:
                return pages._MISSING
            role = self.roles.get((page_id, account_id))
            published = self.status[page_id] == "published"
            return {
                "page_id": page_id,
                "status": self.status[page_id],
                "role": role,
                "can_post": published and role in ("owner", "admin", "editor"),
                "can_moderate": role in ("owner", "admin", "editor", "moderator"),
            }

        def visibility(self, page_ids, viewer_id):
            """Profile's rule for the page itself: published and live, or the
            viewer is on the page's team (a deleted page: nobody)."""
            self.visibility_calls += 1
            if self.down:
                return None
            return {
                p
                for p in page_ids
                if p in self.status
                and p not in self.deleted
                and (self.status[p] == "published" or (p, str(viewer_id)) in self.roles)
            }

        def page(self, *, status="published") -> str:
            page_id = _acct()
            self.status[page_id] = status
            return page_id

        def hide(self, page_id, how: str) -> None:
            """Set back to draft, suspended, or deleted; cached answers expire."""
            if how == "deleted":
                self.deleted.add(page_id)
            else:
                self.status[page_id] = how
            cache.clear()

    cache.clear()
    fake = _Pages()
    monkeypatch.setattr(pages, "_fetch", fake.fetch)
    monkeypatch.setattr(pages, "_fetch_visibility", fake.visibility)
    return fake


def _post_as(client, page_id, **body):
    return client.post(
        reverse("posts:post-create"), {"body": "Hello", "page_id": page_id, **body}, format="json"
    )


@pytest.mark.parametrize("role", ["owner", "admin", "editor"])
def test_page_staff_post_as_the_page(client_for, profile_pages, role):
    page_id = profile_pages.page()
    me = _acct()
    profile_pages.roles[(page_id, me)] = role
    resp = _post_as(client_for(me), page_id, audience="friends")
    assert resp.status_code == 201, resp.content
    data = resp.json()["data"]
    assert (data["author_id"], data["author_type"], data["audience"]) == (
        page_id,
        "page",
        "public",
    )
    event = OutboxEvent.objects.get(event_type="post.created").payload["payload"]
    assert (event["author_id"], event["author_type"]) == (page_id, "page")


@pytest.mark.parametrize("role", ["moderator", "advertiser", "analyst"])
def test_other_page_roles_cannot_post_as_the_page(client_for, profile_pages, role):
    page_id = profile_pages.page()
    me = _acct()
    profile_pages.roles[(page_id, me)] = role
    resp = _post_as(client_for(me), page_id)
    assert resp.status_code == 403
    assert not Post.objects.exists()


def test_a_stranger_or_an_unknown_page_is_a_404(client_for, profile_pages):
    page_id = profile_pages.page()
    assert _post_as(client_for(_acct()), page_id).status_code == 404
    assert _post_as(client_for(_acct()), _acct()).status_code == 404
    assert not Post.objects.exists()


def test_a_draft_page_cannot_post(client_for, profile_pages):
    page_id = profile_pages.page(status="draft")
    me = _acct()
    profile_pages.roles[(page_id, me)] = "owner"
    assert _post_as(client_for(me), page_id).status_code == 403


def test_profile_down_writes_nothing(client_for, profile_pages):
    page_id = profile_pages.page()
    me = _acct()
    profile_pages.roles[(page_id, me)] = "owner"
    profile_pages.down = True
    assert _post_as(client_for(me), page_id).status_code == 503
    assert not Post.objects.exists()


def test_page_posts_have_no_drafts_tags_or_group(client_for, profile_pages):
    page_id = profile_pages.page()
    me = _acct()
    profile_pages.roles[(page_id, me)] = "owner"
    client = client_for(me)
    assert _post_as(client, page_id, draft=True).json()["error"]["code"] == (
        "page_drafts_not_supported"
    )
    assert _post_as(client, page_id, tagged_ids=[_acct()]).json()["error"]["code"] == (
        "page_tags_not_supported"
    )
    assert _post_as(client, page_id, group_id=_acct()).status_code == 400
    assert not Post.objects.exists()
    assert profile_pages.calls == 0  # refused before profile is asked


def test_page_post_media_are_the_editors_own(client_for, profile_pages, media_stub):
    page_id = profile_pages.page()
    me = _acct()
    profile_pages.roles[(page_id, me)] = "editor"
    mine = media_stub.add(me)
    resp = _post_as(client_for(me), page_id, type="image", media_ids=[mine])
    assert resp.status_code == 201, resp.content
    assert media_stub.binds[-1]["owner_id"] == me
    other = media_stub.add(_acct())
    resp = _post_as(client_for(me), page_id, type="image", media_ids=[other])
    assert resp.status_code == 400


def test_the_page_timeline_lists_its_posts(client_for, profile_pages):
    page_id = profile_pages.page()
    me = _acct()
    profile_pages.roles[(page_id, me)] = "owner"
    _post_as(client_for(me), page_id)
    services.create_post(me, body="my own")
    resp = client_for(_acct()).get(reverse("posts:post-create"), {"author_id": page_id})
    assert resp.status_code == 200
    rows = resp.json()["data"]
    assert [r["body"] for r in rows] == ["Hello"]
    # Never on the editor's own timeline.
    own = client_for(_acct()).get(reverse("posts:post-create"), {"author_id": me}).json()
    assert [r["body"] for r in own["data"]] == ["my own"]


@pytest.mark.parametrize(("role", "code"), [("moderator", 204), ("analyst", 404), (None, 404)])
def test_page_staff_delete_the_pages_posts(client_for, profile_pages, role, code):
    page_id = profile_pages.page()
    owner = _acct()
    profile_pages.roles[(page_id, owner)] = "owner"
    post_id = _post_as(client_for(owner), page_id).json()["data"]["id"]
    other = _acct()
    if role:
        profile_pages.roles[(page_id, other)] = role
    resp = client_for(other).delete(reverse("posts:post-detail", args=[post_id]))
    assert resp.status_code == code
    deleted = Post.objects.get(id=post_id).deleted_at is not None
    assert deleted is (code == 204)


def test_hiding_a_page_post_restricts_its_media_for_their_uploader(profile_pages, media_stub):
    page_id = profile_pages.page()
    editor = _acct()
    profile_pages.roles[(page_id, editor)] = "editor"
    image = media_stub.add(editor)
    post = services.create_post(
        editor, body="x", post_type="image", media_ids=[image], page_id=page_id
    )
    services.delete_post(editor, str(post.id))
    services.restrict_media_of_hidden_post(str(post.id))
    last = media_stub.binds[-1]
    assert (last["owner_id"], last["ids"], last["restricted"]) == (editor, [image], True)


def test_require_moderator_hides_the_post_from_others(profile_pages):
    page_id = profile_pages.page()
    with pytest.raises(TaraAPIError) as exc:
        pages.require_moderator(page_id, _acct())
    assert exc.value.http_status == 404


# ---- unsave any saved item ------------------------------------------------------------


@pytest.mark.parametrize("item_type", ["page", "listing", "video", "post"])
def test_unsave_any_kind_of_item(client_for, item_type):
    me = _acct()
    item_id = _acct()
    client = client_for(me)
    saved = client.post(
        reverse("posts:saved-list"), {"item_type": item_type, "item_id": item_id}, format="json"
    )
    assert saved.status_code == 201
    listed = client.get(reverse("posts:saved-list"), {"item_type": item_type}).json()["data"]
    assert [r["item_id"] for r in listed] == [item_id]
    url = reverse("posts:saved-item-by-target", args=[item_type, item_id])
    assert client.get(url).json()["data"] == {"saved": True}
    assert client_for(_acct()).get(url).json()["data"] == {"saved": False}
    resp = client.delete(reverse("posts:saved-item-by-target", args=[item_type, item_id]))
    assert resp.status_code == 204
    assert not SavedItem.objects.filter(owner_id=me).exists()


def test_unsave_touches_only_my_own_items(client_for):
    item_id = _acct()
    other = _acct()
    services.save_item(other, "page", item_id)
    resp = client_for(_acct()).delete(reverse("posts:saved-item-by-target", args=["page", item_id]))
    assert resp.status_code == 204
    assert SavedItem.objects.filter(owner_id=other).exists()


# ---- a hidden page's posts are hidden everywhere --------------------------------------


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


@pytest.fixture
def page_post(client_for, profile_pages):
    """A published page with an owner, one post and one comment on it."""
    page_id = profile_pages.page()
    owner = _acct()
    profile_pages.roles[(page_id, owner)] = "owner"
    post_id = _post_as(client_for(owner), page_id).json()["data"]["id"]
    comment = services.add_comment(_acct(), post_id, "nice")
    return {"page": page_id, "owner": owner, "post": post_id, "comment": str(comment.id)}


def _reads(client, page_post) -> dict[str, int]:
    """The status of every read path of the page's post, its timeline and comments."""
    post, comment = page_post["post"], page_post["comment"]
    timeline = client.get(reverse("posts:post-create"), {"author_id": page_post["page"]})
    batch = client.post(reverse("posts:post-batch"), {"ids": [post]}, format="json")
    return {
        "detail": client.get(reverse("posts:post-detail", args=[post])).status_code,
        "timeline": len(timeline.json()["data"]),
        "batch": len(batch.json()["data"]),
        "comments": client.get(reverse("posts:post-comments", args=[post])).status_code,
        "replies": client.get(reverse("posts:comment-replies", args=[comment])).status_code,
        "reactions": client.get(reverse("posts:post-reactions", args=[post])).status_code,
        "shares": client.get(reverse("posts:post-shares", args=[post])).status_code,
        "react": client.post(
            reverse("posts:post-reactions", args=[post]), {"type": "like"}, format="json"
        ).status_code,
        "comment": client.post(
            reverse("posts:post-comments", args=[post]), {"body": "hi"}, format="json"
        ).status_code,
        "share": client.post(
            reverse("posts:post-share", args=[post]), {"body": ""}, format="json"
        ).status_code,
        "save": client.post(reverse("posts:post-save", args=[post])).status_code,
    }


HIDDEN = {
    "detail": 404,
    "timeline": 0,
    "batch": 0,
    "comments": 404,
    "replies": 404,
    "reactions": 404,
    "shares": 404,
    "react": 404,
    "comment": 404,
    "share": 404,
    "save": 404,
}


def test_a_published_pages_posts_are_read_as_before(client_for, page_post):
    reads = _reads(client_for(_acct()), page_post)
    assert reads["detail"] == 200 and reads["timeline"] == 1 and reads["batch"] == 1
    assert reads["comments"] == reads["reactions"] == reads["shares"] == 200


@pytest.mark.parametrize("how", ["draft", "suspended", "deleted"])
def test_a_hidden_pages_posts_404_on_every_read_path(client_for, profile_pages, page_post, how):
    profile_pages.hide(page_post["page"], how)
    assert _reads(client_for(_acct()), page_post) == HIDDEN
    visible = _internal().get(
        reverse("internal-post-visibility", args=[page_post["post"]]), {"viewer_id": _acct()}
    )
    assert visible.json()["data"]["visible"] is False
    # Search's backfill leaves the page's posts out.
    exported = _internal().get(reverse("search-export-posts")).json()["data"]["items"]
    assert page_post["post"] not in [i["id"] for i in exported]


def test_search_export_keeps_a_published_pages_posts(page_post):
    exported = _internal().get(reverse("search-export-posts")).json()["data"]["items"]
    assert page_post["post"] in [i["id"] for i in exported]


@pytest.mark.parametrize("how", ["draft", "suspended"])
def test_the_page_team_still_sees_an_unpublished_pages_posts(
    client_for, profile_pages, page_post, how
):
    profile_pages.hide(page_post["page"], how)
    analyst = _acct()
    profile_pages.roles[(page_post["page"], analyst)] = "analyst"
    for member in (page_post["owner"], analyst):
        client = client_for(member)
        assert client.get(reverse("posts:post-detail", args=[page_post["post"]])).status_code == 200
        timeline = client.get(reverse("posts:post-create"), {"author_id": page_post["page"]})
        assert len(timeline.json()["data"]) == 1


def test_a_deleted_page_hides_its_posts_from_its_team_too(client_for, profile_pages, page_post):
    profile_pages.hide(page_post["page"], "deleted")
    client = client_for(page_post["owner"])
    assert client.get(reverse("posts:post-detail", args=[page_post["post"]])).status_code == 404


def test_page_visibility_is_asked_once_per_timeline_and_cached(
    client_for, profile_pages, page_post
):
    owner = page_post["owner"]
    for _ in range(4):
        _post_as(client_for(owner), page_post["page"])
    viewer = client_for(_acct())
    profile_pages.visibility_calls = 0
    rows = viewer.get(reverse("posts:post-create"), {"author_id": page_post["page"]})
    assert len(rows.json()["data"]) == 5
    assert profile_pages.visibility_calls == 1
    viewer.get(reverse("posts:post-create"), {"author_id": page_post["page"]})
    viewer.get(reverse("posts:post-detail", args=[page_post["post"]]))
    assert profile_pages.visibility_calls == 1  # cached briefly


def test_profile_down_hides_page_posts_but_not_peoples(client_for, profile_pages, page_post):
    mine = services.create_post(_acct(), body="a person's post", audience="public")
    profile_pages.down = True
    client = client_for(_acct())
    assert client.get(reverse("posts:post-detail", args=[page_post["post"]])).status_code == 404
    assert client.get(reverse("posts:post-detail", args=[mine.id])).status_code == 200
    profile_pages.down = False
    # Nothing was cached while profile was down.
    assert client.get(reverse("posts:post-detail", args=[page_post["post"]])).status_code == 200


def test_a_share_of_a_hidden_pages_post_loses_its_original(client_for, profile_pages, page_post):
    sharer = _acct()
    url = reverse("posts:post-share", args=[page_post["post"]])
    share_id = client_for(sharer).post(url, {"body": "look"}, format="json").json()["data"]["id"]
    profile_pages.hide(page_post["page"], "draft")
    data = client_for(_acct()).get(reverse("posts:post-detail", args=[share_id])).json()["data"]
    assert data.get("shared_post") is None


# ---- editing a page's post ------------------------------------------------------------


@pytest.mark.parametrize("role", ["owner", "admin", "editor"])
def test_page_staff_edit_the_pages_posts(client_for, profile_pages, page_post, role):
    member = _acct()
    profile_pages.roles[(page_post["page"], member)] = role
    resp = client_for(member).patch(
        reverse("posts:post-detail", args=[page_post["post"]]), {"body": "Edited"}, format="json"
    )
    assert resp.status_code == 200, resp.content
    assert resp.json()["data"]["body"] == "Edited"
    assert Post.objects.get(id=page_post["post"]).author_id == uuid.UUID(page_post["page"])
    updated = OutboxEvent.objects.filter(event_type="post.updated").last().payload["payload"]
    assert (updated["author_id"], updated["author_type"]) == (page_post["page"], "page")


@pytest.mark.parametrize(("role", "code"), [("analyst", 403), ("moderator", 403), (None, 404)])
def test_others_cannot_edit_the_pages_posts(client_for, profile_pages, page_post, role, code):
    member = _acct()
    if role:
        profile_pages.roles[(page_post["page"], member)] = role
    resp = client_for(member).patch(
        reverse("posts:post-detail", args=[page_post["post"]]), {"body": "Edited"}, format="json"
    )
    assert resp.status_code == code
    assert Post.objects.get(id=page_post["post"]).body == "Hello"


def test_a_page_post_stays_public_and_untagged(client_for, page_post):
    client = client_for(page_post["owner"])
    url = reverse("posts:post-detail", args=[page_post["post"]])
    assert client.patch(url, {"audience": "friends"}, format="json").status_code == 400
    assert client.patch(url, {"tagged_ids": [_acct()]}, format="json").status_code == 400
    assert Post.objects.get(id=page_post["post"]).audience == "public"


def test_an_editor_removed_a_moment_ago_cannot_edit(client_for, profile_pages, page_post):
    editor = _acct()
    profile_pages.roles[(page_post["page"], editor)] = "editor"
    url = reverse("posts:post-detail", args=[page_post["post"]])
    assert client_for(editor).patch(url, {"body": "one"}, format="json").status_code == 200
    del profile_pages.roles[(page_post["page"], editor)]
    assert client_for(editor).patch(url, {"body": "two"}, format="json").status_code == 404
