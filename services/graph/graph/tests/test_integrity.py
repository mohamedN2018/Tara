"""Review fixes: accepting a request that changed under the caller, and bad input
on the internal relationship endpoint."""

import time
import uuid

import jwt
import pytest
from django.conf import settings
from django.urls import reverse
from rest_framework.test import APIClient

from graph import services
from graph.models import Friendship, OutboxEvent
from tara_common.exceptions import TaraAPIError

pytestmark = pytest.mark.django_db


def _acct() -> str:
    return str(uuid.uuid4())


def _accepted_events() -> int:
    return OutboxEvent.objects.filter(event_type="friendship.accepted").count()


def _stale_pending(monkeypatch, friendship_id: str) -> None:
    """Make ``accept`` work from the pending row as it was read before a racer."""
    stale = Friendship.objects.get(id=friendship_id)
    monkeypatch.setattr(services, "_load_pending", lambda _id: stale)


def test_a_second_accept_from_a_stale_read_is_404_and_emits_once(monkeypatch):
    a, b = _acct(), _acct()
    request = services.send_friend_request(a, b)
    _stale_pending(monkeypatch, str(request.id))
    services.accept_friend_request(b, str(request.id))

    with pytest.raises(TaraAPIError) as exc:
        services.accept_friend_request(b, str(request.id))  # a double click
    assert exc.value.http_status == 404
    assert _accepted_events() == 1


def test_accepting_a_request_a_block_deleted_meanwhile_is_404(monkeypatch):
    a, b = _acct(), _acct()
    request = services.send_friend_request(a, b)
    _stale_pending(monkeypatch, str(request.id))
    # The block deletes the pending request; the accept read it just before.
    services.block(a, b)
    monkeypatch.setattr(services, "is_blocked", lambda x, y: False)  # read before the block

    with pytest.raises(TaraAPIError) as exc:
        services.accept_friend_request(b, str(request.id))
    assert exc.value.http_status == 404
    assert not Friendship.objects.exists()
    assert _accepted_events() == 0


def _internal_client() -> APIClient:
    now = int(time.time())
    token = jwt.encode(
        {"iss": "post", "aud": "graph-internal", "iat": now, "exp": now + 30},
        settings.TARA_INTERNAL_JWT_SECRET,
        algorithm="HS256",
    )
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


@pytest.mark.parametrize(
    "params", [{"a": "nope", "b": str(uuid.uuid4())}, {"a": str(uuid.uuid4())}, {}]
)
def test_internal_relationship_rejects_non_uuids_with_400(params):
    resp = _internal_client().get(reverse("relationship"), params)
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "validation_error"
