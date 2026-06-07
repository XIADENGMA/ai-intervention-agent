"""R273 / cycle-23 (exploratory i18n audit):
``Bark URL`` 与 ``Device Key`` 这两个 setting label 在 ``web_ui.html`` 中
**没有** ``data-i18n`` 属性，硬编码英文，中文用户看到也是英文。

Pre-R273 现象
-------------

``templates/web_ui.html`` line 1437 + 1449:

.. code-block:: html

    <span class="setting-title">Bark URL</span>
    <span class="setting-title">Device Key</span>

对比邻近 line 1462:

.. code-block:: html

    <span class="setting-title" data-i18n="settings.barkIconUrl">Icon URL (optional)</span>

两个邻居有 ``data-i18n``，独 "Bark URL" + "Device Key" 漏掉。看上去是
最早 ship Bark 通知功能时的 oversight。

R273 修复
---------

- ``web_ui.html``: 给两个 ``<span>`` 加 ``data-i18n="settings.barkUrl"``
  / ``data-i18n="settings.barkDeviceKey"``
- ``locales/en.json`` / ``zh-CN.json`` / ``zh-TW.json`` /
  ``_pseudo/pseudo.json``: 新增对应 4 个 key，与现有 ``settings.bark*``
  family 命名一致

Why locked
----------

i18n 漂移最难发现 — 中文用户看到 1 个英文 label 通常以为是"故意没翻"
而不会报 bug；维护者看代码时也容易跟着原 pattern 写硬编码。R273
invariant 把这两个 label 锁死，并扩成 "所有 setting-title 必须有
data-i18n" 的 meta-rule (Track B)，未来加新 setting 时 lint 自动拦截。

Invariant
---------

1. 4 个 locale 文件 (en / zh-CN / zh-TW / pseudo) 都必须有
   ``settings.barkUrl`` 和 ``settings.barkDeviceKey``
2. ``web_ui.html`` 必须有 ``data-i18n="settings.barkUrl"`` 与
   ``data-i18n="settings.barkDeviceKey"``
3. (Meta-lint) ``web_ui.html`` 中所有 ``<span class="setting-title">``
   都必须有 ``data-i18n`` 属性（防止未来新 setting label 又硬编码）
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WEB_UI_HTML = REPO_ROOT / "src" / "ai_intervention_agent" / "templates" / "web_ui.html"
LOCALES_DIR = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "locales"
PSEUDO_LOCALE = LOCALES_DIR / "_pseudo" / "pseudo.json"

NEW_KEYS = ["barkUrl", "barkDeviceKey"]
EXPECTED_LOCALES = ["en", "zh-CN", "zh-TW"]


def _load_locale(locale_name: str) -> dict:
    path = LOCALES_DIR / f"{locale_name}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _load_pseudo_locale() -> dict:
    return json.loads(PSEUDO_LOCALE.read_text(encoding="utf-8"))


class TestNewKeysExistInAllLocales(unittest.TestCase):
    def test_en_locale_has_new_keys(self) -> None:
        en = _load_locale("en")
        settings = en.get("settings", {})
        for key in NEW_KEYS:
            self.assertIn(
                key,
                settings,
                f"R273: en.json settings.{key} 缺失。新增 setting label 必须"
                "对所有 locale 加翻译。",
            )

    def test_zh_cn_locale_has_new_keys(self) -> None:
        zh = _load_locale("zh-CN")
        settings = zh.get("settings", {})
        for key in NEW_KEYS:
            self.assertIn(
                key,
                settings,
                f"R273: zh-CN.json settings.{key} 缺失。中文用户会看到英文 fallback。",
            )

    def test_zh_tw_locale_has_new_keys(self) -> None:
        zh_tw = _load_locale("zh-TW")
        settings = zh_tw.get("settings", {})
        for key in NEW_KEYS:
            self.assertIn(
                key,
                settings,
                f"R273: zh-TW.json settings.{key} 缺失。繁中用户会看到英文 fallback。",
            )

    def test_pseudo_locale_has_new_keys(self) -> None:
        pseudo = _load_pseudo_locale()
        settings = pseudo.get("settings", {})
        for key in NEW_KEYS:
            self.assertIn(
                key,
                settings,
                f"R273: pseudo.json settings.{key} 缺失。pseudo locale 用于"
                "i18n 视觉测试 — 所有 key 都必须有 pseudo 翻译。",
            )


class TestWebUiHtmlReferencesNewKeys(unittest.TestCase):
    def test_html_has_data_i18n_for_bark_url(self) -> None:
        text = WEB_UI_HTML.read_text(encoding="utf-8")
        self.assertIn(
            'data-i18n="settings.barkUrl"',
            text,
            "R273: web_ui.html 必须给 Bark URL label 加 "
            '``data-i18n="settings.barkUrl"``，否则中文用户看到英文。',
        )

    def test_html_has_data_i18n_for_bark_device_key(self) -> None:
        text = WEB_UI_HTML.read_text(encoding="utf-8")
        self.assertIn(
            'data-i18n="settings.barkDeviceKey"',
            text,
            "R273: web_ui.html 必须给 Device Key label 加 "
            '``data-i18n="settings.barkDeviceKey"``，否则中文用户看到英文。',
        )


class TestAllSettingTitlesHaveDataI18nMetaLint(unittest.TestCase):
    """R273 Track B (Meta-lint): 防止未来回退 — 所有
    ``<span class="setting-title">`` 必须有 ``data-i18n`` 属性。"""

    def test_all_setting_title_spans_have_data_i18n(self) -> None:
        text = WEB_UI_HTML.read_text(encoding="utf-8")
        # 匹配 <span class="setting-title" ...> 开头标签（不挑次序）
        pattern = re.compile(
            r'<span\b(?P<attrs>[^>]*?\bclass="[^"]*\bsetting-title\b[^"]*"[^>]*)>',
            re.IGNORECASE,
        )
        offenders: list[str] = []
        for match in pattern.finditer(text):
            attrs = match.group("attrs")
            if "data-i18n" not in attrs:
                snippet = text[
                    max(0, match.start() - 60) : min(len(text), match.end() + 60)
                ]
                offenders.append(snippet.replace("\n", " "))
        self.assertEqual(
            len(offenders),
            0,
            'R273 meta-lint: 所有 `<span class="setting-title">` 必须带 '
            "``data-i18n`` 属性，否则中文用户看到英文 label。发现以下硬编码 "
            "label:\n  - " + "\n  - ".join(offenders),
        )


class TestNewKeysAreNonEmpty(unittest.TestCase):
    def test_en_translations_are_non_empty(self) -> None:
        en = _load_locale("en")
        for key in NEW_KEYS:
            val = en.get("settings", {}).get(key, "")
            self.assertGreater(
                len(val.strip()),
                0,
                f"R273: en.json settings.{key} 不能是空字符串。",
            )

    def test_zh_cn_translations_are_non_empty(self) -> None:
        zh = _load_locale("zh-CN")
        for key in NEW_KEYS:
            val = zh.get("settings", {}).get(key, "")
            self.assertGreater(
                len(val.strip()),
                0,
                f"R273: zh-CN.json settings.{key} 不能是空字符串。",
            )


if __name__ == "__main__":
    unittest.main()
