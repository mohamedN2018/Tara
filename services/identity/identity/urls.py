"""Identity API routes, mounted under /api/v1/ by config.urls."""

from django.urls import path

from . import security_views, views

app_name = "identity"

urlpatterns = [
    # Auth
    path("auth/providers/", security_views.AuthProvidersView.as_view(), name="auth-providers"),
    path("auth/google/", security_views.GoogleSignInView.as_view(), name="google-sign-in"),
    path(
        "auth/email/confirm/",
        security_views.ConfirmEmailChangeView.as_view(),
        name="email-change-confirm",
    ),
    path(
        "auth/telegram/webhook/",
        security_views.TelegramWebhookView.as_view(),
        name="telegram-webhook",
    ),
    path("auth/register/", views.RegisterView.as_view(), name="register"),
    path("auth/login/", views.LoginView.as_view(), name="login"),
    path("auth/refresh/", views.RefreshView.as_view(), name="refresh"),
    path("auth/logout/", views.LogoutView.as_view(), name="logout"),
    path("auth/verify-email/", views.VerifyEmailView.as_view(), name="verify-email"),
    path(
        "auth/verify-email/resend/",
        views.ResendVerificationView.as_view(),
        name="verify-email-resend",
    ),
    path("auth/password/forgot/", views.PasswordForgotView.as_view(), name="password-forgot"),
    path("auth/password/reset/", views.PasswordResetView.as_view(), name="password-reset"),
    # Sessions
    path("auth/sessions/", views.SessionListView.as_view(), name="session-list"),
    path(
        "auth/sessions/<uuid:session_id>/", views.SessionDeleteView.as_view(), name="session-delete"
    ),
    # Account
    path("me/", views.MeView.as_view(), name="me"),
    path("me/security/", security_views.SecurityOverviewView.as_view(), name="me-security"),
    path("me/password/", security_views.ChangePasswordView.as_view(), name="me-password"),
    path("me/email/", security_views.ChangeEmailView.as_view(), name="me-email"),
    path("me/google/", security_views.GoogleLinkView.as_view(), name="me-google"),
    path("me/phone/", security_views.PhoneView.as_view(), name="me-phone"),
    path(
        "me/phone/telegram/",
        security_views.TelegramPhoneStartView.as_view(),
        name="me-phone-telegram",
    ),
]
