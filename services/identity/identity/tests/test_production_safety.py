"""Tests for the shared production-safety deploy check (tara_common.checks).

Covers the pure detection logic (no Django needed) and the Django system-check
wrapper that surfaces findings on ``manage.py check --deploy``.
"""

from __future__ import annotations

from types import SimpleNamespace

from django.test import override_settings

from tara_common.checks import (
    evaluate_production_safety,
    production_safety_check,
)


def _ids(findings) -> set[str]:
    return {fid for fid, _level, _msg in findings}


# ---- pure logic -------------------------------------------------------------


def test_debug_true_is_never_flagged():
    # In development everything is permitted; the gate is production-only.
    settings_obj = SimpleNamespace(
        DEBUG=True,
        SECRET_KEY="dev-only-insecure-secret-change-me",
        ALLOWED_HOSTS=["*"],
    )
    assert evaluate_production_safety(settings_obj) == []


def test_dev_defaults_flag_errors_in_production():
    settings_obj = SimpleNamespace(
        DEBUG=False,
        SECRET_KEY="dev-only-insecure-secret-change-me",
        TARA_INTERNAL_JWT_SECRET="dev-only-internal-secret-change-me",
        DATABASES={"default": {"PASSWORD": "identity-dev-pass"}},
        ALLOWED_HOSTS=["*"],
        CORS_ALLOW_ALL_ORIGINS=True,
        CORS_ALLOW_CREDENTIALS=True,
        SESSION_COOKIE_SECURE=False,
        CSRF_COOKIE_SECURE=False,
    )
    ids = _ids(evaluate_production_safety(settings_obj))
    # Every error rule fires, plus the two cookie warnings.
    assert {"tara.E001", "tara.E002", "tara.E003", "tara.E004", "tara.E006"} <= ids
    assert {"tara.W001", "tara.W002"} <= ids


def test_empty_allowed_hosts_flags_e005_not_e004():
    settings_obj = SimpleNamespace(
        DEBUG=False,
        SECRET_KEY="a-real-strong-secret",
        ALLOWED_HOSTS=[],
    )
    ids = _ids(evaluate_production_safety(settings_obj))
    assert "tara.E005" in ids
    assert "tara.E004" not in ids


def test_hardened_production_config_is_clean():
    settings_obj = SimpleNamespace(
        DEBUG=False,
        SECRET_KEY="x7" + "k9q2w" * 12,
        TARA_INTERNAL_JWT_SECRET="z3" + "p1m4n" * 12,
        DATABASES={"default": {"PASSWORD": "S0me-Strong-Rotating-Secret"}},
        ALLOWED_HOSTS=["api.tara.example"],
        CORS_ALLOW_ALL_ORIGINS=False,
        CORS_ALLOW_CREDENTIALS=True,
        SESSION_COOKIE_SECURE=True,
        CSRF_COOKIE_SECURE=True,
    )
    assert evaluate_production_safety(settings_obj) == []


# ---- Django system-check wrapper -------------------------------------------


def test_wrapper_returns_no_messages_in_debug():
    # The identity test settings run with DEBUG; the deploy check stays silent.
    with override_settings(DEBUG=True):
        assert production_safety_check() == []


def test_wrapper_emits_django_errors_in_production():
    with override_settings(
        DEBUG=False,
        SECRET_KEY="dev-only-insecure-secret-change-me",
        ALLOWED_HOSTS=["*"],
    ):
        messages = production_safety_check()
    ids = {m.id for m in messages}
    assert "tara.E001" in ids
    assert "tara.E004" in ids
    # Errors carry Django's ERROR level so `check --deploy` exits non-zero.
    assert any(m.id == "tara.E001" and m.is_serious() for m in messages)
