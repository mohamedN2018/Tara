"""Events business logic: visibility, create/edit/cancel/delete, RSVP, invites,
attendee lists, reports, moderation and reminders.

Rules (roadmap 1.13 and section 3.3):

* **One visibility rule** (``visible_to_viewer`` for one event, ``visible_filter``
  for lists, the same rule in SQL so lists filter before paging). A hidden
  event is 404, never 403. Deleted and moderator-removed events are hidden from
  everyone, the host included. Blocks hide the event both ways.
  - ``public``: everyone else.
  - ``friends``: the host's friends (graph).
  - ``invite_only``: the host, invitees and anyone who has an RSVP row.
* **The host does not RSVP** (decision): the host is the organiser, is never
  counted in ``going_count`` and never takes a capacity seat; an RSVP from the
  host is 400 ``host_cannot_rsvp``. The host still gets the reminders.
* **Capacity** counts ``going`` only. Every RSVP write locks the event row
  first, so two last-seat requests can never both win; the loser gets 409
  ``event_full``. There is no waitlist.
* **Remote calls before the write transaction** (graph, media), as in posts.
* **Events on the bus carry ids and enums only.** Recipient lists are chunked
  (``RECIPIENT_CHUNK`` ids per event).
"""

from __future__ import annotations

import logging
import zoneinfo
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from django.db import IntegrityError, transaction
from django.db.models import DateTimeField, ExpressionWrapper, F, Q
from django.db.models.functions import Coalesce
from django.utils import timezone
from posts import events, media_client
from posts.clients import get_relationship
from posts.models import BlockedPair, PostMedia

from tara_common.exceptions import TaraAPIError
from tara_events.envelope import uuid7

from . import graph
from .models import (
    MAX_CAPACITY,
    Gathering,
    GatheringInvite,
    GatheringReminderLog,
    GatheringReport,
    GatheringRSVP,
    ReportReason,
    RSVPStatus,
)

logger = logging.getLogger("tara.post.gatherings")

RECIPIENT_CHUNK = 500
MAX_INVITES_PER_CALL = 50
# An event with no end time counts as running for this long (lists, "ended").
DEFAULT_DURATION = timedelta(hours=3)
MAX_HORIZON = timedelta(days=2 * 365)
MAX_SEARCH = 100
_ATTACHABLE_STATUSES = {"processing", "ready"}
# Changes the people coming must hear about.
SCHEDULE_FIELDS = frozenset(
    {"starts_at", "ends_at", "timezone", "location_type", "location", "online_url"}
)
EDITABLE_FIELDS = (
    "title",
    "description",
    "starts_at",
    "ends_at",
    "timezone",
    "location_type",
    "location",
    "online_url",
    "cover_media_id",
    "audience",
    "capacity",
)
# (window, remind when the start is at most this far away, ... and further than this)
REMINDER_WINDOWS = (
    (GatheringReminderLog.Window.DAY, timedelta(hours=24), timedelta(hours=2)),
    (GatheringReminderLog.Window.HOUR, timedelta(hours=1), timedelta(0)),
)
REMINDER_BATCH = 200
SCOPES = ("upcoming", "past", "hosting", "going", "invited")
ATTENDEE_STATES = ("going", "interested", "not_going", "invited")
HOST_ONLY_STATES = frozenset({"not_going", "invited"})

_EFFECTIVE_END = Coalesce(
    "ends_at",
    ExpressionWrapper(F("starts_at") + DEFAULT_DURATION, output_field=DateTimeField()),
)


# ---- errors ----------------------------------------------------------------------


def _not_found() -> TaraAPIError:
    return TaraAPIError("Event not found.", code="not_found", http_status_code=404)


def _bad_request(message: str, code: str = "validation_error") -> TaraAPIError:
    return TaraAPIError(message, code=code, http_status_code=400)


def _conflict(message: str, code: str) -> TaraAPIError:
    return TaraAPIError(message, code=code, http_status_code=409)


def _forbidden(message: str) -> TaraAPIError:
    return TaraAPIError(message, code="permission_denied", http_status_code=403)


# ---- time ------------------------------------------------------------------------


