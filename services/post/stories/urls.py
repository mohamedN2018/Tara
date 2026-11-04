from django.urls import path

from . import views

app_name = "stories"

urlpatterns = [
    path("stories/", views.StoryListCreateView.as_view(), name="story-list"),
    path("stories/tray/", views.StoryTrayView.as_view(), name="story-tray"),
    path("stories/archive/", views.StoryArchiveView.as_view(), name="story-archive"),
    path("stories/close-friends/", views.CloseFriendsView.as_view(), name="close-friends"),
    path(
        "stories/close-friends/<uuid:account_id>/",
        views.CloseFriendDetailView.as_view(),
        name="close-friend-detail",
    ),
    path("stories/<uuid:story_id>/", views.StoryDetailView.as_view(), name="story-detail"),
    path("stories/<uuid:story_id>/seen/", views.StorySeenView.as_view(), name="story-seen"),
    path(
        "stories/<uuid:story_id>/viewers/", views.StoryViewersView.as_view(), name="story-viewers"
    ),
    path("stories/<uuid:story_id>/react/", views.StoryReactView.as_view(), name="story-react"),
    path("stories/<uuid:story_id>/report/", views.StoryReportView.as_view(), name="story-report"),
]
