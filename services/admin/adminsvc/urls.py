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
]
