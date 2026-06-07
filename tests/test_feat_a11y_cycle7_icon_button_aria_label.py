"""a11y-audit-cycle-7 Track A (R260) · icon-only button 必须有 accessible name。

背景
----

WCAG 2.1 SC 4.1.2 (Name, Role, Value)：所有交互元素必须有"可被辅助技术读
出的名字"。``<button>`` 元素的 accessible name 优先级是 ``aria-labelledby``
> ``aria-label`` > 内部 text content > ``title``。

**``title`` 单独使用 NOT 充分**：

- Screen reader 对 ``title`` 支持参差不齐 (e.g., NVDA 朗读，VoiceOver 仅
  hover 时朗读)
- 移动端/键盘用户根本看不到 ``title`` tooltip
- ARIA Authoring Practices 把 ``title`` 列为"最后兜底"，不应作为唯一 name
  source

icon-only button (无 text content，只有 ``<svg>``) 必须显式标注
``aria-label`` 或 ``aria-labelledby``。

cr49 §5 follow-up #6 audit 发现 ``#open-config-file-btn`` (settings 页 IDE
打开按钮) 是 icon-only + 仅 ``title``，违反 WCAG 4.1.2。Track A 修复 + 加
invariant 防止未来 regression。

回归契约
--------

1. 所有 ``class*=btn-icon-only`` 的 ``<button>`` 必须有 ``aria-label``
   或 ``aria-labelledby``
2. 所有 ``class*=close-btn`` 的 ``<button>`` 必须有 ``aria-label``
   或 ``aria-labelledby`` (同源 icon-only 模式)
3. ``#open-config-file-btn`` 必须有 ``data-i18n-aria-label="settings.
   openConfigInIde"`` (确保 aria-label 跟随 i18n)
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

HTML_PATH = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "ai_intervention_agent"
    / "templates"
    / "web_ui.html"
)

ICON_BUTTON_CLASS_RE = re.compile(
    # cycle-8 Track A 扩展（R260a）：把任何 ``<前缀>-close`` 也算 icon-only
    # （e.g. ``image-modal-close``），不只是 ``close-btn``。这避免组件按惯例
    # 命名时绕过 R260 检查。
    r"class=\"[^\"]*(?:btn-icon-only|close-btn|tab-close|btn-circle|\w+-close\b)[^\"]*\"",
    re.IGNORECASE,
)
HAS_ARIA_LABEL_RE = re.compile(r"\baria-label\s*=|aria-labelledby\s*=", re.IGNORECASE)
BUTTON_TAG_RE = re.compile(r"<button\b([^>]*)>", re.IGNORECASE)


def _find_icon_buttons_without_aria_label(html: str) -> list[str]:
    """Returns list of icon-style button opening tags without aria-label/aria-labelledby."""
    offenders: list[str] = []
    for m in BUTTON_TAG_RE.finditer(html):
        attrs = m.group(1)
        if ICON_BUTTON_CLASS_RE.search(attrs) and not HAS_ARIA_LABEL_RE.search(attrs):
            summary = re.sub(r"\s+", " ", m.group(0)).strip()[:200]
            offenders.append(summary)
    return offenders


class TestIconButtonsHaveAriaLabel(unittest.TestCase):
    """R260 · 所有 icon-style buttons 必须有 accessible name (WCAG 4.1.2)。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.html = HTML_PATH.read_text(encoding="utf-8")

    def test_no_icon_only_button_without_aria_label(self) -> None:
        offenders = _find_icon_buttons_without_aria_label(self.html)
        self.assertEqual(
            offenders,
            [],
            "R260 · 以下 icon-style <button> 缺少 aria-label 或 aria-labelledby"
            "（WCAG 4.1.2 violation，title 单独不充分）:\n  - "
            + "\n  - ".join(offenders),
        )


class TestOpenConfigButtonI18nAriaLabel(unittest.TestCase):
    """R260 · open-config-file-btn 必须有 data-i18n-aria-label 跟随 i18n。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.html = HTML_PATH.read_text(encoding="utf-8")

    def test_btn_has_data_i18n_aria_label(self) -> None:
        # 截取 open-config-file-btn 整个 opening tag (跨多行)
        tag_match = re.search(
            r"<button\b[^>]*?id=\"open-config-file-btn\"[^>]*?>",
            self.html,
            re.DOTALL,
        )
        self.assertIsNotNone(
            tag_match,
            "找不到 #open-config-file-btn — cycle-7 Track A 期望它存在",
        )
        assert tag_match is not None
        attrs = tag_match.group(0)
        self.assertIn(
            'data-i18n-aria-label="settings.openConfigInIde"',
            attrs,
            "#open-config-file-btn 缺少 data-i18n-aria-label，aria-label 不会跟随语言切换",
        )
        self.assertIn(
            "aria-label=",
            attrs,
            "#open-config-file-btn 缺少 aria-label 默认值 (WCAG 4.1.2)",
        )


if __name__ == "__main__":
    unittest.main()
