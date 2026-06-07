"""a11y-audit-cycle-22 · Track F (R264) · settings-panel + code-paste-modal
focus capture-activeElement 升级。

背景
----

cycle-8 R263a/b/c 把 ``image-modal`` 升级到 WAI-ARIA Dialog Pattern：
``_imageModalPreviouslyFocusedElement = document.activeElement`` (打开时
快照) + ``document.contains(prev) ? prev.focus() : fallback`` (关闭时回归)。
cycle-1 R255 把 ``keyboard_shortcut_help`` 升级到同套模式。

cycle-22 / cr51 follow-up #1 把同套 capture-activeElement 模式扩展到剩下
两个 hardcode focus restore 的 dialog：

1. ``src/.../js/settings-manager.js`` ``showSettings()`` / ``hideSettings()``
   关闭时永远跳回 ``#settings-btn``，丢失键盘快捷键 / 多 task tab 场景的
   原始触发位置。
2. ``src/.../js/app.js`` ``openCodePasteModal()`` / ``closeCodePasteModal()``
   关闭时永远跳回 ``#feedback-text``，多 task tab 下取错 textarea，
   quick-phrases 触发流被打断。

回归契约
--------

8 invariants：
- settings-panel: showSettings 快照 + hideSettings ``document.contains`` 兜底
- code-paste-modal: openCodePasteModal 快照 + closeCodePasteModal 同样兜底
- 两者都保留 hardcode fallback 路径（旧行为）作为最后一道防线

Without these invariants, a routine refactor like "let me simplify by
removing the unused ``_previouslyFocusedElement`` field" would silently
revert the upgrade to the pre-cycle-22 hardcoded-restore behavior, and
the user would notice focus jumping in subtle "feels-wrong" ways that
no other test would catch (the existing R263 tests only guard image-modal,
not settings-panel or code-paste-modal).
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

SETTINGS_JS_PATH = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "ai_intervention_agent"
    / "static"
    / "js"
    / "settings-manager.js"
)

APP_JS_PATH = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "ai_intervention_agent"
    / "static"
    / "js"
    / "app.js"
)


class TestSettingsPanelFocusCapture(unittest.TestCase):
    """settings-panel showSettings/hideSettings capture-activeElement 升级。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = SETTINGS_JS_PATH.read_text(encoding="utf-8")

    def test_show_settings_captures_active_element(self) -> None:
        """``showSettings()`` 必须在打开 panel 前快照 ``document.activeElement``."""
        body_match = re.search(
            r"async\s+showSettings\s*\(\s*\)\s*\{[\s\S]*?(?=\n  applySettingsTheme\b)",
            self.js,
        )
        self.assertIsNotNone(body_match, "找不到 async showSettings() 函数体")
        assert body_match is not None
        body = body_match.group(0)
        self.assertRegex(
            body,
            r"this\._previouslyFocusedElement\s*=\s*document\.activeElement",
            "R264 settings-panel 缺 capture：showSettings 必须 "
            "this._previouslyFocusedElement = document.activeElement",
        )

    def test_hide_settings_checks_document_contains(self) -> None:
        """``hideSettings()`` 关闭后必须 ``document.contains(prev)`` 兜底，
        防止快照元素已脱离 DOM（如 SSE 重渲染）时盲调 ``prev.focus()``."""
        body_match = re.search(
            r"hideSettings\s*\(\s*\)\s*\{[\s\S]*?(?=\n  async testNotification\b)",
            self.js,
        )
        self.assertIsNotNone(body_match, "找不到 hideSettings() 函数体")
        assert body_match is not None
        body = body_match.group(0)
        self.assertRegex(
            body,
            r"document\.contains\(\s*prev\s*\)",
            "R264 settings-panel hideSettings 缺 document.contains(prev) 兜底",
        )

    def test_hide_settings_preserves_fallback_to_settings_btn(self) -> None:
        """``hideSettings()`` 必须保留 ``#settings-btn`` 作 fallback —— 升级
        前的语义不能 silent 丢失（如果原触发元素失踪/inert 时）。"""
        body_match = re.search(
            r"hideSettings\s*\(\s*\)\s*\{[\s\S]*?(?=\n  async testNotification\b)",
            self.js,
        )
        self.assertIsNotNone(body_match, "找不到 hideSettings() 函数体")
        assert body_match is not None
        body = body_match.group(0)
        self.assertIn(
            'document.getElementById("settings-btn")',
            body,
            "R264 settings-panel hideSettings 应保留 #settings-btn fallback "
            "—— 升级前语义",
        )

    def test_hide_settings_clears_captured_ref_to_avoid_stale(self) -> None:
        """``hideSettings()`` 必须在恢复后 ``_previouslyFocusedElement = null``，
        防止下次 showSettings 之前 stale 引用持有 detached DOM（leak）。"""
        body_match = re.search(
            r"hideSettings\s*\(\s*\)\s*\{[\s\S]*?(?=\n  async testNotification\b)",
            self.js,
        )
        self.assertIsNotNone(body_match, "找不到 hideSettings() 函数体")
        assert body_match is not None
        body = body_match.group(0)
        self.assertRegex(
            body,
            r"this\._previouslyFocusedElement\s*=\s*null",
            "R264 settings-panel hideSettings 必须 clear _previouslyFocusedElement "
            "—— 防 stale DOM 引用 leak",
        )


