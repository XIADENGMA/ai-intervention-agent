"""a11y-audit-cycle-8 Track B (R263) · image-modal focus 管理 + leak 修复。

背景
----

cycle-8 Track A 修了 image-modal 的 dialog semantics（role, aria-modal,
aria-label）。Track B 修 3 个 deeper a11y/性能 bug，在 audit 过 image-
upload.js 时发现：

**Bug 1 (R263a · leak)**: ``openImageModal`` 每次调用都 ``addEventListener
("click", anonymous, ...)``，N 次打开 → N 个监听器累积，永不解绑。

**Bug 2 (R263b · focus loss)**: modal 打开后焦点丢失，关闭后无法回到
触发元素 —— 违反 WAI-ARIA Dialog Pattern。

**Bug 3 (R263c · Tab escape)**: 无 Tab trap，键盘焦点可游走到背景
（虽然 aria-modal 让 AT 忽略背景）。

修复参考 ``keyboard_shortcut_help.js`` (cycle-1 Track A R255) 的模式：

- ``_imageModalPreviouslyFocusedElement`` 记录触发元素
- ``_imageModalTabTrapHandler`` 把所有 Tab/Shift+Tab 重定向回 close button
- ``_initImageModalOnce`` (DOMContentLoaded) 只绑一次背景 click handler

回归契约
--------

8 invariants 防 leak 回归 + 保护 focus pattern。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

JS_PATH = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "ai_intervention_agent"
    / "static"
    / "js"
    / "image-upload.js"
)


class TestImageModalEventLeakFix(unittest.TestCase):
    """R263a · 防止 background click handler 累积"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = JS_PATH.read_text(encoding="utf-8")

    def test_init_function_exists(self) -> None:
        self.assertIn(
            "_initImageModalOnce",
            self.js,
            "R263a leak 修复缺失：需要 _initImageModalOnce() 在 DOMContentLoaded"
            " 时只绑一次背景点击 handler",
        )

    def test_init_uses_data_attr_guard(self) -> None:
        self.assertRegex(
            self.js,
            r"modal\.dataset\.aiiaInited\s*=",
            "R263a 缺 data-attr 重入保护，防 _initImageModalOnce 被调用多次",
        )

    def test_openimagemodal_does_not_add_click_listener(self) -> None:
        # 找 openImageModal 函数体（从 `function openImageModal` 到下一个
        # `function ` 顶层定义）
        body_match = re.search(
            r"function\s+openImageModal[\s\S]*?(?=\nfunction\s+)", self.js
        )
        self.assertIsNotNone(body_match, "找不到 function openImageModal")
        assert body_match is not None
        body = body_match.group(0)
        # 函数内部不再 addEventListener("click", ...) — 那是 R263a 旧 leak
        self.assertNotRegex(
            body,
            r'addEventListener\(\s*[\'"]click[\'"]',
            "R263a leak 复发：openImageModal 内部不应再 addEventListener('click', ...) "
            "— 应在 _initImageModalOnce 里绑一次",
        )


class TestImageModalFocusReturn(unittest.TestCase):
    """R263b · focus 触发元素回归"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = JS_PATH.read_text(encoding="utf-8")

    def test_previously_focused_var_exists(self) -> None:
        self.assertIn(
            "_imageModalPreviouslyFocusedElement",
            self.js,
            "R263b: 缺 _imageModalPreviouslyFocusedElement 变量记录触发元素",
        )

    def test_open_captures_active_element(self) -> None:
        self.assertRegex(
            self.js,
            r"_imageModalPreviouslyFocusedElement\s*=\s*document\.activeElement",
            "R263b: openImageModal 应在 show modal 之前记录 document.activeElement",
        )

    def test_close_restores_focus(self) -> None:
        # 关闭时必须有 document.contains 守护 + try/catch + 复原 focus + 重置 null
        self.assertRegex(
            self.js,
            r"document\.contains\(\s*_imageModalPreviouslyFocusedElement\s*\)",
            "R263b: closeImageModal 缺 document.contains 守护（防元素已被移除）",
        )
        self.assertRegex(
            self.js,
            r"_imageModalPreviouslyFocusedElement\s*=\s*null",
            "R263b: closeImageModal 应在 restore 后置 null（防 next open 引用旧值）",
        )


class TestImageModalTabTrap(unittest.TestCase):
    """R263c · Tab 焦点不逸出"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = JS_PATH.read_text(encoding="utf-8")

    def test_tab_trap_handler_exists(self) -> None:
        self.assertIn(
            "_imageModalTabTrapHandler",
            self.js,
            "R263c: 缺 _imageModalTabTrapHandler — Tab 焦点会逸出 modal",
        )

    def test_tab_trap_filters_tab_key_and_prevent_default(self) -> None:
        m = re.search(
            r"function\s+_imageModalTabTrapHandler[\s\S]*?(?=\nfunction\s+|\n\}\s*\n)",
            self.js,
        )
        self.assertIsNotNone(m, "找不到 _imageModalTabTrapHandler 函数体")
        assert m is not None
        body = m.group(0)
        self.assertRegex(
            body,
            r'event\.key\s*!==\s*[\'"]Tab[\'"]',
            "R263c: _imageModalTabTrapHandler 应短路非 Tab 事件",
        )
        self.assertIn(
            "event.preventDefault()",
            body,
            "R263c: Tab handler 应 preventDefault 防焦点逸出",
        )

    def test_open_close_register_unregister_tab_handler(self) -> None:
        # open 必 add，close 必 remove，否则就是新版 R263a-style leak
        self.assertIn(
            'addEventListener("keydown", _imageModalTabTrapHandler)',
            self.js,
            "R263c: openImageModal 缺 addEventListener Tab trap",
        )
        self.assertIn(
            'removeEventListener("keydown", _imageModalTabTrapHandler)',
            self.js,
            "R263c: closeImageModal 缺 removeEventListener Tab trap（会 leak）",
        )


if __name__ == "__main__":
    unittest.main()
