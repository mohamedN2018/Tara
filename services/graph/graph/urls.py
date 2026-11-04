from django.urls import path

from . import social_views, views

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
    path(
        "social/<uuid:user_id>/following/",
        social_views.SocialFollowingView.as_view(),
        name="social-following",
    ),
    path(
        "social/<uuid:user_id>/counts/",
        social_views.SocialCountsView.as_view(),
        name="social-counts",
    ),
    # Owner-only: relationship privacy (1.6)
    path(
        "social/settings/",
        social_views.RelationshipSettingsView.as_view(),
        name="social-settings",
    ),
    # Suggestions (1.6, plan 08 track 2D)
    path(
        "social/suggestions/",
        social_views.PeopleSuggestionsView.as_view(),
        name="suggestions-people",
    ),
    path(
        "social/suggestions/pages/",
        social_views.PageSuggestionsView.as_view(),
        name="suggestions-pages",
    ),
    path(
        "social/suggestions/<uuid:target_id>/dismiss/",
        social_views.DismissSuggestionView.as_view(),
        name="suggestion-dismiss",
    ),
    # Owner-only preferences: mute, restrict, favorites (plan 08 track 2D)
    path("social/mutes/", social_views.MutesView.as_view(), name="mutes"),
    path("social/mutes/<uuid:user_id>/", social_views.MuteView.as_view(), name="mute"),
    path("social/restricted/", social_views.RestrictsView.as_view(), name="restricts"),
    path(
        "social/restricted/<uuid:user_id>/",
        social_views.RestrictView.as_view(),
        name="restrict",
    ),
    path("social/favorites/", social_views.FavoritesView.as_view(), name="favorites"),
    path(
        "social/favorites/<uuid:user_id>/",
        social_views.FavoriteView.as_view(),
        name="favorite",
    ),
]
