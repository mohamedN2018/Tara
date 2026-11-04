from django.urls import path

from . import views

app_name = "adminsvc"

urlpatterns = [
    path("admin/feature-flags/", views.FeatureFlagsView.as_view(), name="feature-flags"),
    path(
        "admin/feature-flags/<str:key>/",
        views.FeatureFlagDetailView.as_view(),
        name="feature-flag-detail",
    ),
    path("admin/roles/", views.RolesView.as_view(), name="roles"),
    path("admin/roles/lookup/", views.RoleLookupView.as_view(), name="role-lookup"),
    path("admin/roles/<uuid:account_id>/", views.AccountRolesView.as_view(), name="account-roles"),
    path("admin/service-health/", views.ServiceHealthView.as_view(), name="service-health"),
    path("admin/capabilities/", views.CapabilityMatrixView.as_view(), name="capabilities"),
    path("admin/audit/", views.AuditListView.as_view(), name="audit"),
    path("admin/audit/export.csv", views.AuditExportView.as_view(), name="audit-export"),
    path("admin/monitor/", views.MonitorView.as_view(), name="monitor"),
    path("admin/notices/", views.SystemNoticesView.as_view(), name="notices"),
    # User management console (8.6).
    path("admin/users/", views.UserSearchView.as_view(), name="users"),
    path("admin/users/<uuid:account_id>/", views.UserDetailView.as_view(), name="user-detail"),
    path(
        "admin/users/<uuid:account_id>/reveal/",
        views.UserRevealView.as_view(),
        name="user-reveal",
    ),
    path(
        "admin/users/<uuid:account_id>/suspend/",
        views.UserSuspendView.as_view(),
        name="user-suspend",
    ),
    path(
        "admin/users/<uuid:account_id>/unsuspend/",
        views.UserUnsuspendView.as_view(),
        name="user-unsuspend",
    ),
    path(
        "admin/users/<uuid:account_id>/sign-out/",
        views.UserSignOutView.as_view(),
        name="user-sign-out",
    ),
    path(
        "admin/users/<uuid:account_id>/resend-verification/",
        views.UserResendVerificationView.as_view(),
        name="user-resend-verification",
    ),
]
