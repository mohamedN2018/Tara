"""Identity domain models.

This service owns `identity_db`. It holds credentials, sessions, tokens, and
security state — NOT profile content or social data (those live in their own
services). Public ids are UUIDv7 (ADR-007).
"""

from __future__ import annotations

from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models

from tara_events.envelope import uuid7
from tara_events.models import AbstractOutboxEvent, AbstractProcessedEvent
from tara_resilience.idempotency import AbstractIdempotencyRecord

from .managers import AccountManager


class PersonalVisibility(models.TextChoices):
    """Who sees a personal detail kept in identity (birthday, gender)."""

    FRIENDS = "friends", "Friends"
    ONLY_ME = "only_me", "Only me"


class Gender(models.TextChoices):
    FEMALE = "female", "Female"
    MALE = "male", "Male"
    CUSTOM = "custom", "Custom"  # the words are in Account.gender_custom
    UNDISCLOSED = "prefer_not_to_say", "Prefer not to say"


class Account(AbstractBaseUser, PermissionsMixin):
    """The single central identity for a human user."""

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        PENDING = "pending", "Pending verification"
        SUSPENDED = "suspended", "Suspended"
        DEACTIVATED = "deactivated", "Deactivated"
        DELETED = "deleted", "Deleted"

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    email = models.EmailField(unique=True)
    email_verified = models.BooleanField(default=False)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)

    # Preferences mirrored to clients (single source of truth for these two).
    language = models.CharField(max_length=8, default="en")
    theme = models.CharField(max_length=8, default="system")  # light | dark | system

    is_staff = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_login_at = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    # E.164-ish number proven through the Telegram bot's "share contact" button.
    # Set only together with phone_verified_at (see telegram.py).
    phone = models.CharField(max_length=32, blank=True, default="")
    phone_verified_at = models.DateTimeField(null=True, blank=True)

    # Self-declared at signup (roadmap 2.12). Age leaves identity only as the
    # `is_minor` / `age_band` token claims: never on the bus, never to ads.
    # Null for accounts created before 2.12 (and Google sign-ups), whose
    # `age_band` is `unknown`.
    date_of_birth = models.DateField(null=True, blank=True)
    # Decision 5.3: a birthday shows day and month only, to friends by default.
    birthday_visibility = models.CharField(
        max_length=16, choices=PersonalVisibility.choices, default=PersonalVisibility.FRIENDS
    )
    # Decision 5.8: optional, "only me" by default, never used for ads.
    gender = models.CharField(max_length=24, choices=Gender.choices, blank=True, default="")
    gender_custom = models.CharField(max_length=40, blank=True, default="")
    gender_visibility = models.CharField(
        max_length=16, choices=PersonalVisibility.choices, default=PersonalVisibility.ONLY_ME
    )

    objects = AccountManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    class Meta:
        db_table = "account"
        indexes = [models.Index(fields=["status"], name="account_status_idx")]
        constraints = [
            # One account per verified phone number.
            models.UniqueConstraint(
                fields=["phone"],
                condition=models.Q(phone_verified_at__isnull=False),
                name="account_verified_phone_uniq",
            ),
        ]

    def __str__(self) -> str:
        return self.email

    @property
    def is_usable(self) -> bool:
        return self.status == self.Status.ACTIVE and self.is_active

    @property
    def phone_verified(self) -> bool:
        return self.phone_verified_at is not None


class AccountRole(models.Model):
    """Platform roles. Identity owns them, and ``roles`` in the access token reads them.

    ``is_superuser`` and ``is_staff`` still count as admin and moderator (see tokens.py).
    """

    class Role(models.TextChoices):
        ADMIN = "admin", "Admin"
        MODERATOR = "moderator", "Moderator"
        AD_REVIEWER = "ad_reviewer", "Ad reviewer"
        ANALYST = "analyst", "Analyst"

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="role_grants")
    role = models.CharField(max_length=32, choices=Role.choices)
    granted_by = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "account_role"
        constraints = [
            models.UniqueConstraint(fields=["account", "role"], name="account_role_uniq"),
        ]


