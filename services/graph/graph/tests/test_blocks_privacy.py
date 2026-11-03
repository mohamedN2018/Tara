"""Milestone 1.1 (graph): blocks are honoured by every relationship list, and a
block emits the removal events that feed/notification/chat consumers rely on."""

import time
import uuid

import jwt
import pytest
from django.conf import settings
from django.urls import reverse
from rest_framework.test import APIClient

from graph import services
from graph.models import BlockRelation, FollowRelation, Friendship, OutboxEvent

pytestmark = pytest.mark.django_db

LIST_ENDPOINTS = ["graph:social-friends", "graph:social-followers", "graph:social-mutual"]
BLOCK_DIRECTIONS = ["viewer_blocked_other", "other_blocked_viewer"]


def _acct() -> str:
    return str(uuid.uuid4())


def _befriend(a: str, b: str) -> Friendship:
    friendship = services.send_friend_request(a, b)
    services.accept_friend_request(b, str(friendship.id))
    return friendship


def _block(direction: str, viewer: str, other: str) -> None:
    if direction == "viewer_blocked_other":
        services.block(viewer, other)
    else:
        services.block(other, viewer)


def _stale_block(blocker: str, blocked: str) -> None:
    """A block row whose edges survived (legacy data, or a request/follow that
    raced block()). Lists must still hide the edges."""
    BlockRelation.objects.create(blocker_id=blocker, blocked_id=blocked)


def _envelopes(event_type: str | None = None) -> list[dict]:
    qs = OutboxEvent.objects.order_by("created_at")
    if event_type:
        qs = qs.filter(event_type=event_type)
    return [row.payload for row in qs]


def _internal_client() -> APIClient:
    now = int(time.time())
    token = jwt.encode(
        {"iss": "feed", "aud": "graph-internal", "iat": now, "exp": now + 30},
        settings.TARA_INTERNAL_JWT_SECRET,
        algorithm="HS256",
    )
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


# ---- block() severs edges and emits the removal events ----------------------


def test_block_between_friends_emits_friendship_removed(client_for):
    a, b = _acct(), _acct()
    friendship = _befriend(a, b)
    OutboxEvent.objects.all().delete()

    assert client_for(a).post(reverse("graph:block", args=[b])).status_code == 204

    assert services.are_friends(a, b) is False
    assert not Friendship.objects.exists()
    removed = _envelopes("friendship.removed")
    assert len(removed) == 1
    low, high = sorted([a, b], key=uuid.UUID)
    # Feed's on_friendship_removed reads p["a"] and p["b"]; keep them as before.
    assert removed[0]["payload"] == {"a": low, "b": high, "reason": "block"}
    assert removed[0]["subject_id"] == str(friendship.id)
    assert removed[0]["actor_id"] == a


def test_block_emits_unfollow_for_each_follow_direction():
    a, b = _acct(), _acct()
    services.follow(a, b)
    services.follow(b, a)
    OutboxEvent.objects.all().delete()

    services.block(a, b)

    assert services.follows(a, b) is False
    assert services.follows(b, a) is False
    unfollowed = _envelopes("user.unfollowed")
    # Feed's on_user_unfollowed reads follower, target and target_type.
    assert sorted((e["payload"]["follower"], e["payload"]["target"]) for e in unfollowed) == sorted(
        [(a, b), (b, a)]
    )
    for envelope in unfollowed:
        assert envelope["payload"]["target_type"] == "user"
        assert envelope["payload"]["reason"] == "block"
        assert envelope["actor_id"] == a  # the blocker, even for b's severed follow
        assert envelope["subject_id"] == envelope["payload"]["target"]


def test_block_of_friend_follower_emits_everything_once_in_one_transaction():
    a, b = _acct(), _acct()
    _befriend(a, b)
    services.follow(a, b)
    services.follow(b, a)
    OutboxEvent.objects.all().delete()

    services.block(b, a)

    types = [e["event_type"] for e in _envelopes()]
    assert types[0] == "user.blocked"
    assert sorted(types) == sorted(
        ["user.blocked", "friendship.removed", "user.unfollowed", "user.unfollowed"]
    )
    blocked = _envelopes("user.blocked")[0]["payload"]
    assert blocked == {"blocker_id": b, "blocked_id": a}


def test_block_deletes_pending_request_without_friendship_removed():
    a, b = _acct(), _acct()
    services.send_friend_request(a, b)
    OutboxEvent.objects.all().delete()

    services.block(b, a)

    assert not Friendship.objects.exists()
    assert _envelopes("friendship.removed") == []
    assert [e["event_type"] for e in _envelopes()] == ["user.blocked"]


def test_reblock_is_idempotent_and_emits_nothing(client_for):
    a, b = _acct(), _acct()
    _befriend(a, b)
    services.block(a, b)
    before = OutboxEvent.objects.count()

    assert client_for(a).post(reverse("graph:block", args=[b])).status_code == 204

    assert OutboxEvent.objects.count() == before
    assert BlockRelation.objects.filter(blocker_id=a, blocked_id=b).count() == 1


