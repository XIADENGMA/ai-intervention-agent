"""R737 — the zh-TW text the project ships contains no Simplified-only characters.

Why this exists
---------------
``zh-TW.json`` (Web UI and VS Code extension) was derived from ``zh-CN.json`` by
``scripts/gen_zhtw_from_zhcn.py`` and then edited by hand.  The generator's
character table is partial, and nothing checked the result beyond a handful of
spot checks (``test_feat_zhtw_locale.py``), so Simplified characters stayed in
the text people read: ``請换一個檔案``, ``無法解码``, ``路径``, ``帮助``, ``详情``,
``診断``, ``日志`` and more (18 strings in the Web UI, 9 in the extension).  The
generator also turned ``尚未授予`` into ``尚尚未授予`` because its phrase
``未授予 -> 尚未授予`` matches inside the word it produces.

How Simplified-only text is recognised
--------------------------------------
* Python's ``big5`` codec is Taiwan's standard Traditional character set.  It
  cannot encode about 3750 of the 3980 characters that OpenCC converts, so
  "an ideograph ``big5`` refuses" is a precise test for "never valid in
  Traditional text".
* The other ~230 convertible characters are mostly valid in both scripts
  (``只 台 后 里 干 面 谷 表 复`` ...) and must stay allowed.  A short, curated
  supplement names the few that Big5 keeps only as legacy variants but that
  no Traditional text uses (``触 坏 万 与 机`` ...).
* Some Simplified words are spelled entirely with characters valid in both
  scripts (``日志`` for ``日誌``, ``复制`` for ``複製``, ``然后`` for ``然後``);
  a short phrase list covers the ones the UI is likely to need.
* A doubled ideograph (``尚尚``) is a generator artefact unless the zh-CN
  source has a doubled ideograph there too (``谢谢`` -> ``謝謝``).

Scope: both ``zh-TW.json`` files, the server's own zh-TW message table
(``i18n._MESSAGES``) and the inline zh-TW block of the offline page.

Pattern: A (data invariant) with negative self-checks of the detector.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path

import pytest

from ai_intervention_agent import i18n

REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_LOCALES = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "locales"
VSCODE_LOCALES = REPO_ROOT / "packages" / "vscode" / "locales"
OFFLINE_PAGE = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "templates" / "offline.html"
)

# Simplified forms that Python's ``big5`` codec still encodes (legacy variants)
# but that Traditional text never uses.  Only add a character after checking
# that it is not a valid Traditional character in its own right.
SIMPLIFIED_BUT_ENCODABLE_AS_BIG5 = frozenset(
    "触坏万与价优体儿党厂吨听圣夸宁岭异忏怀怜惊愿扰挂据晒机杰极构柜气么丰云"
    "确种网离适胜荐虫蚕肮"
)

# Simplified words whose every character is valid in Traditional text, so the
# character rules cannot see them.
SIMPLIFIED_ONLY_PHRASES = (
    "日志",
    "里面",
    "后面",
    "以后",
    "之后",
    "然后",
    "最后",
    "前后",
    "复制",
    "复原",
    "恢复",
    "重复",
    "回复",
    "制作",
    "制造",
)

# Characters that look Simplified but are ordinary Traditional text too; the
# detector must never report them (pinned by a test, so nobody "fixes" the
# detector by adding one of them to the lists above).
VALID_IN_BOTH_SCRIPTS = frozenset("只台后里干面谷表复准于余制向并系范采志合同周")


def _is_ideograph(char: str) -> bool:
    return "\u4e00" <= char <= "\u9fff"


def _big5_refuses(char: str) -> bool:
    try:
        char.encode("big5")
    except UnicodeEncodeError:
        return True
    return False


def find_simplified_only(text: str) -> list[str]:
    """Simplified-only characters of ``text`` (distinct, in order), then phrases."""
    found: list[str] = []
    for char in text:
        if not _is_ideograph(char) or char in found:
            continue
        if _big5_refuses(char) or char in SIMPLIFIED_BUT_ENCODABLE_AS_BIG5:
            found.append(char)
    found.extend(phrase for phrase in SIMPLIFIED_ONLY_PHRASES if phrase in text)
    return found


def _doubled_ideographs(text: str) -> list[str]:
    return [match.group(0) for match in re.finditer(r"([\u4e00-\u9fff])\1", text)]


def doubled_conversion_artifacts(
    traditional: dict[str, str], simplified: dict[str, str]
) -> list[str]:
    """Keys whose zh-TW text has more doubled ideographs than its zh-CN source."""
    return [
        f"{key}: {_doubled_ideographs(text)} in {text!r}"
        for key, text in traditional.items()
        if len(_doubled_ideographs(text))
        > len(_doubled_ideographs(simplified.get(key, "")))
    ]


def _leaves(node: object, path: str = "") -> Iterator[tuple[str, str]]:
    """``(key path, text)`` of every string leaf."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _leaves(value, f"{path}.{key}" if path else str(key))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _leaves(value, f"{path}[{index}]")
    elif isinstance(node, str):
        yield path, node


def _load_leaves(path: Path) -> dict[str, str]:
    return dict(_leaves(json.loads(path.read_text(encoding="utf-8"))))


def _offline_page_block(language: str) -> str:
    """The inline ``"<language>": { ... }`` message block of the offline page."""
    page = OFFLINE_PAGE.read_text(encoding="utf-8")
    match = re.search(rf'"{re.escape(language)}":\s*\{{(.*?)\n\s*\}}', page, re.DOTALL)
    assert match, f"offline page has no {language} message block"
    return match.group(1)


