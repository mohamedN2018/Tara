"""04 WP 8.1: ``GET/PATCH /api/v1/feed/preferences/`` and ``POST .../undo/``.

Every field is validated; PATCH takes any subset plus ``version`` (a stale one is
409); every change writes an ``intel_preference_change`` row and can be undone; the
import path ``intel.preferences`` of WP 4.6 still works."""

import pytest

from intel import preferences
from intel.models import PreferenceChange, UserPreference

from . import world as w

pytestmark = pytest.mark.django_db
URL = "/api/v1/feed/preferences/"


def test_get_body_has_every_field(client_for):
    data = client_for(w.uid()).get(URL).json()["data"]
    assert set(data) == {
        "default_mode",
        "discovery_level",
        "languages",
        "formats",
        "discovery_prefs",
        "sensitive_inference",
        "personalization_off",
        "search_signal",
        "onboarded_at",
        "reset_at",
        "reset_available_at",
        "debug_consent_expires_at",
        "version",
    }
    assert data["discovery_prefs"]["other_languages"] is False
    assert data["discovery_prefs"]["people_suggestions"] is True


def test_patch_subset_version_and_undo(client_for):
    viewer = w.uid()
    client = client_for(viewer)
    first = client.patch(
        URL, {"formats": {"video": "less"}, "discovery_level": 3}, format="json"
    ).json()["data"]
    assert first["formats"] == {"video": "less"} and first["discovery_level"] == 3
    assert first["change_id"]
    second = client.patch(
        URL,
        {"discovery_prefs": {"trending": False}, "version": first["version"]},
        format="json",
    ).json()["data"]
    assert second["discovery_prefs"]["trending"] is False
    assert second["discovery_prefs"]["new_creators"] is True  # merged, not replaced
    stale = client.patch(URL, {"discovery_level": 0, "version": first["version"]}, format="json")
    assert stale.status_code == 409
    undone = client.post(f"{URL}undo/", {"change_id": first["change_id"]}, format="json")
    assert undone.status_code == 200
    data = undone.json()["data"]
    assert data["formats"] == {} and data["discovery_level"] == 2
    assert data["discovery_prefs"]["trending"] is False  # the later change is kept
    assert PreferenceChange.objects.filter(account_id=viewer).count() == 3
    again = client.post(f"{URL}undo/", {"change_id": first["change_id"]}, format="json")
    assert again.status_code == 404  # already undone
    other = client_for(w.uid()).post(
        f"{URL}undo/", {"change_id": second["change_id"]}, format="json"
    )
    assert other.status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        {"discovery_level": 4},
        {"discovery_level": True},
        {"languages": ["fr"]},
        {"formats": {"video": "lots"}},
        {"formats": {"podcast": "more"}},
        {"discovery_prefs": {"trending": "no"}},
        {"discovery_prefs": {"unknown": True}},
        {"personalization_off": "yes"},
        {"nope": 1},
        {},
    ],
)
def test_invalid_patches_are_400(client_for, body):
    assert client_for(w.uid()).patch(URL, body, format="json").status_code == 400


def test_the_old_import_path_and_a_noop_change():
    viewer = w.uid()
    row = preferences.set_default_mode(viewer, "friends")
    assert preferences.remembered_mode(viewer) == "friends"
    row2, change = preferences.patch(viewer, {"default_mode": "friends"})
    assert change is None and row2.version == row.version
    assert UserPreference.objects.get(account_id=viewer).default_mode == "friends"
