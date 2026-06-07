"""a11y-audit-cycle-6 Track A (R259i) · ``.btn-secondary`` WCAG 1.4.3 contrast。

背景
----

cycle-5 Track D 修了 ``.btn-primary``，cr49 §5 #4 follow-up 指出
``.btn-secondary`` 是同源 risk（同样 white-on-X bg pattern + light theme
彩色背景）。审计结果：

dark theme:
- bg: ``rgba(255, 255, 255, 0.1)`` 半透明白（合成于黑色背景）
- color: ``#f5f5f7`` 浅灰白
- 实际合成 ≈ #303030，浅灰 on #303030 = 12.12:1 (AAA)

→ **dark theme 通过**，无需修复。

light theme（cycle-6 修复对象）:
- 旧 bg: ``#cc785c`` (Book Cloth)，white-on = 3.28:1 ❌
- 旧 hover: ``#b86a50``，white-on = 4.03:1 ❌

cycle-6 升级到同 Claude 暖棕红家族 deeper variants：
- 新 bg: ``#a85234`` (Book Cloth deeper)，white-on = 5.36:1 ✓
- 新 hover: ``#8a4525`` (深 Book Cloth)，white-on = 7.10:1 ✓

R65 ``.btn-secondary:active`` 仍用 ``#c56a4c`` 保留品牌色（R65 invariant
已锁定，瞬时态 contrast 要求更低）。

回归契约
--------

4 invariants：
1. light default white-on-bg ≥ 4.5:1 (AA-normal)
2. light hover white-on-bg ≥ 4.5:1
3. dark default 合成 effective bg 与文字 contrast ≥ 4.5:1
   （以 ``#1a1a1a`` 为底，半透明白 0.1 合成 ≈ ``#303030``）
4. R65 ``.btn-secondary:active`` 保留 Anthropic Orange 字面量
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


def _parse_hex(hex_str: str) -> tuple[int, int, int]:
    h = hex_str.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _relative_luminance(rgb: tuple[int, int, int]) -> float:
    def _conv(c: int) -> float:
        c_norm = c / 255
        return (
            c_norm / 12.92 if c_norm <= 0.03928 else ((c_norm + 0.055) / 1.055) ** 2.4
        )

    return 0.2126 * _conv(rgb[0]) + 0.7152 * _conv(rgb[1]) + 0.0722 * _conv(rgb[2])


def _contrast(c1: str, c2: str) -> float:
    l1 = _relative_luminance(_parse_hex(c1))
    l2 = _relative_luminance(_parse_hex(c2))
    if l1 < l2:
        l1, l2 = l2, l1
    return (l1 + 0.05) / (l2 + 0.05)


def _composite_alpha_white(alpha: float, bg_hex: str) -> str:
    """半透明白色 ``rgba(255, 255, 255, alpha)`` 合成到 ``bg_hex`` 上的实际
    rendered 颜色（Source-Over 算法）。"""
    r, g, b = _parse_hex(bg_hex)
    nr = int(alpha * 255 + (1 - alpha) * r)
    ng = int(alpha * 255 + (1 - alpha) * g)
    nb = int(alpha * 255 + (1 - alpha) * b)
    return f"#{nr:02x}{ng:02x}{nb:02x}"


def _extract_bg_from_rule(css: str, selector_regex: str) -> str | None:
    """从给定 selector 的规则块里取 ``background:`` 第一个 hex 值。"""
    rule_pat = re.compile(
        selector_regex + r"[^{]*\{([^{}]*)\}",
        re.MULTILINE,
    )
    bg_pat = re.compile(r"background\s*:\s*(#[0-9a-fA-F]{6})", re.IGNORECASE)
    for block_match in rule_pat.finditer(css):
        body = block_match.group(1)
        bg_match = bg_pat.search(body)
        if bg_match:
            return bg_match.group(1).lower()
    return None


AA_NORMAL = 4.5
WHITE = "#ffffff"
LIGHT_GRAY = "#f5f5f7"
# dark theme --bg-primary 主背景近似（实测取主题最深色 hex 之一）
DARK_BG_PRIMARY = "#1a1a1a"


class TestBtnSecondaryLightContrast(unittest.TestCase):
    """R259i · light theme btn-secondary 与白色文字 ≥ AA-normal。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.css = CSS_PATH.read_text(encoding="utf-8")

    def test_default_white_on_bg(self) -> None:
        bg = _extract_bg_from_rule(
            self.css, r"\[data-theme=\"light\"\]\s+\.btn-secondary(?!:|-|\s+span)"
        )
        assert bg is not None, "找不到 [data-theme=light] .btn-secondary 默认规则"
        contrast = _contrast(WHITE, bg)
        self.assertGreaterEqual(
            contrast,
            AA_NORMAL,
            f"light .btn-secondary 默认 white-on-{bg} = {contrast:.2f}:1 < "
            f"{AA_NORMAL}（cycle-6 Track A R259i 要求 AA-normal）。"
            f"建议色：#a85234 (5.36:1)。",
        )

    def test_hover_white_on_bg(self) -> None:
        bg = _extract_bg_from_rule(
            self.css, r"\[data-theme=\"light\"\]\s+\.btn-secondary:hover(?!:|-)"
        )
        assert bg is not None, "找不到 [data-theme=light] .btn-secondary:hover 规则"
        contrast = _contrast(WHITE, bg)
        self.assertGreaterEqual(
            contrast,
            AA_NORMAL,
            f"light .btn-secondary:hover white-on-{bg} = {contrast:.2f}:1 < "
            f"{AA_NORMAL}",
        )


