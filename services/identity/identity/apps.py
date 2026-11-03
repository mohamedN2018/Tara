from django.apps import AppConfig


class IdentityConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "identity"
    verbose_name = "Identity"

    def ready(self) -> None:
        # Optional OpenTelemetry tracing (no-op unless OTEL_ENABLED).
        try:
            from tara_observability.tracing import setup_tracing

            setup_tracing("identity")
        except Exception:  # noqa: S110,BLE001 - observability must never block boot
            pass

        from . import checks  # noqa: F401 - registers identity's deploy checks

        # Enforce production-safety on `manage.py check --deploy` (blocks dev
        # secrets / wildcard hosts when DEBUG=False). Every service registers
        # this the same way; see libs/tara_common/tara_common/checks.py.
        try:
            from tara_common.checks import register_checks

            register_checks()
            from tara_events.metrics import install_outbox_gauge

            install_outbox_gauge()
        except Exception:  # noqa: S110,BLE001 - never block boot on check wiring
            pass
