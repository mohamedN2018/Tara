"""Media domain models (owns `media_db`). The only context that talks to object storage."""

from __future__ import annotations

from django.db import models

from tara_events.envelope import uuid7
from tara_events.models import AbstractOutboxEvent, AbstractProcessedEvent


class MediaAsset(models.Model):
    class Kind(models.TextChoices):
        IMAGE = "image", "Image"
        VIDEO = "video", "Video"
        AUDIO = "audio", "Audio"
        VOICE = "voice", "Voice note"
        FILE = "file", "File"

    class Status(models.TextChoices):
        UPLOADING = "uploading", "Uploading"
        PROCESSING = "processing", "Processing"
        READY = "ready", "Ready"
        FAILED = "failed", "Failed"

    class Visibility(models.TextChoices):
        PUBLIC = "public", "Public"
        PRIVATE = "private", "Private"

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    owner_id = models.UUIDField()  # account that uploaded it
    kind = models.CharField(max_length=8, choices=Kind.choices)
    storage_key = models.CharField(max_length=300)
    # The stored object's real size: the declared size until completion, then
    # what storage reports (and, for images, the size after EXIF removal).
    bytes = models.BigIntegerField(default=0)
    etag = models.CharField(max_length=128, blank=True, default="")
    mime = models.CharField(max_length=120, blank=True, default="")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.UPLOADING)
    scan_status = models.CharField(max_length=12, default="pending")  # virus-scan hook
    visibility = models.CharField(
        max_length=8, choices=Visibility.choices, default=Visibility.PUBLIC
    )
    # The post this media is attached to (a bare id in post_db). When
    # ``restricted``, only the owner and viewers the post service says can see
    # that post may read it; ``visibility`` is then ignored.
    post_id = models.UUIDField(null=True, blank=True)
    restricted = models.BooleanField(default=False)
    error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "media_asset"
        indexes = [models.Index(fields=["owner_id", "kind"], name="media_owner_kind_idx")]


class MediaVariant(models.Model):
    class Kind(models.TextChoices):
        THUMB = "thumb", "Thumbnail"
        TRANSCODE = "transcode", "Transcode"
        WAVEFORM = "waveform", "Waveform"
        PREVIEW = "preview", "Preview"

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    media = models.ForeignKey(MediaAsset, on_delete=models.CASCADE, related_name="variants")
    kind = models.CharField(max_length=12, choices=Kind.choices)
    storage_key = models.CharField(max_length=300)
    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)
    duration_ms = models.PositiveIntegerField(null=True, blank=True)
    bitrate = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "media_variant"


class UploadSession(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    media = models.OneToOneField(
        MediaAsset, on_delete=models.CASCADE, related_name="upload_session"
    )
    # Where the presigned PUT writes. ``complete()`` verifies it and copies it to
    # the asset's key, so a replayed PUT can never change the verified object.
    # Empty for sessions signed before staging keys existed.
    staging_key = models.CharField(max_length=300, blank=True, default="")
    expires_at = models.DateTimeField()
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "upload_session"


class OutboxEvent(AbstractOutboxEvent):
    class Meta(AbstractOutboxEvent.Meta):
        abstract = False
        db_table = "outbox_event"


class ProcessedEvent(AbstractProcessedEvent):
    class Meta(AbstractProcessedEvent.Meta):
        abstract = False
        db_table = "processed_event"
