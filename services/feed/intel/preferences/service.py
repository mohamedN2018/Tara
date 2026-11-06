"""My Algorithm preferences (04 WP 4.6, 8.1; 07 WP 8.4-B2, 8.7-B2; 02 sections 9, 13, 19).

Precedence for the mode a Home first page is served in:

1. ``?mode=`` on the request (a link, or the switcher);
2. the viewer's remembered ``intel_user_preference.default_mode``;
3. ``mode_hint``: the web client's offline fallback (``localStorage``), sent only
   when the request names no mode;
4. ``feed.services.DEFAULT_MODE`` ("Most recent", owner decisions 5 and 25).

R4 adds the whole row (``body``): formats, discovery level and toggles, languages,
``sensitive_inference`` (decision 12), ``personalization_off`` (decisions 8 and 24),
``search_signal`` (decision 7), onboarding, reset, debug consent (decision 17).
Every change goes through ``patch`` with optimistic concurrency (``version``) and
writes an ``intel_preference_change`` row with the exact ``before`` / ``after``, so
``undo`` restores it. Side effects run in the same transaction:

- ``personalization_off`` turned on: the account's visit rows are deleted, and after
  commit its behavioural redis-hot keys (``feed:sess``, ``feed:exp``, ``feed:head:*``,
  ``feed:si``, ``feed:rank:*``, ``intel:prof``) are purged, fail-soft with
  ``intel_hot_purge_failed_total``;
- ``sensitive_inference`` turned off: inferred rows on sensitive topics are deleted;
- the effective search signal (``search_signal AND NOT personalization_off``) changed:
  ``intel.search_signal.changed`` is emitted (``INTEL_EMIT_R4_EVENTS``).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from django.core import signing
from django.db import connection, transaction
from django.db.models import F
from django.utils import timezone

from ..models import DebugConsent, FeedMode, PreferenceChange, UserInterest, UserPreference

MODES = tuple(FeedMode.values)
FORMATS = ("text", "image", "video", "link", "share", "poll", "reel")
FORMAT_CHOICES = ("more", "less")
DISCOVERY_PREFS = (
    "new_creators",
    "trending",
    "people_suggestions",
    "page_suggestions",
    "group_suggestions",
    "other_languages",
)
LANGUAGES = ("ar", "en")
FIELDS = (
    "default_mode",
    "discovery_level",
    "languages",
    "formats",
    "discovery_prefs",
    "sensitive_inference",
    "personalization_off",
    "search_signal",
)
_RESET_SALT = "tara.intel.reset.v1"
RESET_SCOPE = (
    "inferred_interests",
    "engagement_history",
    "session_and_visit_history",
    "ranking_sessions",
)
RESET_KEEPS = (
    "explicit_topics",
    "follows",
    "friends",
    "blocks",
    "hides",
    "mutes",
    "item_not_interested",
)


class StaleVersion(Exception):
    """``If-Match``/``version`` named an older row than the stored one."""

    def __init__(self, current: int) -> None:
        super().__init__(current)
        self.current = current


class PreferenceError(Exception):
    def __init__(self, code: str, message: str, *, retry_after: int | None = None):
        super().__init__(message)
        self.code = code
        self.retry_after = retry_after


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


# ---- the API body ------------------------------------------------------------------


def _home_cfg():
    from .. import config

    return config.for_surface("home")


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def active_consent(account_id, now: datetime | None = None) -> DebugConsent | None:
    now = now or timezone.now()
    return (
        DebugConsent.objects.filter(
            account_id=account_id, revoked_at__isnull=True, expires_at__gt=now
        )
        .order_by("-expires_at")
        .first()
    )


def state(row: UserPreference) -> dict:
    """The editable fields, as stored (the change log's ``before`` / ``after``)."""
    return {
        "default_mode": row.default_mode or None,
        "discovery_level": int(row.discovery_level),
        "languages": list(row.languages or []),
        "formats": dict(row.formats or {}),
        "discovery_prefs": {**_defaults_prefs(), **dict(row.discovery_prefs or {})},
        "sensitive_inference": bool(row.sensitive_inference),
        "personalization_off": bool(row.personalization_off),
        "search_signal": bool(row.search_signal),
    }


def _defaults_prefs() -> dict:
    from ..models import _default_discovery_prefs

    return _default_discovery_prefs()


def body(row: UserPreference, now: datetime | None = None) -> dict:
    now = now or timezone.now()
    out = state(row)
    reset_available = None
    if row.reset_at:
        hours = int(_home_cfg().get("reset.min_interval_h"))
        nxt = row.reset_at + timedelta(hours=hours)
        reset_available = nxt if nxt > now else None
    consent = active_consent(row.account_id, now)
    out.update(
        {
            "onboarded_at": _iso(row.onboarded_at),
            "reset_at": _iso(row.reset_at),
            "reset_available_at": _iso(reset_available),
            "debug_consent_expires_at": _iso(consent.expires_at) if consent else None,
            "version": int(row.version),
        }
    )
    return out


# ---- validation ----------------------------------------------------------------------


def validate(changes: dict) -> dict:
    """The accepted subset of ``changes`` (``PreferenceError`` on a bad value)."""
    out = {}
    for key, value in changes.items():
        if key not in FIELDS:
            raise PreferenceError("invalid", f"Unknown field {key!r}.")
        if key == "default_mode":
            if value is not None and value not in MODES:
                raise PreferenceError("invalid", "default_mode is not a mode.")
            out[key] = value or ""
        elif key == "discovery_level":
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 3:
                raise PreferenceError("invalid", "discovery_level is 0 to 3.")
            out[key] = value
        elif key == "languages":
            if not isinstance(value, list) or any(v not in LANGUAGES for v in value):
                raise PreferenceError("invalid", "languages are ar and en.")
            out[key] = sorted(set(value))
        elif key == "formats":
            if not isinstance(value, dict) or any(
                k not in FORMATS or v not in FORMAT_CHOICES for k, v in value.items()
            ):
                raise PreferenceError("invalid", "formats map a format to more or less.")
            out[key] = dict(value)
        elif key == "discovery_prefs":
            if not isinstance(value, dict) or any(
                k not in DISCOVERY_PREFS or not isinstance(v, bool) for k, v in value.items()
            ):
                raise PreferenceError("invalid", "discovery_prefs are booleans.")
            out[key] = dict(value)
        else:
            if not isinstance(value, bool):
                raise PreferenceError("invalid", f"{key} is true or false.")
            out[key] = value
    return out


# ---- writes ----------------------------------------------------------------------------


def _new_id() -> uuid.UUID:
    from tara_events.envelope import uuid7

    return uuid7()


def _locked(account_id) -> UserPreference:
    row, _ = UserPreference.objects.select_for_update().get_or_create(
        account_id=account_id, defaults={"version": 0}
    )
    return row


def _effective_search(st: dict) -> bool:
    return bool(st["search_signal"]) and not bool(st["personalization_off"])


def _emit_search_signal(account_id, enabled: bool, at: datetime) -> None:
    from django.conf import settings

    if not getattr(settings, "INTEL_EMIT_R4_EVENTS", True):
        return
    from feed.events import PRODUCER
    from feed.models import OutboxEvent

    from tara_events.envelope import EventEnvelope
    from tara_events.outbox import record_event

    record_event(
        OutboxEvent,
        EventEnvelope(
            event_type="intel.search_signal.changed",
            payload={"account_id": str(account_id), "enabled": enabled, "at": at.isoformat()},
            subject_id=str(account_id),
            producer=PRODUCER,
            partition_key=f"account:{account_id}",
        ),
    )


def purge_behaviour(account_id, reason: str) -> None:
    """Personalization off and Reset (WP 8.1, 8.4-B2): the account's visit rows now,
    its behavioural redis-hot keys after commit (fail-soft)."""
    from .. import hot

    with connection.cursor() as cur:
        cur.execute("DELETE FROM intel_feed_session WHERE account_id = %s", [str(account_id)])
    transaction.on_commit(lambda: hot.purge_behaviour(account_id, reason))


def _sensitive_inferred_off(account_id) -> int:
    with connection.cursor() as cur:
        cur.execute(
            "DELETE FROM intel_user_interest WHERE account_id = %s AND source = 'inferred' "
            "AND dim = 'topic' AND key IN (SELECT id::text FROM intel_topic WHERE sensitive)",
            [str(account_id)],
        )
        return cur.rowcount


def _apply(row: UserPreference, after: dict, *, now: datetime) -> None:
    for key, value in after.items():
        setattr(row, key, value)
    row.version = int(row.version) + 1
    row.save()


def _side_effects(account_id, before: dict, after: dict, now: datetime) -> None:
    from .. import interests

    if after.get("personalization_off") and not before.get("personalization_off"):
        purge_behaviour(account_id, "personalization_off")
    if before.get("sensitive_inference") and not after.get("sensitive_inference"):
        _sensitive_inferred_off(account_id)
    if _effective_search(before) != _effective_search(after):
        _emit_search_signal(account_id, _effective_search(after), now)
    interests.invalidate(account_id)


def patch(
    account_id,
    changes: dict,
    *,
    expected_version: int | None = None,
    source: str = PreferenceChange.Source.UI,
    now: datetime | None = None,
) -> tuple[UserPreference, PreferenceChange | None]:
    """Apply a validated subset. 409 (``StaleVersion``) when ``expected_version`` is
    older than the stored row. A no-op change writes nothing."""
    now = now or timezone.now()
    accepted = validate(changes)
    with transaction.atomic():
        row = _locked(account_id)
        if expected_version is not None and expected_version != row.version:
            raise StaleVersion(row.version)
        before = state(row)
        after = {**before, **accepted}
        if "discovery_prefs" in accepted:
            after["discovery_prefs"] = {**before["discovery_prefs"], **accepted["discovery_prefs"]}
        if after == before:
            return row, None
        stored = {k: after[k] for k in FIELDS}
        stored["default_mode"] = stored["default_mode"] or ""
        _apply(row, stored, now=now)
        change = PreferenceChange.objects.create(
            id=_new_id(),
            account_id=account_id,
            source=source,
            ops=[
                {"op": "set", "field": k, "value": after[k]}
                for k in FIELDS
                if after[k] != before[k]
            ],
            before=before,
            after=after,
            created_at=now,
        )
        _side_effects(account_id, before, after, now)
    return row, change


def undo(account_id, change_id, *, now: datetime | None = None):
    """Restore the fields one change moved (``source`` undo). None when the change is
    not the caller's, already undone, or not undoable (a reset)."""
    now = now or timezone.now()
    with transaction.atomic():
        change = (
            PreferenceChange.objects.select_for_update()
            .filter(id=change_id, account_id=account_id, undone_by__isnull=True)
            .exclude(source__in=(PreferenceChange.Source.RESET, PreferenceChange.Source.UNDO))
            .first()
        )
        if change is None:
            return None
        moved = {op["field"] for op in change.ops if op.get("field") in FIELDS}
        restore = {k: change.before[k] for k in moved}
        row, new = patch(account_id, restore, source=PreferenceChange.Source.UNDO, now=now)
        marker = new.id if new is not None else _new_id()
        PreferenceChange.objects.filter(pk=change.pk).update(undone_by=marker)
        if change.source == PreferenceChange.Source.ONBOARDING:
            _undo_onboarding(account_id, change)
    return row, new


# ---- onboarding (WP 6.6) ----------------------------------------------------------------


def onboard(account_id, slugs: list[str], skipped: bool, *, now: datetime | None = None):
    """The optional topic picker after sign-up (decision 11): explicit rows for the chosen
    topics, ``onboarded_at`` set either way. Topic ids in ``ops`` let an undo remove them."""
    from .. import interests
    from ..models import Topic

    now = now or timezone.now()
    cfg = _home_cfg()
    limit = int(cfg.get("cold_start.max_topics"))
    polarity = cfg.get("cold_start.explicit_polarity")
    slugs = [] if skipped else list(dict.fromkeys(slugs or []))
    if len(slugs) > limit:
        raise PreferenceError("invalid", f"At most {limit} topics.")
    topics = dict(Topic.objects.filter(slug__in=slugs, status="active").values_list("slug", "id"))
    if len(topics) != len(slugs):
        raise PreferenceError("invalid_topic", "Unknown topic.")
    with transaction.atomic():
        row = _locked(account_id)
        before = state(row)
        for slug in slugs:
            interests.set_explicit(account_id, "topic", str(topics[slug]), polarity, now)
        row.onboarded_at = row.onboarded_at or now
        row.version = int(row.version) + 1
        row.save()
        change = PreferenceChange.objects.create(
            id=_new_id(),
            account_id=account_id,
            source=PreferenceChange.Source.ONBOARDING,
            ops=[{"op": "explicit", "topic_id": topics[s], "polarity": polarity} for s in slugs],
            before=before,
            after=state(row),
            created_at=now,
        )
    return row, change


def _undo_onboarding(account_id, change: PreferenceChange) -> None:
    from .. import interests

    ids = [str(op["topic_id"]) for op in change.ops if op.get("op") == "explicit"]
    UserInterest.objects.filter(
        account_id=account_id, dim="topic", key__in=ids, source="explicit"
    ).delete()
    interests.invalidate(account_id)


# ---- debug consent (WP 8.1, decision 17) -------------------------------------------------


def grant_consent(account_id, *, now: datetime | None = None) -> DebugConsent:
    now = now or timezone.now()
    hours = int(_home_cfg().get("retention.debug_consent_ttl_h"))
    with transaction.atomic():
        DebugConsent.objects.filter(
            account_id=account_id, revoked_at__isnull=True, expires_at__gt=now
        ).update(revoked_at=now)
        return DebugConsent.objects.create(
            id=_new_id(),
            account_id=account_id,
            granted_at=now,
            expires_at=now + timedelta(hours=hours),
        )


def revoke_consent(account_id, *, now: datetime | None = None) -> int:
    now = now or timezone.now()
    return DebugConsent.objects.filter(
        account_id=account_id, revoked_at__isnull=True, expires_at__gt=now
    ).update(revoked_at=now)


# ---- reset recommendations (WP 8.4-B2) -------------------------------------------------


def reset_request(account_id, *, now: datetime | None = None) -> dict:
    """Step 1: a short-lived confirm token, and what the reset deletes and keeps."""
    now = now or timezone.now()
    ttl = int(_home_cfg().get("reset.confirm_ttl_s"))
    token = signing.dumps({"a": str(account_id), "n": uuid.uuid4().hex}, salt=_RESET_SALT)
    return {
        "confirm_token": token,
        "expires_in_s": ttl,
        "scope": list(RESET_SCOPE),
        "keeps": list(RESET_KEEPS),
    }


def _emit_reset(account_id, at: datetime) -> None:
    from django.conf import settings

    if not getattr(settings, "INTEL_EMIT_R4_EVENTS", True):
        return
    from feed.events import PRODUCER
    from feed.models import OutboxEvent

    from tara_events.envelope import EventEnvelope
    from tara_events.outbox import record_event

    record_event(
        OutboxEvent,
        EventEnvelope(
            event_type="feed.recommendations.reset",
            payload={"account_id": str(account_id), "reset_at": at.isoformat()},
            subject_id=str(account_id),
            producer=PRODUCER,
            partition_key=f"account:{account_id}",
        ),
    )


def reset_confirm(account_id, token: str, *, now: datetime | None = None) -> dict:
    """Step 2: set ``reset_at`` (throttled to one per ``reset.min_interval_h``), log it,
    emit ``feed.recommendations.reset`` and queue the deletion task, in one transaction.
    Not undoable (the dialog says so)."""
    now = now or timezone.now()
    cfg = _home_cfg()
    ttl = int(cfg.get("reset.confirm_ttl_s"))
    try:
        data = signing.loads(token or "", salt=_RESET_SALT, max_age=ttl)
    except signing.BadSignature as exc:
        raise PreferenceError("invalid_token", "The confirmation expired; ask again.") from exc
    if not isinstance(data, dict) or data.get("a") != str(account_id):
        raise PreferenceError("invalid_token", "The confirmation expired; ask again.")
    hours = int(cfg.get("reset.min_interval_h"))
    with transaction.atomic():
        row = _locked(account_id)
        if row.reset_at and row.reset_at + timedelta(hours=hours) > now:
            wait = int((row.reset_at + timedelta(hours=hours) - now).total_seconds()) + 1
            raise PreferenceError("throttled", "One reset per day.", retry_after=wait)
        before = state(row)
        row.reset_at = now
        row.version = int(row.version) + 1
        row.save()
        PreferenceChange.objects.create(
            id=_new_id(),
            account_id=account_id,
            source=PreferenceChange.Source.RESET,
            ops=[{"op": "reset", "scope": list(RESET_SCOPE)}],
            before=before,
            after=before,
            created_at=now,
        )
        _emit_reset(account_id, now)
        purge_behaviour(account_id, "reset")

        def queue():
            from ..tasks import reset_recommendations

            reset_recommendations.delay(str(account_id), now.isoformat())

        transaction.on_commit(queue)
    return {
        "reset_at": now.isoformat(),
        "next_allowed_at": (now + timedelta(hours=hours)).isoformat(),
    }


def run_reset(account_id, reset_at: datetime) -> dict:
    """The asynchronous part (Celery ``intel.reset_recommendations``): one ``DELETE`` per
    weekly partition of ``intel_user_item_engagement``, the inferred interest rows, the
    decayed affinity (``affinity``, back to the fan-out prior), the visit rows and the
    behavioural keys. Kept: explicit rows (topics, mutes, hidden creators, suppressed
    markers), follows, blocks, hides and item-level feedback rows."""
    from .. import hot
    from ..signals import partitions

    account = str(account_id)
    out = {"engagement": 0, "interests": 0, "affinity": 0, "feed_session": 0}
    with transaction.atomic(), connection.cursor() as cur:
        for table, _start in partitions.partitions(partitions.ENGAGEMENT):
            cur.execute(f"DELETE FROM {table} WHERE account_id = %s", [account])  # noqa: S608
            out["engagement"] += cur.rowcount
        cur.execute(
            "DELETE FROM intel_user_interest WHERE account_id = %s AND source = 'inferred'",
            [account],
        )
        out["interests"] = cur.rowcount
        cur.execute("DELETE FROM affinity WHERE account_id = %s", [account])
        out["affinity"] = cur.rowcount
        cur.execute("DELETE FROM intel_feed_session WHERE account_id = %s", [account])
        out["feed_session"] = cur.rowcount
    out["keys_purged"] = hot.purge_behaviour(account, "reset")
    return out