def effective_end(g: Gathering) -> datetime:
    return g.ends_at or g.starts_at + DEFAULT_DURATION


def effective_status(g: Gathering, now: datetime | None = None) -> str:
    """``scheduled`` turns into ``ended`` as soon as the end passes, before the
    beat task stores it."""
    if g.status == Gathering.Status.SCHEDULED and effective_end(g) < (now or timezone.now()):
        return Gathering.Status.ENDED
    return g.status


def _require_open(g: Gathering) -> None:
    status = effective_status(g)
    if status == Gathering.Status.CANCELLED:
        raise _conflict("The event was cancelled.", "event_cancelled")
    if status == Gathering.Status.ENDED:
        raise _conflict("The event has ended.", "event_ended")


# ---- visibility ------------------------------------------------------------------


def _blocked_either_way(a: str, b: str) -> bool:
    return BlockedPair.objects.filter(
        Q(blocker_id=a, blocked_id=b) | Q(blocker_id=b, blocked_id=a)
    ).exists()


def blocked_ids(account_id: str) -> set[str]:
    """Accounts blocked by, or blocking, the account."""
    pairs = BlockedPair.objects.filter(
        Q(blocker_id=account_id) | Q(blocked_id=account_id)
    ).values_list("blocker_id", "blocked_id")
    return {str(a) for pair in pairs for a in pair} - {str(account_id)}


def visible_to_viewer(
    viewer_id: str,
    g: Gathering,
    *,
    friends: set[str] | None = None,
    blocked: set[str] | None = None,
) -> bool:
    """The single rule. ``friends``/``blocked`` avoid lookups when checking many."""
    if not g.is_visible:
        return False
    viewer, host = str(viewer_id), str(g.host_id)
    if viewer == host:
        return True
    if blocked is None:
        if _blocked_either_way(viewer, host):
            return False
    elif host in blocked:
        return False
    if g.audience == Gathering.Audience.PUBLIC:
        return True
    if g.audience == Gathering.Audience.FRIENDS:
        if friends is not None:
            return host in friends
        rel = get_relationship(viewer, host)  # graph down: not friends (fail closed)
        return rel.are_friends and not rel.blocked_either_way
    if g.audience == Gathering.Audience.INVITE_ONLY:
        return (
            GatheringInvite.objects.filter(gathering=g, invitee_id=viewer).exists()
            or GatheringRSVP.objects.filter(gathering=g, account_id=viewer).exists()
        )
    return False


def visible_filter(viewer_id: str, friends: set[str]) -> Q:
    """``visible_to_viewer`` as SQL (blocks are excluded separately)."""
    invited = GatheringInvite.objects.filter(invitee_id=viewer_id).values("gathering_id")
    answered = GatheringRSVP.objects.filter(account_id=viewer_id).values("gathering_id")
    return (
        Q(host_id=viewer_id)
        | Q(audience=Gathering.Audience.PUBLIC)
        | Q(audience=Gathering.Audience.FRIENDS, host_id__in=list(friends))
        | Q(audience=Gathering.Audience.INVITE_ONLY, id__in=invited)
        | Q(audience=Gathering.Audience.INVITE_ONLY, id__in=answered)
    )


def require_visible(viewer_id: str, gathering_id) -> Gathering:
    g = Gathering.objects.filter(id=gathering_id).first()
    if g is None or not visible_to_viewer(viewer_id, g):
        raise _not_found()
    return g


def get_gathering(viewer_id: str, gathering_id) -> Gathering:
    return require_visible(viewer_id, gathering_id)


def _live() -> Q:
    return Q(deleted_at__isnull=True, moderation_status=Gathering.ModerationStatus.OK)


