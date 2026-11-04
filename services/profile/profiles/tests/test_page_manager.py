"""Pages manager (plan 08, track T3): page avatar and cover, follow counts from
graph, the ``ids`` lookup, reserved handles and the internal access check that
post asks before a post is published as a page."""

import uuid

import pytest
from django.urls import reverse
from django.utils import timezone

from profiles import media_client, page_graph, services
from profiles.media_client import MediaInfo
from profiles.models import BlockedPair, OutboxEvent, Page, PageMember
from tara_common.auth import mint_internal_token
from tara_common.exceptions import TaraAPIError
from tara_resilience import CircuitBreaker

pytestmark = pytest.mark.django_db


def _acct() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def media(monkeypatch):
    class _Media:
        def __init__(self):
            self.assets: dict[str, MediaInfo] = {}
            self.down = False

        def add(self, owner, *, kind="image", status="ready") -> str:
            media_id = _acct()
            self.assets[media_id] = MediaInfo(media_id, str(owner), kind, status)
            return media_id

        def lookup(self, ids):
            if self.down:
                raise TaraAPIError("down", code="dependency_unavailable", http_status_code=503)
            return {m: self.assets[m] for m in ids if m in self.assets}

    fake = _Media()
    monkeypatch.setattr(media_client, "lookup", fake.lookup)
    return fake


class _Resp:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        return None

    def json(self):
        return self.body


@pytest.fixture
def graph(monkeypatch):
    """Graph's relationship batch: ``graph.pages = {page_id: (following, count)}``."""
    monkeypatch.setattr(page_graph, "_breaker", CircuitBreaker(name="page-graph-test"))

    class _Graph:
        def __init__(self):
            self.pages: dict[str, tuple[bool, int]] = {}
            self.calls: list[dict] = []
            self.down = False

        def post(self, url, json, headers, timeout):
            self.calls.append({"url": url, "json": json})
            if self.down:
                raise ConnectionError("graph down")
            results = {
                p: {"following": f, "followers_count": n}
                for p, (f, n) in self.pages.items()
                if p in json["pages"]
            }
            return _Resp({"data": {"results": results}})

    fake = _Graph()
    monkeypatch.setattr(page_graph.requests, "post", fake.post)
    return fake


def _page(owner=None, **kw) -> Page:
    owner = owner or _acct()
    data = {"handle": f"p{uuid.uuid4().hex[:10]}", "name": "Nile Books", **kw}
    return services.create_page(owner, data)


def _member(page: Page, role: str) -> str:
    account = _acct()
    PageMember.objects.create(page=page, account_id=account, role=role)
    return account


# ---- avatar and cover ---------------------------------------------------------------


@pytest.mark.parametrize("field", ["avatar_media_id", "cover_media_id"])
def test_an_editor_sets_the_page_avatar_or_cover_from_their_own_upload(
    auth_client, media, graph, field
):
    page = _page()
    editor = _member(page, "editor")
    media_id = media.add(editor)
    resp = auth_client(editor).patch(
        reverse("profiles:page-detail", args=[page.id]), {field: media_id}, format="json"
    )
    assert resp.status_code == 200, resp.content
    assert resp.json()["data"][field] == media_id
    page.refresh_from_db()
    assert str(getattr(page, field)) == media_id
    event = OutboxEvent.objects.filter(event_type="page.updated").latest("created_at")
    assert field in event.payload["payload"]["changed"]


