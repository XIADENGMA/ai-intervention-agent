"""R52-A：``task_queue`` 全部写路径必须走 ``_watched_write_lock``。

R51-A 起步只把 ``add_task`` 接到 watchdog。R52-A 把剩余 7 处写路径
（``clear_all_tasks`` / ``update_auto_resubmit_timeout_for_all`` /
``set_active_task`` / ``complete_task`` / ``remove_task`` /
``clear_completed_tasks`` / ``cleanup_completed_tasks``）都迁移过来，
让任何写侧 deadlock 无论发生在哪个方法都会被 daemon 捕获。

本测试用静态扫源码方式锁定契约 —— 任何未来的改动若退回裸
``self._lock.write_lock()``，CI 立刻 fail。"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import ai_intervention_agent.task_queue as task_queue

WRITE_METHOD_LABEL_MAP = {
    "add_task": "add_task",
    "clear_all_tasks": "clear_all_tasks",
    "update_auto_resubmit_timeout_for_all": "update_auto_resubmit_timeout_for_all",
    "set_active_task": "set_active_task",
    "complete_task": "complete_task",
    "remove_task": "remove_task",
    "clear_completed_tasks": "clear_completed_tasks",
    "cleanup_completed_tasks": "cleanup_completed_tasks",
}


class TestAllWritePathsUseWatchdog(unittest.TestCase):
    """每个写方法必须用 ``_watched_write_lock(self._lock, "<label>")`` 包装。"""

    def setUp(self) -> None:
        self.src = Path(task_queue.__file__).read_text(encoding="utf-8")

    def _extract_method_body(self, name: str) -> str:
        """提取方法 body：从 ``def name(`` 到下一个 ``\n    def `` 或文件尾。"""
        pattern = rf"\n    def {re.escape(name)}\("
        match = re.search(pattern, self.src)
        if not match:
            self.fail(f"找不到方法 {name}")
        start = match.start()
        # 下一个同级 method
        next_match = re.search(r"\n    def ", self.src[start + 1 :])
        end = (start + 1 + next_match.start()) if next_match else len(self.src)
        return self.src[start:end]

    def test_each_write_method_uses_watched_lock_with_correct_label(self) -> None:
        for method, expected_label in WRITE_METHOD_LABEL_MAP.items():
            with self.subTest(method=method):
                body = self._extract_method_body(method)
                expected = f'_watched_write_lock(self._lock, "{expected_label}")'
                self.assertIn(
                    expected,
                    body,
                    f"写方法 {method!r} 应当用 _watched_write_lock(label={expected_label!r}) "
                    f"包装写锁（R52-A 全覆盖）",
                )

    def test_no_raw_write_lock_remains_in_methods(self) -> None:
        """task_queue 类方法体内不应再有裸 ``self._lock.write_lock()``。"""
        for method in WRITE_METHOD_LABEL_MAP:
            with self.subTest(method=method):
                body = self._extract_method_body(method)
                self.assertNotIn(
                    "self._lock.write_lock()",
                    body,
                    f"写方法 {method!r} 不应再裸调 self._lock.write_lock()",
                )

    def test_module_level_no_raw_write_lock_outside_docstring(self) -> None:
        """全模块扫一次：``self._lock.write_lock()`` 仅允许出现在 docstring。"""
        # 把 docstring 段去掉再扫
        cleaned = re.sub(r'""".*?"""', "", self.src, flags=re.DOTALL)
        cleaned = re.sub(r"#.*", "", cleaned)  # 注释也去掉
        self.assertNotIn(
            "self._lock.write_lock()",
            cleaned,
            "全模块（除 docstring / 注释）不应再有裸 self._lock.write_lock()",
        )


class TestWatchdogLabelsAreUnique(unittest.TestCase):
    """所有 ``_watched_write_lock`` label 都应当独一无二（便于诊断时区分）。"""

    def setUp(self) -> None:
        self.src = Path(task_queue.__file__).read_text(encoding="utf-8")

    def test_no_duplicate_labels(self) -> None:
        # 扫所有 label，但忽略 docstring 里的示例
        cleaned = re.sub(r'""".*?"""', "", self.src, flags=re.DOTALL)
        labels = re.findall(
            r'_watched_write_lock\(self\._lock,\s*"([^"]+)"\)',
            cleaned,
        )
        self.assertEqual(
            sorted(labels),
            sorted(set(labels)),
            f"label 不应有重复（可能两个方法挪到了 watchdog 但用了同一个 label）：{labels}",
        )

    def test_labels_match_expected_set(self) -> None:
        cleaned = re.sub(r'""".*?"""', "", self.src, flags=re.DOTALL)
        labels = set(
            re.findall(
                r'_watched_write_lock\(self\._lock,\s*"([^"]+)"\)',
                cleaned,
            )
        )
        expected = set(WRITE_METHOD_LABEL_MAP.values())
        self.assertEqual(
            labels,
            expected,
            f"label 集合与期望不符 — 实际 {labels}, 期望 {expected}",
        )


class TestRealTaskQueueCallableThroughWatchdog(unittest.TestCase):
    """端到端：用真 TaskQueue 走完添加 → 完成 → 清理三段路径，全部不抛。"""

    def test_full_lifecycle_no_exception(self) -> None:
        q = task_queue.TaskQueue(max_tasks=5)
        try:
            self.assertTrue(q.add_task("life-1", "prompt"))
            self.assertTrue(q.complete_task("life-1", {"user_input": "ok"}))
            cleared = q.clear_completed_tasks()
            self.assertEqual(cleared, 1)
            count = q.get_task_count()
            self.assertEqual(count["total"], 0)
        finally:
            q.stop_cleanup()


if __name__ == "__main__":
    unittest.main()
