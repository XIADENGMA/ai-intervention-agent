"""R144 · 键盘快捷键 cheatsheet overlay（按 ? 弹出）契约测试。

背景
----

R131d 的 Alt+1..9（Quick Phrases）+ R140 的 Ctrl+Enter / Enter 提交模式
等隐藏快捷键 discoverability 不足——新用户不打开源码 / changelog 就发
现不了。GitHub / GitLab / Linear 都用 ``?`` 触发快捷键 cheatsheet 浮
层成为行业范式。

R144 落地一个最小可行 overlay：

* 触发：任意 input/textarea/contenteditable **不 focus** 时按 ``?``
  (Shift+/)；textarea 中 ``?`` 仍是字符（不打扰键盘党正常输入）。
* 关闭：Esc / 点击遮罩 / 卡片外。卡片内点击不冒泡（防误关）。
* 静态列出 6 条 shortcut（``? / Esc / Alt+1-9 / Ctrl+Enter / Enter /
  Shift+Enter``），i18n 全覆盖，不依赖 localStorage（无状态 UI）。

设计契约（共 ~28 cases）：

1. **JS 文件存在 + 关键常量** — ``OVERLAY_ID`` /``TRIGGER_KEY="?"``
   / ``SHORTCUTS`` 列表 6 条。

2. **API 表面** — ``window.AIIA_KEYBOARD_SHORTCUT_HELP`` 暴露
   ``showOverlay`` / ``hideOverlay`` / ``isOverlayOpen`` /
   ``_shouldTriggerHelp`` / ``_isTypingTarget`` 共 5 项 + 3 个常量。

3. **HTML 集成** — ``web_ui.html`` 含 ``<script
   src="/static/js/keyboard_shortcut_help.js?v={{
   keyboard_shortcut_help_version }}"``，``defer``，``nonce``。

4. **template context** — ``_get_template_context`` 计算
   ``keyboard_shortcut_help_version``。

5. **CSS 选择器与品牌色** — main.css 含 ``.aiia-kshelp-overlay``、
   ``.aiia-kshelp-card``、``.aiia-kshelp-key`` 等核心选择器；用
   ``var(--text-primary, ...)`` 等 fallback 模式（与 R138 charCounter
   同款）。

6. **i18n 全覆盖** — 中英两份 locale 的 ``shortcuts`` namespace 必含
   新增的 ``helpSubtitle / helpEscHint / quickPhrase /
   submitCtrlEnter / submitEnter / newline`` 6 个 key；既有
   ``helpTitle / showHelp / closeModal`` 复用不变。

7. **触发条件 (_shouldTriggerHelp 契约描述)** — 源码中含「不在 input
   / textarea / contenteditable focus 时拦截」的语义注释 ；触发键
   是 ``?``。

8. **CSP / XSS 安全** — JS 全部用 ``createElement`` + ``textContent``，
   无 ``innerHTML`` / ``insertAdjacentHTML``。

9. **优雅降级** — i18n 模块未加载（``window.AIIA_I18N`` 缺失或 ``t``
   不是函数）时，``_t`` 兜底返回 fallback；不抛错。

10. **Capture phase 监听** — 源码中 ``addEventListener("keydown", ...,
    true)`` 显式 capture（与 R140 同款架构，确保先于其他 keydown 拦截）。
"""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


JS_PATH = (
    REPO_ROOT
    / "src"
    / "ai_intervention_agent"
    / "static"
    / "js"
    / "keyboard_shortcut_help.js"
)
HTML_PATH = REPO_ROOT / "src" / "ai_intervention_agent" / "templates" / "web_ui.html"
WEB_UI_PY = REPO_ROOT / "src" / "ai_intervention_agent" / "web_ui.py"
CSS_PATH = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "css" / "main.css"
LOCALE_ZH = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "locales" / "zh-CN.json"
)
LOCALE_EN = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "locales" / "en.json"
)


class TestJsFileExists(unittest.TestCase):
    """JS 文件存在 + 关键 IIFE 与常量结构。"""

    def test_js_file_exists(self):
        self.assertTrue(JS_PATH.exists(), f"missing {JS_PATH}")

    def test_iife_pattern(self):
        src = JS_PATH.read_text(encoding="utf-8")
        # IIFE 启动模式与 quick_phrases.js / feedback_*.js 一致
        self.assertRegex(src, r"\(function\s*\(\)\s*\{")
        self.assertIn('"use strict"', src)


