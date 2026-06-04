"""cr37 §8 #1 + #3 follow-up regression tests.

#1 [low] PLACEHOLDER_MAX_LENGTH constant extraction
   — single source of truth for 200-char clamp;
     prevents drift between ``task_queue.add_task`` clamp
     and ``web_ui_routes/task.py`` response check.

#3 [info] Yesno hide-textarea a11y hardening
   — ``display=none`` + ``aria-hidden=true`` + ``tabindex=-1``
     双保险（Safari + VoiceOver 旧版有 display:none-aware bug）。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TASK_QUEUE_PY = REPO_ROOT / "src" / "ai_intervention_agent" / "task_queue.py"
TASK_ROUTES_PY = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "web_ui_routes" / "task.py"
)
MULTI_TASK_JS = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "multi_task.js"
)


class TestPlaceholderMaxLengthConstant(unittest.TestCase):
    """cr37 §8 #1 — constant must exist, be 200, and replace inline 200 literals."""

    def test_constant_is_exported(self) -> None:
        from ai_intervention_agent.task_queue import PLACEHOLDER_MAX_LENGTH

        self.assertEqual(PLACEHOLDER_MAX_LENGTH, 200)
        self.assertIsInstance(PLACEHOLDER_MAX_LENGTH, int)

    def test_add_task_uses_constant(self) -> None:
        """``add_task`` 不应再有内嵌 200 literal for placeholder clamp。"""
        src = TASK_QUEUE_PY.read_text(encoding="utf-8")
        # 注意：测试是文本级别，必须区分"clamp 用法"和其他用 200 的地方。
        # 加 :PLACEHOLDER_MAX_LENGTH] 前缀 anchor 来锚定到 slice 语法。
        self.assertIn("s[:PLACEHOLDER_MAX_LENGTH]", src)

    def test_route_imports_constant(self) -> None:
        """``web_ui_routes/task.py`` 响应字段必须用常量而非 inline 200。"""
        src = TASK_ROUTES_PY.read_text(encoding="utf-8")
        self.assertIn("PLACEHOLDER_MAX_LENGTH", src)
        # 不能再有 inline ``> 200`` 用于 placeholder boundary check
        # （字符串级别 — 允许其他地方用 200 比如 HTTP 200 status）
        self.assertNotIn("len(feedback_placeholder.strip()) > 200", src)

    def test_route_uses_constant_in_response_field(self) -> None:
        src = TASK_ROUTES_PY.read_text(encoding="utf-8")
        self.assertIn('resp["placeholder_max_length"] = PLACEHOLDER_MAX_LENGTH', src)


class TestYesnoAccessibilityHardening(unittest.TestCase):
    """cr37 §8 #3 — hide textarea 必须 ``aria-hidden`` + ``tabindex=-1``，
    并在 reveal 时清除这些标记。
    """

    src = MULTI_TASK_JS.read_text(encoding="utf-8")

    def test_hide_sets_aria_hidden_true(self) -> None:
        m = re.search(
            r"function\s+updateYesnoButtonGroup\(questionType\)\s*\{([\s\S]*?)\n\}\n",
            self.src,
        )
        self.assertIsNotNone(m)
        assert m is not None
        body = m.group(1)
        self.assertIn('setAttribute("aria-hidden", "true")', body)
        self.assertIn('setAttribute("tabindex", "-1")', body)

    def test_reveal_removes_aria_hidden(self) -> None:
        m = re.search(
            r"function\s+updateYesnoButtonGroup\(questionType\)\s*\{([\s\S]*?)\n\}\n",
            self.src,
        )
        assert m is not None
        body = m.group(1)
        self.assertIn('removeAttribute("aria-hidden")', body)
        self.assertIn('removeAttribute("tabindex")', body)

    def test_hide_and_reveal_pair_is_symmetric(self) -> None:
        """每个 setAttribute 调用应有对应的 removeAttribute 调用。
        protect against future regression where reveal branch is reverted.
        """
        m = re.search(
            r"function\s+updateYesnoButtonGroup\(questionType\)\s*\{([\s\S]*?)\n\}\n",
            self.src,
        )
        assert m is not None
        body = m.group(1)
        # 1 set + 1 remove for aria-hidden
        self.assertEqual(body.count('"aria-hidden"'), 2)
        # 1 set + 1 remove for tabindex
        self.assertEqual(body.count('"tabindex"'), 2)


class TestClampBehaviorUnchanged(unittest.TestCase):
    """重构必须**不**改变 clamp 行为：long → 200 chars。"""

    def test_201_still_clamped_to_200(self) -> None:
        from ai_intervention_agent.task_queue import TaskQueue

        q = TaskQueue(persist_path=None)
        ok = q.add_task(task_id="t-201", prompt="hi", feedback_placeholder="x" * 201)
        self.assertTrue(ok)
        t = q.get_task("t-201")
        assert t is not None
        assert t.feedback_placeholder is not None
        self.assertEqual(len(t.feedback_placeholder), 200)

    def test_short_unchanged(self) -> None:
        from ai_intervention_agent.task_queue import TaskQueue

        q = TaskQueue(persist_path=None)
        ok = q.add_task(task_id="t-short", prompt="hi", feedback_placeholder="ok")
        self.assertTrue(ok)
        t = q.get_task("t-short")
        assert t is not None
        self.assertEqual(t.feedback_placeholder, "ok")


if __name__ == "__main__":
    unittest.main()
