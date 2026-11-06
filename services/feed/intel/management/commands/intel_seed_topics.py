"""Seed the topic taxonomy and its aliases (04 WP 6.1). Additive and idempotent.

    manage.py intel_seed_topics [--min-uses 5] [--json]

Topics come from ``intel.topics.taxonomy`` (about 40, ar and en labels; politics,
religion and Quran seeded ``sensitive``). Aliases: the curated hashtags, the page
categories in use, the 18 group categories, the 8 market categories and the keyword
lexicons ``intel/topics/lexicons/{ar,en}.txt``. Existing rows are never changed or
deleted: a topic or alias already stored is left as it is.

It then queries the hashtags with at least ``--min-uses`` live uses **at run time**
and reports each as mapped (to which topic) or explicitly unmapped (with the reason
in ``taxonomy.UNMAPPED``); any other is listed as ``uncurated`` so staff see it.
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import connection, transaction

from intel.models import Topic, TopicAlias
from intel.topics import classify, taxonomy

LEXICONS = Path(__file__).resolve().parents[2] / "topics" / "lexicons"


def lexicon_rows() -> list[tuple[str, str, str, bool]]:
    """``(lang, value_norm, slug, strong)`` from the lexicon files, first wins."""
    out, seen = [], set()
    for lang in ("ar", "en"):
        for line in (LEXICONS / f"{lang}.txt").read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            value = " ".join(classify.tokens(parts[0]))
            if not value or value in seen:
                continue
            seen.add(value)
            out.append(
                (lang, value, parts[1].strip(), len(parts) > 2 and parts[2].strip() == "strong")
            )
    return out


def seed() -> dict:
    counts = {"topics": 0, "aliases": 0}
    with transaction.atomic():
        for slug, ar, en, _parent, sensitive, minors in taxonomy.TOPICS:
            _, made = Topic.objects.get_or_create(
                slug=slug,
                defaults={
                    "label_ar": ar,
                    "label_en": en,
                    "sensitive": sensitive,
                    "allow_minors": minors,
                },
            )
            counts["topics"] += int(made)
        ids = dict(Topic.objects.values_list("slug", "id"))
        for slug, _ar, _en, parent, _s, _m in taxonomy.TOPICS:
            if parent and ids.get(parent):
                Topic.objects.filter(slug=slug, parent_id__isnull=True).update(
                    parent_id=ids[parent]
                )

        def alias(kind, value, slug, *, lang="any", strong=False):
            if not slug or slug not in ids or not value:
                return
            _, made = TopicAlias.objects.get_or_create(
                kind=kind,
                value_norm=value[:80],
                defaults={"topic_id": ids[slug], "lang": lang, "strong": strong},
            )
            counts["aliases"] += int(made)

        for tag, slug in taxonomy.HASHTAGS.items():
            alias("hashtag", taxonomy.norm(tag), slug)
        for value, slug in taxonomy.PAGE_CATEGORIES.items():
            alias("page_category", taxonomy.norm(value), slug)
        for value, slug in taxonomy.GROUP_CATEGORIES.items():
            alias("group_category", value, slug)
        for value, slug in taxonomy.MARKET_CATEGORIES.items():
            alias("market_category", value, slug)
        for lang, value, slug, strong in lexicon_rows():
            alias("keyword", value, slug, lang=lang, strong=strong)
    classify.clear_cache()
    return counts


def hashtag_report(min_uses: int) -> dict:
    """Every live hashtag with >= ``min_uses`` uses: mapped, unmapped or uncurated."""
    with connection.cursor() as cur:
        cur.execute(
            "SELECT h, count(*) FROM (SELECT unnest(hashtags) AS h FROM intel_content_ref "
            "WHERE state = 'live') x GROUP BY h HAVING count(*) >= %s ORDER BY 2 DESC, 1",
            [min_uses],
        )
        rows = cur.fetchall()
        cur.execute(
            "SELECT a.value_norm, t.slug FROM intel_topic_alias a "
            "JOIN intel_topic t ON t.id = a.topic_id WHERE a.kind = 'hashtag'"
        )
        mapped = dict(cur.fetchall())
    unmapped_norm = {taxonomy.norm(k): v for k, v in taxonomy.UNMAPPED.items()}
    out = {"mapped": {}, "unmapped": {}, "uncurated": []}
    for tag, n in rows:
        key = taxonomy.norm(tag)
        if key in mapped:
            out["mapped"][tag] = {"topic": mapped[key], "uses": n}
        elif key in unmapped_norm:
            out["unmapped"][tag] = {"reason": unmapped_norm[key], "uses": n}
        else:
            out["uncurated"].append({"tag": tag, "uses": n})
    return out


class Command(BaseCommand):
    help = "Seed intel_topic and intel_topic_alias (WP 6.1); report hashtag coverage."

    def add_arguments(self, parser):
        parser.add_argument("--min-uses", type=int, default=5)
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **opts):
        counts = seed()
        report = hashtag_report(opts["min_uses"])
        out = {"created": counts, "hashtags": report}
        if opts["json"]:
            self.stdout.write(json.dumps(out, ensure_ascii=False))
            return
        self.stdout.write(f"created {counts['topics']} topics, {counts['aliases']} aliases")
        self.stdout.write(
            f"hashtags with >= {opts['min_uses']} uses: {len(report['mapped'])} mapped, "
            f"{len(report['unmapped'])} unmapped, {len(report['uncurated'])} uncurated"
        )
        for item in report["uncurated"]:
            self.stdout.write(f"  uncurated: {item['tag']} ({item['uses']})")
