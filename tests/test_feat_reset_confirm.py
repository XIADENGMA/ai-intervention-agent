"""``feat-reset-confirm`` 回归契约：

"重置设置"按钮必须先弹二次确认，用户取消即 noop。

背景
----
用户偏好："web 页面上设置页面的重置设置点击后应该需要二次确认。"

重置设置是破坏性操作——一键覆盖全部本地通知偏好。误点曾导致"全部偏好
被刷掉、只能手工逐项再调一遍"的痛点。

实现要点
--------
- 复用 ``quick_phrases.js`` 的 ``window.confirm`` + i18n 文案范式：最小变更面、
  与既有删除短语 / 全量替换确认一致。
- 三个 locale 都加 ``settings.resetConfirm`` + ``settings.resetCancelled``。
- 用户取消（confirm 返回 false）时立即 ``return``，**不**触碰 ``this.settings``、
  也**不**调用 ``saveSettings`` / ``updateUI`` / ``applySettings``。

测试覆盖
--------
1. ``resetSettings`` 函数体里**先**出现 ``window.confirm`` 调用，**后**才出现
   状态修改三件套（``this.settings = ... defaultSettings``、``saveSettings``、
   ``updateUI``）。
2. confirm 返回 false 时必须 ``return``，不能继续走重置路径。
3. en / zh-CN / pseudo 三个 locale 都注册 ``settings.resetConfirm`` 和
   ``settings.resetCancelled``。
4. ``_tl`` (i18n 帮助函数) 用于取文案，避免硬编码导致中文用户看到英文。
5. confirm 消息从 i18n key 取（而不是裸字符串），通过 ``_tl("settings.resetConfirm", ...)``
   调用站可观察。
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SETTINGS_JS = (
    REPO_ROOT
    / "src"
    / "ai_intervention_agent"
    / "static"
    / "js"
    / "settings-manager.js"
)
EN_LOCALE = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "locales" / "en.json"
)
ZH_LOCALE = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "locales" / "zh-CN.json"
)
PSEUDO_LOCALE = (
    REPO_ROOT
    / "src"
    / "ai_intervention_agent"
    / "static"
    / "locales"
    / "_pseudo"
    / "pseudo.json"
)


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _strip_js_comments(src: str) -> str:
    """剥离 ``// ...`` 单行注释与 ``/* ... */`` 块注释，避免注释文字误命中契约。"""
    src = re.sub(r"/\*[\s\S]*?\*/", "", src)
    src = re.sub(r"(?m)^\s*//.*?$", "", src)
    return src


