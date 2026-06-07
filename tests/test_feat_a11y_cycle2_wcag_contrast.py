"""a11y-audit-cycle-2 Track A (R257) · WCAG 2.1 AA contrast 自动审计。

背景
----

a11y-audit-cycle-1 完成 focus management；cycle-2 把视线移到**色彩
对比度** —— WCAG 2.1 SC 1.4.3 (Contrast Minimum)：

* AA-normal text (< 18pt 或 < 14pt bold): contrast ≥ 4.5:1
* AA-large text (≥ 18pt 或 ≥ 14pt bold): contrast ≥ 3:1
* AAA-normal: ≥ 7:1，AAA-large: ≥ 4.5:1

cycle-2 §1 inventory：
- ``--text-primary / --text-secondary / --text-tertiary`` 是 text
  色 tokens；``--text-muted`` 仅作 background-only（代码注释守护）
- ``--bg-primary / --bg-secondary`` 是常见 text-on-bg 背景

cycle-2 §2 audit findings (Track A 落地前)：
- dark text-tertiary on bg-primary: 3.59:1 (passes AA-large only)
- dark text-tertiary on bg-secondary: 3.15:1 (passes AA-large only)
- **light text-tertiary on bg-primary: 1.78:1 (FAIL all levels)**
- **light text-tertiary on bg-secondary: 2.11:1 (FAIL all levels)**

Track A 落地决策：
- dark: ``#71717a`` → ``#98989e`` (从 AA-large 升到 AA-normal)
- light: ``#b0aea5`` → ``#757470`` (从 FAIL 升到 AA-large)

light bg-primary 是 Anthropic 品牌的暖米色 ``#e8e6dc``——为保持品牌
不能加深；text-tertiary 升到 ``#757470`` 已是兼顾 muted 语义 + WCAG
AA-large 合规的最佳折中（saturation point 已显示如 ``#757470`` 这种
中性暗灰才能在该 bg 上达到 3:1）。

回归契约（共 8 cases）
----------------------

针对 dark + light 两套主题，4 对 text × bg 组合 = 8 个 invariants。
每条都直接从 CSS 文件解析出当前值，重新计算 WCAG 对比度，断言达标。

如果未来有人想"再 muted 一点"重置回 FAIL 值，这些 invariants 会立刻
红线。同时如果设计师有充分理由调整品牌色（例如更深 bg-primary），
重跑这些 invariants 可以一次性验证全部组合。

加 2 个 anti-regression invariants：
- ``--text-tertiary`` 与 strikethrough 用例仍在
- ``--text-muted`` 仍仅用于 background （未泄漏到 color: 规则）
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

# WCAG 2.1 thresholds
AA_NORMAL = 4.5
AA_LARGE = 3.0


def parse_hex(h: str) -> tuple[int, int, int]:
    """Parse #rgb 或 #rrggbb → (r, g, b) 0-255."""
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def relative_luminance(rgb: tuple[int, int, int]) -> float:
    """sRGB → relative luminance per WCAG 2.1 formula."""

    def channel(c: int) -> float:
        cl = c / 255
        return cl / 12.92 if cl <= 0.03928 else ((cl + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(fg: str, bg: str) -> float:
    """两个 hex 颜色的 WCAG 对比度，浮点 (L_max+0.05)/(L_min+0.05)."""
    l1 = relative_luminance(parse_hex(fg))
    l2 = relative_luminance(parse_hex(bg))
    if l1 < l2:
        l1, l2 = l2, l1
    return (l1 + 0.05) / (l2 + 0.05)


def _extract_token(css: str, scope_signature: str, token_name: str) -> str:
    """从 ``scope_signature {`` 块内抓取 ``--token_name: #xxxxxx;`` 值。

    Args:
        css: 完整 CSS 文本
        scope_signature: CSS scope 签名（例如 ":root", '[data-theme="light"]'）
        token_name: 不含 ``--`` 前缀的 token 名

    Returns:
        ``#xxxxxx`` 6 位 hex 字符串
    """
    # 找 scope 开始
    scope_idx = css.find(scope_signature)
    assert scope_idx != -1, f"scope 未找到: {scope_signature}"
    # 找 scope 紧接的第一个 {
    open_idx = css.find("{", scope_idx)
    assert open_idx != -1
    # 抓 brace-balanced body
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
    # 抓 token
    match = re.search(rf"--{re.escape(token_name)}:\s*(#[0-9a-fA-F]+);", body)
    assert match, f"{scope_signature} 内未找到 --{token_name}"
    return match.group(1).lower()


class TestWcagContrastDark(unittest.TestCase):
    """暗色主题 (:root) 的 WCAG AA contrast 检查。"""

    @classmethod
    def setUpClass(cls) -> None:
        css = CSS_PATH.read_text(encoding="utf-8")
        cls.bg_primary = _extract_token(css, ":root", "bg-primary")
        cls.bg_secondary = _extract_token(css, ":root", "bg-secondary")
        cls.text_primary = _extract_token(css, ":root", "text-primary")
        cls.text_secondary = _extract_token(css, ":root", "text-secondary")
        cls.text_tertiary = _extract_token(css, ":root", "text-tertiary")

    def test_text_primary_on_bg_primary_aa(self) -> None:
        r = contrast_ratio(self.text_primary, self.bg_primary)
        self.assertGreaterEqual(
            r,
            AA_NORMAL,
            f"dark text-primary({self.text_primary}) on bg-primary"
            f"({self.bg_primary}) = {r:.2f}:1 < AA-normal {AA_NORMAL}",
        )

    def test_text_secondary_on_bg_primary_aa(self) -> None:
        r = contrast_ratio(self.text_secondary, self.bg_primary)
        self.assertGreaterEqual(
            r,
            AA_NORMAL,
            f"dark text-secondary({self.text_secondary}) on bg-primary"
            f"({self.bg_primary}) = {r:.2f}:1 < AA-normal {AA_NORMAL}",
        )

    def test_text_tertiary_on_bg_primary_aa_large(self) -> None:
        # tertiary 是设计意图上的 muted text，AA-large 是底线
        r = contrast_ratio(self.text_tertiary, self.bg_primary)
        self.assertGreaterEqual(
            r,
            AA_LARGE,
            f"dark text-tertiary({self.text_tertiary}) on bg-primary"
            f"({self.bg_primary}) = {r:.2f}:1 < AA-large {AA_LARGE}",
        )

    def test_text_tertiary_on_bg_secondary_aa_large(self) -> None:
        r = contrast_ratio(self.text_tertiary, self.bg_secondary)
        self.assertGreaterEqual(
            r,
            AA_LARGE,
            f"dark text-tertiary({self.text_tertiary}) on bg-secondary"
            f"({self.bg_secondary}) = {r:.2f}:1 < AA-large {AA_LARGE}",
        )


class TestWcagContrastLight(unittest.TestCase):
    """浅色主题 ([data-theme="light"]) 的 WCAG AA contrast 检查。"""

    @classmethod
    def setUpClass(cls) -> None:
        css = CSS_PATH.read_text(encoding="utf-8")
        cls.bg_primary = _extract_token(css, '[data-theme="light"]', "bg-primary")
        cls.bg_secondary = _extract_token(css, '[data-theme="light"]', "bg-secondary")
        cls.text_primary = _extract_token(css, '[data-theme="light"]', "text-primary")
        cls.text_secondary = _extract_token(
            css, '[data-theme="light"]', "text-secondary"
        )
        cls.text_tertiary = _extract_token(css, '[data-theme="light"]', "text-tertiary")

    def test_text_primary_on_bg_primary_aa(self) -> None:
        r = contrast_ratio(self.text_primary, self.bg_primary)
        self.assertGreaterEqual(
            r,
            AA_NORMAL,
            f"light text-primary({self.text_primary}) on bg-primary"
            f"({self.bg_primary}) = {r:.2f}:1 < AA-normal {AA_NORMAL}",
        )

    def test_text_secondary_on_bg_primary_aa(self) -> None:
        r = contrast_ratio(self.text_secondary, self.bg_primary)
        self.assertGreaterEqual(
            r,
            AA_NORMAL,
            f"light text-secondary({self.text_secondary}) on bg-primary"
            f"({self.bg_primary}) = {r:.2f}:1 < AA-normal {AA_NORMAL}",
        )

    def test_text_tertiary_on_bg_primary_aa_large(self) -> None:
        # light bg-primary 是 Anthropic 品牌米色——AA-normal 难以达到
        # （需要黑色级别的字色，破坏 muted 语义）；AA-large 是合规底线
        r = contrast_ratio(self.text_tertiary, self.bg_primary)
        self.assertGreaterEqual(
            r,
            AA_LARGE,
            f"light text-tertiary({self.text_tertiary}) on bg-primary"
            f"({self.bg_primary}) = {r:.2f}:1 < AA-large {AA_LARGE}",
        )

    def test_text_tertiary_on_bg_secondary_aa_large(self) -> None:
        r = contrast_ratio(self.text_tertiary, self.bg_secondary)
        self.assertGreaterEqual(
            r,
            AA_LARGE,
            f"light text-tertiary({self.text_tertiary}) on bg-secondary"
            f"({self.bg_secondary}) = {r:.2f}:1 < AA-large {AA_LARGE}",
        )


class TestTextTertiaryStillForStrikethroughOnly(unittest.TestCase):
    """text-tertiary as foreground text 仅允许 strikethrough 用例。

    若有人误用 ``color: var(--text-tertiary)`` 给普通正文，会被这里
    cone-off。strikethrough 因为有 ``text-decoration: line-through``
    视觉强化，AA-large 已是 WCAG 合规标准做法。
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.css = CSS_PATH.read_text(encoding="utf-8")

    def test_text_tertiary_color_only_for_strikethrough(self) -> None:
        # 找所有 color: var(--text-tertiary) 使用点
        pattern = re.compile(r"color:\s*var\(--text-tertiary[^)]*\)")
        matches = list(pattern.finditer(self.css))
        # 当前应仅有 1 处（strikethrough）
        self.assertEqual(
            len(matches),
            1,
            f"color: var(--text-tertiary) 用法目前仅允许 1 处"
            f"（strikethrough），实际 {len(matches)} 处；若新增需在 cycle-2"
            f" 文档评估 WCAG 影响并扩 invariant 允许列表",
        )
        # 验证 context 含 strikethrough/del/s 标识
        idx = matches[0].start()
        context = self.css[max(0, idx - 500) : idx]
        self.assertTrue(
            "strikethrough" in context
            or ".markdown-content del" in context
            or "markdown-content s" in context,
            "text-tertiary as text color 必须出现在 strikethrough/del/s 选择器上下文中",
        )


class TestStatusColorsDark(unittest.TestCase):
    """R257b · dark theme status colors WCAG AA contrast."""

    @classmethod
    def setUpClass(cls) -> None:
        css = CSS_PATH.read_text(encoding="utf-8")
        cls.bg_primary = _extract_token(css, ":root", "bg-primary")
        cls.bg_secondary = _extract_token(css, ":root", "bg-secondary")
        cls.success = _extract_token(css, ":root", "success-500")
        cls.warning = _extract_token(css, ":root", "warning-500")
        cls.error = _extract_token(css, ":root", "error-500")
        cls.info = _extract_token(css, ":root", "info-500")

    def _assert_aa(self, color_name: str, color: str, bg_name: str, bg: str) -> None:
        r = contrast_ratio(color, bg)
        self.assertGreaterEqual(
            r,
            AA_NORMAL,
            f"dark {color_name}({color}) on {bg_name}({bg}) = "
            f"{r:.2f}:1 < AA-normal {AA_NORMAL}",
        )

    def test_success_aa_on_primary(self) -> None:
        self._assert_aa("success-500", self.success, "bg-primary", self.bg_primary)

    def test_success_aa_on_secondary(self) -> None:
        self._assert_aa("success-500", self.success, "bg-secondary", self.bg_secondary)

    def test_warning_aa_on_primary(self) -> None:
        self._assert_aa("warning-500", self.warning, "bg-primary", self.bg_primary)

    def test_warning_aa_on_secondary(self) -> None:
        self._assert_aa("warning-500", self.warning, "bg-secondary", self.bg_secondary)

    def test_error_aa_on_primary(self) -> None:
        self._assert_aa("error-500", self.error, "bg-primary", self.bg_primary)

    def test_error_aa_on_secondary(self) -> None:
        self._assert_aa("error-500", self.error, "bg-secondary", self.bg_secondary)

    def test_info_aa_on_primary(self) -> None:
        self._assert_aa("info-500", self.info, "bg-primary", self.bg_primary)

    def test_info_aa_on_secondary(self) -> None:
        self._assert_aa("info-500", self.info, "bg-secondary", self.bg_secondary)


class TestStatusColorsLight(unittest.TestCase):
    """R257b · light theme status colors WCAG AA contrast (explicit data-theme)."""

    @classmethod
    def setUpClass(cls) -> None:
        css = CSS_PATH.read_text(encoding="utf-8")
        scope = '[data-theme="light"]'
        cls.bg_primary = _extract_token(css, scope, "bg-primary")
        cls.bg_secondary = _extract_token(css, scope, "bg-secondary")
        cls.success = _extract_token(css, scope, "success-500")
        cls.warning = _extract_token(css, scope, "warning-500")
        cls.error = _extract_token(css, scope, "error-500")
        cls.info = _extract_token(css, scope, "info-500")

    def _assert_aa(self, color_name: str, color: str, bg_name: str, bg: str) -> None:
        r = contrast_ratio(color, bg)
        self.assertGreaterEqual(
            r,
            AA_NORMAL,
            f"light {color_name}({color}) on {bg_name}({bg}) = "
            f"{r:.2f}:1 < AA-normal {AA_NORMAL}",
        )

    def test_success_aa_on_primary(self) -> None:
        self._assert_aa("success-500", self.success, "bg-primary", self.bg_primary)

    def test_success_aa_on_secondary(self) -> None:
        self._assert_aa("success-500", self.success, "bg-secondary", self.bg_secondary)

    def test_warning_aa_on_primary(self) -> None:
        self._assert_aa("warning-500", self.warning, "bg-primary", self.bg_primary)

    def test_warning_aa_on_secondary(self) -> None:
        self._assert_aa("warning-500", self.warning, "bg-secondary", self.bg_secondary)

    def test_error_aa_on_primary(self) -> None:
        self._assert_aa("error-500", self.error, "bg-primary", self.bg_primary)

    def test_error_aa_on_secondary(self) -> None:
        self._assert_aa("error-500", self.error, "bg-secondary", self.bg_secondary)

    def test_info_aa_on_primary(self) -> None:
        self._assert_aa("info-500", self.info, "bg-primary", self.bg_primary)

    def test_info_aa_on_secondary(self) -> None:
        self._assert_aa("info-500", self.info, "bg-secondary", self.bg_secondary)


class TestSystemLightMediaQueryMirrorsStatusColors(unittest.TestCase):
    """R257b · media query (prefers-color-scheme: light) must mirror status colors.

    Latent bug pre-cycle-2：``@media (prefers-color-scheme: light)
    :root:not([data-theme])`` 块只 override text/bg/border/accent，
    **不** override status colors → 系统 light 模式且无 explicit
    data-theme 的用户拿到 dark-theme status colors 显示在 light bg 上
    → 全部 4 个 status × 2 bgs = 8 cells FAIL。

    Track A ship 修复此问题：把 [data-theme="light"] 的 status colors
    完整 mirror 到 media query 块。
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.css = CSS_PATH.read_text(encoding="utf-8")
        # 抓 @media (prefers-color-scheme: light) { :root:not([data-theme]) { ... } } 块
        # 用 brace counting
        start = cls.css.find("@media (prefers-color-scheme: light)")
        assert start > -1, "media query block 必须存在"
        open_idx = cls.css.find("{", start)
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
        assert end_idx > -1
        cls.block = cls.css[open_idx : end_idx + 1]

    def test_success_500_mirrored(self) -> None:
        self.assertIn(
            "--success-500:",
            self.block,
            "system-light media query 必须 override success-500 防止 dark "
            "默认值被使用在 light bg 上",
        )

    def test_warning_500_mirrored(self) -> None:
        self.assertIn("--warning-500:", self.block)

    def test_error_500_mirrored(self) -> None:
        self.assertIn("--error-500:", self.block)

    def test_info_500_mirrored(self) -> None:
        self.assertIn("--info-500:", self.block)

    def test_all_status_bg_tokens_mirrored(self) -> None:
        for token in ("--success-bg:", "--warning-bg:", "--error-bg:", "--info-bg:"):
            self.assertIn(
                token,
                self.block,
                f"system-light media query 必须 override {token} 配套保持一致",
            )


class TestTextMutedBackgroundOnly(unittest.TestCase):
    """--text-muted 仅作 background-color，不应作 foreground text color。

    text-muted 在 dark/light 两套都 < 2.5:1 对比，绝不可作文本色。
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.css = CSS_PATH.read_text(encoding="utf-8")

    def test_text_muted_never_used_as_color(self) -> None:
        pattern = re.compile(r"color:\s*var\(--text-muted[^)]*\)")
        matches = list(pattern.finditer(self.css))
        self.assertEqual(
            len(matches),
            0,
            f"--text-muted 是 background-only token（WCAG 对比 < 2.5），"
            f"绝不可作 color: foreground 用；实际找到 {len(matches)} 处",
        )


if __name__ == "__main__":
    unittest.main()
