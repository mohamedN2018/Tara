"""Event consumers for groups: moderation decisions on a group."""

from __future__ import annotations

from tara_events import on_event
from tara_events.envelope import EventEnvelope

from . import services


@on_event("moderation.actioned")
def on_moderation_actioned_group(event: EventEnvelope) -> None:
    """``remove`` suspends the group (hidden from everyone), ``approve`` (an
    overturned removal) restores it. Other target types are not ours."""
    p = event.payload
    if p.get("target_type") == "group" and p.get("target_id"):
        services.apply_moderation(str(p["target_id"]), p.get("action", ""))


@on_event("intel.config.published")
def on_intel_config_published(e: EventEnvelope) -> None:
    """Keep the newest published config of each surface (Tara Intelligence WP 5.5)."""
    from . import intel_config

    intel_config.apply_published(e.payload)
