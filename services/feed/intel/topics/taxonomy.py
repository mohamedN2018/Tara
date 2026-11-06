"""The curated topic taxonomy (04 WP 6.1, 02 section 14, 03 section 2.3).

About 40 bilingual topics, seeded by ``manage.py intel_seed_topics`` from the 18
group categories (``profile/groups/models.py``), the 8 marketplace roots, the page
categories in use and the dev hashtags. Topics are never auto-created: a hashtag
that is not curated here is reported as unmapped, with the reason it stays so.

``sensitive`` (decision 12): politics, religion and Quran. No inferred interest row
for them without the viewer's opt-in; "a topic" only in reasons; never for ads.
"""

from __future__ import annotations

from tara_common.text import normalize_ar, normalize_key

# slug, label_ar, label_en, parent slug, sensitive, allow_minors
TOPICS: tuple[tuple[str, str, str, str | None, bool, bool], ...] = (
    ("technology", "تكنولوجيا", "Technology", None, False, True),
    ("programming", "برمجة", "Programming", "technology", False, True),
    ("ai", "ذكاء اصطناعي", "Artificial intelligence", "technology", False, True),
    ("mobiles", "موبايلات", "Mobile phones", "technology", False, True),
    ("electronics", "إلكترونيات", "Electronics", "technology", False, True),
    ("gaming", "ألعاب", "Gaming", None, False, True),
    ("design", "تصميم", "Design", None, False, True),
    ("photography", "تصوير", "Photography", None, False, True),
    ("business", "أعمال", "Business", None, False, True),
    ("entrepreneurship", "مشاريع وريادة أعمال", "Entrepreneurship", "business", False, True),
    ("marketing", "تسويق", "Marketing", "business", False, True),
    ("finance", "فلوس واستثمار", "Money and investing", "business", False, True),
    ("education", "تعليم", "Education", None, False, True),
    ("science", "علوم", "Science", None, False, True),
    ("history", "تاريخ", "History", None, False, True),
    ("books", "كتب وقراءة", "Books and reading", None, False, True),
    ("food", "أكل", "Food", None, False, True),
    ("cooking", "طبخ ووصفات", "Cooking and recipes", "food", False, True),
    ("travel", "سفر", "Travel", None, False, True),
    ("sports", "رياضة", "Sports", None, False, True),
    ("football", "كورة", "Football", "sports", False, True),
    ("health", "صحة", "Health", None, False, True),
    ("fitness", "لياقة", "Fitness", "health", False, True),
    ("parenting", "تربية الأطفال", "Parenting", None, False, True),
    ("arts", "فنون", "Arts", None, False, True),
    ("music", "موسيقى", "Music", "arts", False, True),
    ("movies", "أفلام ومسلسلات", "Movies and TV", "entertainment", False, True),
    ("entertainment", "ترفيه", "Entertainment", None, False, True),
    ("fashion", "موضة", "Fashion", None, False, True),
    ("beauty", "جمال وعناية", "Beauty and care", None, False, True),
    ("cars", "عربيات", "Cars", None, False, True),
    ("property", "عقارات", "Property", None, False, True),
    ("home_garden", "البيت والجنينة", "Home and garden", None, False, True),
    ("services", "خدمات", "Services", None, False, True),
    ("local", "مجتمع محلي", "Local community", None, False, True),
    ("shopping", "بيع وشرا", "Buy and sell", None, False, True),
    ("hobbies", "هوايات", "Hobbies", None, False, True),
    ("news", "أخبار", "News", None, False, True),
    ("stories", "حكايات وذكريات", "Stories and memories", None, False, True),
    ("politics", "سياسة", "Politics", None, True, False),
    ("religion", "دين", "Religion", None, True, True),
    ("quran", "قرآن", "Quran", "religion", True, True),
)

