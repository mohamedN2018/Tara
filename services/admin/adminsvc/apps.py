from django.apps import AppConfig


class AdminSvcConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "adminsvc"
    verbose_name = "Admin"

    def ready(self) -> None:
        try:
            from tara_observability.tracing import setup_tracing

            setup_tracing("admin")
        except Exception:  # noqa: S110,BLE001 - observability must never block boot
            pass

        # Enforce production-safety on `manage.py check --deploy`.
        try:
            from tara_common.checks import register_checks

            register_checks()
        except Exception:  # noqa: S110,BLE001 - never block boot on check wiring
            pass
