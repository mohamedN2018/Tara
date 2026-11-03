"""Run the event-bus consumer for the Profile service."""

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Consume domain events from the bus and dispatch to registered handlers."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--replay-dlq",
            action="store_true",
            help="Move dead-lettered events back to the queue, then exit.",
        )

    def handle(self, *args, **options) -> None:
        import groups.handlers  # noqa: F401

        import profiles.handlers  # noqa: F401 - registers @on_event handlers
        from profiles.models import ProcessedEvent
        from tara_events.worker import run_worker

        if not settings.TARA_EVENT_BROKER_URL:
            self.stderr.write("No broker configured (RABBITMQ_URL empty); nothing to consume.")
            return
        if options["replay_dlq"]:
            from tara_events.worker import replay_dead_letters

            moved = replay_dead_letters(
                broker_url=settings.TARA_EVENT_BROKER_URL, queue_name=settings.TARA_EVENT_QUEUE
            )
            self.stdout.write(self.style.SUCCESS(f"replayed {moved} events"))
            return
        self.stdout.write(self.style.SUCCESS(f"consuming on {settings.TARA_EVENT_QUEUE}"))
        run_worker(
            broker_url=settings.TARA_EVENT_BROKER_URL,
            exchange_name=settings.TARA_EVENT_EXCHANGE,
            queue_name=settings.TARA_EVENT_QUEUE,
            processed_model=ProcessedEvent,
            consumer_name=settings.SERVICE_NAME,
        )
