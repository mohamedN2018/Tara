"""Intent v0, in shadow (06 section 4.5; 07 WP 6.8-B2). Hand-written rules, no model,
no search text (decision 7).

First match wins (overlay in brackets, shipped at weight 0):

- ``catch_up``: visit returning or lapsed and ``new_count >= min_to_show``
  (connected share +0.1);
- ``browse_video``: video and reel hold ``browse_video_min / browse_video_window`` of
  the session's decayed format mass (video run 3);
- ``topic_focus``: one topic holds ``topic_focus_share`` of the session's topic mass,
  with ``topic_focus_min_events`` events (max_topic_share 0.5);
- ``explore``: the session consumed ``explore_min_recommended`` recommended items
  (recommended share +0.1; not tracked before R6's Explore, so it never fires yet);
- ``none``: otherwise.

The intent is stored in ``intel_feed_session.intent`` (the visit row) and in
``feed:si`` (``intent``), never shown to staff (decision 17). Overlays live in the
``intent`` block and are multiplied by ``intent.overlay_weight``, which ships at 0: with
weight 0 ``overlay`` returns its inputs unchanged, so the order is identical to a
ranking without intent (``test_intent_rules.py`` golden). Promotion above 0 needs the
06 section 17 readout on real data.

``browse_video`` deviates from "3 of the last 5 consumptions": the vector keeps decayed
format mass, not a sequence, so the rule reads the share of that mass (the same 3/5).
"""

from __future__ import annotations

from . import session_ctx

NONE, CATCH_UP, BROWSE_VIDEO, TOPIC_FOCUS, EXPLORE = (
    "none",
    "catch_up",
    "browse_video",
    "topic_focus",
    "explore",
)
INTENTS = (CATCH_UP, BROWSE_VIDEO, TOPIC_FOCUS, EXPLORE, NONE)
_VIDEO_FORMATS = ("video", "reel")


def _session_rules(si: dict | None, block: dict) -> str:
    if not si:
        return NONE
    formats = si.get("format") or {}
    total = sum(max(v, 0.0) for v in formats.values())
    if total > 0:
        video = sum(max(formats.get(f, 0.0), 0.0) for f in _VIDEO_FORMATS)
        if video / total >= block["browse_video_min"] / block["browse_video_window"]:
            return BROWSE_VIDEO
    topics = si.get("topic") or {}
    mass = sum(max(v, 0.0) for v in topics.values())
    if mass > 0 and si.get("n", 0) >= block["topic_focus_min_events"]:
        if max(topics.values()) / mass >= block["topic_focus_share"]:
            return TOPIC_FOCUS
    return NONE


def classify(visit, si: dict | None, cfg) -> str:
    """The pre-rank intent (``catch_up`` is confirmed by ``finalize`` once the
    new-since count is known)."""
    block = cfg.section("intent")
    if visit is not None and visit.kind in (session_ctx.RETURNING, session_ctx.LAPSED):
        return CATCH_UP
    return _session_rules(si, block)


def finalize(pre: str | None, visit, new_count: int, cfg) -> str:
    if pre != CATCH_UP:
        return pre or NONE
    if new_count >= int(cfg.get("session.new_since.min_to_show")):
        return CATCH_UP
    return NONE


def overlay(intent: str | None, cfg, *, share: float, diversity: dict) -> tuple[float, dict]:
    """The intent's overlays at ``overlay_weight`` (0: unchanged inputs, exactly)."""
    block = cfg.section("intent")
    w = float(block["overlay_weight"])
    if not w or intent in (None, NONE):
        return share, diversity
    o = block["overlays"]
    div = dict(diversity)
    if intent == CATCH_UP:
        share = max(0.0, share - w * o["catch_up_connected"])
    elif intent == EXPLORE:
        share = min(1.0, share + w * o["explore_recommended"])
    elif intent == BROWSE_VIDEO:
        base = div["max_same_format_run"]
        div["max_same_format_run"] = max(1, round(base + w * (o["browse_video_run"] - base)))
    elif intent == TOPIC_FOCUS:
        base = div["max_topic_share"]
        div["max_topic_share"] = base + w * (o["topic_focus_share"] - base)
    return share, div


def store(viewer_id, intent: str | None, cfg) -> None:
    """``feed:si.intent`` (only into an existing vector: no hash for a viewer with no
    consumption yet)."""
    if not intent:
        return
    ttl = int(cfg.get("session_interest.ttl_s"))
    session_ctx.si_set_field(viewer_id, "intent", intent, ttl, create=False)
