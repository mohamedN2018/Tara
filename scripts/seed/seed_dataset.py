#!/usr/bin/env python3
# ruff: noqa: S311 - seeded pseudo-randomness for test data, not security
"""Seed a local Tara stack with a large, realistic test dataset.

Everything is created through the real public API at ``--api`` (the same calls
the web app makes): sign-up with the full registration fields, e-mail
verification read back from Mailpit, profiles, friendships, follows, pages and
their teams, groups, photo/album/text posts, video posts and reels, marketplace
listings, stories, and then reactions, comments, replies, shares, saves, hides
and reel views with a popular-versus-long-tail skew, so ranking work has signal.
Nothing is written to any database directly.

    python scripts/seed/seed_dataset.py \
        --source "F:/.../Captures/داتا" --source "D:/2_Mieda/Instagram=quran" --dry-run
    python -u scripts/seed/seed_dataset.py --source ... --source ... > seed.log 2>&1

Re-runs are idempotent: ``.seed-state/manifest.json`` (gitignored) records what
was created, so a second run skips it and an interrupted run resumes. Media is
never copied into the repository: images are re-encoded (EXIF stripped) into
``.seed-state/cache`` and uploaded; videos are uploaded as they are.

Standard library only; Pillow (images, AVIF) and openpyxl (xlsx price menus)
are used when installed, and ffprobe (local) when on PATH, for the dry-run plan.
Whether a video becomes a reel is decided by the server after transcoding
(``POST /reels/eligibility/``), never by the file name or the local probe.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import os
import random
import re
import shutil
import subprocess
import sys
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

try:  # optional: images (re-encode, strip EXIF, AVIF), generated avatars
    from PIL import Image, ImageOps

    HAVE_PIL = True
except ImportError:  # pragma: no cover - depends on the machine
    HAVE_PIL = False

try:  # optional: xlsx price menus
    import openpyxl

    HAVE_XLSX = True
except ImportError:  # pragma: no cover
    HAVE_XLSX = False

REPO = Path(__file__).resolve().parents[2]
DEFAULT_API = os.getenv("TARA_API", "http://127.0.0.1:8080/api/v1")
DEFAULT_MAILPIT = os.getenv("TARA_MAILPIT", "http://127.0.0.1:8026/api/v1")
DEFAULT_PASSWORD = os.getenv("TARA_SEED_PASSWORD", "Seed-Tara-2026!")
LEGAL_VERSION = os.getenv("TARA_LEGAL_VERSION", "2026-11-04-draft")
SEED = 2026
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "0.0.0.0", "host.docker.internal"}  # noqa: S104

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif"}
VIDEO_EXT = {".mp4", ".mov", ".webm"}
VIDEO_MIME = {".mp4": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm"}
MAX_VIDEO_BYTES = 200 * 1024 * 1024  # media's MEDIA_VIDEO_MAX_BYTES_POST
MAX_VIDEO_SECONDS = 600  # media's MEDIA_VIDEO_MAX_SECONDS_POST
MAX_IMAGE_SIDE = 1920
MAX_IMAGE_RATIO = 2.6  # full-page screenshots read badly as post photos

# ---- what may be used ---------------------------------------------------------
# Top-level folders of the media tree whose images the topic phases use.
ALLOWED_TOP = {
    "Real",
    "MDEIA",
    "Product",
    "Banner",
    "Project",
    "Social media",
    "abbreviation",
    "design pattrns",
}
SKIP_SUBFOLDERS = {"Certificate"}
# Second pass ("every usable file"): the other folders, the loose files at the
# top of a tree and these project sub-folders are used too, by the extra phase
# (topic ``x:<page>``), after the stricter screenshot filter below.
EXTRA_TOP = {
    "MyFilter": "tech",
    "WorkShop": "tech",
    "Problime": "tech",
    "Tools": "tech",
    "error": "tech",
    "Pc Tester": "tech",
    "Logo": "projects",
}
EXTRA_SUBFOLDERS = {"BackupData", "New folder", "New folder (2)", "login"}
# Screenshots that can show secrets or private data: editors, terminals, browser
# dev tools, deploy dashboards, system tools, account pages, CVs saved as images.
SENSITIVE_RE = re.compile(
    r"visual studio code|devtools|dokploy|thorium|command prompt|task manager|root@|"
    r"accounts-profile|accounts-dashboard|^settings \d{4}-|-cv-|resume|"
    r"^615089754_4281055458842511_",
    re.IGNORECASE,
)
NEWS_NAME_RE = re.compile(r"getty|rtrmadp|usa-fed|iran|^ap\d", re.IGNORECASE)
SKIP_EXT = {".pdf", ".ai", ".psd", ".rar", ".zip", ".ico", ".ini", ".svg", ".xlsx", ".exe"}
PERSONAL_RE = re.compile(
    r"resume|\bcv\b|passport|national.?id|id.?card|certificate|whatsapp|gmail|invoice|"
    r"password|bank|بطاقة|جواز|شهادة|فاتورة|البنك|كلمة.?السر|IMG_\d{4}\.MOV",
    re.IGNORECASE,
)
# Live conflict footage (missile strikes, interceptions, explosions) is not used:
# the whole folder, and any clip whose caption says so.
SKIP_VIDEO_FOLDERS = {"إران": "live conflict footage (strikes and interceptions)"}
GRAPHIC_WORDS = [
    "انفجار",
    "صواريخ",
    "صاروخ",
    "يستهدف",
    "تستهدف",
    "قصف",
    "هجمات",
    "الحوثي",
    "حزب الله",
    "تل أبيب",
    "الموت لكل",
    "توجع",
    "قتل",
    "جثث",
    "دماء",
    "missile",
    "frappes",
    "smashed",
    "strike",
    "explosion",
    "bomb",
    "killed",
    # Inflammatory or hateful wording about peoples, faiths or named people.
    "أوهام إسلامية",
    "الصهاينه",
    "العبرانين",
    "مشتموناش",
    "الاخواني",
    "خيانه",
    "اتربت",
    "اليهود",
    "black for a long time",
]

# ---- topics, pages and groups ------------------------------------------------
# Folder name -> topic. Real/<x> are videos, MDEIA/<x> news photos.
REAL_TOPICS = {
    "AI": "ai",
    "تاريخ": "history",
    "تاريخ سياسى": "history",
    "جيش": "military",
    "رمضان": "ramadan",
    "روسيا": "russia",
    "سياسة": "politics",
    "قران": "quran",
    "قصص": "stories",
    "ملابس": "fashion",
}
MDEIA_TOPICS = {
    "policy": "politics",
    "science": "science",
    "technology": "tech",
    "رياضة": "sports",
    "samsung phone": "samsung",
    "xiomi phone": "xiaomi",
}
# Loose clips under Real/ are routed by words in their caption.
ROUTE_WORDS = [
    ("quran", ["يرتل", "تلاوة", "قرآن", "القرآن"]),
    ("sports", ["boxing", "gym", "ملاكمة", "footwork", "جيم", "رياضة"]),
    ("military", ["air force", "rafale", "f-16", "tank", "دبابة"]),
    ("science", ["علمية", "علمي", "science", "processor"]),
    (
        "tech",
        ["javascript", "programming", "premiere", "nokia", "hdd", "dji", "fpv", "uav", "برمجة"],
    ),
    ("ai", ["claude", " ai ", "ذكاء"]),
    ("history", ["اهرامات", "الأهرامات", "pyramid", "فرعون"]),
    ("products", ["marketplace", "كرسى", "كرسي"]),
    ("politics", ["البرلمان", "trump", "ترامب", "السيسي", "sawiris", "ساويرس"]),
]


@dataclass(frozen=True)
class PageDef:
    key: str
    handle: str
    name: str
    category: str
    description: str
    tags: tuple[str, ...]


PAGES = [
    PageDef(
        "politics",
        "siyasa_today",
        "سياسة اليوم",
        "News & Media",
        "متابعة هادئة لأهم الأحداث السياسية في مصر والمنطقة.",
        ("سياسة", "مصر"),
    ),
    PageDef(
        "history",
        "tarikh_hekayat",
        "تاريخ وحكايات",
        "Education",
        "حكايات من التاريخ المصري والعربي بالصورة والفيديو.",
        ("تاريخ", "حكايات"),
    ),
    PageDef(
        "quran",
        "tilawat_quran",
        "تلاوات قرآنية",
        "Religious Organization",
        "تلاوات خاشعة لكبار القراء، مقاطع قصيرة يومية.",
        ("قرآن", "تلاوة"),
    ),
    PageDef(
        "ramadan",
        "ramadan_yegma3na",
        "رمضان يجمعنا",
        "Community",
        "أجواء رمضان والعيد واللمة الحلوة.",
        ("رمضان", "عيد"),
    ),
    PageDef(
        "sports",
        "riyada_now",
        "رياضة",
        "Sports",
        "أخبار الرياضة واللياقة والملاكمة وكمال الأجسام.",
        ("رياضة", "جيم"),
    ),
    PageDef(
        "tech",
        "tech_arabia",
        "تكنولوجيا",
        "Science & Technology",
        "أخبار التقنية ونصائح البرمجة والأدوات.",
        ("تكنولوجيا", "برمجة"),
    ),
    PageDef(
        "ai",
        "ai_arabi",
        "ذكاء اصطناعي",
        "Science & Technology",
        "كل جديد في الذكاء الاصطناعي بالعربي.",
        ("ذكاء_اصطناعي", "AI"),
    ),
    PageDef(
        "science",
        "olom_daily",
        "علوم",
        "Science",
        "معلومة علمية كل يوم بلغة بسيطة.",
        ("علوم", "معلومة"),
    ),
    PageDef(
        "samsung",
        "samsung_reviews_ar",
        "هواتف سامسونج - مراجعات",
        "Electronics",
        "صفحة مراجعات مستقلة لهواتف سامسونج، غير تابعة للشركة.",
        ("سامسونج", "موبايلات"),
    ),
    PageDef(
        "xiaomi",
        "xiaomi_reviews_ar",
        "هواتف شاومي - مراجعات",
        "Electronics",
        "صفحة مراجعات مستقلة لهواتف شاومي، غير تابعة للشركة.",
        ("شاومي", "موبايلات"),
    ),
    PageDef(
        "products",
        "montagat_store",
        "منتجات",
        "Shopping & Retail",
        "منتجات مختارة: موبايلات، لابتوبات، كراسي جيمنج وأكثر.",
        ("منتجات", "عروض"),
    ),
    PageDef(
        "military",
        "jaysh_difaa",
        "جيش ودفاع",
        "News & Media",
        "معدات وصناعات دفاعية وتاريخ عسكري.",
        ("جيش", "دفاع"),
    ),
    PageDef(
        "russia",
        "russia_news_ar",
        "أخبار روسيا",
        "News & Media",
        "تغطية لأخبار روسيا والتقنيات الجديدة.",
        ("روسيا", "أخبار"),
    ),
    PageDef(
        "stories",
        "qesas_ebar",
        "قصص وعبر",
        "Community",
        "قصص ملهمة ومواقف من الحياة.",
        ("قصص", "عبرة"),
    ),
    PageDef(
        "fashion",
        "azyaa_regali",
        "أزياء رجالي",
        "Clothing",
        "تفصيل وبدل وأناقة رجالي.",
        ("موضة", "ملابس"),
    ),
    PageDef(
        "news", "akhbar_alyoum", "أخبار اليوم", "News & Media", "أهم الأخبار في صورة.", ("أخبار",)
    ),
    PageDef(
        "projects",
        "mashare3_barmaga",
        "مشاريع برمجية",
        "Software",
        "معرض لواجهات ومشاريع ويب وموبايل.",
        ("مشاريع", "تصميم"),
    ),
    PageDef(
        "food",
        "fahm_burger",
        "برجر الفحم",
        "Restaurant",
        "برجر لحم وتشيكن مشوي على الفحم.",
        ("برجر", "أكل"),
    ),
    PageDef(
        "misc", "monawaat_daily", "منوعات", "Entertainment", "فيديوهات منوعة وخفيفة.", ("منوعات",)
    ),
]
PAGE_BY_KEY = {p.key: p for p in PAGES}


@dataclass(frozen=True)
class GroupDef:
    key: str
    handle: str
    name: str
    category: str
    privacy: str
    description: str
    topic: str


GROUPS = [
    GroupDef(
        "django",
        "django_devs_eg",
        "مطوري Django في مصر",
        "technology",
        "public",
        "أسئلة ونقاشات Django وPython والنشر.",
        "tech",
    ),
    GroupDef(
        "history",
        "history_lovers",
        "عشاق التاريخ",
        "education",
        "public",
        "نتكلم عن التاريخ المصري والعربي.",
        "history",
    ),
    GroupDef(
        "quran",
        "quran_circle",
        "حلقة القرآن",
        "general",
        "public",
        "تلاوات ومراجعة وتشجيع على الحفظ.",
        "quran",
    ),
    GroupDef(
        "gym", "gym_eg", "جيم وكمال أجسام", "sports", "public", "تمارين وتغذية وتحفيز.", "sports"
    ),
    GroupDef(
        "mobiles",
        "mobile_market_eg",
        "سوق الموبايلات",
        "business",
        "public",
        "بيع وشراء ومراجعات الموبايلات.",
        "samsung",
    ),
    GroupDef(
        "food", "akl_beity", "أكل بيتي ووصفات", "food", "public", "وصفات سهلة وتجارب مطاعم.", "food"
    ),
    GroupDef(
        "ai",
        "ai_tools_ar",
        "أدوات الذكاء الاصطناعي",
        "technology",
        "private",
        "تجارب عملية مع أدوات الذكاء الاصطناعي.",
        "ai",
    ),
    GroupDef(
        "talk",
        "hadi2_talk",
        "نقاشات هادئة",
        "general",
        "public",
        "نقاش محترم في الشأن العام.",
        "politics",
    ),
]

# ---- people ----------------------------------------------------------------------
MALE = [
    ("أحمد", "ahmed"),
    ("محمد", "mohamed"),
    ("محمود", "mahmoud"),
    ("مصطفى", "mostafa"),
    ("عمر", "omar"),
    ("يوسف", "youssef"),
    ("خالد", "khaled"),
    ("كريم", "karim"),
    ("طارق", "tarek"),
    ("حسام", "hossam"),
    ("إبراهيم", "ibrahim"),
    ("عبدالله", "abdallah"),
    ("سامح", "sameh"),
    ("هشام", "hesham"),
    ("علي", "ali"),
    ("حسن", "hassan"),
    ("ياسر", "yasser"),
    ("وليد", "waleed"),
    ("شريف", "sherif"),
    ("مروان", "marwan"),
    ("زياد", "ziad"),
    ("أدهم", "adham"),
    ("نادر", "nader"),
    ("عمرو", "amr"),
]
FEMALE = [
    ("سارة", "sara"),
    ("مريم", "mariam"),
    ("نور", "nour"),
    ("فاطمة", "fatma"),
    ("منى", "mona"),
    ("هبة", "heba"),
    ("ياسمين", "yasmin"),
    ("دينا", "dina"),
    ("رنا", "rana"),
    ("آية", "aya"),
    ("ندى", "nada"),
    ("سلمى", "salma"),
    ("ريم", "reem"),
    ("شيماء", "shaimaa"),
    ("إسراء", "esraa"),
    ("ملك", "malak"),
    ("هالة", "hala"),
    ("نهى", "noha"),
    ("جنى", "jana"),
    ("لمياء", "lamiaa"),
]
LAST = [
    ("حسن", "hassan"),
    ("عبدالرحمن", "abdelrahman"),
    ("السيد", "elsayed"),
    ("علي", "ali"),
    ("إبراهيم", "ibrahim"),
    ("فؤاد", "fouad"),
    ("منصور", "mansour"),
    ("الشريف", "elsherif"),
    ("سليمان", "soliman"),
    ("عبدالعزيز", "abdelaziz"),
    ("رمضان", "ramadan"),
    ("نبيل", "nabil"),
    ("جمال", "gamal"),
    ("فاروق", "farouk"),
    ("صلاح", "salah"),
    ("زكي", "zaki"),
    ("كامل", "kamel"),
    ("شاكر", "shaker"),
    ("عادل", "adel"),
    ("مراد", "morad"),
]
CITIES = [
    ("القاهرة", "مصر"),
    ("الجيزة", "مصر"),
    ("الإسكندرية", "مصر"),
    ("المنصورة", "مصر"),
    ("طنطا", "مصر"),
    ("أسيوط", "مصر"),
    ("الزقازيق", "مصر"),
    ("بورسعيد", "مصر"),
    ("شبين القناطر", "مصر"),
    ("الرياض", "السعودية"),
    ("جدة", "السعودية"),
    ("دبي", "الإمارات"),
    ("الكويت", "الكويت"),
    ("الدوحة", "قطر"),
]
BIOS = [
    "مهندس برمجيات ومحب للقهوة ☕",
    "طالبة في كلية التجارة 📚",
    "بحب التصوير والسفر",
    "مصمم جرافيك",
    "مدرس رياضيات",
    "أعمل في التسويق الرقمي",
    "طبيب أسنان 🦷",
    "صاحب مشروع صغير",
    "قارئ نهم وبحب التاريخ",
    "مطور Django وVue",
    "Fitness coach 💪",
    "محاسب ومهتم بالاستثمار",
    "بحب الكورة والبلايستيشن 🎮",
    "Frontend developer",
    "ربة منزل وبحب الطبخ 🍰",
    "طالب هندسة",
]
WORK = [
    ("Q-Tech Solutions", "مطور برمجيات"),
    ("بنك محلي", "محاسب"),
    ("مدرسة النور", "مدرس"),
    ("شركة تسويق", "مسؤول تسويق"),
    ("عيادة خاصة", "طبيب"),
    ("عمل حر", "مصمم جرافيك"),
    ("مصنع ملابس", "مدير إنتاج"),
    ("شركة اتصالات", "مهندس شبكات"),
]
SCHOOLS = [
    ("جامعة القاهرة", "بكالوريوس", "تجارة"),
    ("جامعة عين شمس", "بكالوريوس", "حاسبات ومعلومات"),
    ("جامعة الإسكندرية", "بكالوريوس", "هندسة"),
    ("جامعة المنصورة", "بكالوريوس", "طب"),
    ("جامعة الأزهر", "ليسانس", "دراسات إسلامية"),
    ("جامعة بنها", "بكالوريوس", "علوم"),
]

# ---- text pools ------------------------------------------------------------------
STATUS_TEXTS = [
    "صباح الخير على أحلى ناس ☀️",
    "الحمد لله على كل حال 🤍",
    "حد عنده ترشيح لكتاب حلو؟ 📚",
    "أخيرًا خلصت المشروع اللي كنت شغال عليه 🎉",
    "القهوة الصبح دي مفيش زيها ☕",
    "مين متابع الماتش النهارده؟ ⚽",
    "بفكر أبدأ أتعلم Python من الصفر، تنصحوني بإيه؟",
    "اللهم بلغنا رمضان 🌙",
    "الجو النهارده يجنن 🌤️",
    "يوم طويل بس الحمد لله عدى على خير",
    "مين بيحب البحر زيي؟ 🌊",
    "نصيحة اليوم: اشرب مية كتير 💧",
    "عايز أشتري لابتوب للبرمجة، ميزانية 20 ألف",
    "أحسن أكلة بتحبوها في الشتا؟ 🍲",
    "Finally deployed my side project 🚀",
    "Weekend plans? Thinking of a trip to Alexandria",
    "Coffee + code = happy morning",
    "الصبر مفتاح الفرج",
    "ذكريات الجامعة كانت أحلى أيام 🎓",
    "شكرًا لكل اللي سأل عليا 🙏",
    "كنت فاكر الموضوع سهل لحد ما بدأت 😅",
    "تحدي النهارده: ساعة رياضة 💪",
]
PHOTO_TEXTS = [
    "لقطة النهارده 📸",
    "شوفوا الصورة دي",
    "حلوة صح؟ ✨",
    "من أرشيف الصور",
    "التفاصيل 👌",
    "اختاروا المفضلة عندكم 👇",
    "Just sharing this",
    "مش محتاجة كلام",
    "ألبوم الأسبوع",
]
GROUP_TEXTS = {
    "tech": [
        "إيه أفضل طريقة تعمل deploy لمشروع Django على VPS؟",
        "حد جرب Celery مع Redis في الإنتاج؟ تجاربكم؟",
        "نصيحة: افصلوا settings الإنتاج عن التطوير من الأول.",
        "مين بيستخدم Docker Compose في التطوير المحلي؟",
        "Vue 3 ولا React لمشروع جديد؟",
        "إزاي تكتب tests كويسة لـ API؟",
    ],
    "history": [
        "مين أعظم ملك في تاريخ مصر القديمة في رأيكم؟",
        "ترشيحات لكتب عن تاريخ القاهرة؟",
        "معلومة: الهرم الأكبر فضل أطول مبنى في العالم آلاف السنين.",
        "زرت المتحف المصري الكبير، تجربة رائعة",
    ],
    "quran": [
        "مين حافظ سورة الكهف؟ تعالوا نراجع مع بعض",
        "أحب القراء لقلبكم؟",
        "ورد اليوم: صفحتين على الأقل 🤍",
        "نصائح للحفظ والمراجعة؟",
    ],
    "sports": [
        "برنامج تمرين للمبتدئين 3 أيام في الأسبوع؟",
        "البروتين ضروري ولا الأكل كفاية؟",
        "صورة قبل وبعد 6 شهور تمرين 💪",
        "أحسن تمرين للضهر؟",
    ],
    "samsung": [
        "مين جرب الموبايل الجديد؟ البطارية عاملة إزاي؟",
        "عايز موبايل بكاميرا كويسة في حدود 15 ألف",
        "للبيع موبايل مستعمل بحالة ممتازة",
        "شاومي ولا سامسونج في الفئة المتوسطة؟",
    ],
    "food": [
        "وصفة كيكة سهلة في 30 دقيقة 🍰",
        "أحسن برجر جربتوه في القاهرة؟",
        "طريقة عمل الكشري في البيت",
        "عزومة النهارده: محشي وفراخ 😋",
    ],
    "ai": [
        "إيه أكتر أداة ذكاء اصطناعي بتستخدموها في الشغل؟",
        "جربت أعمل تطبيق كامل بمساعدة AI",
        "نصائح لكتابة prompts كويسة",
        "الذكاء الاصطناعي هياخد شغل المبرمجين؟ رأيكم",
    ],
    "politics": [
        "إيه رأيكم في الأخبار الاقتصادية الأخيرة؟ نقاش بهدوء",
        "مصادر الأخبار اللي بتثقوا فيها؟",
        "الاحترام في النقاش أهم من الرأي نفسه",
        "ملخص أهم أحداث الأسبوع",
    ],
}
COMMENTS = {
    "generic": [
        "جميل جدًا 👏",
        "تسلم إيدك",
        "رائع",
        "عجبني جدًا",
        "ممتاز 👌",
        "حلو أوي",
        "Great post!",
        "Love this",
        "شكرًا على المشاركة",
        "فكرة حلوة",
        "تمام 👍",
        "مفيد جدًا",
        "🔥🔥",
        "ربنا يوفقك",
        "Nice one",
        "إبداع",
    ],
    "quran": [
        "سبحان الله 🤍",
        "اللهم بارك",
        "تلاوة خاشعة",
        "جزاكم الله خيرًا",
        "صدق الله العظيم",
        "ما شاء الله تبارك الله",
        "اللهم اجعل القرآن ربيع قلوبنا",
    ],
    "politics": [
        "تحليل مهم",
        "ربنا يحفظ مصر 🇪🇬",
        "محتاجين نفهم الصورة كاملة",
        "متابع",
        "كلام منطقي",
        "ننتظر التطورات",
    ],
    "history": [
        "معلومة جديدة عليا",
        "تاريخنا عظيم",
        "محتاجين أكتر من كده",
        "فكرتني بحاجات قريتها زمان",
    ],
    "tech": [
        "مفيد جدًا للمبرمجين",
        "جربتها وفعلًا شغالة",
        "شكرًا على التبسيط",
        "Very helpful",
        "محتاجين شرح أكتر",
        "حفظته 🔖",
    ],
    "ai": ["المستقبل هنا", "مخيف ومبهر في نفس الوقت", "جربت الأداة دي؟", "رهيب"],
    "sports": ["وحش 💪", "تحفيز رهيب", "الاستمرارية أهم حاجة", "أسطورة"],
    "funny": ["😂😂😂", "هههههه", "ميتة من الضحك 😂", "حقيقي جدًا 😂", "Lol"],
    "products": ["بكام؟", "متاح لسه؟", "فيه توصيل؟", "السعر نهائي؟", "شكله ممتاز"],
    "food": ["شكله يجنن 😋", "جعان 😂", "فين العنوان؟", "أحلى برجر"],
    "fashion": ["شيك جدًا", "ذوق عالي", "فين المحل؟", "التفصيل ممتاز"],
}
REPLIES = ["عندك حق", "بالظبط 👍", "شكرًا للتوضيح", "Agreed", "فعلًا", "😂", "أكيد", "متفق معاك"]
TOPIC_COMMENTS = {
    "quran": "quran",
    "ramadan": "quran",
    "politics": "politics",
    "news": "politics",
    "russia": "politics",
    "military": "politics",
    "history": "history",
    "tech": "tech",
    "projects": "tech",
    "samsung": "tech",
    "xiaomi": "tech",
    "science": "tech",
    "ai": "ai",
    "sports": "sports",
    "products": "products",
    "food": "food",
    "fashion": "fashion",
    "misc": "funny",
    "stories": "generic",
}
REACTION_MIX = {
    "default": {"like": 55, "love": 22, "haha": 6, "wow": 8, "care": 5, "sad": 3, "angry": 1},
    "quran": {"love": 50, "like": 30, "care": 18, "wow": 2},
    "funny": {"haha": 60, "like": 25, "love": 15},
    "politics": {"like": 60, "wow": 12, "love": 10, "sad": 8, "angry": 6, "care": 4},
}
QURAN_CAPTIONS = [
    "تلاوة خاشعة 🤍 #قرآن #تلاوة",
    "آيات تريح القلب #قرآن_كريم",
    "اسمعها بقلبك 🤍 #تلاوة",
    "من أجمل التلاوات #قرآن",
    "ورد اليوم 📖 #قرآن #تدبر",
    "صوت يأخذك بعيدًا 🤍 #تلاوة_خاشعة",
]
TOPIC_CAPTIONS = {
    "politics": ["متابعة لأهم الأحداث", "خبر اليوم", "قراءة في المشهد"],
    "history": ["من صفحات التاريخ", "حكاية من الماضي", "تاريخنا"],
    "science": ["معلومة علمية", "العلم ببساطة", "اكتشاف جديد"],
    "tech": ["نصيحة تقنية", "جديد التكنولوجيا", "معلومة للمبرمجين"],
    "ai": ["جديد الذكاء الاصطناعي", "تجربة مع AI"],
    "sports": ["رياضة", "تحفيز اليوم", "من الملاعب"],
    "news": ["خبر في صورة", "أخبار اليوم"],
    "products": ["متوفر الآن", "منتج اليوم"],
    "projects": ["من معرض أعمالنا", "واجهة مشروع", "تصميم جديد"],
    "military": ["صناعات دفاعية", "معدات"],
    "russia": ["من روسيا", "تقنيات جديدة"],
    "stories": ["قصة اليوم", "عبرة"],
    "fashion": ["أناقة", "تفصيل"],
    "ramadan": ["أجواء رمضان", "كل سنة وانتم طيبين"],
    "quran": ["تلاوة"],
    "misc": ["منوعات", "شوفوا ده"],
    "samsung": ["مراجعة سريعة", "نصيحة لمستخدمي سامسونج"],
    "xiaomi": ["مراجعة سريعة", "نصيحة لمستخدمي شاومي"],
    "food": ["من مطبخنا"],
}
PHONE_TEXTS = {
    "samsung": [
        "نصيحة: فعّل وضع توفير الطاقة الذكي عشان البطارية تعيش أكتر 🔋",
        "إيه رأيكم في شاشات سامسونج الجديدة؟",
        "مقارنة سريعة بين الفئة المتوسطة والرائدة",
        "تحديث جديد نزل، حد حدّث؟",
        "إزاي تنقل بياناتك لموبايل جديد بسهولة",
    ],
    "xiaomi": [
        "شاومي في الفئة الاقتصادية: قيمة مقابل سعر ممتازة",
        "إزاي تقفل الإعلانات في واجهة MIUI/HyperOS",
        "الشحن السريع: مفيد ولا بيأثر على البطارية؟",
        "أحسن إعدادات للكاميرا",
        "مين جرب الموديل الجديد؟",
    ],
}
LISTING_TEMPLATES = {
    # folder -> (title, category slug, price range EGP, description)
    "accessory-gaming-chairs": (
        "كرسي جيمنج مريح",
        "furniture",
        (5500, 12500),
        "كرسي جيمنج بمسند ظهر قابل للتعديل، حالة ممتازة.",
    ),
    "iPad": ("آيباد الجيل العاشر", "electronics", (16000, 26000), "آيباد بحالة ممتازة مع الشاحن."),
    "iphone": ("آيفون 17 برو ماكس", "electronics", (70000, 92000), "جديد بالكرتونة، ضمان محلي."),
    "LabTop": (
        "لابتوب Lenovo IdeaPad 1",
        "electronics",
        (14000, 21000),
        "مناسب للدراسة والبرمجة الخفيفة.",
    ),
    "كرواسون": ("كرواسون طازة", "other", (25, 45), "كرواسون زبدة طازة يوميًا."),
    "": ("منتج مميز", "other", (150, 900), "منتج بحالة ممتازة."),
}

# ---- small helpers ---------------------------------------------------------------
_print_lock = threading.Lock()


def log(msg: str) -> None:
    with _print_lock:
        print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def long_path(p: Path) -> str:
    """A path string that also works past MAX_PATH on Windows."""
    s = str(p.resolve())
    if os.name == "nt" and not s.startswith("\\\\?\\") and len(s) > 240:
        return "\\\\?\\" + s
    return s


def sha1_bytes(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()  # noqa: S324 - a content key, not security


def file_key(p: Path) -> str:
    """Stable content key: size plus the hash of the first 2 MB."""
    with open(long_path(p), "rb") as fh:
        head = fh.read(2 * 1024 * 1024)
    return sha1_bytes(head + str(os.path.getsize(long_path(p))).encode())[:16]


FULLWIDTH = str.maketrans(
    {
        "｜": "|",
        "：": ":",
        "？": "?",
        "＂": '"',
        "／": "/",
        "＊": "*",
        "＜": "<",
        "＞": ">",
        "＼": "\\",
        "\u200f": "",
        "\u200e": "",
    }
)
METRIC_RE = re.compile(r"([\d.,]+)\s*([KMB]?)\s+(views|reactions|shares|comments)", re.I)
GENERIC_NAME_RE = re.compile(
    r"^(video[_ ]?\d|video by|facebook|فيديو\s*_?\s*facebook|مشاهد$|img_|vid_)"
    # account_date_n file names (saved Instagram clips) and bare handles
    r"|^_*[\w.]+_[\d٠-٩]{6,8}_\d+$|^[a-z0-9_.]+_[a-z0-9]{6,}$",
    re.I,
)


def parse_metrics(name: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for num, unit, kind in METRIC_RE.findall(name):
        value = float(num.replace(",", ""))
        value *= {"": 1, "K": 1e3, "M": 1e6, "B": 1e9}[unit.upper()]
        out[kind.lower()] = int(value)
    return out


def clean_caption(stem: str) -> str:
    """The caption a clip was saved with, without counters, author or file noise."""
    text = unicodedata.normalize("NFC", stem.translate(FULLWIDTH))
    text = re.sub(r"\(\d+\)$", "", text).strip()
    text = re.sub(
        r"^(?:[\d.,]+\s*[KMB]?\s+(?:views|reactions|shares|comments)\s*·?\s*)+",
        "",
        text,
        flags=re.I,
    ).strip()
    text = text.lstrip("|").strip()
    raw_parts = [p.strip() for p in text.split("|")]
    if len(raw_parts) > 1 and not raw_parts[0]:
        return ""  # "| author": no caption was saved
    parts = [p for p in raw_parts if p]
    if not parts:
        return ""
    if len(parts) > 1:  # "caption | author": keep the caption only
        parts = parts[:-1] if len(parts[-1]) < 40 else parts
    caption = " ".join(parts)
    caption = re.sub(r"\bBy\s+[\w .]+$", "", caption).strip()
    caption = re.sub(r"\bon Reels$", "", caption, flags=re.I).strip()
    caption = re.sub(r"^Marketplace\s*-\s*", "", caption).strip(" _-")
    if GENERIC_NAME_RE.match(caption) or len(caption) < 4:
        return ""
    if len(stem) >= 38 and not caption.endswith(("…", ".", "!", "?", "؟")):
        caption += "…"  # saved names are cut short
    return caption


def is_graphic(text: str) -> bool:
    low = text.lower()
    return any(w.lower() in low for w in GRAPHIC_WORDS)


def route_loose_clip(caption: str) -> str:
    low = f" {caption.lower()} "
    for topic, words in ROUTE_WORDS:
        if any(w in low for w in words):
            return topic
    return "misc"


def engagement_weight(metrics: dict[str, int], rng: random.Random) -> float:
    """0..1: how much attention the item gets; real counters when the name has
    them, a long-tailed draw otherwise."""
    if metrics:
        views = metrics.get("views", 0)
        reach = max(views, metrics.get("reactions", 0) * 25, metrics.get("shares", 0) * 120, 1)
        return max(0.05, min(1.0, (math.log10(reach) - 2.5) / 5.0))
    return max(0.02, min(1.0, (rng.paretovariate(1.8) - 1) * 0.12 + 0.03))


def weighted_sample(rng: random.Random, items: list, weights: list[float], k: int) -> list:
    """k distinct items, heavier weights more likely (Efraimidis-Spirakis)."""
    if k <= 0 or not items:
        return []
    keyed = sorted(
        ((rng.random() ** (1.0 / max(w, 1e-6)), it) for it, w in zip(items, weights, strict=True)),
        key=lambda x: x[0],
        reverse=True,
    )
    return [it for _, it in keyed[: min(k, len(items))]]


def pick_reaction(rng: random.Random, topic: str) -> str:
    kind = TOPIC_COMMENTS.get(topic, "generic")
    mix = REACTION_MIX.get(kind if kind in REACTION_MIX else topic, REACTION_MIX["default"])
    if topic in ("quran", "ramadan"):
        mix = REACTION_MIX["quran"]
    return rng.choices(list(mix), weights=list(mix.values()))[0]


def hashtags(*tags: str) -> str:
    return " ".join("#" + t.replace(" ", "_") for t in tags if t)


# ---- the source catalog ------------------------------------------------------------
@dataclass
class ImageItem:
    path: Path
    topic: str
    group: str  # album key (project folder, product folder...)
    key: str = ""


@dataclass
class VideoItem:
    path: Path
    topic: str
    caption: str
    metrics: dict
    key: str = ""
    probe: dict = field(default_factory=dict)


@dataclass
class Catalog:
    images: list[ImageItem] = field(default_factory=list)
    videos: list[VideoItem] = field(default_factory=list)
    menus: list[dict] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)


def iter_files(root: Path):
    base = long_path(root)
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames.sort()
        for name in sorted(filenames):
            full = Path(dirpath) / name
            rel = Path(os.path.relpath(full, base))
            yield root / rel, rel


def parse_source(spec: str) -> tuple[Path, str]:
    """``PATH`` or ``PATH=topic`` (the topic of its loose top-level files)."""
    if "=" in spec and not re.match(r"^[A-Za-z]:?$", spec.rsplit("=", 1)[1]):
        path, topic = spec.rsplit("=", 1)
        return Path(path), topic.strip()
    return Path(spec), ""


def scan_sources(specs: list[str]) -> Catalog:
    cat = Catalog()
    seen: set[str] = set()
    # The topic files first, the extra pass after: a duplicate is always the
    # extra copy, so adding the extra pass never changes the first pass.
    entries: list[tuple[Path, Path, Path, str, str]] = []
    for spec in specs:
        root, root_topic = parse_source(spec)
        if not Path(long_path(root)).is_dir():
            raise SystemExit(f"source not found: {root}")
        for path, rel in iter_files(root):
            parts = rel.parts
            ext = path.suffix.lower()
            shown = rel.as_posix()
            top = parts[0] if len(parts) > 1 else ""
            if ext in SKIP_EXT or path.name.lower() == "desktop.ini":
                if ext == ".xlsx" and top == "Product":
                    cat.menus.extend(read_menu(path))
                cat.skipped.append((shown, f"excluded type {ext or path.name}"))
                continue
            if ext not in IMAGE_EXT | VIDEO_EXT:
                cat.skipped.append((shown, f"not media ({ext})"))
                continue
            extra = ""  # the page an extra-pass file goes to
            if not root_topic and (
                not top
                or top in EXTRA_TOP
                or (top == "Project" and any(p in EXTRA_SUBFOLDERS for p in parts[:-1]))
            ):
                extra = EXTRA_TOP.get(top, "projects" if top == "Project" else "tech")
                if SENSITIVE_RE.search(path.name):
                    cat.skipped.append((shown, "screenshot that can show private data"))
                    continue
            elif top and not root_topic and top not in ALLOWED_TOP:
                cat.skipped.append((shown, f"folder '{top}' is not in the media allow-list"))
                continue
            if any(p in SKIP_SUBFOLDERS for p in parts[:-1]):
                cat.skipped.append((shown, "excluded sub-folder"))
                continue
            if PERSONAL_RE.search(path.name):
                cat.skipped.append((shown, "looks like a personal document"))
                continue
            entries.append((path, rel, root, root_topic, extra))
    entries.sort(key=lambda e: bool(e[4]))  # stable: the original order within each pass
    for path, rel, root, root_topic, extra in entries:
        parts = rel.parts
        ext = path.suffix.lower()
        shown = rel.as_posix()
        top = parts[0] if len(parts) > 1 else ""
        try:
            key = file_key(path)
        except OSError as exc:
            cat.skipped.append((shown, f"unreadable: {exc}"))
            continue
        if key in seen:
            cat.skipped.append((shown, "duplicate of another file"))
            continue
        seen.add(key)
        sub = parts[1] if len(parts) > 2 else ""
        if ext in VIDEO_EXT:
            metrics = parse_metrics(path.stem.translate(FULLWIDTH))
            caption = clean_caption(path.stem)
            if root_topic and not top:
                topic = root_topic
            elif top == "Real":
                if sub in SKIP_VIDEO_FOLDERS:
                    cat.skipped.append((shown, SKIP_VIDEO_FOLDERS[sub]))
                    continue
                topic = REAL_TOPICS.get(sub) or route_loose_clip(caption)
            else:
                topic = route_loose_clip(caption)
            if is_graphic(path.stem.translate(FULLWIDTH)):
                cat.skipped.append((shown, "conflict, graphic or inflammatory caption"))
                continue
            size = os.path.getsize(long_path(path))
            if size > MAX_VIDEO_BYTES:
                cat.skipped.append((shown, f"larger than 200 MB ({size // 2**20} MB)"))
                continue
            cat.videos.append(VideoItem(path, topic, caption, metrics, key))
        elif extra:
            if extra == "tech" and NEWS_NAME_RE.search(path.name):
                extra = "news"
            group = (parts[-2] if len(parts) > 1 else "") or "لقطات"
            cat.images.append(ImageItem(path, f"x:{extra}", group, key))
        else:
            if root_topic and not top:
                topic, group = root_topic, root.name
            elif top == "MDEIA":
                topic, group = MDEIA_TOPICS.get(sub, "news"), sub or "news"
            elif top == "Product":
                topic, group = "products", sub
            elif top in ("Project", "Banner"):
                topic, group = "projects", sub or top
            else:  # Social media, abbreviation, design pattrns
                topic, group = "tech", top
            cat.images.append(ImageItem(path, topic, group, key))
    return cat


def read_menu(path: Path) -> list[dict]:
    """Rows of a price menu: name, description, price (EGP)."""
    if not HAVE_XLSX:
        return []
    rows = []
    try:
        wb = openpyxl.load_workbook(long_path(path), read_only=True, data_only=True)
    except Exception:  # noqa: BLE001 - a broken sheet is skipped
        return []
    for ws in wb.worksheets:
        header = None
        for row in ws.iter_rows(values_only=True):
            cells = list(row)
            if header is None:
                if any(isinstance(c, str) and ("اسم" in c or "الاسم" in c) for c in cells if c):
                    header = [str(c or "") for c in cells]
                continue
            data = dict(zip(header, cells, strict=False))
            name = next((v for k, v in data.items() if "اسم" in k and v), None)
            price = next(
                (
                    v
                    for k, v in data.items()
                    if ("سعر" in k or "السعر" in k) and isinstance(v, int | float)
                ),
                None,
            )
            desc = next((v for k, v in data.items() if ("مكونات" in k or "الوصف" in k) and v), "")
            if name and price:
                rows.append(
                    {
                        "name": str(name).strip(),
                        "price": float(price),
                        "description": str(desc or "").strip(),
                        "sheet": ws.title,
                    }
                )
    wb.close()
    return rows


def probe_video(path: Path) -> dict:
    """Local ffprobe (dry-run planning only): display width/height and duration."""
    exe = shutil.which("ffprobe")
    if not exe:
        return {}
    try:
        out = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [
                exe,
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_streams",
                "-show_format",
                long_path(path),
            ],
            capture_output=True,
            timeout=60,
            check=False,
        )
        info = json.loads(out.stdout or b"{}")
    except (OSError, subprocess.SubprocessError, ValueError):
        return {}
    stream = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), None)
    if not stream:
        return {}
    w, h = int(stream.get("width") or 0), int(stream.get("height") or 0)
    rotation = 0
    for side in stream.get("side_data_list") or []:
        if "rotation" in side:
            rotation = int(side["rotation"])
    rotation = int((stream.get("tags") or {}).get("rotate", rotation) or rotation)
    if abs(rotation) % 180 == 90:
        w, h = h, w
    return {"width": w, "height": h, "duration": float(info.get("format", {}).get("duration", 0))}


def local_reel_guess(probe: dict) -> str:
    """Mirror of post's reel rule (portrait 0.40..0.67, <= 90 s), for the plan only."""
    if not probe or not probe.get("width"):
        return "unknown"
    w, h, d = probe["width"], probe["height"], probe["duration"]
    if h > w and 0.40 <= w / h <= 0.67 and d <= 90:
        return "reel"
    return "video"


