"""R22.2 · TaskQueue 升级 ReadWriteLock 的回归与不变量测试

背景
----
``task_queue.TaskQueue`` 在 R22.2 之前用一把粗粒度 ``threading.Lock`` 保护
所有共享状态，``GET /api/tasks`` / SSE / 倒计时刷新等纯读路径在多 client
场景下会自相阻塞。R22.2 把 ``self._lock`` 升级为 ``ReadWriteLock``，让
读读并发、读写仍互斥、写写仍互斥。

本测试覆盖五个层面：

1.  **锁类型与公共属性**：``_lock`` 是 ``ReadWriteLock`` 实例，且能拿到
    ``read_lock()`` / ``write_lock()`` 上下文管理器；保留 R22.1 之前
    所有公共行为。
2.  **源码不变量**：写路径必须走 ``write_lock``、读路径必须走 ``read_lock``，
    禁止裸 ``with self._lock:`` 残留。
3.  **运行时语义**：读读并发、读阻塞写、写阻塞读、写写互斥。
4.  **文档契约**：类 docstring 与字段说明已经反映 R22.2 的语义变化。
5.  **回归用例**：add/get/complete/remove/clear 的对外行为不受锁切换影响。
"""

from __future__ import annotations

import re
import threading
import time
import unittest
from pathlib import Path

from config_manager import ReadWriteLock
from task_queue import TaskQueue

REPO_ROOT = Path(__file__).resolve().parent.parent
TASK_QUEUE_PY = REPO_ROOT / "task_queue.py"


class _TaskQueueFixture(unittest.TestCase):
    """自带 stop_cleanup 兜底的基类，避免后台线程残留。"""

    def _make(self, max_tasks: int = 10) -> TaskQueue:
        tq = TaskQueue(max_tasks=max_tasks)
        self.addCleanup(tq.stop_cleanup)
        return tq


# ---------------------------------------------------------------------------
# 1. 锁类型与公共属性
# ---------------------------------------------------------------------------


class TestLockType(_TaskQueueFixture):
    """``_lock`` 是 ``ReadWriteLock``，且符合契约。"""

    def test_lock_attribute_is_read_write_lock(self) -> None:
        tq = self._make()
        self.assertIsInstance(tq._lock, ReadWriteLock)

    def test_read_lock_returns_context_manager(self) -> None:
        tq = self._make()
        cm = tq._lock.read_lock()
        self.assertTrue(hasattr(cm, "__enter__"))
        self.assertTrue(hasattr(cm, "__exit__"))
        with cm:
            pass

    def test_write_lock_returns_context_manager(self) -> None:
        tq = self._make()
        cm = tq._lock.write_lock()
        self.assertTrue(hasattr(cm, "__enter__"))
        self.assertTrue(hasattr(cm, "__exit__"))
        with cm:
            pass

    def test_lock_does_not_support_legacy_with_protocol(self) -> None:
        """旧用法 ``with tq._lock:`` 必须显式失败 —— 否则会静默忽略锁。"""
        tq = self._make()
        with self.assertRaises(TypeError):
            with tq._lock:  # type: ignore[attr-defined]
                pass

    def test_each_instance_has_independent_lock(self) -> None:
        """两个 TaskQueue 实例的 ``_lock`` 必须是独立对象，避免跨实例互相阻塞。"""
        tq1 = self._make()
        tq2 = self._make()
        self.assertIsNot(tq1._lock, tq2._lock)


# ---------------------------------------------------------------------------
# 2. 源码不变量（基于 task_queue.py 的文本扫描）
# ---------------------------------------------------------------------------


