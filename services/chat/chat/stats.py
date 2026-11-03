"""Counters for admin's platform statistics (``GET /internal/v1/stats/``, 8.11)."""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from .models import Conversation

ACTIVE_WINDOW = timedelta(days=7)


def count_active_conversations() -> int:
    """Conversations with a message in the last seven days."""
    return Conversation.objects.filter(last_message_at__gte=timezone.now() - ACTIVE_WINDOW).count()


COUNTERS = {"active_conversations": count_active_conversations}