def test_someone_elses_image_cannot_be_the_page_avatar(auth_client, media, graph):
    owner = _acct()
    page = _page(owner)
    stranger_image = media.add(_acct())
    resp = auth_client(owner).patch(
        reverse("profiles:page-detail", args=[page.id]),
        {"avatar_media_id": stranger_image},
        format="json",
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "media_not_owned"
    page.refresh_from_db()
    assert page.avatar_media_id is None


def test_a_video_or_an_unfinished_upload_is_refused(auth_client, media, graph):
    owner = _acct()
    page = _page(owner)
    client = auth_client(owner)
    url = reverse("profiles:page-detail", args=[page.id])
    video = media.add(owner, kind="video")
    assert (
        client.patch(url, {"cover_media_id": video}, format="json").json()["error"]["code"]
        == "media_kind_not_allowed"
    )
    failed = media.add(owner, status="failed")
    assert (
        client.patch(url, {"cover_media_id": failed}, format="json").json()["error"]["code"]
        == "media_not_ready"
    )


def test_media_down_saves_nothing(auth_client, media, graph):
    owner = _acct()
    page = _page(owner)
    image = media.add(owner)
    media.down = True
    resp = auth_client(owner).patch(
        reverse("profiles:page-detail", args=[page.id]), {"avatar_media_id": image}, format="json"
    )
    assert resp.status_code == 503
    page.refresh_from_db()
    assert page.avatar_media_id is None


def test_an_analyst_cannot_change_the_page_images(auth_client, media, graph):
    page = _page()
    analyst = _member(page, "analyst")
    resp = auth_client(analyst).patch(
        reverse("profiles:page-detail", args=[page.id]),
        {"avatar_media_id": media.add(analyst)},
        format="json",
    )
    assert resp.status_code == 403


def test_a_page_is_created_with_its_images_and_contact(auth_client, media, graph):
    owner = _acct()
    avatar, cover = media.add(owner), media.add(owner)
    resp = auth_client(owner).post(
        reverse("profiles:page-create"),
        {
            "handle": "nilebooks",
            "name": "Nile Books",
            "avatar_media_id": avatar,
            "cover_media_id": cover,
            "contact": {"website": "https://nile.example", "phone": "+20 100 000 0000"},
        },
        format="json",
    )
    assert resp.status_code == 201, resp.content
    data = resp.json()["data"]
    assert (data["avatar_media_id"], data["cover_media_id"]) == (avatar, cover)
    assert data["contact"] == {"website": "https://nile.example", "phone": "+20 100 000 0000"}
    created = OutboxEvent.objects.get(event_type="page.created").payload["payload"]
    assert created["avatar_media_id"] == avatar


def test_clearing_the_avatar_needs_no_media_call(auth_client, media, graph):
    owner = _acct()
    page = _page(owner)
    Page.objects.filter(id=page.id).update(avatar_media_id=media.add(owner))
    media.down = True
    resp = auth_client(owner).patch(
        reverse("profiles:page-detail", args=[page.id]), {"avatar_media_id": None}, format="json"
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["avatar_media_id"] is None


# ---- reserved handles ---------------------------------------------------------------


@pytest.mark.parametrize("handle", ["manage", "settings", "new", "Followed"])
def test_route_words_are_not_page_handles(auth_client, graph, handle):
    resp = auth_client(_acct()).post(
        reverse("profiles:page-create"), {"handle": handle, "name": "X"}, format="json"
    )
    assert resp.status_code == 409


# ---- follow counts and the ids lookup -------------------------------------------------


def test_the_page_carries_the_viewers_follow_state_and_the_follower_count(auth_client, graph):
    page = _page()
    graph.pages[str(page.id)] = (True, 42)
    data = auth_client(_acct()).get(reverse("profiles:page-by-handle", args=[page.handle])).json()
    assert (data["data"]["viewer_following"], data["data"]["followers_count"]) == (True, 42)


def test_graph_down_leaves_the_counts_unknown_not_zero(auth_client, graph):
    page = _page()
    graph.down = True
    resp = auth_client(_acct()).get(reverse("profiles:page-detail", args=[page.id]))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["viewer_following"] is None and data["followers_count"] is None


def test_ids_returns_the_visible_pages_among_them(auth_client, graph):
    viewer = _acct()
    shown = _page()
    draft = _page(status="draft")
    Page.objects.filter(id=draft.id).update(status="draft")
    graph.pages[str(shown.id)] = (True, 3)
    resp = auth_client(viewer).get(
        reverse("profiles:page-create"), {"ids": f"{shown.id},{draft.id},{uuid.uuid4()}"}
    )
    assert resp.status_code == 200
    rows = resp.json()["data"]
    assert [r["id"] for r in rows] == [str(shown.id)]
    assert rows[0]["followers_count"] == 3
    # One graph call for the whole list.
    assert len(graph.calls) == 1


def test_bad_ids_are_a_validation_error(auth_client, graph):
    resp = auth_client(_acct()).get(reverse("profiles:page-create"), {"ids": "nope"})
    assert resp.status_code == 400


# ---- internal access for post ----------------------------------------------------------


def _access(client, page_id, account_id):
    token = mint_internal_token(issuer="post", audience="profile-internal")
    return client.get(
        f"/internal/v1/pages/{page_id}/access/",
        {"account_id": account_id},
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )


@pytest.mark.parametrize(
    ("role", "can_post", "can_moderate"),
    [
        ("owner", True, True),
        ("admin", True, True),
        ("editor", True, True),
        ("moderator", False, True),
        ("advertiser", False, False),
        ("analyst", False, False),
        (None, False, False),
    ],
)
def test_page_access_by_role(api_client, role, can_post, can_moderate):
    owner = _acct()
    page = _page(owner)
    if role == "owner":
        account = owner
    elif role:
        account = _member(page, role)
    else:
        account = _acct()
    data = _access(api_client, page.id, account).json()["data"]
    assert (data["role"], data["can_post"], data["can_moderate"]) == (role, can_post, can_moderate)


def test_a_draft_page_cannot_post(api_client):
    owner = _acct()
    page = _page(owner)
    Page.objects.filter(id=page.id).update(status="draft")
    data = _access(api_client, page.id, owner).json()["data"]
    assert data["can_post"] is False


def test_page_access_needs_an_internal_token_and_a_live_page(api_client):
    page = _page()
    resp = api_client.get(f"/internal/v1/pages/{page.id}/access/", {"account_id": _acct()})
    assert resp.status_code == 401
    assert _access(api_client, uuid.uuid4(), _acct()).status_code == 404


def test_page_team_lists_every_member_with_their_role(api_client):
    owner = _acct()
    page = _page(owner)
    editor = _member(page, "editor")
    analyst = _member(page, "analyst")
    url = f"/internal/v1/pages/{page.id}/team/"
    assert api_client.get(url).status_code == 401
    auth = f"Bearer {mint_internal_token(issuer='chat', audience='profile-internal')}"
    members = api_client.get(url, HTTP_AUTHORIZATION=auth).json()["data"]["members"]
    assert members[0] == {"account_id": owner, "role": "owner"}
    assert {(m["account_id"], m["role"]) for m in members[1:]} == {
        (editor, "editor"),
        (analyst, "analyst"),
    }
    missing = f"/internal/v1/pages/{uuid.uuid4()}/team/"
    assert api_client.get(missing, HTTP_AUTHORIZATION=auth).status_code == 404
    Page.objects.filter(id=page.id).update(deleted_at=timezone.now())
    assert api_client.get(url, HTTP_AUTHORIZATION=auth).status_code == 404


# ---- internal visibility for post (a hidden page's posts are hidden too) ---------------


def _visibility(client, page_ids, viewer_id=None, token=True):
    headers = {}
    if token:
        headers["HTTP_AUTHORIZATION"] = (
            f"Bearer {mint_internal_token(issuer='post', audience='profile-internal')}"
        )
    return client.post(
        "/internal/v1/pages/visibility/",
        {"page_ids": [str(p) for p in page_ids], "viewer_id": viewer_id},
        format="json",
        **headers,
    )


def test_page_visibility_hides_draft_suspended_and_deleted_pages_from_outsiders(api_client):
    owner = _acct()
    live, draft, suspended, deleted = (_page(owner) for _ in range(4))
    Page.objects.filter(id=draft.id).update(status=Page.Status.DRAFT)
    Page.objects.filter(id=suspended.id).update(status=Page.Status.SUSPENDED)
    Page.objects.filter(id=deleted.id).update(deleted_at=timezone.now())
    ids = [live.id, draft.id, suspended.id, deleted.id, uuid.uuid4()]

    outsider = _visibility(api_client, ids, _acct()).json()["data"]["visible"]
    assert outsider == [str(live.id)]
    anyone = _visibility(api_client, ids).json()["data"]["visible"]
    assert anyone == [str(live.id)]
    # The page's team still sees its unpublished pages; a deleted one is gone for all.
    analyst = _member(draft, "analyst")
    team = _visibility(api_client, ids, owner).json()["data"]["visible"]
    assert sorted(team) == sorted(str(p.id) for p in (live, draft, suspended))
    assert _visibility(api_client, [draft.id], analyst).json()["data"]["visible"] == [str(draft.id)]


def test_page_visibility_hides_a_page_whose_owner_blocks_the_viewer(api_client):
    owner, viewer = _acct(), _acct()
    page = _page(owner)
    BlockedPair.objects.create(blocker_id=owner, blocked_id=viewer)
    assert _visibility(api_client, [page.id], viewer).json()["data"]["visible"] == []


def test_page_visibility_needs_an_internal_token_and_bounded_ids(api_client):
    page = _page()
    assert _visibility(api_client, [page.id], token=False).status_code == 401
    too_many = [uuid.uuid4() for _ in range(201)]
    assert _visibility(api_client, too_many).status_code == 400
