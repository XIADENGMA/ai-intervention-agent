"""a11y-audit-cycle-1 Track B (R256) · prefers-contrast: more 支持回归测试。

背景
----

a11y-audit-cycle-1 §7 backlog 列出 prefers-contrast 支持。Track A 关
overlay focus 的同 cycle bonus ship。

prefers-contrast 是 WCAG 2.1 SC 1.4.11 (Non-text Contrast) 配套的
user-preference 媒体查询，让 web app 响应用户开启的：

* macOS: System Settings → Accessibility → Display → **Increase contrast**
* Windows: Settings → Accessibility → **Contrast themes**
* Chromium: emulate via DevTools "Rendering" panel → ``prefers-contrast: more``

我们的策略
----------

不在常规模式下硬加视觉冗余（focus ring 仍是 2px 主品牌色），但在
用户**显式表达更高对比偏好**时，把 focus indicator 升级为：

1. 4px outline-width（vs 2px 常规）
2. 3px outline-offset（vs 2px 常规）  —— 离元素更远，对比更强
3. ``outline-color: Highlight`` —— 系统高对比 highlight 色，避免
   品牌色与用户已选高对比方案冲突

回归契约
--------

1. ``main.css`` 含 ``@media (prefers-contrast: more)`` block
2. block 在 ``@layer a11y { ... }`` 内 —— 不被普通组件 CSS 覆盖
3. block 含 outline-width: 4px
4. block 含 outline-offset: 3px
5. block 含 outline-color: Highlight
6. block 标注 R256 + a11y-audit-cycle-1 Track B
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

CSS_PATH = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "ai_intervention_agent"
    / "static"
    / "css"
    / "main.css"
)


class TestPrefersContrastMore(unittest.TestCase):
    """R256 · prefers-contrast: more focus indicator upgrade."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.css = CSS_PATH.read_text(encoding="utf-8")

    def test_media_query_block_exists(self) -> None:
        self.assertIn(
            "@media (prefers-contrast: more)",
            self.css,
            "main.css 必须含 @media (prefers-contrast: more) block",
        )

    def test_media_query_inside_a11y_layer(self) -> None:
        # 用 regex 匹配最后一个 @layer a11y 块包住 prefers-contrast
        # @layer a11y { ... @media (prefers-contrast: more) ... }
        # 由于嵌套规则可能复杂，我们用更简单的策略：
        # 找 @media (prefers-contrast: more) 位置，往前找最近的
        # @layer 行（应该是 a11y）
        media_idx = self.css.find("@media (prefers-contrast: more)")
        self.assertGreater(media_idx, -1)
        preceding = self.css[:media_idx]
        last_layer_idx = preceding.rfind("@layer ")
        self.assertGreater(
            last_layer_idx,
            -1,
            "prefers-contrast 块必须出现在某个 @layer 块内",
        )
        layer_line = self.css[last_layer_idx : last_layer_idx + 50]
        self.assertIn(
            "@layer a11y",
            layer_line,
            "prefers-contrast 块必须 in @layer a11y（保证不被普通组件 "
            "CSS 覆盖；@layer 优先级顺序由 CSS 标准保证）",
        )

    def test_outline_width_thicker(self) -> None:
        block = self._extract_media_block()
        self.assertIn(
            "outline-width: 4px",
            block,
            "prefers-contrast: more 必须把 outline 加粗到 4px"
            "（常规 2px 在 High Contrast 模式下可能看不清）",
        )

    def test_outline_offset_increased(self) -> None:
        block = self._extract_media_block()
        self.assertIn(
            "outline-offset: 3px",
            block,
            "prefers-contrast: more 必须增大 outline-offset 到 3px"
            "（离元素更远 = 与背景对比更强）",
        )

    def test_outline_color_uses_system_highlight(self) -> None:
        block = self._extract_media_block()
        self.assertIn(
            "outline-color: Highlight",
            block,
            "prefers-contrast: more 必须用系统 Highlight 色，复用用户"
            "已选高对比方案，避免品牌色与之冲突",
        )

    def test_media_query_targets_focus_visible(self) -> None:
        block = self._extract_media_block()
        self.assertIn(
            ":focus-visible",
            block,
            "prefers-contrast 升级必须针对 :focus-visible，不影响 "
            "鼠标点击焦点（与现有 a11y 焦点策略一致）",
        )

    def test_r256_documentation_tag_present(self) -> None:
        # 标注 cycle + R-id 让 git blame / grep 可定位来源
        # 找 prefers-contrast block 前方的注释段
        media_idx = self.css.find("@media (prefers-contrast: more)")
        self.assertGreater(media_idx, -1)
        # 往回 800 字符内找注释引用
        context = self.css[max(0, media_idx - 800) : media_idx]
        # 至少有 R256 或 a11y-audit-cycle-1 Track B 中的一个
        has_rid = "R256" in context
        has_cycle = "a11y-audit-cycle-1 Track B" in context
        self.assertTrue(
            has_rid or has_cycle,
            "prefers-contrast block 前方必须有注释标注 R256 或 "
            "a11y-audit-cycle-1 Track B（git blame archaeology）",
        )

    def _extract_media_block(self) -> str:
        """抓 @media (prefers-contrast: more) { ... } 的整个 body。"""
        match = re.search(
            r"@media \(prefers-contrast: more\)\s*\{(.*?)\n\s*\}\s*\n\s*\}",
            self.css,
            re.DOTALL,
        )
        # 上面 regex 期望嵌套在 @layer { @media { ... } } 内，end 匹配
        # ``}\n  }`` 即 @media 闭 + @layer 闭。如果失败 fallback 抓一对
        # 大括号
        if match:
            return match.group(1)
        # fallback brace counting
        start = self.css.find("@media (prefers-contrast: more)")
        assert start != -1
        open_idx = self.css.find("{", start)
        depth = 0
        for i in range(open_idx, len(self.css)):
            ch = self.css[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return self.css[open_idx + 1 : i]
        raise AssertionError("无法解析 @media (prefers-contrast: more) block")


if __name__ == "__main__":
    unittest.main()
