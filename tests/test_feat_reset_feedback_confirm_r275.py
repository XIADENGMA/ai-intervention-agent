"""R275 / cycle-24 t24-3: ``resetFeedbackConfig`` 加 ``window.confirm`` 二次确认。

破坏性操作一致性原则
--------------------

项目里有 2 个 reset button:

1. ``#reset-settings-btn`` → ``resetSettings()`` — 本地通知设置重置
   (R231 / feat-reset-confirm，cycle-13)
2. ``#reset-feedback-config-btn`` → ``resetFeedbackConfig()`` — 服务端
   反馈配置重置（写 config.toml + SSE 广播给所有协作者）

(1) 已经有 ``window.confirm`` 二次确认（cycle-13 R231 加），但 (2) 仍是
"一键直接重置"。但 (2) 的破坏性等级实际**严格高于**(1)：

- (1) 影响范围: 当前浏览器的 localStorage
- (2) 影响范围: 服务端 config.toml + 同服务器所有协作者通过 SSE 收到广播

按破坏性等级排序，(2) **更应该**有二次确认。用户 TODO "重置设置点击后
应该需要二次确认" 字面是 (1)，但等同强度的 (2) 必须同步加 confirm，否则
就是不一致的 UX 漏洞。

R275 修复
---------

- ``settings-manager.js::resetFeedbackConfig`` 开头加 ``window.confirm``
  判断，pattern 与 ``resetSettings`` 完全一致 (typeof guard + _tl fallback)
- 4 个 locale 新增 ``settings.resetFeedbackConfirm`` +
  ``settings.resetFeedbackCancelled``

Invariant
---------

1. ``resetFeedbackConfig`` 函数必须以 ``_tl("settings.resetFeedbackConfirm"``
   开头（在任何 await/fetch 之前）
2. ``resetFeedbackConfig`` 必须有 ``typeof window`` + ``typeof window.confirm``
   guard
3. ``resetFeedbackConfig`` 必须有 ``console.debug("...resetFeedbackCancelled..."``
   分支（取消时打 debug log，与 ``resetSettings`` 范式对齐）
4. ``resetFeedbackConfig`` 必须 ``return`` 在 confirm cancel 分支（不能
   继续往下走 fetch）
5. 4 个 locale 都必须有 ``settings.resetFeedbackConfirm`` 和
   ``settings.resetFeedbackCancelled``

Meta-lint (R273 v3.4 pattern 推广)
----------------------------------

未来再加 reset button 时自动拦截 — 任何 ``async reset*()`` 函数都必须
先有 ``_tl("settings.reset...Confirm"`` 调用 (R275 t24-3 → cr54 meta-lint)。
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
LOCALES_DIR = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "locales"

NEW_KEYS = ["resetFeedbackConfirm", "resetFeedbackCancelled"]


def _load_locale(locale_name: str) -> dict:
    path = LOCALES_DIR / f"{locale_name}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _load_pseudo_locale() -> dict:
    return json.loads(
        (LOCALES_DIR / "_pseudo" / "pseudo.json").read_text(encoding="utf-8")
    )


def _extract_function_body(src: str, func_name: str) -> str:
    """Extract the body of a JS method by name, until matching close brace.

    支持 ``async funcName()`` 与 ``funcName()`` 两种声明形式。"""
    # 找 method 起点
    pattern = re.compile(r"(async\s+)?" + re.escape(func_name) + r"\s*\([^)]*\)\s*\{")
    match = pattern.search(src)
    assert match is not None, f"R275: 找不到函数 ``{func_name}``"
    start = match.end()
    # 匹配 brace 深度
    depth = 1
    i = start
    while i < len(src) and depth > 0:
        ch = src[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        i += 1
    assert depth == 0, f"R275: ``{func_name}`` 大括号不闭合"
    return src[start : i - 1]


class TestResetFeedbackConfigHasConfirm(unittest.TestCase):
    src = SETTINGS_JS.read_text(encoding="utf-8")

    def setUp(self) -> None:
        self.body = _extract_function_body(self.src, "resetFeedbackConfig")

    def test_uses_tl_for_confirm_message(self) -> None:
        self.assertIn(
            '_tl(\n      "settings.resetFeedbackConfirm"',
            self.body,
            'R275: resetFeedbackConfig 必须调用 ``_tl("settings.'
            'resetFeedbackConfirm"`` 来获取 confirm 文案（i18n 化 + '
            "fallback）",
        )

    def test_uses_window_confirm_with_typeof_guard(self) -> None:
        self.assertRegex(
            self.body,
            r'typeof\s+window\s*!==\s*"undefined"\s*&&\s*'
            r'typeof\s+window\.confirm\s*===\s*"function"\s*&&\s*'
            r"!window\.confirm\(",
            "R275: 必须有完整的 typeof guard + window.confirm 调用，"
            "防止自动化测试 / sandbox 环境 break",
        )

    def test_has_cancelled_console_debug(self) -> None:
        self.assertIn(
            "settings.resetFeedbackCancelled",
            self.body,
            'R275: cancel 分支必须用 ``_tl("settings.'
            'resetFeedbackCancelled"`` 打 debug log，与 resetSettings 对齐',
        )

    def test_returns_early_on_cancel(self) -> None:
        """confirm cancel 必须 ``return``，不能继续 fetch /api/reset-feedback-config。"""
        # 找到 confirm block 后必须紧跟 return
        match = re.search(
            r"!window\.confirm\([^)]+\)\s*\)\s*\{[\s\S]*?return;",
            self.body,
        )
        self.assertIsNotNone(
            match,
            "R275: confirm cancel 必须 ``return;``，否则会绕过用户取消继续"
            "调用 /api/reset-feedback-config",
        )

    def test_confirm_happens_before_fetch(self) -> None:
        """confirm 必须在任何 fetch 之前，否则点 cancel 也会触发后端调用。"""
        confirm_pos = self.body.find("window.confirm(")
        fetch_pos = self.body.find('fetch("/api/reset-feedback-config"')
        self.assertGreater(
            confirm_pos,
            -1,
            "R275: 必须有 window.confirm 调用",
        )
        self.assertGreater(
            fetch_pos,
            -1,
            "R275: 必须有 fetch 调用",
        )
        self.assertLess(
            confirm_pos,
            fetch_pos,
            "R275: confirm 必须在 fetch 之前（否则 cancel 也会调后端）",
        )


class TestResetSettingsStillHasConfirm(unittest.TestCase):
    """R275 sanity: 修 resetFeedbackConfig 时不能弄坏 resetSettings 的原 confirm。"""

    src = SETTINGS_JS.read_text(encoding="utf-8")

    def setUp(self) -> None:
        self.body = _extract_function_body(self.src, "resetSettings")

    def test_reset_settings_still_uses_tl_confirm(self) -> None:
        self.assertIn(
            "settings.resetConfirm",
            self.body,
            "R275 sanity: resetSettings 原有的 confirm 不能被回归破坏",
        )


class TestNewKeysExistInAllLocales(unittest.TestCase):
    def test_en_locale_has_new_keys(self) -> None:
        en = _load_locale("en")
        settings = en.get("settings", {})
        for key in NEW_KEYS:
            self.assertIn(
                key,
                settings,
                f"R275: en.json settings.{key} 缺失",
            )

    def test_zh_cn_locale_has_new_keys(self) -> None:
        zh = _load_locale("zh-CN")
        settings = zh.get("settings", {})
        for key in NEW_KEYS:
            self.assertIn(
                key,
                settings,
                f"R275: zh-CN.json settings.{key} 缺失",
            )

    def test_zh_tw_locale_has_new_keys(self) -> None:
        zh_tw = _load_locale("zh-TW")
        settings = zh_tw.get("settings", {})
        for key in NEW_KEYS:
            self.assertIn(
                key,
                settings,
                f"R275: zh-TW.json settings.{key} 缺失",
            )

    def test_pseudo_locale_has_new_keys(self) -> None:
        pseudo = _load_pseudo_locale()
        settings = pseudo.get("settings", {})
        for key in NEW_KEYS:
            self.assertIn(
                key,
                settings,
                f"R275: pseudo.json settings.{key} 缺失",
            )


class TestNewKeyTranslationsNonEmpty(unittest.TestCase):
    def test_en_translations_non_empty(self) -> None:
        en = _load_locale("en")
        for key in NEW_KEYS:
            val = en.get("settings", {}).get(key, "")
            self.assertGreater(
                len(val.strip()),
                0,
                f"R275: en.json settings.{key} 不能空",
            )

    def test_zh_cn_translations_non_empty(self) -> None:
        zh = _load_locale("zh-CN")
        for key in NEW_KEYS:
            val = zh.get("settings", {}).get(key, "")
            self.assertGreater(
                len(val.strip()),
                0,
                f"R275: zh-CN.json settings.{key} 不能空",
            )


class TestAsyncResetMethodMetaLint(unittest.TestCase):
    """R275 v3.4 meta-lint (借鉴 R273 setting-title pattern):
    所有 ``async reset*()`` 方法必须先有 ``_tl("settings.reset*Confirm"`` 调用。
    防止未来加新 reset button 时漏掉二次确认。"""

    src = SETTINGS_JS.read_text(encoding="utf-8")

    def test_all_async_reset_methods_have_confirm(self) -> None:
        # 找所有 ``async resetXxx()`` 与 ``resetXxx()`` 方法定义
        method_pattern = re.compile(
            r"(?:async\s+)?(reset[A-Z][a-zA-Z]*)\s*\([^)]*\)\s*\{",
        )
        violations: list[str] = []
        for match in method_pattern.finditer(self.src):
            func_name = match.group(1)
            try:
                body = _extract_function_body(self.src, func_name)
            except AssertionError:
                continue  # 同名重复声明等异常情形，跳过
            # Meta-lint: 函数体必须有任何形式的 ``Confirm`` i18n key 引用
            # 和 ``window.confirm(`` 调用 — 不强制 key 名命名规约，只要确认
            # "破坏性 reset 必须有二次确认"这个语义即可。
            has_confirm_key = re.search(
                r'"settings\.[a-zA-Z]+Confirm"',
                body,
            )
            has_window_confirm = "window.confirm(" in body
            if not (has_confirm_key and has_window_confirm):
                missing = []
                if not has_confirm_key:
                    missing.append('``"settings.*Confirm"`` i18n key 引用')
                if not has_window_confirm:
                    missing.append("``window.confirm(`` 调用")
                violations.append(f"``{func_name}`` 缺 " + " + ".join(missing))
        self.assertEqual(
            len(violations),
            0,
            'R275 meta-lint: 所有 reset*() 方法必须有 ``"settings.*Confirm"`` '
            "i18n key 引用 + ``window.confirm(`` 调用，确保破坏性操作有二次"
            "确认。违反:\n  - " + "\n  - ".join(violations),
        )


if __name__ == "__main__":
    unittest.main()
