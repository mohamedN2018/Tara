"""The viewer's personal ranking inputs of one first page (R4: 04 WP 6.5, 8.3; 07 WP
6.5-B2, 6.8-B2, 7.5-B2).

``Personal`` is built once per first page from the one preference row the request
reads anyway and the first page's pipelined redis-hot read (``intel:prof``,
``feed:si``), so it adds **no query** on a warm profile cache (one on a miss).

Effects, every value from the config (decision 20):

- ``interest_rel`` (02 section 13) and ``session_rel`` (06 section 4.4): only under a
  version that carries ``interest_rank`` (the home@3 drafts); 0 otherwise, so home@1
  and the home@2* versions are untouched;
- formats (``preference_effects.format_more`` / ``format_less``) and a muted primary
  topic on a connected item (``feedback_effects.mute_primary_multiplier``, when its
  confidence is at least ``mute_primary_min_confidence``): score multipliers under
  every version, because they are the viewer's own explicit controls;
- ``discovery_level`` scales the recommended share (``preference_effects.discovery_scale``,
  capped at ``discovery_cap``; 02 section 10.1);
- ``personalization_off`` never reaches here: the view serves those viewers the
  chronological order with no inferred interests (02 section 13).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..config import SurfaceConfig
from ..interests import Profile


@dataclass
class Personal:
    profile: Profile | None = None
    si: dict | None = None  # decoded ``feed:si`` (``session_ctx.si_decode``)
    formats: dict = field(default_factory=dict)  # {post type: "more" | "less"}
    discovery_level: int = 2
    discovery_prefs: dict = field(default_factory=dict)
    intent: str | None = None
    # E10 content languages (the chosen ones, else the account language), None: none.
    languages: frozenset | None = None
    # ``intel:prof`` missed: the eligibility statement carries the interest rows and the
    # ranker builds (and caches) the profile from them (no query of its own).
    need_profile: bool = False
    account_id: str | None = None

    def viewer(self, viewer):
        """The eligibility viewer with the My Algorithm filters: E10 languages (lifted by
        ``other_languages``) and the discovery toggles (rule E12)."""
        from dataclasses import replace

        prefs = self.discovery_prefs or {}
        off = frozenset(k for k in ("trending", "new_creators") if prefs.get(k) is False)
        if (
            self.languages is None
            and not off
            and not prefs.get("other_languages")
            and not self.need_profile
        ):
            return viewer
        return replace(
            viewer,
            languages=self.languages if self.languages is not None else viewer.languages,
            other_languages=bool(prefs.get("other_languages")),
            discovery_off=off,
            want_profile=self.need_profile,
        )

    def share(self, base: float, cfg: SurfaceConfig) -> float:
        if base <= 0:
            return base
        block = cfg.section("preference_effects")
        scale = block["discovery_scale"].get(str(self.discovery_level), 1.0)
        value = base * scale
        # Level 3 is "more", capped (02 section 10.1: min(recommended x 1.33, 0.5)).
        return min(value, max(block["discovery_cap"], base)) if scale > 1 else value

    def format_multiplier(self, kind: str, cfg: SurfaceConfig) -> float:
        choice = self.formats.get(kind)
        if choice == "more":
            return cfg.get("preference_effects.format_more")
        if choice == "less":
            return cfg.get("preference_effects.format_less")
        return 1.0


DEFAULT = Personal()