class TestCodePasteModalFocusCapture(unittest.TestCase):
    """code-paste-modal open/close capture-activeElement 升级。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = APP_JS_PATH.read_text(encoding="utf-8")

    def test_module_declares_previously_focused_state_var(self) -> None:
        """模块顶层必须有 ``_codePasteModalPreviouslyFocusedElement`` 全局
        state —— pattern 对齐 ``_imageModalPreviouslyFocusedElement``。"""
        self.assertRegex(
            self.js,
            r"let\s+_codePasteModalPreviouslyFocusedElement\s*=\s*null",
            "R264 code-paste-modal 缺顶层 state var "
            "_codePasteModalPreviouslyFocusedElement",
        )

    def test_open_code_paste_modal_captures_active_element(self) -> None:
        """``openCodePasteModal()`` 必须 snapshot ``document.activeElement``."""
        body_match = re.search(
            r"function\s+openCodePasteModal\s*\([^)]*\)\s*\{[\s\S]*?(?=\nfunction\s+closeCodePasteModal\b)",
            self.js,
        )
        self.assertIsNotNone(body_match, "找不到 function openCodePasteModal")
        assert body_match is not None
        body = body_match.group(0)
        self.assertRegex(
            body,
            r"_codePasteModalPreviouslyFocusedElement\s*=\s*document\.activeElement",
            "R264 openCodePasteModal 缺 capture：必须 "
            "_codePasteModalPreviouslyFocusedElement = document.activeElement",
        )

    def test_close_code_paste_modal_checks_document_contains(self) -> None:
        """``closeCodePasteModal()`` 必须 ``document.contains(prev)`` 兜底."""
        body_match = re.search(
            r"function\s+closeCodePasteModal\s*\(\s*\)\s*\{[\s\S]*?(?=\n/\*\*|\nfunction\s+)",
            self.js,
        )
        self.assertIsNotNone(body_match, "找不到 function closeCodePasteModal")
        assert body_match is not None
        body = body_match.group(0)
        self.assertRegex(
            body,
            r"document\.contains\(\s*prev\s*\)",
            "R264 closeCodePasteModal 缺 document.contains(prev) 兜底",
        )

    def test_close_code_paste_modal_preserves_fallback_to_feedback_text(
        self,
    ) -> None:
        """``closeCodePasteModal()`` 必须保留 ``#feedback-text`` fallback ——
        升级前语义不能 silent 丢失。"""
        body_match = re.search(
            r"function\s+closeCodePasteModal\s*\(\s*\)\s*\{[\s\S]*?(?=\n/\*\*|\nfunction\s+)",
            self.js,
        )
        self.assertIsNotNone(body_match, "找不到 function closeCodePasteModal")
        assert body_match is not None
        body = body_match.group(0)
        self.assertIn(
            'document.getElementById("feedback-text")',
            body,
            "R264 closeCodePasteModal 应保留 #feedback-text fallback —— 升级前语义",
        )


if __name__ == "__main__":
    unittest.main()
