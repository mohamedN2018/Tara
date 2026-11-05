"""Stage 3: predictions (02 section 15). Rules now (``rules.RulePredictor``); a
calibrated ML predictor can replace it behind the same ``Predictor`` interface
(phase 11). Outputs are named ``score_*``: heuristics, not probabilities, until the
calibration check of WP 12.6 passes for a surface."""

from .base import Prediction, Predictor
from .rules import RulePredictor

__all__ = ["Prediction", "Predictor", "RulePredictor", "for_config"]


def for_config(cfg) -> Predictor:
    name = cfg.get("predictor.name")
    if name == "rules":
        return RulePredictor()
    raise KeyError(f"{cfg.version}: unknown predictor {name!r}")
