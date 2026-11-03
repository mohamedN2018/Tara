from django.urls import path

from . import views

app_name = "gatherings"

urlpatterns = [
    path("events/", views.GatheringListCreateView.as_view(), name="event-list"),
    path("events/<uuid:gathering_id>/", views.GatheringDetailView.as_view(), name="event-detail"),
    path(
        "events/<uuid:gathering_id>/cancel/",
        views.GatheringCancelView.as_view(),
        name="event-cancel",
    ),
    path("events/<uuid:gathering_id>/rsvp/", views.GatheringRSVPView.as_view(), name="event-rsvp"),
    path(
        "events/<uuid:gathering_id>/attendees/",
        views.GatheringAttendeesView.as_view(),
        name="event-attendees",
    ),
    path(
        "events/<uuid:gathering_id>/invite/",
        views.GatheringInviteView.as_view(),
        name="event-invite",
    ),
    path(
        "events/<uuid:gathering_id>/report/",
        views.GatheringReportView.as_view(),
        name="event-report",
    ),
]
