"""The predictions interface (02 section 15)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Prediction:
    # Named score_* until the surface passes the calibration check (WP 12.6);
    # renamed p_* for that surface only afterwards.
    score_meaningful: float
    score_like: float
    score_comment: float
    score_share: float
    score_save: float
    score_complete: float | None
    score_rewatch: float | None  # reels and video, once rewatches are aggregated
    exp_watch_s: float | None
    score_negative: float
    interest_rel: float
    predictor: str  # "rules@1", later "sklearn:logreg@2026-12-01"
    calibrated: bool  # False for rules@1 until WP 12.6 passes

    def logged(self) -> list[float]:
        """The scores a serve token carries (``intel_signal_event.pred``), in [0, 1]."""
        return [
            self.score_meaningful,
            self.score_like,
            self.score_comment,
            self.score_share,
            self.score_save,
            self.score_negative,
        ]


class Predictor(Protocol):
    name: str

    def predict(self, viewer_id, feats: Sequence, cfg) -> list[Prediction]: ...
