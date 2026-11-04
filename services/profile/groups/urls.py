from django.urls import path, re_path

from . import views

app_name = "groups"

# ``<ref>`` is a handle (``[a-z0-9_]``) or a group id (a UUID with dashes).
REF = r"(?P<ref>[A-Za-z0-9_-]{3,36})"

urlpatterns = [
    path("groups/", views.GroupListCreateView.as_view(), name="group-list"),
    path("groups/suggestions/", views.GroupSuggestionsView.as_view(), name="group-suggestions"),
    path(
        "groups/suggestions/<uuid:group_id>/dismiss/",
        views.GroupSuggestionDismissView.as_view(),
        name="group-suggestion-dismiss",
    ),
    re_path(rf"^groups/{REF}/$", views.GroupDetailView.as_view(), name="group-detail"),
    re_path(rf"^groups/{REF}/join/$", views.GroupJoinView.as_view(), name="group-join"),
    re_path(rf"^groups/{REF}/leave/$", views.GroupLeaveView.as_view(), name="group-leave"),
    re_path(
        rf"^groups/{REF}/membership/$",
        views.GroupMembershipView.as_view(),
        name="group-membership",
    ),
    re_path(rf"^groups/{REF}/invite/$", views.GroupInviteView.as_view(), name="group-invite"),
    re_path(rf"^groups/{REF}/members/$", views.GroupMembersView.as_view(), name="group-members"),
    re_path(
        rf"^groups/{REF}/members/(?P<account_id>[0-9a-fA-F-]{{36}})/$",
        views.GroupMemberRoleView.as_view(),
        name="group-member-role",
    ),
    re_path(
        rf"^groups/{REF}/members/(?P<account_id>[0-9a-fA-F-]{{36}})/(?P<action>remove|ban|unban)/$",
        views.GroupMemberActionView.as_view(),
        name="group-member-action",
    ),
    re_path(
        rf"^groups/{REF}/requests/(?P<account_id>[0-9a-fA-F-]{{36}})/(?P<action>approve|decline)/$",
        views.GroupRequestActionView.as_view(),
        name="group-request-action",
    ),
    re_path(
        rf"^groups/{REF}/invites/(?P<account_id>[0-9a-fA-F-]{{36}})/(?P<action>revoke)/$",
        views.GroupRequestActionView.as_view(),
        name="group-invite-revoke",
    ),
    re_path(rf"^groups/{REF}/rules/$", views.GroupRulesView.as_view(), name="group-rules"),
    re_path(
        rf"^groups/{REF}/rules/order/$", views.GroupRuleOrderView.as_view(), name="group-rule-order"
    ),
    re_path(
        rf"^groups/{REF}/rules/(?P<rule_id>[0-9a-fA-F-]{{36}})/$",
        views.GroupRuleDetailView.as_view(),
        name="group-rule-detail",
    ),
    re_path(rf"^groups/{REF}/report/$", views.GroupReportView.as_view(), name="group-report"),
]
