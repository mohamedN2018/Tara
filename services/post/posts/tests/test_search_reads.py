"""What search reads from post (roadmap 1.15): the additive ``post.updated``
fields, an event's indexable state, and the backfill exports."""

import time
import uuid

import jwt
import pytest
from django.conf import settings
from django.urls import reverse
from gatherings import services as gatherings
from gatherings.tests.conftest import make_event
from rest_framework.test import APIClient

from posts import services
from posts.models import OutboxEvent, Post

pytestmark = pytest.mark.django_db


def acct() -> str:
    return str(uuid.uuid4())


def _internal(audience="post-internal") -> APIClient:
    now = int(time.time())
    token = jwt.encode(
        {"iss": "search", "aud": audience, "iat": now, "exp": now + 30},
        settings.TARA_INTERNAL_JWT_SECRET,
        algorithm="HS256",
    )
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


def test_post_updated_carries_type_media_and_date():
    author = acct()
    post = services.create_post(author, body="hello #world", audience="friends")
    services.edit_post(author, str(post.id), audience="public")
    row = OutboxEvent.objects.filter(event_type="post.updated").latest("created_at")
    payload = row.payload["payload"]
    assert payload["type"] == post.type
    assert payload["author_type"] == "user"
    assert payload["media_ids"] == []
    assert payload["created_at"] == Post.objects.get(id=post.id).created_at.isoformat()


def test_event_state_shows_text_only_for_a_public_live_event():
    host = acct()
    public = make_event(host, title="Iftar", location="Al-Azhar Park")
    friends = make_event(host, title="Secret dinner", audience="friends")
    client = _internal()

    state = client.get(reverse("search-gathering-state", args=[public.id])).json()["data"]
    assert state["indexable"] is True
    assert state["title"] == "Iftar" and state["location"] == "Al-Azhar Park"
    assert state["updated_at"]

    hidden = client.get(reverse("search-gathering-state", args=[friends.id])).json()["data"]
    assert hidden == {
        "gathering_id": str(friends.id),
        "indexable": False,
        "updated_at": hidden["updated_at"],
    }

    gatherings.cancel_gathering(host, public.id)
    state = client.get(reverse("search-gathering-state", args=[public.id])).json()["data"]
    assert state["indexable"] is False and "title" not in state

    assert client.get(reverse("search-gathering-state", args=[uuid.uuid4()])).status_code == 404


def test_deleted_event_is_not_indexable():
    host = acct()
    g = make_event(host)
    gatherings.delete_gathering(host, g.id)
    state = _internal().get(reverse("search-gathering-state", args=[g.id])).json()["data"]
    assert state["indexable"] is False


def test_exports_list_only_public_live_content():
    author = acct()
    shown = services.create_post(author, body="public #tag", audience="public")
    services.create_post(author, body="friends only", audience="friends")
    gone = services.create_post(author, body="deleted", audience="public")
    services.delete_post(author, str(gone.id))
    host = acct()
    event = make_event(host)
    make_event(host, audience="friends")

    client = _internal()
    posts = client.get(reverse("search-export-posts")).json()["data"]
    assert [i["id"] for i in posts["items"]] == [str(shown.id)]
    assert posts["items"][0]["payload"]["hashtags"] == ["tag"]
    assert posts["items"][0]["payload"]["audience"] == "public"

    events = client.get(reverse("search-export-gatherings")).json()["data"]["items"]
    assert [i["id"] for i in events] == [str(event.id)]
    assert events[0]["payload"]["indexable"] is True


def test_search_reads_require_an_internal_token():
    g = make_event(acct())
    assert APIClient().get(reverse("search-gathering-state", args=[g.id])).status_code == 401
    wrong = _internal("graph-internal")
    assert wrong.get(reverse("search-export-posts")).status_code == 401
