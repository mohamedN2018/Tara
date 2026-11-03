"""Profile & Pages business logic."""

from __future__ import annotations

import re
import secrets

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Prefetch, Q

from tara_common.exceptions import Conflict, TaraAPIError

from . import events, media_client
from .models import (
    BlockedPair,
    Page,
    PageMember,
    PageRole,
    ProfileFieldPrivacy,
    UserProfile,
    Visibility,
)

_COMPLETION_FIELDS = ("display_name", "bio", "city", "country", "avatar_media_id")


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9_]", "", value.lower())


# Path segments of the API (``users/lookup/``) and names people would take for staff.
RESERVED_HANDLES = frozenset({"lookup", "id", "me", "admin", "tara"})


def _handle_taken(handle: str) -> bool:
    return handle in RESERVED_HANDLES or UserProfile.objects.filter(handle=handle).exists()


def generate_handle(seed: str) -> str:
    """``seed`` as a free handle, or with digits after it.

    Names in other scripts (Arabic) slug to nothing and share the base
    ``user``, so after a few 4-digit tries the suffix grows: the loop always ends.
    """
    base = _slug(seed)[:20]
    if len(base) < 3:
        base = "user"
    if not _handle_taken(base):
        return base
    for digits in (4, 4, 4, 8, 8, 8):
        handle = f"{base}{secrets.randbelow(9 * 10 ** (digits - 1)) + 10 ** (digits - 1)}"
        if not _handle_taken(handle):
            return handle
    return f"{base}{secrets.token_hex(5)}"


def _completion(profile: UserProfile) -> int:
    filled = sum(1 for f in _COMPLETION_FIELDS if getattr(profile, f))
    return round(100 * filled / len(_COMPLETION_FIELDS))


# ---- profile provisioning (event-driven) ------------------------------------


def ensure_profile(
    account_id: str, *, display_name: str = "", requested_handle: str = ""
) -> UserProfile:
    """Idempotently create a profile for an account (called on account.registered).

    The handle is the requested one, else made from the display name; a taken
    one gets digits. Never from the email: a handle is public, and the part of
    an address before the @ is often the whole of what makes it guessable.
    """
    existing = UserProfile.objects.filter(account_id=account_id).first()
    if existing:
        return existing
    handle = generate_handle(requested_handle or display_name)
    with transaction.atomic():
        profile = UserProfile.objects.create(
            account_id=account_id,
            handle=handle,
            display_name=display_name or handle,
        )
        emit_profile_updated(profile, changed=["handle", "display_name"])
    return profile


def profile_search_payload(profile: UserProfile, changed: list[str]) -> dict:
    """The ``profile.updated`` payload. ``city`` is sent only while its field
    privacy is public (search shows it to everyone); otherwise it is ``None``."""
    city_level = (
        ProfileFieldPrivacy.objects.filter(profile=profile, field_key="city")
        .values_list("visibility", flat=True)
        .first()
    )
    public_city = (city_level or Visibility.PUBLIC) == Visibility.PUBLIC
    return {
        "handle": profile.handle,
        "display_name": profile.display_name,
        "visibility": profile.visibility,
        "avatar_media_id": str(profile.avatar_media_id) if profile.avatar_media_id else None,
        "city": (profile.city or None) if public_city else None,
        "changed": changed,
    }


def emit_profile_updated(profile: UserProfile, changed: list[str]) -> None:
    """Search indexes people from this event, so a new account needs one too."""
    events.emit(
        "profile.updated",
        subject_id=str(profile.account_id),
        payload=profile_search_payload(profile, changed),
        actor_id=str(profile.account_id),
    )


def profile_cards(viewer_id: str, account_ids: list) -> list[dict]:
    """Public identity of each account, leaving out anyone blocked either way."""
    blocked = set(
        BlockedPair.objects.filter(blocker_id=viewer_id).values_list("blocked_id", flat=True)
    ) | set(BlockedPair.objects.filter(blocked_id=viewer_id).values_list("blocker_id", flat=True))
    profiles = UserProfile.objects.filter(
        account_id__in=account_ids, deleted_at__isnull=True
    ).exclude(account_id__in=blocked)
    return [
        {
            "account_id": str(p.account_id),
            "handle": p.handle,
            "display_name": p.display_name,
            "avatar_media_id": str(p.avatar_media_id) if p.avatar_media_id else None,
        }
        for p in profiles
    ]


# ---- profile editing --------------------------------------------------------


_IMAGE_FIELDS = ("avatar_media_id", "cover_media_id")


def _bad_media(message: str, code: str) -> TaraAPIError:
    return TaraAPIError(message, code=code, http_status_code=400)


