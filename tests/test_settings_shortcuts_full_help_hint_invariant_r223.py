"""R223 / Cycle 12: settings panel keyboard-help discoverability hint.

设计目标
========

The Web UI settings panel had a "Common shortcuts" section that listed
5 input-workflow shortcuts (Submit / Insert code / Paste image / Upload
image / Clear images) but **never told the user there were 7 more
navigation shortcuts** registered in `static/js/keyboard-shortcuts.js`'s
`showHelp()` function (Ctrl+, → settings · Ctrl+/ → help ·
T → theme toggle · Tab → next task · Shift+Tab → prev task ·
Escape → close modal · Mod+Enter → submit).

This is a textbook discoverability gap — power-user shortcuts existed
in code but were invisible in the UI. R223 adds a one-line hint
beneath the shortcuts list pointing users at `Ctrl+/` (Cmd+/ on
macOS) for the full reference. The hint is fully i18n-keyed
(`settings.shortcutsFullHelpHint`).

Invariant contract / what this test locks
=========================================

1. The i18n key `settings.shortcutsFullHelpHint` exists in both
   `en.json` and `zh-CN.json` with non-empty translations.
2. The web template references the key via
   `data-i18n="settings.shortcutsFullHelpHint"` so the page actually
   renders the hint.
3. The hint message mentions the canonical shortcut binding
   (`Ctrl+/` in EN, both Cmd+/ and Ctrl+/ acceptable in zh-CN) —
   without this the hint is useless.
4. The hint message mentions where the output goes (`console` in
   EN, `控制台` in zh-CN) — otherwise users press Ctrl+/ and see
   no apparent effect.

This protects against three common drift scenarios:

* A later refactor changes the hint text to omit the shortcut
  binding — silently degrades discoverability.
* Someone deletes the `data-i18n` attribute thinking it's
  unused — the i18n key remains but the page no longer renders it.
* A translation rewrite drops "console" / "控制台" — users press
  the key and don't know to open DevTools.

Implemented 2026-05-14, 5 cases / 6 subtests.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LOCALES_DIR = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "locales"
WEB_UI_HTML = REPO_ROOT / "src" / "ai_intervention_agent" / "templates" / "web_ui.html"

I18N_KEY = "settings.shortcutsFullHelpHint"


def _load_locale(name: str) -> dict[str, object]:
    raw = (LOCALES_DIR / name).read_text(encoding="utf-8")
    obj = json.loads(raw)
    if not isinstance(obj, dict):
        raise AssertionError(f"{name}: locale root must be a JSON object")
    return obj


def _nested_get(obj: dict, dotted_key: str) -> object:
    parts = dotted_key.split(".")
    cur: object = obj
    for p in parts:
        if not isinstance(cur, dict) or p not in cur:
            return None
        cur = cur[p]
    return cur


class TestI18nKeyPresent(unittest.TestCase):
    """1. The hint key exists in both EN and zh-CN locales."""

    def test_en_locale_has_key_with_nonempty_value(self) -> None:
        en = _load_locale("en.json")
        value = _nested_get(en, I18N_KEY)
        self.assertIsInstance(
            value,
            str,
            f"en.json missing string value for `{I18N_KEY}`",
        )
        assert isinstance(value, str)
        self.assertGreater(
            len(value.strip()),
            10,
            f"en.json `{I18N_KEY}` is suspiciously short: {value!r}",
        )

    def test_zh_locale_has_key_with_nonempty_value(self) -> None:
        zh = _load_locale("zh-CN.json")
        value = _nested_get(zh, I18N_KEY)
        self.assertIsInstance(
            value,
            str,
            f"zh-CN.json missing string value for `{I18N_KEY}`",
        )
        assert isinstance(value, str)
        self.assertGreater(
            len(value.strip()),
            10,
            f"zh-CN.json `{I18N_KEY}` is suspiciously short: {value!r}",
        )


class TestHtmlReferencesKey(unittest.TestCase):
    """2. web_ui.html must render the hint via the i18n key."""

    def test_html_has_data_i18n_attribute(self) -> None:
        html = WEB_UI_HTML.read_text(encoding="utf-8")
        # Match data-i18n="settings.shortcutsFullHelpHint" anywhere
        # (quoting style flexibility: " or ' both OK).
        pattern = re.compile(
            r"""data-i18n\s*=\s*["']settings\.shortcutsFullHelpHint["']""",
        )
        self.assertRegex(
            html,
            pattern,
            (
                "web_ui.html missing data-i18n attribute referencing "
                f"`{I18N_KEY}`. The settings panel will not render the "
                "discoverability hint, defeating R223's purpose."
            ),
        )


class TestShortcutBindingMentioned(unittest.TestCase):
    """3. The hint must call out the actual shortcut binding (Ctrl+/)."""

    def test_en_hint_mentions_ctrl_slash(self) -> None:
        en = _load_locale("en.json")
        value = _nested_get(en, I18N_KEY)
        assert isinstance(value, str)
        self.assertIn(
            "Ctrl+/",
            value,
            (
                f"en.json `{I18N_KEY}` does not mention the actual "
                "shortcut binding `Ctrl+/`. The hint must tell users "
                "which keys to press."
            ),
        )

    def test_zh_hint_mentions_one_of_ctrl_or_cmd_slash(self) -> None:
        zh = _load_locale("zh-CN.json")
        value = _nested_get(zh, I18N_KEY)
        assert isinstance(value, str)
        self.assertTrue(
            "Ctrl+/" in value or "Cmd+/" in value,
            (
                f"zh-CN.json `{I18N_KEY}` mentions neither `Ctrl+/` "
                f"nor `Cmd+/`. Current value: {value!r}. The hint "
                "must tell users which keys to press."
            ),
        )


class TestOutputLocationMentioned(unittest.TestCase):
    """4. The hint must tell users where the output appears (DevTools console)."""

    def test_en_hint_mentions_console(self) -> None:
        en = _load_locale("en.json")
        value = _nested_get(en, I18N_KEY)
        assert isinstance(value, str)
        self.assertIn(
            "console",
            value.lower(),
            (
                f"en.json `{I18N_KEY}` does not mention `console`. "
                "Without this hint users press Ctrl+/ and see no "
                "apparent effect because the output is in DevTools."
            ),
        )

    def test_zh_hint_mentions_console_in_chinese(self) -> None:
        zh = _load_locale("zh-CN.json")
        value = _nested_get(zh, I18N_KEY)
        assert isinstance(value, str)
        self.assertIn(
            "控制台",
            value,
            (
                f"zh-CN.json `{I18N_KEY}` 缺少 `控制台` 关键词。"
                "用户按 Ctrl+/ 后看不到效果，因为输出在 DevTools 里。"
            ),
        )


if __name__ == "__main__":
    unittest.main()
