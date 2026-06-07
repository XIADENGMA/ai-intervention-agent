"""a11y-audit-cycle-3 Track A (R258) · WCAG 1.4.11 focus ring contrast invariants。

背景
----

cycle-2 完成 1.4.3 (text contrast)。cycle-3 进入 1.4.11 (UI 组件 /
non-text contrast)，覆盖 focus indicator、border、状态指示器等。

cycle-3 §2 audit finding：
- dark ``--primary-500`` #a855f7 on bg-primary  = 4.38:1 ✅
- dark ``--primary-500`` on bg-secondary       = 3.84:1 ✅
- **light ``--primary-500`` #d97757 on bg-primary  = 2.50:1 ❌**
- **light ``--primary-500`` on bg-secondary       = 2.96:1 ❌**

Track A 落地：
1. 新 token ``--focus-ring-color`` 单一职责（不与 brand 色绑死）：
   - dark = ``#a855f7`` (reuse, 已合规)
   - light = ``#b35a3c`` (深 Anthropic orange, 3.78/4.49 ≥ 3:1)
2. ``:focus-visible`` rule 改用 ``var(--focus-ring-color, var(--primary-500, currentColor))``
3. 媒体查询 ``(prefers-color-scheme: light)`` block mirror

回归契约（共 6 cases）
----------------------

针对 WCAG 1.4.11 ≥ 3:1，所有 token × bg 组合检查 + rule 集成验证。
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

WCAG_UI_THRESHOLD = 3.0  # SC 1.4.11 Non-text Contrast


def _parse_hex(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _relative_luminance(rgb: tuple[int, int, int]) -> float:
    def ch(c: int) -> float:
        cl = c / 255
        return cl / 12.92 if cl <= 0.03928 else ((cl + 0.055) / 1.055) ** 2.4

    r, g, b = (ch(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(fg: str, bg: str) -> float:
    l1 = _relative_luminance(_parse_hex(fg))
    l2 = _relative_luminance(_parse_hex(bg))
    if l1 < l2:
        l1, l2 = l2, l1
    return (l1 + 0.05) / (l2 + 0.05)


def _extract_token_in_scope(css: str, scope_signature: str, token_name: str) -> str:
    scope_idx = css.find(scope_signature)
    assert scope_idx != -1, f"scope 未找到: {scope_signature}"
    open_idx = css.find("{", scope_idx)
    depth = 0
    end_idx = -1
    for i in range(open_idx, len(css)):
        ch = css[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end_idx = i
                break
    assert end_idx != -1
    body = css[open_idx : end_idx + 1]
    match = re.search(rf"--{re.escape(token_name)}:\s*(#[0-9a-fA-F]+);", body)
    assert match, f"{scope_signature} 内未找到 --{token_name}"
    return match.group(1).lower()


class TestFocusRingDarkContrast(unittest.TestCase):
    """R258 · dark theme focus ring WCAG 1.4.11 ≥ 3:1."""

    @classmethod
    def setUpClass(cls) -> None:
        css = CSS_PATH.read_text(encoding="utf-8")
        cls.bg_primary = _extract_token_in_scope(css, ":root", "bg-primary")
        cls.bg_secondary = _extract_token_in_scope(css, ":root", "bg-secondary")
        cls.focus_color = _extract_token_in_scope(css, ":root", "focus-ring-color")

    def test_focus_ring_on_bg_primary(self) -> None:
        r = _contrast(self.focus_color, self.bg_primary)
        self.assertGreaterEqual(
            r,
            WCAG_UI_THRESHOLD,
            f"dark focus-ring-color({self.focus_color}) on "
            f"bg-primary({self.bg_primary}) = {r:.2f}:1 < "
            f"{WCAG_UI_THRESHOLD} (WCAG 1.4.11)",
        )

    def test_focus_ring_on_bg_secondary(self) -> None:
        r = _contrast(self.focus_color, self.bg_secondary)
        self.assertGreaterEqual(
            r,
            WCAG_UI_THRESHOLD,
            f"dark focus-ring-color({self.focus_color}) on "
            f"bg-secondary({self.bg_secondary}) = {r:.2f}:1 < "
            f"{WCAG_UI_THRESHOLD} (WCAG 1.4.11)",
        )


class TestFocusRingLightContrast(unittest.TestCase):
    """R258 · light theme (explicit data-theme) focus ring WCAG 1.4.11."""

    @classmethod
    def setUpClass(cls) -> None:
        css = CSS_PATH.read_text(encoding="utf-8")
        scope = '[data-theme="light"]'
        cls.bg_primary = _extract_token_in_scope(css, scope, "bg-primary")
        cls.bg_secondary = _extract_token_in_scope(css, scope, "bg-secondary")
        cls.focus_color = _extract_token_in_scope(css, scope, "focus-ring-color")

    def test_focus_ring_on_bg_primary(self) -> None:
        r = _contrast(self.focus_color, self.bg_primary)
        self.assertGreaterEqual(
            r,
            WCAG_UI_THRESHOLD,
            f"light focus-ring-color({self.focus_color}) on "
            f"bg-primary({self.bg_primary}) = {r:.2f}:1 < "
            f"{WCAG_UI_THRESHOLD} (WCAG 1.4.11)",
        )

    def test_focus_ring_on_bg_secondary(self) -> None:
        r = _contrast(self.focus_color, self.bg_secondary)
        self.assertGreaterEqual(
            r,
            WCAG_UI_THRESHOLD,
            f"light focus-ring-color({self.focus_color}) on "
            f"bg-secondary({self.bg_secondary}) = {r:.2f}:1 < "
            f"{WCAG_UI_THRESHOLD} (WCAG 1.4.11)",
        )


class TestFocusRingMediaQueryMirror(unittest.TestCase):
    """R258 · system-light media query must mirror --focus-ring-color。"""

    @classmethod
    def setUpClass(cls) -> None:
        css = CSS_PATH.read_text(encoding="utf-8")
        # 抓 media query 块
        start = css.find("@media (prefers-color-scheme: light)")
        open_idx = css.find("{", start)
        depth = 0
        end_idx = -1
        for i in range(open_idx, len(css)):
            if css[i] == "{":
                depth += 1
            elif css[i] == "}":
                depth -= 1
                if depth == 0:
                    end_idx = i
                    break
        cls.block = css[open_idx : end_idx + 1]

    def test_focus_ring_color_present(self) -> None:
        self.assertIn(
            "--focus-ring-color:",
            self.block,
            "system-light media query 必须 override --focus-ring-color 否则 "
            "系统 light 用户 fall through 到 dark token (mirror lesson "
            "from cycle-2 §6 L5)",
        )


class TestFocusVisibleRuleUsesNewToken(unittest.TestCase):
    """R258 · :focus-visible rule 必须用 var(--focus-ring-color, ...)。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.css = CSS_PATH.read_text(encoding="utf-8")

    @classmethod
    def _extract_a11y_layer_focus_visible_body(cls) -> str:
        """专门抓 ``@layer a11y { ... :focus-visible { ... } }`` 内的规则体。

        css 里有多处 ``:focus-visible``（每个组件自带 outline 覆盖），但本
        cycle Track A 改的是 ``@layer a11y`` 内的**全局基底**规则，所以
        必须特定 scope 抓取。
        """
        idx_layer = cls.css.find("@layer a11y")
        assert idx_layer != -1, "@layer a11y 必须存在"
        # 抓 layer 块整体
        open_idx = cls.css.find("{", idx_layer)
        depth = 0
        end_idx = -1
        for i in range(open_idx, len(cls.css)):
            if cls.css[i] == "{":
                depth += 1
            elif cls.css[i] == "}":
                depth -= 1
                if depth == 0:
                    end_idx = i
                    break
        assert end_idx != -1
        layer_body = cls.css[open_idx + 1 : end_idx]
        # 在 layer 内找独立的 ``:focus-visible {`` 规则（避免匹配到 selector
        # ``:focus:not(:focus-visible)`` —— 那是 "去掉 outline" 的规则，不
        # 是 cycle-3 要审查的那条）。
        fv_match = re.search(
            r"(?<!\()\s*:focus-visible\s*\{",
            layer_body,
        )
        assert fv_match, (
            "@layer a11y 内独立 :focus-visible {} 规则必须存在 "
            "（区别于 :focus:not(:focus-visible)）"
        )
        rule_open = fv_match.end() - 1  # 指向 ``{``
        rule_depth = 0
        rule_end = -1
        for i in range(rule_open, len(layer_body)):
            if layer_body[i] == "{":
                rule_depth += 1
            elif layer_body[i] == "}":
                rule_depth -= 1
                if rule_depth == 0:
                    rule_end = i
                    break
        assert rule_end != -1
        return layer_body[rule_open + 1 : rule_end]

    def test_focus_visible_outline_uses_focus_ring_color_token(self) -> None:
        body = self._extract_a11y_layer_focus_visible_body()
        self.assertIn(
            "var(--focus-ring-color",
            body,
            "@layer a11y :focus-visible outline 必须用 "
            "var(--focus-ring-color, ...) 而非直接 var(--primary-500)，"
            "否则 light 主题 focus 不可见 (2.50:1 FAIL WCAG 1.4.11)",
        )

    def test_focus_visible_has_primary_500_fallback(self) -> None:
        body = self._extract_a11y_layer_focus_visible_body()
        # forwards-compat：若 --focus-ring-color 未定义（旧 theme），fall 到
        # --primary-500，再 fall 到 currentColor
        self.assertIn(
            "--primary-500",
            body,
            "focus-visible 必须保留 --primary-500 fallback 链，兼容旧 theme",
        )


if __name__ == "__main__":
    unittest.main()
