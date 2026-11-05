"""WP 4.4: the engagement-bait lexicon on a hand-labelled gold set.

``fixtures/bait_gold.jsonl``: 200 posts (100 ar, 100 en), each labelled by hand
``bait`` or not. Bait asks for an action in exchange for nothing but reach (share,
like, comment a word, tag, follow); asking for real feedback, a lost-dog share
request phrased plainly, or a post that merely uses the words is not bait. Some
bait is deliberately phrased in ways the lexicon does not know ("double tap",
"be honest... answer in the replies"), so recall is measured, not assumed.

Acceptance (04 WP 4.4): precision >= 0.8 and recall >= 0.5, overall; the measured
numbers are printed and recorded in docs/intelligence/results/phase-04.md.
"""

import json
from pathlib import Path

from intel import config, integrity

GOLD = Path(__file__).resolve().parent / "fixtures" / "bait_gold.jsonl"


def _rows():
    return [json.loads(line) for line in GOLD.read_text(encoding="utf-8").splitlines() if line]


def _measure(rows, threshold):
    tp = fp = fn = tn = 0
    for r in rows:
        predicted = integrity.bait_score(r["text"]) >= threshold
        if predicted and r["bait"]:
            tp += 1
        elif predicted:
            fp += 1
        elif r["bait"]:
            fn += 1
        else:
            tn += 1
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "precision": precision, "recall": recall}


def test_the_gold_set_has_the_planned_shape():
    rows = _rows()
    assert len(rows) == 200
    assert sum(r["lang"] == "ar" for r in rows) == 100
    assert sum(r["lang"] == "en" for r in rows) == 100
    assert sum(r["bait"] for r in rows) >= 40
    assert len({r["text"] for r in rows}) == 200


def test_bait_precision_and_recall_meet_the_bar():
    threshold = config.store.defaults("home", 2)["integrity"]["bait_min_score"]
    rows = _rows()
    overall = _measure(rows, threshold)
    per_lang = {
        lang: _measure([r for r in rows if r["lang"] == lang], threshold) for lang in ("ar", "en")
    }
    print("bait gold", overall, per_lang)
    assert overall["precision"] >= 0.8, overall
    assert overall["recall"] >= 0.5, overall
    for lang, m in per_lang.items():
        assert m["precision"] >= 0.8 and m["recall"] >= 0.5, (lang, m)


def test_scores_are_deterministic_and_in_range():
    for r in _rows():
        s = integrity.bait_score(r["text"])
        assert 0.0 <= s <= 1.0
        assert s == integrity.bait_score(r["text"])
    assert integrity.bait_score("") == 0.0
    assert integrity.bait_score(None) == 0.0
    assert integrity.bait_score("اعمل شير") == 0.5
    assert integrity.bait_score("اعمل شير ومنشن صاحبك") == 0.75
