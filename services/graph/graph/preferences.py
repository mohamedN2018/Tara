"""Owner-private relationship preferences: mute, restrict and favorites (plan 08, 2D).

Each one is a one-way edge only its owner can list or change, and none of them
tells the other account anything: no notification, no event that a notifier
consumes. Feed consumes ``relationship.muted``/``unmuted`` (hide their posts)
and ``relationship.favorited``/``unfavorited`` (rank them first); post is meant
to consume ``relationship.restricted``/``unrestricted`` and, until it does, can
read the restricted set from ``/internal/v1/preferences/<account_id>/``.

Every change and its event are written in one transaction, so a failed outbox
write leaves the edge unchanged. Mute and favorite exclude each other: muting a
favorite removes the favorite (and emits ``relationship.unfavorited``), and the
other way round.

All writes for one owner run one at a time behind a transaction-scoped
advisory lock (``_lock_owner``). Without it, a concurrent mute and favorite of
the same account could each miss the other's uncommitted row and leave both
edges stored, and concurrent favorites could pass ``MAX_FAVORITES``.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings
from django.db import IntegrityError, connection, transaction
from django.db.models import Model
from django.utils import timezone

from tara_common.exceptions import TaraAPIError

from . import events
from .models import FavoriteRelation, MuteRelation, RestrictRelation

#: Facebook-style cap: favorites only work as "first in my feed" while short.
MAX_FAVORITES = 30


@dataclass(frozen=True)
class Kind:
    model: type[Model]
    added: str
    removed: str
    flag: str


KINDS: dict[str, Kind] = {
    "mute": Kind(
        MuteRelation,
        "relationship.muted",
        "relationship.unmuted",
        "GRAPH_EMIT_MUTE_FAVORITE_EVENTS",
    ),
    "favorite": Kind(
        FavoriteRelation,
        "relationship.favorited",
        "relationship.unfavorited",
        "GRAPH_EMIT_MUTE_FAVORITE_EVENTS",
    ),
    "restrict": Kind(
        RestrictRelation,
        "relationship.restricted",
        "relationship.unrestricted",
        "GRAPH_EMIT_RESTRICT_EVENTS",
    ),
}

#: Adding one of these removes the other (a muted favorite makes no sense).
EXCLUSIVE = {"mute": "favorite", "favorite": "mute"}


def _emit(kind: Kind, event_type: str, actor_id: str, target_id: str) -> None:
    if not getattr(settings, kind.flag, True):
        return
    events.emit(
        event_type,
        subject_id=actor_id,
        payload={
            "actor_id": actor_id,
            "target_id": target_id,
            "occurred_at": timezone.now().isoformat(),
        },
        actor_id=actor_id,
    )


def _lock_owner(*owner_ids: str) -> None:
    """Serialise preference writes per owner until the transaction ends. Locks
    are taken in sorted order so two multi-owner callers cannot deadlock.
    Statements issued after this get a fresh READ COMMITTED snapshot, so they
    see whatever an earlier holder committed. Must run inside a transaction."""
    with connection.cursor() as cursor:
        for owner_id in sorted({str(o) for o in owner_ids}):
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", [f"graph-pref:{owner_id}"])


def _remove(name: str, actor_id: str, target_id: str) -> bool:
    """Delete one edge; emit the removal only if a row actually went away, so
    concurrent callers emit it once. Must run inside a transaction."""
    kind = KINDS[name]
    deleted, _ = kind.model.objects.filter(account_id=actor_id, target_id=target_id).delete()
    if deleted:
        _emit(kind, kind.removed, actor_id, target_id)
    return bool(deleted)


def add(name: str, actor_id: str, target_id: str) -> bool:
    """Mute, restrict or favorite ``target_id``. Idempotent: returns ``False``
    (and emits nothing) when the edge already exists."""
    from .services import is_blocked

    actor_id, target_id = str(actor_id), str(target_id)
    if actor_id == target_id:
        raise TaraAPIError(
            "You cannot do that to yourself.", code="validation_error", http_status_code=400
        )
    kind = KINDS[name]
    with transaction.atomic():
        _lock_owner(actor_id)
        # Checked under the lock: block() takes it too (in on_block), so a
        # block committed meanwhile is seen here instead of racing a favorite.
        if is_blocked(actor_id, target_id):
            # A blocked account does not exist for the actor.
            raise TaraAPIError("Resource not found.", code="not_found", http_status_code=404)
        if kind.model.objects.filter(account_id=actor_id, target_id=target_id).exists():
            return False
        if (
            name == "favorite"
            and FavoriteRelation.objects.filter(account_id=actor_id).count() >= MAX_FAVORITES
        ):
            raise TaraAPIError(
                f"You can have at most {MAX_FAVORITES} favorites.",
                code="favorites_limit",
                http_status_code=400,
            )
        try:
            with transaction.atomic():  # a savepoint: a lost race is not an error
                kind.model.objects.create(account_id=actor_id, target_id=target_id)
        except IntegrityError:
            return False
        if name in EXCLUSIVE:
            _remove(EXCLUSIVE[name], actor_id, target_id)
        _emit(kind, kind.added, actor_id, target_id)
    return True


def remove(name: str, actor_id: str, target_id: str) -> bool:
    with transaction.atomic():
        _lock_owner(actor_id)
        return _remove(name, str(actor_id), str(target_id))


def target_ids(name: str, actor_id: str) -> list[str]:
    """The owner's list, newest first, minus accounts with a block either way
    (the edge stays stored, so an unblock brings it back)."""
    from .services import _unblocked

    rows = (
        KINDS[name]
        .model.objects.filter(account_id=actor_id)
        .filter(_unblocked("target_id", (str(actor_id),)))
        .order_by("-created_at")
        .values_list("target_id", flat=True)
    )
    return [str(x) for x in rows]


def on_block(actor_id: str, target_id: str) -> None:
    """A block ends favorites both ways (feed stops ranking them first). Mutes
    and restrictions stay stored, so an unblock does not silently undo them.
    Runs inside block()'s transaction."""
    _lock_owner(actor_id, target_id)
    for owner, other in ((actor_id, target_id), (target_id, actor_id)):
        _remove("favorite", str(owner), str(other))


def snapshot(account_id: str) -> dict:
    """Everything feed and post need about one owner's preferences."""
    return {
        "account_id": str(account_id),
        "muted": target_ids("mute", account_id),
        "favorites": target_ids("favorite", account_id),
        "restricted": target_ids("restrict", account_id),
    }