def test_counter_block_emits_only_user_blocked():
    a, b = _acct(), _acct()
    _befriend(a, b)
    services.follow(a, b)
    services.block(b, a)  # severs everything
    OutboxEvent.objects.all().delete()

    services.block(a, b)

    assert [e["event_type"] for e in _envelopes()] == ["user.blocked"]


def test_block_keeps_unrelated_edges():
    a, b, c, page = _acct(), _acct(), _acct(), _acct()
    _befriend(a, c)
    services.follow(a, c)
    services.follow(a, page, "page")
    services.follow(b, c)
    OutboxEvent.objects.all().delete()

    services.block(a, b)

    assert services.are_friends(a, c) is True
    assert services.follows(a, c) is True
    assert services.follows(b, c) is True
    assert FollowRelation.objects.filter(follower_id=a, target_id=page).exists()
    assert [e["event_type"] for e in _envelopes()] == ["user.blocked"]


def test_unfriend_and_unfollow_carry_their_own_reason(client_for):
    a, b = _acct(), _acct()
    friendship = _befriend(a, b)
    services.follow(a, b)
    OutboxEvent.objects.all().delete()

    client_for(a).delete(reverse("graph:friend-delete", args=[b]))
    client_for(a).delete(reverse("graph:friend-delete", args=[b]))  # idempotent
    client_for(a).delete(reverse("graph:follow", args=[b]))
    client_for(a).delete(reverse("graph:follow", args=[b]))  # idempotent

    removed = _envelopes("friendship.removed")
    unfollowed = _envelopes("user.unfollowed")
    assert len(removed) == 1
    assert removed[0]["payload"]["reason"] == "unfriend"
    # Regression: the instance pk is None after delete(); the event used to
    # carry subject_id/partition_key "None".
    assert removed[0]["subject_id"] == str(friendship.id)
    assert removed[0]["partition_key"] == str(friendship.id)
    assert len(unfollowed) == 1
    assert unfollowed[0]["payload"] == {
        "follower": a,
        "target": b,
        "target_type": "user",
        "reason": "unfollow",
    }


def test_unfriend_leaves_a_pending_request_alone():
    a, b = _acct(), _acct()
    services.send_friend_request(a, b)
    OutboxEvent.objects.all().delete()

    services.unfriend(a, b)

    assert Friendship.objects.filter(status=Friendship.Status.PENDING).count() == 1
    assert _envelopes() == []


# ---- another account's lists: 404 for a blocked viewer -----------------------


@pytest.mark.parametrize("direction", BLOCK_DIRECTIONS)
@pytest.mark.parametrize("endpoint", LIST_ENDPOINTS)
def test_blocked_viewer_gets_404_on_every_list(client_for, endpoint, direction):
    viewer, owner, friend = _acct(), _acct(), _acct()
    _befriend(owner, friend)
    _befriend(viewer, friend)  # so mutual would otherwise disclose `friend`
    services.follow(friend, owner)
    _block(direction, viewer, owner)

    resp = client_for(viewer).get(reverse(endpoint, args=[owner]))

    assert resp.status_code == 404
    body = resp.json()
    assert "data" not in body
    assert body["error"]["code"] == "not_found"
    assert friend not in resp.content.decode()


@pytest.mark.parametrize("endpoint", LIST_ENDPOINTS)
def test_stale_block_row_alone_still_hides_lists(client_for, endpoint):
    """The gate reads the block table, not the (possibly stale) edges."""
    viewer, owner, friend = _acct(), _acct(), _acct()
    _befriend(owner, friend)
    _befriend(viewer, friend)
    _befriend(viewer, owner)
    _stale_block(owner, viewer)

    assert client_for(viewer).get(reverse(endpoint, args=[owner])).status_code == 404


@pytest.mark.parametrize("endpoint", LIST_ENDPOINTS)
def test_unrelated_viewer_and_owner_still_get_lists(client_for, endpoint):
    viewer, owner, friend, stranger = _acct(), _acct(), _acct(), _acct()
    _befriend(owner, friend)
    _befriend(viewer, friend)
    services.follow(friend, owner)
    services.block(owner, stranger)  # owner's block of someone else hides nothing

    resp = client_for(viewer).get(reverse(endpoint, args=[owner]))

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert friend in next(iter(data.values()))
    # The owner can always read their own lists.
    assert client_for(owner).get(reverse(endpoint, args=[owner])).status_code == 200


# ---- blocked accounts never appear in a list returned to the other party ----


@pytest.mark.parametrize("direction", BLOCK_DIRECTIONS)
def test_lists_of_a_third_account_hide_accounts_blocked_with_viewer(client_for, direction):
    viewer, owner, blocked, visible, other_viewer = _acct(), _acct(), _acct(), _acct(), _acct()
    for account in (blocked, visible):
        _befriend(owner, account)
        services.follow(account, owner)
    _block(direction, viewer, blocked)

    friends = client_for(viewer).get(reverse("graph:social-friends", args=[owner]))
    followers = client_for(viewer).get(reverse("graph:social-followers", args=[owner]))
    assert friends.status_code == followers.status_code == 200
    assert friends.json()["data"]["friends"] == [visible]
    assert followers.json()["data"]["followers"] == [visible]

    # Nobody else is affected: another viewer and the owner still see both.
    for client in (client_for(other_viewer), client_for(owner)):
        seen = client.get(reverse("graph:social-friends", args=[owner])).json()["data"]
        assert sorted(seen["friends"]) == sorted([blocked, visible])
    assert sorted(services.list_friend_ids(owner)) == sorted([blocked, visible])


