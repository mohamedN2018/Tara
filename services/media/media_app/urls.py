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
    path("media/<uuid:media_id>/playback/", views.PlaybackView.as_view(), name="playback"),
    # The gunicorn logger and the web edge skip ``/hls/``: the token is in the URL.
    path(
        "media/<uuid:media_id>/hls/master.m3u8",
        views.MasterPlaylistView.as_view(),
        name="hls-master",
    ),
    path(
        "media/<uuid:media_id>/hls/<int:rung>.m3u8",
        views.RenditionPlaylistView.as_view(),
        name="hls-rendition",
    ),
]
