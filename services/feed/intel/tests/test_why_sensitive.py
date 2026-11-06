"""07 WP 7.6-B2: the new reason codes and the sensitive guard.

- the session's factor codes become the new codes: ``new_since_visit``,
  ``rec_new_activity``, ``rec_similar_watched`` (a video), ``rec_topic`` /
  ``rec_adjacent_topic`` (a topic the profile likes, or a sibling of one),
  ``rec_community_popular`` (a group item lifted by engagement, never naming the group);
- golden: an item in a sensitive topic never carries ``rec_similar_watched``,
  ``continue_watching`` or ``rec_new_activity`` without the decision-12 opt-in
  (``rec_generic`` instead), a sensitive topic is never named, and no reason string
  contains a group id or name.
"""

import json
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from feed import ranking
from feed.models import FeedItem

from intel import why
from intel.models import UserPreference
from intel.ranking import explain
from intel.ranking import session as rank_session

from . import r4
from . import world as w

pytestmark = pytest.mark.django_db


def _session(viewer, post_id, source, reason, factor_names):
    factors = tuple((explain.CODE[n], 10) for n in factor_names)
    entries = [rank_session.Entry(post_id, source, reason, factors)]
    session = {
        "sid": "s" * 32,
        "surface": "home",
        "cfg": "home@7",
        "items": rank_session.pack(entries),
        "n": 1,
        "edge": None,
        "cu": None,
        "as_of": timezone.now().isoformat(),
    }
    assert rank_session.save("home", viewer, session, 600, ranking._hot())  # noqa: SLF001


def _connected(viewer, *, type="text"):  # noqa: A002
    author = w.uid()
    p = w.post(author, type=type)
    FeedItem.objects.create(
        recipient_id=viewer,
        post_id=p,
        author_id=author,
        reason="friend",
        snapshot={"post_id": p, "author_id": author, "type": type},
        post_created_at=timezone.now() - timedelta(minutes=5),
    )
    return p, author


def _codes(client, post_id):
    resp = client.get(reverse("intel:why", args=["post", post_id]))
    assert resp.status_code == 200, resp.content
    return [f["code"] for f in resp.json()["data"]["factors"]], resp.json()


def test_new_codes_from_the_session_factors(client_for):
    ids = r4.seed()
    viewer = w.uid()
    client = client_for(viewer)
    p, _ = _connected(viewer)
    r4.tag(p, (ids["cooking"], 0.9))
    r4.explicit(viewer, "topic", ids["food"], "like")  # cooking's parent: a sibling liked
    _session(viewer, p, "connections", "friend", ["new_since_visit", "rec_new_activity"])
    codes, _ = _codes(client, p)
    assert codes[0] == "friend"
    assert {"new_since_visit", "rec_new_activity"} <= set(codes)
    # ``why.max_factors`` (3) keeps the relationship and two terms: one term at a time.
    _session(viewer, p, "connections", "friend", ["interest"])
    codes, _ = _codes(client, p)
    assert "rec_adjacent_topic" in codes
    r4.explicit(viewer, "topic", ids["cooking"], "like")
    codes, body = _codes(client, p)
    assert {"code": "rec_topic", "topic": "cooking"} in body["data"]["factors"]
    video, _ = _connected(viewer, type="video")
    _session(viewer, video, "connections", "friend", ["interest"])
    from intel.models import ContentRef

    ContentRef.objects.filter(post_id=video).update(type="video")
    codes, _ = _codes(client, video)
    assert set(codes) <= set(why.CODES)


def test_sensitive_item_never_carries_history_codes_without_opt_in(client_for):
    ids = r4.seed()
    viewer = w.uid()
    client = client_for(viewer)
    p, _ = _connected(viewer)
    r4.tag(p, (ids["politics"], 0.9))
    r4.explicit(viewer, "topic", ids["politics"], "like")
    _session(viewer, p, "connections", "friend", ["rec_new_activity", "interest"])
    codes, body = _codes(client, p)
    assert "rec_new_activity" not in codes and "rec_similar_watched" not in codes
    assert "rec_generic" in codes
    assert "politics" not in json.dumps(body, ensure_ascii=False)  # never named
    assert {"code": "rec_topic_sensitive"} in body["data"]["factors"]
    # With the opt-in, the history code is shown (the topic is still masked).
    UserPreference.objects.create(account_id=viewer, sensitive_inference=True)
    codes, body = _codes(client, p)
    assert "rec_new_activity" in codes
    assert "politics" not in json.dumps(body, ensure_ascii=False)


def test_group_items_never_name_the_group(client_for):
    viewer, author = w.uid(), w.uid()
    group = w.group(owner=w.uid())
    w.member(viewer, group)
    p = w.post(author, group=group, audience="group")
    _session(viewer, p, "groups", "group", ["engagement", "shared_groups"])
    codes, body = _codes(client_for(viewer), p)
    assert "rec_community_popular" in codes and codes[0] == "group_member"
    assert group not in json.dumps(body)


def test_every_code_is_in_the_published_list():
    assert len(why.NEW_CODES) == 7
    assert set(why.NEW_CODES) <= set(why.CODES)
    assert why.HISTORY_CODES == {"rec_similar_watched", "continue_watching", "rec_new_activity"}