# The 18 group categories (1:1 where a topic exists). ``general`` and ``other``
# describe no topic: a post in such a group inherits nothing (02 section 14).
GROUP_CATEGORIES = {
    "general": None,
    "education": "education",
    "business": "business",
    "technology": "technology",
    "sports": "sports",
    "gaming": "gaming",
    "arts": "arts",
    "entertainment": "entertainment",
    "health": "health",
    "travel": "travel",
    "food": "food",
    "parenting": "parenting",
    "religion": "religion",
    "local": "local",
    "buy_sell": "shopping",
    "hobbies": "hobbies",
    "science": "science",
    "other": None,
}
# The 8 marketplace roots (``marketplace_category`` with no parent).
MARKET_CATEGORIES = {
    "electronics": "electronics",
    "fashion": "fashion",
    "furniture": "home_garden",
    "home-garden": "home_garden",
    "property": "property",
    "services": "services",
    "vehicles": "cars",
    "other": None,
}
# Free-text ``Page.category`` values seen on dev, normalized at seed time.
PAGE_CATEGORIES = {
    "Bookshop": "books",
    "Bookstore": "books",
    "Books": "books",
    "مكتبة": "books",
    "مطاعم": "food",
    "مطعم": "food",
    "Restaurant": "food",
    "Food": "food",
    "Bakery": "food",
    "مخبز": "food",
    "Science": "science",
    "Science & Technology": "science",
    "News & Media": "news",
    "Community": "local",
    "Electronics": "electronics",
    "Sports": "sports",
    "Clothing": "fashion",
    "Shopping & Retail": "shopping",
    "Entertainment": "entertainment",
    "ناشط سياسي": "politics",
    "Religious Organization": "religion",
    "Software": "programming",
    "Education": "education",
}
# Curated hashtags (the dev hashtags with >= 5 uses on 2026-11-06, plus common
# English and Egyptian variants). A hashtag outside both lists is reported unmapped.
HASHTAGS = {
    "ريادة_اعمال": "entrepreneurship",
    "startup": "entrepreneurship",
    "تصميم": "design",
    "design": "design",
    "برمجة": "programming",
    "programming": "programming",
    "coding": "programming",
    "تكنولوجيا": "technology",
    "تقنية": "technology",
    "tech": "technology",
    "technology": "technology",
    "uav": "technology",
    "fpv": "technology",
    "درون": "technology",
    "ai": "ai",
    "ذكاء_اصطناعي": "ai",
    "موبايلات": "mobiles",
    "شاومي": "mobiles",
    "سامسونج": "mobiles",
    "ايفون": "mobiles",
    "قرآن": "quran",
    "قرآن_كريم": "quran",
    "تلاوة": "quran",
    "تلاوة_خاشعة": "quran",
    "تدبر": "quran",
    "quran": "quran",
    "سياسة": "politics",
    "politics": "politics",
    "ذكريات": "stories",
    "حكايات": "stories",
    "صورة": "photography",
    "لقطة": "photography",
    "photography": "photography",
    "تصوير": "photography",
    "تاريخ": "history",
    "history": "history",
    "gaming": "gaming",
    "العاب": "gaming",
    "أخبار": "news",
    "news": "news",
    "رياضة": "sports",
    "sports": "sports",
    "كورة": "football",
    "football": "football",
    "منتجات": "shopping",
    "عروض": "shopping",
    "علوم": "science",
    "science": "science",
    "طبخ": "cooking",
    "وصفات": "cooking",
    "cooking": "cooking",
    "food": "food",
    "اكل": "food",
    "سفر": "travel",
    "travel": "travel",
    "كتب": "books",
    "books": "books",
    "موسيقى": "music",
    "music": "music",
    "افلام": "movies",
    "movies": "movies",
    "موضة": "fashion",
    "fashion": "fashion",
    "صحة": "health",
    "health": "health",
    "تعليم": "education",
    "education": "education",
    "تسويق": "marketing",
    "marketing": "marketing",
}
# Dev hashtags with >= 5 uses that name no topic, and why (WP 6.1 acceptance:
# mapped or explicitly left unmapped).
UNMAPPED = {
    "مصر": "a place, not a topic (location is R5's geo work)",
    "tara": "the app's own name",
    "نقاش": "an engagement prompt (discussion), not a topic",
    "رأيكم": "an engagement prompt (your opinion?), not a topic",
    "تريند": "the word trend, not a topic",
    "منوعات": "miscellaneous by definition",
    "fyp": "an algorithm-bait tag (for you page), not a topic",
    "معلومة": "a fact of any subject",
    "optical": "ambiguous on dev (optics, lenses, illusions)",
    "مشاريع": "projects of any kind; on dev it tags design portfolios, not entrepreneurship",
    "جيم": "ambiguous in Egyptian Arabic (a gym or a game)",
}


def norm(value: str | None) -> str:
    """The alias key form: ``normalize_key(normalize_ar(value))`` without a leading #."""
    return normalize_key(normalize_ar(value or "")).lstrip("#").strip()
