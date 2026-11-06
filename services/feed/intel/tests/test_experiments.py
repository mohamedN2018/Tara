"""WP 5.4 / 5.5: the experiment core and ``intel.config.published``.

- create / start / stop through the store and the management command; one running
  experiment per surface; variants must name stored versions and sum to <= 100;
- ``config_for`` serves the assigned variant's version (sticky), the active version
  outside the allocated range;
- ``intel.config.published`` is emitted in the same transaction on activate,
  rollback, experiment start and stop, with the active params and the running
  experiment's variants; ``intel_config publish`` re-emits it; payloads match the
  JSON schema;
- ``discovery@1`` is active and reproduces graph's and profile's constants (parity).
"""

import json
import uuid
from pathlib import Path

import pytest
from django.core.management import CommandError, call_command
from feed.models import OutboxEvent

from intel import config, experiments
from intel.config import store
from intel.models import Experiment, RankingConfig, RankingConfigChange

from . import variants

pytestmark = pytest.mark.django_db
SCHEMAS = Path("/opt/tara/libs/tara_events/tara_events/schemas")


def _published() -> list[dict]:
    return [
        e.payload["payload"]
        for e in OutboxEvent.objects.filter(event_type="intel.config.published").order_by(
            "created_at"
        )
    ]


def _three_arms() -> list[dict]:
    return [
        {"name": "control", "pct": 34, "version": variants.version("home@2b")},
        {"name": "r15", "pct": 33, "version": variants.version("home@2b-r15")},
        {"name": "r30", "pct": 33, "version": variants.version("home@2b-r30")},
    ]


def _start(key="home.discovery_ratio"):
    experiments.create(key, "home", _three_arms(), salt="s1")
    return experiments.start(key, reason="test")


def test_discovery_at_1_is_active_with_todays_constants():
    row = RankingConfig.objects.get(surface="discovery", version=1)
    assert row.status == "active"
    cfg = config.for_surface("discovery")
    assert cfg.section("people") == {
        "default_limit": 10,
        "max_limit": 30,
        "max_bridges": 500,
        "max_candidates": 2000,
        "follower_fill": True,
    }
    assert cfg.section("pages") == {"default_limit": 5}
    assert cfg.section("groups") == {"max_suggestions": 20, "friend_preview": 3}


def test_variants_are_checked():
    with pytest.raises(experiments.ExperimentError):
        experiments.create("x", "home", [{"name": "a", "pct": 60, "version": 1}] * 2, salt="s")
    with pytest.raises(experiments.ExperimentError):
        experiments.create("x", "home", [{"name": "a", "pct": 50, "version": 999}], salt="s")
    with pytest.raises(experiments.ExperimentError):
        experiments.create(
            "x",
            "home",
            [{"name": "a", "pct": 60, "version": 1}, {"name": "b", "pct": 60, "version": 1}],
            salt="s",
        )


def test_one_running_experiment_per_surface_and_stop():
    _start()
    experiments.create("second", "home", _three_arms(), salt="s2")
    with pytest.raises(experiments.ExperimentError):
        experiments.start("second", reason="test")
    stopped = experiments.stop("home.discovery_ratio", reason="done")
    assert stopped.status == "stopped" and stopped.ends_at is not None
    experiments.start("second", reason="now")
    with pytest.raises(experiments.ExperimentError):
        experiments.start("home.discovery_ratio", reason="restart a stopped one")
    actions = list(
        RankingConfigChange.objects.filter(surface="home", action__startswith="experiment_")
        .order_by("created_at")
        .values_list("action", flat=True)
    )
    assert actions == ["experiment_started", "experiment_stopped", "experiment_started"]
    changed = OutboxEvent.objects.filter(event_type="intel.config.changed").order_by("created_at")
    assert [e.payload["payload"]["experiment"] for e in changed][-3:] == [
        "home.discovery_ratio",
        "home.discovery_ratio",
        "second",
    ]


def test_config_for_serves_the_assigned_variant_sticky():
    _start()
    experiments.clear_cache()
    by_variant = {}
    for _ in range(300):
        account = str(uuid.uuid4())
        assignment = experiments.assign(account, "home")
        assert assignment is not None  # 100% allocated
        cfg = experiments.config_for(account, "home", record=False)
        assert cfg.version == f"home@{assignment.version}"
        assert experiments.assign(account, "home") == assignment
        by_variant.setdefault(assignment.variant, 0)
        by_variant[assignment.variant] += 1
    assert set(by_variant) == {"control", "r15", "r30"}


def test_no_experiment_serves_the_active_version():
    experiments.clear_cache()
    account = str(uuid.uuid4())
    assert experiments.config_for(account, "home").version == config.for_surface("home").version


def test_published_on_activate_rollback_start_and_stop():
    before = len(_published())
    store.activate("home", variants.version("home@2b"), reason="t")
    store.rollback("home", reason="t")
    _start()
    experiments.stop("home.discovery_ratio", reason="t")
    events = _published()[before:]
    assert len(events) == 4
    assert [e["experiment"] is None for e in events] == [True, True, False, True]
    running = events[2]["experiment"]
    assert running["key"] == "home.discovery_ratio" and running["salt"] == "s1"
    assert [v["name"] for v in running["variants"]] == ["control", "r15", "r30"]
    assert running["variants"][1]["params"]["mix"]["recommended"] == 0.15
    assert all(e["surface"] == "home" and e["params"]["surface"] == "home" for e in events)


def test_publish_command_re_emits_the_state_and_honours_the_flag(settings):
    before = len(_published())
    call_command("intel_config", "publish", "--surface", "discovery")
    event = _published()[-1]
    assert len(_published()) == before + 1
    assert event["surface"] == "discovery" and event["version"] == 1
    assert event["params"]["people"]["max_bridges"] == 500
    settings.INTEL_EMIT_R4_EVENTS = False
    call_command("intel_config", "publish", "--surface", "discovery")
    assert len(_published()) == before + 1


def test_management_command_lifecycle():
    arms = _three_arms()
    args = [f"--variant={v['name']}:{v['pct']}:{v['version']}" for v in arms]
    call_command("intel_experiment", "create", "cmd.exp", "--surface", "home", "--salt", "z", *args)
    with pytest.raises(CommandError):
        call_command("intel_experiment", "start", "cmd.exp")  # a reason is required
    call_command("intel_experiment", "start", "cmd.exp", "--reason", "go")
    assert Experiment.objects.get(key="cmd.exp").status == "running"
    call_command("intel_experiment", "stop", "cmd.exp", "--reason", "end")
    assert Experiment.objects.get(key="cmd.exp").status == "stopped"


def test_payloads_match_their_json_schemas():
    if not SCHEMAS.exists():
        pytest.skip("schemas are copied into the image at /opt/tara/libs")
    jsonschema = pytest.importorskip("jsonschema")
    _start()
    call_command("intel_config", "publish", "--surface", "discovery")
    spec = json.loads((SCHEMAS / "intel.config.published.v1.json").read_text(encoding="utf-8"))
    checker = jsonschema.Draft202012Validator(spec, format_checker=jsonschema.FormatChecker())
    for payload in _published():
        checker.validate(payload)
    changed = json.loads((SCHEMAS / "intel.config.changed.v1.json").read_text(encoding="utf-8"))
    for e in OutboxEvent.objects.filter(event_type="intel.config.changed"):
        jsonschema.validate(e.payload["payload"], changed)
