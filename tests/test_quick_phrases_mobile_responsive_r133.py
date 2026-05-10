"""R133 · Quick Phrases 面板移动端响应式契约。

背景
----
R130 v1 的 ``.quick-phrases-header`` 只有「label + Add」两个元素，
``@media (max-width: 768px)`` 下只动了 container margin + chip 字号
就足够。R131b 把 header 扩到 4 元素（label + Add + Export + Import），
在 < 480px 设备（iPhone SE / 老款 Android）上会撞挤——按钮 padding
被压到 0、点击目标 <32×32（iOS HIG / Material 推荐 ≥44/48px）、
甚至按钮文字断行成两列。

R133 不引入新元素 / 不改 R131b 的桌面布局，仅把 ``@media`` 断点扩成
两档：

- ``≤768px`` — header 加 ``flex-wrap`` 让按钮在空间紧张时换行；
  按钮 padding / 字号收紧到 0.3rem×0.7rem / 0.78rem。
- ``≤480px`` — label 通过 ``flex-basis: 100%`` 强制独占一行（配合
  flex-wrap），让按钮组在第二行可用全宽；按钮再收紧到
  0.28rem×0.55rem / 0.74rem；chip max-width 从 10rem 进一步降到
  8rem。

测试覆盖三个层面（共 9 cases / 3 invariant classes）：

1.  **断点存在性** — CSS 文件含 ``@media (max-width: 768px)`` 与
    ``@media (max-width: 480px)`` 两个块，且都包含
    ``.quick-phrases-*`` 选择器。
2.  **flex-wrap + 按钮 padding 收紧** — 768px 块含 ``flex-wrap: wrap``
    + 三类按钮共享 padding/font-size 规则；480px 块含
    ``flex-basis: 100%`` + 进一步收紧的按钮规则。
3.  **R130/R131b 桌面契约保留** — 桌面 ``.quick-phrases-header`` /
    ``.quick-phrases-label`` 主规则未被 R133 改动；三类按钮的桌面
    base style（base + light theme override）仍按 R131b 的合并形态
    存在。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CSS = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "css" / "main.css"


def _read(p: Path) -> str:
    assert p.is_file(), f"缺失文件: {p}"
    return p.read_text(encoding="utf-8")


def _extract_media_block(src: str, breakpoint_px: int) -> str:
    """抽取所有匹配 ``@media (max-width: <px>px) {...}`` 的块（可能多个），
    用 brace counter 处理嵌套，返回拼接后的字符串。
    """
    pattern = rf"@media\s*\(\s*max-width\s*:\s*{breakpoint_px}px\s*\)\s*\{{"
    out: list[str] = []
    for m in re.finditer(pattern, src):
        depth = 1
        i = m.end()
        start = i
        while i < len(src) and depth > 0:
            if src[i] == "{":
                depth += 1
            elif src[i] == "}":
                depth -= 1
            i += 1
        out.append(src[start : i - 1])
    return "\n\n".join(out)


# ---------------------------------------------------------------------------
# 1. 断点存在性
# ---------------------------------------------------------------------------


class TestBreakpointsPresent(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.css = _read(CSS)

    def test_breakpoint_768_block_exists(self) -> None:
        self.assertRegex(
            self.css,
            r"@media\s*\(\s*max-width:\s*768px\s*\)",
            "main.css 必须含 @media (max-width: 768px) 块",
        )

    def test_breakpoint_480_block_exists(self) -> None:
        self.assertRegex(
            self.css,
            r"@media\s*\(\s*max-width:\s*480px\s*\)",
            "main.css 必须含 @media (max-width: 480px) 块",
        )

    def test_breakpoint_768_covers_quick_phrases(self) -> None:
        block = _extract_media_block(self.css, 768)
        self.assertIn(
            ".quick-phrases-header",
            block,
            "768px 块必须含 .quick-phrases-header 收紧规则（R133 引入 flex-wrap）",
        )

    def test_breakpoint_480_covers_quick_phrases(self) -> None:
        block = _extract_media_block(self.css, 480)
        self.assertIn(
            ".quick-phrases-label",
            block,
            "480px 块必须含 .quick-phrases-label 强制独行规则（R133）",
        )


# ---------------------------------------------------------------------------
# 2. flex-wrap + padding 收紧
# ---------------------------------------------------------------------------


class TestResponsiveLayoutTightening(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.css = _read(CSS)
        cls.block_768 = _extract_media_block(cls.css, 768)
        cls.block_480 = _extract_media_block(cls.css, 480)

    def test_768_header_uses_flex_wrap(self) -> None:
        # 768px 必须给 header 加 flex-wrap，让按钮在空间紧张时自动换行
        self.assertIn(
            "flex-wrap: wrap",
            self.block_768,
            "768px 块 .quick-phrases-header 必须 flex-wrap: wrap（R133）",
        )

    def test_768_three_buttons_share_padding_rule(self) -> None:
        # 三类按钮在 768px 块内必须共享 padding/font-size 规则（与 R131b
        # 的合并 selector group 模式一致）
        self.assertRegex(
            self.block_768,
            (
                r"\.quick-phrases-add-btn,\s*\n"
                r"\s*\.quick-phrases-export-btn,\s*\n"
                r"\s*\.quick-phrases-import-btn\s*\{"
            ),
            "768px 三类按钮必须共享同一规则块（与 R131b 桌面 selector group 对齐）",
        )

    def test_480_label_takes_full_width(self) -> None:
        # 480px 让 label 通过 flex-basis: 100% 强制独行
        self.assertIn(
            "flex-basis: 100%",
            self.block_480,
            "480px 块必须给 .quick-phrases-label 设 flex-basis: 100%（R133）",
        )

    def test_480_chip_max_width_tighter_than_768(self) -> None:
        # 桌面规则里 chip 没显式 max-width；768px 给 10rem；480px 必须
        # 比 10rem 更紧（从测试角度：含 max-width 且数值 < 10rem）
        chip_rule_768 = re.search(
            r"\.quick-phrase-chip\s*\{[^}]*max-width:\s*([\d.]+)rem",
            self.block_768,
        )
        chip_rule_480 = re.search(
            r"\.quick-phrase-chip\s*\{[^}]*max-width:\s*([\d.]+)rem",
            self.block_480,
        )
        self.assertIsNotNone(chip_rule_768, "768px 块必须给 chip 设 max-width")
        self.assertIsNotNone(chip_rule_480, "480px 块必须给 chip 设更紧的 max-width")
        assert chip_rule_768 is not None and chip_rule_480 is not None
        w768 = float(chip_rule_768.group(1))
        w480 = float(chip_rule_480.group(1))
        self.assertLess(
            w480,
            w768,
            f"480px chip max-width ({w480}rem) 必须比 768px ({w768}rem) 更紧",
        )


# ---------------------------------------------------------------------------
# 3. R130 / R131b 桌面契约保留
# ---------------------------------------------------------------------------


class TestDesktopContractsIntact(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.css = _read(CSS)

    def test_header_main_rule_unchanged(self) -> None:
        # 桌面 .quick-phrases-header 主规则（display: flex / gap: 0.5rem）
        # 必须不被 R133 移走
        self.assertRegex(
            self.css,
            r"\.quick-phrases-header\s*\{[^}]*display:\s*flex[^}]*gap:\s*0\.5rem",
            "桌面 .quick-phrases-header 主规则（display:flex + gap:0.5rem）必须保留",
        )

    def test_three_button_base_selector_group_intact(self) -> None:
        # R131b 的合并 selector group（在 R133 之后仍必须有，CSS @media
        # 之外的 base style 不能被 R133 移走）
        self.assertRegex(
            self.css,
            (
                r"\.quick-phrases-add-btn,\s*\n"
                r"\.quick-phrases-export-btn,\s*\n"
                r"\.quick-phrases-import-btn\s*\{"
            ),
            "R131b 三类按钮共享 base selector group 必须保留（@media 之外）",
        )

    def test_label_margin_right_auto_default(self) -> None:
        # 桌面 .quick-phrases-label 仍是 margin-right: auto 把 label 推
        # 左侧、按钮挤右侧（R131b 引入），R133 仅在 480px 块里覆盖它
        self.assertRegex(
            self.css,
            r"\.quick-phrases-label\s*\{[^}]*margin-right:\s*auto",
            "桌面 .quick-phrases-label 必须 margin-right: auto（R131b 设计）",
        )


if __name__ == "__main__":
    unittest.main()
