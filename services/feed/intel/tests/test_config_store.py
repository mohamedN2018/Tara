"""WP 4.1: the versioned config store. Invalid params are rejected, an active version
is immutable, and every change is logged and emitted in the same transaction."""

import json
import uuid
from pathlib import Path

import pytest
from django.db import IntegrityError, connection, transaction
from feed.models import OutboxEvent

from intel import config
from intel.config import schema, store
from intel.models import RankingConfig, RankingConfigChange

pytestmark = pytest.mark.django_db

SCHEMA = Path("/opt/tara/libs/tara_events/tara_events/schemas/intel.config.changed.v1.json")
STAFF = str(uuid.uuid4())


def _events():
    return [e.payload for e in OutboxEvent.objects.filter(event_type="intel.config.changed")]


def test_the_migration_loads_version_1_of_every_surface_and_home_v2_as_a_draft():
    rows = {(r.surface, r.version): r.status for r in RankingConfig.objects.all()}
    for surface in schema.SURFACES:
        assert rows[(surface, 1)] == "active"
    assert rows[("home", 2)] == "draft"
    assert config.for_surface("home").version == "home@1"
    # The stored home@1 is the package file, key for key.
    stored = RankingConfig.objects.get(surface="home", version=1).params
    assert {k: v for k, v in store.defaults("home").items() if k in stored} == stored


def test_invalid_params_are_never_stored():
    params = store.defaults("home")
    params["weights"]["freshness"] = 50
    before = RankingConfig.objects.count()
    with pytest.raises(schema.ConfigInvalid):
        store.create("home", params, actor_id=STAFF)
    assert RankingConfig.objects.count() == before
    assert not RankingConfigChange.objects.filter(action="created", actor_id=STAFF).exists()


def test_an_active_version_is_immutable_in_the_model_and_in_the_database():
    row = RankingConfig.objects.get(surface="home", version=1)
    row.params = {**row.params, "freshness": {"half_life_hours": 12}}
    with pytest.raises(ValueError, match="frozen"):
        row.save()
    with (
        pytest.raises(Exception, match="immutable"),
        transaction.atomic(),
        connection.cursor() as cur,
    ):
        cur.execute(
            "UPDATE intel_ranking_config SET params = '{}'::jsonb"
            " WHERE surface = 'home' AND version = 1"
        )
    with pytest.raises(Exception, match="cannot be deleted"), transaction.atomic():
        RankingConfig.objects.filter(surface="home", version=1).delete()
    # A draft can change.
    draft = store.create("home", store.defaults("home"))
    params = store.defaults("home")
    params["freshness"]["half_life_hours"] = 12
    store.update_draft("home", draft, params)
    assert store.load("home", draft)["freshness"]["half_life_hours"] == 12


def test_only_one_version_per_surface_is_active():
    with pytest.raises(IntegrityError), transaction.atomic():
        RankingConfig.objects.filter(surface="home", version=2).update(status="active")


def test_activation_archives_the_old_version_logs_a_diff_and_emits_an_event():
    store.clear_cache()
    assert config.for_surface("home").get("diversity.enabled") is False
    old = store.activate("home", 2, actor_id=STAFF, reason="phase 4 switch")
    assert old == 1
    assert RankingConfig.objects.get(surface="home", version=1).status == "archived"
    assert RankingConfig.objects.get(surface="home", version=2).status == "active"
    change = RankingConfigChange.objects.filter(action="activated").latest("created_at")
    assert (change.from_version, change.to_version, str(change.actor_id)) == (1, 2, STAFF)
    assert change.reason == "phase 4 switch"
    paths = {d["path"] for d in change.diff}
    assert {"weights.s_like", "diversity.enabled", "ranking.sources"} <= paths
    # The new version is served at once in this process (others within 30 s).
    cfg = config.for_surface("home")
    assert cfg.version == "home@2" and cfg.get("diversity.enabled") is True
    [event] = _events()
    assert event["payload"] == {
        "surface": "home",
        "action": "activated",
        "from_version": 1,
        "to_version": 2,
        "experiment": None,
        "reason_present": True,
    }
    assert event["actor_id"] == STAFF and event["subject_id"] == "home@2"
    assert "phase 4 switch" not in json.dumps(event)  # free text stays in feed


