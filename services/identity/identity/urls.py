"""Identity API routes, mounted under /api/v1/ by config.urls."""

from django.urls import path

from . import security_views, settings_views, views

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
    # Settings centre (plan 08 wave 3C)
    path("me/2fa/", settings_views.TwoFactorView.as_view(), name="me-2fa"),
    path("me/2fa/setup/", settings_views.TwoFactorSetupView.as_view(), name="me-2fa-setup"),
    path("me/2fa/confirm/", settings_views.TwoFactorConfirmView.as_view(), name="me-2fa-confirm"),
    path("me/2fa/disable/", settings_views.TwoFactorDisableView.as_view(), name="me-2fa-disable"),
    path(
        "me/2fa/recovery-codes/",
        settings_views.RecoveryCodesView.as_view(),
        name="me-2fa-recovery-codes",
    ),
    path(
        "me/security/activity/",
        settings_views.SecurityActivityView.as_view(),
        name="me-security-activity",
    ),
    path("me/devices/", settings_views.DeviceListView.as_view(), name="me-devices"),
    path(
        "me/devices/<uuid:device_id>/",
        settings_views.DeviceDetailView.as_view(),
        name="me-device",
    ),
    path("me/deactivate/", settings_views.DeactivateView.as_view(), name="me-deactivate"),
    path("me/delete/", settings_views.DeleteAccountView.as_view(), name="me-delete"),
    # Friends' birthdays today and this week (plan 08, social shell).
    path("me/birthdays/", settings_views.FriendBirthdaysView.as_view(), name="me-birthdays"),
    # What the caller may see of someone's birthday and gender. Under /me/ so
    # the edge's identity route covers it.
    path(
        "me/people/<uuid:account_id>/personal/",
        settings_views.PersonalDetailsView.as_view(),
        name="personal-details",
    ),
]
