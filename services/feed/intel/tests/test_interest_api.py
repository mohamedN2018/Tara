"""04 WP 6.4 / 07 WP 8.5-B2: ``/api/v1/feed/preferences/profile/``.

The owner sees their rows by tier (explicit, emerging, short, medium, long, negative)
with counts by event type and **no item ids**; muted topics and hidden creators are
listed apart; deleting an inferred row suppresses it (it does not come straight back);
deleting a mute or a hide undoes it; ``post_report`` counts are the viewer's own and
never name a reporter; another account sees none of it."""

import json
from datetime import timedelta

import pytest
from django.utils import timezone
from feed.models import OutboxEvent

from intel.models import UserInterest

from . import r4
from . import world as w

pytestmark = pytest.mark.django_db
URL = "/api/v1/feed/preferences/profile/"


def test_tiers_counts_and_no_item_ids(client_for):
    ids = r4.seed()
    viewer, creator = w.uid(), w.uid()
    long_ago = timezone.now() - timedelta(days=60)
    r4.inferred(viewer, "topic", ids["history"], 6.0, at=long_ago)  # long
    r4.inferred(viewer, "topic", ids["gaming"], 2.0)  # recent: short (or emerging)
    row = r4.inferred(viewer, "topic", ids["books"], -3.0)  # negative
    UserInterest.objects.filter(pk=row.pk)
    r4.explicit(viewer, "topic", ids["travel"], "like")
    r4.explicit(viewer, "topic", ids["politics"], "muted")
    r4.explicit(viewer, "creator", creator, "hidden")
    UserInterest.objects.filter(account_id=viewer, key=str(ids["history"])).update(
        counts={"post_like": 6, "post_report": 1}
    )
    data = client_for(viewer).get(URL).json()["data"]
    tiers = data["tiers"]
    assert [r["key"] for r in tiers["explicit"]] == ["travel"]
    assert [r["key"] for r in tiers["long"]] == ["history"]
    assert [r["key"] for r in tiers["negative"]] == ["books"]
    assert ["gaming"] in ([r["key"] for r in tiers["short"]], [r["key"] for r in tiers["emerging"]])
    assert tiers["long"][0]["counts"] == {"post_like": 6, "post_report": 1}
    assert data["muted_topics"] == [
        {"slug": "politics", "label_ar": "سياسة", "label_en": "Politics"}
    ]
    assert data["hidden_creators"][0]["account_id"] == creator
    assert data["sensitive_inference"] is False
    text = json.dumps(data)
    for t in ("post_id", "item_id", "reporter"):
        assert t not in text
    other = client_for(w.uid()).get(URL).json()["data"]
    assert all(v == [] for v in other["tiers"].values()) and other["muted_topics"] == []


def test_delete_suppresses_an_inferred_row_and_undoes_mutes_and_hides(client_for):
    ids = r4.seed()
    viewer, creator = w.uid(), w.uid()
    r4.inferred(viewer, "topic", ids["history"], 6.0)
    r4.explicit(viewer, "topic", ids["politics"], "muted")
    r4.explicit(viewer, "creator", creator, "hidden")
    client = client_for(viewer)
    assert client.delete(f"{URL}topic/history/").status_code == 204
    assert r4.rows(viewer)[0:1] == [("creator", creator, "explicit", "hidden")]
    assert ("topic", str(ids["history"]), "explicit", "suppressed") in r4.rows(viewer)
    assert client.get(URL).json()["data"]["tiers"]["long"] == []
    assert client.delete(f"{URL}topic/history/").status_code == 404  # nothing left to delete
    assert client.delete(f"{URL}topic/politics/").status_code == 204
    assert client.delete(f"{URL}creator/{creator}/").status_code == 204
    events = OutboxEvent.objects.filter(event_type="intel.creator.hidden")
    assert [e.payload["payload"]["hidden"] for e in events] == [False]
    assert client.delete(f"{URL}nope/x/").status_code == 404
    assert client.delete(f"{URL}topic/no-such-topic/").status_code == 404


def test_post_adds_an_explicit_topic_row(client_for):
    r4.seed()
    viewer = w.uid()
    client = client_for(viewer)
    resp = client.post(URL, {"dim": "topic", "key": "cooking", "polarity": "like"}, format="json")
    assert resp.status_code == 201
    assert resp.json()["data"]["key"] == "cooking" and resp.json()["data"]["source"] == "explicit"
    assert (
        client.post(
            URL, {"dim": "creator", "key": "x", "polarity": "like"}, format="json"
        ).status_code
        == 400
    )
    assert (
        client.post(
            URL, {"dim": "topic", "key": "cooking", "polarity": "hidden"}, format="json"
        ).status_code
        == 400
    )
    topics = client.get("/api/v1/feed/topics/", {"q": "طبخ"}).json()["data"]
    assert topics[0]["slug"] == "cooking" and topics[0]["sensitive"] is False
    assert len(client.get("/api/v1/feed/topics/", {"limit": 5}).json()["data"]) == 5
