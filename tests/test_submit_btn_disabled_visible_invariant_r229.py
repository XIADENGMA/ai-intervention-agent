"""R229 / Cycle 13 invariant: #submit-btn 与 #insert-code-btn 禁用状态视觉降级。

为什么需要这条不变量
----------------------

R229 之前，``disableSubmitButton()`` (app.js) 给两个按钮写 inline
``.style.backgroundColor = "#3a3a3c"``，期望把禁用状态降级成灰色。但
``main.css`` 里 ``#submit-btn { background: linear-gradient(...) !important }``
对所有状态 (无 ``:not(:disabled)`` 限定) 都生效——CSS ``!important`` 永远赢
过 inline non-important 声明 (W3C CSS Cascade Spec 优先级：author
``!important`` > inline normal)，所以禁用按钮视觉与启用完全一致，用户
点击没反应才能发现"哦原来是禁用了"。R229 把降级视觉下沉到 CSS 的
``:disabled`` pseudo-class，并把 JS 的 inline color 抠掉（只保留
``.disabled`` 属性切换）。

这条不变量 lock 住 R229 的两个修复点：

1. CSS 必须有 ``#submit-btn:disabled`` / ``#insert-code-btn:disabled``
   规则 (深 + 浅两套主题)，否则禁用状态又会回到"看起来一模一样"的
   bug 状态。
2. JS 的 ``disableSubmitButton`` / ``enableSubmitButton`` 必须不再给
   ``#submit-btn`` / ``#insert-code-btn`` 写 ``style.backgroundColor``——
   否则即便 CSS 加了 ``:disabled`` 规则，inline 也会 silently 覆盖
   （inline normal < CSS !important，但如果谁日后把 CSS 的
   ``!important`` 删掉，inline 又会赢，形成新一轮 silent override）。

测试结构
--------

* ``TestCssHasDisabledRule``：CSS 文件包含两个按钮的 ``:disabled``
  选择器，深+浅两套主题各一套。
* ``TestCssDisabledRuleHasOverride``：``:disabled`` 规则用了
  ``!important``，能 override 启用规则的 ``!important``。
* ``TestJsDoesNotInlineColorForButtons``：``app.js`` 的
  ``disableSubmitButton`` / ``enableSubmitButton`` 不给
  ``submitBtn`` / ``insertBtn`` 写任何 ``.style.backgroundColor``
  ``.style.color`` ``.style.cursor``。
* ``TestJsStillTogglesDisabledAttribute``：JS 仍然切换 ``.disabled``
  属性（删除 inline 的同时不能把整个降级逻辑也删掉）。
* ``TestFeedbackTextareaInlineStyleKept``：``feedback-text`` 的 inline
  styling 故意保留，因为 textarea 的 CSS 没用 ``!important``，
  R229 不需要碰它（防御性 lock，避免后续误删）。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CSS_PATH = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "css" / "main.css"
APP_JS_PATH = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "app.js"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TestCssHasDisabledRule(unittest.TestCase):
    def test_dark_theme_disabled_selector_present(self) -> None:
        css = _read(CSS_PATH)
        self.assertRegex(
            css,
            r"#submit-btn:disabled",
            msg=(
                "R229 invariant: main.css 必须包含 '#submit-btn:disabled' 选择器，"
                "否则启用规则的 !important 渐变会让禁用按钮视觉与启用一致 "
                "(W3C CSS cascade: author !important > inline normal)。"
            ),
        )
        self.assertRegex(
            css,
            r"#insert-code-btn:disabled",
            msg=(
                "R229 invariant: main.css 必须包含 '#insert-code-btn:disabled' 选择器。"
            ),
        )

    def test_light_theme_disabled_selector_present(self) -> None:
        css = _read(CSS_PATH)
        self.assertRegex(
            css,
            r'\[data-theme="light"\]\s+#submit-btn:disabled',
            msg=(
                "R229 invariant: 浅色主题必须有 '#submit-btn:disabled' 规则，"
                "否则 light theme 下禁用按钮仍显示橙色 (CSS #d97757 !important "
                "win over inline non-important)。"
            ),
        )
        self.assertRegex(
            css,
            r'\[data-theme="light"\]\s+#insert-code-btn:disabled',
        )


class TestCssDisabledRuleHasOverride(unittest.TestCase):
    """:disabled 规则必须用 !important，否则无法 override 启用规则的 !important。"""

    def test_dark_disabled_rule_uses_important(self) -> None:
        css = _read(CSS_PATH)
        match = re.search(
            r"#submit-btn:disabled,?\s*\n?\s*#insert-code-btn:disabled\s*\{([^}]+)\}",
            css,
        )
        assert match is not None, (
            "R229 invariant: 期望深色模式合并了 #submit-btn:disabled + "
            "#insert-code-btn:disabled 一条规则；如果未来拆开，请同步更新此测试。"
        )
        block = match.group(1)
        self.assertIn(
            "!important",
            block,
            msg=(
                "R229 invariant: 深色模式 :disabled 规则必须用 !important，否则启用"
                "规则的 'background: linear-gradient(...) !important' 永远赢，禁用"
                "视觉退化为零。"
            ),
        )

    def test_light_disabled_rule_uses_important(self) -> None:
        css = _read(CSS_PATH)
        match = re.search(
            r'\[data-theme="light"\]\s+#submit-btn:disabled,?\s*'
            r'\n?\s*\[data-theme="light"\]\s+#insert-code-btn:disabled'
            r"\s*\{([^}]+)\}",
            css,
        )
        assert match is not None
        block = match.group(1)
        self.assertIn("!important", block)


class TestJsDoesNotInlineColorForButtons(unittest.TestCase):
    """app.js 不再给 #submit-btn / #insert-code-btn 写 inline background/color/cursor。"""

    def _function_body(self, name: str) -> str:
        js = _read(APP_JS_PATH)
        match = re.search(
            rf"function {re.escape(name)}\(\)\s*\{{(.*?)\n\}}",
            js,
            re.DOTALL,
        )
        assert match is not None, f"无法在 app.js 找到函数 {name}"
        return match.group(1)

    def test_disable_does_not_set_submit_btn_inline_color(self) -> None:
        body = self._function_body("disableSubmitButton")
        forbidden_patterns = [
            r"submitBtn\.style\.backgroundColor",
            r"submitBtn\.style\.color",
            r"submitBtn\.style\.cursor",
        ]
        for pat in forbidden_patterns:
            self.assertNotRegex(
                body,
                pat,
                msg=(
                    f"R229 invariant: disableSubmitButton 不能再写 inline {pat}——"
                    "CSS :disabled 规则已接管禁用视觉，inline non-important 在 CSS "
                    "!important 面前永远输，这里写了也只是死代码，但读起来误导后人 "
                    "(让人以为 JS 才是禁用降级的真相)。"
                ),
            )

    def test_disable_does_not_set_insert_btn_inline_color(self) -> None:
        body = self._function_body("disableSubmitButton")
        forbidden_patterns = [
            r"insertBtn\.style\.backgroundColor",
            r"insertBtn\.style\.color",
            r"insertBtn\.style\.cursor",
        ]
        for pat in forbidden_patterns:
            self.assertNotRegex(body, pat)

    def test_enable_does_not_set_submit_btn_inline_color(self) -> None:
        body = self._function_body("enableSubmitButton")
        forbidden_patterns = [
            r"submitBtn\.style\.backgroundColor",
            r"submitBtn\.style\.color",
            r"submitBtn\.style\.cursor",
        ]
        for pat in forbidden_patterns:
            self.assertNotRegex(body, pat)

    def test_enable_does_not_set_insert_btn_inline_color(self) -> None:
        body = self._function_body("enableSubmitButton")
        forbidden_patterns = [
            r"insertBtn\.style\.backgroundColor",
            r"insertBtn\.style\.color",
            r"insertBtn\.style\.cursor",
        ]
        for pat in forbidden_patterns:
            self.assertNotRegex(body, pat)


