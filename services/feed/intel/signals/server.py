"""Server-sourced signal rows (02 section 12.1): post-menu actions the feed itself
performs. Written in the caller's transaction, so the action and its row commit
together (WP 2.5)."""

from __future__ import annotations

from django.utils import timezone

from .. import origin
from ..models import SignalSource
from . import store


def record(account_id, event_type: str, item_type: str, item_id, author_id=None) -> bool:
    """One ``source=server`` row. False when the account's rows are refused here."""
    resolution = origin.resolve(account_id)
    if resolution.refused:
        return False
    now = timezone.now()
    store.insert_row(
        store.SignalRow(
            account_id=account_id,
            event_type=event_type,
            item_type=item_type,
            item_id=item_id,
            author_id=author_id,
            source=SignalSource.SERVER,
            data_origin=resolution.origin,
            occurred_at=now,
            received_at=now,
        )
    )
    return True
