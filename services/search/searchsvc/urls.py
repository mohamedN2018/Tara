from django.urls import path

from . import views

app_name = "searchsvc"

urlpatterns = [
    path("search/", views.SearchView.as_view(), name="search"),
    path("search/suggest/", views.SuggestView.as_view(), name="suggest"),
    path("search/autocomplete/", views.AutocompleteView.as_view(), name="autocomplete"),
    path("search/recent/", views.RecentSearchesView.as_view(), name="recent"),
    path(
        "search/recent/<uuid:entry_id>/",
        views.RecentSearchDetailView.as_view(),
        name="recent-detail",
    ),
    path("search/trending/", views.TrendingView.as_view(), name="trending"),
]