class TestJsStillTogglesDisabledAttribute(unittest.TestCase):
    """删 inline color 时，不能顺手把 .disabled 属性切换也删掉——否则按钮真的能被点击。"""

    def _function_body(self, name: str) -> str:
        js = _read(APP_JS_PATH)
        match = re.search(
            rf"function {re.escape(name)}\(\)\s*\{{(.*?)\n\}}",
            js,
            re.DOTALL,
        )
        assert match is not None
        return match.group(1)

    def test_disable_sets_submit_disabled_true(self) -> None:
        body = self._function_body("disableSubmitButton")
        self.assertRegex(
            body,
            r"submitBtn\.disabled\s*=\s*true",
            msg=(
                "R229 invariant: disableSubmitButton 必须设置 submitBtn.disabled = true，"
                "否则用户能点击表面禁用的按钮触发重复提交 (CSS :disabled pseudo-class "
                "靠 disabled 属性激活, 不设属性则视觉降级和功能禁用全部失效)。"
            ),
        )

    def test_disable_sets_insert_disabled_true(self) -> None:
        body = self._function_body("disableSubmitButton")
        self.assertRegex(body, r"insertBtn\.disabled\s*=\s*true")

    def test_enable_sets_submit_disabled_false(self) -> None:
        body = self._function_body("enableSubmitButton")
        self.assertRegex(body, r"submitBtn\.disabled\s*=\s*false")

    def test_enable_sets_insert_disabled_false(self) -> None:
        body = self._function_body("enableSubmitButton")
        self.assertRegex(body, r"insertBtn\.disabled\s*=\s*false")