def test_rollback_reactivates_the_replaced_version():
    store.activate("home", 2, actor_id=STAFF, reason="try v2")
    back = store.rollback("home", actor_id=STAFF, reason="")
    assert back == 1
    assert config.for_surface("home").version == "home@1"
    assert RankingConfigChange.objects.filter(action="rolled_back", to_version=1).exists()
    assert [e["payload"]["action"] for e in _events()] == ["activated", "rolled_back"]
    assert _events()[-1]["payload"]["reason_present"] is False


def test_activating_the_active_version_or_an_unknown_one_fails():
    with pytest.raises(store.ConfigError):
        store.activate("home", 1, reason="x")
    with pytest.raises(store.ConfigError):
        store.activate("home", 999, reason="x")


def test_a_change_and_its_event_share_one_transaction():
    with pytest.raises(RuntimeError), transaction.atomic():
        store.activate("home", 2, actor_id=STAFF, reason="rolled back by the caller")
        raise RuntimeError
    assert RankingConfig.objects.get(surface="home", version=1).status == "active"
    assert not _events()
    assert not RankingConfigChange.objects.filter(action="activated", actor_id=STAFF).exists()


def test_the_emission_flag_turns_the_event_off(settings):
    settings.INTEL_EMIT_CONFIG_CHANGED = False
    store.activate("home", 2, reason="quiet")
    assert not _events()
    assert RankingConfigChange.objects.filter(action="activated", to_version=2).exists()


def test_create_logs_and_emits():
    version = store.create("reels", store.defaults("reels"), actor_id=STAFF, note="copy")
    assert version == 2
    assert RankingConfig.objects.get(surface="reels", version=2).status == "draft"
    assert _events()[-1]["payload"]["action"] == "created"


def test_a_read_failure_keeps_the_last_good_config_then_the_package_defaults(monkeypatch):
    store.clear_cache()
    store.activate("home", 2, reason="x")
    assert config.for_surface("home").version == "home@2"

    def broken(surface):
        raise RuntimeError("database down")

    monkeypatch.setattr(store, "_load_active", broken)
    monkeypatch.setattr(store, "ACTIVE_TTL_S", -1.0)  # the pointer is stale at once
    store._active["home"] = (0.0, *store._active["home"][1:])
    assert config.for_surface("home").version == "home@2"  # last good
    store.clear_cache()
    assert config.for_surface("home").version == "home@1"  # compiled defaults


def test_a_stored_version_without_a_newer_block_takes_the_package_defaults():
    params = store.defaults("home")
    params.pop("why")  # an optional block a later release added
    version = store.create("home", params)
    store.activate("home", version, reason="x")
    assert (
        config.for_surface("home").get("why.max_factors")
        == store.defaults("home")["why"]["max_factors"]
    )


def test_the_event_payload_matches_its_json_schema():
    if not SCHEMA.exists():
        pytest.skip("schemas are copied into the image at /opt/tara/libs")
    jsonschema = pytest.importorskip("jsonschema")
    store.activate("home", 2, actor_id=STAFF, reason="x")
    store.rollback("home", reason="y")
    store.create("video", store.defaults("video"))
    spec = json.loads(SCHEMA.read_text(encoding="utf-8"))
    for event in _events():
        jsonschema.validate(event["payload"], spec)


def test_the_management_command_validates_and_activates(tmp_path):
    from django.core.management import CommandError, call_command

    bad = tmp_path / "bad.json"
    params = store.defaults("home")
    params["weights"]["negative"] = 11
    bad.write_text(json.dumps(params), encoding="utf-8")
    with pytest.raises(CommandError, match="weights.negative"):
        call_command("intel_config", "validate", "home", str(bad))
    with pytest.raises(CommandError, match="--reason"):
        call_command("intel_config", "activate", "home", "2")
    call_command("intel_config", "activate", "home", "2", "--reason", "go", "--actor", STAFF)
    assert config.for_surface("home").version == "home@2"
