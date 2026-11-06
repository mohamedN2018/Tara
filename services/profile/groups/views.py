"""Groups HTTP API (``/api/v1/groups/``).

``<ref>`` is a group handle or its id. Views run outside ``ATOMIC_REQUESTS``:
invites ask graph and covers ask media before writing, and each write path in
``services`` opens its own transaction (roadmap 3.3).
"""

from __future__ import annotations

from django.db import transaction
from django.utils.decorators import method_decorator
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tara_common.pagination import CursorPagination
from tara_common.responses import data_response

from . import services
from .serializers import (
    GroupCreateSerializer,
    GroupReportSerializer,
    GroupUpdateSerializer,
    InviteSerializer,
    MembershipSerializer,
    NotifySerializer,
    RoleSerializer,
    RuleEditSerializer,
    RuleInSerializer,
    RuleOrderSerializer,
    RuleSerializer,
    group_data,
)
from .throttling import GroupReportThrottle


def _me(request: Request) -> str:
    return request.user.account_id


def _detail(request: Request, group, member=None) -> dict:
    if member is None:
        member = services.membership(group, _me(request))
    return group_data(group, _me(request), member, with_rules=True)


class _GroupView(APIView):
    permission_classes = [IsAuthenticated]

    def resolve(self, request: Request, ref: str):
        return services.resolve(_me(request), ref)


@method_decorator(transaction.non_atomic_requests, name="dispatch")
class GroupListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: None}, tags=["groups"])
    def get(self, request: Request) -> Response:
        """``?scope=mine`` (default) | ``discover`` | ``invited`` | ``requested``,
        with ``?q=`` and ``?category=``. Discover never lists hidden groups."""
        queryset = services.list_queryset(
            _me(request),
            request.query_params.get("scope") or "mine",
            q=request.query_params.get("q", ""),
            category=request.query_params.get("category", ""),
        )
        paginator = CursorPagination()
        page = paginator.paginate_queryset(queryset, request)
        mine = services.memberships_of(_me(request), page)
        return paginator.get_paginated_response(
            [group_data(g, _me(request), mine.get(g.id)) for g in page]
        )

    @extend_schema(request=GroupCreateSerializer, responses={201: None}, tags=["groups"])
    def post(self, request: Request) -> Response:
        serializer = GroupCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        group = services.create_group(_me(request), serializer.validated_data)
        return data_response(_detail(request, group), status=status.HTTP_201_CREATED)


@method_decorator(transaction.non_atomic_requests, name="dispatch")  # asks graph
class GroupSuggestionsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: None}, tags=["groups"])
    def get(self, request: Request) -> Response:
        """Up to 20 public or private groups, ranked by friends who are members.

        The counts come from the ``discovery`` config (Tara Intelligence WP 5.5); under
        a running experiment the response carries ``meta.variant``."""
        from . import intel_config

        cfg = intel_config.served(_me(request))
        out = []
        for group, friend_count, friend_ids in services.suggestions(_me(request), cfg):
            item = group_data(group, _me(request), None)
            item["friend_member_count"] = friend_count
            item["friend_ids"] = friend_ids
            out.append(item)
        response = data_response(out)
        if cfg.variant:
            response.data["meta"] = cfg.meta()
        return response


