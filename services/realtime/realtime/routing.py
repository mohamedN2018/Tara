from django.urls import path

from .consumers import TaraConsumer

websocket_urlpatterns = [
    path("ws/v1/", TaraConsumer.as_asgi()),
]
