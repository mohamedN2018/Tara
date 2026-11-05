"""WP 2.1: the intel app is installed, migrates, and leaves feed's endpoints alone."""

import pytest
from django.apps import apps
from django.db import connection
from django.urls import resolve, reverse

pytestmark = pytest.mark.django_db


def test_app_is_installed():
    assert apps.get_app_config("intel").verbose_name == "Tara Intelligence"


def test_tables_exist_and_telemetry_is_partitioned():
    with connection.cursor() as cur:
        cur.execute(
            "SELECT c.relname, c.relkind FROM pg_class c WHERE c.relname = ANY(%s)",
            [
                [
                    "intel_signal_event",
                    "intel_user_item_engagement",
                    "intel_signal_batch",
                    "intel_synthetic_account",
                ]
            ],
        )
        kinds = dict(cur.fetchall())
    # 'p' = partitioned table, 'r' = ordinary table
    assert kinds == {
        "intel_signal_event": "p",
        "intel_user_item_engagement": "p",
        "intel_signal_batch": "r",
        "intel_synthetic_account": "r",
    }


def test_existing_feed_endpoints_unchanged():
    expected = {
        "feed:home-feed": "/api/v1/feed/",
        "feed:hide": "/api/v1/feed/hide/",
        "feed:snooze": "/api/v1/feed/snooze/",
        "feed:snoozes": "/api/v1/feed/snoozes/",
    }
    for name, path in expected.items():
        assert reverse(name) == path
        assert resolve(path).url_name == name.split(":")[1]


def test_signals_route_is_intel():
    assert reverse("intel:signals") == "/api/v1/feed/signals/"
    assert resolve("/api/v1/feed/signals/").namespace == "intel"


def test_consumer_registers_intel_handlers():
    import intel.handlers  # noqa: F401
    from tara_events.dispatch import handlers_for

    for event_type in ("post.reacted", "user.blocked", "account.deleted"):
        names = [fn.__name__ for fn in handlers_for(event_type)]
        assert any(n.startswith("intel_") for n in names), event_type
