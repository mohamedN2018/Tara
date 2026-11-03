from django.urls import path

from . import views

app_name = "calls_internal"

# Service-to-service only (LiveKit -> chat). The edge never routes /internal/.
urlpatterns = [
    path("livekit/webhook/", views.livekit_webhook, name="livekit-webhook"),
]
