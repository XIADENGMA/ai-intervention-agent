"""a11y-audit-cycle-5 Track C (R259g) · 组件 :focus-visible 必须用
``--focus-ring-color`` token。

背景
----

cycle-3 R258 引入 ``--focus-ring-color`` 语义 token，dark = ``#a855f7``
（reuses primary-500），light = ``#b35a3c``（deeper Anthropic orange，3.78:1
WCAG 1.4.11 compliant on bg-primary）。``@layer a11y :focus-visible`` 全局
规则用了新 token，但 8 个具体组件还在硬绑 ``var(--primary-500)`` 或
``var(--primary-500, #8b5cf6)``，导致 light theme 用户看到的不是 cycle-3
的 WCAG-compliant 橙色而是 ``#d97757`` (2.50:1 FAIL)。

cycle-5 Track C 把这 8 个组件迁到 ``var(--focus-ring-color, var(--primary-500
, fallback))`` 三级 fallback，自动继承 R258。

回归契约
--------

8 个组件 selector 必须出现在 ``var(--focus-ring-color, ...)`` 形式的
``outline:`` 规则中：

1. ``.upload-btn-label``
2. ``.custom-sound-btn``
3. ``.quick-phrases-add-btn``
4. ``.quick-phrases-export-btn``
5. ``.quick-phrases-import-btn``
6. ``.quick-phrase-chip``
7. ``.quick-phrase-chip-edit``
8. ``.quick-phrase-chip-delete``

未来如果有新组件 ``:focus-visible``，按 §3.ter / §3.quater CONTRIBUTING
checklist 也应该跟随这个模式。
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

# cycle-5 Track C 迁移的 8 个 selector
REQUIRED_SELECTORS = [
    ".upload-btn-label",
    ".custom-sound-btn",
    ".quick-phrases-add-btn",
    ".quick-phrases-export-btn",
    ".quick-phrases-import-btn",
    ".quick-phrase-chip",
    ".quick-phrase-chip-edit",
    ".quick-phrase-chip-delete",
]


def _extract_focus_visible_rules(css: str) -> list[tuple[str, str]]:
    """提取 ``selector1:focus-visible[, selector2:focus-visible]* { body }``
    形式所有规则，返回 (selectors_raw, body) 元组列表。

    selectors_raw 是逗号分隔的原始字符串（含 ``:focus-visible``）；body 是
    ``{ ... }`` 内的内容。
    """
    rules: list[tuple[str, str]] = []
    # 匹配 selector chain（可能多个逗号分隔，可能带 :focus-visible）+ 规则体
    # 用非贪心 .*? 跨行匹配大括号内容
    pattern = re.compile(
        r"((?:[\w.#\-:_, \t\n*+~>()=\[\]\"]+?:focus-visible[ \t]*,?[ \t\n]*)+)\{([^{}]*)\}",
        re.MULTILINE,
    )
    for match in pattern.finditer(css):
        rules.append((match.group(1).strip(), match.group(2)))
    return rules


def _has_focus_ring_color_var(body: str) -> bool:
    """检查规则体是否包含 ``var(--focus-ring-color`` 引用。"""
    return "var(--focus-ring-color" in body


class TestRequiredComponentsUseFocusRingColor(unittest.TestCase):
    """R259g · 8 个组件的 :focus-visible 必须用 var(--focus-ring-color)。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.css = CSS_PATH.read_text(encoding="utf-8")
        cls.rules = _extract_focus_visible_rules(cls.css)

    def test_each_required_selector_has_focus_ring_color_rule(self) -> None:
        for selector in REQUIRED_SELECTORS:
            with self.subTest(selector=selector):
                matching_rules = [
                    body for (selectors, body) in self.rules if selector in selectors
                ]
                self.assertNotEqual(
                    matching_rules,
                    [],
                    f"组件 {selector}:focus-visible 没找到匹配的 CSS 规则",
                )
                # 至少一条匹配规则必须用 --focus-ring-color
                self.assertTrue(
                    any(_has_focus_ring_color_var(body) for body in matching_rules),
                    f"组件 {selector}:focus-visible 应当用 var(--focus-ring-color, "
                    f"var(--primary-500, fallback)) 三级 fallback，继承 cycle-3 "
                    f"R258 WCAG-compliant focus 色。当前规则体：\n  "
                    + "\n  ".join(matching_rules),
                )


class TestRegressionFloor(unittest.TestCase):
    """R259g 防止 cycle-5 之后 ``--focus-ring-color`` 使用计数倒退。

    cycle-3 R258: @layer a11y 1 处
    cycle-5 R259g: 8 component 处 → total ≥ 5（按规则块数算，因 8 selector
    被合并到 4 rules + global a11y rule = 5）
    """

    def test_focus_ring_color_usage_count_floor(self) -> None:
        css = CSS_PATH.read_text(encoding="utf-8")
        count = css.count("var(--focus-ring-color")
        self.assertGreaterEqual(
            count,
            5,
            f"CSS 中 var(--focus-ring-color) 引用应 ≥ 5（cycle-3 1 处 + cycle-5 "
            f"4+ 处）。当前 {count}。若数量下降说明组件迁移被还原，违反 R259g。",
        )


if __name__ == "__main__":
    unittest.main()
