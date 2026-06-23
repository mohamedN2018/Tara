from django.urls import path

from . import views

app_name = "profiles"

urlpatterns = [
    # Own profile
    path("profile/me/", views.MyProfileView.as_view(), name="me"),
    path("profile/me/privacy/", views.FieldPrivacyView.as_view(), name="field-privacy"),
    path("profile/me/links/", views.LinksView.as_view(), name="links"),
    path("profile/me/links/<int:pk>/", views.LinkDetailView.as_view(), name="link-detail"),
    path("profile/me/education/", views.EducationView.as_view(), name="education"),
    path(
        "profile/me/education/<int:pk>/",
        views.EducationDetailView.as_view(),
        name="education-detail",
    ),
    path("profile/me/work/", views.WorkView.as_view(), name="work"),
    path("profile/me/work/<int:pk>/", views.WorkDetailView.as_view(), name="work-detail"),
    # Public profile
    path("users/<str:handle>/", views.PublicProfileView.as_view(), name="public-profile"),
    # Pages
    path("pages/", views.PageCreateView.as_view(), name="page-create"),
    path("pages/<str:handle>/", views.PageByHandleView.as_view(), name="page-by-handle"),
    path("pages/id/<uuid:page_id>/", views.PageDetailView.as_view(), name="page-detail"),
    path("pages/id/<uuid:page_id>/members/", views.PageMembersView.as_view(), name="page-members"),
    path(
        "pages/id/<uuid:page_id>/members/<uuid:member_id>/",
        views.PageMemberDetailView.as_view(),
        name="page-member-detail",
    ),
]
