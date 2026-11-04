from django.apps import AppConfig


class StoriesConfig(AppConfig):
    """Stories and close friends (roadmap 1.9). Lives in ``post_db``; the outbox,
    ``BlockedPair`` and idempotency tables are the posts app's."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "stories"
    verbose_name = "Stories"
