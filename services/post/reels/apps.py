from django.apps import AppConfig


class ReelsConfig(AppConfig):
    """Reels (roadmap 5.5 / 5.8): short vertical videos. Each reel is a ``Post``
    of type ``reel`` (the authority for audience, deletion and moderation) plus
    a ``Reel`` row with what only reels need. Lives in ``post_db``; the outbox,
    ``BlockedPair`` and idempotency tables are the posts app's."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "reels"
    verbose_name = "Reels"