def _extract_reset_settings_body(js: str) -> str:
    """抓取 ``resetSettings() { ... }`` 的函数体（含 brace matching）。"""
    m = re.search(r"resetSettings\s*\([^)]*\)\s*\{", js)
    assert m is not None, "未在 settings-manager.js 中找到 resetSettings 方法定义"
    start = m.end()
    depth = 1
    i = start
    while i < len(js) and depth > 0:
        ch = js[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        i += 1
    assert depth == 0, "resetSettings 方法体的大括号没匹配上"
    return js[start : i - 1]


class TestResetSettingsAsksConfirmation(unittest.TestCase):
    """``resetSettings`` 必须先 ``window.confirm``，再做状态变更。"""

    def setUp(self) -> None:
        self.raw = _read(SETTINGS_JS)
        self.body = _strip_js_comments(_extract_reset_settings_body(self.raw))

    def test_window_confirm_call_present(self) -> None:
        self.assertRegex(
            self.body,
            r"window\.confirm\s*\(",
            "resetSettings 必须调用 window.confirm 做二次确认",
        )

    def test_confirm_message_via_i18n_helper(self) -> None:
        # 通过 ``_tl("settings.resetConfirm", fallback)`` 取文案，
        # 避免硬编码英文导致中文用户看不到本地化提示。
        self.assertRegex(
            self.body,
            r'_tl\(\s*"settings\.resetConfirm"',
            'resetSettings 必须用 _tl("settings.resetConfirm", ...) 取确认文案',
        )

    def test_confirm_precedes_state_mutation(self) -> None:
        # window.confirm 必须出现在 ``this.settings = ... defaultSettings`` 之前
        confirm_idx = self.body.find("window.confirm")
        # 状态变更：拷贝 defaultSettings 到 this.settings
        mutate_match = re.search(
            r"this\.settings\s*=\s*\{\s*\.\.\.\s*this\.defaultSettings",
            self.body,
        )
        self.assertIsNotNone(
            mutate_match,
            "未在 resetSettings 中找到 ``this.settings = {...this.defaultSettings}``",
        )
        assert mutate_match is not None
        mutate_idx = mutate_match.start()
        self.assertGreater(confirm_idx, -1, "未找到 window.confirm 调用")
        self.assertLess(
            confirm_idx,
            mutate_idx,
            "window.confirm 必须出现在 ``this.settings = {...defaultSettings}`` 之前，"
            "否则二次确认失去意义",
        )

    def test_early_return_on_user_cancel(self) -> None:
        """confirm 取消分支必须直接 ``return``。"""
        # 模式：``!window.confirm(confirmMsg)) { ... return; ... }``
        # 用宽松匹配：任何 ``!window.confirm`` 后的同一分支里有 ``return``。
        m = re.search(
            r"!\s*window\.confirm\s*\([^)]*\)\s*\)\s*\{[^}]*\breturn\b",
            self.body,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(
            m,
            "confirm 取消分支（!window.confirm(...)）必须立即 return，"
            "不能继续走重置路径",
        )

    def test_save_after_confirm_pass(self) -> None:
        """confirm 通过后，saveSettings / updateUI / applySettings 必须按
        既有顺序继续调用，行为不退化。"""
        for call in ("this.saveSettings()", "this.updateUI()", "this.applySettings()"):
            self.assertIn(
                call,
                self.body,
                f"resetSettings 必须仍调用 {call}（确认通过后行为不变）",
            )


class TestLocalesRegistered(unittest.TestCase):
    """三个 locale 必须都注册 ``settings.resetConfirm`` 和 ``settings.resetCancelled``。"""

    KEYS = ("resetConfirm", "resetCancelled")

    def _load_settings(self, path: Path) -> dict[str, object]:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
        return data["settings"]

    def _assert_nonempty_string_value(
        self, s: dict[str, object], k: str, locale: str
    ) -> None:
        self.assertIn(k, s, f"{locale} settings.{k} 必须存在")
        value = s[k]
        self.assertIsInstance(value, str, f"{locale} settings.{k} 必须是字符串")
        assert isinstance(value, str)  # for ty
        self.assertTrue(
            value.strip(),
            f"{locale} settings.{k} 必须是非空字符串",
        )

    def test_en_locale_has_keys(self) -> None:
        s = self._load_settings(EN_LOCALE)
        for k in self.KEYS:
            self._assert_nonempty_string_value(s, k, "en.json")

    def test_zh_locale_has_keys(self) -> None:
        s = self._load_settings(ZH_LOCALE)
        for k in self.KEYS:
            self._assert_nonempty_string_value(s, k, "zh-CN.json")

    def test_pseudo_locale_has_keys(self) -> None:
        s = self._load_settings(PSEUDO_LOCALE)
        for k in self.KEYS:
            self.assertIn(
                k,
                s,
                f"pseudo.json settings.{k} 必须存在（rerun "
                f"scripts/gen_pseudo_locale.py 同步）",
            )

    def test_zh_locale_not_just_copied_from_en(self) -> None:
        """中文文案确实是中文（不退化为英文 fallback）。"""
        en = self._load_settings(EN_LOCALE)
        zh = self._load_settings(ZH_LOCALE)
        for k in self.KEYS:
            self.assertNotEqual(
                zh[k],
                en[k],
                f"zh-CN.json settings.{k} 不应等于英文文案（应翻译为中文）",
            )


if __name__ == "__main__":
    unittest.main()