class AccountSuspension(models.Model):
    """One suspension of an account (roadmap 8.4, 8.6). Identity owns them.

    While a row has no ``lifted_at`` the account's status is ``suspended``:
    login and refresh refuse it, and its sessions were revoked when the row was
    made. ``until`` (optional) is when it lifts by itself; the beat task and the
    next login attempt lift an expired one. ``previous_status`` is what the
    account goes back to (a pending account stays pending). The idempotency key
    makes a retried request (admin's dialog, moderation's case action in 8.4)
    apply once. ``reason`` is staff-written and never goes on the bus.
    """

    class Source(models.TextChoices):
        ADMIN = "admin", "Admin console"
        MODERATION = "moderation", "Moderation case"

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="suspensions")
    reason = models.CharField(max_length=500)
    until = models.DateTimeField(null=True, blank=True)
    previous_status = models.CharField(max_length=16, choices=Account.Status.choices)
    source = models.CharField(max_length=16, choices=Source.choices, default=Source.ADMIN)
    idempotency_key = models.CharField(max_length=100, unique=True)
    created_by = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    lifted_at = models.DateTimeField(null=True, blank=True)
    # None with ``lifted_at`` set: lifted by the system (expiry).
    lifted_by = models.UUIDField(null=True, blank=True)
    lift_reason = models.CharField(max_length=500, blank=True, default="")

    class Meta:
        db_table = "account_suspension"
        constraints = [
            models.UniqueConstraint(
                fields=["account"],
                condition=models.Q(lifted_at__isnull=True),
                name="suspension_one_active_uniq",
            ),
        ]
        indexes = [
            models.Index(
                fields=["until"],
                condition=models.Q(lifted_at__isnull=True, until__isnull=False),
                name="suspension_expiry_idx",
            ),
            models.Index(fields=["account", "-created_at"], name="suspension_account_idx"),
        ]

    @property
    def is_active(self) -> bool:
        return self.lifted_at is None


class LegalConsent(models.Model):
    """One acceptance of the terms and the privacy policy (decision 5.14).

    The versions are the ones the person was shown and the server accepted
    (``LEGAL_TERMS_VERSION`` / ``LEGAL_PRIVACY_VERSION``). ``ip_hash`` is a
    keyed HMAC of the client address, never the address itself: enough to tell
    two consents came from one place, not to say where that is.
    """

    class Source(models.TextChoices):
        REGISTER = "register", "Registration"

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="legal_consents")
    terms_version = models.CharField(max_length=40)
    privacy_version = models.CharField(max_length=40)
    source = models.CharField(max_length=16, choices=Source.choices, default=Source.REGISTER)
    ip_hash = models.CharField(max_length=64, blank=True, default="")
    accepted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "legal_consent"
        indexes = [models.Index(fields=["account", "-accepted_at"], name="consent_account_idx")]


class RoleCapability(models.Model):
    """One cell of the capability matrix that differs from the code defaults.

    ``tara_common.capabilities.DEFAULT_ROLE_CAPABILITIES`` holds the defaults; a
    row grants (``granted=True``) or revokes a capability for a role on top of
    them. No row means the default applies. Edited only through admin (8.12).
    """

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    role = models.CharField(max_length=32, choices=AccountRole.Role.choices)
    capability = models.CharField(max_length=80)
    granted = models.BooleanField()
    updated_by = models.UUIDField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "role_capability"
        constraints = [
            models.UniqueConstraint(fields=["role", "capability"], name="role_capability_uniq"),
        ]