def _paired_sources() -> list[tuple[str, dict[str, str], dict[str, str]]]:
    """``(label, zh-TW text by key, zh-CN text by key)`` for each paired source."""
    return [
        (
            "web locale",
            _load_leaves(WEB_LOCALES / "zh-TW.json"),
            _load_leaves(WEB_LOCALES / "zh-CN.json"),
        ),
        (
            "vscode locale",
            _load_leaves(VSCODE_LOCALES / "zh-TW.json"),
            _load_leaves(VSCODE_LOCALES / "zh-CN.json"),
        ),
        (
            "server messages",
            dict(i18n._MESSAGES["zh-TW"]),
            dict(i18n._MESSAGES["zh-CN"]),
        ),
    ]


def _shipped_zh_tw_text() -> list[tuple[str, str, str]]:
    """``(source, key, text)`` for everything the project ships as zh-TW."""
    rows = [
        (label, key, text)
        for label, traditional, _simplified in _paired_sources()
        for key, text in traditional.items()
    ]
    rows.append(("offline page", "inline block", _offline_page_block("zh-TW")))
    return rows


def test_shipped_zh_tw_text_has_no_simplified_only_characters() -> None:
    offenders = [
        f"{source} :: {key}: {' '.join(found)} in {text!r}"
        for source, key, text in _shipped_zh_tw_text()
        if (found := find_simplified_only(text))
    ]
    assert offenders == [], (
        "Simplified text in zh-TW (fix the string; if Python's Big5 codec "
        "wrongly refuses a real Traditional character, teach the detector):\n"
        + "\n".join(offenders)
    )


def test_zh_tw_text_has_no_doubled_ideograph_the_zh_cn_source_lacks() -> None:
    offenders = [
        f"{label} :: {row}"
        for label, traditional, simplified in _paired_sources()
        for row in doubled_conversion_artifacts(traditional, simplified)
    ]
    assert offenders == [], (
        "A doubled character that zh-CN does not have is a conversion artefact "
        "(a phrase replaced inside its own output):\n" + "\n".join(offenders)
    )


# -- the detector itself ---------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("请换一個檔案", ["请", "换"]),
        ("無法解码此音訊檔案", ["码"]),
        ("診断訊息与日志", ["断", "与", "日志"]),
        ("已触發測試通知", ["触"]),
        ("可能為空或已损坏", ["损", "坏"]),
        ("請先复制再恢复", ["复制", "恢复"]),
        ("設定載入失敗", []),
        ("請換一個檔案再試", []),
        ("最多只能上傳 10 張圖片", []),
        ("台灣後面的里程與干擾", []),
        ("已觸發 · 日誌 · 診斷 · 幫助 · 複製 · 恢復", []),
        ("Tab/Shift+Tab 任務", []),
    ],
)
def test_detector_flags_simplified_and_spares_valid_traditional(
    text: str, expected: list[str]
) -> None:
    assert find_simplified_only(text) == expected


def test_detector_is_not_vacuous_on_the_simplified_sources() -> None:
    # If the ``big5`` codec ever became unavailable or lenient, the zh-TW
    # assertions would pass for the wrong reason; zh-CN must keep lighting up.
    flagged: set[str] = set()
    for _label, _traditional, simplified in _paired_sources():
        for text in simplified.values():
            flagged.update(find_simplified_only(text))
    assert len(flagged) >= 150, sorted(flagged)


def test_supplement_only_names_characters_big5_would_accept() -> None:
    redundant = sorted(
        char for char in SIMPLIFIED_BUT_ENCODABLE_AS_BIG5 if _big5_refuses(char)
    )
    assert redundant == [], f"already caught by the Big5 rule: {redundant}"
    assert all(_is_ideograph(char) for char in SIMPLIFIED_BUT_ENCODABLE_AS_BIG5)


def test_phrase_list_is_made_of_characters_the_character_rules_accept() -> None:
    # A phrase containing a character the other rules already catch would be
    # redundant; the list exists for words the character rules cannot see.
    redundant = [
        phrase
        for phrase in SIMPLIFIED_ONLY_PHRASES
        if any(
            _big5_refuses(char) or char in SIMPLIFIED_BUT_ENCODABLE_AS_BIG5
            for char in phrase
        )
    ]
    assert redundant == [], redundant


def test_every_shipped_zh_tw_source_is_scanned() -> None:
    rows = _shipped_zh_tw_text()
    by_source: dict[str, list[str]] = {}
    for source, _key, text in rows:
        by_source.setdefault(source, []).append(text)
    assert set(by_source) == {
        "web locale",
        "vscode locale",
        "server messages",
        "offline page",
    }
    # Sizes are loose lower bounds: they only prove each source was really read.
    assert len(by_source["web locale"]) > 250
    assert len(by_source["vscode locale"]) > 150
    assert len(by_source["server messages"]) >= 20
    assert "離線" in by_source["offline page"][0]


@pytest.mark.parametrize(
    ("traditional", "simplified", "expected_keys"),
    [
        ({"k": "尚尚未授予"}, {"k": "尚未授予"}, ["k"]),
        ({"k": "謝謝"}, {"k": "谢谢"}, []),
        ({"k": "謝謝謝謝"}, {"k": "谢谢"}, ["k"]),
        ({"k": "尚未授予"}, {"k": "尚未授予"}, []),
        ({"k": "尚尚"}, {}, ["k"]),
    ],
)
def test_doubled_artifacts_follow_the_zh_cn_source(
    traditional: dict[str, str], simplified: dict[str, str], expected_keys: list[str]
) -> None:
    rows = doubled_conversion_artifacts(traditional, simplified)
    assert [row.split(":")[0] for row in rows] == expected_keys


def test_characters_valid_in_both_scripts_are_never_flagged() -> None:
    flagged = sorted(
        char for char in VALID_IN_BOTH_SCRIPTS if find_simplified_only(char)
    )
    assert flagged == [], flagged
