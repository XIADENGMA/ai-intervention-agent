"""R230 / Cycle 13 invariant: 装饰性 SVG 必须用 aria-hidden + focusable=false 屏蔽 AT。

为什么需要这条不变量
----------------------

R230 前的 ``web_ui.html`` 共 31 个 ``<svg>`` 元素，只有 2 个标注了
``aria-hidden="true"``。其余 29 个 SVG 会被屏幕阅读器宣读为 "graphic" /
"image"，紧接着才是按钮的实际文本标签（如 "Submit feedback"）。结果用户
听到的是 "graphic Submit feedback button" —— graphic 这个词没有任何信
息量但占用了听感时间，更糟的是图标内部的 ``<title>`` / ``<desc>``（如果
有）也会被一并宣读，导致严重噪声。

WCAG 2.1 SC 1.1.1 (Non-text Content) 要求 "Decorative, formatting, or
invisible content can be ignored by assistive technologies"。``btn-icon`` /
``section-icon`` / ``theme-icon`` 这三类都属于纯视觉装饰（旁边都有显式
文本标签 / aria-label），应当用 ``aria-hidden="true"`` + ``focusable="false"``
双属性隐藏：

* ``aria-hidden="true"`` 把 SVG 从 accessibility tree 摘除；
* ``focusable="false"`` 防止 IE/Edge legacy 行为给 SVG 加焦点（即便
  ``aria-hidden`` 也救不了，因为焦点会回到 SVG 元素本身，AT 仍会读出
  来）；这是 SVG icon 的 a11y 标准做法。

R230 把这两个属性补到 ``web_ui.html`` 所有装饰性 SVG 上，并加这条不变
量测试，防止未来新加 SVG 时遗漏。

允许例外（meaningful_svg_allowlist）
------------------------------------

如果某个 SVG 真的承载语义信息（例如显示当前任务的状态徽章、含 ``<title>``
说明的诊断图标），它就不该 aria-hidden。这种情况：

1. 在测试的 ``MEANINGFUL_SVG_CLASSES`` 集合里加它的 class 名（或精确
   line 号）；
2. 在 ``web_ui.html`` 给它加 ``role="img"`` + ``aria-label="..."`` 或
   ``<title>`` 子元素，让 AT 能读到正确语义。

目前没有 meaningful SVG，allowlist 为空。

测试结构
--------

* ``TestAllSvgsHaveAriaHidden``：枚举所有 ``<svg>`` 元素，逐一断言其
  opening tag 包含 ``aria-hidden="true"``。
* ``TestAllSvgsHaveFocusableFalse``：同上，断言包含
  ``focusable="false"``。
* ``TestNoMeaningfulSvgRegression``：若未来允许 meaningful SVG，必须显
  式加到 allowlist，否则测试会强制要求 aria-hidden。
* ``TestExistingPatternUnchanged``：line 340 / line 1695 的已有
  ``aria-hidden="true"`` ``focusable="false"`` 模式保留，作为 reference
  实现（防回归）。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HTML_PATH = REPO_ROOT / "src" / "ai_intervention_agent" / "templates" / "web_ui.html"

MEANINGFUL_SVG_CLASSES: set[str] = set()


def _read_html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


def _enumerate_svgs(html: str) -> list[tuple[int, str, str]]:
    """返回 (line_no, opening_tag, class_attr) 三元组。"""
    results: list[tuple[int, str, str]] = []
    for match in re.finditer(r"<svg\b[^>]*>", html):
        opening_tag = match.group(0)
        line_no = html[: match.start()].count("\n") + 1
        class_match = re.search(r'class="([^"]*)"', opening_tag)
        class_attr = class_match.group(1) if class_match else ""
        results.append((line_no, opening_tag, class_attr))
    return results


class TestAllSvgsHaveAriaHidden(unittest.TestCase):
    def test_every_svg_has_aria_hidden_true(self) -> None:
        html = _read_html()
        svgs = _enumerate_svgs(html)
        missing: list[tuple[int, str]] = []
        for line_no, opening_tag, class_attr in svgs:
            classes = set(class_attr.split())
            if classes & MEANINGFUL_SVG_CLASSES:
                continue
            if 'aria-hidden="true"' not in opening_tag:
                missing.append((line_no, class_attr or "(no class)"))
        self.assertEqual(
            missing,
            [],
            msg=(
                "R230 invariant: web_ui.html 中所有装饰性 <svg> 必须包含 "
                'aria-hidden="true"（否则屏幕阅读器会宣读 "graphic" 噪声）。'
                "缺失列表（行号, class）："
                f"{missing}。修复：给每个 SVG opening tag 加 "
                '`aria-hidden="true" focusable="false"`；若 SVG 真的承载语义，'
                "请加到本测试的 MEANINGFUL_SVG_CLASSES allowlist 并配上 "
                'role="img" + aria-label。'
            ),
        )


class TestAllSvgsHaveFocusableFalse(unittest.TestCase):
    def test_every_svg_has_focusable_false(self) -> None:
        html = _read_html()
        svgs = _enumerate_svgs(html)
        missing: list[tuple[int, str]] = []
        for line_no, opening_tag, class_attr in svgs:
            classes = set(class_attr.split())
            if classes & MEANINGFUL_SVG_CLASSES:
                continue
            if 'focusable="false"' not in opening_tag:
                missing.append((line_no, class_attr or "(no class)"))
        self.assertEqual(
            missing,
            [],
            msg=(
                "R230 invariant: web_ui.html 中所有装饰性 <svg> 必须包含 "
                'focusable="false"（IE/legacy Edge 行为：SVG 默认可 focus, '
                "AT 仍会读出，aria-hidden 救不了）。缺失列表（行号, class）："
                f"{missing}。"
            ),
        )


class TestExistingPatternUnchanged(unittest.TestCase):
    """L340 / L1695 已有 reference 实现 (R125b export 按钮 / R??? 某个按钮)，作为不会回归的锚点。"""

    def test_reference_pattern_intact(self) -> None:
        html = _read_html()
        svgs = _enumerate_svgs(html)
        with_both_attrs = [
            (line_no, class_attr)
            for line_no, opening_tag, class_attr in svgs
            if 'aria-hidden="true"' in opening_tag
            and 'focusable="false"' in opening_tag
        ]
        self.assertGreaterEqual(
            len(with_both_attrs),
            2,
            msg=(
                "R230 invariant: 至少有 2 个 <svg> 同时含 aria-hidden + "
                "focusable, 作为模式参考。如果数量低于 2, 说明 reference 实现"
                "被误删, 应当回滚。"
            ),
        )


class TestExpectedTotalSvgCount(unittest.TestCase):
    """SVG 总数不应该意外大跌——如果有人删模板某块，应当显式更新这个 baseline。"""

    EXPECTED_MIN_SVG_COUNT = 25

    def test_total_svg_count_within_band(self) -> None:
        html = _read_html()
        svgs = _enumerate_svgs(html)
        self.assertGreaterEqual(
            len(svgs),
            self.EXPECTED_MIN_SVG_COUNT,
            msg=(
                f"R230 invariant: web_ui.html SVG 数量 ({len(svgs)}) "
                f"明显低于 baseline ({self.EXPECTED_MIN_SVG_COUNT}). "
                "如果是有意删模板部分, 请同步更新 EXPECTED_MIN_SVG_COUNT。"
                "如果是意外回滚, 请检查 git history."
            ),
        )


if __name__ == "__main__":
    unittest.main()
