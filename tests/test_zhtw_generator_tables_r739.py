"""R739 — the zh-TW generator's per-character table holds only entries that can match.

Why this exists
---------------
``CHAR_MAP_v2`` is read one character at a time (``_apply_char_map``), yet 232
of its 556 entries had two to four characters (``实际``, ``贡献者``,
``赖账不还``...).  They could never match.  Behind them the table lacked 34
single characters those words need (``际``, ``业``, ``状``, ``账``...), so a new
zh-CN string with ``实际`` came out as ``實际`` and was caught only afterwards
by the Simplified-text test; and the entries meant as word-level spellings
(``赞助`` is ``贊助`` in zh-TW, ``细致`` is ``細緻``, while ``一致`` keeps its
``致``) were never applied.

The dead entries are gone, the conversions they described now come out of the
generator, and the table is guarded so that a word cannot be put there again.

Pattern: A (data invariant) + behaviour of the real generator.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "gen_zhtw_from_zhcn.py"

INTENDED_WORDS = [
    ("实际", "實際"),
    ("实践", "實踐"),
    ("总额", "總額"),
    ("态势", "態勢"),
    ("态势感知", "態勢感知"),
    ("动画", "動畫"),
    ("动员", "動員"),
    ("状况", "狀況"),
    ("细节", "細節"),
    ("细致", "細緻"),
    ("辞职", "辭職"),
    ("辩驳", "辯駁"),
    ("辩诬", "辯誣"),
    ("毕业", "畢業"),
    ("尽职", "盡職"),
    ("贝壳", "貝殼"),
    ("财产", "財產"),
    ("贞节", "貞節"),
    ("负责", "負責"),
    ("负担", "負擔"),
    ("贡献", "貢獻"),
    ("贡献者", "貢獻者"),
    ("贫穷", "貧窮"),
    ("贱视", "賤視"),
    ("贵宾", "貴賓"),
    ("贺词", "賀詞"),
    ("贺礼", "賀禮"),
    ("贺岁", "賀歲"),
    ("贺寿", "賀壽"),
    ("贿赂", "賄賂"),
    ("赋税", "賦稅"),
    ("赋闲", "賦閒"),
    ("赏罚", "賞罰"),
    ("赔偿", "賠償"),
    ("赔礼", "賠禮"),
    ("赖账", "賴帳"),
    ("赖账不还", "賴帳不還"),
    ("赞扬", "讚揚"),
    ("赞同", "贊同"),
    ("赞成", "贊成"),
    ("赞助", "贊助"),
    ("赞颂", "讚頌"),
    ("赠书", "贈書"),
]

CARRIED_OVER_SIMPLIFIED = (
    "业书产偿势员壳宾寿岁扬担状献画礼税穷罚职节视词诬责账赂践还闲际颂额驳栏"
)
CARRIED_OVER_TRADITIONAL = (
    "業書產償勢員殼賓壽歲揚擔狀獻畫禮稅窮罰職節視詞誣責帳賂踐還閒際頌額駁欄"
)

WORDS_WHOSE_SPELLING_DEPENDS_ON_THE_WORD = [
    ("一致", "一致"),
    ("致辞", "致辭"),
    ("致谢", "致謝"),
    ("赞美", "讚美"),
    ("数据", "資料"),
]


@pytest.fixture(scope="module")
def gen() -> ModuleType:
    spec = importlib.util.spec_from_file_location("gen_zhtw_from_zhcn_r739", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _convert(gen: ModuleType, text: str) -> str:
    return gen._convert_value(text)


def test_every_char_map_key_is_a_single_character(gen: ModuleType) -> None:
    words = sorted(key for key in gen.CHAR_MAP_v2 if len(key) != 1)

    assert words == [], (
        "the table is read one character at a time: put words in PHRASE_MAP"
    )
    assert len(gen.CHAR_MAP_v2) > 300, "the table must really have been read"


def test_every_char_map_entry_turns_one_character_into_another_one(
    gen: ModuleType,
) -> None:
    bad = {
        key: value
        for key, value in gen.CHAR_MAP_v2.items()
        if len(value) != 1 or value == key
    }

    assert bad == {}


def test_every_char_map_value_is_a_traditional_form(gen: ModuleType) -> None:
    not_big5 = {}
    for key, value in gen.CHAR_MAP_v2.items():
        try:
            value.encode("big5")
        except UnicodeEncodeError:
            not_big5[key] = value

    assert not_big5 == {}, (
        "Big5 cannot encode these targets: still Simplified, or a typo"
    )


def test_a_character_is_defined_in_one_table_only(gen: ModuleType) -> None:
    both = sorted(
        key for key in gen.PHRASE_MAP if len(key) == 1 and key in gen.CHAR_MAP_v2
    )

    assert both == []


@pytest.mark.parametrize(("simplified", "traditional"), INTENDED_WORDS)
def test_the_formerly_dead_entries_now_convert_as_intended(
    gen: ModuleType, simplified: str, traditional: str
) -> None:
    assert _convert(gen, simplified) == traditional


@pytest.mark.parametrize(
    ("simplified", "traditional"), WORDS_WHOSE_SPELLING_DEPENDS_ON_THE_WORD
)
def test_a_character_with_two_spellings_is_not_forced_into_one(
    gen: ModuleType, simplified: str, traditional: str
) -> None:
    assert _convert(gen, simplified) == traditional


def test_every_character_the_dead_entries_needed_is_in_the_table(
    gen: ModuleType,
) -> None:
    assert len(CARRIED_OVER_SIMPLIFIED) == len(CARRIED_OVER_TRADITIONAL) == 35

    converted = "".join(_convert(gen, char) for char in CARRIED_OVER_SIMPLIFIED)

    assert converted == CARRIED_OVER_TRADITIONAL


def test_a_sentence_mixing_the_new_characters_is_converted_whole(
    gen: ModuleType,
) -> None:
    text = "实际业务状况的责任由负责人承担，细致的书面记录"

    converted = _convert(gen, text)

    assert converted == "實際業務狀況的責任由負責人承擔，細緻的書面記錄"
