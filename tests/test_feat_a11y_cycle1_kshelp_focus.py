"""a11y-audit-cycle-1 Track A (R255) · keyboard cheatsheet overlay 焦点管理回归测试。

背景
----

R144 落地了 ``?`` cheatsheet overlay，已有 a11y 基础：
``role="dialog"`` + ``aria-modal="true"`` + ``aria-label`` + 卡片
auto-focus。**但** a11y-audit-cycle-1 §2 矩阵对比 settings panel 后
发现 3 个缺失：

1. **close 不 restore opener focus** —— WAI-ARIA Authoring Practices
   规定 modal 关闭时焦点要回到打开它的元素（settings panel 已通过
   ``settingsBtn.focus()`` 做到）
2. **Tab 不 trap 在 overlay** —— Tab 键会逃逸到背景 page；kshelp
   overlay 内无任何 focusable，trap 策略 = 双方向都 refocus card
3. **背景 sibling 不 inert** —— 屏幕阅读器和键盘都能透过 overlay
   访问背景内容；settings panel 用 ``_setContainerSiblingsInert``

本次 ship 让 kshelp 与 settings panel a11y 完全对齐。

回归契约（共 7 cases）
-----------------------

1. ``_previouslyFocusedElement`` 模块作用域变量存在 + 注释 R255
2. ``showOverlay`` 在 append DOM **之前** 读 ``document.activeElement``
3. ``showOverlay`` 调用 ``_setContainerSiblingsInert(true)``
4. ``hideOverlay`` 调用 ``_setContainerSiblingsInert(false)``
5. ``hideOverlay`` restore ``previouslyFocused`` 元素的 focus
6. ``_onTabInOverlay`` keydown listener handles Tab keys: 0 focusables 时
   preventDefault + refocus card
7. test API 暴露 ``_onTabInOverlay`` + ``_setContainerSiblingsInert``
   供 future test harness
"""

from __future__ import annotations

import unittest
from pathlib import Path

JS_PATH = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "ai_intervention_agent"
    / "static"
    / "js"
    / "keyboard_shortcut_help.js"
)


