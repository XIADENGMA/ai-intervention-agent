"""R23.4 · ``TaskQueue.get_all_tasks_with_stats`` 合并读锁的契约测试

背景
----
R23.4 之前 ``web_ui_routes/task.py::get_tasks`` 用 ``get_all_tasks()``
+ ``get_task_count()`` 两次独立调用，每次都进入一次 ``read_lock`` 上下文，
hot path 上累积浪费一次 RWLock atomic 进出 + 一次 list view 重建。新方法
``get_all_tasks_with_stats`` 在单一临界区里同时返回 list 与 stats，并把
原本两次读之间的 1-step skew 升级成完全一致的原子快照。

本测试覆盖五个层面：

1.  **API 存在性**：方法签名稳定（返回 ``tuple[list[Task], dict]``）。
2.  **行为等价性**：稳态下与「``get_all_tasks()`` + ``get_task_count()``」
    返回值完全一致。
3.  **原子快照不变量**：哪怕和 writer 高速并发，``len(tasks) ==
    stats['total']`` 始终成立，保留单调性 invariant。
4.  **源码契约**：路由层 ``web_ui_routes/task.py::get_tasks`` 已切换到
    新 API，且新方法实现单一 ``read_lock`` 边界内。
5.  **文档契约**：docstring 必须提到 R23.4 与单次 read_lock 的优化目的。
"""

from __future__ import annotations

import inspect
import re
import threading
import time
import unittest
from pathlib import Path

from task_queue import TaskQueue

REPO_ROOT = Path(__file__).resolve().parent.parent
TASK_QUEUE_PY = REPO_ROOT / "task_queue.py"
TASK_ROUTE_PY = REPO_ROOT / "web_ui_routes" / "task.py"


class _TaskQueueFixture(unittest.TestCase):
    """基类：自带 stop_cleanup 清理，避免后台线程残留。"""

    def _make(self, max_tasks: int = 10) -> TaskQueue:
        tq = TaskQueue(max_tasks=max_tasks)
        self.addCleanup(tq.stop_cleanup)
        return tq


# ---------------------------------------------------------------------------
# 1. API 存在性
# ---------------------------------------------------------------------------


class TestApiExists(_TaskQueueFixture):
    """新方法签名稳定。"""

    def test_method_exists_and_callable(self) -> None:
        tq = self._make()
        self.assertTrue(callable(getattr(tq, "get_all_tasks_with_stats", None)))

    def test_returns_tuple_of_list_and_dict(self) -> None:
        tq = self._make()
        result = tq.get_all_tasks_with_stats()
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)
        tasks, stats = result
        self.assertIsInstance(tasks, list)
        self.assertIsInstance(stats, dict)

    def test_stats_dict_has_required_keys(self) -> None:
        tq = self._make()
        _, stats = tq.get_all_tasks_with_stats()
        for key in ("total", "pending", "active", "completed", "max"):
            self.assertIn(key, stats, f"stats 必须包含 {key} 字段")
            self.assertIsInstance(stats[key], int, f"{key} 必须是 int")


# ---------------------------------------------------------------------------
# 2. 行为等价性
# ---------------------------------------------------------------------------


class TestBehaviouralEquivalence(_TaskQueueFixture):
    """与旧 API 在稳态下行为完全一致。"""

    def test_empty_queue(self) -> None:
        tq = self._make()
        tasks, stats = tq.get_all_tasks_with_stats()
        self.assertEqual(tasks, [])
        self.assertEqual(stats["total"], 0)
        self.assertEqual(stats["pending"], 0)
        self.assertEqual(stats["active"], 0)
        self.assertEqual(stats["completed"], 0)
        self.assertEqual(stats["max"], tq.max_tasks)

    def test_matches_legacy_get_all_tasks(self) -> None:
        tq = self._make()
        for i in range(5):
            tq.add_task(f"t{i}", f"p{i}")
        tasks, _ = tq.get_all_tasks_with_stats()
        legacy = tq.get_all_tasks()
        self.assertEqual([t.task_id for t in tasks], [t.task_id for t in legacy])

    def test_matches_legacy_get_task_count(self) -> None:
        tq = self._make()
        tq.add_task("t1", "p1")
        tq.add_task("t2", "p2")
        tq.add_task("t3", "p3")
        tq.complete_task("t1", {"feedback": "ok"})
        _, stats = tq.get_all_tasks_with_stats()
        legacy = tq.get_task_count()
        self.assertEqual(stats, legacy)

    def test_status_breakdown(self) -> None:
        tq = self._make()
        tq.add_task("t1", "p1")
        tq.add_task("t2", "p2")
        tq.add_task("t3", "p3")
        tq.complete_task("t1", {"feedback": "ok"})

        _, stats = tq.get_all_tasks_with_stats()
        self.assertEqual(stats["total"], 3)
        self.assertEqual(stats["completed"], 1)
        self.assertEqual(stats["active"], 1)
        self.assertEqual(stats["pending"], 1)

    def test_returns_list_copy_not_internal_view(self) -> None:
        tq = self._make()
        tq.add_task("t1", "p1")
        tasks_a, _ = tq.get_all_tasks_with_stats()
        tasks_b, _ = tq.get_all_tasks_with_stats()
        self.assertIsNot(tasks_a, tasks_b, "每次调用必须返回独立 list")
        tasks_a.clear()
        # 清空返回的 list 不应影响内部状态
        tasks_c, _ = tq.get_all_tasks_with_stats()
        self.assertEqual(len(tasks_c), 1)

    def test_returns_stats_dict_copy(self) -> None:
        tq = self._make()
        tq.add_task("t1", "p1")
        _, stats_a = tq.get_all_tasks_with_stats()
        _, stats_b = tq.get_all_tasks_with_stats()
        self.assertIsNot(stats_a, stats_b, "每次调用必须返回独立 dict")
        stats_a["total"] = 999
        _, stats_c = tq.get_all_tasks_with_stats()
        self.assertEqual(stats_c["total"], 1)