# ---- state (the manifest) --------------------------------------------------------
class State:
    def __init__(self, folder: Path):
        self.folder = folder
        self.path = folder / "manifest.json"
        self.lock = threading.RLock()
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "cache").mkdir(exist_ok=True)
        gi = folder / ".gitignore"
        if not gi.exists():
            gi.write_text("*\n", encoding="utf-8")
        if self.path.exists():
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        else:
            self.data = {}
        for k in (
            "accounts",
            "pages",
            "groups",
            "posts",
            "videos",
            "listings",
            "stories",
            "media",
            "done",
            "failures",
        ):
            self.data.setdefault(k, [] if k == "failures" else {})
        self._dirty = 0

    def save(self, force: bool = False) -> None:
        with self.lock:
            self._dirty += 1
            if not force and self._dirty < 20:
                return
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, self.path)
            self._dirty = 0

    def done(self, key: str) -> bool:
        return key in self.data["done"]

    def mark(self, key: str, value=1) -> None:
        with self.lock:
            self.data["done"][key] = value
        self.save()

    def fail(self, what: str, why) -> None:
        with self.lock:
            self.data["failures"].append({"what": what, "why": str(why)[:300], "at": time.time()})
        log(f"FAIL {what}: {str(why)[:200]}")
        self.save()


