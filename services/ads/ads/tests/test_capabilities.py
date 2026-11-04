"""Ad review follows the ``ads.review`` capability (8.12); decisions feed the audit log."""

import uuid

import pytest
from django.urls import reverse

from ads.models import OutboxEvent

pytestmark = pytest.mark.django_db


def _acct() -> str:
    return str(uuid.uuid4())


@pytest.mark.parametrize(
    ("roles", "caps", "status"),
    [
        (["ad_reviewer"], None, 200),  # token from before caps: role defaults
        (["admin"], None, 200),
        (["moderator"], None, 403),
        (["ad_reviewer"], [], 403),  # caps present: they win over roles
        (["analyst"], ["ads.review"], 200),  # granted through the matrix
    ],
)
def test_review_queue_follows_capabilities(client_for, roles, caps, status):
    resp = client_for(_acct(), roles=roles, caps=caps).get(reverse("ads:review-queue"))
    assert resp.status_code == status


def test_a_review_decision_carries_the_reviewer_and_request_id(client_for, settings):
    from ads.tests.test_ads import _make_active_creative

    settings.ADS_AUTO_APPROVE = False
    _campaign, creative = _make_active_creative(_acct())
    reviewer = _acct()
    resp = client_for(reviewer, caps=["ads.review"]).post(
        reverse("ads:review", args=[creative.id]),
        {"decision": "rejected", "notes": "Misleading claim"},
        format="json",
        HTTP_X_REQUEST_ID="edge-ad1",
    )
    assert resp.status_code == 200
    event = OutboxEvent.objects.get(event_type="ad.review.decided")
    assert event.payload["actor_id"] == reviewer
    assert event.correlation_id == "edge-ad1"
    assert event.payload["payload"] == {"creative_id": str(creative.id), "decision": "rejected"}