class TestConstants(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.src = JS_PATH.read_text(encoding="utf-8")

    def test_overlay_id_constant(self):
        self.assertIn(
            'var OVERLAY_ID = "aiia-keyboard-shortcut-help-overlay";', self.src
        )

    def test_trigger_key_constant(self):
        self.assertIn('var TRIGGER_KEY = "?";', self.src)

    def test_shortcuts_array_six_items(self):
        # 6 个 shortcut 条目 —— 数 SHORTCUTS 列表里 i18nKey 的出现次数
        keys_in_table = (
            "shortcuts.showHelp",
            "shortcuts.closeModal",
            "shortcuts.quickPhrase",
            "shortcuts.submitCtrlEnter",
            "shortcuts.submitEnter",
            "shortcuts.newline",
        )
        for k in keys_in_table:
            self.assertIn(
                k, self.src, f"i18n key {k!r} should appear in SHORTCUTS table"
            )


class TestApiSurface(unittest.TestCase):
    """``window.AIIA_KEYBOARD_SHORTCUT_HELP`` exposes 5 functions + 3 constants."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.src = JS_PATH.read_text(encoding="utf-8")

    def test_global_namespace(self):
        self.assertIn("window.AIIA_KEYBOARD_SHORTCUT_HELP", self.src)

    def test_show_overlay_exposed(self):
        self.assertRegex(self.src, r"showOverlay\s*:\s*showOverlay")

    def test_hide_overlay_exposed(self):
        self.assertRegex(self.src, r"hideOverlay\s*:\s*hideOverlay")

    def test_is_overlay_open_exposed(self):
        self.assertRegex(self.src, r"isOverlayOpen\s*:\s*isOverlayOpen")

    def test_should_trigger_helper_exposed(self):
        self.assertRegex(self.src, r"_shouldTriggerHelp\s*:\s*_shouldTriggerHelp")

    def test_typing_target_helper_exposed(self):
        self.assertRegex(self.src, r"_isTypingTarget\s*:\s*_isTypingTarget")


class TestHtmlIntegration(unittest.TestCase):
    """``web_ui.html`` 含 R144 的 <script> 标签（defer + nonce + cache-busting）。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.html = HTML_PATH.read_text(encoding="utf-8")

    def test_script_tag_present(self):
        self.assertIn(
            "/static/js/keyboard_shortcut_help.js?v={{ keyboard_shortcut_help_version }}",
            self.html,
        )

    def test_script_has_defer_and_nonce(self):
        # 把 R144 的 <script> 块整段抓出来检查 defer / nonce
        match = re.search(
            r"<script[^>]*keyboard_shortcut_help\.js[^>]*>",
            self.html,
        )
        self.assertIsNotNone(
            match, "R144 script tag must exist with the keyboard_shortcut_help.js src"
        )
        # 找前后的 <script ... > 全部 —— 注意 HTML 里 <script defer ...><script src=...>，
        # match 是单个 <script>...</script> 起始 tag。但 HTML 里 attr 顺序：
        # <script\n      defer\n      src="..."\n      nonce="...">
        # 要 multi-line 匹配，扩大范围
        block_match = re.search(
            r"<script\s+defer\s+src=\"/static/js/keyboard_shortcut_help\.js\?v=\{\{ keyboard_shortcut_help_version \}\}\"\s+nonce=\"\{\{ csp_nonce \}\}\"\s*>",
            self.html,
        )
        self.assertIsNotNone(
            block_match,
            "R144 script block must have defer + src + nonce in the right order",
        )


class TestTemplateContextWiring(unittest.TestCase):
    """``_get_template_context`` 计算 ``keyboard_shortcut_help_version``。"""

    def test_version_key_in_web_ui_py(self):
        src = WEB_UI_PY.read_text(encoding="utf-8")
        self.assertIn('"keyboard_shortcut_help_version"', src)
        self.assertRegex(
            src,
            r'"keyboard_shortcut_help_version":\s*_compute_file_version\(',
        )


class TestCssSelectors(unittest.TestCase):
    """main.css 含 R144 选择器，且用 var() fallback 模式。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.css = CSS_PATH.read_text(encoding="utf-8")

    def test_overlay_selector_present(self):
        self.assertIn(".aiia-kshelp-overlay {", self.css)

    def test_card_selector_present(self):
        self.assertIn(".aiia-kshelp-card {", self.css)

    def test_key_selector_present(self):
        self.assertIn(".aiia-kshelp-key {", self.css)

    def test_uses_css_variables_with_fallback(self):
        # 与 R138 charCounter 同款 fallback 模式：var(--name, fallback)
        match = re.search(r"var\(--text-primary,\s*#", self.css)
        self.assertIsNotNone(
            match,
            "R144 CSS should use var(--text-primary, #fallback) pattern "
            "for portable theming",
        )

    def test_responsive_breakpoint_present(self):
        # @media 480 下卡片 padding 收紧（与 quick-phrases-mobile 同款）
        self.assertRegex(
            self.css,
            r"@media\s*\(max-width:\s*480px\)\s*\{[^}]*\.aiia-kshelp-card\s*\{",
            "R144 CSS must define a 480px responsive collapse",
        )


class TestI18nCoverage(unittest.TestCase):
    """zh-CN + en + pseudo locale 都含新增 6 个 shortcuts.* keys。"""

    expected_new_keys = {
        "shortcuts.helpSubtitle",
        "shortcuts.helpEscHint",
        "shortcuts.quickPhrase",
        "shortcuts.submitCtrlEnter",
        "shortcuts.submitEnter",
        "shortcuts.newline",
    }

    def _load_flat(self, path: Path) -> set[str]:
        data: object = json.loads(path.read_text(encoding="utf-8"))
        flat: set[str] = set()

        def walk(prefix: str, obj: object) -> None:
            if isinstance(obj, dict):
                items = obj.items()  # type: ignore[var-annotated]
                for k, v in items:
                    key_str = str(k)
                    walk(f"{prefix}.{key_str}" if prefix else key_str, v)
            else:
                flat.add(prefix)

        walk("", data)
        return flat

    def test_zh_cn_has_new_keys(self):
        flat = self._load_flat(LOCALE_ZH)
        for k in self.expected_new_keys:
            self.assertIn(k, flat, f"zh-CN missing {k}")

    def test_en_has_new_keys(self):
        flat = self._load_flat(LOCALE_EN)
        for k in self.expected_new_keys:
            self.assertIn(k, flat, f"en missing {k}")

    def test_legacy_keys_still_present(self):
        # 复用既有 helpTitle / showHelp / closeModal 不应被删
        for path in (LOCALE_ZH, LOCALE_EN):
            flat = self._load_flat(path)
            for k in (
                "shortcuts.helpTitle",
                "shortcuts.showHelp",
                "shortcuts.closeModal",
            ):
                self.assertIn(k, flat, f"R144 must reuse legacy key {k} in {path.name}")


class TestTriggerLogicSemantics(unittest.TestCase):
    """``_shouldTriggerHelp`` / ``_isTypingTarget`` 语义边界。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.src = JS_PATH.read_text(encoding="utf-8")

    def test_typing_target_excludes_input_textarea_select(self):
        # _isTypingTarget 应当识别 input/textarea/select 三种 tag
        for tag in ("input", "textarea", "select"):
            self.assertIn(f'tag === "{tag}"', self.src)

    def test_typing_target_excludes_contenteditable(self):
        self.assertIn("isContentEditable", self.src)
        self.assertIn('contenteditable"', self.src)

    def test_modifier_keys_filtered(self):
        # ctrl+? / cmd+? / alt+? 都不该触发（避免与系统快捷键冲突）
        self.assertIn("event.ctrlKey", self.src)
        self.assertIn("event.metaKey", self.src)
        self.assertIn("event.altKey", self.src)


class TestSafeDomConstruction(unittest.TestCase):
    """JS 全部用 createElement + textContent，无 innerHTML 漏洞。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.src = JS_PATH.read_text(encoding="utf-8")

    def test_no_innerHTML(self):
        self.assertNotIn(
            ".innerHTML",
            self.src,
            "R144 must not use .innerHTML — CSP / XSS safe construction only",
        )

    def test_no_insert_adjacent_html(self):
        self.assertNotIn(
            "insertAdjacentHTML",
            self.src,
            "R144 must not use insertAdjacentHTML",
        )

    def test_uses_create_element(self):
        # 至少 5 处 createElement（dialog / card / title / row / kbd 等）
        n = self.src.count("createElement(")
        self.assertGreaterEqual(
            n, 5, f"R144 should use createElement >=5 times (got {n})"
        )


class TestGracefulDegradation(unittest.TestCase):
    """i18n 模块缺失 / t() 非函数 / 抛错 → 返回 fallback 不打断。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.src = JS_PATH.read_text(encoding="utf-8")

    def test_i18n_undefined_handled(self):
        # _t 函数包 try/catch 并检查 typeof
        self.assertIn('typeof i18n.t === "function"', self.src)
        self.assertIn("} catch (_e)", self.src)

    def test_returns_fallback_when_i18n_returns_key_back(self):
        # i18n.t(key) 找不到 key 时通常返回 key 自身（或空 / null）—— _t 检查
        self.assertIn("v !== key", self.src)


class TestCapturePhaseListener(unittest.TestCase):
    """capture phase keydown 监听 + 在 textarea 之外才拦截。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.src = JS_PATH.read_text(encoding="utf-8")

    def test_capture_phase_addEventListener(self):
        # third arg true (capture) —— 与 R140 feedback_submit_mode 同款
        self.assertRegex(
            self.src,
            r'document\.addEventListener\s*\(\s*"keydown"[^,]*,\s*_onKeydown\s*,\s*true\s*\)',
        )


if __name__ == "__main__":
    unittest.main()
