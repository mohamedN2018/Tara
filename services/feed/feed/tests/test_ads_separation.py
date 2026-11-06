"""WP 4.9: ad slots come from the config (``ads.slots``, default ``[4]``) and ads
never touch the organic order (02 section 18)."""

import uuid
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from intel import config

from feed import views
from feed.models import Affinity, FeedItem, RelationshipFlag

pytestmark = pytest.mark.django_db

MODES = ("for_you", "following", "friends", "favorites", "recent")


def _acct() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def world():
    viewer, friend, fav = _acct(), _acct(), _acct()
    for m in range(30):
        author, reason = (friend, "friend") if m % 3 else (fav, "follow")
        post_id = str(uuid.uuid4())
        FeedItem.objects.create(
            recipient_id=viewer,
            post_id=post_id,
            author_id=author,
            reason=reason,
            snapshot={"post_id": post_id, "author_id": author, "audience": "public"},
            post_created_at=timezone.now() - timedelta(minutes=m * 7),
        )
    RelationshipFlag.objects.create(
        actor_id=viewer, target_id=fav, kind="favorite", occurred_at=timezone.now()
    )
    Affinity.objects.create(account_id=viewer, author_id=friend, interactions=9)
    return viewer


def _ads_on(monkeypatch, n_creatives=5):
    served = iter(range(10_000))

    def fake(viewer):
        i = next(served)
        return {"creative_id": f"c{i % n_creatives}", "headline": "Ad", "sponsored": True}

    monkeypatch.setattr("feed.ads_client.feed_sponsored", fake)


def _ads_off(monkeypatch):
    monkeypatch.setattr("feed.ads_client.feed_sponsored", lambda v: None)


def _slots(monkeypatch, slots):
    real = config.for_surface

    def patched(surface, overrides=None):
        if surface == "home":
            overrides = {**(overrides or {}), "ads": {"slots": slots}}
        return real(surface, overrides)

    monkeypatch.setattr(views.config, "for_surface", patched)


def _organic(client, mode):
    ids, cursor = [], None
    for _ in range(20):
        params = {"mode": mode, "limit": 8}
        if cursor:
            params["cursor"] = cursor
        body = client.get(reverse("feed:home-feed"), params).json()
        ids += [i["post_id"] for i in body["data"]]
        cursor = body["page"]["next_cursor"]
        if not cursor:
            break
    return ids


def test_default_config_is_one_slot_at_index_four():
    assert config.for_surface("home").get("ads.slots") == [4]
    assert views.ad_slots() == [4]


@pytest.mark.parametrize("mode", MODES)
def test_organic_order_is_identical_with_ads_on_and_off(client_for, world, monkeypatch, mode):
    client = client_for(world)
    _ads_off(monkeypatch)
    off = _organic(client, mode)
    _ads_on(monkeypatch)
    on = _organic(client, mode)
    assert off and on == off


def test_first_page_meta_names_the_slots_and_one_ad(client_for, world, monkeypatch):
    _ads_on(monkeypatch)
    body = client_for(world).get(reverse("feed:home-feed"), {"mode": "recent"}).json()
    assert body["meta"]["ad_slots"] == [4]
    assert body["sponsored"]["creative_id"] == "c0"
    assert [a["creative_id"] for a in body["sponsored_slots"]] == ["c0"]
    assert all(not i.get("sponsored") for i in body["data"])  # ads stay out of `data`


def test_later_pages_carry_no_ads(client_for, world, monkeypatch):
    _ads_on(monkeypatch)
    client = client_for(world)
    first = client.get(reverse("feed:home-feed"), {"mode": "recent", "limit": 5}).json()
    second = client.get(
        reverse("feed:home-feed"), {"mode": "recent", "cursor": first["page"]["next_cursor"]}
    ).json()
    assert "sponsored" not in second
    # A later page's meta is the delivery block only (WP 4c.2-B3): no ad slots.
    assert set(second["meta"]) == {"delivery"}


def test_two_slots_only_when_the_config_says_so(client_for, world, monkeypatch):
    _ads_on(monkeypatch)
    _slots(monkeypatch, [14, 4, 4, -1])
    body = client_for(world).get(reverse("feed:home-feed"), {"mode": "recent"}).json()
    assert body["meta"]["ad_slots"] == [4, 14]  # sorted, distinct, non-negative
    assert [a["creative_id"] for a in body["sponsored_slots"]] == ["c0", "c1"]


def test_the_same_creative_never_fills_two_slots(client_for, world, monkeypatch):
    _ads_on(monkeypatch, n_creatives=1)
    _slots(monkeypatch, [4, 14])
    body = client_for(world).get(reverse("feed:home-feed"), {"mode": "recent"}).json()
    assert [a["creative_id"] for a in body["sponsored_slots"]] == ["c0"]


def test_no_slots_means_no_ads_call(client_for, world, monkeypatch):
    calls = []
    monkeypatch.setattr("feed.ads_client.feed_sponsored", lambda v: calls.append(v))
    _slots(monkeypatch, [])
    body = client_for(world).get(reverse("feed:home-feed"), {"mode": "recent"}).json()
    assert calls == [] and body["sponsored"] is None and body["meta"]["ad_slots"] == []


def test_ads_outage_still_serves_organic(client_for, world, monkeypatch):
    _ads_off(monkeypatch)
    body = client_for(world).get(reverse("feed:home-feed"), {"mode": "for_you"}).json()
    assert body["data"] and body["sponsored"] is None and body["sponsored_slots"] == []
