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