class Device(models.Model):
    class Platform(models.TextChoices):
        WEB = "web", "Web"
        IOS = "ios", "iOS"
        ANDROID = "android", "Android"

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="devices")
    platform = models.CharField(max_length=12, choices=Platform.choices, default=Platform.WEB)
    label = models.CharField(max_length=120, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "device"


class UserSession(models.Model):
    """A login session bound to a device, the unit refresh tokens belong to."""

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="sessions")
    device = models.ForeignKey(Device, on_delete=models.SET_NULL, null=True, blank=True)
    ip_region = models.CharField(max_length=80, blank=True, default="")  # coarse, not raw IP
    user_agent = models.CharField(max_length=400, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "user_session"
        indexes = [models.Index(fields=["account", "revoked_at"], name="session_account_idx")]

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None


class RefreshToken(models.Model):
    """Opaque, rotating refresh token. Only the SHA-256 hash is stored.

    Rotation forms a `family`; presenting an already-used/revoked token triggers
    reuse detection that revokes the whole family (ADR-005).
    """

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="refresh_tokens")
    session = models.ForeignKey(
        UserSession, on_delete=models.CASCADE, related_name="refresh_tokens"
    )
    token_hash = models.CharField(max_length=64, unique=True)
    family_id = models.UUIDField()
    rotated_from = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "refresh_token"
        indexes = [
            models.Index(fields=["family_id"], name="refresh_family_idx"),
            models.Index(fields=["account", "expires_at"], name="refresh_account_idx"),
        ]


class EmailVerification(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    account = models.ForeignKey(
        Account, on_delete=models.CASCADE, related_name="email_verifications"
    )
    token_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "email_verification"


class PasswordReset(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="password_resets")
    token_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "password_reset"


class SocialIdentity(models.Model):
    """An external login (Google) linked to an account.

    Keyed on the provider's stable subject id (`sub`), never on the email: the
    email at the provider can change or be recycled, the subject cannot.
    """

    class Provider(models.TextChoices):
        GOOGLE = "google", "Google"

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="social_identities")
    provider = models.CharField(max_length=16, choices=Provider.choices)
    subject = models.CharField(max_length=255)
    email = models.EmailField(blank=True, default="")  # as last reported by the provider
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "social_identity"
        constraints = [
            models.UniqueConstraint(fields=["provider", "subject"], name="social_subject_uniq"),
            models.UniqueConstraint(fields=["account", "provider"], name="social_account_uniq"),
        ]


class EmailChangeRequest(models.Model):
    """A pending email change. The address only changes once the link sent to
    the NEW address is opened (proving the user owns it)."""

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="email_changes")
    new_email = models.EmailField()
    token_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "email_change_request"
        indexes = [models.Index(fields=["account", "created_at"], name="emailchange_account_idx")]


class PhoneVerification(models.Model):
    """One Telegram phone-verification attempt.

    The deep-link code is stored hashed. `/start <code>` binds the Telegram
    chat and user; only a contact shared by that same Telegram user, for
    themselves, completes it.
    """

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    account = models.ForeignKey(
        Account, on_delete=models.CASCADE, related_name="phone_verifications"
    )
    code_hash = models.CharField(max_length=64, unique=True)
    telegram_chat_id = models.CharField(max_length=32, blank=True, default="")
    telegram_user_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "phone_verification"
        indexes = [models.Index(fields=["telegram_chat_id"], name="phonever_chat_idx")]


class SecurityEvent(models.Model):
    """Append-only security log (login, logout, reuse-detected, reset, ...)."""

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    account = models.ForeignKey(
        Account, on_delete=models.SET_NULL, null=True, blank=True, related_name="security_events"
    )
    type = models.CharField(max_length=60)
    ip_region = models.CharField(max_length=80, blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "security_event"
        indexes = [models.Index(fields=["account", "created_at"], name="secevent_account_idx")]


class TwoFactorSecret(models.Model):
    """2FA scaffolding (TOTP). Present now; enabled in a later phase."""

    account = models.OneToOneField(Account, on_delete=models.CASCADE, primary_key=True)
    type = models.CharField(max_length=16, default="totp")
    secret_enc = models.BinaryField()
    confirmed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "two_factor_secret"


# ---- Platform tables this service owns (concrete subclasses of shared kernel) ----


class OutboxEvent(AbstractOutboxEvent):
    class Meta(AbstractOutboxEvent.Meta):
        abstract = False  # reset: inheriting an abstract Meta re-inherits abstract=True
        db_table = "outbox_event"


class ProcessedEvent(AbstractProcessedEvent):
    class Meta(AbstractProcessedEvent.Meta):
        abstract = False
        db_table = "processed_event"


class IdempotencyRecord(AbstractIdempotencyRecord):
    class Meta(AbstractIdempotencyRecord.Meta):
        abstract = False
        db_table = "idempotency_record"