# ---- HTTP ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, status: int, body, what: str = ""):
        self.status, self.body = status, body
        code = body.get("error", {}).get("code") if isinstance(body, dict) else None
        self.code = code or ""
        super().__init__(f"{what} -> {status} {str(body)[:300]}")


class Api:
    def __init__(self, base: str, mailpit: str, password: str, state: State, pace: float):
        self.base = base.rstrip("/")
        self.mailpit = mailpit.rstrip("/")
        self.password = password
        self.state = state
        self.pace = pace
        self.tokens: dict[str, tuple[str, float]] = {}
        self.tok_lock = threading.Lock()
        self.requests = Counter()

    # -- raw --------------------------------------------------------------------------------------
    def raw(self, method, url, data=None, headers=None, timeout=60):
        req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)  # noqa: S310 - http(s) API URLs from the CLI
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - our API
                return resp.status, resp.read(), dict(resp.headers)
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read(), dict(exc.headers or {})

    def call(
        self,
        method,
        path,
        uid=None,
        body=None,
        *,
        idem=None,
        ok=(200, 201, 204),
        attempts=6,
        timeout=60,
    ):
        url = path if path.startswith("http") else self.base + path
        data = json.dumps(body).encode() if body is not None else None
        for attempt in range(attempts):
            headers = {"Content-Type": "application/json", "Accept": "application/json"}
            if uid:
                headers["Authorization"] = f"Bearer {self.token(uid)}"
            if idem:
                headers["Idempotency-Key"] = idem
            if self.pace:
                time.sleep(self.pace)
            try:
                status, payload, rheaders = self.raw(method, url, data, headers, timeout)
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
                wait = min(60, 2**attempt)
                log(f"network error {method} {path}: {exc}; retry in {wait}s")
                time.sleep(wait)
                continue
            self.requests[method] += 1
            try:
                parsed = json.loads(payload) if payload else {}
            except ValueError:
                parsed = {"raw": payload[:200].decode("utf-8", "replace")}
            if status == 401 and uid and attempt < attempts - 1:
                self.token(uid, refresh=True)
                continue
            if status in (429, 502, 503, 504) and attempt < attempts - 1:
                retry = rheaders.get("Retry-After") or rheaders.get("retry-after")
                wait = (
                    float(retry) if retry and str(retry).isdigit() else min(60, 2 ** (attempt + 1))
                )
                time.sleep(wait)
                continue
            if status not in ok:
                raise ApiError(status, parsed, f"{method} {path}")
            return parsed.get("data", parsed) if isinstance(parsed, dict) else parsed
        raise ApiError(0, {}, f"{method} {path}: gave up")

    # -- auth -------------------------------------------------------------------------------------
    def token(self, uid: str, refresh: bool = False) -> str:
        with self.tok_lock:
            cached = self.tokens.get(uid)
            if cached and not refresh and time.time() - cached[1] < 600:
                return cached[0]
        acc = self.state.data["accounts"][uid]
        data = self.call(
            "POST", "/auth/login/", body={"email": acc["email"], "password": self.password}
        )
        with self.tok_lock:
            self.tokens[uid] = (data["access_token"], time.time())
        return data["access_token"]

    def verification_token(self, email: str, timeout: float = 30) -> str | None:
        deadline = time.time() + timeout
        q = urllib.parse.quote(f'to:"{email}"')
        while time.time() < deadline:
            status, payload, _ = self.raw("GET", f"{self.mailpit}/search?query={q}")
            if status == 200:
                messages = json.loads(payload).get("messages") or []
                for m in messages:  # newest first
                    st, body, _ = self.raw("GET", f"{self.mailpit}/message/{m['ID']}")
                    if st != 200:
                        continue
                    text = json.loads(body).get("Text", "")
                    match = re.search(r"verify[^\s]*token=([\w\-.:%]+)", text) or re.search(
                        r"token=([\w\-.:%]+)", text
                    )
                    if match:
                        return urllib.parse.unquote(match.group(1))
            time.sleep(1)
        return None

    # -- media ------------------------------------------------------------------------------------
    def upload(self, uid: str, data: bytes, mime: str, kind: str, purpose: str = "") -> str:
        body = {"kind": kind, "mime": mime, "size": len(data), "visibility": "public"}
        if purpose:
            body["purpose"] = purpose
        signed = self.call("POST", "/media/uploads/sign/", uid, body)
        url = signed["upload_url"]
        headers = {"Content-Type": mime}
        for k, v in (signed.get("headers") or {}).items():
            headers[k] = v
        parsed = urllib.parse.urlparse(url)
        if parsed.hostname == "minio":  # dev signs for the in-network host
            headers["Host"] = parsed.netloc
            url = url.replace(f"//{parsed.netloc}", f"//127.0.0.1:{parsed.port or 9000}", 1)
        for attempt in range(5):
            try:
                status, payload, _ = self.raw("PUT", url, data, headers, timeout=600)
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                status, payload = 0, str(exc).encode()
            if status in (200, 204):
                break
            time.sleep(2**attempt)
        else:
            raise ApiError(status, {"raw": payload[:200].decode("utf-8", "replace")}, "PUT upload")
        media_id = signed["media_id"]
        self.call("POST", f"/media/uploads/{media_id}/complete/", uid, {})
        return media_id

    def media(self, uid: str, media_id: str) -> dict:
        return self.call("GET", f"/media/{media_id}/", uid)


