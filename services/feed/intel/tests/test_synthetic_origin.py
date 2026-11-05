"""WP 2.9: synthetic rows are labelled, production refuses them, the seed command
writes backdated rows only for authorized content."""

import uuid
from datetime import timedelta

import pytest
from django.core.management import CommandError, call_command
from django.utils import timezone
from feed.models import FeedItem, PostHide

from intel import checks, origin, readiness
from intel.models import SyntheticAccount

from .helpers import acct, signal_rows

pytestmark = pytest.mark.django_db


def _register(account, label="seed-2026-11"):
    SyntheticAccount.objects.create(account_id=account, label=label)
    origin.clear_cache()


def test_labels_decide_the_origin():
    assert SyntheticAccount(account_id=uuid.uuid4(), label="seed-a").origin == "synthetic"
    assert SyntheticAccount(account_id=uuid.uuid4(), label="test-a").origin == "test"
    from django.core.exceptions import ValidationError

    with pytest.raises(ValidationError):
        SyntheticAccount(account_id=uuid.uuid4(), label="real-a").full_clean()


def test_label_prefix_is_enforced_by_the_database():
    from django.db import IntegrityError, transaction

    with pytest.raises(IntegrityError), transaction.atomic():
        SyntheticAccount.objects.create(account_id=uuid.uuid4(), label="prod-1")


def test_readiness_fails_when_production_holds_synthetic_accounts(settings):
    settings.INTEL_ACCEPT_SYNTHETIC = False
    assert readiness.synthetic_registry_check() == (True, "ok")
    _register(acct())
    ok, detail = readiness.synthetic_registry_check()
    assert not ok and "not empty" in detail
    settings.INTEL_ACCEPT_SYNTHETIC = True
    assert readiness.synthetic_registry_check()[0]


def test_readiness_endpoint_reports_it(client, settings):
    settings.INTEL_ACCEPT_SYNTHETIC = False
    _register(acct())
    body = client.get("/readyz/").json()
    assert body["checks"]["intel_synthetic"] != "ok"


def test_deploy_checks_refuse_synthetic_flags_in_production(settings):
    settings.TARA_ENV = "production"
    settings.INTEL_ACCEPT_SYNTHETIC = True
    settings.INTEL_SYNTHETIC_IN_RANKING = True
    ids = {e.id for e in checks.synthetic_in_production()}
    assert ids == {"intel.E003", "intel.E004"}
    settings.INTEL_SERVE_TOKEN_SECRET = ""
    assert [e.id for e in checks.serve_token_secret()] == ["intel.E002"]
    settings.INTEL_SERVE_TOKEN_SECRET = settings.SECRET_KEY
    assert [e.id for e in checks.serve_token_secret()] == ["intel.E001"]


# ---- intel_register_synthetic ------------------------------------------------------


def test_register_command_refuses_production_and_unaccepted(settings):
    settings.INTEL_ACCEPT_SYNTHETIC = False
    with pytest.raises(CommandError):
        call_command("intel_register_synthetic", "--label", "seed-x", "--ids", acct())
    settings.INTEL_ACCEPT_SYNTHETIC = True
    settings.TARA_ENV = "production"
    with pytest.raises(CommandError):
        call_command("intel_register_synthetic", "--label", "seed-x", "--ids", acct())
    assert not SyntheticAccount.objects.exists()


def test_register_command_from_a_seed_manifest(settings, tmp_path):
    import json

    settings.INTEL_ACCEPT_SYNTHETIC = True
    a, b = acct(), acct()
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"accounts": {"u001": {"id": a}, "u002": {"id": b}}}))
    call_command("intel_register_synthetic", "--label", "seed-2026-11", "--manifest", str(manifest))
    assert set(map(str, SyntheticAccount.objects.values_list("account_id", flat=True))) == {a, b}
    with pytest.raises(CommandError):
        call_command("intel_register_synthetic", "--label", "nope", "--ids", acct())
    call_command("intel_register_synthetic", "--remove", "--ids", a)
    assert list(map(str, SyntheticAccount.objects.values_list("account_id", flat=True))) == [b]


# ---- intel_seed_synthetic_signals --------------------------------------------------


def _feed(viewer, *, days_ago, kind="text", hidden=False):
    post_id, author = str(uuid.uuid4()), acct()
    FeedItem.objects.create(
        recipient_id=viewer,
        post_id=post_id,
        author_id=author,
        reason="friend",
        snapshot={"post_id": post_id, "author_id": author, "type": kind, "audience": "public"},
        post_created_at=timezone.now() - timedelta(days=days_ago),
    )
    if hidden:
        PostHide.objects.create(account_id=viewer, post_id=post_id, author_id=author, reason="spam")
    return post_id


