"""R53-A：``TaskQueue.add_task`` 必须对 prompt 字节数做 6 MB / 10 MB 双阈值校验。

| 输入字节数 | add_task 行为     | 日志             |
| ---------- | ----------------- | ---------------- |
| ≤ 6 MB     | 接受              | 无               |
| 6-10 MB    | 接受 + warn       | warning 一条     |
| > 10 MB    | 拒绝 (return False) | warning 一条 |

设计目标：保护进程内存 / SSE history deque / 跨进程 IPC，但**不破坏正常业务**
（人类可读 prompt 几乎从不接近 6 MB）。
"""

from __future__ import annotations

import logging
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import task_queue


class TestPromptSizeAcceptance(unittest.TestCase):
    """正常路径：≤ 6 MB prompt 必须能 add_task 成功，无 warning。"""

    def setUp(self) -> None:
        self.q = task_queue.TaskQueue(max_tasks=5)

    def tearDown(self) -> None:
        self.q.stop_cleanup()

    def test_small_prompt_accepted(self) -> None:
        small_prompt = "hello"
        with patch.object(task_queue.logger, "warning") as fake_warn:
            ok = self.q.add_task("t-small", small_prompt)
        self.assertTrue(ok)
        # 不应有任何 warning（小 prompt 走快速路径）
        self.assertEqual(fake_warn.call_count, 0)

    def test_5mb_prompt_accepted_no_warn(self) -> None:
        # 5 MB < 6 MB warn 阈值
        prompt = "X" * (5 * 1024 * 1024)
        with patch.object(task_queue.logger, "warning") as fake_warn:
            ok = self.q.add_task("t-5mb", prompt)
        self.assertTrue(ok)
        self.assertEqual(fake_warn.call_count, 0)


class TestPromptSizeWarning(unittest.TestCase):
    """6 MB - 10 MB 区间：accept + warn。"""

    def setUp(self) -> None:
        self.q = task_queue.TaskQueue(max_tasks=5)

    def tearDown(self) -> None:
        self.q.stop_cleanup()

    def test_7mb_prompt_warned_but_accepted(self) -> None:
        # 7 MB ∈ (6 MB, 10 MB)
        prompt = "X" * (7 * 1024 * 1024)
        with patch.object(task_queue.logger, "warning") as fake_warn:
            ok = self.q.add_task("t-7mb", prompt)
        self.assertTrue(ok)
        # 至少一条 warn 提到 size
        self.assertGreaterEqual(fake_warn.call_count, 1)
        warn_str = "\n".join(str(c) for c in fake_warn.call_args_list)
        self.assertIn("R53-A", warn_str)
        self.assertIn("warn 阈值", warn_str)


class TestPromptSizeRejection(unittest.TestCase):
    """> 10 MB：reject + warn。"""

    def setUp(self) -> None:
        self.q = task_queue.TaskQueue(max_tasks=5)

    def tearDown(self) -> None:
        self.q.stop_cleanup()

    def test_11mb_prompt_rejected(self) -> None:
        prompt = "X" * (11 * 1024 * 1024)
        with patch.object(task_queue.logger, "warning") as fake_warn:
            ok = self.q.add_task("t-11mb", prompt)
        self.assertFalse(ok, "11 MB prompt 必须被拒绝")
        # 没有进队列
        self.assertIsNone(self.q.get_task("t-11mb"))
        # 至少一条 warn 提到 R53-A 拒绝
        self.assertGreaterEqual(fake_warn.call_count, 1)
        warn_str = "\n".join(str(c) for c in fake_warn.call_args_list)
        self.assertIn("R53-A", warn_str)
        self.assertIn("硬上限", warn_str)

    def test_50mb_prompt_rejected_does_not_oom(self) -> None:
        """50 MB 也必须被快速拒绝；不应进 Task() 构造路径产生大对象拷贝。"""
        prompt = "X" * (50 * 1024 * 1024)
        ok = self.q.add_task("t-50mb", prompt)
        self.assertFalse(ok)
        self.assertIsNone(self.q.get_task("t-50mb"))