class TestKshelpFocusManagement(unittest.TestCase):
    """R255 · kshelp focus return + Tab trap + sibling inert."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = JS_PATH.read_text(encoding="utf-8")

    # ------------------------------------------------------------------
    # 1. 模块作用域 _previouslyFocusedElement
    # ------------------------------------------------------------------

    def test_previously_focused_element_variable_exists(self) -> None:
        self.assertIn(
            "var _previouslyFocusedElement = null;",
            self.js,
            "应有模块作用域变量记忆 opener element",
        )

    def test_previously_focused_element_has_r255_doc(self) -> None:
        self.assertIn("a11y-audit-cycle-1 Track A (R255)", self.js)
        self.assertIn("_previouslyFocusedElement", self.js)

    # ------------------------------------------------------------------
    # 2. showOverlay 在挂 DOM 之前读 activeElement
    # ------------------------------------------------------------------

    def test_show_overlay_captures_active_element_before_dom_append(self) -> None:
        body = _function_body(self.js, "function showOverlay()")
        # activeElement 读取必须出现在 appendChild 之前
        idx_active = body.find("_previouslyFocusedElement = document.activeElement")
        idx_append = body.find("document.body.appendChild(overlay)")
        self.assertGreater(
            idx_active,
            -1,
            "showOverlay 必须读 document.activeElement",
        )
        self.assertGreater(idx_append, -1, "showOverlay 必须挂 overlay")
        self.assertLess(
            idx_active,
            idx_append,
            "activeElement 必须在 appendChild **之前** 读取，"
            "否则 focus 已被 DOM 操作转移",
        )

    # ------------------------------------------------------------------
    # 3 + 4. showOverlay/hideOverlay 调用 _setContainerSiblingsInert
    # ------------------------------------------------------------------

    def test_show_overlay_inerts_container_siblings(self) -> None:
        body = _function_body(self.js, "function showOverlay()")
        self.assertIn(
            "_setContainerSiblingsInert(true)",
            body,
            "showOverlay 必须 inert 背景 .container children",
        )

    def test_hide_overlay_clears_container_siblings_inert(self) -> None:
        body = _function_body(self.js, "function hideOverlay()")
        self.assertIn(
            "_setContainerSiblingsInert(false)",
            body,
            "hideOverlay 必须清掉 .container children 的 inert",
        )

    # ------------------------------------------------------------------
    # 5. hideOverlay restore 焦点 + DOM contains guard
    # ------------------------------------------------------------------

    def test_hide_overlay_restores_previously_focused(self) -> None:
        body = _function_body(self.js, "function hideOverlay()")
        self.assertIn(
            "_previouslyFocusedElement",
            body,
            "hideOverlay 必须引用 _previouslyFocusedElement",
        )
        self.assertIn(
            "prev.focus",
            body,
            "hideOverlay 必须 call prev.focus()",
        )
        # 防 stale element error
        self.assertIn(
            "document.contains(prev)",
            body,
            "hideOverlay 必须用 document.contains 保护，避免对已移除的元素 focus",
        )

    def test_hide_overlay_resets_previously_focused_after_use(self) -> None:
        body = _function_body(self.js, "function hideOverlay()")
        self.assertIn(
            "_previouslyFocusedElement = null",
            body,
            "hideOverlay 必须把 _previouslyFocusedElement 复位到 null，"
            "避免后续 showOverlay 调用读到上一次的 stale 引用",
        )

    # ------------------------------------------------------------------
    # 6. _onTabInOverlay 行为契约
    # ------------------------------------------------------------------

    def test_on_tab_in_overlay_function_exists(self) -> None:
        self.assertIn("function _onTabInOverlay(event)", self.js)

    def test_on_tab_in_overlay_filters_tab_key_only(self) -> None:
        body = _function_body(self.js, "function _onTabInOverlay(event)")
        self.assertIn(
            'event.key !== "Tab"',
            body,
            "_onTabInOverlay 必须只处理 Tab 键，让其他键正常 dispatch",
        )

    def test_on_tab_in_overlay_short_circuits_when_overlay_absent(self) -> None:
        body = _function_body(self.js, "function _onTabInOverlay(event)")
        self.assertIn(
            "if (!overlay) return",
            body,
            "_onTabInOverlay 必须在 overlay 不存在时短路（防 stale listener "
            "在 hide 后仍 fire 的极端 race）",
        )

    def test_on_tab_in_overlay_traps_focus_to_card(self) -> None:
        body = _function_body(self.js, "function _onTabInOverlay(event)")
        self.assertIn(
            "event.preventDefault()",
            body,
            "_onTabInOverlay 必须 preventDefault 阻止 Tab 默认行为",
        )
        self.assertIn(
            "card.focus",
            body,
            "_onTabInOverlay 必须 refocus card（kshelp 0 focusables，双方向都 cycle 回 card）",
        )

    def test_show_overlay_registers_tab_trap_listener(self) -> None:
        body = _function_body(self.js, "function showOverlay()")
        self.assertIn(
            'document.addEventListener("keydown", _onTabInOverlay, true)',
            body,
            "showOverlay 必须挂 _onTabInOverlay 在 capture phase 上",
        )

    def test_hide_overlay_unregisters_tab_trap_listener(self) -> None:
        body = _function_body(self.js, "function hideOverlay()")
        self.assertIn(
            'document.removeEventListener("keydown", _onTabInOverlay, true)',
            body,
            "hideOverlay 必须卸 _onTabInOverlay listener，否则内存泄漏 + "
            "stale handler 风险",
        )

    # ------------------------------------------------------------------
    # 7. test API 暴露
    # ------------------------------------------------------------------

    def test_test_api_exposes_focus_helpers(self) -> None:
        # 抓 window.AIIA_KEYBOARD_SHORTCUT_HELP = { ... } 对象
        idx = self.js.find("window.AIIA_KEYBOARD_SHORTCUT_HELP =")
        self.assertGreater(idx, -1, "test API 入口必须存在")
        # 检查暴露字段
        api_block = self.js[idx : idx + 1500]
        self.assertIn(
            "_onTabInOverlay: _onTabInOverlay",
            api_block,
            "test API 必须暴露 _onTabInOverlay 供 future harness 测试",
        )
        self.assertIn(
            "_setContainerSiblingsInert: _setContainerSiblingsInert",
            api_block,
            "test API 必须暴露 _setContainerSiblingsInert 供测试",
        )

    # ------------------------------------------------------------------
    # 8. _setContainerSiblingsInert + _safelySetInert 实现
    # ------------------------------------------------------------------

    def test_set_container_siblings_inert_iterates_children(self) -> None:
        body = _function_body(self.js, "function _setContainerSiblingsInert(value)")
        self.assertIn(
            'document.querySelector(".container")',
            body,
            "必须 query .container",
        )
        self.assertIn(
            "container.children",
            body,
            "必须遍历 children",
        )
        self.assertIn(
            "_safelySetInert",
            body,
            "必须用 _safelySetInert helper（同 settings-manager.js 模式）",
        )

    def test_safely_set_inert_has_attribute_fallback(self) -> None:
        body = _function_body(self.js, "function _safelySetInert(el, value)")
        self.assertIn("el.inert = value", body, "首选 setter 路径")
        self.assertIn(
            'el.setAttribute("inert", "")',
            body,
            "fallback 走 attribute setter（老浏览器）",
        )


# ----------------------------------------------------------------------
# helper
# ----------------------------------------------------------------------


def _function_body(js: str, signature: str) -> str:
    """从 ``signature`` 起截取整个 brace-balanced function body。

    用 brace counting 避免 regex greedy 问题（cycle-9 R254 lesson #1
    引用的同款问题）。
    """
    start = js.find(signature)
    assert start != -1, f"signature 未找到: {signature}"
    open_idx = js.find("{", start)
    assert open_idx != -1, f"signature 后无 brace: {signature}"
    depth = 0
    for i in range(open_idx, len(js)):
        ch = js[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return js[open_idx : i + 1]
    raise AssertionError(f"未找到匹配的 closing brace: {signature}")


if __name__ == "__main__":
    unittest.main()
