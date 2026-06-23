from django.urls import path

from .internal_views import FanoutAudienceView, RelationshipView

urlpatterns = [
    path("relationship/", RelationshipView.as_view(), name="relationship"),
    path("fanout/<uuid:account_id>/", FanoutAudienceView.as_view(), name="fanout-audience"),
]