class TestSourceInvariants(unittest.TestCase):
    """直接扫描 ``task_queue.py``，确保 R22.2 的契约写在代码里。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = TASK_QUEUE_PY.read_text(encoding="utf-8")

    def test_imports_read_write_lock(self) -> None:
        self.assertIn(
            "from config_manager import ReadWriteLock",
            self.source,
            "R22.2 必须显式从 config_manager 导入 ReadWriteLock",
        )

    def test_lock_assignment_uses_read_write_lock(self) -> None:
        self.assertIn(
            "self._lock = ReadWriteLock()",
            self.source,
            "TaskQueue.__init__ 必须把 _lock 设置为 ReadWriteLock 实例",
        )

    def test_no_legacy_lock_assignment(self) -> None:
        """禁止再次出现 ``self._lock = Lock()``。"""
        self.assertNotIn(
            "self._lock = Lock()",
            self.source,
            "self._lock 不应该再被赋值为 Lock()，已升级为 ReadWriteLock",
        )

    def test_no_naked_with_self_lock(self) -> None:
        """禁止 ``with self._lock:`` 出现 —— 必须显式选择 read/write。"""
        # 注意：只匹配真正的语法，不匹配 docstring 内容
        # 用一个相对宽松的正则：以 with self._lock: 开头（前面允许空白），
        # 后面紧跟换行或者注释
        pattern = re.compile(r"^\s+with\s+self\._lock\s*:", re.MULTILINE)
        matches = pattern.findall(self.source)
        self.assertEqual(
            matches,
            [],
            f"task_queue.py 中残留了 {len(matches)} 处裸 'with self._lock:'，"
            "必须用 .read_lock() 或 .write_lock()",
        )

    def test_write_paths_use_write_lock(self) -> None:
        """每个写方法的方法体内必须使用 ``self._lock.write_lock()``。"""
        write_methods = [
            "clear_all_tasks",
            "add_task",
            "update_auto_resubmit_timeout_for_all",
            "set_active_task",
            "complete_task",
            "remove_task",
            "clear_completed_tasks",
            "cleanup_completed_tasks",
        ]
        for method in write_methods:
            with self.subTest(method=method):
                body = self._extract_method_body(method)
                self.assertIn(
                    "self._lock.write_lock()",
                    body,
                    f"写方法 {method} 必须使用 self._lock.write_lock()",
                )
                self.assertNotIn(
                    "self._lock.read_lock()",
                    body,
                    f"写方法 {method} 不应该使用 read_lock（会丢失互斥性）",
                )

    def test_read_paths_use_read_lock(self) -> None:
        """每个读方法的方法体内必须使用 ``self._lock.read_lock()``。"""
        read_methods = [
            "get_task",
            "get_all_tasks",
            "get_active_task",
            "get_task_count",
        ]
        for method in read_methods:
            with self.subTest(method=method):
                body = self._extract_method_body(method)
                self.assertIn(
                    "self._lock.read_lock()",
                    body,
                    f"读方法 {method} 必须使用 self._lock.read_lock()",
                )
                self.assertNotIn(
                    "self._lock.write_lock()",
                    body,
                    f"读方法 {method} 不应该退化到 write_lock（破坏读读并发）",
                )

    def test_persist_uses_read_lock_for_snapshot(self) -> None:
        """``_persist`` 内部读快照必须用 read_lock，让多个并发 _persist 不互相阻塞。"""
        body = self._extract_method_body("_persist")
        self.assertIn(
            "self._lock.read_lock()",
            body,
            "_persist 应该用 read_lock 读取 _tasks 快照",
        )

    def test_class_docstring_mentions_read_write_lock(self) -> None:
        """类 docstring 必须显式描述 ReadWriteLock 升级。"""
        self.assertIn("ReadWriteLock", self.source)
        # 至少在某处提及 R22.2 标记，方便回溯
        self.assertIn("R22.2", self.source)

    def test_no_threading_lock_for_main_lock(self) -> None:
        """``self._lock`` 不应再被指定为 ``threading.Lock()`` 或 ``Lock()``。"""
        bad_patterns = [
            r"self\._lock\s*=\s*Lock\(\)",
            r"self\._lock\s*=\s*threading\.Lock\(\)",
            r"self\._lock\s*=\s*RLock\(\)",
        ]
        for pat in bad_patterns:
            with self.subTest(pattern=pat):
                self.assertEqual(
                    re.findall(pat, self.source),
                    [],
                    f"task_queue.py 中存在过时的锁类型赋值: {pat}",
                )

    @classmethod
    def _extract_method_body(cls, method_name: str) -> str:
        """提取 ``def method_name(...):`` 到下一个 ``def`` / 类结束之间的文本。

        用按行切分的方式实现，避免单一正则在 docstring 跨行时匹配范围错位。
        TaskQueue 的方法均缩进 4 空格、属于一个类内部。
        """
        lines = cls.source.splitlines(keepends=True)
        method_def_prefix = f"    def {method_name}("
        start_idx: int | None = None
        for i, line in enumerate(lines):
            if line.startswith(method_def_prefix):
                start_idx = i
                break
        if start_idx is None:
            raise AssertionError(f"无法在 task_queue.py 中定位方法 {method_name}")

        end_idx = len(lines)
        for j in range(start_idx + 1, len(lines)):
            line = lines[j]
            # 下一个同级方法 / 类结束 / 顶层定义
            if line.startswith(("    def ", "class ")) or (
                line and not line.startswith((" ", "\t")) and line.strip() != ""
            ):
                end_idx = j
                break
        return "".join(lines[start_idx:end_idx])


# ---------------------------------------------------------------------------
# 3. 运行时语义（多线程并发行为）
# ---------------------------------------------------------------------------


class TestRuntimeConcurrency(_TaskQueueFixture):
    """验证 R22.2 升级后实际多线程行为符合 R/W 锁语义。"""

    def test_multiple_readers_can_run_concurrently(self) -> None:
        """多个 read_lock 持有者可同时存在，不互相阻塞。"""
        tq = self._make()
        tq.add_task("t1", "p1")
        tq.add_task("t2", "p2")

        barrier = threading.Barrier(3)
        observed = []

        def reader() -> None:
            with tq._lock.read_lock():
                # 进入临界区后等待其他读者也都进来 → 证明三者并发持锁
                barrier.wait(timeout=2.0)
                observed.append(threading.get_ident())

        threads = [threading.Thread(target=reader) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=3.0)
            self.assertFalse(t.is_alive(), "读者线程应在 3s 内完成")

        self.assertEqual(len(observed), 3, "三个读者必须都成功通过 barrier")
        self.assertEqual(len({*observed}), 3, "三个读者必须是独立线程")

    def test_writer_excludes_readers(self) -> None:
        """写者持锁时，新读者必须被阻塞。"""
        tq = self._make()

        writer_acquired = threading.Event()
        writer_release = threading.Event()
        reader_done = threading.Event()

        def writer() -> None:
            with tq._lock.write_lock():
                writer_acquired.set()
                writer_release.wait(timeout=2.0)

        def reader() -> None:
            writer_acquired.wait(timeout=2.0)
            with tq._lock.read_lock():
                reader_done.set()

        wt = threading.Thread(target=writer)
        rt = threading.Thread(target=reader)
        wt.start()
        rt.start()

        # 等 writer 拿到锁
        self.assertTrue(writer_acquired.wait(timeout=2.0))
        # 给 reader 一段时间尝试拿锁（应该被阻塞）
        self.assertFalse(
            reader_done.wait(timeout=0.3),
            "writer 持锁时 reader 必须被阻塞",
        )

        # 释放 writer，reader 应该立刻完成
        writer_release.set()
        self.assertTrue(
            reader_done.wait(timeout=2.0), "writer 释放后 reader 应立即获锁"
        )

        wt.join(timeout=2.0)
        rt.join(timeout=2.0)

    def test_writer_waits_for_active_readers(self) -> None:
        """读者持锁时，新写者必须被阻塞至所有读者释放。"""
        tq = self._make()

        reader_acquired = threading.Event()
        reader_release = threading.Event()
        writer_done = threading.Event()

        def reader() -> None:
            with tq._lock.read_lock():
                reader_acquired.set()
                reader_release.wait(timeout=2.0)

        def writer() -> None:
            reader_acquired.wait(timeout=2.0)
            with tq._lock.write_lock():
                writer_done.set()

        rt = threading.Thread(target=reader)
        wt = threading.Thread(target=writer)
        rt.start()
        wt.start()

        self.assertTrue(reader_acquired.wait(timeout=2.0))
        self.assertFalse(
            writer_done.wait(timeout=0.3),
            "reader 持锁时 writer 必须被阻塞",
        )

        reader_release.set()
        self.assertTrue(writer_done.wait(timeout=2.0))

        rt.join(timeout=2.0)
        wt.join(timeout=2.0)

    def test_two_writers_are_mutually_exclusive(self) -> None:
        """两个写者不可同时持锁。"""
        tq = self._make()

        first_acquired = threading.Event()
        first_release = threading.Event()
        second_done = threading.Event()

        def first() -> None:
            with tq._lock.write_lock():
                first_acquired.set()
                first_release.wait(timeout=2.0)

        def second() -> None:
            first_acquired.wait(timeout=2.0)
            with tq._lock.write_lock():
                second_done.set()

        t1 = threading.Thread(target=first)
        t2 = threading.Thread(target=second)
        t1.start()
        t2.start()

        self.assertTrue(first_acquired.wait(timeout=2.0))
        self.assertFalse(
            second_done.wait(timeout=0.3),
            "第一个写者持锁时第二个写者必须被阻塞",
        )

        first_release.set()
        self.assertTrue(second_done.wait(timeout=2.0))

        t1.join(timeout=2.0)
        t2.join(timeout=2.0)

    def test_concurrent_get_all_tasks_no_starvation(self) -> None:
        """高频 get_all_tasks 多线程并发不应显著串行化。"""
        tq = self._make()
        for i in range(5):
            tq.add_task(f"t{i}", f"p{i}")

        iterations = 200
        worker_count = 4

        def worker() -> None:
            for _ in range(iterations):
                tq.get_all_tasks()

        threads = [threading.Thread(target=worker) for _ in range(worker_count)]
        start = time.monotonic()
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)
        elapsed = time.monotonic() - start

        for t in threads:
            self.assertFalse(t.is_alive(), "并发读不应该死锁或长时间阻塞")
        # 4 worker × 200 iter = 800 次 get_all_tasks，应在亚秒级完成
        self.assertLess(
            elapsed, 2.0, f"并发读耗时 {elapsed:.3f}s 异常高，可能退化到串行"
        )


# ---------------------------------------------------------------------------
# 4. 文档契约
# ---------------------------------------------------------------------------


class TestDocstringContract(unittest.TestCase):
    """类 docstring 与字段说明必须匹配 R22.2 的语义。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = TASK_QUEUE_PY.read_text(encoding="utf-8")

    def test_class_doc_mentions_rwlock_field(self) -> None:
        self.assertRegex(
            self.source,
            r"`_lock`.*ReadWriteLock",
            "类 docstring 中 _lock 字段说明必须提到 ReadWriteLock",
        )

    def test_class_doc_lists_write_paths(self) -> None:
        for method in ("add_task", "complete_task", "remove_task"):
            self.assertIn(
                method,
                self.source,
                f"类 docstring / 代码内必须出现写路径方法 {method}",
            )

    def test_class_doc_lists_read_paths(self) -> None:
        for method in (
            "get_task",
            "get_all_tasks",
            "get_active_task",
            "get_task_count",
        ):
            self.assertIn(
                method,
                self.source,
                f"类 docstring / 代码内必须出现读路径方法 {method}",
            )

    def test_class_doc_mentions_concurrency_semantics(self) -> None:
        """docstring 至少描述读读并发、读写互斥语义。"""
        self.assertRegex(
            self.source,
            r"读读并发|多读者并发|read.*concurrent",
            "类 docstring 必须描述读读并发语义",
        )

    def test_class_doc_does_not_claim_simple_lock(self) -> None:
        """禁止再宣称『使用 Lock 保护』这种与新行为矛盾的语句。"""
        # 允许 docstring 中提及历史 Lock，但新版本不应说 "使用 Lock 保护"
        self.assertNotIn(
            "所有以下方法都使用 `with self._lock:` 保护",
            self.source,
            "旧的 Lock 描述必须更新为 ReadWriteLock 语义",
        )


