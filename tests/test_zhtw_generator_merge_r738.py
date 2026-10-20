"""R738 — ``scripts/gen_zhtw_from_zhcn.py`` keeps what is translated and derives clean text.

Why this exists
---------------
The release checklist ran the generator with ``--all``.  That re-derived every
zh-TW string from zh-CN and overwrote the files: 34 Web UI and 17 VS Code
strings that had been corrected by hand were lost, and the Simplified
characters the generator's table does not cover came back.  The derivation was
unsafe on its own as well:

* phrases were replaced one after another over the whole text, so a phrase's
  output could be rewritten by a later phrase or by itself (``尚未授予`` became
  ``尚尚未授予``);
* the one-character phrases ``块 -> 區塊`` and ``段 -> 區段`` fired inside other
  words and shipped in the VS Code zh-TW text (``模块`` -> ``模區塊``,
  ``一段代码`` -> ``一區段程式碼``);
* 40 characters used by the shipped zh-CN text had no table entry.

The generator now merges by default (existing zh-TW text is kept, only missing
keys are derived, ``--force`` overwrites), converts phrases in one
left-to-right pass, and the release checklist runs it with ``--check``.

Pattern: A (data invariant) + behaviour tests on temporary copies.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path
from types import ModuleType

import pytest

from tests.test_zhtw_locales_no_simplified_chars_r737 import (
    SIMPLIFIED_BUT_ENCODABLE_AS_BIG5,
    SIMPLIFIED_ONLY_PHRASES,
    _leaves,
    _shipped_zh_tw_text,
    doubled_conversion_artifacts,
    find_simplified_only,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "gen_zhtw_from_zhcn.py"
RELEASE_CHECKLIST = REPO_ROOT / "docs" / "release-checklist.md"

# Text no Traditional Chinese contains, and the rule that once produced it.
CONVERSION_ARTEFACTS = {
    "尚尚": "a phrase replaced inside its own output (未授予 on 尚未授予)",
    "模區塊": "the one-character phrase 块 -> 區塊 inside 模块 (the word is 模組)",
    "一區段": "the one-character phrase 段 -> 區段 inside 一段 (the word is 一段)",
    "階區段": "the same phrase inside 阶段 (the word is 階段)",
    "標准": "标 converted, 准 left behind (the word is 標準)",
}


@pytest.fixture(scope="module")
def gen() -> ModuleType:
    spec = importlib.util.spec_from_file_location("gen_zhtw_from_zhcn_r738", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", "utf-8")


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def pair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, gen: ModuleType
) -> tuple[Path, Path]:
    cn, tw = tmp_path / "zh-CN.json", tmp_path / "zh-TW.json"
    monkeypatch.setattr(gen, "_VARIANTS", {"web": (cn, tw)})
    return cn, tw


# -- the derivation is clean ------------------------------------------------------


@pytest.mark.parametrize("variant", ["web", "vscode"])
def test_fresh_derivation_of_the_shipped_zh_cn_text_is_clean(
    gen: ModuleType, variant: str
) -> None:
    source_path = gen._VARIANTS[variant][0]
    source = dict(_leaves(_read(source_path)))
    derived = {key: gen._convert_value(text) for key, text in source.items()}
    simplified = {
        key: found
        for key, text in derived.items()
        if (found := find_simplified_only(text))
    }
    artefacts = {
        key: [bad for bad in CONVERSION_ARTEFACTS if bad in text]
        for key, text in derived.items()
        if any(bad in text for bad in CONVERSION_ARTEFACTS)
    }
    assert simplified == {}, "the generator left Simplified-only text behind"
    assert artefacts == {}, "the generator produced a known conversion artefact"
    assert doubled_conversion_artifacts(derived, source) == []
    assert len(source) > 100, "the source must really have been read"


def test_shipped_zh_tw_text_has_no_known_conversion_artefact() -> None:
    offenders = [
        f"{source} :: {key}: {bad} ({CONVERSION_ARTEFACTS[bad]}) in {text!r}"
        for source, key, text in _shipped_zh_tw_text()
        for bad in CONVERSION_ARTEFACTS
        if bad in text
    ]
    assert offenders == [], "\n".join(offenders)


def test_generator_converts_every_character_and_phrase_the_detector_names(
    gen: ModuleType,
) -> None:
    unconverted = [
        char
        for char in sorted(SIMPLIFIED_BUT_ENCODABLE_AS_BIG5)
        if gen._convert_value(char) == char
    ]
    leftovers = [
        text
        for text in [*SIMPLIFIED_BUT_ENCODABLE_AS_BIG5, *SIMPLIFIED_ONLY_PHRASES]
        if find_simplified_only(gen._convert_value(text))
    ]
    assert unconverted == [], f"no CHAR_MAP_v2 entry for: {''.join(unconverted)}"
    assert leftovers == [], f"still Simplified after conversion: {leftovers}"


def test_table_targets_hold_no_simplified_only_text(gen: ModuleType) -> None:
    offenders = [
        f"{table} {key!r} -> {value!r}: {find_simplified_only(value)}"
        for table, entries in (
            ("PHRASE_MAP", gen.PHRASE_MAP),
            ("CHAR_MAP_v2", gen.CHAR_MAP_v2),
        )
        for key, value in entries.items()
        if find_simplified_only(value)
    ]
    assert offenders == []


def test_one_character_phrases_only_rewrite_to_one_character(gen: ModuleType) -> None:
    # A one-character key fires inside every word that contains it, so it may
    # only convert the character (节 -> 節), never add characters (块 -> 區塊
    # turned 模块 into 模區塊).
    offenders = {
        key: value
        for key, value in gen.PHRASE_MAP.items()
        if len(key) == 1 and len(value) != 1
    }
    assert offenders == {}


# -- the phrase pass --------------------------------------------------------------


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("尚未授予通知权限", "尚未授予通知權限"),
        ("未授予通知权限", "尚未授予通知權限"),
        ("设置模块不可用", "設定模組無法使用"),
        ("先复制一段代码", "先複製一段程式碼"),
        ("循环阶段", "循環階段"),
        ("完成标准", "完成標準"),
        ("格式异常", "格式異常"),
        ("查看日志", "查看日誌"),
        ("代码块", "程式碼區塊"),
    ],
)
def test_derivation_examples(gen: ModuleType, source: str, expected: str) -> None:
    assert gen._convert_value(source) == expected


def test_phrase_output_is_never_scanned_again(
    gen: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gen, "PHRASE_MAP", {"ab": "bc", "bc": "X", "q": "qq"})
    assert gen._apply_phrase_map("ab") == "bc"
    assert gen._apply_phrase_map("abc") == "bcc"
    assert gen._apply_phrase_map("q") == "qq"


def test_phrases_match_longest_first_from_the_left(
    gen: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        gen, "PHRASE_MAP", {"a": "1", "ab": "2", "abc": "3", "bcd": "4"}
    )
    assert gen._apply_phrase_map("abcd") == "3d"
    assert gen._apply_phrase_map("abd") == "2d"
    assert gen._apply_phrase_map("xa") == "x1"
    assert gen._apply_phrase_map("") == ""
    monkeypatch.setattr(gen, "PHRASE_MAP", {"ab": "2", "bcd": "4"})
    assert gen._apply_phrase_map("abcd") == "2cd"


def test_every_phrase_converts_to_its_own_target(gen: ModuleType) -> None:
    wrong = {
        key: gen._apply_phrase_map(key)
        for key, value in gen.PHRASE_MAP.items()
        if gen._apply_phrase_map(key) != value
    }
    assert wrong == {}


# -- merge behaviour --------------------------------------------------------------


def test_merge_keeps_translated_text_and_derives_only_missing_keys(
    gen: ModuleType, pair: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    cn, tw = pair
    _write(cn, {"a": "设置", "group": {"c": "文件", "d": "加载失败"}})
    _write(tw, {"_meta": {"note": "mine"}, "a": "手改設定", "group": {"c": "手改檔案"}})
    assert gen.main([]) == 0
    assert _read(tw) == {
        "_meta": {"note": "mine"},
        "a": "手改設定",
        "group": {"c": "手改檔案", "d": "載入失敗"},
    }
    out = capsys.readouterr().out
    assert "保留 2 条，派生 1 条，删除 0 条" in out
    assert "+ group.d" in out


def test_merge_drops_keys_zh_cn_no_longer_has(
    gen: ModuleType, pair: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    cn, tw = pair
    _write(cn, {"a": "设置", "group": {"c": "文件"}})
    _write(
        tw,
        {
            "_meta": {},
            "a": "手改設定",
            "old": "舊",
            "group": {"c": "手改檔案", "gone": "沒了"},
        },
    )
    assert gen.main([]) == 0
    assert _read(tw) == {"_meta": {}, "a": "手改設定", "group": {"c": "手改檔案"}}
    out = capsys.readouterr().out
    assert "- old" in out and "- group.gone" in out


def test_merge_follows_the_key_order_of_zh_cn(
    gen: ModuleType, pair: tuple[Path, Path]
) -> None:
    cn, tw = pair
    _write(cn, {"z": "设置", "a": "文件", "m": {"y": "保存", "b": "复制"}})
    _write(tw, {"_meta": {}, "a": "乙", "m": {"b": "丁", "y": "丙"}, "z": "甲"})
    assert gen.main([]) == 0
    result = _read(tw)
    assert result == {"_meta": {}, "z": "甲", "a": "乙", "m": {"y": "丙", "b": "丁"}}
    assert list(result) == ["_meta", "z", "a", "m"]
    assert list(result["m"]) == ["y", "b"]


def test_merge_keeps_the_existing_meta_and_adds_one_when_missing(
    gen: ModuleType, pair: tuple[Path, Path]
) -> None:
    cn, tw = pair
    _write(cn, {"a": "设置"})
    _write(tw, {"_meta": {"derivedFrom": "zh-CN", "note": "hand"}, "a": "設定"})
    gen.main([])
    assert _read(tw)["_meta"] == {"derivedFrom": "zh-CN", "note": "hand"}

    _write(tw, {"a": "設定"})
    gen.main([])
    assert _read(tw)["_meta"]["derivedFrom"] == "zh-CN"
    assert next(iter(_read(tw))) == "_meta"


def test_merge_derives_again_when_the_kind_of_value_changed(
    gen: ModuleType, pair: tuple[Path, Path]
) -> None:
    cn, tw = pair
    _write(
        cn, {"was_text": {"x": "设置"}, "was_group": "文件", "list": ["设置", "文件"]}
    )
    _write(tw, {"_meta": {}, "was_text": "文字", "was_group": {"x": 1}, "list": ["一"]})
    gen.main([])
    assert _read(tw) == {
        "_meta": {},
        "was_text": {"x": "設定"},
        "was_group": "檔案",
        "list": ["設定", "檔案"],
    }


def test_second_run_changes_nothing_and_leaves_the_file_alone(
    gen: ModuleType, pair: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    cn, tw = pair
    _write(cn, {"a": "设置", "b": "文件"})
    gen.main([])
    first = tw.read_bytes()
    old = 1_000_000_000
    os.utime(tw, ns=(old, old))
    capsys.readouterr()

    assert gen.main([]) == 0

    assert tw.read_bytes() == first
    assert tw.stat().st_mtime_ns == old, "an unchanged file must not be rewritten"
    assert "已是最新" in capsys.readouterr().out


def test_force_derives_everything_again_and_discards_hand_edits(
    gen: ModuleType, pair: tuple[Path, Path]
) -> None:
    cn, tw = pair
    _write(cn, {"a": "设置"})
    _write(tw, {"_meta": {"note": "mine"}, "a": "手改", "old": "舊"})
    assert gen.main(["--force"]) == 0
    result = _read(tw)
    assert result["a"] == "設定"
    assert "old" not in result
    assert result["_meta"]["derivedFrom"] == "zh-CN"


def test_a_missing_zh_tw_file_is_created_from_zh_cn(
    gen: ModuleType, pair: tuple[Path, Path]
) -> None:
    cn, tw = pair
    _write(cn, {"a": "设置"})
    assert not tw.exists()
    assert gen.main([]) == 0
    assert _read(tw)["a"] == "設定"
    assert _read(tw)["_meta"]["source"] == "scripts/gen_zhtw_from_zhcn.py"


@pytest.mark.parametrize("broken", ["{ not json", "[1, 2]"])
def test_an_unreadable_zh_tw_file_is_reported_and_left_alone(
    gen: ModuleType,
    pair: tuple[Path, Path],
    capsys: pytest.CaptureFixture[str],
    broken: str,
) -> None:
    cn, tw = pair
    _write(cn, {"a": "设置"})
    tw.write_text(broken, encoding="utf-8")
    with pytest.raises(SystemExit) as raised:
        gen.main([])
    assert raised.value.code == 2
    assert tw.read_text(encoding="utf-8") == broken
    assert "--force" in capsys.readouterr().out

    assert gen.main(["--force"]) == 0
    assert _read(tw)["a"] == "設定"


@pytest.mark.parametrize(
    ("zh_cn", "zh_tw", "reported"),
    [
        ({"a": "设置", "b": "文件"}, {"a": "設定"}, ["b"]),
        ({"a": "设置"}, {"a": "設定", "extra": "多"}, ["extra"]),
        ({"a": "设置", "g": {"x": "文件"}}, {"a": "設定", "g": {}}, ["g.x"]),
        ({"a": "设置", "g": {}}, {"a": "設定", "g": {"y": "多"}}, ["g.y"]),
        ({"a": {"x": "设置"}}, {"a": "字串"}, ["a"]),
    ],
)
def test_check_reports_each_kind_of_drift_and_writes_nothing(
    gen: ModuleType,
    pair: tuple[Path, Path],
    capsys: pytest.CaptureFixture[str],
    zh_cn: dict,
    zh_tw: dict,
    reported: list[str],
) -> None:
    cn, tw = pair
    _write(cn, zh_cn)
    _write(tw, {"_meta": {}, **zh_tw})
    before = tw.read_bytes()

    assert gen.main(["--check"]) == 1

    out = capsys.readouterr().out
    assert all(f"- {key}" in out for key in reported), out
    assert tw.read_bytes() == before


def test_check_passes_when_the_key_sets_match(
    gen: ModuleType, pair: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    cn, tw = pair
    _write(cn, {"a": "设置", "group": {"c": "文件"}})
    _write(tw, {"_meta": {}, "a": "手改", "group": {"c": "檔案"}})
    assert gen.main(["--check"]) == 0
    assert "同构" in capsys.readouterr().out


def test_check_fails_when_the_zh_tw_file_does_not_exist(
    gen: ModuleType, pair: tuple[Path, Path]
) -> None:
    cn, tw = pair
    _write(cn, {"a": "设置"})
    assert gen.main(["--check"]) == 1
    assert not tw.exists()


def test_check_and_force_cannot_be_combined(
    gen: ModuleType, pair: tuple[Path, Path]
) -> None:
    cn, _tw = pair
    _write(cn, {"a": "设置"})
    with pytest.raises(SystemExit) as raised:
        gen.main(["--check", "--force"])
    assert raised.value.code == 2


def test_all_covers_every_variant(
    gen: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    variants = {
        name: (tmp_path / f"{name}-cn.json", tmp_path / f"{name}-tw.json")
        for name in ("web", "vscode")
    }
    for cn, _tw in variants.values():
        _write(cn, {"a": "设置"})
    monkeypatch.setattr(gen, "_VARIANTS", variants)
    assert gen.main(["--all"]) == 0
    assert all(_read(tw)["a"] == "設定" for _cn, tw in variants.values())


# -- the shipped files ------------------------------------------------------------


@pytest.mark.parametrize("variant", ["web", "vscode"])
def test_default_run_on_copies_of_the_shipped_files_changes_nothing(
    gen: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    variant: str,
) -> None:
    real_cn, real_tw = gen._VARIANTS[variant]
    cn, tw = tmp_path / "zh-CN.json", tmp_path / "zh-TW.json"
    shutil.copyfile(real_cn, cn)
    shutil.copyfile(real_tw, tw)
    monkeypatch.setattr(gen, "_VARIANTS", {variant: (cn, tw)})

    assert gen.main(["--variant", variant]) == 0

    assert tw.read_bytes() == real_tw.read_bytes()
    assert "已是最新" in capsys.readouterr().out


@pytest.mark.parametrize("variant", ["web", "vscode"])
def test_check_passes_on_the_shipped_files(gen: ModuleType, variant: str) -> None:
    assert gen._check(variant) == 0


def test_release_checklist_runs_the_generator_without_overwriting() -> None:
    lines = [
        line
        for line in RELEASE_CHECKLIST.read_text(encoding="utf-8").splitlines()
        if "gen_zhtw_from_zhcn.py" in line
    ]
    assert lines, "the release checklist no longer mentions the generator"
    assert all("--check" in line for line in lines), lines
