"""R272 / cycle-23 (exploratory audit, R264+R268 spillover):
``keyboard-shortcuts.js::escape`` handler 必须 delegate 到
``settingsManager.hideSettings()`` 与 ``closeImageModal()``，而**不能**
裸 ``classList.remove('show')`` / ``classList.add('hidden')`` 绕过两个
close 函数的完整清理逻辑。

Real bug fixed (R272)
---------------------

Pre-R272 实现：

.. code-block:: javascript

    this.register('escape', () => {
      const settingsPanel = document.getElementById('settings-panel');
      if (settingsPanel && settingsPanel.classList.contains('show')) {
        settingsPanel.classList.remove('show');
        settingsPanel.classList.add('hidden');
        return;
      }
      const imageModal = document.getElementById('image-modal');
      if (imageModal && imageModal.classList.contains('show')) {
        imageModal.classList.remove('show');
        return;
      }
    });

绕过 ``settingsManager.hideSettings()`` 漏掉的清理：

1. **焦点回归丢失** (R264 capture-activeElement): 用户从 Cmd+, 打开 →
   按 Esc → 焦点漂浮在 invisible 的 settings 内部元素上 (不能回到原触发
   元素 ``feedback-text`` 或 ``settings-btn``)
2. **背景 inert 不解除** (R237/R245 invariant): ``showSettings`` 在
   ``.container`` 兄弟节点设了 ``inert``，hideSettings 解除。绕过 →
   背景永久键盘锁死（用户必须再开一次 settings + 走正常 close path 才能
   recover）
3. **_settingsEscHandler 不解绑**: ``showSettings`` 内部注册了一个独立
   的 ESC keydown listener (按 ESC 关 panel)，hideSettings 解绑它。绕过
   → memory leak + 下次 ESC 触发 2 次 close logic
4. **container.style.overflow 不复原**: ``showSettings`` 设
   ``container.overflow = "hidden"`` 防滚动。绕过 → 滚动永久卡死

绕过 ``closeImageModal()`` 漏掉的清理：

1. **焦点回归丢失** (R263a capture-activeElement): 同上
2. **handleModalKeydown listener 不解绑**: image-modal 内 ESC 自闭合的
   listener 永久留在 document 上 → memory leak + 下次 ESC 二次触发
3. **_imageModalTabTrapHandler 不解绑**: Tab trap listener 永久留在
   document 上 → 影响其他 modal Tab 行为
4. **hidden attribute 不恢复**: R237 invariant 要求 dialog 关闭后必须
   ``setAttribute("hidden", "")``，使 screen reader 重新跳过整个 dialog；
   绕过 → SR 仍然能 "看到" 已关闭 dialog 的内容

Pattern lesson
--------------

任何 "close X dialog/modal/panel" 的 UX 入口（按钮 / Esc / 背景点击 /
keyboard shortcut）都必须**唯一 delegate** 到那个 dialog 的 ``closeXxx``
公开 API，不能裸 DOM 操作。否则未来 owner 给 close 函数加新清理逻辑时，
所有 entry point 都得记得跟着改 → 高出错率。R272 是这一规则的强制 invariant。

Invariant
---------

1. ``escape`` handler 必须包含 ``settingsManager.hideSettings()`` 调用
2. ``escape`` handler 必须包含 ``closeImageModal()`` 调用
3. ``escape`` handler 必须做 ``typeof`` 守卫（兼容 partial bundle / 延迟加载）
4. ``escape`` handler 内必须**不**包含裸 ``classList.add('hidden')`` 作为
   设置面板的关闭手段（仅允许在 fallback 分支内，且必须明确标注 fallback
   注释）
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SHORTCUTS_JS = (
    REPO_ROOT
    / "src"
    / "ai_intervention_agent"
    / "static"
    / "js"
    / "keyboard-shortcuts.js"
)


def _read_shortcuts_js() -> str:
    return SHORTCUTS_JS.read_text(encoding="utf-8")


def _extract_escape_handler_body(source: str) -> str:
    """提取 ``this.register('escape', () => { ... });`` 的函数体（包括
    嵌套 brace），让其他 register 调用（submit / help / settings / Tab）
    不污染 grep。"""
    match = re.search(
        r"this\.register\(\s*['\"]escape['\"]\s*,\s*\(?\)?\s*=>\s*\{",
        source,
    )
    if match is None:
        return ""
    start = match.end() - 1
    depth = 0
    for i in range(start, len(source)):
        ch = source[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return source[start : i + 1]
    return ""


class TestEscapeHandlerDelegatesSettings(unittest.TestCase):
    def test_escape_calls_settings_manager_hide_settings(self) -> None:
        source = _read_shortcuts_js()
        body = _extract_escape_handler_body(source)
        self.assertTrue(
            body,
            "R272: cannot locate ``this.register('escape', ...)`` handler "
            "in keyboard-shortcuts.js — did it get renamed or removed?",
        )
        self.assertIn(
            "settingsManager.hideSettings",
            body,
            "R272: escape handler 必须调 ``settingsManager.hideSettings()`` "
            "以触发完整清理：focus 回归 (R264) + inert 解除 (R237) + "
            "_settingsEscHandler 解绑 + overflow 复原。裸 classList swap "
            "全部漏掉。",
        )

    def test_escape_has_typeof_guard_for_settings_manager(self) -> None:
        source = _read_shortcuts_js()
        body = _extract_escape_handler_body(source)
        self.assertIn(
            "typeof settingsManager",
            body,
            "R272: settingsManager.hideSettings() 调用必须有 "
            "``typeof settingsManager !== 'undefined'`` 守卫，"
            "兼容 settings-manager.js 未加载的极端 race 场景。",
        )


class TestEscapeHandlerDelegatesImageModal(unittest.TestCase):
    def test_escape_calls_close_image_modal(self) -> None:
        source = _read_shortcuts_js()
        body = _extract_escape_handler_body(source)
        self.assertIn(
            "closeImageModal()",
            body,
            "R272: escape handler 必须调 ``closeImageModal()`` 以触发"
            "完整清理：focus 回归 (R263a) + handleModalKeydown / "
            "_imageModalTabTrapHandler 解绑 + hidden attribute 恢复 "
            "(R237)。",
        )

    def test_escape_has_typeof_guard_for_close_image_modal(self) -> None:
        source = _read_shortcuts_js()
        body = _extract_escape_handler_body(source)
        self.assertIn(
            "typeof closeImageModal",
            body,
            "R272: closeImageModal() 调用必须有 ``typeof closeImageModal === "
            "'function'`` 守卫，兼容 image-upload.js 未加载的场景。",
        )


class TestEscapeHandlerNoBareClassListAsPrimaryPath(unittest.TestCase):
    """Double-lock: 裸 ``classList.remove('show')`` / ``classList.add('hidden')``
    仅允许出现在 fallback 分支，且 fallback 必须显式标注。"""

    def test_escape_handler_contains_fallback_annotation(self) -> None:
        source = _read_shortcuts_js()
        body = _extract_escape_handler_body(source)
        self.assertIn(
            "Fallback",
            body,
            "R272: escape handler 仍可保留裸 classList swap 作为 fallback "
            "分支（settings-manager.js / image-upload.js 未加载的极端 race），"
            "但必须显式注释 ``Fallback`` 让 reviewer 一眼看出哪段是 primary "
            "path、哪段是 fallback。",
        )


class TestEscapeHandlerPreservesEarlyReturn(unittest.TestCase):
    """关键不变量：处理完一个 modal 必须 ``return`` 阻止继续走 image-modal
    分支；否则 settings 关闭后 image-modal 分支也会再被 evaluate（虽然不
    会误关，但增加冗余 DOM 查询）。"""

    def test_settings_branch_returns_early(self) -> None:
        source = _read_shortcuts_js()
        body = _extract_escape_handler_body(source)
        settings_block = re.search(
            r"settingsPanel.*?(?=\s*//\s*关闭图片|\s*const imageModal)",
            body,
            re.DOTALL,
        )
        self.assertIsNotNone(
            settings_block,
            "R272: cannot find settings-panel block before image-modal "
            "block; handler 结构可能已被重构 — 请同步更新本测试。",
        )
        assert settings_block is not None
        self.assertIn(
            "return",
            settings_block.group(0),
            "R272: settings-panel 分支必须 ``return`` 提前退出 escape "
            "handler，否则 image-modal 分支被冗余执行（虽不致命但浪费 "
            "DOM 查询）。",
        )


if __name__ == "__main__":
    unittest.main()
