"""04 WP 8.1 (decision 17): the debug consent. 24 h expiry (``retention.debug_consent_ttl_h``),
revoke, shown in the preferences body, purged after 90 days."""

from datetime import timedelta

import pytest
from django.utils import timezone

from intel import config, preferences, retention
from intel.models import DebugConsent

from . import world as w

pytestmark = pytest.mark.django_db
URL = "/api/v1/feed/preferences/debug-consent/"


def test_grant_expires_in_24h_and_revoke(client_for):
    viewer = w.uid()
    client = client_for(viewer)
    resp = client.post(URL)
    assert resp.status_code == 201
    row = DebugConsent.objects.get(account_id=viewer)
    assert timedelta(hours=23, minutes=59) < row.expires_at - row.granted_at <= timedelta(hours=24)
    body = client.get("/api/v1/feed/preferences/").json()["data"]
    assert body["debug_consent_expires_at"] == row.expires_at.isoformat()
    assert client.delete(URL).status_code == 204
    assert DebugConsent.objects.get(account_id=viewer).revoked_at is not None
    assert preferences.active_consent(viewer) is None


def test_an_expired_consent_is_not_active_and_old_rows_are_purged():
    viewer = w.uid()
    old = preferences.grant_consent(viewer, now=timezone.now() - timedelta(days=2))
    assert preferences.active_consent(viewer) is None
    DebugConsent.objects.filter(pk=old.pk).update(granted_at=timezone.now() - timedelta(days=91))
    fresh = preferences.grant_consent(viewer)
    out = retention.purge(config.for_surface("home"))
    assert out["intel_debug_consent"] == 1
    assert list(DebugConsent.objects.filter(account_id=viewer).values_list("id", flat=True)) == [
        fresh.id
    ]
