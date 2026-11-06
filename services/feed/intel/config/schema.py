"""Typed schema of the ranking config, per surface (02 section 8.2; WP 4.1).

Every version is validated on write, and a version that fails can never be stored
or activated. The rules:

- unknown sections and unknown keys are rejected (a typo in a weight must fail, not
  be ignored: 09 R0 note on 02:310);
- every number has bounds; weights live in [-10, 10];
- half-lives are > 0;
- ratios that share a whole (``mix``, ``diversity.sim_weights``) sum to 1;
- ``schema_version`` names the schema the params were written for. A new block
  (``exposure``, ``session`` v2, ``delivery`` ...) arrives with a schema bump and its
  own spec, never by accepting unknown keys. Version 2 (07 WP 4b.6, 4b.11) adds
  ``mix``, ``continuation``, ``head`` and the ``popular`` / ``fresh`` pool keys; a
  version-1 params set that carries any of them is rejected. Version 3 (08 sections
  7.2 and 15.1, WP 4c.2-B3) adds ``delivery`` (home, reels, video); a stored
  version below 3 that carries it is rejected. Versions stored before it get the
  block from the package defaults (``store.merge``). Version 4 (06 sections 4.2,
  5.3, 5.4, 6.3 and 20; R3) adds ``exposure``, ``rotation``, ``revisit``, the visit
  keys of ``session`` and ``peek.max_count``; a stored version below 4 that carries
  any of them is rejected. Older versions get ``exposure`` and the ``session`` keys
  from the package defaults (ingest and visit classification read them under any
  active version), but never ``rotation`` / ``revisit``: the ranking effects of
  R3 apply only to a version that itself carries ``rotation``
  (``exposure_ranking``).

The specs are frozen dataclasses (``Num``, ``Int``, ``Bool``, ``Section``, ``Map``,
``ListOf``); ``validate(surface, params)`` returns the list of problems (empty when
valid) and ``check`` raises ``ConfigInvalid`` with all of them.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

SCHEMA_VERSION = 4
SURFACES = ("home", "reels", "video", "groups")
# The surfaces that carry a ``delivery`` block (WP 4c.2-B3).
DELIVERY_SURFACES = ("home", "reels", "video")
POST_TYPES = ("text", "image", "video", "link", "share", "poll", "reel")
SOURCES = ("connections", "follow_pull", "groups", "reels", "video")
# Candidate reasons a relationship prior can name (sources' ``reason`` codes).
REASONS = (
    "self",
    "friend",
    "follow",
    "page",
    "group",
    "group_notify",
    "capped",
    "new_follow",
    "public",
    "discovery",
    # Home pools (WP 4b.6): the bucket a recommended item came from.
    "rec_popular",
    "rec_fresh",
)


class ConfigInvalid(ValueError):
    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


@dataclass(frozen=True)
class Num:
    lo: float
    hi: float
    gt: bool = False  # strictly greater than ``lo`` (half-lives)

    def check(self, value, path: str, out: list[str]) -> None:
        if isinstance(value, bool) or not isinstance(value, int | float):
            out.append(f"{path}: a number is required")
            return
        if not math.isfinite(value):
            out.append(f"{path}: must be finite")
        elif (value <= self.lo if self.gt else value < self.lo) or value > self.hi:
            low = f"> {self.lo}" if self.gt else f">= {self.lo}"
            out.append(f"{path}: {value} out of range ({low}, <= {self.hi})")


@dataclass(frozen=True)
class Int:
    lo: int
    hi: int

    def check(self, value, path: str, out: list[str]) -> None:
        if isinstance(value, bool) or not isinstance(value, int):
            out.append(f"{path}: an integer is required")
        elif not self.lo <= value <= self.hi:
            out.append(f"{path}: {value} out of range [{self.lo}, {self.hi}]")


@dataclass(frozen=True)
class Bool:
    def check(self, value, path: str, out: list[str]) -> None:
        if not isinstance(value, bool):
            out.append(f"{path}: true or false is required")


@dataclass(frozen=True)
class Fixed:
    """A switch whose other value is not built yet: accepting it would be a no-op
    toggle in the admin (no fake features). ``until`` names the work that lifts it."""

    value: Any
    until: str

    def check(self, value, path: str, out: list[str]) -> None:
        if type(value) is not type(self.value) or value != self.value:
            out.append(f"{path}: only {self.value!r} is supported until {self.until}")


@dataclass(frozen=True)
class Str:
    choices: tuple[str, ...]

    def check(self, value, path: str, out: list[str]) -> None:
        if value not in self.choices:
            out.append(f"{path}: must be one of {', '.join(self.choices)}")


@dataclass(frozen=True)
class ListOf:
    item: Any
    max_len: int = 64
    min_len: int = 0
    unique: bool = False

    def check(self, value, path: str, out: list[str]) -> None:
        if not isinstance(value, list):
            out.append(f"{path}: a list is required")
            return
        if not self.min_len <= len(value) <= self.max_len:
            out.append(f"{path}: {len(value)} items (allowed {self.min_len} to {self.max_len})")
        for i, v in enumerate(value):
            self.item.check(v, f"{path}[{i}]", out)
        if self.unique and len({repr(v) for v in value}) != len(value):
            out.append(f"{path}: items must be distinct")


@dataclass(frozen=True)
class Pair:
    """A Beta prior ``[a, b]``: two positive pseudo-counts."""

    hi: float = 10_000.0

    def check(self, value, path: str, out: list[str]) -> None:
        if not (isinstance(value, list) and len(value) == 2):
            out.append(f"{path}: [a, b] is required")
            return
        for i, v in enumerate(value):
            Num(0.0, self.hi, gt=True).check(v, f"{path}[{i}]", out)


@dataclass(frozen=True)
class Map:
    """A dict whose keys come from ``keys`` (all optional unless ``required``)."""

    value: Any
    keys: tuple[str, ...] | None = None  # None: any key matching ``key_pattern``
    required: tuple[str, ...] = ()
    numeric_keys: bool = False

    def check(self, value, path: str, out: list[str]) -> None:
        if not isinstance(value, dict):
            out.append(f"{path}: an object is required")
            return
        for k in self.required:
            if k not in value:
                out.append(f"{path}.{k}: required")
        for k, v in value.items():
            if self.keys is not None and k not in self.keys:
                out.append(f"{path}.{k}: unknown key")
                continue
            if self.numeric_keys and not (isinstance(k, str) and k.isdigit()):
                out.append(f"{path}.{k}: a non-negative integer key is required")
                continue
            self.value.check(v, f"{path}.{k}", out)


@dataclass(frozen=True)
class Section:
    fields: dict[str, Any]
    optional: frozenset[str] = field(default_factory=frozenset)
    sums_to_one: tuple[str, ...] = ()

    def check(self, value, path: str, out: list[str]) -> None:
        if not isinstance(value, dict):
            out.append(f"{path}: an object is required")
            return
        for k, spec in self.fields.items():
            if k in value:
                spec.check(value[k], f"{path}.{k}" if path else k, out)
            elif k not in self.optional:
                out.append(f"{path}.{k}: required" if path else f"{k}: required")
        for k in value:
            if k not in self.fields:
                out.append(f"{path}.{k}: unknown key" if path else f"{k}: unknown section")
        if self.sums_to_one and all(
            isinstance(value.get(k), int | float) for k in self.sums_to_one
        ):
            total = sum(value[k] for k in self.sums_to_one)
            if abs(total - 1.0) > 1e-6:
                out.append(
                    f"{path}: {' + '.join(self.sums_to_one)} must sum to 1 (is {round(total, 6)})"
                )


# ---- building blocks -----------------------------------------------------------------

WEIGHT = Num(-10.0, 10.0)
COEF = Num(-10.0, 10.0)
UNIT = Num(0.0, 1.0)
HALF_LIFE_H = Num(0.0, 24 * 365, gt=True)
COUNT = Int(0, 100_000)

WINDOW = Map(Int(0, 5_000), keys=SOURCES)
RETRIEVAL = Section(
    {
        "new_follow_hours": Int(1, 24 * 30),
        "new_follow_days": Int(1, 365),
        "capped_days": Int(1, 365),
        "groups_days": Int(1, 365),
        "max_duration_ms": Int(1_000, 3_600_000),
        "require_portrait": Bool(),
    },
    optional=frozenset(
        {
            "new_follow_hours",
            "new_follow_days",
            "capped_days",
            "groups_days",
            "max_duration_ms",
            "require_portrait",
        }
    ),
)
# Home discovery pools (07 WP 4b.6). ``popular``: smoothed engagement per hour,
# (non-suspect reactions, comments, shares, weighted by ``engagement``, + prior) /
# (age_h + prior_hours), within ``window_d``; ``fresh``: the freshness decay times
# the integrity multipliers, within ``max_age_h``, kept at or above ``min_score``.
# ``cap`` members per (surface, lang, bucket) sorted set (<= 128 keeps Redis's
# compact listpack encoding); ``max_members`` of each are read per first page.
POOL_POPULAR = Section(
    {
        "window_d": Int(1, 90),
        "prior_engagement": Num(0.0, 1_000.0),
        "prior_hours": Num(0.0, 24 * 30, gt=True),
        "min_engagement": Int(0, 100_000),
    }
)
POOL_FRESH = Section({"max_age_h": Int(1, 24 * 30), "min_score": UNIT})
POOL_V2 = frozenset({"popular", "fresh", "rebuild_s", "cap", "max_members"})
POOLS = Section(
    {
        "window_days": Int(1, 180),
        "popular": POOL_POPULAR,
        "fresh": POOL_FRESH,
        "rebuild_s": Int(60, 24 * 3600),
        "cap": Int(1, 128),
        "max_members": Int(1, 128),
    },
    optional=POOL_V2,
)
# The recommended share of a Home session (decisions 4 and 23): ``recommended`` is
# the variant's arm (0.0 control, 0.15, 0.30); a viewer whose eligible connection
# candidates are below ``thin_inventory.below_candidates`` gets at least
# ``thin_inventory.share`` (the decision-23 cap of 10% in the control).
MIX = Section(
    {
        "recommended": UNIT,
        "thin_inventory": Section({"below_candidates": Int(0, 100_000), "share": UNIT}),
    }
)
# After the connection inventory ends, the session goes on into pool items (only
# when the variant recommends anything), at most ``max_items`` of them.
CONTINUATION = Section({"pools": Bool(), "max_items": Int(0, 2_000)})
# The ids of a viewer's last first page (``feed:head``, WP 4b.11): kept this long.
HEAD = Section({"ttl_s": Int(60, 30 * 24 * 3600)})
ELIGIBILITY = Section({"minor_allowed_topics": ListOf(Int(0, 32_767), max_len=500, unique=True)})
MEDIA_QUALITY = Section(
    {
        "rungs": Map(UNIT, numeric_keys=True),
        "no_poster_penalty": UNIT,
        "no_audio_penalty": UNIT,
    }
)

# Integrity (02 section 16). Multipliers are in (0, 1]: a demotion, never a removal.
MULTIPLIER = Num(0.0, 1.0, gt=True)
INTEGRITY = Section(
    {
        "pending_report_min_reporters": Int(1, 1_000),
        "exclude_pending_from_discovery": Bool(),
        "pending_report_multiplier": MULTIPLIER,
        "duplicate_multiplier": MULTIPLIER,
        "simhash_max_distance": Int(0, 16),
        "simhash_author_window_days": Int(1, 365),
        "simhash_public_window_hours": Int(1, 24 * 30),
        "simhash_min_tokens": Int(1, 100),
        "bait_multiplier": MULTIPLIER,
        "bait_min_score": UNIT,
        "spam_flag_multiplier": MULTIPLIER,
        "spam_flag_rate_threshold": UNIT,
        "spam_flag_min_flags": Int(1, 1_000),
        "max_posts_24h": Int(1, 10_000),
        # 0 turns the rule off (home@1: today's rates count every reaction).
        "suspect_account_age_hours": Int(0, 24 * 30),
        "suspect_burst_per_min": Int(0, 10_000),
    },
    optional=frozenset(
        {
            "pending_report_multiplier",
            "duplicate_multiplier",
            "simhash_max_distance",
            "simhash_author_window_days",
            "simhash_public_window_hours",
            "simhash_min_tokens",
            "bait_multiplier",
            "bait_min_score",
            "spam_flag_multiplier",
            "spam_flag_rate_threshold",
            "spam_flag_min_flags",
            "max_posts_24h",
            "suspect_account_age_hours",
            "suspect_burst_per_min",
        }
    ),
)

# The ranked value model (02 section 6.4). Every term has a weight; a weight of 0
# turns the term off (home@1 keeps only today's terms).
WEIGHTS = Section(
    {
        "s_meaningful": WEIGHT,
        "s_like": WEIGHT,
        "s_comment": WEIGHT,
        "s_share": WEIGHT,
        "s_save": WEIGHT,
        "s_complete": WEIGHT,
        "exp_watch": WEIGHT,
        "engagement": WEIGHT,
        "interest": WEIGHT,
        "explicit_multiplier": Num(0.0, 10.0),
        "relationship": WEIGHT,
        "freshness": WEIGHT,
        "quality": WEIGHT,
        "originality": WEIGHT,
        "negative": WEIGHT,
    }
)
# Today's raw engagement term: log1p(r·reactions + c·comments + s·shares) − f·log1p(flags).
ENGAGEMENT = Section(
    {
        "reaction": Num(0.0, 100.0),
        "comment": Num(0.0, 100.0),
        "share": Num(0.0, 100.0),
        "flag_weight": Num(0.0, 100.0),
    }
)
PRIOR_KINDS = ("like", "comment", "share", "save", "hide")
TYPE_PRIORS = Section(
    {
        **{k: Pair() for k in PRIOR_KINDS},
        "complete_by_bucket_s": Map(Pair(), numeric_keys=True),
    },
    optional=frozenset({"complete_by_bucket_s"}),
)
PREDICTOR = Section(
    {
        "name": Str(("rules",)),
        "c_aff": COEF,
        "c_int": COEF,
        "c_disc": COEF,
        "c_conv": COEF,
        "c_dis": COEF,
        "c_neg": COEF,
        "c_reason": Map(COEF, keys=REASONS),
        # ``default`` applies to a type without its own priors.
        "priors": Map(TYPE_PRIORS, keys=(*POST_TYPES, "default"), required=("default",)),
    }
)
RELATIONSHIP = Section(
    {
        "reason_prior": Map(Num(-10.0, 10.0), keys=REASONS),
        "favorite_bonus": WEIGHT,
        "affinity_weight": WEIGHT,
        "dislike_weight": WEIGHT,
        "dislike_cap": Int(0, 100),
        "shared_group_weight": WEIGHT,
        "conversation_weight": WEIGHT,
        "conversation_days": Int(1, 365),
    }
)
FRESHNESS = Section({"half_life_hours": HALF_LIFE_H})
ORIGINALITY = Section({"original": UNIT, "reshare": UNIT})
DIVERSITY = Section(
    {
        "enabled": Bool(),
        "max_per_author_page": Int(1, 100),
        "author_gap": Int(0, 100),
        "max_topic_share": UNIT,
        "max_same_format_run": Int(1, 100),
        "lambda": Num(0.0, 10.0),
        "window_factor": Int(1, 10),
        "page_size": Int(1, 100),
        "sim_weights": Section(
            {"author": UNIT, "topics": UNIT, "type": UNIT},
            sums_to_one=("author", "topics", "type"),
        ),
    }
)
RANKING = Section({"sources": ListOf(Str(SOURCES), min_len=1, max_len=len(SOURCES), unique=True)})
# The sources the Home ranker can retrieve (``intel.ranking.home.SOURCE_FUNCS``);
# ``discovery`` is the popular / fresh pools of WP 4b.6.
HOME_SOURCES = ("connections", "follow_pull", "groups", "discovery")
HOME_RANKING = Section(
    {"sources": ListOf(Str(HOME_SOURCES), min_len=1, max_len=len(HOME_SOURCES), unique=True)}
)
# The visit (06 sections 4.2 and 6.3, R3 WP 4b.4/4b.7/4b.8): classification
# thresholds, the "new since your last visit" block, the client refresh timers
# served in ``meta``, the per-account first-page / peek throttles and the retention
# of ``intel_feed_session``. ``ttl_s`` is the ranking session (WP 4.10).
SESSION_NEW_SINCE = Section(
    {
        "max_items": Int(0, 500),
        "lapsed_max_items": Int(0, 500),
        "min_to_show": Int(0, 100),
        "boost": Num(0.0, 10.0),
        "max_age_h": Int(1, 24 * 30),
    }
)
SESSION_RATE = Section({"first_page_per_min": Int(1, 10_000), "peek_per_min": Int(1, 10_000)})
SESSION_V4 = frozenset(
    {
        "refresh_max_s",
        "ongoing_idle_s",
        "returning_after_h",
        "lapsed_after_d",
        "new_since",
        "refresh_after_s",
        "auto_refetch_after_s",
        "rate",
        "feed_session_retention_d",
    }
)
SESSION = Section(
    {
        "ttl_s": Int(60, 24 * 3600),
        "refresh_max_s": Int(1, 3_600),
        "ongoing_idle_s": Int(60, 24 * 3600),
        "returning_after_h": Int(1, 24 * 30),
        "lapsed_after_d": Int(1, 365),
        "new_since": SESSION_NEW_SINCE,
        "refresh_after_s": Int(0, 24 * 3600),
        "auto_refetch_after_s": Int(0, 24 * 3600),
        "rate": SESSION_RATE,
        "feed_session_retention_d": Int(1, 400),
    },
    optional=SESSION_V4,
)
FEEDBACK = Section({"snooze_days": Int(1, 365)})
# Blocks owned by other WPs (4.6 modes, 4.7 peek, 4.8 why, 4.9 ads): validated here
# so the one schema covers the whole version.
MODES = Section({"recent_includes_groups": Fixed(False, "group rows join the recent mode")})
# ``max_count``: the peek ``new_count`` is capped there (``new_count_capped``; R3).
PEEK = Section(
    {"max_since_hours": Int(1, 24 * 30), "max_count": Int(1, 10_000)},
    optional=frozenset({"max_count"}),
)
# The exposure ledger and multiplier (06 sections 5.1-5.3, R3 WP 4b.3/4b.5).
# Ingest reads ``ledger`` and the dwell thresholds (``length_buckets``: ascending
# ``max_chars``, the consumed-dwell threshold is scaled by the first bucket whose
# ``max_chars`` holds the excerpt; the bucket index rides in the serve token); the
# ranker reads ``m0`` / ``half_life_h`` / ``in_visit_m0`` / ``max_exposures``, and
# only under a version that carries ``rotation`` (``exposure_ranking``).
EXPOSURE_STATES = ("displayed", "skipped", "viewed", "consumed")
EXPOSURE = Section(
    {
        "ledger": Section({"cap": Int(1, 1_000), "ttl_h": Int(1, 24 * 14)}),
        "skip_dwell_ms": Int(0, 600_000),
        "viewed_dwell_ms": Int(0, 600_000),
        "consumed_dwell_ms": Int(0, 600_000),
        "length_buckets": ListOf(
            Section({"max_chars": Int(0, 1_000_000), "scale": Num(0.0, 10.0, gt=True)}),
            min_len=1,
            max_len=16,
        ),
        "m0": Section(dict.fromkeys(EXPOSURE_STATES, UNIT)),
        "half_life_h": Section(dict.fromkeys(EXPOSURE_STATES, HALF_LIFE_H)),
        "in_visit_m0": Section(dict.fromkeys(EXPOSURE_STATES, UNIT)),
        "max_exposures": Int(1, 10),
    }
)
# Relevance-aware rotation (06 section 5.4): an item enters the first
# ``floor_slots`` only with score' >= ``floor`` x the ``floor_pct`` percentile.
ROTATION = Section({"floor": UNIT, "floor_pct": Int(0, 100), "floor_slots": Int(0, 100)})
# The conversation exception (06 section 5.3): >= ``new_comments`` distinct,
# non-suspect commenters since the viewer's last display lift m to ``min_m``.
REVISIT = Section({"new_comments": Int(1, 10_000), "min_m": UNIT})
ADS = Section(
    {
        "slots": ListOf(Int(0, 1_000), max_len=10, unique=True),
        "first_page_only": Fixed(True, "ads on later pages"),
    },
    optional=frozenset({"first_page_only"}),
)
WHY = Section({"max_factors": Int(1, 10), "interacted_min_interactions": Int(0, 1_000)})
# How the web loads and shows a surface (08 sections 7.2, 7.9, 7.12, 15.1; WP
# 4c.2-B3). Served as ``meta.delivery`` and by ``GET /feed/delivery/`` exactly as
# validated (it has no server-only key), so the web holds no delivery constants.
DELIVERY_VIDEO = Section(
    {
        "autoplay": Str(("muted_single", "click")),
        "min_visible": UNIT,
        "min_visible_ms": Int(0, 10_000),
        "pause_below": UNIT,
        "load_margin_vp": Num(0.0, 10.0),
        "unmount_beyond_vp": Num(0.0, 20.0),
        "respect_save_data": Bool(),
        "respect_reduced_motion": Bool(),
    }
)
# The impression rule (08 section 7.12): >= ``min_card_visible`` of the card OR >=
# ``min_viewport_cover`` of the viewport covered by it, for ``min_ms``; telemetry
# rows carry ``def_version`` (``impression_def``) so rates of two rules never mix.
DELIVERY_IMPRESSION = Section(
    {
        "min_card_visible": UNIT,
        "min_viewport_cover": UNIT,
        "min_ms": Int(100, 10_000),
        "def_version": Int(1, 2),
    }
)
DELIVERY = Section(
    {
        "first_page_size": Int(1, 100),
        "page_size": Int(1, 100),
        "prefetch_remaining_items": Int(0, 50),
        "prefetch_root_margin_vp": Num(0.0, 10.0),
        "media_warm_items": Int(0, 50),
        "media_resolve_window_ms": Int(0, 200),
        "virtualize_after_items": Int(0, 1_000),
        "keep_mounted_vp": Num(1.0, 20.0),
        "next_page_retries": Int(0, 10),
        "next_page_backoff_ms": Int(0, 60_000),
        "defer_rails_until_first_post": Bool(),
        # The rail fallback of 08 section 7.4 (1.5 s), so it is not a web literal.
        "defer_rails_max_ms": Int(0, 10_000),
        # Reload position (08 section 7.6): a reload within this many minutes returns
        # to the card on screen, paging forward at most ``reload_max_pages`` pages.
        "reload_window_min": Int(0, 1_440),
        "reload_max_pages": Int(0, 10),
        "video": DELIVERY_VIDEO,
        "impression": DELIVERY_IMPRESSION,
    }
)

_HEADER = {
    "schema_version": Int(1, SCHEMA_VERSION),
    "surface": Str(SURFACES),
    "version": Int(1, 10**6),
}

# The ranking blocks every surface may carry; home requires them (WP 4.3), the other
# surfaces get their rankers in phase 5 and keep them optional until then.
_RANKING_BLOCKS = {
    "ranking": RANKING,
    "weights": WEIGHTS,
    "engagement": ENGAGEMENT,
    "predictor": PREDICTOR,
    "relationship": RELATIONSHIP,
    "freshness": FRESHNESS,
    "originality": ORIGINALITY,
    "diversity": DIVERSITY,
    "session": SESSION,
}
_COMMON = {
    "window": WINDOW,
    "retrieval": RETRIEVAL,
    "pools": POOLS,
    "integrity": INTEGRITY,
    "eligibility": ELIGIBILITY,
    **_RANKING_BLOCKS,
}

SCHEMAS: dict[str, Section] = {
    "home": Section(
        {
            **_HEADER,
            **_COMMON,
            "ranking": HOME_RANKING,
            "media_quality": MEDIA_QUALITY,
            "feedback": FEEDBACK,
            "modes": MODES,
            "peek": PEEK,
            "ads": ADS,
            "why": WHY,
            "mix": MIX,
            "continuation": CONTINUATION,
            "head": HEAD,
            "delivery": DELIVERY,
            "exposure": EXPOSURE,
            "rotation": ROTATION,
            "revisit": REVISIT,
        },
        optional=frozenset(
            {
                "retrieval",
                "pools",
                "modes",
                "peek",
                "ads",
                "why",
                "mix",
                "continuation",
                "head",
                "delivery",
                "exposure",
                "rotation",
                "revisit",
            }
        ),
    ),
    **{
        s: Section(
            {
                **_HEADER,
                **_COMMON,
                "media_quality": MEDIA_QUALITY,
                **({"delivery": DELIVERY} if s in DELIVERY_SURFACES else {}),
            },
            optional=frozenset(
                {"retrieval", "pools", "media_quality", "delivery", *_RANKING_BLOCKS}
            ),
        )
        for s in ("reels", "video", "groups")
    },
}


def validate(surface: str, params: Any) -> list[str]:
    """Every problem with ``params`` as a version of ``surface`` (empty when valid)."""
    if surface not in SCHEMAS:
        return [f"unknown surface {surface!r}"]
    out: list[str] = []
    SCHEMAS[surface].check(params, "", out)
    if isinstance(params, dict) and params.get("surface") not in (None, surface):
        out.append(f"surface: {params.get('surface')!r} is not {surface!r}")
    if isinstance(params, dict):
        out += _version_rules(params)
    return out


# Blocks and pool keys that schema version 2 introduced (WP 4b.6, 4b.11).
V2_SECTIONS = ("mix", "continuation", "head")
# Blocks that schema version 3 introduced (WP 4c.2-B3).
V3_SECTIONS = ("delivery",)
# Blocks and keys that schema version 4 introduced (R3).
V4_SECTIONS = ("exposure", "rotation", "revisit")
PEEK_V4 = frozenset({"max_count"})


def exposure_ranking(params: dict) -> bool:
    """Whether the R3 ranking effects (exposure multiplier, rotation floor,
    carry-over, ``rec_new_activity``, the new-since boost) apply. True only for a
    version that itself carries ``rotation``: ``store.merge`` gives older versions
    ``exposure`` and the visit keys from the package defaults, never ``rotation``."""
    return isinstance(params.get("rotation"), dict) and isinstance(params.get("exposure"), dict)


def _version_rules(params: dict) -> list[str]:
    out = []
    version = params.get("schema_version")
    if isinstance(version, int) and not isinstance(version, bool) and version < 4:
        for name in V4_SECTIONS:
            if name in params:
                out.append(f"{name}: needs schema_version 4")
        for block, keys in (("session", SESSION_V4), ("peek", PEEK_V4)):
            value = params.get(block)
            if isinstance(value, dict):
                for key in sorted(keys & set(value)):
                    out.append(f"{block}.{key}: needs schema_version 4")
    if "rotation" in params or "revisit" in params:
        # The ranking effects read the multiplier and the exception together.
        for name in V4_SECTIONS:
            if name not in params:
                out.append(f"{name}: required with rotation / revisit")
    buckets = (
        params.get("exposure", {}).get("length_buckets")
        if isinstance(params.get("exposure"), dict)
        else None
    )
    if isinstance(buckets, list) and all(
        isinstance(b, dict) and isinstance(b.get("max_chars"), int) for b in buckets
    ):
        edges = [b["max_chars"] for b in buckets]
        if edges != sorted(set(edges)):
            out.append("exposure.length_buckets: max_chars must be strictly ascending")
    if isinstance(version, int) and not isinstance(version, bool) and version < 3:
        for name in V3_SECTIONS:
            if name in params:
                out.append(f"{name}: needs schema_version 3")
    if isinstance(version, int) and not isinstance(version, bool) and version < 2:
        for name in V2_SECTIONS:
            if name in params:
                out.append(f"{name}: needs schema_version 2")
        pools = params.get("pools")
        if isinstance(pools, dict):
            for key in sorted(POOL_V2 & set(pools)):
                out.append(f"pools.{key}: needs schema_version 2")
    ranking = params.get("ranking")
    sources = ranking.get("sources") if isinstance(ranking, dict) else None
    if isinstance(sources, list) and "discovery" in sources:
        # The pools' retriever reads these: a version naming the source must carry them.
        pools = params.get("pools") if isinstance(params.get("pools"), dict) else {}
        for key in ("popular", "fresh", "max_members"):
            if key not in pools:
                out.append(f"pools.{key}: required with the discovery source")
        for name in ("mix", "continuation"):
            if name not in params:
                out.append(f"{name}: required with the discovery source")
    return out


def check(surface: str, params: Any) -> None:
    problems = validate(surface, params)
    if problems:
        raise ConfigInvalid(problems)
