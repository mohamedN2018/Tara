"""06 section 13 / 07 WP 6.3-B2: the R4 migrations run forward and backward on an
empty and a populated database; ``intel_user_interest`` carries ``mid_v`` / ``mid_at``
and the ``polarity`` enum includes ``muted`` and ``hidden``; ``intel_user_preference``
gains ``reset_at``, ``search_signal`` and ``home_sections`` with their defaults."""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from intel.models import InterestPolarity, UserInterest

# Inside the test's transaction (PostgreSQL DDL is transactional), like
# test_migrations_r3: the round trip is rolled back, later tests see it untouched.
pytestmark = pytest.mark.django_db

BEFORE = [("intel", "0010_home_v2c_drafts")]
AFTER = [("intel", "0012_r4_config")]


def _columns(table: str) -> set[str]:
    with connection.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = %s", [table]
        )
        return {r[0] for r in cur.fetchall()}


def _migrate(target):
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(target)


def test_columns_and_the_polarity_enum():
    assert {"mid_v", "mid_at", "short_v", "long_v", "counts"} <= _columns("intel_user_interest")
    assert {"reset_at", "search_signal", "home_sections"} <= _columns("intel_user_preference")
    assert {"muted", "hidden", "suppressed"} <= set(InterestPolarity.values)
    row = UserInterest.objects.create(
        account_id="00000000-0000-4000-8000-000000000001",
        dim="topic",
        key="1",
        source="explicit",
        polarity="muted",
        updated_at=timezone.now(),
    )
    assert row.mid_v == 0.0


def test_forward_and_backward_on_an_empty_and_a_populated_database():
    from intel.models import UserPreference

    UserPreference.objects.create(account_id="00000000-0000-4000-8000-000000000002")
    from intel.models import RankingConfig

    RankingConfig.objects.filter(note__startswith="home@3").delete()  # drafts: allowed
    try:
        _migrate(BEFORE)
        assert "reset_at" not in _columns("intel_user_preference")
        assert "intel_user_interest" not in connection.introspection.table_names()
        _migrate(AFTER)
        pref = UserPreference.objects.get(account_id="00000000-0000-4000-8000-000000000002")
        assert pref.reset_at is None and pref.search_signal is False and pref.home_sections == {}
        # The home@3 drafts again and discovery@1 once (kept on the way back: released).
        notes = list(
            RankingConfig.objects.filter(note__startswith="home@3").values_list("note", flat=True)
        )
        assert sorted(notes) == ["home@3", "home@3-r15", "home@3-r30"]
        assert RankingConfig.objects.filter(surface="discovery", status="active").count() == 1
    finally:
        _migrate(AFTER)
