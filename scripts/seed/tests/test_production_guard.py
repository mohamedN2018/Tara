"""Tara Intelligence WP 2.9 (D16): the seed never runs against production, and
it registers its accounts as synthetic.

Run: uvx pytest scripts/seed/tests (standard library only, no stack needed).
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SEED = Path(__file__).resolve().parents[1] / "seed_dataset.py"
spec = importlib.util.spec_from_file_location("seed_dataset", SEED)
seed = importlib.util.module_from_spec(spec)
sys.modules["seed_dataset"] = seed  # dataclasses look their module up while it loads
spec.loader.exec_module(seed)

LOCAL_API = "http://127.0.0.1:8080/api/v1"


def _no_files(tmp_path) -> tuple[Path, ...]:
    return (tmp_path / "missing.env",)


def test_tara_env_production_refuses_even_a_local_target(tmp_path):
    for value in ("production", "PRODUCTION", " production "):
        with pytest.raises(SystemExit, match="TARA_ENV=production"):
            seed.refuse_production(LOCAL_API, {"TARA_ENV": value}, _no_files(tmp_path))


def test_the_production_domain_is_refused(tmp_path):
    env = {"TARA_ENV": "development", "DOMAIN": "tara.example.com"}
    for api in (
        "https://tara.example.com/api/v1",
        "https://TARA.example.com./api/v1",
        "https://api.tara.example.com/api/v1",
    ):
        with pytest.raises(SystemExit, match="production domain"):
            seed.refuse_production(api, env, _no_files(tmp_path))


def test_the_domain_is_read_from_the_production_env_file_only(tmp_path):
    prod = tmp_path / ".env_prod"
    prod.write_text(
        "SECRET_SOMETHING=do-not-read\nDOMAIN=social.example.org   # the site\n",
        encoding="utf-8",
    )
    assert seed.production_domains({}, (prod,)) == {"social.example.org"}
    with pytest.raises(SystemExit):
        seed.refuse_production("https://social.example.org/api/v1", {}, (prod,))


def test_dev_and_staging_targets_pass(tmp_path):
    env = {"TARA_ENV": "development", "DOMAIN": "tara.example.com"}
    for api in (
        LOCAL_API,
        "http://localhost:8080/api/v1",
        "https://staging.example.net/api/v1",
        "https://example.com/api/v1",  # the parent of the production domain is not it
        "https://nottara.example.com/api/v1",
    ):
        seed.refuse_production(api, env, _no_files(tmp_path))


def test_a_local_domain_value_never_blocks_the_local_stack(tmp_path):
    seed.refuse_production(LOCAL_API, {"DOMAIN": "localhost"}, _no_files(tmp_path))
    seed.refuse_production("http://localhost:8080/api/v1", {"DOMAIN": "localhost"}, ())
    assert seed.production_domains({"DOMAIN": "tara.local"}, ()) == set()


def test_main_refuses_before_doing_anything(tmp_path, monkeypatch):
    """Even --dry-run and --report stop: the guard runs first."""
    monkeypatch.setenv("TARA_ENV", "production")
    state = tmp_path / "state"
    for extra in (["--dry-run"], ["--report"], ["--register-synthetic"], ["--allow-remote"]):
        argv = ["--source", str(tmp_path), "--state-dir", str(state), *extra]
        with pytest.raises(SystemExit, match="TARA_ENV=production"):
            seed.main(argv)
    assert not state.exists()


# ---- synthetic registration ------------------------------------------------------------


def _state(tmp_path, ids):
    state = seed.State(tmp_path / "state")
    for n, account_id in enumerate(ids):
        state.data["accounts"][f"u{n}"] = {"id": account_id, "verified": True}
    state.data["accounts"]["pending"] = {"email": "x@example.invalid"}  # never created
    return state


class Runner:
    def __init__(self, returncode=0, raises=None):
        self.calls = []
        self.returncode = returncode
        self.raises = raises

    def __call__(self, cmd, **kwargs):
        self.calls.append((cmd, kwargs))
        if self.raises:
            raise self.raises
        return subprocess.CompletedProcess(
            cmd, self.returncode, stdout="", stderr="no such command"
        )


def test_seed_accounts_are_registered_with_a_seed_label(tmp_path, monkeypatch):
    ids = ["b0000000-0000-7000-8000-000000000002", "a0000000-0000-7000-8000-000000000001"]
    ids.append("c0000000-0000-7000-8000-000000000003")
    monkeypatch.setattr(seed, "SYNTHETIC_CHUNK", 2)
    state = _state(tmp_path, ids)
    runner = Runner()
    assert seed.register_synthetic(state, "seed-dataset", LOCAL_API, runner=runner) is True
    assert len(runner.calls) == 2  # chunked
    sent = []
    for cmd, _kwargs in runner.calls:
        at = cmd.index("feed")
        assert cmd[at : at + 7] == [
            "feed",
            "python",
            "manage.py",
            "intel_register_synthetic",
            "--label",
            "seed-dataset",
            "--ids",
        ]
        assert "exec" in cmd and "-T" in cmd
        sent += cmd[at + 7 :]
    assert sent == sorted(ids)  # ids only
    saved = json.loads((tmp_path / "state" / seed.SYNTHETIC_FILE).read_text(encoding="utf-8"))
    assert saved == {"label": "seed-dataset", "count": 3, "account_ids": sorted(ids)}


def test_a_label_that_is_not_seed_is_refused(tmp_path):
    state = _state(tmp_path, ["a0000000-0000-7000-8000-000000000001"])
    for label in ("test-integration", "real", ""):
        with pytest.raises(SystemExit, match="seed-"):
            seed.register_synthetic(state, label, LOCAL_API, runner=Runner())


def test_feed_without_the_command_keeps_the_ids_for_later(tmp_path):
    state = _state(tmp_path, ["a0000000-0000-7000-8000-000000000001"])
    assert seed.register_synthetic(state, "seed-dataset", LOCAL_API, runner=Runner(1)) is False
    no_docker = Runner(raises=FileNotFoundError("docker"))
    assert seed.register_synthetic(state, "seed-dataset", LOCAL_API, runner=no_docker) is False
    assert (tmp_path / "state" / seed.SYNTHETIC_FILE).exists()


def test_a_remote_stack_is_never_called_through_local_docker(tmp_path):
    state = _state(tmp_path, ["a0000000-0000-7000-8000-000000000001"])
    runner = Runner()
    staging = "https://staging.example.net/api/v1"
    assert seed.register_synthetic(state, "seed-dataset", staging, runner=runner) is False
    assert runner.calls == []
    assert (tmp_path / "state" / seed.SYNTHETIC_FILE).exists()


def test_nothing_to_register_without_accounts(tmp_path):
    state = seed.State(tmp_path / "state")
    runner = Runner()
    assert seed.register_synthetic(state, "seed-dataset", LOCAL_API, runner=runner) is False
    assert runner.calls == []
