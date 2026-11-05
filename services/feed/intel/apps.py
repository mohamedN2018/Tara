"""Tara Intelligence: ranking, discovery and telemetry inside the feed service.

docs/intelligence/02-architecture.md A1: a Django app of its own (tables prefixed
``intel_``, UUID columns only, no ForeignKey into ``feed``), reaching ``feed`` code
only through ``intel.ports``, so a later split is mechanical.
"""

from django.apps import AppConfig


class IntelConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "intel"
    verbose_name = "Tara Intelligence"

    def ready(self) -> None:
        from tara_common import health

        from . import checks, readiness

        checks.register()
        health.register_readiness_check("intel_synthetic", readiness.synthetic_registry_check)
