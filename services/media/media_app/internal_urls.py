from django.urls import path

from .internal_views import InternalMediaView

urlpatterns = [
    path("media/<uuid:media_id>/", InternalMediaView.as_view(), name="internal-media"),
]
