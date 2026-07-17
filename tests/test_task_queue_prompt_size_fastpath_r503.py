"""R503 - TaskQueue prompt byte-size guard fast path."""

from __future__ import annotations

import inspect
import unittest
from unittest.mock import patch

import ai_intervention_agent.task_queue as task_queue


class TestPromptUtf8GuardSource(unittest.TestCase):
    def test_add_task_uses_helper_instead_of_inline_encode_len(self) -> None:
        source = inspect.getsource(task_queue.TaskQueue.add_task)

        self.assertIn("_prompt_utf8_size_for_guard(prompt)", source)
        self.assertNotIn('prompt.encode("utf-8", errors="replace")', source)

    def test_helper_uses_upper_bound_and_ascii_exact_path_before_encoding(self) -> None:
        source = inspect.getsource(task_queue._prompt_utf8_size_for_guard)

        self.assertIn("char_count * 4 <= _PROMPT_WARN_BYTES", source)
        self.assertIn("prompt.isascii()", source)
        self.assertLess(
            source.index("prompt.isascii()"),
            source.index('prompt.encode("utf-8", errors="replace")'),
        )


class TestPromptUtf8GuardBehavior(unittest.TestCase):
    def test_small_non_ascii_prompt_can_skip_exact_encode(self) -> None:
        with patch.object(task_queue, "_PROMPT_WARN_BYTES", 4):
            self.assertEqual(task_queue._prompt_utf8_size_for_guard("测"), 1)

        self.assertEqual(len("测".encode()), 3)

    def test_ascii_prompt_returns_exact_count_near_threshold(self) -> None:
        with patch.object(task_queue, "_PROMPT_WARN_BYTES", 4):
            self.assertEqual(task_queue._prompt_utf8_size_for_guard("x" * 8), 8)

    def test_non_ascii_prompt_returns_exact_count_near_threshold(self) -> None:
        with patch.object(task_queue, "_PROMPT_WARN_BYTES", 4):
            self.assertEqual(task_queue._prompt_utf8_size_for_guard("测测"), 6)

    def test_add_task_small_non_ascii_does_not_warn_when_proven_under_limit(
        self,
    ) -> None:
        q = task_queue.TaskQueue(max_tasks=5)
        try:
            with (
                patch.object(task_queue, "_PROMPT_WARN_BYTES", 16),
                patch.object(task_queue, "_PROMPT_REJECT_BYTES", 32),
                patch.object(task_queue.logger, "warning") as fake_warn,
            ):
                ok = q.add_task("small-nonascii", "测")

            self.assertTrue(ok)
            self.assertEqual(fake_warn.call_count, 0)
        finally:
            q.stop_cleanup()

    def test_add_task_non_ascii_warns_using_exact_utf8_size(self) -> None:
        q = task_queue.TaskQueue(max_tasks=5)
        try:
            with (
                patch.object(task_queue, "_PROMPT_WARN_BYTES", 16),
                patch.object(task_queue, "_PROMPT_REJECT_BYTES", 32),
                patch.object(task_queue.logger, "warning") as fake_warn,
            ):
                ok = q.add_task("warn-nonascii", "测" * 6)

            self.assertTrue(ok)
            self.assertGreaterEqual(fake_warn.call_count, 1)
            self.assertIn(
                "warn 阈值", "\n".join(str(c) for c in fake_warn.call_args_list)
            )
        finally:
            q.stop_cleanup()

    def test_add_task_ascii_rejects_using_exact_character_count(self) -> None:
        q = task_queue.TaskQueue(max_tasks=5)
        try:
            with (
                patch.object(task_queue, "_PROMPT_WARN_BYTES", 16),
                patch.object(task_queue, "_PROMPT_REJECT_BYTES", 32),
                patch.object(task_queue.logger, "warning") as fake_warn,
            ):
                ok = q.add_task("reject-ascii", "x" * 33)

            self.assertFalse(ok)
            self.assertIsNone(q.get_task("reject-ascii"))
            self.assertIn("硬上限", "\n".join(str(c) for c in fake_warn.call_args_list))
        finally:
            q.stop_cleanup()


if __name__ == "__main__":
    unittest.main()
