from django.urls import path

from . import views

app_name = "ads"

urlpatterns = [
    path("ads/campaigns/", views.CampaignsView.as_view(), name="campaigns"),
    path(
        "ads/campaigns/<uuid:campaign_id>/report/",
        views.CampaignReportView.as_view(),
        name="campaign-report",
    ),
    path("ads/campaigns/<uuid:campaign_id>/ad-sets/", views.AdSetsView.as_view(), name="ad-sets"),
    path(
        "ads/ad-sets/<uuid:ad_set_id>/creatives/", views.CreativesView.as_view(), name="creatives"
    ),
    path("ads/creatives/<uuid:creative_id>/review/", views.ReviewView.as_view(), name="review"),
    path("ads/events/", views.EventsView.as_view(), name="events"),
]