def list_queryset(viewer_id: str, scope: str, *, q: str = ""):
    """Keyset-ordered events for one tab, already filtered by visibility in SQL."""
    if scope not in SCOPES:
        raise _bad_request(f"scope must be one of {', '.join(SCOPES)}.")
    viewer = str(viewer_id)
    now = timezone.now()
    base = Gathering.objects.filter(_live()).annotate(effective_end=_EFFECTIVE_END)
    q = (q or "").strip()[:MAX_SEARCH]
    if q:
        base = base.filter(title__icontains=q)
    if scope == "hosting":
        return base.filter(host_id=viewer, effective_end__gte=now).order_by("starts_at", "id")

    # Graph down: no friends, so friends-only events of others drop out (fail closed).
    friends = graph.friend_ids(viewer) or set()
    visible = base.filter(visible_filter(viewer, friends)).exclude(
        host_id__in=list(blocked_ids(viewer))
    )
    mine = GatheringRSVP.objects.filter(
        account_id=viewer, status__in=(RSVPStatus.GOING, RSVPStatus.INTERESTED)
    ).values("gathering_id")
    if scope == "upcoming":
        qs = visible.filter(status=Gathering.Status.SCHEDULED, effective_end__gte=now)
    elif scope == "going":
        qs = visible.filter(id__in=mine, effective_end__gte=now)
    elif scope == "invited":
        invited = GatheringInvite.objects.filter(invitee_id=viewer).values("gathering_id")
        qs = visible.filter(id__in=invited, effective_end__gte=now).exclude(host_id=viewer)
    else:  # past: what the viewer hosted or meant to attend
        return visible.filter(Q(host_id=viewer) | Q(id__in=mine), effective_end__lt=now).order_by(
            "-starts_at", "-id"
        )
    return qs.order_by("starts_at", "id")


def viewer_state(viewer_id: str, gatherings: list[Gathering]) -> dict:
    ids = [g.id for g in gatherings]
    return {
        "rsvp": dict(
            GatheringRSVP.objects.filter(gathering_id__in=ids, account_id=viewer_id).values_list(
                "gathering_id", "status"
            )
        ),
        "invited": set(
            GatheringInvite.objects.filter(gathering_id__in=ids, invitee_id=viewer_id).values_list(
                "gathering_id", flat=True
            )
        ),
    }


# ---- validation ------------------------------------------------------------------


def validate_url(url: str) -> str:
    """http(s) only, with a host and no whitespace or control characters."""
    url = (url or "").strip()
    if not url:
        return ""
    if any(c.isspace() or ord(c) < 32 for c in url):
        raise _bad_request("The link is not valid.", "invalid_url")
    try:
        parts = urlsplit(url)
    except ValueError as exc:
        raise _bad_request("The link is not valid.", "invalid_url") from exc
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        raise _bad_request("Only http and https links are allowed.", "invalid_url")
    return url


def validate_timezone(name: str) -> str:
    name = (name or "UTC").strip()
    try:
        zoneinfo.ZoneInfo(name)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError) as exc:
        raise _bad_request("Unknown time zone.", "invalid_timezone") from exc
    return name


def _validate(values: dict, *, going_count: int = 0, check_start: bool = True) -> None:
    """Rules across fields, for a new event or the merged state of an edit."""
    now = timezone.now()
    starts, ends = values["starts_at"], values.get("ends_at")
    if check_start and starts <= now:
        raise _bad_request("The event must start in the future.", "starts_in_past")
    if starts > now + MAX_HORIZON:
        raise _bad_request("The event starts too far ahead.", "starts_too_far")
    if ends is not None and ends < starts:
        raise _bad_request("The event must end after it starts.", "ends_before_start")
    if values["location_type"] == Gathering.LocationType.ONLINE:
        if not values.get("online_url"):
            raise _bad_request("An online event needs a link.", "online_url_required")
    elif not (values.get("location") or "").strip():
        raise _bad_request("An event needs a place or a link.", "location_required")
    capacity = values.get("capacity")
    if capacity is not None:
        if capacity < 1 or capacity > MAX_CAPACITY:
            raise _bad_request("Capacity is out of range.")
        if capacity < going_count:
            raise _bad_request(
                "Capacity cannot be lower than the people already going.", "capacity_below_going"
            )
    if values["audience"] not in Gathering.Audience.values:
        raise _bad_request("Invalid audience.")


