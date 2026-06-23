"""Identity API routes, mounted under /api/v1/ by config.urls."""

from django.urls import path

from . import views

app_name = "identity"

urlpatterns = [
    # Auth
    path("auth/register/", views.RegisterView.as_view(), name="register"),
    path("auth/login/", views.LoginView.as_view(), name="login"),
    path("auth/refresh/", views.RefreshView.as_view(), name="refresh"),
    path("auth/logout/", views.LogoutView.as_view(), name="logout"),
    path("auth/verify-email/", views.VerifyEmailView.as_view(), name="verify-email"),
    path("auth/password/forgot/", views.PasswordForgotView.as_view(), name="password-forgot"),
    path("auth/password/reset/", views.PasswordResetView.as_view(), name="password-reset"),
    # Sessions
    path("auth/sessions/", views.SessionListView.as_view(), name="session-list"),
    path(
        "auth/sessions/<uuid:session_id>/", views.SessionDeleteView.as_view(), name="session-delete"
    ),
    # Account
    path("me/", views.MeView.as_view(), name="me"),
]
