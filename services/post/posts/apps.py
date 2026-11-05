from django.apps import AppConfig


class PostsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "posts"
    verbose_name = "Posts"

    def ready(self) -> None:
        try:
            from tara_observability.tracing import setup_tracing

            setup_tracing("post")
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

        # post_batch_dropped_total (intelligence WP 3.6), read from the shared cache.
        try:
            from .hydration import register

            register()
        except Exception:  # noqa: S110,BLE001 - metrics must never block boot
            pass