def _check_cover(host_id: str, gathering_id: str, media_id: str) -> None:
    """The host's own image, uploaded, and on no live post or other event. Then
    bound to the event and restricted: media asks post (the same visibility
    endpoint as posts) before it serves the cover to anyone but the host.
    Remote calls: run before the write transaction."""
    info = media_client.lookup([media_id]).get(media_id)
    if info is None or info.owner_id != str(host_id):
        raise _bad_request("Media not found.", "media_not_owned")
    if info.kind != "image":
        raise _bad_request("Only an image can be an event cover.", "media_kind_not_allowed")
    if info.status not in _ATTACHABLE_STATUSES:
        raise _bad_request("Media upload is not complete.", "media_not_ready")
    on_post = PostMedia.objects.filter(media_id=media_id, post__deleted_at__isnull=True).exists()
    on_event = (
        Gathering.objects.filter(cover_media_id=media_id, deleted_at__isnull=True)
        .exclude(id=gathering_id)
        .exists()
    )
    if on_post or on_event:
        raise _bad_request("Media is already attached elsewhere.", "media_already_attached")
    result = media_client.bind(str(host_id), str(gathering_id), [media_id], restricted=True)
    if result.attached_elsewhere:
        raise _bad_request("Media is already attached elsewhere.", "media_already_attached")
    if result.skipped:
        raise _bad_request("Media not found.", "media_not_owned")


# ---- events on the bus -----------------------------------------------------------


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _core_payload(g: Gathering) -> dict:
    return {
        "gathering_id": str(g.id),
        "host_id": str(g.host_id),
        "host_type": g.host_type,
        "audience": g.audience,
        "status": g.status,
        "location_type": g.location_type,
        "starts_at": _iso(g.starts_at),
        "ends_at": _iso(g.ends_at),
        "capacity": g.capacity,
        "cover_media_id": str(g.cover_media_id) if g.cover_media_id else None,
    }


def _emit(event_type: str, g: Gathering, payload: dict, *, actor_id: str | None = None) -> None:
    events.emit(
        event_type,
        subject_id=str(g.id),
        payload=payload,
        actor_id=str(actor_id or g.host_id),
        partition_key=f"gathering:{g.id}",
    )


def _emit_to(event_type: str, g: Gathering, payload: dict, recipients: list[str], **kw) -> None:
    """One event per ``RECIPIENT_CHUNK`` recipients (one event when there are none)."""
    chunks = [
        recipients[i : i + RECIPIENT_CHUNK] for i in range(0, len(recipients), RECIPIENT_CHUNK)
    ] or [[]]
    for index, chunk in enumerate(chunks):
        _emit(
            event_type,
            g,
            {**payload, "recipients": chunk, "chunk": index, "chunks": len(chunks)},
            **kw,
        )


def _attendees(g: Gathering, states=(RSVPStatus.GOING, RSVPStatus.INTERESTED)) -> list[str]:
    """Accounts with one of ``states``, never one blocked either way with the host."""
    blocked = blocked_ids(str(g.host_id))
    ids = GatheringRSVP.objects.filter(gathering=g, status__in=states).order_by("created_at", "id")
    return [str(a) for a in ids.values_list("account_id", flat=True) if str(a) not in blocked]


# ---- create, edit, cancel, delete ------------------------------------------------


def create_gathering(host_id: str, **values) -> Gathering:
    """``values`` come from ``GatheringCreateSerializer``. The cover is checked and
    bound through media first (503 when media is down, nothing written)."""
    values["timezone"] = validate_timezone(values.get("timezone") or "UTC")
    values["online_url"] = validate_url(values.get("online_url") or "")
    _validate(values)
    gathering_id = uuid7()
    cover = values.get("cover_media_id")
    if cover:
        _check_cover(host_id, str(gathering_id), str(cover))
    with transaction.atomic():
        g = Gathering.objects.create(
            id=gathering_id,
            host_id=host_id,
            title=values["title"].strip(),
            description=values.get("description") or "",
            starts_at=values["starts_at"],
            ends_at=values.get("ends_at"),
            timezone=values["timezone"],
            location_type=values["location_type"],
            location=(values.get("location") or "").strip(),
            online_url=values["online_url"],
            cover_media_id=cover,
            audience=values["audience"],
            capacity=values.get("capacity"),
        )
        _emit("gathering.created", g, _core_payload(g))
    return g


