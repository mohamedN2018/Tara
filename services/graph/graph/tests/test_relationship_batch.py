"""Internal batch relationships for search results (roadmap 1.15)."""

import time
import uuid

import jwt
import pytest
from django.conf import settings
from django.urls import reverse
from rest_framework.test import APIClient

from graph import services
from graph.models import BlockRelation

pytestmark = pytest.mark.django_db


def _acct() -> str:
    return str(uuid.uuid4())


def _befriend(a: str, b: str) -> None:
    request = services.send_friend_request(a, b)
    services.accept_friend_request(b, str(request.id))


def _internal(audience="graph-internal") -> APIClient:
    now = int(time.time())
    token = jwt.encode(
        {"iss": "search", "aud": audience, "iat": now, "exp": now + 30},
        settings.TARA_INTERNAL_JWT_SECRET,
        algorithm="HS256",
    )
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


def _batch(viewer, users=(), pages=(), client=None):
    resp = (client or _internal()).post(
        reverse("relationship-batch"),
        {"viewer_id": viewer, "users": list(users), "pages": list(pages)},
        format="json",
    )
    assert resp.status_code == 200, resp.content
    return resp.json()["data"]["results"]


def test_states_request_ids_follows_and_mutual_counts():
    me, friend, asked, asking, followed, stranger = (_acct() for _ in range(6))
    common1, common2 = _acct(), _acct()
    _befriend(me, friend)
    out = services.send_friend_request(me, asked)
    incoming = services.send_friend_request(asking, me)
    services.follow(me, followed)
    for c in (common1, common2):
        _befriend(me, c)
        _befriend(stranger, c)

    res = _batch(me, [friend, asked, asking, followed, stranger, me, "not-a-uuid"])
    assert res[friend]["state"] == "friends"
    assert res[asked] == {
        "state": "pending_out",
        "request_id": str(out.id),
        "following": False,
        "mutual_count": 0,
    }
    assert res[asking]["state"] == "pending_in"
    assert res[asking]["request_id"] == str(incoming.id)
    assert res[followed]["following"] is True and res[followed]["state"] == "none"
    assert res[stranger]["mutual_count"] == 2
    assert me not in res and "not-a-uuid" not in res


def test_blocked_targets_are_absent_and_never_counted_as_mutual():
    me, blocker, target, shared = _acct(), _acct(), _acct(), _acct()
    _befriend(me, shared)
    _befriend(target, shared)
    services.block(blocker, me)
    res = _batch(me, [blocker, target])
    assert blocker not in res
    assert res[target]["mutual_count"] == 1
    # A block between the shared friend and the target hides that friend.
    BlockRelation.objects.create(blocker_id=shared, blocked_id=target)
    assert _batch(me, [target])[target]["mutual_count"] == 0


def test_page_follow_state_and_counts():
    me, other = _acct(), _acct()
    page, quiet = _acct(), _acct()
    services.follow(me, page, "page")
    services.follow(other, page, "page")
    res = _batch(me, pages=[page, quiet])
    assert res[page] == {"following": True, "followers_count": 2}
    assert res[quiet] == {"following": False, "followers_count": 0}


def test_query_count_does_not_grow_with_the_batch(django_assert_max_num_queries):
    me = _acct()
    users = [_acct() for _ in range(40)]
    for u in users[:10]:
        _befriend(me, u)
    with django_assert_max_num_queries(12):
        _batch(me, users, [_acct() for _ in range(10)])


def test_requires_an_internal_token():
    url = reverse("relationship-batch")
    assert APIClient().post(url, {"viewer_id": _acct()}, format="json").status_code == 401
    wrong = _internal("post-internal")
    assert wrong.post(url, {"viewer_id": _acct()}, format="json").status_code == 401
    assert _internal().post(url, {"viewer_id": "x"}, format="json").status_code == 400
