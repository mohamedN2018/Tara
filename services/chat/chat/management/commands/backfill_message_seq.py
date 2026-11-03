"""Number messages of conversations created before per-conversation sequences.

Safe while sends continue: each conversation is numbered under the same row
lock that sends take (doc 05 §7.3). Run once after the migration; re-running
skips conversations that are already numbered.
"""

from django.core.management.base import BaseCommand

from chat import services
from chat.models import Conversation


class Command(BaseCommand):
    help = "Assign Message.seq and member read pointers for not-yet-numbered conversations."

    def handle(self, *args, **options) -> None:
        done = 0
        ids = Conversation.objects.filter(seq_ready=False).values_list("id", flat=True)
        for conversation_id in ids.iterator():
            if services.backfill_conversation_seq(str(conversation_id)):
                done += 1
        self.stdout.write(self.style.SUCCESS(f"numbered {done} conversations"))
