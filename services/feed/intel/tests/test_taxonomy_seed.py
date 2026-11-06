"""WP 6.1: the taxonomy seed.

- about 40 topics with ar and en labels; politics, religion and Quran sensitive;
- aliases for the curated hashtags, the page categories, the 18 group categories and
  the 8 market categories, and the keyword lexicons;
- every hashtag with >= 5 live uses, **queried at run time**, is mapped or explicitly
  left unmapped (with a reason); anything else is reported ``uncurated``;
- the seed is additive and idempotent.
"""

import pytest
from django.core.management import call_command

from intel.management.commands import intel_seed_topics
from intel.models import Topic, TopicAlias
from intel.topics import taxonomy

from . import world as w

pytestmark = pytest.mark.django_db

# The dev hashtags with >= 5 uses on 2026-11-06 (06 baseline: 25.5% of live posts
# carry a hashtag). The curated lists must cover each one.
DEV_HASHTAGS = (
    "مشاريع تصميم برمجة تكنولوجيا مصر tara قرآن نقاش تلاوة تريند رأيكم سياسة ذكريات صورة "
    "photography لقطة حكايات تاريخ موبايلات جيم أخبار رياضة منتجات تدبر عروض تلاوة_خاشعة ai "
    "ذكاء_اصطناعي منوعات uav علوم fyp شاومي معلومة سامسونج optical قرآن_كريم fpv"
).split()


def test_topics_and_sensitive_flags():
    intel_seed_topics.seed()
    topics = {t.slug: t for t in Topic.objects.all()}
    assert 38 <= len(topics) <= 45
    assert all(t.label_ar and t.label_en for t in topics.values())
    assert {s for s, t in topics.items() if t.sensitive} == {"politics", "religion", "quran"}
    assert topics["quran"].parent_id == topics["religion"].id


def test_aliases_cover_every_category_source():
    intel_seed_topics.seed()
    kinds = {
        k: set(TopicAlias.objects.filter(kind=k).values_list("value_norm", flat=True))
        for k in ("group_category", "market_category", "page_category", "keyword", "hashtag")
    }
    mapped_groups = {k for k, v in taxonomy.GROUP_CATEGORIES.items() if v}
    assert len(taxonomy.GROUP_CATEGORIES) == 18 and kinds["group_category"] == mapped_groups
    assert len(taxonomy.MARKET_CATEGORIES) == 8
    assert kinds["market_category"] == {k for k, v in taxonomy.MARKET_CATEGORIES.items() if v}
    assert taxonomy.norm("مطاعم") in kinds["page_category"]
    assert taxonomy.norm("Bookshop") in kinds["page_category"]
    assert len(kinds["keyword"]) > 300


def test_every_dev_hashtag_is_mapped_or_explicitly_unmapped():
    curated = {taxonomy.norm(t) for t in taxonomy.HASHTAGS} | {
        taxonomy.norm(t) for t in taxonomy.UNMAPPED
    }
    missing = [t for t in DEV_HASHTAGS if taxonomy.norm(t) not in curated]
    assert missing == []


def test_the_run_time_report_reads_the_live_hashtags():
    author = w.uid()
    for _ in range(5):
        p = w.post(author)
        from intel.models import ContentRef

        ContentRef.objects.filter(post_id=p).update(hashtags=["برمجة", "tara", "zzznew"])
    p = w.post(author)
    ContentRef.objects.filter(post_id=p).update(hashtags=["rare"])
    intel_seed_topics.seed()
    report = intel_seed_topics.hashtag_report(5)
    assert report["mapped"]["برمجة"]["topic"] == "programming"
    assert "tara" in report["unmapped"]
    assert [x["tag"] for x in report["uncurated"]] == ["zzznew"]  # reported, never auto-created
    assert "rare" not in str(report)  # below 5 uses


def test_seed_is_idempotent_and_additive():
    first = intel_seed_topics.seed()
    assert first["topics"] > 0
    t = Topic.objects.get(slug="food")
    Topic.objects.filter(pk=t.pk).update(label_en="Food (edited by staff)")
    second = intel_seed_topics.seed()
    assert second == {"topics": 0, "aliases": 0}
    assert Topic.objects.get(slug="food").label_en == "Food (edited by staff)"
    call_command("intel_seed_topics", "--json")