def check_own_images(profile: UserProfile, data: dict) -> None:
    """A new avatar or cover must be the account's own image upload.

    Unchanged and cleared values are not checked. Someone else's media and an
    unknown id look the same, so neither leaks. Media down: 503, nothing saved.
    """
    wanted = {
        str(data[f])
        for f in _IMAGE_FIELDS
        if data.get(f) and str(data[f]) != str(getattr(profile, f) or "")
    }
    if not wanted:
        return
    found = media_client.lookup(sorted(wanted))
    for media_id in wanted:
        info = found.get(media_id)
        if info is None or info.owner_id != str(profile.account_id):
            raise _bad_media("Media not found.", "media_not_owned")
        if info.kind != "image":
            raise _bad_media("Only an image can be an avatar or a cover.", "media_kind_not_allowed")
        if info.status not in media_client.USABLE_STATUSES:
            raise _bad_media("Media upload is not complete.", "media_not_ready")


def update_profile(profile: UserProfile, data: dict) -> UserProfile:
    allowed = {
        "display_name",
        "bio",
        "intro",
        "city",
        "country",
        "avatar_media_id",
        "cover_media_id",
        "visibility",
    }
    check_own_images(profile, data)
    for key, value in data.items():
        if key in allowed:
            setattr(profile, key, value)
    with transaction.atomic():
        profile.completion_pct = _completion(profile)
        profile.save()
        emit_profile_updated(profile, changed=sorted(set(data) & allowed))
    return profile


def set_field_privacy(profile: UserProfile, field_key: str, visibility: str) -> None:
    if visibility not in Visibility.values:
        raise TaraAPIError("Invalid visibility.", code="validation_error", http_status_code=400)
    with transaction.atomic():
        ProfileFieldPrivacy.objects.update_or_create(
            profile=profile, field_key=field_key, defaults={"visibility": visibility}
        )
        if field_key == "city":  # search shows the city only while it is public
            emit_profile_updated(profile, changed=["field_privacy.city"])


# ---- pages ------------------------------------------------------------------


def _is_blocked(a: str, b: str) -> bool:
    return BlockedPair.objects.filter(
        Q(blocker_id=a, blocked_id=b) | Q(blocker_id=b, blocked_id=a)
    ).exists()


def _with_viewer_role(queryset, viewer_id: str):
    return queryset.prefetch_related(
        Prefetch(
            "members",
            queryset=PageMember.objects.filter(account_id=viewer_id),
            to_attr="viewer_memberships",
        )
    )


def _visible_pages(viewer_id: str):
    """Published pages, plus any page the viewer belongs to; never a blocked owner's."""
    blocked = BlockedPair.objects.filter(blocked_id=viewer_id).values("blocker_id")
    blocking = BlockedPair.objects.filter(blocker_id=viewer_id).values("blocked_id")
    mine = PageMember.objects.filter(account_id=viewer_id).values("page_id")
    return (
        Page.objects.filter(deleted_at__isnull=True)
        .filter(Q(status=Page.Status.PUBLISHED) | Q(id__in=mine))
        .exclude(owner_account_id__in=blocked)
        .exclude(owner_account_id__in=blocking)
    )


def list_pages(viewer_id: str, *, q: str = "", mine: bool = False):
    pages = _visible_pages(viewer_id)
    if mine:
        pages = pages.filter(members__account_id=viewer_id)
    if q:
        pages = pages.filter(
            Q(name__icontains=q) | Q(handle__icontains=q) | Q(category__icontains=q)
        )
    return _with_viewer_role(pages, viewer_id).order_by("-created_at")


def get_visible_page(viewer_id: str, **lookup) -> Page:
    page = _with_viewer_role(_visible_pages(viewer_id).filter(**lookup), viewer_id).first()
    if page is None:
        raise TaraAPIError("Page not found.", code="not_found", http_status_code=404)
    return page


def list_page_members(page: Page, actor_id: str):
    if member_role(page, actor_id) is None:
        raise TaraAPIError(
            "Only page members can see this.", code="permission_denied", http_status_code=403
        )
    return page.members.order_by("created_at")


def member_role(page: Page, account_id: str) -> str | None:
    member = page.members.filter(account_id=account_id).first()
    return member.role if member else None


def create_page(owner_account_id: str, data: dict) -> Page:
    handle = data["handle"].lower()
    if Page.objects.filter(handle=handle).exists():
        raise Conflict("Page handle already taken.", code="conflict")
    with transaction.atomic():
        try:
            page = Page.objects.create(
                owner_account_id=owner_account_id,
                handle=handle,
                name=data["name"],
                category=data.get("category", ""),
                description=data.get("description", ""),
                contact=data.get("contact", {}),
                location=data.get("location", ""),
                created_by=owner_account_id,
            )
        except IntegrityError as exc:  # a concurrent create took the handle first
            raise Conflict("Page handle already taken.", code="conflict") from exc
        PageMember.objects.create(
            page=page, account_id=owner_account_id, role=PageRole.OWNER, invited_by=owner_account_id
        )
        events.emit(
            "page.created",
            subject_id=str(page.id),
            payload=page_search_payload(page),
            actor_id=str(owner_account_id),
        )
    return page