def test_seed_command_refuses_unless_accepted(settings):
    settings.INTEL_ACCEPT_SYNTHETIC = False
    settings.INTEL_SIGNAL_RETENTION_DAYS = 90
    with pytest.raises(CommandError):
        call_command("intel_seed_synthetic_signals", "--days", "10")
    settings.INTEL_ACCEPT_SYNTHETIC = True
    settings.TARA_ENV = "production"
    with pytest.raises(CommandError):
        call_command("intel_seed_synthetic_signals", "--days", "10")


def test_seed_command_refuses_to_backdate_beyond_retention(settings):
    settings.INTEL_ACCEPT_SYNTHETIC = True
    settings.INTEL_SIGNAL_RETENTION_DAYS = 30
    _register(acct())
    with pytest.raises(CommandError, match="RETENTION"):
        call_command("intel_seed_synthetic_signals", "--days", "60")


def test_seed_command_writes_backdated_synthetic_rows(settings):
    settings.INTEL_ACCEPT_SYNTHETIC = True
    settings.INTEL_SIGNAL_RETENTION_DAYS = 90
    seed, real, tester = acct(), acct(), acct()
    _register(seed)
    _register(tester, "test-fixture")
    visible = {_feed(seed, days_ago=d, kind="video" if d % 2 else "text") for d in range(1, 40)}
    hidden = _feed(seed, days_ago=20, hidden=True)
    other = {_feed(real, days_ago=d) for d in range(1, 10)}

    call_command("intel_seed_synthetic_signals", "--days", "60", "--seed", "7")

    rows = signal_rows(account_id=seed)
    assert len(rows) > 50
    assert {r["data_origin"] for r in rows} == {"synthetic"}
    assert {r["source"] for r in rows} == {"server"}
    assert all(r["received_at"] == r["occurred_at"] for r in rows)
    assert min(r["occurred_at"] for r in rows) < timezone.now() - timedelta(days=30)
    items = {str(r["item_id"]) for r in rows}
    assert items <= visible and hidden not in items and not items & other
    assert {"feed_impression", "video_start"} <= {r["event_type"] for r in rows}
    # Never seen before it was posted.
    created = dict(
        FeedItem.objects.filter(recipient_id=seed).values_list("post_id", "post_created_at")
    )
    assert all(r["occurred_at"] >= created[r["item_id"]] for r in rows)
    # Neither real nor test accounts get synthetic rows.
    assert signal_rows(account_id=real) == [] and signal_rows(account_id=tester) == []


def test_seed_command_scale_and_replace(settings):
    settings.INTEL_ACCEPT_SYNTHETIC = True
    settings.INTEL_SIGNAL_RETENTION_DAYS = 90
    seed = acct()
    _register(seed)
    for d in range(1, 20):
        _feed(seed, days_ago=d)
    call_command("intel_seed_synthetic_signals", "--days", "20", "--seed", "1")
    once = len(signal_rows(account_id=seed))
    call_command(
        "intel_seed_synthetic_signals", "--days", "20", "--seed", "1", "--scale", "3", "--replace"
    )
    tripled = len(signal_rows(account_id=seed))
    assert tripled > 2 * once


def test_a_new_registration_is_seen_at_once_without_a_cache_reset(settings):
    """No stale window: a process that already resolved the account as real sees the
    registration on its next lookup, so its rows are never stored as ``real``."""
    settings.INTEL_ACCEPT_SYNTHETIC = True
    account = acct()
    assert origin.resolve(account).origin == "real"
    SyntheticAccount.objects.create(account_id=account, label="seed-late")  # no clear_cache
    assert origin.resolve(account).origin == "synthetic"
    settings.INTEL_SYNTHETIC_IN_RANKING = False
    assert origin.excluded_from_ranking(None, "not-a-uuid", account)
    assert not origin.excluded_from_ranking(acct())


def test_a_partition_created_in_a_rolled_back_transaction_is_not_remembered():
    from datetime import UTC, datetime

    from django.db import transaction

    from intel.signals import partitions

    day = datetime(2025, 3, 3, tzinfo=UTC).date()
    with pytest.raises(RuntimeError), transaction.atomic():
        partitions.ensure(partitions.SIGNALS, day)
        raise RuntimeError("roll back")
    name = partitions.SIGNALS.name(day)
    assert name not in partitions._known
    assert not partitions._exists(name)
    partitions.ensure(partitions.SIGNALS, day)  # created again, for real this time
    assert partitions._exists(name)
