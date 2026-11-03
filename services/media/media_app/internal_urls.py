from django.urls import path

from .internal_views import InternalMediaBatchView, InternalMediaBindView, InternalMediaView

urlpatterns = [
    path("media/batch/", InternalMediaBatchView.as_view(), name="internal-media-batch"),
    path("media/bind/", InternalMediaBindView.as_view(), name="internal-media-bind"),
    path("media/<uuid:media_id>/", InternalMediaView.as_view(), name="internal-media"),
]
