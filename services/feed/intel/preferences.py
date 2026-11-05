"""My Algorithm preferences, WP 4.6 slice: the remembered Home mode (02 section 9).

Precedence for the mode a Home first page is served in:

1. ``?mode=`` on the request (a link, or the switcher);
2. the viewer's remembered ``intel_user_preference.default_mode``;
3. ``mode_hint``: the web client's offline fallback (``localStorage``), sent only
   when the request names no mode;
4. ``feed.services.DEFAULT_MODE`` ("Most recent", owner decisions 5 and 25).

Only ``default_mode`` is read or written here; the other columns of the row keep
their documented defaults until the phase that wires them.
"""

from __future__ import annotations

from django.db import transaction
from django.db.models import F

from .models import FeedMode, UserPreference

MODES = tuple(FeedMode.values)


class StaleVersion(Exception):
    """``If-Match``/``version`` named an older row than the stored one."""

    def __init__(self, current: int) -> None:
        super().__init__(current)
        self.current = current


def remembered_mode(account_id) -> str | None:
    value = (
        UserPreference.objects.filter(account_id=account_id)
        .values_list("default_mode", flat=True)
        .first()
    )
    return value if value in MODES else None


def resolve_mode(account_id, requested: str | None, hint: str | None, default: str) -> str:
    """The mode to serve. ``requested`` is validated by the caller."""
    if requested:
        return requested
    remembered = remembered_mode(account_id)
    if remembered:
        return remembered
    if hint in MODES:
        return hint
    return default


def get(account_id) -> UserPreference:
    """The viewer's row, unsaved (version 0) when they never changed anything."""
    row = UserPreference.objects.filter(account_id=account_id).first()
    return row or UserPreference(account_id=account_id, version=0)


def set_default_mode(account_id, mode: str, *, expected_version: int | None = None):
    """Remember ``mode``. ``expected_version`` (optional) guards a concurrent edit."""
    if mode not in MODES:
        raise ValueError(mode)
    with transaction.atomic():
        row, created = UserPreference.objects.select_for_update().get_or_create(
            account_id=account_id, defaults={"default_mode": mode}
        )
        if created:
            return row
        if expected_version is not None and expected_version != row.version:
            raise StaleVersion(row.version)
        if row.default_mode == mode:
            return row
        UserPreference.objects.filter(pk=row.pk).update(default_mode=mode, version=F("version") + 1)
        row.refresh_from_db()
        return row


def personalization_off(account_id) -> bool:
    """The viewer turned personalization off (decision 24: then nothing behavioural is
    stored). Fail closed: an unreadable preference counts as off."""
    try:
        return bool(
            UserPreference.objects.filter(account_id=account_id)
            .values_list("personalization_off", flat=True)
            .first()
        )
    except Exception:  # noqa: BLE001 - never store behaviour we cannot prove is allowed
        return True