# ---- images ---------------------------------------------------------------------------
def prepared_image(state: State, item_path: Path, crop: bool = False) -> tuple[bytes, str] | None:
    """JPEG bytes (re-encoded: EXIF and GPS stripped, AVIF converted, capped size).

    A very tall or wide image (a full-page screenshot) is ``None``, or with
    ``crop`` its top (tall) or centre (wide) at the widest ratio a post shows."""
    key = file_key(item_path)
    cached = state.folder / "cache" / f"{key}{'.crop' if crop else ''}.jpg"
    if cached.exists():
        return cached.read_bytes(), "image/jpeg"
    if not HAVE_PIL:
        ext = item_path.suffix.lower()
        mime = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
            ".gif": "image/gif",
        }.get(ext)
        return (Path(long_path(item_path)).read_bytes(), mime) if mime else None
    try:
        with Image.open(long_path(item_path)) as im:
            im = ImageOps.exif_transpose(im)
            w, h = im.size
            if min(w, h) < 160:
                return None
            if max(w, h) / max(1, min(w, h)) > MAX_IMAGE_RATIO:
                if not crop:
                    return None
                if h > w:
                    im = im.crop((0, 0, w, int(w * MAX_IMAGE_RATIO)))
                else:
                    side = int(h * MAX_IMAGE_RATIO)
                    im = im.crop(((w - side) // 2, 0, (w - side) // 2 + side, h))
            im = im.convert("RGB")
            im.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=85, optimize=True)
    except Exception:  # noqa: BLE001 - an unreadable image is skipped
        return None
    data = buf.getvalue()
    cached.write_bytes(data)
    return data, "image/jpeg"


def generated_avatar(seed_text: str) -> bytes | None:
    """An abstract avatar in Tara colours (no faces, no text), deterministic per seed."""
    if not HAVE_PIL:
        return None
    rng = random.Random(seed_text)
    palette = [
        (0x6A, 0x00, 0xF4),
        (0xA8, 0x55, 0xF7),
        (0xFF, 0x4E, 0xD8),
        (0x0B, 0x0B, 0x1F),
        (0xE8, 0xE6, 0xFF),
        (0x3B, 0x82, 0xF6),
        (0x14, 0xB8, 0xA6),
        (0xF5, 0x9E, 0x0B),
    ]
    a, b = rng.sample(palette, 2)
    size = 384
    # Gradients and masks only (no ImageDraw: it crashes on some Pillow builds).
    ramp = Image.linear_gradient("L").rotate(rng.choice([0, 45, 90, 135])).resize((size, size))
    img = Image.composite(
        Image.new("RGB", (size, size), b), Image.new("RGB", (size, size), a), ramp
    )
    for _ in range(rng.randint(2, 5)):
        d = rng.randint(80, 320)
        alpha = rng.randint(60, 140)
        mask = (
            Image.radial_gradient("L")
            .resize((d, d))
            .point(lambda v, al=alpha: al if v < 128 else 0)
        )
        blob = Image.new("RGB", (d, d), rng.choice(palette))
        img.paste(
            blob, (rng.randint(-d // 2, size - d // 2), rng.randint(-d // 2, size - d // 2)), mask
        )
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=88)
    return buf.getvalue()


# ---- the seeder -------------------------------------------------------------------------
class Seeder:
    def __init__(self, args, catalog: Catalog, state: State):
        self.args = args
        self.cat = catalog
        self.state = state
        self.S = state.data
        self.api = Api(args.api, args.mailpit, args.password, state, args.pace)
        self.rng = random.Random(SEED)
        self.limit = args.limit or 0
        self.counts = Counter()
        self.image_pool = list(catalog.images)
        self.users: list[str] = []
        self.activity: dict[str, float] = {}
        self.popularity: dict[str, float] = {}
        self.friends: dict[str, set[str]] = defaultdict(set)
        self.ns = args.namespace

    # -- utils ------------------------------------------------------------------------------------
    def idem(self, key: str) -> str:
        return hashlib.sha256(f"{self.ns}:{key}".encode()).hexdigest()[:48]

    def acc(self, uid: str) -> dict:
        return self.S["accounts"][uid]

    def aid(self, uid: str) -> str:
        return self.S["accounts"][uid]["id"]

    def lim(self, n: int) -> int:
        return min(n, self.limit) if self.limit else n

    def upload_image(
        self,
        uid: str,
        media_key: str,
        item: ImageItem | None = None,
        raw: bytes | None = None,
        crop: bool = False,
    ) -> str | None:
        """Upload once per logical key; reused on re-runs (until attached)."""
        known = self.S["media"].get(media_key)
        if known:
            return known["media_id"]
        if raw is not None:
            data, mime = raw, "image/jpeg"
        else:
            prepared = prepared_image(self.state, item.path, crop=crop)
            if not prepared:
                return None
            data, mime = prepared
        try:
            media_id = self.api.upload(uid, data, mime, "image")
        except ApiError as exc:
            self.state.fail(f"upload {media_key}", exc)
            return None
        with self.state.lock:
            self.S["media"][media_key] = {"media_id": media_id, "owner": uid}
        self.state.save()
        self.counts["images_uploaded"] += 1
        return media_id

    def wait_ready(self, uid: str, media_ids: list[str], timeout: float = 60) -> None:
        deadline = time.time() + timeout
        pending = list(media_ids)
        while pending and time.time() < deadline:
            still = []
            for m in pending:
                try:
                    if self.api.media(uid, m).get("status") not in (
                        "ready",
                        "processing",
                        "failed",
                    ):
                        still.append(m)
                except ApiError:
                    still.append(m)
            pending = still
            if pending:
                time.sleep(1)

    def usable_images(self, items: list[ImageItem]) -> list[ImageItem]:
        return [i for i in items if prepared_image(self.state, i.path)]

    # -- accounts ---------------------------------------------------------------------------------
    def plan_accounts(self) -> list[dict]:
        rng = random.Random(SEED + 1)
        out, used = [], set()
        for n in range(1, self.args.accounts + 1):
            female = rng.random() < 0.42
            first, first_lat = rng.choice(FEMALE if female else MALE)
            last, last_lat = rng.choice(LAST)
            base = f"{first_lat}_{last_lat}"
            handle = base if base not in used else f"{base}{n}"
            used.add(handle)
            city, country = rng.choice(CITIES)
            dob = date(rng.randint(1968, 2007), rng.randint(1, 12), rng.randint(1, 28))
            out.append(
                {
                    "uid": f"u{n:03d}",
                    "email": f"seed.{handle}.{n:03d}@example.com",
                    "handle": handle[:30],
                    "first_name": first,
                    "last_name": last,
                    "gender": "female" if female else "male",
                    "dob": dob.isoformat(),
                    "city": city,
                    "country": country,
                    "language": "ar" if rng.random() < 0.82 else "en",
                    "theme": rng.choice(["dark", "light", "system"]),
                    "bio": rng.choice(BIOS),
                    "work": rng.choice(WORK) if rng.random() < 0.7 else None,
                    "school": rng.choice(SCHOOLS) if rng.random() < 0.6 else None,
                    "activity": rng.paretovariate(1.3),
                    "popularity": rng.paretovariate(1.1),
                }
            )
        return out

    def ensure_account(self, spec: dict) -> bool:
        uid = spec["uid"]
        acc = self.S["accounts"].get(uid)
        if acc and acc.get("id") and acc.get("verified"):
            return True
        email = spec["email"]
        with self.state.lock:
            self.S["accounts"][uid] = {
                **(acc or {}),
                "email": email,
                "handle": spec["handle"],
                "city": spec["city"],
            }
        signup = {
            "email": email,
            "password": self.args.password,
            "password_confirm": self.args.password,
            "first_name": spec["first_name"],
            "last_name": spec["last_name"],
            "date_of_birth": spec["dob"],
            "gender": spec["gender"],
            "accept_terms": True,
            "terms_version": LEGAL_VERSION,
            "privacy_version": LEGAL_VERSION,
            "language": spec["language"],
            "theme": spec["theme"],
            "handle": spec["handle"],
        }
        try:
            self.api.call("POST", "/auth/register/", body=signup, ok=(200, 201, 202))
        except ApiError as exc:
            if exc.code == "legal_version_mismatch" or "legal_version" in str(exc.body):
                raise SystemExit("legal version mismatch: pass TARA_LEGAL_VERSION") from exc
            if "handle" in str(exc.body) and exc.status == 400:
                signup["handle"] = f"{spec['handle'][:24]}_{uid}"
                try:
                    self.api.call("POST", "/auth/register/", body=signup, ok=(200, 201, 202))
                except ApiError as exc2:
                    if exc2.status not in (400, 409):
                        self.state.fail(f"register {uid}", exc2)
                        return False
            elif exc.status not in (400, 409):
                self.state.fail(f"register {uid}", exc)
                return False
        # Verified already? Log in; otherwise verify from Mailpit.
        status, payload, _ = self.api.raw(
            "POST",
            self.api.base + "/auth/login/",
            json.dumps({"email": email, "password": self.args.password}).encode(),
            {"Content-Type": "application/json"},
        )
        if status == 403:
            token = self.api.verification_token(email)
            if not token:
                self.api.call(
                    "POST", "/auth/verify-email/resend/", body={"email": email}, ok=(200, 202, 204)
                )
                token = self.api.verification_token(email, timeout=45)
            if not token:
                self.state.fail(f"verify {uid}", "no verification e-mail in Mailpit")
                return False
            try:
                self.api.call("POST", "/auth/verify-email/", body={"token": token})
            except ApiError as exc:
                self.state.fail(f"verify {uid}", exc)
                return False
        elif status != 200:
            self.state.fail(f"login {uid}", f"{status} {payload[:200]!r}")
            return False
        me = self.api.call("GET", "/me/", uid)
        with self.state.lock:
            self.S["accounts"][uid].update({"id": me["id"], "verified": True})
        self.state.save(force=True)
        self.counts["accounts_created"] += 1
        return True

    def ensure_profile(self, spec: dict) -> None:
        uid = spec["uid"]
        if self.state.done(f"profile:{uid}"):
            return
        rng = random.Random(f"profile:{uid}")
        avatar_pool = [i for i in self.image_pool if i.topic in ("products", "tech", "sports")]
        cover_pool = [
            i
            for i in self.image_pool
            if i.topic in ("projects", "news", "sports", "politics", "science")
        ]
        if rng.random() < 0.5 or not avatar_pool:
            avatar = self.upload_image(uid, f"avatar:{uid}", raw=generated_avatar(uid))
        else:
            avatar = self.upload_image(uid, f"avatar:{uid}", rng.choice(avatar_pool))
        cover = (
            self.upload_image(uid, f"cover:{uid}", rng.choice(cover_pool)) if cover_pool else None
        )
        self.wait_ready(uid, [m for m in (avatar, cover) if m])
        patch = {
            "bio": spec["bio"],
            "city": spec["city"],
            "country": spec["country"],
            "intro": spec["bio"],
        }
        if avatar:
            patch["avatar_media_id"] = avatar
        if cover:
            patch["cover_media_id"] = cover
        try:
            self.api.call("PATCH", "/profile/me/", uid, patch)
        except ApiError as exc:
            self.state.fail(f"profile {uid}", exc)
            return
        if spec.get("work"):
            company, title = spec["work"]
            start = f"{rng.randint(2012, 2023)}-0{rng.randint(1, 9)}-01"
            try:
                self.api.call(
                    "POST",
                    "/profile/me/work/",
                    uid,
                    {"company": company, "title": title, "start_date": start, "is_current": True},
                )
            except ApiError as exc:
                self.state.fail(f"work {uid}", exc)
        if spec.get("school"):
            school, degree, fld = spec["school"]
            start = rng.randint(2005, 2020)
            try:
                self.api.call(
                    "POST",
                    "/profile/me/education/",
                    uid,
                    {
                        "school": school,
                        "degree": degree,
                        "field": fld,
                        "start_year": start,
                        "end_year": start + 4,
                    },
                )
            except ApiError as exc:
                self.state.fail(f"education {uid}", exc)
        self.state.mark(f"profile:{uid}")

    def phase_accounts(self) -> None:
        specs = self.plan_accounts()
        log(f"accounts: {len(specs)} planned")
        for i, spec in enumerate(specs, 1):
            if self.ensure_account(spec):
                self.users.append(spec["uid"])
                self.activity[spec["uid"]] = spec["activity"]
                self.popularity[spec["uid"]] = spec["popularity"]
            if i % 20 == 0:
                log(f"accounts: {i}/{len(specs)}")
        with ThreadPoolExecutor(self.args.workers) as pool:
            list(pool.map(self.ensure_profile, [s for s in specs if s["uid"] in self.users]))
        self.state.save(force=True)
        log(f"accounts ready: {len(self.users)}")

    # -- graph ------------------------------------------------------------------------------------
    def phase_graph(self) -> None:
        rng = random.Random(SEED + 2)
        users = self.users
        pop = [self.popularity[u] for u in users]
        pairs = set()
        for u in users:
            degree = int(min(30, 3 + self.activity[u] * 3 + rng.random() * 5))
            for v in weighted_sample(rng, users, pop, degree):
                if v != u:
                    pairs.add(tuple(sorted((u, v))))
        pairs = sorted(pairs)
        log(f"graph: {len(pairs)} friendships planned")

        def befriend(pair):
            a, b = pair
            key = f"friend:{a}:{b}"
            if self.state.done(key):
                return
            try:
                req = self.api.call(
                    "POST", "/friends/requests/", a, {"to_user_id": self.aid(b)}, ok=(200, 201)
                )
                self.api.call("POST", f"/friends/requests/{req['id']}/accept/", b, ok=(200, 201))
            except ApiError as exc:
                if exc.status != 409:
                    self.state.fail(key, exc)
                    return
            self.state.mark(key)

        with ThreadPoolExecutor(self.args.workers) as pool:
            list(pool.map(befriend, pairs))
        for a, b in pairs:
            if self.state.done(f"friend:{a}:{b}"):
                self.friends[a].add(b)
                self.friends[b].add(a)
        follows = []
        for u in users:
            k = int(min(40, 4 + self.activity[u] * 4 + rng.random() * 8))
            for v in weighted_sample(rng, users, pop, k):
                if v != u and v not in self.friends[u]:
                    follows.append((u, v))

        def follow(pair):
            u, v = pair
            key = f"follow:{u}:{v}"
            if self.state.done(key):
                return
            try:
                self.api.call("POST", f"/follows/{self.aid(v)}/", u, {"target_type": "user"})
            except ApiError as exc:
                if exc.status != 409:
                    self.state.fail(key, exc)
                    return
            self.state.mark(key)

        with ThreadPoolExecutor(self.args.workers) as pool:
            list(pool.map(follow, follows))
        self.counts["friendships"] = sum(1 for k in self.S["done"] if k.startswith("friend:"))
        self.counts["follows"] = sum(1 for k in self.S["done"] if k.startswith("follow:"))
        self.state.save(force=True)
        log(f"graph: {self.counts['friendships']} friendships, {self.counts['follows']} follows")

    # -- pages ------------------------------------------------------------------------------------
    def page_team(self, key: str) -> dict[str, str]:
        return self.S["pages"].get(key, {}).get("team", {})

    def page_posters(self, key: str) -> list[str]:
        team = self.page_team(key)
        return [u for u, r in team.items() if r in ("owner", "admin", "editor")]

    def phase_pages(self) -> None:
        rng = random.Random(SEED + 3)
        by_pop = sorted(self.users, key=lambda u: -self.popularity[u])
        creators = by_pop[: max(10, len(by_pop) // 6)]
        for n, page in enumerate(PAGES):
            rec = self.S["pages"].get(page.key)
            owner = rec["owner"] if rec else creators[n % len(creators)]
            if not rec or not rec.get("id"):
                topic_imgs = self.usable_images([i for i in self.image_pool if i.topic == page.key])
                avatar = (
                    self.upload_image(owner, f"page-avatar:{page.key}", topic_imgs[0])
                    if topic_imgs
                    else self.upload_image(
                        owner, f"page-avatar:{page.key}", raw=generated_avatar(page.handle)
                    )
                )
                covers = self.usable_images(
                    [i for i in self.image_pool if i.group in ("Banner",) or i.topic == page.key]
                )
                cover = (
                    self.upload_image(
                        owner, f"page-cover:{page.key}", covers[(n * 7) % len(covers)]
                    )
                    if covers
                    else None
                )
                self.wait_ready(owner, [m for m in (avatar, cover) if m])
                body = {
                    "handle": page.handle,
                    "name": page.name,
                    "category": page.category,
                    "description": page.description,
                    "location": "القاهرة، مصر",
                    "avatar_media_id": avatar,
                    "cover_media_id": cover,
                }
                body = {k: v for k, v in body.items() if v}
                created = None
                for _attempt in range(3):
                    try:
                        created = self.api.call("POST", "/pages/", owner, body, ok=(201,))
                        break
                    except ApiError as exc:
                        if exc.status == 409:
                            body["handle"] = f"{page.handle[:25]}_{rng.randint(10, 9999)}"
                            continue
                        self.state.fail(f"page {page.key}", exc)
                        break
                if not created:
                    continue
                with self.state.lock:
                    self.S["pages"][page.key] = {
                        "id": created["id"],
                        "handle": created["handle"],
                        "owner": owner,
                        "team": {owner: "owner"},
                    }
                self.state.save(force=True)
                self.counts["pages_created"] += 1
            rec = self.S["pages"][page.key]
            # The team: an admin, one or two editors, sometimes a moderator.
            others = [u for u in rng.sample(self.users, min(6, len(self.users))) if u != owner]
            others += [others[-1]] * 4  # tiny trial runs: fewer people than roles
            wanted = {others[0]: "admin", others[1]: "editor"}
            if rng.random() < 0.6:
                wanted[others[2]] = "editor"
            if rng.random() < 0.5:
                wanted[others[3]] = "moderator"
            for member, role in wanted.items():
                if member in rec["team"]:
                    continue
                if any(r == role for r in rec["team"].values()) and role == "admin":
                    continue
                try:
                    self.api.call(
                        "POST",
                        f"/pages/id/{rec['id']}/members/",
                        owner,
                        {"account_id": self.aid(member), "role": role},
                        ok=(201,),
                    )
                except ApiError as exc:
                    if exc.status != 409:
                        self.state.fail(f"page-member {page.key}", exc)
                        continue
                with self.state.lock:
                    rec["team"][member] = role
                self.state.save()
        # Followers: popular pages get more.
        page_pop = {p.key: random.Random(p.key).paretovariate(1.2) for p in PAGES}
        keys = [k for k in page_pop if self.S["pages"].get(k, {}).get("id")]
        jobs = []
        for u in self.users:
            k = rng.randint(2, 9)
            for key in weighted_sample(rng, keys, [page_pop[x] for x in keys], k):
                jobs.append((u, key))

        def follow_page(job):
            u, key = job
            dkey = f"follow-page:{u}:{key}"
            if self.state.done(dkey):
                return
            try:
                self.api.call(
                    "POST", f"/follows/{self.S['pages'][key]['id']}/", u, {"target_type": "page"}
                )
            except ApiError as exc:
                if exc.status != 409:
                    self.state.fail(dkey, exc)
                    return
            self.state.mark(dkey)

        with ThreadPoolExecutor(self.args.workers) as pool:
            list(pool.map(follow_page, jobs))
        self.state.save(force=True)
        log(
            f"pages: {len(keys)} pages, "
            f"{sum(1 for k in self.S['done'] if k.startswith('follow-page:'))} page follows"
        )

    # -- groups -----------------------------------------------------------------------------------
    def phase_groups(self) -> None:
        rng = random.Random(SEED + 4)
        for n, g in enumerate(GROUPS):
            rec = self.S["groups"].get(g.key)
            if not rec:
                owner = rng.choice(self.users)
                covers = self.usable_images(
                    [i for i in self.image_pool if i.topic == g.topic]
                    or [i for i in self.image_pool if i.group == "Banner"]
                )
                cover = (
                    self.upload_image(owner, f"group-cover:{g.key}", covers[n % len(covers)])
                    if covers
                    else None
                )
                if cover:
                    self.wait_ready(owner, [cover])
                body = {
                    "name": g.name,
                    "handle": g.handle,
                    "description": g.description,
                    "category": g.category,
                    "privacy": g.privacy,
                }
                if cover:
                    body["cover_media_id"] = cover
                created = None
                for _ in range(3):
                    try:
                        created = self.api.call("POST", "/groups/", owner, body, ok=(201,))
                        break
                    except ApiError as exc:
                        if exc.status in (400, 409) and "handle" in str(exc.body):
                            body["handle"] = f"{g.handle[:24]}_{rng.randint(10, 999)}"
                            continue
                        self.state.fail(f"group {g.key}", exc)
                        break
                if not created:
                    continue
                rec = {
                    "id": created["id"],
                    "handle": created.get("handle", body["handle"]),
                    "owner": owner,
                    "members": [owner],
                    "staff": {},
                }
                with self.state.lock:
                    self.S["groups"][g.key] = rec
                self.state.save(force=True)
                self.counts["groups_created"] += 1
            size = rng.randint(min(15, len(self.users)), min(70, len(self.users)))
            members = weighted_sample(rng, self.users, [self.activity[u] for u in self.users], size)
            for u in members:
                if u in rec["members"]:
                    continue
                try:
                    self.api.call("POST", f"/groups/{rec['id']}/join/", u, ok=(200, 201, 204))
                except ApiError as exc:
                    self.state.fail(f"join {g.key} {u}", exc)
                    continue
                with self.state.lock:
                    rec["members"].append(u)
                self.state.save()
            for role, who in (("admin", rec["members"][1:2]), ("moderator", rec["members"][2:3])):
                for u in who:
                    if rec["staff"].get(u):
                        continue
                    try:
                        self.api.call(
                            "PATCH",
                            f"/groups/{rec['id']}/members/{self.aid(u)}/",
                            rec["owner"],
                            {"role": role},
                        )
                        rec["staff"][u] = role
                    except ApiError as exc:
                        self.state.fail(f"group-role {g.key}", exc)
        self.state.save(force=True)
        log(f"groups: {len(self.S['groups'])} groups")

    # -- posts ------------------------------------------------------------------------------------
    def create_post(self, pkey: str, uid: str, body: dict, meta: dict) -> str | None:
        if pkey in self.S["posts"]:
            return self.S["posts"][pkey]["id"]
        try:
            created = self.api.call("POST", "/posts/", uid, body, idem=self.idem(pkey), ok=(201,))
        except ApiError as exc:
            self.state.fail(f"post {pkey}", exc)
            return None
        with self.state.lock:
            self.S["posts"][pkey] = {
                "id": created["id"],
                "uid": uid,
                "type": created["type"],
                **meta,
            }
        self.state.save()
        self.counts[f"posts_{created['type']}"] += 1
        return created["id"]

    def photo_post(
        self,
        pkey: str,
        uid: str,
        items: list[ImageItem],
        text: str,
        meta: dict,
        page_id: str | None = None,
        group_id: str | None = None,
        audience: str = "public",
        crop: bool = False,
    ) -> None:
        if pkey in self.S["posts"]:
            return
        media = []
        for i, item in enumerate(items[:10]):
            m = self.upload_image(uid, f"{pkey}:{i}", item, crop=crop)
            if m:
                media.append(m)
        if not media:
            return
        self.wait_ready(uid, media)
        body = {"body": text, "type": "image", "media_ids": media, "audience": audience}
        if page_id:
            body["page_id"] = page_id
        if group_id:
            body["group_id"] = group_id
        self.create_post(pkey, uid, body, {**meta, "photos": len(media)})

    def phase_page_posts(self) -> None:
        rng = random.Random(SEED + 5)
        jobs = []
        for page in PAGES:
            rec = self.S["pages"].get(page.key)
            if not rec:
                continue
            posters = self.page_posters(page.key) or [rec["owner"]]
            imgs = self.usable_images([i for i in self.image_pool if i.topic == page.key])
            # Albums by folder (projects, products), single photos otherwise.
            by_group: dict[str, list[ImageItem]] = defaultdict(list)
            for it in imgs:
                by_group[it.group].append(it)
            for grp, items in sorted(by_group.items()):
                chunks: list[list[ImageItem]] = []
                if page.key in ("projects", "products") and len(items) > 1:
                    for s in range(0, len(items), 6):
                        chunks.append(items[s : s + 6])
                else:
                    pos = 0
                    while pos < len(items):
                        size = 1 if rng.random() < 0.72 else rng.randint(2, 4)
                        chunks.append(items[pos : pos + size])
                        pos += size
                for c, chunk in enumerate(chunks):
                    caption = rng.choice(TOPIC_CAPTIONS.get(page.key, ["📸"]))
                    if page.key == "projects":
                        caption = f"{caption}: {grp}"
                    text = f"{caption}\n{hashtags(*page.tags)}"
                    pkey = f"page:{page.key}:{grp}:{c}"
                    w = engagement_weight({}, rng)
                    jobs.append(
                        (
                            pkey,
                            posters[c % len(posters)],
                            chunk,
                            text,
                            {"topic": page.key, "page": page.key, "weight": w},
                            rec["id"],
                        )
                    )
            # Text posts for pages without media (phone review pages) and a few for all.
            texts = PHONE_TEXTS.get(page.key, []) + [
                f"{rng.choice(TOPIC_CAPTIONS.get(page.key, ['']))} 👇 {hashtags(*page.tags)}"
            ]
            for t, text in enumerate(texts):
                pkey = f"page-text:{page.key}:{t}"
                w = engagement_weight({}, rng)
                jobs.append(
                    (
                        pkey,
                        posters[t % len(posters)],
                        [],
                        f"{text} {hashtags(*page.tags)}",
                        {"topic": page.key, "page": page.key, "weight": w},
                        rec["id"],
                    )
                )
        jobs = jobs[: self.lim(len(jobs))]
        log(f"page posts: {len(jobs)} planned")

        def run(job):
            pkey, uid, chunk, text, meta, page_id = job
            if chunk:
                self.photo_post(pkey, uid, chunk, text, meta, page_id=page_id)
            else:
                self.create_post(
                    pkey, uid, {"body": text, "type": "text", "page_id": page_id}, meta
                )

        with ThreadPoolExecutor(self.args.workers) as pool:
            list(pool.map(run, jobs))
        self.state.save(force=True)

    def phase_user_posts(self) -> None:
        rng = random.Random(SEED + 6)
        general = self.usable_images(self.image_pool)
        captions = [v.caption for v in self.cat.videos if v.caption]
        jobs = []
        n_photo = self.lim(int(len(self.users) * 1.0))
        for n in range(n_photo):
            uid = weighted_sample(rng, self.users, [self.activity[u] for u in self.users], 1)[0]
            size = 1 if rng.random() < 0.7 else rng.randint(2, 5)
            items = rng.sample(general, min(size, len(general))) if general else []
            topic = items[0].topic if items else "generic"
            text = rng.choice(PHOTO_TEXTS)
            if rng.random() < 0.4:
                text += " " + hashtags(rng.choice(["صورة", "لقطة", "ذكريات", "photography"]))
            audience = rng.choices(["public", "friends", "followers"], [80, 15, 5])[0]
            jobs.append(
                (
                    "photo",
                    f"user-photo:{n}",
                    uid,
                    items,
                    text,
                    {"topic": topic, "weight": engagement_weight({}, rng), "audience": audience},
                )
            )
        texts = [(c, "caption") for c in captions] + [(t, "status") for t in STATUS_TEXTS]
        n_text = self.lim(len(texts) + len(self.users) // 2)
        for n in range(n_text):
            uid = weighted_sample(rng, self.users, [self.activity[u] for u in self.users], 1)[0]
            text, kind = texts[n % len(texts)]
            if kind == "caption" and "#" not in text:
                text += " " + hashtags(rng.choice(["رأيكم", "نقاش", "تريند", "مصر"]))
            body = {
                "body": text,
                "type": "text",
                "audience": rng.choices(["public", "friends"], [85, 15])[0],
            }
            if rng.random() < 0.15:
                body["feeling"] = rng.choice(["happy", "grateful", "excited", "blessed", "proud"])
            if rng.random() < 0.15:
                body["location"] = self.acc(uid).get("city") or rng.choice(CITIES)[0]
            jobs.append(
                (
                    "text",
                    f"user-text:{n}",
                    uid,
                    body,
                    None,
                    {
                        "topic": "generic",
                        "weight": engagement_weight({}, rng),
                        "audience": body["audience"],
                    },
                )
            )
        log(f"user posts: {len(jobs)} planned")

        def run(job):
            kind, pkey, uid, a, b, meta = job
            if kind == "photo":
                self.photo_post(pkey, uid, a, b, meta, audience=meta["audience"])
            else:
                self.create_post(pkey, uid, a, meta)

        with ThreadPoolExecutor(self.args.workers) as pool:
            list(pool.map(run, jobs))
        self.state.save(force=True)

    def phase_group_posts(self) -> None:
        rng = random.Random(SEED + 7)
        jobs = []
        for g in GROUPS:
            rec = self.S["groups"].get(g.key)
            if not rec:
                continue
            texts = GROUP_TEXTS.get(g.topic, GROUP_TEXTS["tech"])
            imgs = self.usable_images([i for i in self.image_pool if i.topic == g.topic])
            for n in range(self.lim(len(texts) + 4)):
                uid = rng.choice(rec["members"])
                text = texts[n % len(texts)]
                pkey = f"group:{g.key}:{n}"
                meta = {"topic": g.topic, "group": g.key, "weight": engagement_weight({}, rng)}
                if imgs and rng.random() < 0.3:
                    jobs.append((pkey, uid, [rng.choice(imgs)], text, meta, rec["id"]))
                else:
                    jobs.append((pkey, uid, [], text, meta, rec["id"]))
        log(f"group posts: {len(jobs)} planned")

        def run(job):
            pkey, uid, items, text, meta, gid = job
            if items:
                self.photo_post(pkey, uid, items, text, meta, group_id=gid)
            else:
                self.create_post(pkey, uid, {"body": text, "type": "text", "group_id": gid}, meta)

        with ThreadPoolExecutor(self.args.workers) as pool:
            list(pool.map(run, jobs))
        self.state.save(force=True)

    def phase_extra_posts(self) -> None:
        """Every usable image the topic phases leave out: the extra folders
        (``x:`` topics) and full-page screenshots, shown cropped. Keys come from
        the files, so this phase never shifts what the earlier phases planned."""
        extra = [
            i
            for i in self.image_pool
            if i.topic.startswith("x:")
            or (
                prepared_image(self.state, i.path) is None
                and prepared_image(self.state, i.path, crop=True) is not None
            )
        ]
        by_group: dict[tuple[str, str], list[ImageItem]] = defaultdict(list)
        for it in extra:
            if prepared_image(self.state, it.path, crop=True):
                by_group[(it.topic.removeprefix("x:"), it.group)].append(it)
        jobs = []
        for (topic, grp), items in sorted(by_group.items()):
            items.sort(key=lambda i: i.key)
            rng = random.Random(f"{SEED}:extra:{topic}:{grp}")
            page = PAGE_BY_KEY.get(topic)
            rec = self.S["pages"].get(topic) if page else None
            posters = (self.page_posters(topic) or [rec["owner"]]) if rec else []
            album = topic in ("projects", "products")
            pos = 0
            while pos < len(items):
                size = 6 if album else (1 if rng.random() < 0.65 else rng.randint(2, 4))
                chunk = items[pos : pos + size]
                pos += size
                pkey = f"extra:{topic}:{chunk[0].key}"
                w = engagement_weight({}, rng)
                if rec and rng.random() < 0.6:
                    caption = rng.choice(TOPIC_CAPTIONS.get(topic, ["📸"]))
                    if album:
                        caption = f"{caption}: {grp}"
                    text = f"{caption}\n{hashtags(*page.tags)}"
                    uid = posters[len(jobs) % len(posters)]
                    meta = {"topic": topic, "page": topic, "weight": w}
                    jobs.append((pkey, uid, chunk, text, meta, rec["id"], "public"))
                else:
                    weights = [self.activity[u] for u in self.users]
                    uid = weighted_sample(rng, self.users, weights, 1)[0]
                    text = rng.choice(PHOTO_TEXTS)
                    if page:
                        text += " " + hashtags(*page.tags)
                    audience = rng.choices(["public", "friends"], [85, 15])[0]
                    meta = {"topic": topic, "weight": w, "audience": audience}
                    jobs.append((pkey, uid, chunk, text, meta, None, audience))
        jobs = jobs[: self.lim(len(jobs))]
        log(f"extra photo posts: {len(jobs)} planned from {len(extra)} images")

        def run(job):
            pkey, uid, chunk, text, meta, page_id, audience = job
            self.photo_post(
                pkey, uid, chunk, text, meta, page_id=page_id, audience=audience, crop=True
            )

        with ThreadPoolExecutor(self.args.workers) as pool:
            list(pool.map(run, jobs))
        self.state.save(force=True)

    # -- videos and reels -------------------------------------------------------------------------
    def plan_videos(self) -> list[dict]:
        rng = random.Random(SEED + 8)
        by_pop = sorted(self.users, key=lambda u: -self.popularity[u])
        creators = by_pop[:15]
        plan = []
        for n, v in enumerate(self.cat.videos):
            topic = v.topic
            page = topic if topic in PAGE_BY_KEY and self.S["pages"].get(topic) else None
            # Loose clips without a page topic go to creators' own profiles.
            if topic == "misc" and rng.random() < 0.5:
                page = None
            if page:
                posters = self.page_posters(page) or [self.S["pages"][page]["owner"]]
                uploader = posters[n % len(posters)]
            else:
                uploader = creators[n % len(creators)] if creators else self.users[0]
            if v.caption:
                caption = v.caption
            elif topic == "quran":
                caption = rng.choice(QURAN_CAPTIONS)
            else:
                caption = rng.choice(TOPIC_CAPTIONS.get(topic, ["🎬"]))
            tags = PAGE_BY_KEY[page].tags if page else ()
            if "#" not in caption and tags:
                caption = f"{caption}\n{hashtags(*tags)}"
            plan.append(
                {
                    "vkey": f"video:{v.key}",
                    "item": v,
                    "page": page,
                    "uploader": uploader,
                    "caption": caption[:2000],
                    "topic": topic,
                    "weight": engagement_weight(v.metrics, rng),
                }
            )
        return plan[: self.lim(len(plan))]

    def phase_videos(self) -> None:
        plan = self.plan_videos()
        log(f"videos: {len(plan)} planned (max {self.args.max_transcoding} transcoding at once)")
        queue = [
            p
            for p in plan
            if not (
                self.S["videos"].get(p["vkey"], {}).get("post_id")
                or self.S["videos"].get(p["vkey"], {}).get("final")
            )
        ]
        in_flight: list[dict] = []
        # Resume uploads that were in flight when the last run stopped.
        for p in list(queue):
            rec = self.S["videos"].get(p["vkey"])
            if rec and rec.get("media_id"):
                in_flight.append(p)
                queue.remove(p)
        while queue or in_flight:
            while queue and len(in_flight) < self.args.max_transcoding:
                p = queue.pop(0)
                if self.start_video(p):
                    in_flight.append(p)
            time.sleep(5)
            for p in list(in_flight):
                if self.poll_video(p):
                    in_flight.remove(p)
            self.state.save(force=True)
        log("videos: done")

    def start_video(self, p: dict) -> bool:
        item: VideoItem = p["item"]
        try:
            data = Path(long_path(item.path)).read_bytes()
            mime = VIDEO_MIME[item.path.suffix.lower()]
            media_id = self.api.upload(p["uploader"], data, mime, "video", purpose="post")
        except (ApiError, OSError) as exc:
            self.state.fail(f"video upload {item.path.name}", exc)
            with self.state.lock:
                self.S["videos"][p["vkey"]] = {
                    "src": item.path.name,
                    "final": "upload_failed",
                    "why": str(exc)[:200],
                }
            return False
        with self.state.lock:
            self.S["videos"][p["vkey"]] = {
                "src": item.path.name,
                "media_id": media_id,
                "uploader": p["uploader"],
                "page": p["page"],
                "started": time.time(),
            }
        self.state.save(force=True)
        self.counts["videos_uploaded"] += 1
        log(f"video uploaded ({len(data) // 2**20} MB): {item.path.name[:60]}")
        return True

    def poll_video(self, p: dict) -> bool:
        """True when the clip is finished (published or failed)."""
        rec = self.S["videos"][p["vkey"]]
        uid, media_id = rec["uploader"], rec["media_id"]
        try:
            info = self.api.media(uid, media_id)
        except ApiError as exc:
            if exc.status == 404:
                rec["final"] = "media_missing"
                return True
            return False
        status = info.get("status")
        if status == "failed":
            rec.update({"final": "transcode_failed", "why": info.get("failure_code")})
            self.state.fail(f"transcode {rec['src']}", info.get("failure_code"))
            return True
        if status != "ready":
            if time.time() - rec.get("started", time.time()) > self.args.transcode_timeout:
                rec.update({"final": "transcode_timeout"})
                self.state.fail(f"transcode {rec['src']}", "timed out waiting for ready")
                return True
            return False
        rec.update(
            {
                "width": info.get("width"),
                "height": info.get("height"),
                "duration_ms": info.get("duration_ms"),
            }
        )
        try:
            elig = self.api.call("POST", "/reels/eligibility/", uid, {"media_id": media_id})
        except ApiError as exc:
            self.state.fail(f"eligibility {rec['src']}", exc)
            return False
        page = rec.get("page", p["page"])  # as started, even if the plan moved since
        page_id = self.S["pages"][page]["id"] if page else None
        meta = {
            "topic": p["topic"],
            "page": page,
            "weight": p["weight"],
            "video_key": p["vkey"],
        }
        if elig.get("eligible"):
            body = {"media_id": media_id, "caption": p["caption"], "audience": "public"}
            if page_id:
                body["page_id"] = page_id
            try:
                created = self.api.call(
                    "POST", "/reels/", uid, body, idem=self.idem(p["vkey"]), ok=(201,)
                )
            except ApiError as exc:
                self.state.fail(f"reel {rec['src']}", exc)
                rec["final"] = f"reel_failed:{exc.code}"
                return True
            kind = "reel"
        elif elig.get("code") in ("reel_not_vertical", "reel_too_long"):
            body = {"body": p["caption"], "type": "video", "media_ids": [media_id]}
            if page_id:
                body["page_id"] = page_id
            try:
                created = self.api.call(
                    "POST", "/posts/", uid, body, idem=self.idem(p["vkey"]), ok=(201,)
                )
            except ApiError as exc:
                self.state.fail(f"video post {rec['src']}", exc)
                rec["final"] = f"video_failed:{exc.code}"
                return True
            kind = "video"
        elif elig.get("code") == "reel_video_not_ready":
            return False
        else:
            rec["final"] = f"not_publishable:{elig.get('code')}"
            self.state.fail(f"video {rec['src']}", elig)
            return True
        rec.update(
            {"post_id": created["id"], "kind": kind, "reason": elig.get("code") or "eligible"}
        )
        with self.state.lock:
            self.S["posts"][p["vkey"]] = {"id": created["id"], "uid": uid, "type": kind, **meta}
        self.counts[f"posts_{kind}"] += 1
        log(
            f"{kind} published: {rec['src'][:60]} ({rec.get('width')}x{rec.get('height')}, "
            f"{(rec.get('duration_ms') or 0) / 1000:.0f}s)"
        )
        return True

    # -- marketplace ------------------------------------------------------------------------------
    def phase_listings(self) -> None:
        rng = random.Random(SEED + 9)
        try:
            cats = {
                c["slug"]: c["id"]
                for c in self.api.call("GET", "/marketplace/categories/", self.users[0])
            }
        except ApiError as exc:
            self.state.fail("marketplace categories", exc)
            return
        imgs = self.usable_images([i for i in self.image_pool if i.topic == "products"])
        by_folder: dict[str, list[ImageItem]] = defaultdict(list)
        for it in imgs:
            by_folder[it.group].append(it)
        jobs = []
        sellers = rng.sample(self.users, min(25, len(self.users)))
        for folder, items in sorted(by_folder.items()):
            title, slug, (lo, hi), desc = LISTING_TEMPLATES.get(folder, LISTING_TEMPLATES[""])
            pos = 0
            n = 0
            while pos < len(items):
                size = rng.randint(1, 3)
                chunk = items[pos : pos + size]
                pos += size
                price = round(rng.uniform(lo, hi), -1 if hi > 100 else 0)
                jobs.append(
                    {
                        "key": f"listing:{folder}:{n}",
                        "seller": rng.choice(sellers),
                        "title": f"{title}" + (f" - {n + 1}" if n else ""),
                        "description": desc,
                        "category": cats.get(slug) or cats.get("other"),
                        "price": price,
                        "images": chunk,
                        "condition": rng.choice(["new", "like_new", "good"]),
                    }
                )
                n += 1
        food_seller = self.S["pages"].get("food", {}).get("owner") or rng.choice(sellers)
        seen_names = set()
        for row in self.cat.menus:
            name = row["name"]
            if name in seen_names:
                continue
            seen_names.add(name)
            jobs.append(
                {
                    "key": f"listing:menu:{name}",
                    "seller": food_seller,
                    "title": f"ساندوتش {name}" if row["sheet"] in ("برجر لحم", "تشيكن") else name,
                    "description": row["description"] or "طازة يوميًا",
                    "category": cats.get("other"),
                    "price": row["price"],
                    "images": [],
                    "condition": "new",
                }
            )
        # Phones from the review pages' topics, so every category has stock.
        for n, (model, price) in enumerate(
            [
                ("سامسونج جالاكسي A55", 17500),
                ("شاومي ريدمي نوت 13", 9800),
                ("سامسونج جالاكسي S24 مستعمل", 31000),
                ("شاومي 14T", 24500),
            ]
        ):
            jobs.append(
                {
                    "key": f"listing:phone:{n}",
                    "seller": rng.choice(sellers),
                    "title": model,
                    "description": "بحالة ممتازة، معاه الكرتونة والشاحن.",
                    "category": cats.get("electronics"),
                    "price": price,
                    "images": [],
                    "condition": rng.choice(["like_new", "good"]),
                }
            )
        jobs = jobs[: self.lim(len(jobs))]
        log(f"listings: {len(jobs)} planned")

        def run(job):
            key = job["key"]
            if key in self.S["listings"]:
                return
            uid = job["seller"]
            media = [
                m
                for i, it in enumerate(job["images"])
                if (m := self.upload_image(uid, f"{key}:{i}", it))
            ]
            if media:
                self.wait_ready(uid, media)
            body = {
                "category_id": job["category"],
                "title": job["title"][:160],
                "description": job["description"][:5000],
                "price": f"{job['price']:.2f}",
                "currency": "EGP",
                "price_type": "fixed",
                "condition": job["condition"],
                "location": self.acc(uid).get("city", ""),
                "media_ids": media,
            }
            try:
                created = self.api.call(
                    "POST", "/marketplace/listings/", uid, body, idem=self.idem(key), ok=(201,)
                )
                self.api.call("POST", f"/marketplace/listings/{created['id']}/publish/", uid)
            except ApiError as exc:
                self.state.fail(key, exc)
                return
            with self.state.lock:
                self.S["listings"][key] = {
                    "id": created["id"],
                    "seller": uid,
                    "weight": engagement_weight({}, rng),
                }
            self.state.save()
            self.counts["listings"] += 1

        with ThreadPoolExecutor(self.args.workers) as pool:
            list(pool.map(run, jobs))
        self.state.save(force=True)

    # -- stories ----------------------------------------------------------------------------------
    def phase_stories(self) -> None:
        rng = random.Random(SEED + 10)
        general = self.usable_images(self.image_pool)
        authors = weighted_sample(
            rng,
            self.users,
            [self.activity[u] for u in self.users],
            self.lim(max(36, len(self.users) // 3)),
        )
        day = time.strftime("%Y-%m-%d")
        jobs = []
        for uid in authors:
            for s in range(rng.choice([1, 1, 2, 3])):
                jobs.append((uid, s))

        def run(job):
            uid, s = job
            key = f"story:{day}:{uid}:{s}"
            if key in self.S["stories"]:
                return
            audience = rng.choice(["public", "public", "friends"])
            if general and rng.random() < 0.7:
                media = self.upload_image(uid, key, rng.choice(general))
                if not media:
                    return
                self.wait_ready(uid, [media])
                body = {
                    "kind": "photo",
                    "media_id": media,
                    "audience": audience,
                    "text": rng.choice(["", "", "صباح الخير", "📸", "يوم حلو"]),
                }
            else:
                body = {
                    "kind": "text",
                    "text": rng.choice(STATUS_TEXTS),
                    "audience": audience,
                    "background": rng.choice(
                        ["violet", "dusk", "magenta", "night", "aurora", "sunset"]
                    ),
                }
            try:
                created = self.api.call(
                    "POST", "/stories/", uid, body, idem=self.idem(key), ok=(201,)
                )
            except ApiError as exc:
                self.state.fail(key, exc)
                return
            with self.state.lock:
                self.S["stories"][key] = {"id": created["id"], "uid": uid, "audience": audience}
            self.state.save()
            self.counts["stories"] += 1

        with ThreadPoolExecutor(self.args.workers) as pool:
            list(pool.map(run, jobs))
        self.state.save(force=True)
        log(f"stories: {sum(1 for k in self.S['stories'] if k.startswith(f'story:{day}'))} today")

    # -- engagement -------------------------------------------------------------------------------
    def eligible_viewers(self, post: dict) -> list[str]:
        author = post["uid"]
        if post.get("group"):
            return [u for u in self.S["groups"][post["group"]]["members"] if u != author]
        if post.get("page"):
            return [u for u in self.users if u != author]
        audience = post.get("audience", "public")
        if audience == "friends":
            return sorted(self.friends.get(author, set()))
        if audience == "followers":  # who follows the author (friends follow too)
            fans = {
                k.split(":")[1]
                for k in self.S["done"]
                if k.endswith(f":{author}") and k.startswith("follow:")
            }
            return sorted(fans | self.friends.get(author, set()))
        return [u for u in self.users if u != author]

    def engage_post(self, pkey: str) -> None:
        post = self.S["posts"][pkey]
        if self.state.done(f"engaged:{pkey}:{len(self.users)}"):
            return
        rng = random.Random(f"engage:{pkey}")
        pid, topic = post["id"], post.get("topic", "generic")
        viewers = self.eligible_viewers(post)
        if not viewers:
            self.state.mark(f"engaged:{pkey}:{len(self.users)}")
            return
        w = float(post.get("weight", 0.1))
        acts = [self.activity[u] for u in viewers]
        n_react = max(
            1 if rng.random() < 0.8 else 0,
            min(len(viewers), round(len(viewers) * (0.02 + 0.85 * w**1.3) * rng.uniform(0.7, 1.2))),
        )
        reactors = weighted_sample(rng, viewers, acts, n_react)
        for u in reactors:
            key = f"react:{pid}:{u}"
            if self.state.done(key):
                continue
            try:
                self.api.call(
                    "POST",
                    f"/posts/{pid}/reactions/",
                    u,
                    {"type": pick_reaction(rng, topic)},
                    ok=(200, 201, 204),
                )
                self.state.mark(key)
            except ApiError as exc:
                if exc.status == 404:
                    break  # not visible to this viewer set (e.g. a pending group post)
                self.state.fail(key, exc)
        pool = COMMENTS[TOPIC_COMMENTS.get(topic, "generic")] + COMMENTS["generic"][:6]
        n_comments = round(n_react * rng.uniform(0.08, 0.3)) + (1 if rng.random() < 0.3 else 0)
        commenters = weighted_sample(rng, viewers, acts, min(n_comments, len(viewers)))
        comment_ids = []
        for c, u in enumerate(commenters):
            key = f"comment:{pid}:{u}:{c}"
            if self.state.done(key):
                cid = self.S["done"][key]
                if isinstance(cid, str):
                    comment_ids.append(cid)
                continue
            body = {"body": rng.choice(pool)}
            if comment_ids and rng.random() < 0.25:
                body = {"body": rng.choice(REPLIES), "reply_to_id": rng.choice(comment_ids)}
            try:
                created = self.api.call("POST", f"/posts/{pid}/comments/", u, body, ok=(201,))
                self.state.mark(key, created["id"])
                comment_ids.append(created["id"])
            except ApiError as exc:
                if exc.status == 404:
                    break
                self.state.fail(key, exc)
        if post.get("type") != "share" and not post.get("group"):
            n_share = round(n_react * rng.uniform(0.0, 0.07))
            for u in weighted_sample(rng, viewers, acts, n_share):
                skey = f"share:{pid}:{u}"
                if self.state.done(skey):
                    continue
                try:
                    created = self.api.call(
                        "POST",
                        f"/posts/{pid}/share/",
                        u,
                        {"body": rng.choice(["", "", "شوفوا ده 👇", "مهم", "Worth a look"])},
                        idem=self.idem(skey),
                        ok=(200, 201),
                    )
                    self.state.mark(skey)
                    with self.state.lock:
                        self.S["posts"][skey] = {
                            "id": created["id"],
                            "uid": u,
                            "type": "share",
                            "topic": topic,
                            "weight": w * 0.3,
                            "shared_of": pid,
                        }
                    self.counts["posts_share"] += 1
                except ApiError as exc:
                    self.state.fail(skey, exc)
        n_save = round(n_react * rng.uniform(0.02, 0.12))
        for u in weighted_sample(rng, viewers, acts, n_save):
            key = f"save:{pid}:{u}"
            if self.state.done(key):
                continue
            try:
                self.api.call("POST", f"/posts/{pid}/save/", u, {}, ok=(200, 201))
                self.state.mark(key)
            except ApiError as exc:
                self.state.fail(key, exc)
        if post.get("type") == "reel":
            n_views = min(len(viewers), max(n_react, round(len(viewers) * (0.1 + 0.9 * w))))
            for u in weighted_sample(rng, viewers, acts, n_views):
                key = f"view:{pid}:{u}"
                if self.state.done(key):
                    continue
                try:
                    self.api.call("POST", f"/reels/{pid}/view/", u, ok=(200,))
                    self.state.mark(key)
                except ApiError as exc:
                    self.state.fail(key, exc)
        # Some "not interested" signal on the long tail.
        if w < 0.15 and not post.get("group") and rng.random() < 0.35:
            for u in rng.sample(viewers, min(len(viewers), rng.randint(1, 3))):
                if u in reactors:
                    continue
                key = f"hide:{pid}:{u}"
                if self.state.done(key):
                    continue
                try:
                    if post.get("type") == "reel":
                        self.api.call("POST", f"/reels/{pid}/hide/", u, ok=(204,))
                    else:
                        self.api.call(
                            "POST",
                            "/feed/hide/",
                            u,
                            {
                                "post_id": pid,
                                "reason": rng.choice(
                                    ["not_interested", "not_interested", "annoying"]
                                ),
                            },
                            ok=(200, 201, 204),
                        )
                    self.state.mark(key)
                except ApiError as exc:
                    if exc.status not in (404, 409):
                        self.state.fail(key, exc)
        self.state.mark(f"engaged:{pkey}:{len(self.users)}")

    def engage_listings_and_stories(self) -> None:
        rng = random.Random(SEED + 11)
        for rec in list(self.S["listings"].values()):
            n = round(len(self.users) * 0.25 * rec.get("weight", 0.1)) + rng.randint(0, 3)
            for u in rng.sample(self.users, min(n, len(self.users))):
                if u == rec["seller"]:
                    continue
                for action in ("view", "save") if rng.random() < 0.35 else ("view",):
                    dkey = f"listing-{action}:{rec['id']}:{u}"
                    if self.state.done(dkey):
                        continue
                    try:
                        self.api.call(
                            "POST",
                            f"/marketplace/listings/{rec['id']}/{action}/",
                            u,
                            {},
                            ok=(200, 201, 202, 204),
                        )
                        self.state.mark(dkey)
                    except ApiError as exc:
                        if exc.status not in (404, 409):
                            self.state.fail(dkey, exc)
        day = time.strftime("%Y-%m-%d")
        for key, rec in list(self.S["stories"].items()):
            if not key.startswith(f"story:{day}"):
                continue
            pool = (
                sorted(self.friends.get(rec["uid"], set()))
                if rec["audience"] == "friends"
                else [u for u in self.users if u != rec["uid"]]
            )
            for u in rng.sample(pool, min(len(pool), rng.randint(2, 25))):
                dkey = f"story-seen:{rec['id']}:{u}"
                if self.state.done(dkey):
                    continue
                try:
                    self.api.call("POST", f"/stories/{rec['id']}/seen/", u, ok=(200, 201, 204))
                    if rng.random() < 0.2:
                        self.api.call(
                            "POST",
                            f"/stories/{rec['id']}/react/",
                            u,
                            {"reaction": rng.choice(["love", "like", "haha", "wow"])},
                        )
                    self.state.mark(dkey)
                except ApiError as exc:
                    if exc.status != 404:
                        self.state.fail(dkey, exc)

    def phase_engagement(self) -> None:
        keys = [k for k, p in self.S["posts"].items() if p.get("type") != "share"]
        log(f"engagement: {len(keys)} posts")
        done = 0
        with ThreadPoolExecutor(self.args.workers) as pool:
            for _ in pool.map(self.engage_post, keys):
                done += 1
                if done % 50 == 0:
                    log(f"engagement: {done}/{len(keys)}")
        self.engage_listings_and_stories()
        self.state.save(force=True)

    # -- run --------------------------------------------------------------------------------------
    def run(self) -> None:
        phases = self.args.phases
        self.phase_accounts()
        if not self.users:
            raise SystemExit("no accounts could be created; is the stack up?")
        if "graph" in phases:
            self.phase_graph()
        else:
            self.load_friends()
        if "pages" in phases:
            self.phase_pages()
        if "groups" in phases:
            self.phase_groups()
        video_thread = None
        if "videos" in phases and self.cat.videos:
            video_thread = threading.Thread(target=self.phase_videos, name="videos", daemon=True)
            video_thread.start()
        if "posts" in phases:
            self.phase_page_posts()
            self.phase_user_posts()
            self.phase_group_posts()
            self.phase_extra_posts()
        if "listings" in phases:
            self.phase_listings()
        if "stories" in phases:
            self.phase_stories()
        if "engagement" in phases:
            self.phase_engagement()  # what exists so far; videos get a second pass
        if video_thread:
            log("waiting for the video pipeline to finish...")
            video_thread.join()
            if "engagement" in phases:
                self.phase_engagement()
        self.state.save(force=True)

    def load_friends(self) -> None:
        for k in self.S["done"]:
            if k.startswith("friend:"):
                _, a, b = k.split(":")
                self.friends[a].add(b)
                self.friends[b].add(a)


# ---- reporting ----------------------------------------------------------------------
def report(state: State) -> dict:
    S = state.data
    posts = Counter(p.get("type") for p in S["posts"].values())
    videos = Counter(v.get("kind") or v.get("final") or "pending" for v in S["videos"].values())
    done = Counter(k.split(":", 1)[0] for k in S["done"])
    out = {
        "accounts": sum(1 for a in S["accounts"].values() if a.get("verified")),
        "pages": sum(1 for p in S["pages"].values() if p.get("id")),
        "page_team_members": sum(len(p.get("team", {})) - 1 for p in S["pages"].values()),
        "groups": len(S["groups"]),
        "group_members": sum(len(g.get("members", [])) for g in S["groups"].values()),
        "posts_total": len(S["posts"]),
        "posts_by_type": dict(posts),
        "videos": dict(videos),
        "listings": len(S["listings"]),
        "stories": len(S["stories"]),
        "friendships": done.get("friend", 0),
        "follows_user": done.get("follow", 0),
        "follows_page": done.get("follow-page", 0),
        "reactions": done.get("react", 0),
        "comments": done.get("comment", 0),
        "shares": done.get("share", 0),
        "saves": done.get("save", 0),
        "hides": done.get("hide", 0),
        "reel_views": done.get("view", 0),
        "listing_views": done.get("listing-view", 0),
        "listing_saves": done.get("listing-save", 0),
        "story_views": done.get("story-seen", 0),
        "failures": len(S["failures"]),
        "failure_kinds": dict(
            Counter(f["what"].split(" ")[0].split(":")[0] for f in S["failures"])
        ),
    }
    return out


def dry_run(cat: Catalog, args) -> None:
    print(f"images usable: {len(cat.images)}")
    extra = sum(1 for i in cat.images if i.topic.startswith("x:"))
    print(f"  of them for the extra pass: {extra}")
    print("  by topic:", dict(Counter(i.topic for i in cat.images)))
    print(f"videos usable: {len(cat.videos)}")
    print("  by topic:", dict(Counter(v.topic for v in cat.videos)))
    guess = Counter()
    for v in cat.videos:
        v.probe = probe_video(v.path)
        if v.probe.get("duration", 0) > MAX_VIDEO_SECONDS:
            guess["too_long_for_media"] += 1
        else:
            guess[local_reel_guess(v.probe)] += 1
    print("  local ffprobe guess (the server decides):", dict(guess))
    print(f"  with view/reaction counters: {sum(1 for v in cat.videos if v.metrics)}")
    print(f"menu rows (xlsx): {len(cat.menus)}")
    print(f"skipped files: {len(cat.skipped)}")
    for reason, n in Counter(r for _, r in cat.skipped).most_common():
        print(f"  {n:4d}  {reason}")
    if args.verbose:
        for name, reason in cat.skipped:
            print(f"    - {name}  [{reason}]")
        for v in cat.videos:
            print(
                f"    video [{v.topic}] {local_reel_guess(v.probe)} {v.metrics} :: {v.caption[:70]}"
            )
    print(f"\naccounts planned: {args.accounts}, pages: {len(PAGES)}, groups: {len(GROUPS)}")


def check_target(api: str, allow_remote: bool) -> None:
    host = (urllib.parse.urlparse(api).hostname or "").lower()
    local = host in LOCAL_HOSTS or host.endswith((".localhost", ".local", ".test"))
    if local:
        return
    if not allow_remote:
        raise SystemExit(f"refusing to seed {host}: only a local/dev API unless --allow-remote")
    print(
        "WARNING: seeding a non-local server. The source media (news clips, recitations, "
        "product photos) belong to their owners; publishing them on a public server needs "
        "their permission. Use a private staging stack only.",
        file=sys.stderr,
    )
    time.sleep(5)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument(
        "--source",
        action="append",
        required=True,
        help="media tree (repeatable); PATH=topic sets the topic of its loose files",
    )
    ap.add_argument("--api", default=DEFAULT_API)
    ap.add_argument("--mailpit", default=DEFAULT_MAILPIT, help="Mailpit API, for verification")
    ap.add_argument("--accounts", type=int, default=120)
    ap.add_argument("--password", default=DEFAULT_PASSWORD, help="password of every seed account")
    ap.add_argument("--dry-run", action="store_true", help="scan and plan, no network")
    ap.add_argument("--limit", type=int, default=0, help="cap each content phase (quick trials)")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--pace", type=float, default=0.0, help="seconds to sleep before each call")
    ap.add_argument(
        "--max-transcoding", type=int, default=2, help="videos waiting for the transcoder at once"
    )
    ap.add_argument("--transcode-timeout", type=int, default=3600)
    ap.add_argument(
        "--phases", default="graph,pages,groups,posts,videos,listings,stories,engagement"
    )
    ap.add_argument("--state-dir", default=str(REPO / ".seed-state"))
    ap.add_argument("--namespace", default="tara-seed-v1", help="idempotency-key namespace")
    ap.add_argument("--allow-remote", action="store_true")
    ap.add_argument("--report", action="store_true", help="print counts from the manifest")
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args(argv)
    args.phases = set(args.phases.split(","))
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    state = State(Path(args.state_dir))
    if args.report:
        print(json.dumps(report(state), ensure_ascii=False, indent=2))
        return 0
    catalog = scan_sources(args.source)
    if args.dry_run:
        dry_run(catalog, args)
        return 0
    check_target(args.api, args.allow_remote)
    if not HAVE_PIL:
        log("Pillow not installed: AVIF images are skipped and avatars are pool photos only")
    log(
        f"sources: {len(catalog.images)} images, {len(catalog.videos)} videos, "
        f"{len(catalog.menus)} menu rows, {len(catalog.skipped)} skipped files"
    )
    seeder = Seeder(args, catalog, state)
    started = time.time()
    try:
        seeder.run()
    finally:
        state.save(force=True)
        log(
            f"finished in {(time.time() - started) / 60:.1f} min; "
            f"requests {dict(seeder.api.requests)}"
        )
        print(json.dumps(report(state), ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
