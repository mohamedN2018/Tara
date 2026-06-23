from django.urls import path

from . import views

app_name = "media_app"

urlpatterns = [
    path("media/uploads/sign/", views.SignUploadView.as_view(), name="sign-upload"),
    path(
        "media/uploads/<uuid:media_id>/complete/",
        views.CompleteUploadView.as_view(),
        name="complete-upload",
    ),
    path("media/<uuid:media_id>/", views.MediaDetailView.as_view(), name="media-detail"),
    path(
        "media/<uuid:media_id>/download-url/", views.DownloadUrlView.as_view(), name="download-url"
    ),
]