class TestBtnSecondaryDarkContrast(unittest.TestCase):
    """R259i · dark theme btn-secondary 合成 effective bg 与文字 ≥ AA-normal。

    半透明白色背景需 simulate composite on dark base 才能算 contrast。
    """

    def test_translucent_bg_composite_contrast(self) -> None:
        # alpha=0.1 半透明白 + 黑色 #1a1a1a 合成 → ~#303030
        effective_bg = _composite_alpha_white(0.1, DARK_BG_PRIMARY)
        contrast = _contrast(LIGHT_GRAY, effective_bg)
        self.assertGreaterEqual(
            contrast,
            AA_NORMAL,
            f"dark .btn-secondary effective bg={effective_bg} (composite of "
            f"rgba(255,255,255,0.1) on {DARK_BG_PRIMARY})，"
            f"{LIGHT_GRAY}-on-{effective_bg} = {contrast:.2f}:1 < {AA_NORMAL}。"
            f"若不达标，调高 alpha 或改文字颜色（不动 R65/R109 baseline）。",
        )

    def test_translucent_hover_bg_composite_contrast(self) -> None:
        # alpha=0.15 hover 状态
        effective_bg = _composite_alpha_white(0.15, DARK_BG_PRIMARY)
        contrast = _contrast(LIGHT_GRAY, effective_bg)
        self.assertGreaterEqual(
            contrast,
            AA_NORMAL,
            f"dark .btn-secondary:hover effective bg={effective_bg}，"
            f"{LIGHT_GRAY}-on-{effective_bg} = {contrast:.2f}:1 < {AA_NORMAL}",
        )


class TestActiveStillUsesBrandOrangeSecondary(unittest.TestCase):
    """R259i · 确保 R65 ``.btn-secondary:active`` 仍使用 Anthropic Orange。

    cycle-6 Track A 升级 default + hover，但 :active 保留品牌色（R65 invariant
    已锁定）。防止 Track A 修复时误改 :active 规则。
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.css = CSS_PATH.read_text(encoding="utf-8")

    def test_btn_secondary_active_block_contains_orange_hex(self) -> None:
        # 取 [data-theme=light] .btn-secondary:active 规则块
        # （可能与 .btn:active / .btn-primary:active 在同一规则块）
        block_pat = re.compile(
            r"\[data-theme=\"light\"\][^{]*\.btn-secondary:active[^{]*\{([^}]+)\}",
            re.DOTALL,
        )
        m = block_pat.search(self.css)
        self.assertIsNotNone(
            m,
            "R65 .btn-secondary:active 规则块丢失？cycle-6 Track A 应当只改 default + :hover。",
        )
        assert m is not None
        body = m.group(1)
        self.assertTrue(
            re.search(r"#(?:d97757|c56a4c)", body, re.IGNORECASE)
            or re.search(r"rgba\(\s*217\s*,\s*119\s*,\s*87", body, re.IGNORECASE),
            "R65 .btn-secondary:active 规则块不再含 Anthropic Orange。"
            "cycle-6 Track A 应当只改 default + :hover，保留 :active。",
        )


if __name__ == "__main__":
    unittest.main()
