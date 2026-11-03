"""Run the event-bus → WebSocket bridge (no DB; idempotency not needed)."""

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Consume domain events and push them to connected WebSocket clients."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--replay-dlq",
            action="store_true",
            help="Move dead-lettered events back to the queue, then exit.",
        )

    def handle(self, *args, **options) -> None:
        import realtime.bridge  # noqa: F401 - registers @on_event handlers
        from tara_events.worker import run_worker

        if not settings.TARA_EVENT_BROKER_URL:
            self.stderr.write("No broker configured (RABBITMQ_URL empty); nothing to bridge.")
            return
        if options["replay_dlq"]:
            from tara_events.worker import replay_dead_letters

            moved = replay_dead_letters(
                broker_url=settings.TARA_EVENT_BROKER_URL, queue_name=settings.TARA_EVENT_QUEUE
            )
            self.stdout.write(self.style.SUCCESS(f"replayed {moved} events"))
            return
        self.stdout.write(self.style.SUCCESS(f"bridging events on {settings.TARA_EVENT_QUEUE}"))
        run_worker(
            broker_url=settings.TARA_EVENT_BROKER_URL,
            exchange_name=settings.TARA_EVENT_EXCHANGE,
            queue_name=settings.TARA_EVENT_QUEUE,
            processed_model=None,  # gateway has no DB; at-least-once push is fine
            consumer_name=settings.SERVICE_NAME,
        )