def page_search_payload(page: Page) -> dict:
    """``page.created``/``page.updated``: the page's searchable state. The owner is
    always carried, so a re-index never clears it (blocks are matched on it)."""
    return {
        "handle": page.handle,
        "name": page.name,
        "owner": str(page.owner_account_id),
        "category": page.category,
        "location": page.location,
        "status": page.status,
        "avatar_media_id": str(page.avatar_media_id) if page.avatar_media_id else None,
        "deleted": page.deleted_at is not None,
    }


def update_page(page: Page, actor_id: str, data: dict) -> Page:
    role = member_role(page, actor_id)
    if role not in (PageRole.OWNER, PageRole.ADMIN, PageRole.EDITOR):
        raise TaraAPIError(
            "Not permitted to edit this page.", code="permission_denied", http_status_code=403
        )
    if page.status == Page.Status.SUSPENDED and "status" in data:
        raise TaraAPIError(
            "This page is suspended.", code="permission_denied", http_status_code=403
        )
    if "status" in data and role == PageRole.EDITOR:
        raise TaraAPIError(
            "Only owners/admins can change the status.",
            code="permission_denied",
            http_status_code=403,
        )
    editable = ("name", "category", "description", "contact", "location", "status")
    for key in editable:
        if key in data:
            setattr(page, key, data[key])
    with transaction.atomic():
        page.save()
        if settings.PROFILE_EMIT_PAGE_UPDATED:
            events.emit(
                "page.updated",
                subject_id=str(page.id),
                payload={**page_search_payload(page), "changed": sorted(set(data) & set(editable))},
                actor_id=str(actor_id),
            )
    return page


def remove_member(page: Page, actor_id: str, member: PageMember) -> None:
    """Owners and admins remove others; anyone but the owner can leave."""
    if member.role == PageRole.OWNER:
        raise TaraAPIError(
            "The owner cannot be removed.", code="validation_error", http_status_code=400
        )
    leaving = str(member.account_id) == str(actor_id)
    if not leaving and member_role(page, actor_id) not in (PageRole.OWNER, PageRole.ADMIN):
        raise TaraAPIError(
            "Only owners/admins can remove members.",
            code="permission_denied",
            http_status_code=403,
        )
    with transaction.atomic():
        account_id = member.account_id
        member.delete()
        events.emit(
            "page.member.changed",
            subject_id=str(page.id),
            payload={"member": str(account_id), "role": None, "action": "removed"},
            actor_id=str(actor_id),
        )


def add_member(page: Page, actor_id: str, account_id: str, role: str) -> PageMember:
    actor_role = member_role(page, actor_id)
    if actor_role not in (PageRole.OWNER, PageRole.ADMIN):
        raise TaraAPIError(
            "Only owners/admins can add members.", code="permission_denied", http_status_code=403
        )
    if role == PageRole.OWNER:
        raise TaraAPIError(
            "Cannot assign a second owner.", code="validation_error", http_status_code=400
        )
    if role not in PageRole.values:
        raise TaraAPIError("Invalid role.", code="validation_error", http_status_code=400)
    if _is_blocked(actor_id, account_id):
        raise TaraAPIError("Action not allowed.", code="permission_denied", http_status_code=403)
    if page.members.filter(account_id=account_id).exists():
        raise Conflict("Account is already a member.", code="conflict")
    with transaction.atomic():
        member = PageMember.objects.create(
            page=page, account_id=account_id, role=role, invited_by=actor_id
        )
        events.emit(
            "page.member.changed",
            subject_id=str(page.id),
            payload={"member": str(account_id), "role": role, "action": "added"},
            actor_id=str(actor_id),
        )
    return member


def update_member_role(page: Page, actor_id: str, member: PageMember, role: str) -> PageMember:
    actor_role = member_role(page, actor_id)
    if actor_role not in (PageRole.OWNER, PageRole.ADMIN):
        raise TaraAPIError(
            "Only owners/admins can change roles.", code="permission_denied", http_status_code=403
        )
    if member.role == PageRole.OWNER or role == PageRole.OWNER:
        raise TaraAPIError(
            "Owner role cannot be reassigned here.", code="validation_error", http_status_code=400
        )
    if role not in PageRole.values:
        raise TaraAPIError("Invalid role.", code="validation_error", http_status_code=400)
    with transaction.atomic():
        member.role = role
        member.save(update_fields=["role"])
        events.emit(
            "page.member.changed",
            subject_id=str(page.id),
            payload={"member": str(member.account_id), "role": role, "action": "updated"},
            actor_id=str(actor_id),
        )
    return member
