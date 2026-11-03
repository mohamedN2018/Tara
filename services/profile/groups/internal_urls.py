from django.urls import path

from .internal_views import GroupAccessView

urlpatterns = [
    path("groups/<uuid:group_id>/access/", GroupAccessView.as_view(), name="group-access"),
]