def _hosted(host_id: str, gathering_id, *, lock: bool = False) -> Gathering:
    """The host's own live event; anything else is 404 (a non-host cannot tell
    a hidden event from one they cannot edit)."""
    qs = Gathering.objects.filter(id=gathering_id, host_id=host_id).filter(_live())
    g = (qs.select_for_update() if lock else qs).first()
    if g is None:
        raise _not_found()
    return g


def edit_gathering(host_id: str, gathering_id, changes: dict) -> Gathering:
    """Host only. A change of time or place tells everyone going or interested
    (``gathering.updated`` with recipients); a new start time resets reminders."""
    changes = {k: v for k, v in changes.items() if k in EDITABLE_FIELDS}
    if not changes:
        raise _bad_request("Nothing to change.")
    g = _hosted(host_id, gathering_id)
    _require_open(g)
    if "timezone" in changes:
        changes["timezone"] = validate_timezone(changes["timezone"])
    if "online_url" in changes:
        changes["online_url"] = validate_url(changes["online_url"] or "")
    for key in ("title", "location"):
        if key in changes:
            changes[key] = (changes[key] or "").strip()
    if changes.get("title") == "":
        raise _bad_request("A title is required.")
    merged = {f: changes.get(f, getattr(g, f)) for f in EDITABLE_FIELDS}
    _validate(
        merged,
        going_count=g.going_count,
        check_start="starts_at" in changes and changes["starts_at"] != g.starts_at,
    )
    cover = changes.get("cover_media_id")
    if cover and cover != g.cover_media_id:
        _check_cover(host_id, str(g.id), str(cover))

    with transaction.atomic():
        g = _hosted(host_id, gathering_id, lock=True)  # removed meanwhile: 404
        _require_open(g)
        if "capacity" in changes and changes["capacity"] is not None:
            if changes["capacity"] < g.going_count:  # filled up since the check
                raise _bad_request(
                    "Capacity cannot be lower than the people already going.",
                    "capacity_below_going",
                )
        changed = sorted(f for f, v in changes.items() if getattr(g, f) != v)
        if not changed:
            return g
        for field in changed:
            setattr(g, field, changes[field])
        g.save(update_fields=[*changed, "updated_at"])
        if "starts_at" in changed:
            GatheringReminderLog.objects.filter(gathering=g).delete()
        notify = sorted(SCHEDULE_FIELDS.intersection(changed))
        _emit_to(
            "gathering.updated",
            g,
            {**_core_payload(g), "changed": changed, "notify": notify},
            _attendees(g) if notify else [],
        )
    return g


def cancel_gathering(host_id: str, gathering_id) -> Gathering:
    """Host only, once. Everyone going or interested is told."""
    with transaction.atomic():
        g = _hosted(host_id, gathering_id, lock=True)
        _require_open(g)
        g.status = Gathering.Status.CANCELLED
        g.cancelled_at = timezone.now()
        g.save(update_fields=["status", "cancelled_at", "updated_at"])
        _emit_to("gathering.cancelled", g, _core_payload(g), _attendees(g))
    return g


def delete_gathering(host_id: str, gathering_id) -> None:
    with transaction.atomic():
        g = _hosted(host_id, gathering_id, lock=True)
        g.deleted_at = timezone.now()
        g.save(update_fields=["deleted_at", "updated_at"])
        _emit("gathering.deleted", g, {"gathering_id": str(g.id), "host_id": str(g.host_id)})


# ---- RSVP ------------------------------------------------------------------------

_COUNTERS = {RSVPStatus.GOING: "going_count", RSVPStatus.INTERESTED: "interested_count"}


def _bump(g: Gathering, status: str | None, delta: int) -> None:
    field = _COUNTERS.get(status)
    if field:
        setattr(g, field, max(0, getattr(g, field) + delta))


