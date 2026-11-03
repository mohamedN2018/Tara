"""Profile & Pages business logic."""

from __future__ import annotations

import re
import secrets

from django.db import transaction
from django.db.models import Prefetch, Q

from tara_common.exceptions import Conflict, TaraAPIError

from . import events
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


def generate_handle(seed: str) -> str:
    base = _slug(seed.split("@")[0])[:20] or "user"
    handle = base
    while UserProfile.objects.filter(handle=handle).exists():
        handle = f"{base}{secrets.randbelow(9000) + 1000}"[:30]
    return handle


def _completion(profile: UserProfile) -> int:
    filled = sum(1 for f in _COMPLETION_FIELDS if getattr(profile, f))
    return round(100 * filled / len(_COMPLETION_FIELDS))


# ---- profile provisioning (event-driven) ------------------------------------


def ensure_profile(
    account_id: str, *, email: str = "", display_name: str = "", requested_handle: str = ""
) -> UserProfile:
    """Idempotently create a profile for an account (called on account.registered)."""
    existing = UserProfile.objects.filter(account_id=account_id).first()
    if existing:
        return existing
    # A taken requested handle falls back to a numbered variant of it.
    handle = generate_handle(requested_handle or email or f"user{secrets.randbelow(99999)}")
    with transaction.atomic():
        profile = UserProfile.objects.create(
            account_id=account_id,
            handle=handle,
            display_name=display_name or handle,
        )
        emit_profile_updated(profile, changed=["handle", "display_name"])
    return profile


def emit_profile_updated(profile: UserProfile, changed: list[str]) -> None:
    """Search indexes people from this event, so a new account needs one too."""
    events.emit(
        "profile.updated",
        subject_id=str(profile.account_id),
        payload={
            "handle": profile.handle,
            "display_name": profile.display_name,
            "visibility": profile.visibility,
            "avatar_media_id": str(profile.avatar_media_id) if profile.avatar_media_id else None,
            "changed": changed,
        },
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
    ProfileFieldPrivacy.objects.update_or_create(
        profile=profile, field_key=field_key, defaults={"visibility": visibility}
    )


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
        PageMember.objects.create(
            page=page, account_id=owner_account_id, role=PageRole.OWNER, invited_by=owner_account_id
        )
        events.emit(
            "page.created",
            subject_id=str(page.id),
            payload={"handle": page.handle, "name": page.name, "owner": str(owner_account_id)},
            actor_id=str(owner_account_id),
        )
    return page


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
    for key in ("name", "category", "description", "contact", "location", "status"):
        if key in data:
            setattr(page, key, data[key])
    page.save()
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
