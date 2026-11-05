from django.urls import path

from . import views

app_name = "intel"

urlpatterns = [
    path("feed/signals/", views.SignalIngestView.as_view(), name="signals"),
    path("feed/preferences/", views.PreferencesView.as_view(), name="preferences"),
    path("feed/why/<str:item_type>/<str:item_id>/", views.WhyView.as_view(), name="why"),
]