def _write_rsvp(viewer_id: str, gathering_id, status: str | None) -> Gathering:
    """Set (``status``) or remove (``None``) the viewer's answer under the event's
    row lock. Same answer again: nothing changes and nothing is emitted."""
    g = require_visible(viewer_id, gathering_id)  # may call graph: before the lock
    if str(g.host_id) == str(viewer_id):
        raise _bad_request("The host does not RSVP to their own event.", "host_cannot_rsvp")
    with transaction.atomic():
        g = Gathering.objects.select_for_update().filter(id=g.id).first()
        if g is None or not g.is_visible:
            raise _not_found()
        _require_open(g)
        current = GatheringRSVP.objects.filter(gathering=g, account_id=viewer_id).first()
        previous = current.status if current else None
        if previous == status:
            return g
        if status == RSVPStatus.GOING and g.capacity is not None and g.going_count >= g.capacity:
            raise _conflict("The event is full.", "event_full")
        _bump(g, previous, -1)
        _bump(g, status, +1)
        g.save(update_fields=["going_count", "interested_count"])
        if status is None:
            current.delete()
        elif current is None:
            GatheringRSVP.objects.create(gathering=g, account_id=viewer_id, status=status)
        else:
            current.status = status
            current.save(update_fields=["status", "updated_at"])
        _emit(
            "gathering.rsvp",
            g,
            {
                "gathering_id": str(g.id),
                "host_id": str(g.host_id),
                "account_id": str(viewer_id),
                "status": status,
                "previous_status": previous,
                "going_count": g.going_count,
                "interested_count": g.interested_count,
            },
            actor_id=str(viewer_id),
        )
    return g


def rsvp(viewer_id: str, gathering_id, status: str) -> Gathering:
    if status not in RSVPStatus.values:
        raise _bad_request("Invalid RSVP status.")
    return _write_rsvp(viewer_id, gathering_id, status)


def withdraw_rsvp(viewer_id: str, gathering_id) -> Gathering:
    return _write_rsvp(viewer_id, gathering_id, None)


# ---- invites ---------------------------------------------------------------------


def invite(host_id: str, gathering_id, account_ids: list) -> list[str]:
    """The host invites friends only (graph is asked; 503 when it cannot answer).
    Returns the newly invited ids; people already invited are skipped quietly."""
    host = str(host_id)
    ids = list(dict.fromkeys(str(a) for a in account_ids if str(a) != host))
    if not ids:
        raise _bad_request("Choose at least one friend to invite.")
    if len(ids) > MAX_INVITES_PER_CALL:
        raise _bad_request(f"At most {MAX_INVITES_PER_CALL} invites at a time.")
    g = require_visible(host, gathering_id)
    if str(g.host_id) != host:
        raise _forbidden("Only the host can invite.")
    _require_open(g)
    friends = graph.friend_ids(host)
    if friends is None:
        raise TaraAPIError(
            "Friends cannot be checked right now; try again.",
            code="dependency_unavailable",
            http_status_code=503,
        )
    blocked = blocked_ids(host)
    if any(i not in friends or i in blocked for i in ids):
        raise _bad_request("You can only invite your friends.", "invite_not_friend")
    with transaction.atomic():
        g = _hosted(host, gathering_id, lock=True)
        _require_open(g)
        existing = {
            str(i)
            for i in GatheringInvite.objects.filter(gathering=g, invitee_id__in=ids).values_list(
                "invitee_id", flat=True
            )
        }
        new = [i for i in ids if i not in existing]
        GatheringInvite.objects.bulk_create(
            GatheringInvite(gathering=g, invitee_id=i, inviter_id=host) for i in new
        )
        if new:
            _emit(
                "gathering.invited",
                g,
                {"gathering_id": str(g.id), "host_id": host, "invitee_ids": new},
            )
    return new


# ---- attendee lists --------------------------------------------------------------