class TestThresholdConstantsHaveSensibleBounds(unittest.TestCase):
    """阈值常量必须在合理区间。"""

    def test_warn_threshold_at_least_1mb(self) -> None:
        # < 1 MB 会因为正常 markdown 摘要触发 warn，假阳性多
        self.assertGreaterEqual(task_queue._PROMPT_WARN_BYTES, 1 * 1024 * 1024)

    def test_reject_threshold_greater_than_warn(self) -> None:
        self.assertGreater(
            task_queue._PROMPT_REJECT_BYTES, task_queue._PROMPT_WARN_BYTES
        )

    def test_reject_threshold_at_most_64mb(self) -> None:
        # > 64 MB 失去防御意义，进程已经在 OOM 边缘
        self.assertLessEqual(task_queue._PROMPT_REJECT_BYTES, 64 * 1024 * 1024)


class TestPromptSizeEdgeCases(unittest.TestCase):
    """边界条件：空 prompt、刚好等于阈值、UTF-8 多字节。"""

    def setUp(self) -> None:
        self.q = task_queue.TaskQueue(max_tasks=10)

    def tearDown(self) -> None:
        self.q.stop_cleanup()

    def test_empty_prompt_accepted(self) -> None:
        ok = self.q.add_task("t-empty", "")
        self.assertTrue(ok)

    def test_exactly_at_warn_boundary_no_warn(self) -> None:
        # 刚好等于 warn 阈值（不超）→ 不 warn
        prompt = "X" * task_queue._PROMPT_WARN_BYTES
        with patch.object(task_queue.logger, "warning") as fake_warn:
            ok = self.q.add_task("t-warn-edge", prompt)
        self.assertTrue(ok)
        self.assertEqual(fake_warn.call_count, 0)

    def test_one_byte_over_warn_triggers_warn(self) -> None:
        prompt = "X" * (task_queue._PROMPT_WARN_BYTES + 1)
        with patch.object(task_queue.logger, "warning") as fake_warn:
            ok = self.q.add_task("t-warn-over", prompt)
        self.assertTrue(ok)
        self.assertGreaterEqual(fake_warn.call_count, 1)

    def test_utf8_multibyte_counted_in_bytes_not_chars(self) -> None:
        """7 MB 中文 (UTF-8 3 字节/字) 也应触发 warn。

        之前若用 ``len(prompt)`` 而不是 ``encode().__len__()`` 会漏掉一半 size。"""
        # 3 MB chars × 3 bytes/char = 9 MB UTF-8 bytes（落在 6-10 MB warn 区间）
        chars_count = 3 * 1024 * 1024
        prompt = "测" * chars_count
        with patch.object(task_queue.logger, "warning") as fake_warn:
            ok = self.q.add_task("t-utf8", prompt)
        self.assertTrue(ok)
        self.assertGreaterEqual(
            fake_warn.call_count,
            1,
            "UTF-8 多字节字符的字节数应当算到 prompt size 里",
        )


class TestNonStringPromptDoesNotCrash(unittest.TestCase):
    """caller 传非 str 类型也不应让 add_task 抛 TypeError。"""

    def setUp(self) -> None:
        # 抑制 pydantic 验证器自身打的日志，让本测试输出干净
        logging.getLogger("pydantic").setLevel(logging.CRITICAL)
        self.q = task_queue.TaskQueue(max_tasks=5)

    def tearDown(self) -> None:
        self.q.stop_cleanup()

    def test_int_prompt_returns_false_or_handled(self) -> None:
        # 非 str：encode() 会抛 AttributeError，被 try/except 接住，
        # prompt_bytes=0，跳过 size gate，进入 Task() pydantic 校验，
        # 因类型不对返回 False（ValidationError 被 caller 吞）或抛
        # 异常（这两种 R53-A 都不在意，只要不让 size gate 自己 crash）
        non_str_prompt: object = 12345
        try:
            ok = self.q.add_task("t-non-str", non_str_prompt)  # ty: ignore[invalid-argument-type]
        except Exception:
            # pydantic ValidationError 是合法的下游错误；R53-A 不该让它们更早
            # 在 size gate 阶段失败，这里就当 pass
            return
        # 若没抛，那应当返回 False（pydantic 验证 prompt 必须是 str）
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