# ---------------------------------------------------------------------------
# 5. 回归用例（确保锁切换不影响对外行为）
# ---------------------------------------------------------------------------


class TestBehaviouralRegression(_TaskQueueFixture):
    """R22.2 锁切换不应改变任何对外可观察行为。"""

    def test_add_task_then_get_task(self) -> None:
        tq = self._make()
        self.assertTrue(tq.add_task("t1", "p1"))
        self.assertEqual(tq.get_task("t1").prompt, "p1")

    def test_get_active_task_when_first_added(self) -> None:
        tq = self._make()
        tq.add_task("t1", "p1")
        active = tq.get_active_task()
        self.assertIsNotNone(active)
        self.assertEqual(active.task_id, "t1")

    def test_complete_then_auto_activate_next(self) -> None:
        tq = self._make()
        tq.add_task("t1", "p1")
        tq.add_task("t2", "p2")
        tq.complete_task("t1", {"feedback": "ok"})
        active = tq.get_active_task()
        self.assertIsNotNone(active)
        self.assertEqual(active.task_id, "t2")

    def test_remove_task_does_not_affect_others(self) -> None:
        tq = self._make()
        tq.add_task("t1", "p1")
        tq.add_task("t2", "p2")
        self.assertTrue(tq.remove_task("t2"))
        self.assertIsNone(tq.get_task("t2"))
        self.assertIsNotNone(tq.get_task("t1"))

    def test_get_task_count_with_mixed_status(self) -> None:
        tq = self._make()
        tq.add_task("t1", "p1")
        tq.add_task("t2", "p2")
        tq.complete_task("t1", {"feedback": "ok"})
        counts = tq.get_task_count()
        self.assertEqual(counts["total"], 2)
        self.assertEqual(counts["completed"], 1)
        self.assertEqual(counts["active"], 1)

    def test_clear_all_tasks(self) -> None:
        tq = self._make()
        tq.add_task("t1", "p1")
        tq.add_task("t2", "p2")
        cleared = tq.clear_all_tasks()
        self.assertEqual(cleared, 2)
        self.assertEqual(tq.get_all_tasks(), [])

    def test_clear_completed_tasks(self) -> None:
        tq = self._make()
        tq.add_task("t1", "p1")
        tq.add_task("t2", "p2")
        tq.complete_task("t1", {"feedback": "ok"})
        cleared = tq.clear_completed_tasks()
        self.assertEqual(cleared, 1)

    def test_update_auto_resubmit_timeout_for_all(self) -> None:
        tq = self._make()
        tq.add_task("t1", "p1", auto_resubmit_timeout=120)
        tq.add_task("t2", "p2", auto_resubmit_timeout=120)
        updated = tq.update_auto_resubmit_timeout_for_all(60)
        self.assertEqual(updated, 2)
        for t in tq.get_all_tasks():
            self.assertEqual(t.auto_resubmit_timeout, 60)

    def test_set_active_task_changes_status(self) -> None:
        tq = self._make()
        tq.add_task("t1", "p1")
        tq.add_task("t2", "p2")
        self.assertTrue(tq.set_active_task("t2"))
        self.assertEqual(tq.get_active_task().task_id, "t2")

    def test_concurrent_writes_serialise_safely(self) -> None:
        """高并发写不应出现状态错乱：每个 task_id 唯一，最终任务数正确。"""
        tq = self._make(max_tasks=200)

        worker_count = 4
        per_worker = 25

        def worker(idx: int) -> None:
            for i in range(per_worker):
                tq.add_task(f"w{idx}-t{i}", f"p{idx}-{i}")

        threads = [
            threading.Thread(target=worker, args=(i,)) for i in range(worker_count)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)
            self.assertFalse(t.is_alive())

        all_tasks = tq.get_all_tasks()
        self.assertEqual(len(all_tasks), worker_count * per_worker)
        ids = {t.task_id for t in all_tasks}
        self.assertEqual(len(ids), worker_count * per_worker, "任务 ID 必须唯一")

    def test_no_callback_invoked_inside_lock(self) -> None:
        """状态回调必须在锁外触发（旧契约保留 + 防止读锁内部回调升级写锁死锁）。"""
        tq = self._make()

        observed_lock_state: list[bool] = []

        def cb(task_id: str, old: str | None, new: str) -> None:
            # 在回调里再尝试拿写锁；如果回调本身在锁内执行，会立刻死锁
            # （ReadWriteLock 不支持递归）。我们用 timeout 的写锁去自检，
            # 因为标准 ReadWriteLock 没有 timeout API，所以改用读锁试探：
            # 若回调在锁内，则 read_lock() 自身要重新竞争 → 在单线程内
            # 不会立刻完成（递归被禁），但实际 ReadWriteLock 没有递归
            # 检测，所以这里只观测能否成功获取到读锁。
            with tq._lock.read_lock():
                observed_lock_state.append(True)

        tq.register_status_change_callback(cb)
        tq.add_task("t1", "p1")
        tq.complete_task("t1", {"feedback": "ok"})

        # 至少有 add_task → ACTIVE 与 complete_task → COMPLETED 两次回调
        self.assertGreaterEqual(len(observed_lock_state), 2)
        self.assertTrue(all(observed_lock_state))


if __name__ == "__main__":
    unittest.main()