def attendees_queryset(viewer_id: str, gathering_id, state: str):
    """Going and interested are listed to anyone who can see the event; not going
    and invited to the host only. Accounts blocked either way with the viewer are
    left out."""
    if state not in ATTENDEE_STATES:
        raise _bad_request(f"status must be one of {', '.join(ATTENDEE_STATES)}.")
    g = require_visible(viewer_id, gathering_id)
    if state in HOST_ONLY_STATES and str(g.host_id) != str(viewer_id):
        raise _forbidden("Only the host can see this list.")
    hidden = list(blocked_ids(str(viewer_id)))
    if state == "invited":
        return (
            GatheringInvite.objects.filter(gathering=g)
            .exclude(invitee_id__in=hidden)
            .order_by("-created_at", "-id")
        )
    return (
        GatheringRSVP.objects.filter(gathering=g, status=state)
        .exclude(account_id__in=hidden)
        .order_by("-updated_at", "-id")
    )


# ---- reports ---------------------------------------------------------------------


def report(viewer_id: str, gathering_id, reason: str) -> GatheringReport:
    """404 (nothing written) when the reporter cannot see the event; one report
    per account per event, a repeat returns the first and emits nothing."""
    if reason not in ReportReason.values:
        raise _bad_request("Invalid reason.")
    g = require_visible(viewer_id, gathering_id)
    existing = GatheringReport.objects.filter(gathering=g, reporter_id=viewer_id).first()
    if existing is not None:
        return existing
    try:
        with transaction.atomic():
            row = GatheringReport.objects.create(gathering=g, reporter_id=viewer_id, reason=reason)
            _emit(
                "gathering.reported",
                g,
                {
                    "gathering_id": str(g.id),
                    "reporter": str(viewer_id),
                    "reason": reason,
                    "owner_id": str(g.host_id),
                },
                actor_id=str(viewer_id),
            )
    except IntegrityError:  # a concurrent duplicate won the unique constraint
        return GatheringReport.objects.get(gathering=g, reporter_id=viewer_id)
    return row


# ---- moderation ------------------------------------------------------------------


def apply_moderation(gathering_id: str, action: str) -> None:
    """Driven by ``moderation.actioned`` with ``target_type=gathering``.

    ``remove`` hides the event everywhere (404, the host too) and emits
    ``gathering.deleted`` so notifications and search drop it; its cover follows
    the event's visibility in media, so it is hidden as well. ``approve`` (an
    overturned removal) shows it again and emits ``gathering.updated``.
    """
    with transaction.atomic():
        g = Gathering.objects.select_for_update().filter(id=gathering_id).first()
        if g is None:
            return
        removed = g.moderation_status == Gathering.ModerationStatus.REMOVED
        if action == "remove" and not removed:
            g.moderation_status = Gathering.ModerationStatus.REMOVED
            g.save(update_fields=["moderation_status", "updated_at"])
            _emit(
                "gathering.deleted",
                g,
                {"gathering_id": str(g.id), "host_id": str(g.host_id), "by": "moderation"},
            )
        elif action == "approve" and removed:
            g.moderation_status = Gathering.ModerationStatus.OK
            g.save(update_fields=["moderation_status", "updated_at"])
            if g.deleted_at is None:
                _emit_to(
                    "gathering.updated",
                    g,
                    {**_core_payload(g), "changed": ["moderation_status"], "notify": []},
                    [],
                )


# ---- blocks ----------------------------------------------------------------------


def _drop(host: str, other: str, *, audiences: tuple[str, ...] | None = None) -> int:
    """Remove ``other``'s RSVP and invite on ``host``'s events (only events whose
    audience is in ``audiences``, read under the lock, when given). Counters change
    under the event's row lock. Nothing is emitted. Running it again is a no-op."""
    qs = GatheringRSVP.objects.filter(gathering__host_id=host, account_id=other)
    invites = GatheringInvite.objects.filter(gathering__host_id=host, invitee_id=other)
    if audiences is not None:
        qs = qs.filter(gathering__audience__in=audiences)
        invites = invites.filter(gathering__audience__in=audiences)
    ids = set(qs.values_list("gathering_id", flat=True)) | set(
        invites.values_list("gathering_id", flat=True)
    )
    changed = 0
    for gathering_id in ids:
        with transaction.atomic():
            g = Gathering.objects.select_for_update().get(id=gathering_id)
            if audiences is not None and g.audience not in audiences:
                continue  # the host changed the audience meanwhile
            row = GatheringRSVP.objects.filter(gathering=g, account_id=other).first()
            if row is not None:
                _bump(g, row.status, -1)
                g.save(update_fields=["going_count", "interested_count"])
                row.delete()
            GatheringInvite.objects.filter(gathering=g, invitee_id=other).delete()
        changed += 1
    return changed