class GroupSuggestionDismissView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={204: None}, tags=["groups"])
    def post(self, request: Request, group_id: str) -> Response:
        services.dismiss_suggestion(_me(request), group_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


@method_decorator(transaction.non_atomic_requests, name="dispatch")  # cover: media
class GroupDetailView(_GroupView):
    @extend_schema(responses={200: None}, tags=["groups"])
    def get(self, request: Request, ref: str) -> Response:
        group, member = self.resolve(request, ref)
        return data_response(_detail(request, group, member))

    @extend_schema(request=GroupUpdateSerializer, responses={200: None}, tags=["groups"])
    def patch(self, request: Request, ref: str) -> Response:
        serializer = GroupUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        group, member = self.resolve(request, ref)
        group = services.update_group(_me(request), group, member, serializer.validated_data)
        return data_response(_detail(request, group))

    @extend_schema(responses={204: None}, tags=["groups"])
    def delete(self, request: Request, ref: str) -> Response:
        group, _ = self.resolve(request, ref)
        services.delete_group(_me(request), group)
        return Response(status=status.HTTP_204_NO_CONTENT)


@method_decorator(transaction.non_atomic_requests, name="dispatch")
class GroupJoinView(_GroupView):
    @extend_schema(responses={201: MembershipSerializer}, tags=["groups"])
    def post(self, request: Request, ref: str) -> Response:
        """Join, or ask to join when the group needs approval."""
        group, _ = self.resolve(request, ref)
        member = services.join(_me(request), group)
        return data_response(MembershipSerializer(member).data, status=status.HTTP_201_CREATED)

    @extend_schema(responses={204: None}, tags=["groups"])
    def delete(self, request: Request, ref: str) -> Response:
        """Take back my request, or decline my invite."""
        group, _ = self.resolve(request, ref)
        services.cancel_join(_me(request), group)
        return Response(status=status.HTTP_204_NO_CONTENT)


@method_decorator(transaction.non_atomic_requests, name="dispatch")
class GroupLeaveView(_GroupView):
    @extend_schema(responses={204: None}, tags=["groups"])
    def post(self, request: Request, ref: str) -> Response:
        group, _ = self.resolve(request, ref)
        services.leave(_me(request), group)
        return Response(status=status.HTTP_204_NO_CONTENT)


@method_decorator(transaction.non_atomic_requests, name="dispatch")
class GroupMembershipView(_GroupView):
    @extend_schema(request=NotifySerializer, responses={200: MembershipSerializer}, tags=["groups"])
    def patch(self, request: Request, ref: str) -> Response:
        serializer = NotifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        group, _ = self.resolve(request, ref)
        member = services.set_notify_posts(
            _me(request), group, serializer.validated_data["notify_posts"]
        )
        return data_response(MembershipSerializer(member).data)


@method_decorator(transaction.non_atomic_requests, name="dispatch")  # asks graph
class GroupInviteView(_GroupView):
    @extend_schema(request=InviteSerializer, responses={200: None}, tags=["groups"])
    def post(self, request: Request, ref: str) -> Response:
        serializer = InviteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        group, _ = self.resolve(request, ref)
        invited = services.invite(_me(request), group, serializer.validated_data["account_ids"])
        return data_response({"invited": invited})


class GroupMembersView(_GroupView):
    @extend_schema(responses={200: MembershipSerializer(many=True)}, tags=["groups"])
    def get(self, request: Request, ref: str) -> Response:
        """``?state=active`` (default) | ``requested`` | ``invited`` | ``banned``,
        ``?role=``, ``?q=`` (name or handle)."""
        group, member = self.resolve(request, ref)
        queryset = services.members_queryset(
            _me(request),
            group,
            member,
            state=request.query_params.get("state") or "active",
            role=request.query_params.get("role") or "",
            q=request.query_params.get("q", ""),
        )
        paginator = CursorPagination()
        page = paginator.paginate_queryset(queryset, request)
        return paginator.get_paginated_response(MembershipSerializer(page, many=True).data)


@method_decorator(transaction.non_atomic_requests, name="dispatch")
class GroupRequestActionView(_GroupView):
    @extend_schema(responses={200: MembershipSerializer}, tags=["groups"])
    def post(self, request: Request, ref: str, account_id: str, action: str) -> Response:
        group, _ = self.resolve(request, ref)
        if action == "approve":
            member = services.approve_request(_me(request), group, str(account_id))
            return data_response(MembershipSerializer(member).data)
        if action == "revoke":
            services.revoke_invite(_me(request), group, str(account_id))
            return Response(status=status.HTTP_204_NO_CONTENT)
        services.decline_request(_me(request), group, str(account_id))
        return Response(status=status.HTTP_204_NO_CONTENT)


@method_decorator(transaction.non_atomic_requests, name="dispatch")
class GroupMemberActionView(_GroupView):
    @extend_schema(responses={200: MembershipSerializer}, tags=["groups"])
    def post(self, request: Request, ref: str, account_id: str, action: str) -> Response:
        group, _ = self.resolve(request, ref)
        if action == "ban":
            member = services.ban(_me(request), group, str(account_id))
            return data_response(MembershipSerializer(member).data)
        if action == "unban":
            services.unban(_me(request), group, str(account_id))
        else:
            services.remove_member(_me(request), group, str(account_id))
        return Response(status=status.HTTP_204_NO_CONTENT)


@method_decorator(transaction.non_atomic_requests, name="dispatch")
class GroupMemberRoleView(_GroupView):
    @extend_schema(request=RoleSerializer, responses={200: MembershipSerializer}, tags=["groups"])
    def patch(self, request: Request, ref: str, account_id: str) -> Response:
        serializer = RoleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        group, _ = self.resolve(request, ref)
        member = services.change_role(
            _me(request), group, str(account_id), serializer.validated_data["role"]
        )
        return data_response(MembershipSerializer(member).data)


@method_decorator(transaction.non_atomic_requests, name="dispatch")
class GroupRulesView(_GroupView):
    @extend_schema(responses={200: RuleSerializer(many=True)}, tags=["groups"])
    def get(self, request: Request, ref: str) -> Response:
        group, _ = self.resolve(request, ref)
        return data_response(RuleSerializer(services.list_rules(group), many=True).data)

    @extend_schema(request=RuleInSerializer, responses={201: RuleSerializer}, tags=["groups"])
    def post(self, request: Request, ref: str) -> Response:
        serializer = RuleInSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        group, _ = self.resolve(request, ref)
        rule = services.add_rule(
            _me(request),
            group,
            serializer.validated_data["title"],
            serializer.validated_data.get("body", ""),
        )
        return data_response(RuleSerializer(rule).data, status=status.HTTP_201_CREATED)


@method_decorator(transaction.non_atomic_requests, name="dispatch")
class GroupRuleDetailView(_GroupView):
    @extend_schema(request=RuleEditSerializer, responses={200: RuleSerializer}, tags=["groups"])
    def patch(self, request: Request, ref: str, rule_id: str) -> Response:
        serializer = RuleEditSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        group, _ = self.resolve(request, ref)
        rule = services.edit_rule(_me(request), group, rule_id, serializer.validated_data)
        return data_response(RuleSerializer(rule).data)

    @extend_schema(responses={204: None}, tags=["groups"])
    def delete(self, request: Request, ref: str, rule_id: str) -> Response:
        group, _ = self.resolve(request, ref)
        services.delete_rule(_me(request), group, rule_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


@method_decorator(transaction.non_atomic_requests, name="dispatch")
class GroupRuleOrderView(_GroupView):
    @extend_schema(
        request=RuleOrderSerializer, responses={200: RuleSerializer(many=True)}, tags=["groups"]
    )
    def put(self, request: Request, ref: str) -> Response:
        serializer = RuleOrderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        group, _ = self.resolve(request, ref)
        rules = services.reorder_rules(_me(request), group, serializer.validated_data["ids"])
        return data_response(RuleSerializer(rules, many=True).data)


@method_decorator(transaction.non_atomic_requests, name="dispatch")
class GroupReportView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [*APIView.throttle_classes, GroupReportThrottle]

    @extend_schema(request=GroupReportSerializer, responses={202: None}, tags=["groups"])
    def post(self, request: Request, ref: str) -> Response:
        """404 if the reporter cannot see the group; a repeat report is accepted once."""
        serializer = GroupReportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        group, member = services.resolve(_me(request), ref)
        services.report(_me(request), group, member, serializer.validated_data["reason"])
        return data_response({"detail": "reported"}, status=status.HTTP_202_ACCEPTED)