@pytest.mark.parametrize("direction", BLOCK_DIRECTIONS)
def test_lists_hide_accounts_blocked_with_the_owner_even_if_edges_are_stale(client_for, direction):
    """A block row without severed edges (a race) is still honoured for every
    viewer: the owner's blocked partner never appears in the owner's lists."""
    owner, partner, viewer = _acct(), _acct(), _acct()
    _befriend(owner, partner)
    services.follow(partner, owner)
    if direction == "viewer_blocked_other":
        _stale_block(owner, partner)
    else:
        _stale_block(partner, owner)

    for client in (client_for(viewer), client_for(owner)):
        assert client.get(reverse("graph:social-friends", args=[owner])).json()["data"] == {
            "friends": []
        }
        assert client.get(reverse("graph:social-followers", args=[owner])).json()["data"] == {
            "followers": []
        }


def test_mutual_hides_shared_friends_blocked_with_either_side(client_for):
    viewer, owner, shared, blocks_viewer, blocked_by_owner = (
        _acct(),
        _acct(),
        _acct(),
        _acct(),
        _acct(),
    )
    for account in (shared, blocks_viewer, blocked_by_owner):
        _befriend(viewer, account)
        _befriend(owner, account)
    # Stale rows: the edges are still there, only the block table says no.
    _stale_block(blocks_viewer, viewer)
    _stale_block(owner, blocked_by_owner)

    resp = client_for(viewer).get(reverse("graph:social-mutual", args=[owner]))

    assert resp.status_code == 200
    assert resp.json()["data"] == {"mutual": [shared]}


def test_mutual_is_sorted_intersection_for_unblocked_pair(client_for):
    viewer, owner, s1, s2, only_owner = _acct(), _acct(), _acct(), _acct(), _acct()
    for account in (s1, s2):
        _befriend(viewer, account)
        _befriend(owner, account)
    _befriend(owner, only_owner)

    resp = client_for(viewer).get(reverse("graph:social-mutual", args=[owner]))

    assert resp.json()["data"] == {"mutual": sorted([s1, s2])}


# ---- own lists and requests: stale edges never surface ----------------------


def test_own_lists_hide_blocked_partner_with_stale_edges(client_for):
    me, partner, page, kept = _acct(), _acct(), _acct(), _acct()
    _befriend(me, partner)
    services.follow(me, partner)
    services.follow(partner, me)
    services.follow(me, page, "page")
    services.follow(me, kept)
    _stale_block(partner, me)

    client = client_for(me)
    assert client.get(reverse("graph:friend-list")).json()["data"] == {"friends": []}
    assert client.get(reverse("graph:followers")).json()["data"] == {"followers": []}
    following = client.get(reverse("graph:following")).json()["data"]["following"]
    assert sorted((f["target_id"], f["target_type"]) for f in following) == sorted(
        [(page, "page"), (kept, "user")]
    )

    # The same holds for the blocker's own lists.
    other = client_for(partner)
    assert other.get(reverse("graph:friend-list")).json()["data"] == {"friends": []}
    assert other.get(reverse("graph:following")).json()["data"] == {"following": []}


def test_requests_list_hides_requests_across_a_block(client_for):
    a, b, c = _acct(), _acct(), _acct()
    services.send_friend_request(a, b)
    services.send_friend_request(c, b)
    _stale_block(b, a)

    incoming = client_for(b).get(reverse("graph:friend-requests")).json()["data"]
    outgoing = (
        client_for(a)
        .get(reverse("graph:friend-requests"), {"direction": "outgoing"})
        .json()["data"]
    )
    assert [row["requested_by"] for row in incoming] == [c]
    assert outgoing == []


def test_accepting_a_request_across_a_block_is_404(client_for):
    a, b = _acct(), _acct()
    request = services.send_friend_request(a, b)
    _stale_block(a, b)  # the request raced the block
    OutboxEvent.objects.all().delete()

    resp = client_for(b).post(reverse("graph:friend-accept", args=[request.id]))

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"
    assert services.are_friends(a, b) is False
    assert _envelopes("friendship.accepted") == []


# ---- internal fan-out audience ----------------------------------------------


def test_fanout_audience_excludes_accounts_blocked_with_author():
    author, follower, friend, blocked_follower, blocking_friend = (
        _acct(),
        _acct(),
        _acct(),
        _acct(),
        _acct(),
    )
    services.follow(follower, author)
    _befriend(author, friend)
    services.follow(blocked_follower, author)
    _befriend(author, blocking_friend)
    _stale_block(author, blocked_follower)
    _stale_block(blocking_friend, author)

    resp = _internal_client().get(reverse("fanout-audience", args=[author]))

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["followers"] == [follower]
    assert data["friends"] == [friend]
    assert data["recipients"] == sorted([follower, friend])
