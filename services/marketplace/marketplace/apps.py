from django.apps import AppConfig


class MarketplaceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "marketplace"
    verbose_name = "Marketplace"

    def ready(self) -> None:
        try:
            from tara_observability.tracing import setup_tracing

            setup_tracing("marketplace")
        except Exception:  # noqa: S110,BLE001 - observability must never block boot
            pass

        # Enforce production-safety on `manage.py check --deploy`.
        try:
            from tara_common.checks import register_checks

            register_checks()
            from tara_events.metrics import install_outbox_gauge

            install_outbox_gauge()
        except Exception:  # noqa: S110,BLE001 - never block boot on check wiring
            pass
