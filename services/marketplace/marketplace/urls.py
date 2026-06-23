from django.urls import path

from . import views

app_name = "marketplace"

urlpatterns = [
    path("marketplace/categories/", views.CategoriesView.as_view(), name="categories"),
    path("marketplace/listings/", views.ListingsView.as_view(), name="listings"),
    path("marketplace/my-listings/", views.MyListingsView.as_view(), name="my-listings"),
    path("marketplace/saved/", views.SavedListView.as_view(), name="saved"),
    path(
        "marketplace/listings/<uuid:listing_id>/",
        views.ListingDetailView.as_view(),
        name="listing-detail",
    ),
    path(
        "marketplace/listings/<uuid:listing_id>/publish/",
        views.PublishView.as_view(),
        name="publish",
    ),
    path(
        "marketplace/listings/<uuid:listing_id>/transition/",
        views.TransitionView.as_view(),
        name="transition",
    ),
    path("marketplace/listings/<uuid:listing_id>/save/", views.SaveView.as_view(), name="save"),
    path(
        "marketplace/listings/<uuid:listing_id>/report/", views.ReportView.as_view(), name="report"
    ),
    path(
        "marketplace/listings/<uuid:listing_id>/contact/",
        views.ContactView.as_view(),
        name="contact",
    ),
]
