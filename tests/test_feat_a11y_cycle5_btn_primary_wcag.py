"""a11y-audit-cycle-5 Track D (R259h) · ``.btn-primary`` WCAG 1.4.3 contrast。

背景
----

cr48 §5 follow-up #1 指出 ``.btn-primary`` 在 dark 默认与 light theme 都用
white-on-X 不达 WCAG 2.1 AA-normal (4.5:1)：

- dark default bg ``#007aff``: white-on = 4.02:1 ❌
- dark hover bg ``#0056cc``: white-on = 6.56:1 ✓ (AA)
- light default bg ``#d97757`` (Anthropic Orange): white-on = 3.12:1 ❌
- light hover bg ``#c56a4c``: white-on = 3.79:1 ❌ (AA-large only)

cycle-5 Track D 修复：

- dark default → ``#0056cc`` (6.56:1 AA pass; 原 :hover 色)
- dark hover  → ``#0045a0`` (8.90:1 AAA pass; 新加入 R109 iOS 蓝家族)
- light default → ``#b35730`` (4.86:1 AA pass; 同 Anthropic 橙家族 deeper)
- light hover → ``#9a4929`` (6.25:1 AA pass)

R65 ``.btn:active`` 仍用 ``#d97757`` / ``#c56a4c`` 保留品牌色脉络（active
是瞬时按下态，contrast 要求更低）。

回归契约
--------

5 invariants：
1. dark default white-on-bg ≥ 4.5:1 (AA-normal)
2. dark hover white-on-bg ≥ 4.5:1
3. light default white-on-bg ≥ 4.5:1
4. light hover white-on-bg ≥ 4.5:1
5. R65 protected `.btn-primary:active` 仍存在 Anthropic Orange 字面量
   （防止 Track D 修复时误删 :active 规则）
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


def _extract_bg_from_rule(css: str, selector_regex: str) -> str | None:
    """从给定 selector 的规则块里取 ``background:`` 第一个 hex 值。

    同一 selector 可能被多次定义（如 ``[data-theme=light] .btn-primary``
    在 R64 行 8307 是 color override，行 8623 才是 background override）。
    迭代所有匹配，返回**第一个含 background hex** 的规则。
    """
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


class TestBtnPrimaryDarkContrast(unittest.TestCase):
    """R259h · dark theme btn-primary 与白色文字 ≥ AA-normal。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.css = CSS_PATH.read_text(encoding="utf-8")

    def test_default_white_on_bg(self) -> None:
        # 必须用 negative lookahead (?!:) 排除 :hover/:active 等 pseudo
        bg = _extract_bg_from_rule(self.css, r"^\.btn-primary(?!:|-)")
        assert bg is not None, "找不到 .btn-primary 默认规则 (排除 :hover/-foo)"
        contrast = _contrast(WHITE, bg)
        self.assertGreaterEqual(
            contrast,
            AA_NORMAL,
            f"dark .btn-primary 默认 white-on-{bg} contrast = {contrast:.2f}:1 "
            f"< {AA_NORMAL}（cycle-5 Track D R259h 要求 AA-normal）",
        )

    def test_hover_white_on_bg(self) -> None:
        bg = _extract_bg_from_rule(self.css, r"^\.btn-primary:hover(?!:|-)")
        assert bg is not None, "找不到 .btn-primary:hover 规则"
        contrast = _contrast(WHITE, bg)
        self.assertGreaterEqual(
            contrast,
            AA_NORMAL,
            f"dark .btn-primary:hover white-on-{bg} = {contrast:.2f}:1 < {AA_NORMAL}",
        )


class TestBtnPrimaryLightContrast(unittest.TestCase):
    """R259h · light theme btn-primary 与白色文字 ≥ AA-normal。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.css = CSS_PATH.read_text(encoding="utf-8")

    def test_default_white_on_bg(self) -> None:
        bg = _extract_bg_from_rule(
            self.css, r"\[data-theme=\"light\"\]\s+\.btn-primary(?!:|-|\s+span)"
        )
        assert bg is not None, "找不到 [data-theme=light] .btn-primary 默认规则"
        contrast = _contrast(WHITE, bg)
        self.assertGreaterEqual(
            contrast,
            AA_NORMAL,
            f"light .btn-primary 默认 white-on-{bg} = {contrast:.2f}:1 < "
            f"{AA_NORMAL}（cycle-5 Track D R259h 要求 AA-normal）。"
            f"建议色：#b35730 (4.86:1)。",
        )

    def test_hover_white_on_bg(self) -> None:
        bg = _extract_bg_from_rule(
            self.css, r"\[data-theme=\"light\"\]\s+\.btn-primary:hover(?!:|-)"
        )
        assert bg is not None, "找不到 [data-theme=light] .btn-primary:hover 规则"
        contrast = _contrast(WHITE, bg)
        self.assertGreaterEqual(
            contrast,
            AA_NORMAL,
            f"light .btn-primary:hover white-on-{bg} = {contrast:.2f}:1 < {AA_NORMAL}",
        )


class TestActiveStillUsesBrandOrange(unittest.TestCase):
    """R259h · 确保 R65 ``.btn:active`` 仍使用 Anthropic Orange 字面量。

    cycle-5 Track D 升级 default + hover，但 :active 保留品牌色（R65 invariant）。
    防止 Track D 修复时误改 :active 规则。
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.css = CSS_PATH.read_text(encoding="utf-8")

    def test_btn_active_block_contains_orange_hex(self) -> None:
        # 取 [data-theme=light] .btn(-primary|-secondary)?:active 规则块
        block_pat = re.compile(
            r"\[data-theme=\"light\"\][^{]*\.btn(?:-(?:primary|secondary))?:active[^{]*\{([^}]+)\}",
            re.DOTALL,
        )
        m = block_pat.search(self.css)
        self.assertIsNotNone(m, "R65 .btn:active 规则块丢失？")
        assert m is not None
        body = m.group(1)
        self.assertTrue(
            re.search(r"#(?:d97757|c56a4c)", body, re.IGNORECASE)
            or re.search(r"rgba\(\s*217\s*,\s*119\s*,\s*87", body, re.IGNORECASE),
            "R65 :active 规则块不再含 Anthropic Orange (#d97757/#c56a4c/RGB)。"
            "cycle-5 Track D 应当只改 default + :hover，保留 :active。",
        )


if __name__ == "__main__":
    unittest.main()
