from django.urls import path

from . import views

app_name = "graph"

urlpatterns = [
    # Friends
    path("friends/", views.FriendListView.as_view(), name="friend-list"),
    path("friends/requests/", views.FriendRequestsView.as_view(), name="friend-requests"),
    path(
        "friends/requests/<uuid:request_id>/accept/",
        views.FriendRequestAcceptView.as_view(),
        name="friend-accept",
    ),
    path(
        "friends/requests/<uuid:request_id>/reject/",
        views.FriendRequestRejectView.as_view(),
        name="friend-reject",
    ),
    path("friends/<uuid:user_id>/", views.FriendDeleteView.as_view(), name="friend-delete"),
    # Follows
    path("follows/followers/", views.FollowersView.as_view(), name="followers"),
    path("follows/following/", views.FollowingView.as_view(), name="following"),
    path("follows/<uuid:user_id>/", views.FollowView.as_view(), name="follow"),
    # Blocks
    path("blocks/", views.BlockListView.as_view(), name="block-list"),
    path("blocks/<uuid:user_id>/", views.BlockView.as_view(), name="block"),
    # Public relationship lists
    path(
        "social/<uuid:user_id>/friends/", views.SocialFriendsView.as_view(), name="social-friends"
    ),
    path(
        "social/<uuid:user_id>/followers/",
        views.SocialFollowersView.as_view(),
        name="social-followers",
    ),
    path("social/<uuid:user_id>/mutual/", views.SocialMutualView.as_view(), name="social-mutual"),
]
