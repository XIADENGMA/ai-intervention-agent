"""R234 / Cycle 14 · F-cycle13-2: feedback-textarea disabled visual lives in CSS, not JS inline.

Why this invariant
------------------

R229 sank the disabled-state visuals for ``#submit-btn`` and
``#insert-code-btn`` from JS inline styles into CSS ``:disabled`` rules
(with ``!important`` to override the brand-gradient ``!important``).
At that time R229 explicitly left ``feedback-text`` (the textarea)
alone with a defensive comment + invariant test, on the rationale
that ``.feedback-textarea`` CSS does not use ``!important`` so the JS
inline writes actually take effect.

R234 reverses that decision after observing two things:

1. The JS inline values were ``#2c2c2e`` / ``#8e8e93`` /
   ``rgba(255,255,255,0.03)`` / ``#f5f5f7`` — all **dark-theme-only
   hex codes**. On light theme the disabled textarea showed dark
   colors on a beige page, with reversed contrast. Same class of bug
   R229 fixed for buttons (theme-incorrect inline color override).
2. After R229 + R230 + R232 standardized "visual state belongs to
   CSS, JS only flips the `disabled` attribute" across button and
   icon paths, the textarea was the only outlier. Inconsistency is
   itself a maintenance hazard.

R234 lock:

* CSS has ``.feedback-textarea:disabled`` rule for the default (dark)
  theme.
* CSS has ``[data-theme="light"] .feedback-textarea:disabled`` rule.
* Light-theme rule uses ``!important`` because the enabled-state
  light-theme rule
  ``[data-theme="light"] .feedback-textarea { background: ... !important }``
  also uses ``!important`` and would otherwise win.
* Both rules include ``cursor: not-allowed`` (UX cue) and
  ``background`` + ``color`` + ``border-color`` (visual cue triple).

Companion test in R229's file (``TestFeedbackTextareaInlineStyleRemovedByR234``)
asserts the JS side: ``disableSubmitButton`` / ``enableSubmitButton``
no longer write inline color/background/cursor for the textarea.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CSS_PATH = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "css" / "main.css"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _extract_rule_block(css: str, selector_re: str) -> str:
    match = re.search(rf"{selector_re}\s*\{{([^}}]+)\}}", css)
    assert match is not None, f"Cannot find CSS rule matching: {selector_re}"
    return match.group(1)


class TestDarkThemeDisabledRule(unittest.TestCase):
    def test_default_disabled_selector_exists(self) -> None:
        css = _read(CSS_PATH)
        self.assertRegex(
            css,
            r"\.feedback-textarea:disabled",
            msg=(
                "R234 invariant: 必须有 .feedback-textarea:disabled 规则。"
                "缺失会让 R234 删掉 JS inline 后, 禁用 textarea 视觉与启用一致, "
                "用户察觉不到 textarea 被禁用 (R229 同款 bug)。"
            ),
        )

    def test_default_disabled_rule_has_visual_cues(self) -> None:
        css = _read(CSS_PATH)
        block = _extract_rule_block(css, r"\.feedback-textarea:disabled")
        for prop in ("background", "color", "cursor", "border-color"):
            self.assertIn(
                prop,
                block,
                msg=(
                    f"R234 invariant: 深色模式 .feedback-textarea:disabled 必须"
                    f"声明 {prop}; 缺失会让禁用视觉漏掉关键提示 (cursor: not-allowed"
                    "是悬停提示, background/color/border 是静态视觉, 缺一不可)。"
                ),
            )


class TestLightThemeDisabledRule(unittest.TestCase):
    def test_light_disabled_selector_exists(self) -> None:
        css = _read(CSS_PATH)
        self.assertRegex(
            css,
            r'\[data-theme="light"\]\s+\.feedback-textarea:disabled',
            msg=(
                "R234 invariant: 必须有 [data-theme='light'] .feedback-textarea:disabled "
                "规则。R229 同款问题: 启用规则 [data-theme='light'] .feedback-textarea "
                "用了 !important, 不加同 specificity + !important 的 :disabled 规则会"
                "让浅色主题禁用视觉与启用一致。"
            ),
        )

    def test_light_disabled_rule_uses_important(self) -> None:
        css = _read(CSS_PATH)
        block = _extract_rule_block(
            css,
            r'\[data-theme="light"\]\s+\.feedback-textarea:disabled,?\s*'
            r'\n?\s*\[data-theme="light"\]\s+textarea\.feedback-textarea:disabled',
        )
        self.assertIn(
            "!important",
            block,
            msg=(
                "R234 invariant: 浅色模式 :disabled 规则必须用 !important, 否则启用"
                "规则的 'background: var(--bg-input, #e8e6dc) !important' 永远赢, "
                "禁用视觉退化为零 (R229 同款根因)。"
            ),
        )

    def test_light_disabled_rule_has_visual_cues(self) -> None:
        css = _read(CSS_PATH)
        block = _extract_rule_block(
            css,
            r'\[data-theme="light"\]\s+\.feedback-textarea:disabled,?\s*'
            r'\n?\s*\[data-theme="light"\]\s+textarea\.feedback-textarea:disabled',
        )
        for prop in ("background", "color", "cursor", "border-color"):
            self.assertIn(prop, block)


class TestUsesThemeAgnosticRgba(unittest.TestCase):
    """禁用规则用 rgba 半透明而非 brand-color hex (避免触发 R66 brand drift)。"""

    def test_dark_disabled_uses_rgba(self) -> None:
        css = _read(CSS_PATH)
        block = _extract_rule_block(css, r"\.feedback-textarea:disabled")
        self.assertIn(
            "rgba(",
            block,
            msg=(
                "R234 invariant: 深色模式 :disabled 规则推荐用 rgba 半透明 (例如 "
                "rgba(255,255,255,0.02))而非 hex 直写, 避免触发 R66 brand-color "
                "drift 检测 (R229 同款做法)。如果未来用 var(--xxx) 等 design "
                "token 替换, 请同步更新此测试或移除。"
            ),
        )

    def test_light_disabled_uses_rgba(self) -> None:
        css = _read(CSS_PATH)
        block = _extract_rule_block(
            css,
            r'\[data-theme="light"\]\s+\.feedback-textarea:disabled,?\s*'
            r'\n?\s*\[data-theme="light"\]\s+textarea\.feedback-textarea:disabled',
        )
        self.assertIn("rgba(", block)


if __name__ == "__main__":
    unittest.main()
