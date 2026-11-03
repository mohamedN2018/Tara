from django.urls import path

from .internal_views import FanoutAudienceView, RelationshipBatchView, RelationshipView

urlpatterns = [
    path("relationship/", RelationshipView.as_view(), name="relationship"),
    path("fanout/<uuid:account_id>/", FanoutAudienceView.as_view(), name="fanout-audience"),
    path("relationships/batch/", RelationshipBatchView.as_view(), name="relationship-batch"),
]
