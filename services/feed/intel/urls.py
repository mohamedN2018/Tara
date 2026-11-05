from django.urls import path

from . import views

app_name = "intel"

urlpatterns = [
    path("feed/signals/", views.SignalIngestView.as_view(), name="signals"),
]
