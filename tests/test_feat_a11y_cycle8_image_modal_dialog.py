"""a11y-audit-cycle-8 Track A (R261) · ``#image-modal`` dialog semantics 守护。

背景
----

cr50 §5 follow-up #1 + cycle-7 backlog Track B：模态对话框必须有
WCAG 4.1.2 + ARIA Authoring Practices Dialog Pattern 完整 markup：

1. ``role="dialog"`` —— 告诉 AT 这是 modal 对话框
2. ``aria-modal="true"`` —— 表明对话框 modal，AT 忽略背景内容
3. ``aria-label`` 或 ``aria-labelledby`` —— 给 AT 朗读的 dialog 名字

cycle-7 Track A 已扫了 button 级 (R260)，cycle-8 Track A 把 audit 范围
推到 dialog 容器级。

调研发现 3 个真 modal 容器：
- ``#code-paste-panel`` ✓ 完整合规 (role + aria-modal + aria-labelledby)
- ``#settings-panel`` ✓ 完整合规
- ``#image-modal`` ❌ 缺 role / aria-modal / aria-label，且其内置 close
  button 用 ``×`` 字符无 accessible name

(``#aiia-tri-state-panel`` 是 ``role="status"`` 用 ``aria-live="polite"``，
不是 modal，不在 audit 范围；``#drag-overlay`` 是 transient 装饰层，无
focus 交互，亦不属 modal pattern。)

回归契约
--------

3 invariants：
1. ``#image-modal`` 必有 ``role="dialog"`` + ``aria-modal="true"``
2. ``#image-modal`` 必有 ``aria-label`` 或 ``aria-labelledby``
3. ``#image-modal`` 必有 ``data-i18n-aria-label="page.imagePreview"``
   (确保 aria-label 跟随 i18n)
4. ``.image-modal-close`` button 必有 ``aria-label`` (因为内容仅 ``×``)
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


def _extract_tag_by_id(html: str, tag_id: str) -> str | None:
    """提取 ``id=tag_id`` 的开标签（跨多行）。"""
    m = re.search(
        rf"<(?:div|section|aside|dialog)\b[^>]*?\bid=\"{re.escape(tag_id)}\"[^>]*?>",
        html,
        re.DOTALL,
    )
    return m.group(0) if m else None


def _extract_button_by_class(html: str, cls: str) -> str | None:
    """提取 ``class*=cls`` 的第一个 button 开标签（跨多行）。"""
    m = re.search(
        rf"<button\b[^>]*?\bclass=\"[^\"]*\b{re.escape(cls)}\b[^\"]*\"[^>]*?>",
        html,
        re.DOTALL,
    )
    return m.group(0) if m else None


class TestImageModalDialogSemantics(unittest.TestCase):
    """R261 · #image-modal 必有完整 dialog pattern (WCAG 4.1.2)。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.html = HTML_PATH.read_text(encoding="utf-8")

    def test_has_role_dialog(self) -> None:
        tag = _extract_tag_by_id(self.html, "image-modal")
        self.assertIsNotNone(tag, "找不到 #image-modal — cycle-8 Track A 期望它存在")
        assert tag is not None
        self.assertRegex(
            tag,
            r'role\s*=\s*"dialog"',
            '#image-modal 缺 role="dialog" (WCAG 4.1.2 + ARIA Dialog Pattern)',
        )

    def test_has_aria_modal_true(self) -> None:
        tag = _extract_tag_by_id(self.html, "image-modal")
        assert tag is not None
        self.assertRegex(
            tag,
            r'aria-modal\s*=\s*"true"',
            '#image-modal 缺 aria-modal="true" (ARIA Dialog Pattern)',
        )

    def test_has_aria_label_or_labelledby(self) -> None:
        tag = _extract_tag_by_id(self.html, "image-modal")
        assert tag is not None
        self.assertRegex(
            tag,
            r"aria-label\s*=|aria-labelledby\s*=",
            "#image-modal 缺 aria-label 或 aria-labelledby (WCAG 4.1.2)",
        )

    def test_has_i18n_aria_label_for_locale_change(self) -> None:
        tag = _extract_tag_by_id(self.html, "image-modal")
        assert tag is not None
        self.assertIn(
            'data-i18n-aria-label="page.imagePreview"',
            tag,
            "#image-modal 缺 data-i18n-aria-label，切换语言时 aria-label 不会更新",
        )


class TestImageModalCloseButton(unittest.TestCase):
    """R261 · .image-modal-close 必有 aria-label (内容仅 ``×``)。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.html = HTML_PATH.read_text(encoding="utf-8")

    def test_close_button_has_aria_label(self) -> None:
        tag = _extract_button_by_class(self.html, "image-modal-close")
        self.assertIsNotNone(
            tag, "找不到 .image-modal-close button — cycle-8 期望它存在"
        )
        assert tag is not None
        self.assertRegex(
            tag,
            r"aria-label\s*=|aria-labelledby\s*=",
            ".image-modal-close 缺 accessible name (内容仅 × 字符，"
            "screen reader 朗读为 'multiplication sign')",
        )

    def test_close_button_has_type_button(self) -> None:
        # 在 <form> 上下文里不写 type 默认为 submit，意外刷新页面是常见 bug。
        # cycle-8 顺手 audit。
        tag = _extract_button_by_class(self.html, "image-modal-close")
        assert tag is not None
        self.assertRegex(
            tag,
            r'type\s*=\s*"button"',
            '.image-modal-close 缺 type="button"，'
            "在 form 上下文里默认 type=submit 会触发意外提交",
        )


class TestImagePreviewI18nKeyExists(unittest.TestCase):
    """R261 · page.imagePreview 必须在 3 个 locale 都存在 (lockstep)。"""

    LOCALES_DIR = (
        Path(__file__).resolve().parent.parent
        / "src"
        / "ai_intervention_agent"
        / "static"
        / "locales"
    )

    def test_key_in_all_required_locales(self) -> None:
        import json

        missing: list[str] = []
        for lang in ("en", "zh-CN", "zh-TW"):
            path = self.LOCALES_DIR / f"{lang}.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            if "imagePreview" not in data.get("page", {}):
                missing.append(lang)
        self.assertEqual(
            missing,
            [],
            f"page.imagePreview 缺失于 locale(s): {missing}。"
            f"i18n lockstep（CONTRIBUTING §3.quater）",
        )


if __name__ == "__main__":
    unittest.main()
