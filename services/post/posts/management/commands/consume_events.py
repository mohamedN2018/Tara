"""Run the event-bus consumer for the Post service."""

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Consume domain events from the bus and dispatch to registered handlers."

    def handle(self, *args, **options) -> None:
        import posts.handlers  # noqa: F401 - registers @on_event handlers
        from posts.models import ProcessedEvent
        from tara_events.worker import run_worker

        if not settings.TARA_EVENT_BROKER_URL:
            self.stderr.write("No broker configured (RABBITMQ_URL empty); nothing to consume.")
            return
        self.stdout.write(self.style.SUCCESS(f"consuming on {settings.TARA_EVENT_QUEUE}"))
        run_worker(
            broker_url=settings.TARA_EVENT_BROKER_URL,
            exchange_name=settings.TARA_EVENT_EXCHANGE,
            queue_name=settings.TARA_EVENT_QUEUE,
            processed_model=ProcessedEvent,
            consumer_name=settings.SERVICE_NAME,
        )
