from django.urls import path

from . import views

app_name = "feed"

urlpatterns = [
    path("feed/", views.HomeFeedView.as_view(), name="home-feed"),
]
