from django.urls import path

from . import views

app_name = "moderation"

urlpatterns = [
    path("moderation/reports/", views.ReportsView.as_view(), name="reports"),
    path("moderation/reports/file/", views.ManualReportView.as_view(), name="report-file"),
    path("moderation/cases/", views.CasesView.as_view(), name="cases"),
    path(
        "moderation/cases/<uuid:case_id>/assign/",
        views.CaseAssignView.as_view(),
        name="case-assign",
    ),
    path(
        "moderation/cases/<uuid:case_id>/action/",
        views.CaseActionView.as_view(),
        name="case-action",
    ),
    path(
        "moderation/cases/<uuid:case_id>/appeals/",
        views.CaseAppealView.as_view(),
        name="case-appeal",
    ),
    path(
        "moderation/appeals/<uuid:appeal_id>/resolve/",
        views.AppealResolveView.as_view(),
        name="appeal-resolve",
    ),
]
