from django.urls import path

from .internal_views import (
    FanoutAudienceView,
    FriendIdsView,
    PreferencesView,
    RelationshipBatchView,
    RelationshipView,
)

urlpatterns = [
    path("relationship/", RelationshipView.as_view(), name="relationship"),
    path("fanout/<uuid:account_id>/", FanoutAudienceView.as_view(), name="fanout-audience"),
    path("relationships/batch/", RelationshipBatchView.as_view(), name="relationship-batch"),
    path("preferences/<uuid:account_id>/", PreferencesView.as_view(), name="preferences"),
    path("friends/<uuid:account_id>/", FriendIdsView.as_view(), name="internal-friend-ids"),
]
