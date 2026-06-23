from django.urls import path

from .views import InternalRolesView

urlpatterns = [
    path("roles/<uuid:account_id>/", InternalRolesView.as_view(), name="internal-roles"),
]
