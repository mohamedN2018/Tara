from django.apps import AppConfig


class GatheringsConfig(AppConfig):
    """Events with RSVP (roadmap 1.13). Named ``gatherings`` so it never clashes
    with each service's ``events.py`` emit module or the event-bus vocabulary."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "gatherings"
    verbose_name = "Gatherings (events)"
