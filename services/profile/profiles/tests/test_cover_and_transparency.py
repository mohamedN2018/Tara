"""Plan 08, profile track: the cover's vertical position (drag to reposition)
and Page transparency (created date, category, name history)."""

import uuid

import pytest
from django.urls import reverse

from profiles import page_graph, services
from profiles.clients import Relationship
from profiles.models import BlockedPair, OutboxEvent, Page, PageMember, PageNameChange
from tara_resilience import CircuitBreaker

pytestmark = pytest.mark.django_db


def _acct() -> str:
    return str(uuid.uuid4())


@pytest.fixture(autouse=True)
def _no_graph(monkeypatch):
    """Pages ask graph for follow counts; down here, so they stay unknown."""
    monkeypatch.setattr(page_graph, "_breaker", CircuitBreaker(name="page-graph-cover-test"))
    monkeypatch.setattr(page_graph, "page_stats", lambda *a, **k: {})
    monkeypatch.setattr("profiles.privacy.get_relationship", lambda a, b: Relationship())


# ---- cover_offset_y -----------------------------------------------------------


def test_cover_offset_defaults_to_centre_and_is_saved(auth_client):
    owner = _acct()
    services.ensure_profile(owner)
    client = auth_client(owner)
    me = reverse("profiles:me")
    assert client.get(me).json()["data"]["cover_offset_y"] == 50
    resp = client.patch(me, {"cover_offset_y": 20}, format="json")
    assert resp.status_code == 200
    assert resp.json()["data"]["cover_offset_y"] == 20
    event = OutboxEvent.objects.filter(event_type="profile.updated").latest("created_at")
    assert "cover_offset_y" in event.payload["payload"]["changed"]


@pytest.mark.parametrize("value", [-1, 101, "top"])
def test_cover_offset_outside_0_to_100_is_refused(auth_client, value):
    owner = _acct()
    services.ensure_profile(owner)
    resp = auth_client(owner).patch(
        reverse("profiles:me"), {"cover_offset_y": value}, format="json"
    )
    assert resp.status_code == 400


def test_visitors_get_the_cover_offset(auth_client):
    owner = _acct()
    profile = services.ensure_profile(owner)
    profile.cover_offset_y = 73
    profile.save()
    data = auth_client(_acct()).get(reverse("profiles:public-profile", args=[profile.handle]))
    assert data.json()["data"]["cover_offset_y"] == 73


# ---- page transparency ----------------------------------------------------------


def _page(owner=None, **kw) -> Page:
    owner = owner or _acct()
    data = {"handle": f"p{uuid.uuid4().hex[:10]}", "name": "Nile Books", **kw}
    return services.create_page(owner, data)


def _transparency(client, page):
    return client.get(reverse("profiles:page-transparency", args=[page.id]))


def test_a_rename_is_recorded_in_the_same_write(auth_client):
    owner = _acct()
    page = _page(owner, category="Books")
    detail = reverse("profiles:page-detail", args=[page.id])
    client = auth_client(owner)
    assert client.patch(detail, {"name": "Nile Readers"}, format="json").status_code == 200
    assert client.patch(detail, {"description": "same name"}, format="json").status_code == 200
    assert client.patch(detail, {"name": "Nile Readers"}, format="json").status_code == 200
    rows = list(PageNameChange.objects.filter(page=page))
    assert [(r.old_name, r.new_name) for r in rows] == [("Nile Books", "Nile Readers")]

    data = _transparency(auth_client(_acct()), page).json()["data"]
    assert data["category"] == "Books"
    assert data["name"] == "Nile Readers"
    assert data["created_at"]
    assert [(c["old_name"], c["new_name"]) for c in data["name_changes"]] == [
        ("Nile Books", "Nile Readers")
    ]
    assert "changed_by" not in data["name_changes"][0]  # who renamed it stays private


def test_a_refused_rename_records_nothing(auth_client):
    page = _page()
    analyst = _acct()
    PageMember.objects.create(page=page, account_id=analyst, role="analyst")
    resp = auth_client(analyst).patch(
        reverse("profiles:page-detail", args=[page.id]), {"name": "Taken over"}, format="json"
    )
    assert resp.status_code == 403
    assert not PageNameChange.objects.exists()


def test_transparency_of_a_hidden_page_is_404(auth_client):
    owner = _acct()
    draft = _page(owner)
    Page.objects.filter(id=draft.id).update(status=Page.Status.DRAFT)
    assert _transparency(auth_client(_acct()), draft).status_code == 404
    assert _transparency(auth_client(owner), draft).status_code == 200  # the team still sees it

    blocked = _acct()
    page = _page(owner)
    BlockedPair.objects.create(blocker_id=owner, blocked_id=blocked)
    assert _transparency(auth_client(blocked), page).status_code == 404
    assert _transparency(auth_client(_acct()), Page(id=uuid.uuid4())).status_code == 404
