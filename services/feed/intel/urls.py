from django.urls import path

from . import api, views

app_name = "intel"

urlpatterns = [
    path("feed/signals/", views.SignalIngestView.as_view(), name="signals"),
    path("feed/preferences/", api.PreferencesView.as_view(), name="preferences"),
    # R4 (04 WP 6.4, 6.6, 7.1, 8.1; 07 WP 8.4-B2, 8.5-B2): My Algorithm and feedback.
    path("feed/preferences/undo/", api.PreferencesUndoView.as_view(), name="preferences-undo"),
    path("feed/preferences/profile/", api.ProfileView.as_view(), name="profile"),
    path(
        "feed/preferences/profile/<str:dim>/<str:key>/",
        api.ProfileRowView.as_view(),
        name="profile-row",
    ),
    path("feed/preferences/onboarding/", api.OnboardingView.as_view(), name="onboarding"),
    path("feed/preferences/reset/", api.ResetView.as_view(), name="reset"),
    path("feed/preferences/debug-consent/", api.DebugConsentView.as_view(), name="debug-consent"),
    path("feed/feedback/", api.FeedbackView.as_view(), name="feedback"),
    path("feed/feedback/<uuid:action_id>/", api.FeedbackUndoView.as_view(), name="feedback-undo"),
    path("feed/topics/", api.TopicsView.as_view(), name="topics"),
    path("feed/why/<str:item_type>/<str:item_id>/", views.WhyView.as_view(), name="why"),
]
