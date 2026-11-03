from django.apps import AppConfig


class GroupsConfig(AppConfig):
    """Groups (roadmap 1.11): the group, its members and roles, rules and reports.

    A separate app in ``profile_db`` so it can be extracted later. The outbox,
    ``BlockedPair`` and idempotency tables are the profiles app's: one service,
    one outbox."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "groups"
    verbose_name = "Groups"
