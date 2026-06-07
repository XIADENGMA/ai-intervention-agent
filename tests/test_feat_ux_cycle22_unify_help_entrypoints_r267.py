"""UX-cycle-22 · Track J (R267) · unify keyboard help 入口 +
expand `?` cheatsheet to cover all 10 shortcuts.

背景
----

`keyboard_shortcut_help.js` (`?` cheatsheet 真正的 modal overlay) 与
`keyboard-shortcuts.js` (`KeyboardShortcuts.init/showHelp`) 是两套并行
的"键盘帮助"系统：

| 系统 | 触发 | UI |
|------|------|-----|
| keyboard_shortcut_help.js | `?` (Shift+/) | 真 modal overlay (a11y + i18n + focus trap) |
| keyboard-shortcuts.js | `Cmd+/` / `Ctrl+/` | **console.debug + browser notification** |

`Cmd+/` 在 IDE webview / 关掉通知权限 / 浏览器关掉 devtools 的场景下
等于"按了没反应" —— 用户感受到 keyboard help 完全失效。

更严重的：cheatsheet (`?`) 只列出 6 个 shortcut，**完全缺失**
keyboard-shortcuts.js 注册的 5 个 system 级 shortcut：
- `Cmd+,` 打开设置
- `Cmd+/` 显示帮助（即两套系统的入口）
- `T` 切换主题
- `Tab` 下一个 task
- `Shift+Tab` 上一个 task

用户按 `?` 看到不全的列表反而被误导（"原来只有 6 个 shortcut"）。

修复
----

1. **统一两个入口**: `KeyboardShortcuts.showHelp()` 优先调用
   `window.AIIA_KEYBOARD_SHORTCUT_HELP.showOverlay()`，让 `Cmd+/` 也
   弹真正的 modal overlay。Overlay 不可用时退到原 console.debug fallback
   （保留 dev 视角的兜底）。
2. **扩展 SHORTCUTS 列表**: `?` cheatsheet 的 `SHORTCUTS` 数组从 6 条
   扩到 10 条，对齐 keyboard-shortcuts.js 注册的全部 system 级 shortcut。
3. **i18n keys 已存在**: `shortcuts.openSettings/nextTask/prevTask/toggleTheme`
   早在 keyboard-shortcuts.js `showHelp()` console 输出里就用了，4 条
   key 已在 en/zh-CN/zh-TW/pseudo 4 个 locale 全覆盖 —— 本 cycle 不需要
   新增 i18n key。

回归契约
--------

7 invariants：
- 4 条 SHORTCUTS 项必须存在于 `?` cheatsheet 的 SHORTCUTS 数组
- `_resolveShortcutLabel` 必须有 4 条新 literal key 分支（i18n 静态分析器
  需要 literal key 才能识别）
- `KeyboardShortcuts.showHelp()` 必须优先尝试 overlay 入口

Without these invariants, 一次"let me delete this unused notification
fallback" 或 "let me consolidate the literal i18n keys via a map" 重构
都能 silently 把 Cmd+/ 回退到 console-only / cheatsheet 回退到 6 条的
不完整列表，用户感受到 keyboard help 系统失效。
"""

from __future__ import annotations

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CHEATSHEET_JS = (
    REPO_ROOT
    / "src"
    / "ai_intervention_agent"
    / "static"
    / "js"
    / "keyboard_shortcut_help.js"
)
SHORTCUTS_JS = (
    REPO_ROOT
    / "src"
    / "ai_intervention_agent"
    / "static"
    / "js"
    / "keyboard-shortcuts.js"
)


class TestCheatsheetCoversSystemShortcuts(unittest.TestCase):
    """R267 · `?` cheatsheet 必须列出 keyboard-shortcuts.js 注册的全部
    system 级 shortcut，否则 discoverability 名存实亡."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = CHEATSHEET_JS.read_text(encoding="utf-8")

    def test_shortcuts_array_contains_open_settings(self) -> None:
        self.assertIn(
            '"shortcuts.openSettings"',
            self.js,
            "R267 cheatsheet SHORTCUTS 数组必须含 shortcuts.openSettings（Cmd+,）",
        )

    def test_shortcuts_array_contains_next_task(self) -> None:
        self.assertIn(
            '"shortcuts.nextTask"',
            self.js,
            "R267 cheatsheet SHORTCUTS 数组必须含 shortcuts.nextTask（Tab）",
        )

    def test_shortcuts_array_contains_prev_task(self) -> None:
        self.assertIn(
            '"shortcuts.prevTask"',
            self.js,
            "R267 cheatsheet SHORTCUTS 数组必须含 shortcuts.prevTask（Shift+Tab）",
        )

    def test_shortcuts_array_contains_toggle_theme(self) -> None:
        self.assertIn(
            '"shortcuts.toggleTheme"',
            self.js,
            "R267 cheatsheet SHORTCUTS 数组必须含 shortcuts.toggleTheme（T）",
        )


class TestResolveShortcutLabelHandlesNewKeys(unittest.TestCase):
    """R267 · `_resolveShortcutLabel` 必须有 4 条新 literal key 分支 ——
    i18n 静态分析器需要 literal key 才能识别（不能用动态 map）."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = CHEATSHEET_JS.read_text(encoding="utf-8")

    def test_resolve_handles_open_settings(self) -> None:
        self.assertIn(
            'if (i18nKey === "shortcuts.openSettings")',
            self.js,
            "R267 _resolveShortcutLabel 缺 shortcuts.openSettings literal 分支",
        )

    def test_resolve_handles_toggle_theme(self) -> None:
        self.assertIn(
            'if (i18nKey === "shortcuts.toggleTheme")',
            self.js,
            "R267 _resolveShortcutLabel 缺 shortcuts.toggleTheme literal 分支",
        )


class TestShowHelpDelegatesToOverlay(unittest.TestCase):
    """R267 · `KeyboardShortcuts.showHelp()` 必须优先调用 overlay 入口
    （`window.AIIA_KEYBOARD_SHORTCUT_HELP.showOverlay`），让 Cmd+/ 和
    `?` 走同一个 UI."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = SHORTCUTS_JS.read_text(encoding="utf-8")

    def test_show_help_calls_overlay_showOverlay(self) -> None:
        self.assertIn(
            "window.AIIA_KEYBOARD_SHORTCUT_HELP.showOverlay()",
            self.js,
            "R267 KeyboardShortcuts.showHelp() 必须调用 "
            "window.AIIA_KEYBOARD_SHORTCUT_HELP.showOverlay() —— "
            "Cmd+/ 不能停留在 console.debug-only 假死状态",
        )


if __name__ == "__main__":
    unittest.main()