class TestFeedbackTextareaInlineStyleRemovedByR234(unittest.TestCase):
    """R234 follow-up: textarea 的 inline styling 已下沉到 CSS, JS 不应再写。

    R229 当时定的 "故意保留 textarea inline" 现在被 R234 反转——textarea
    虽然 CSS 没用 !important, inline 能生效, 但 R229 写死的 4 个 hex
    (#2c2c2e / #8e8e93 / rgba(255,255,255,0.03) / #f5f5f7) 全是 dark-theme
    色, 浅色主题 textarea 禁用视觉错位。R234 给浅+深两套主题加 CSS
    :disabled 规则后, JS inline 反而成了多余的死代码。
    """

    def _function_body(self, name: str) -> str:
        js = _read(APP_JS_PATH)
        match = re.search(
            rf"function {re.escape(name)}\(\)\s*\{{(.*?)\n\}}",
            js,
            re.DOTALL,
        )
        assert match is not None
        return match.group(1)

    def test_disable_does_not_inline_feedback_text_color(self) -> None:
        body = self._function_body("disableSubmitButton")
        forbidden = [
            r"feedbackText\.style\.backgroundColor",
            r"feedbackText\.style\.color",
            r"feedbackText\.style\.cursor",
        ]
        for pat in forbidden:
            self.assertNotRegex(
                body,
                pat,
                msg=(
                    f"R234 invariant: disableSubmitButton 不能再写 inline {pat}——"
                    "R234 已把 textarea 的禁用视觉下沉到 CSS .feedback-textarea:disabled "
                    "(深+浅两套), inline 写法会引入 dark-theme-only hex 在浅色主题"
                    "下错位, 等价于 R229 修过的同一类型 bug。"
                ),
            )

    def test_enable_does_not_inline_feedback_text_color(self) -> None:
        body = self._function_body("enableSubmitButton")
        forbidden = [
            r"feedbackText\.style\.backgroundColor",
            r"feedbackText\.style\.color",
            r"feedbackText\.style\.cursor",
        ]
        for pat in forbidden:
            self.assertNotRegex(body, pat)

    def test_disable_still_sets_disabled_attribute(self) -> None:
        body = self._function_body("disableSubmitButton")
        self.assertRegex(
            body,
            r"feedbackText\.disabled\s*=\s*true",
            msg=(
                "R234 invariant: disableSubmitButton 必须仍切换 feedbackText.disabled = "
                "true, 否则 CSS :disabled pseudo-class 不会激活, 用户能继续往禁用 "
                "textarea 里打字, 后端不知情。"
            ),
        )

    def test_enable_still_sets_disabled_false(self) -> None:
        body = self._function_body("enableSubmitButton")
        self.assertRegex(body, r"feedbackText\.disabled\s*=\s*false")


if __name__ == "__main__":
    unittest.main()
