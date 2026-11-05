"""WP 3.1: the content language of a post, from its letters only (no model, no AI)."""

import pytest

from intel.topics import language


@pytest.mark.parametrize(
    "text",
    [
        "صباح الخير يا جماعة، النهارده الجو حلو جدا في القاهرة",
        "الحمد لله على كل حال 🙏 #مصر https://example.com/x",
    ],
)
def test_arabic(text):
    assert language.detect(text) == "ar"


@pytest.mark.parametrize(
    "text",
    [
        "Good morning everyone, the weather in Cairo is lovely today",
        "Check out my new video!! 🔥🔥 #travel @friend https://example.com/v",
    ],
)
def test_english(text):
    assert language.detect(text) == "en"


def test_mixed_arabic_and_english():
    assert language.detect("النهارده عندنا اجتماع مهم about the new release") == "mixed"


@pytest.mark.parametrize(
    "text",
    [
        None,
        "",
        "😂😂😂 !!! 123",
        "ok 👍",  # too few letters
        "#hashtag @mention https://example.com/long/path/only",
        "Привет всем, как у вас дела сегодня",  # another script
    ],
)
def test_undetermined(text):
    assert language.detect(text) == "und"


def test_arabizi_is_documented_as_english():
    """Arabic in Latin letters and digits is Latin text: ``en``, never ``ar``. A
    known limit of a letters-only rule (02 section 14)."""
    assert language.detect("ana 3ayez a7ki m3ak bokra el sob7") == "en"
    assert language.detect("ezayak ya basha, 3amel eh el naharda?") == "en"


def test_every_answer_is_a_known_code():
    for text in ("abc def ghi", "مرحبا بكم جميعا", "x", "مرحبا hello"):
        assert language.detect(text) in language.LANGS