# ---------------------------------------------------------------------------
# 3. 原子快照不变量（与 writer 并发也保持一致）
# ---------------------------------------------------------------------------


class TestAtomicSnapshotInvariant(_TaskQueueFixture):
    """list 长度必须与 stats['total'] 始终一致，即使并发 writer 在跑。"""

    def test_invariant_under_concurrent_writers(self) -> None:
        tq = self._make(max_tasks=200)
        stop = threading.Event()

        def writer(prefix: str) -> None:
            i = 0
            while not stop.is_set():
                tq.add_task(f"{prefix}{i}", f"p{i}")
                if i > 0 and i % 5 == 0:
                    tq.remove_task(f"{prefix}{i - 5}")
                i += 1
                time.sleep(0.0005)

        writers = [
            threading.Thread(target=writer, args=(f"w{idx}_",), daemon=True)
            for idx in range(2)
        ]
        for t in writers:
            t.start()

        violations: list[tuple[int, int]] = []
        try:
            for _ in range(500):
                tasks, stats = tq.get_all_tasks_with_stats()
                if len(tasks) != stats["total"]:
                    violations.append((len(tasks), stats["total"]))
                # status counts 之和 + 其它状态 == 0 时 == total
                breakdown = stats["pending"] + stats["active"] + stats["completed"]
                if breakdown != stats["total"]:
                    violations.append((breakdown, stats["total"]))
        finally:
            stop.set()
            for t in writers:
                t.join(timeout=2.0)

        self.assertEqual(
            violations,
            [],
            f"原子快照不应出现 list/stats skew，发现 {len(violations)} 例",
        )


# ---------------------------------------------------------------------------
# 4. 源码契约
# ---------------------------------------------------------------------------


class TestSourceContract(unittest.TestCase):
    """源码层面验证：合并锁 + 路由层切换。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.task_queue_src = TASK_QUEUE_PY.read_text(encoding="utf-8")
        cls.task_route_src = TASK_ROUTE_PY.read_text(encoding="utf-8")

    def test_method_body_uses_single_read_lock(self) -> None:
        """方法体应当只 enter 一次 ``self._lock.read_lock``。"""
        method_src = inspect.getsource(TaskQueue.get_all_tasks_with_stats)
        # 去掉 docstring 后再统计
        body = re.sub(r'"""(.*?)"""', "", method_src, count=1, flags=re.DOTALL)
        read_lock_count = len(re.findall(r"self\._lock\.read_lock\(\)", body))
        self.assertEqual(
            read_lock_count,
            1,
            "get_all_tasks_with_stats 必须在单次 read_lock 临界区内完成",
        )

    def test_method_does_not_acquire_write_lock(self) -> None:
        method_src = inspect.getsource(TaskQueue.get_all_tasks_with_stats)
        self.assertNotIn(
            "write_lock",
            method_src,
            "纯读路径不能拿写锁，否则会阻塞读读并发",
        )

    def test_route_layer_calls_new_api(self) -> None:
        """``web_ui_routes/task.py::get_tasks`` 路由必须用合并 API。"""
        self.assertIn(
            "get_all_tasks_with_stats(",
            self.task_route_src,
            "/api/tasks 路由应切换到 get_all_tasks_with_stats",
        )

    def test_route_layer_no_longer_calls_legacy_pair_in_get_tasks(self) -> None:
        """``get_tasks`` 函数体内不再串行调用 get_all_tasks + get_task_count。"""
        match = re.search(
            r"def get_tasks\(\)[\s\S]*?return jsonify\([\s\S]*?\)",
            self.task_route_src,
        )
        self.assertIsNotNone(match, "无法定位 get_tasks 函数体")
        assert match is not None  # type: narrowing for mypy
        body = match.group(0)
        self.assertNotIn(
            "task_queue.get_all_tasks()",
            body,
            "get_tasks 不应再单独调用 get_all_tasks()",
        )
        self.assertNotIn(
            "task_queue.get_task_count()",
            body,
            "get_tasks 不应再单独调用 get_task_count()",
        )

    def test_legacy_apis_still_exposed(self) -> None:
        """``get_all_tasks`` / ``get_task_count`` 仍是公开方法（其它调用方依赖）。"""
        tq = TaskQueue(max_tasks=4)
        try:
            self.assertTrue(callable(tq.get_all_tasks))
            self.assertTrue(callable(tq.get_task_count))
        finally:
            tq.stop_cleanup()


# ---------------------------------------------------------------------------
# 5. 文档契约
# ---------------------------------------------------------------------------


class TestDocstringContract(unittest.TestCase):
    """docstring 必须解释 R23.4 的优化动机。"""

    def test_method_doc_mentions_r23_4(self) -> None:
        doc = TaskQueue.get_all_tasks_with_stats.__doc__ or ""
        self.assertIn("R23.4", doc, "docstring 必须显式标记 R23.4")

    def test_method_doc_mentions_single_read_lock(self) -> None:
        doc = TaskQueue.get_all_tasks_with_stats.__doc__ or ""
        self.assertRegex(
            doc,
            r"单次.*read_lock|read_lock.*合并|临界区",
            "docstring 必须解释「合并到单次 read_lock」",
        )

    def test_method_doc_mentions_returns_shape(self) -> None:
        doc = TaskQueue.get_all_tasks_with_stats.__doc__ or ""
        self.assertIn("tasks", doc)
        self.assertIn("stats", doc)


if __name__ == "__main__":
    unittest.main()
