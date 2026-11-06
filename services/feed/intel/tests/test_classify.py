"""WP 6.2: the rule-based classifier (02 section 14). Each rule, Arabic normalization,
inherited topics, the at-most-3 cap, the event hook, and the precision on the gold
set (``fixtures/topic_gold.jsonl``)."""

import json
from pathlib import Path

import pytest

from intel.models import ContentRef, ContentTopic, GroupRef, PageRef
from intel.topics import classify, taxonomy

from . import r4
from . import world as w
from .helpers import deliver, event

pytestmark = pytest.mark.django_db
GOLD = Path(__file__).parent / "fixtures" / "topic_gold.jsonl"


def _slugs(found, ids):
    by_id = {v: k for k, v in ids.items()}
    return [by_id[f.topic_id] for f in found]


def test_hashtag_rule_and_normalization():
    ids = r4.seed()
    found = classify.classify(excerpt="", hashtags=["#برمجه", "سياسة"])
    assert set(_slugs(found, ids)) == {"programming", "politics"}
    assert all(f.confidence == 0.9 and f.source == "hashtag" for f in found)


def test_lexicon_needs_two_hits_or_one_strong():
    ids = r4.seed()
    # One weak hit (كود) is not enough; two distinct weak hits are.
    assert _slugs(classify.classify(excerpt="شوفت الكود ده"), ids) == []
    two = classify.classify(excerpt="الكود شغال على السيرفر")
    assert _slugs(two, ids) == ["programming"] and two[0].confidence == 0.5
    strong = classify.classify(excerpt="بتعلم بايثون")
    assert _slugs(strong, ids) == ["programming"] and strong[0].confidence == 0.4
    # Clitics and spelling variants meet: والبرمجة / البرمجه.
    assert _slugs(classify.classify(excerpt="والبرمجة حلوة"), ids) == ["programming"]
    # Two-word terms match adjacent tokens.
    assert "ai" in _slugs(classify.classify(excerpt="عن الذكاء الاصطناعي"), ids)


def test_page_group_and_inherited_rules_and_the_cap():
    ids = r4.seed()
    found = classify.classify(
        excerpt="", page_category=taxonomy.norm("مطاعم"), group_category="sports"
    )
    assert set(_slugs(found, ids)) == {"food", "sports"}
    assert classify.classify(excerpt="", group_category="general") == []
    inherited = classify.classify(excerpt="", inherited=[(ids["history"], 0.9)])
    assert _slugs(inherited, ids) == ["history"] and inherited[0].confidence == pytest.approx(0.72)
    many = classify.classify(excerpt="", hashtags=["برمجة", "تصميم", "تاريخ", "رياضة", "سفر"])
    assert len(many) == 3


def test_classify_post_on_the_bus_and_an_edit_without_text():
    ids = r4.seed()
    author = w.uid()
    post_id = w.uid()
    payload = {
        "post_id": post_id,
        "author_id": author,
        "author_type": "user",
        "type": "text",
        "audience": "public",
        "hashtags": ["تاريخ"],
        "excerpt": "وصفة كشري مصري بطريقة عمل سهلة",
        "created_at": w.NOW.isoformat(),
    }
    deliver(event("post.created", payload, at=w.NOW), only_intel=True)
    stored = dict(ContentTopic.objects.filter(post_id=post_id).values_list("topic_id", "source"))
    assert stored == {ids["history"]: "hashtag", ids["cooking"]: "lexicon", ids["food"]: "lexicon"}
    # An edit that carries hashtags but no excerpt keeps the lexicon topics.
    deliver(
        event("post.updated", {"post_id": post_id, "hashtags": ["سفر"]}, at=w.NOW),
        only_intel=True,
    )
    stored = set(ContentTopic.objects.filter(post_id=post_id).values_list("topic_id", flat=True))
    assert stored == {ids["travel"], ids["cooking"], ids["food"]}
    assert ContentRef.objects.filter(post_id=post_id).exists()


def test_page_and_group_category_sources_from_the_read_models():
    ids = r4.seed()
    owner = w.uid()
    page = w.page(owner)
    PageRef.objects.filter(page_id=page).update(category_norm="مطاعم")
    p1 = w.post(page, author_type="page")
    assert [f.topic_id for f in classify.classify_post(p1, "")] == [ids["food"]]
    group = w.group()
    GroupRef.objects.filter(group_id=group).update(category="technology")
    p2 = w.post(w.uid(), group=group, audience="group")
    assert [f.topic_id for f in classify.classify_post(p2, "")] == [ids["technology"]]
    assert ContentTopic.objects.get(post_id=p2).source == "group"


def test_page_category_reaches_the_read_model():
    from intel import readmodels

    page_id = w.uid()
    readmodels.set_page(
        page_id, {"owner": w.uid(), "status": "published", "category": "Bakery"}, w.NOW
    )
    assert PageRef.objects.get(page_id=page_id).category_norm == "bakery"
    readmodels.set_page(page_id, {"status": "published"}, w.NOW)  # no category: kept
    assert PageRef.objects.get(page_id=page_id).category_norm == "bakery"


def test_gold_set_precision():
    """Precision of the rules on the hand-labelled gold set (target >= 0.8): every
    topic the classifier returns must be one of the post's gold topics."""
    if not GOLD.exists():
        pytest.skip("gold set not present")
    ids = r4.seed()
    by_id = {v: k for k, v in ids.items()}
    returned = correct = covered = 0
    rows = [json.loads(line) for line in GOLD.read_text(encoding="utf-8").splitlines() if line]
    assert len(rows) >= 200
    for row in rows:
        found = classify.classify(excerpt=row["excerpt"], hashtags=row.get("hashtags") or [])
        slugs = {by_id[f.topic_id] for f in found}
        if slugs:
            covered += 1
        returned += len(slugs)
        correct += len(slugs & set(row["topics"]))
    precision = correct / returned if returned else 0.0
    assert precision >= 0.8, (precision, correct, returned, covered)
