from django.urls import path

from . import views

app_name = "searchsvc"

urlpatterns = [
    path("search/", views.SearchView.as_view(), name="search"),
    path("search/autocomplete/", views.AutocompleteView.as_view(), name="autocomplete"),
]
