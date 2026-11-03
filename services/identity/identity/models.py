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

    objects = AccountManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    class Meta:
        db_table = "account"
        indexes = [models.Index(fields=["status"], name="account_status_idx")]

    def __str__(self) -> str:
        return self.email

    @property
    def is_usable(self) -> bool:
        return self.status == self.Status.ACTIVE and self.is_active


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
