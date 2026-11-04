from django.urls import path

from . import views

app_name = "marketplace"

urlpatterns = [
    path("marketplace/categories/", views.CategoriesView.as_view(), name="categories"),
    path("marketplace/listings/", views.ListingsView.as_view(), name="listings"),
    path("marketplace/listings/facets/", views.FacetsView.as_view(), name="facets"),
    path("marketplace/compare/", views.CompareView.as_view(), name="compare"),
    path("marketplace/my-listings/", views.MyListingsView.as_view(), name="my-listings"),
    path(
        "marketplace/my-listings/summary/",
        views.SellingSummaryView.as_view(),
        name="selling-summary",
    ),
    path("marketplace/inquiries/", views.InquiriesListView.as_view(), name="inquiries-list"),
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
        "marketplace/listings/<uuid:listing_id>/view/",
        views.ListingViewBeacon.as_view(),
        name="view",
    ),
    path(
        "marketplace/listings/<uuid:listing_id>/report/", views.ReportView.as_view(), name="report"
    ),
    path(
        "marketplace/listings/<uuid:listing_id>/contact/",
        views.ContactView.as_view(),
        name="contact",
    ),
    path(
        "marketplace/listings/<uuid:listing_id>/inquiries/",
        views.InquiryView.as_view(),
        name="inquiries",
    ),
    path(
        "marketplace/listings/<uuid:listing_id>/reviews/",
        views.ListingReviewsView.as_view(),
        name="listing-reviews",
    ),
    path("marketplace/sellers/<uuid:seller_id>/", views.SellerView.as_view(), name="seller"),
    path(
        "marketplace/sellers/<uuid:seller_id>/reviews/",
        views.SellerReviewsView.as_view(),
        name="seller-reviews",
    ),
    path(
        "marketplace/reviews/<uuid:review_id>/report/",
        views.ReviewReportView.as_view(),
        name="review-report",
    ),
]
