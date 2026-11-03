"""Profile & Pages HTTP API."""

from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tara_common.exceptions import TaraAPIError
from tara_common.pagination import CursorPagination
from tara_common.responses import data_response

from . import services
from .models import (
    Page,
    PageMember,
    UserEducation,
    UserLink,
    UserProfile,
    UserWorkExperience,
)
from .privacy import field_visibility_map, resolve_context, visible_fields
from .serializers import (
    EducationSerializer,
    FieldPrivacyBulkSerializer,
    LinkSerializer,
    MemberAddSerializer,
    MemberRoleSerializer,
    MyProfileSerializer,
    PageCreateSerializer,
    PageMemberSerializer,
    PageSerializer,
    PageUpdateSerializer,
    ProfileLookupSerializer,
    ProfileUpdateSerializer,
    WorkSerializer,
)


def _require_profile(request: Request) -> UserProfile:
    profile = UserProfile.objects.filter(
        account_id=request.user.account_id, deleted_at__isnull=True
    ).first()
    if profile is None:
        raise TaraAPIError("Profile not found.", code="not_found", http_status_code=404)
    return profile


def _build_public_profile(profile: UserProfile, ctx) -> dict:
    from .privacy import profile_visible

    base = {
        "account_id": str(profile.account_id),
        "created_at": profile.created_at.isoformat(),
        "handle": profile.handle,
        "display_name": profile.display_name,
        "avatar_media_id": str(profile.avatar_media_id) if profile.avatar_media_id else None,
        "cover_media_id": str(profile.cover_media_id) if profile.cover_media_id else None,
        "visibility": profile.visibility,
        "is_self": ctx.is_self,
        "are_friends": ctx.are_friends,
    }
    if not profile_visible(profile, ctx):
        return {**base, "restricted": True}

    fields = visible_fields(profile, ctx)
    if "bio" in fields:
        base["bio"] = profile.bio
    if "intro" in fields:
        base["intro"] = profile.intro
    if "city" in fields:
        base["city"] = profile.city
    if "country" in fields:
        base["country"] = profile.country
    if "links" in fields:
        base["links"] = LinkSerializer(profile.links.all(), many=True).data
    if "education" in fields:
        base["education"] = EducationSerializer(profile.education.all(), many=True).data
    if "work" in fields:
        base["work"] = WorkSerializer(profile.work.all(), many=True).data
    return {**base, "restricted": False}


# ---- own profile ------------------------------------------------------------


class MyProfileView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: MyProfileSerializer}, tags=["profile"])
    def get(self, request: Request) -> Response:
        return data_response(MyProfileSerializer(_require_profile(request)).data)

    @extend_schema(
        request=ProfileUpdateSerializer, responses={200: MyProfileSerializer}, tags=["profile"]
    )
    def patch(self, request: Request) -> Response:
        profile = _require_profile(request)
        serializer = ProfileUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        services.update_profile(profile, serializer.validated_data)
        return data_response(MyProfileSerializer(profile).data)


class FieldPrivacyView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: None}, tags=["profile"])
    def get(self, request: Request) -> Response:
        levels = field_visibility_map(_require_profile(request))
        return data_response(
            {"items": [{"field_key": k, "visibility": v} for k, v in levels.items()]}
        )

    @extend_schema(request=FieldPrivacyBulkSerializer, responses={200: None}, tags=["profile"])
    def put(self, request: Request) -> Response:
        profile = _require_profile(request)
        serializer = FieldPrivacyBulkSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        for item in serializer.validated_data["items"]:
            services.set_field_privacy(profile, item["field_key"], item["visibility"])
        return data_response({"detail": "Field privacy updated."})


# Per list. Every public profile read returns the whole list.
MAX_PROFILE_ITEMS = 20


class _OwnedListCreate(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    related_name = ""
    # Explicit: the cursor paginator's default (-created_at) is not a field here.
    ordering: tuple[str, ...] = ("id",)

    def get_queryset(self):
        profile = _require_profile(self.request)
        return getattr(profile, self.related_name).order_by(*self.ordering)

    def perform_create(self, serializer):
        profile = _require_profile(self.request)
        if getattr(profile, self.related_name).count() >= MAX_PROFILE_ITEMS:
            raise TaraAPIError(
                f"A profile can list at most {MAX_PROFILE_ITEMS} of these.",
                code="validation_error",
                http_status_code=400,
            )
        serializer.save(profile=profile)


class _OwnedDestroy(generics.DestroyAPIView):
    permission_classes = [IsAuthenticated]
    related_name = ""

    def get_queryset(self):
        profile = _require_profile(self.request)
        return getattr(profile, self.related_name).all()


class LinksView(_OwnedListCreate):
    serializer_class = LinkSerializer
    related_name = "links"
    ordering = ("position", "id")


class LinkDetailView(_OwnedDestroy):
    serializer_class = LinkSerializer
    related_name = "links"
    queryset = UserLink.objects.none()


class EducationView(_OwnedListCreate):
    serializer_class = EducationSerializer
    related_name = "education"


class EducationDetailView(_OwnedDestroy):
    serializer_class = EducationSerializer
    related_name = "education"
    queryset = UserEducation.objects.none()


class WorkView(_OwnedListCreate):
    serializer_class = WorkSerializer
    related_name = "work"


class WorkDetailView(_OwnedDestroy):
    serializer_class = WorkSerializer
    related_name = "work"
    queryset = UserWorkExperience.objects.none()


# ---- public profile ---------------------------------------------------------


def _public_profile_response(request: Request, profile: UserProfile | None) -> Response:
    if profile is None:
        raise TaraAPIError("Profile not found.", code="not_found", http_status_code=404)
    ctx = resolve_context(request.user.account_id, profile)
    if ctx.blocked:
        # Blocked either way -> behave as if the profile does not exist.
        raise TaraAPIError("Profile not found.", code="not_found", http_status_code=404)
    return data_response(_build_public_profile(profile, ctx))


class PublicProfileView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: None}, tags=["profile"])
    def get(self, request: Request, handle: str) -> Response:
        profile = UserProfile.objects.filter(handle=handle.lower(), deleted_at__isnull=True).first()
        return _public_profile_response(request, profile)