def drop_between(a: str, b: str) -> int:
    """After a block, neither account keeps an RSVP or invite on the other's events
    (a blocked guest must not hold a seat). Returns how many events changed."""
    return _drop(a, b) + _drop(b, a)


def drop_after_unfriend(a: str, b: str) -> int:
    """After ``friendship.removed``: on friends-only events hosted by either side,
    the other side loses its RSVP and invite, so the seat is free again. Invite-only
    and public events are left alone (an invite there was explicit).

    Retries reorder events, so graph is asked first: if the two are friends again,
    nothing is dropped. When graph cannot answer, this raises and the consumer
    retries later instead of guessing.
    """
    rel = get_relationship(str(a), str(b))
    if rel.degraded:
        raise TaraAPIError(
            "Graph is unavailable; retry the unfriend clean-up.",
            code="dependency_unavailable",
            http_status_code=503,
        )
    if rel.are_friends:
        return 0
    friends_only = (Gathering.Audience.FRIENDS,)
    return _drop(a, b, audiences=friends_only) + _drop(b, a, audiences=friends_only)


# ---- reminders and ending --------------------------------------------------------


def _reminder_recipients(g: Gathering, window: str) -> list[str]:
    """Going (and, a day ahead, interested) accounts, plus the host."""
    states = (
        (RSVPStatus.GOING, RSVPStatus.INTERESTED)
        if window == GatheringReminderLog.Window.DAY
        else (RSVPStatus.GOING,)
    )
    return [str(g.host_id), *_attendees(g, states)]


def _send_reminder(gathering_id, window: str, now: datetime) -> bool:
    """Exactly once per event and window: the log row and the outbox rows commit
    together, under the event's row lock (a concurrent run skips the locked row,
    and the unique log row is the backstop)."""
    with transaction.atomic():
        g = (
            Gathering.objects.select_for_update(skip_locked=True)
            .filter(_live(), id=gathering_id, status=Gathering.Status.SCHEDULED)
            .first()
        )
        if g is None or g.starts_at <= now:
            return False
        if GatheringReminderLog.objects.filter(gathering=g, kind=window).exists():
            return False
        recipients = _reminder_recipients(g, window)
        try:
            with transaction.atomic():
                GatheringReminderLog.objects.create(
                    gathering=g, kind=window, recipients=len(recipients)
                )
        except IntegrityError:
            return False
        _emit_to(
            "gathering.reminder",
            g,
            {
                "gathering_id": str(g.id),
                "host_id": str(g.host_id),
                "window": window,
                "starts_at": _iso(g.starts_at),
            },
            recipients,
        )
    return True


def send_due_reminders(now: datetime | None = None) -> int:
    """Beat task body: every event whose reminder window has opened, once each."""
    now = now or timezone.now()
    sent = 0
    for window, lead, floor in REMINDER_WINDOWS:
        due = (
            Gathering.objects.filter(
                _live(),
                status=Gathering.Status.SCHEDULED,
                starts_at__lte=now + lead,
                starts_at__gt=now + floor,
            )
            .exclude(reminders__kind=window)
            .order_by("starts_at")
            .values_list("id", flat=True)[:REMINDER_BATCH]
        )
        for gathering_id in list(due):
            sent += _send_reminder(gathering_id, window, now)
    return sent


def mark_ended(now: datetime | None = None) -> int:
    """Store ``ended`` on scheduled events whose end has passed."""
    now = now or timezone.now()
    ids = list(
        Gathering.objects.filter(status=Gathering.Status.SCHEDULED)
        .annotate(effective_end=_EFFECTIVE_END)
        .filter(effective_end__lt=now)
        .values_list("id", flat=True)[:1000]
    )
    return Gathering.objects.filter(id__in=ids, status=Gathering.Status.SCHEDULED).update(
        status=Gathering.Status.ENDED
    )