class PublicProfileByIdView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: None}, tags=["profile"])
    def get(self, request: Request, account_id: str) -> Response:
        profile = UserProfile.objects.filter(account_id=account_id, deleted_at__isnull=True).first()
        return _public_profile_response(request, profile)


class ProfileLookupView(APIView):
    """Names and avatars for a batch of accounts, for rendering lists."""

    permission_classes = [IsAuthenticated]

    @extend_schema(request=ProfileLookupSerializer, responses={200: None}, tags=["profile"])
    def post(self, request: Request) -> Response:
        serializer = ProfileLookupSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return data_response(
            services.profile_cards(request.user.account_id, serializer.validated_data["ids"])
        )


# ---- pages ------------------------------------------------------------------


def _page_data(page: Page, request: Request) -> dict:
    return PageSerializer(page, context={"viewer_id": request.user.account_id}).data


class PageCreateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: PageSerializer(many=True)}, tags=["pages"])
    def get(self, request: Request) -> Response:
        """Browse pages (``?q=`` searches), or the caller's own with ``?mine=1``."""
        pages = services.list_pages(
            request.user.account_id,
            q=request.query_params.get("q", "").strip(),
            mine=request.query_params.get("mine") in ("1", "true"),
        )
        paginator = CursorPagination()
        page = paginator.paginate_queryset(pages, request)
        return paginator.get_paginated_response(
            PageSerializer(page, many=True, context={"viewer_id": request.user.account_id}).data
        )

    @extend_schema(request=PageCreateSerializer, responses={201: PageSerializer}, tags=["pages"])
    def post(self, request: Request) -> Response:
        serializer = PageCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        page = services.create_page(request.user.account_id, serializer.validated_data)
        return data_response(_page_data(page, request), status=status.HTTP_201_CREATED)


class PageByHandleView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: PageSerializer}, tags=["pages"])
    def get(self, request: Request, handle: str) -> Response:
        page = services.get_visible_page(request.user.account_id, handle=handle.lower())
        return data_response(_page_data(page, request))


class PageDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: PageSerializer}, tags=["pages"])
    def get(self, request: Request, page_id: str) -> Response:
        page = services.get_visible_page(request.user.account_id, id=page_id)
        return data_response(_page_data(page, request))

    @extend_schema(request=PageUpdateSerializer, responses={200: PageSerializer}, tags=["pages"])
    def patch(self, request: Request, page_id: str) -> Response:
        serializer = PageUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        page = services.get_visible_page(request.user.account_id, id=page_id)
        page = services.update_page(page, request.user.account_id, serializer.validated_data)
        return data_response(_page_data(page, request))


class PageMembersView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: PageMemberSerializer(many=True)}, tags=["pages"])
    def get(self, request: Request, page_id: str) -> Response:
        page = services.get_visible_page(request.user.account_id, id=page_id)
        members = services.list_page_members(page, request.user.account_id)
        return data_response(PageMemberSerializer(members, many=True).data)

    @extend_schema(
        request=MemberAddSerializer, responses={201: PageMemberSerializer}, tags=["pages"]
    )
    def post(self, request: Request, page_id: str) -> Response:
        page = services.get_visible_page(request.user.account_id, id=page_id)
        serializer = MemberAddSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        member = services.add_member(
            page,
            request.user.account_id,
            str(serializer.validated_data["account_id"]),
            serializer.validated_data["role"],
        )
        return data_response(PageMemberSerializer(member).data, status=status.HTTP_201_CREATED)


class PageMemberDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def _member(self, request: Request, page_id: str, member_id: str) -> PageMember:
        services.get_visible_page(request.user.account_id, id=page_id)
        member = (
            PageMember.objects.filter(id=member_id, page_id=page_id).select_related("page").first()
        )
        if member is None:
            raise TaraAPIError("Member not found.", code="not_found", http_status_code=404)
        return member

    @extend_schema(responses={204: None}, tags=["pages"])
    def delete(self, request: Request, page_id: str, member_id: str) -> Response:
        member = self._member(request, page_id, member_id)
        services.remove_member(member.page, request.user.account_id, member)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        request=MemberRoleSerializer, responses={200: PageMemberSerializer}, tags=["pages"]
    )
    def patch(self, request: Request, page_id: str, member_id: str) -> Response:
        member = self._member(request, page_id, member_id)
        serializer = MemberRoleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        member = services.update_member_role(
            member.page, request.user.account_id, member, serializer.validated_data["role"]
        )
        return data_response(PageMemberSerializer(member).data)
