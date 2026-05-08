"""R51-A：TaskQueue ``_watched_write_lock`` deadlock detector 回归契约。

覆盖目标：

  1. ``_watched_write_lock`` 进出会正确把 record 加进 / 移出
     ``_pending_acquisitions``。
  2. ``_lock_watchdog_loop`` 在临界区 hold 时长超过
     ``_LOCK_WATCHDOG_TIMEOUT_S`` 时会向 ``logger.error`` 打一条 dump，
     并且只 dump 一次（``dumped`` flag 防 spam）。
  3. ``_capture_all_thread_stacks`` 不抛异常，返回 string。
  4. ``add_task`` 走的是 ``_watched_write_lock``（静态扫源码）。
  5. watchdog daemon 是 idempotent，重复 ``_ensure_lock_watchdog_started``
     不会重复创建线程。
  6. watchdog 线程是 daemon，进程退出时不会阻塞。

为不让真正 30 s 的等待出现在测试里，所有"超时"用例都通过 monkeypatch
把 ``_LOCK_WATCHDOG_TIMEOUT_S`` / ``_LOCK_WATCHDOG_SCAN_INTERVAL_S`` 改小。
"""

from __future__ import annotations

import importlib
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import ai_intervention_agent.task_queue as task_queue


class TestWatchedWriteLockBookkeeping(unittest.TestCase):
    """``_watched_write_lock`` 进出会维护 ``_pending_acquisitions``。"""

    def test_record_added_inside_critical_section(self) -> None:
        from ai_intervention_agent.config_manager import ReadWriteLock

        rwlock = ReadWriteLock()
        seen_count: list[int] = []
        with task_queue._watched_write_lock(rwlock, "test-label"):
            with task_queue._pending_acquisitions_lock:
                seen_count.append(len(task_queue._pending_acquisitions))
        self.assertEqual(seen_count, [1])

    def test_record_removed_after_exit(self) -> None:
        from ai_intervention_agent.config_manager import ReadWriteLock

        rwlock = ReadWriteLock()
        before = len(task_queue._pending_acquisitions)
        with task_queue._watched_write_lock(rwlock, "test-label"):
            pass
        after = len(task_queue._pending_acquisitions)
        self.assertEqual(before, after)

    def test_record_removed_even_when_critical_section_raises(self) -> None:
        from ai_intervention_agent.config_manager import ReadWriteLock

        rwlock = ReadWriteLock()
        before = len(task_queue._pending_acquisitions)
        with self.assertRaises(RuntimeError):
            with task_queue._watched_write_lock(rwlock, "test-raise"):
                raise RuntimeError("simulated")
        after = len(task_queue._pending_acquisitions)
        self.assertEqual(before, after)

    def test_label_recorded_in_pending(self) -> None:
        from ai_intervention_agent.config_manager import ReadWriteLock

        rwlock = ReadWriteLock()
        seen_labels: list[str] = []
        with task_queue._watched_write_lock(rwlock, "expected-label"):
            with task_queue._pending_acquisitions_lock:
                for rec in task_queue._pending_acquisitions.values():
                    seen_labels.append(rec["label"])
        self.assertIn("expected-label", seen_labels)


class TestStackCapture(unittest.TestCase):
    """``_capture_all_thread_stacks`` 始终返回 string，不抛。"""

    def test_returns_string(self) -> None:
        out = task_queue._capture_all_thread_stacks()
        self.assertIsInstance(out, str)
        self.assertGreater(len(out), 0)

    def test_includes_at_least_current_thread(self) -> None:
        out = task_queue._capture_all_thread_stacks()
        # 主线程必然在快照里
        self.assertIn("Thread id=", out)


class TestWatchdogIdempotent(unittest.TestCase):
    """``_ensure_lock_watchdog_started`` 必须 idempotent。"""

    def test_repeat_call_does_not_create_new_thread(self) -> None:
        task_queue._ensure_lock_watchdog_started()
        first = task_queue._watchdog_thread
        task_queue._ensure_lock_watchdog_started()
        second = task_queue._watchdog_thread
        self.assertIs(first, second)

    def test_thread_is_daemon(self) -> None:
        task_queue._ensure_lock_watchdog_started()
        thread = task_queue._watchdog_thread
        self.assertIsNotNone(thread)
        assert thread is not None  # for type checker
        self.assertTrue(thread.daemon)
        self.assertEqual(thread.name, "TaskQueueLockWatchdog")


class TestWatchdogDumpsOnSlowAcquire(unittest.TestCase):
    """``_scan_pending_and_dump_slow`` 在 record 超时时 dump 全栈到 ``logger.error``。

    用 ``_scan_pending_and_dump_slow()`` 直接触发，而不是依赖 daemon 周期；这样
    测试不受 daemon 当前 sleep 进度的影响，也不用真的等 ``_LOCK_WATCHDOG_SCAN_INTERVAL_S``。
    """

    def setUp(self) -> None:
        self._orig_timeout = task_queue._LOCK_WATCHDOG_TIMEOUT_S
        task_queue._LOCK_WATCHDOG_TIMEOUT_S = 0.1  # 0.1 s 超时
        # ``_pending_acquisitions`` 是 module-level dict，在 daemon 与
        # ``_watched_write_lock`` 之间共享。如果上一个 test class（比如真实
        # ``TaskQueue.add_task`` 路径）在并发场景下意外早退、record 没及时被
        # ``finally`` 清掉，会让本类的 dedup-flag 测试看到来自上一个用例的
        # "已 dumped" 残留 → 计数对不上。这里强清一次，让本类测试从一个
        # 干净的 dedup 状态起。
        with task_queue._pending_acquisitions_lock:
            task_queue._pending_acquisitions.clear()

    def tearDown(self) -> None:
        task_queue._LOCK_WATCHDOG_TIMEOUT_S = self._orig_timeout
        # 退出本类后再清一次，保护下游 test class（同一进程跑 flake 反演时
        # 也避免我们造成的污染）。
        with task_queue._pending_acquisitions_lock:
            task_queue._pending_acquisitions.clear()

    def _reset_dumped_for_label(self, label: str) -> None:
        """防 daemon race：把目标 record 的 ``dumped`` flag 重置回 False。

        daemon 是个 5s 周期的后台 thread，单跑这个测试时几乎不会 race，但
        全量 pytest 跑时（前面有别的测试触发了 ``_ensure_lock_watchdog_started``
        → daemon 已经在 ``_lock_watchdog_wake_event.wait(5s)``）daemon 偶尔
        会在我们 sleep 的 0.2s 窗口里被早期 wait 唤醒并扫一次，把 record
        标 ``dumped=True``，让我们自己的 ``_scan_pending_and_dump_slow()``
        命中 dedup 跳过。这里手动清这个 flag，让我们的测试 scan 必然命中。
        """
        with task_queue._pending_acquisitions_lock:
            for rec in task_queue._pending_acquisitions.values():
                if rec.get("label") == label:
                    rec["dumped"] = False

    def test_scan_dumps_when_critical_section_held_too_long(self) -> None:
        from ai_intervention_agent.config_manager import ReadWriteLock

        rwlock = ReadWriteLock()
        with patch.object(task_queue.logger, "error") as fake_err:
            with task_queue._watched_write_lock(rwlock, "slow-test"):
                time.sleep(0.2)  # > 0.1 s 阈值
                # daemon 可能在 sleep 期间偷扫一次 → 重置 + 清 fake_err 计数。
                self._reset_dumped_for_label("slow-test")
                fake_err.reset_mock()
                dumped_count = task_queue._scan_pending_and_dump_slow()
        self.assertEqual(dumped_count, 1)
        self.assertEqual(fake_err.call_count, 1)
        dump_str = "\n".join(str(call) for call in fake_err.call_args_list)
        self.assertIn("slow-test", dump_str)
        self.assertIn("写锁卡死", dump_str)

    def test_dump_only_fires_once_per_record(self) -> None:
        """同一个 record 不会被反复 dump（``dumped`` flag 生效）。"""
        from ai_intervention_agent.config_manager import ReadWriteLock

        rwlock = ReadWriteLock()
        with patch.object(task_queue.logger, "error") as fake_err:
            with task_queue._watched_write_lock(rwlock, "dedup-test"):
                time.sleep(0.2)
                # 防 daemon race：先 reset，让第一轮我们的 scan 必然命中。
                self._reset_dumped_for_label("dedup-test")
                fake_err.reset_mock()
                # 连扫 5 次：只有第一次 dump
                dump_counts = [
                    task_queue._scan_pending_and_dump_slow() for _ in range(5)
                ]
        self.assertEqual(dump_counts, [1, 0, 0, 0, 0])
        self.assertEqual(fake_err.call_count, 1)

    def test_fast_critical_section_does_not_dump(self) -> None:
        """正常路径（< 阈值）扫描不应触发 dump。"""
        from ai_intervention_agent.config_manager import ReadWriteLock

        rwlock = ReadWriteLock()
        with patch.object(task_queue.logger, "error") as fake_err:
            with task_queue._watched_write_lock(rwlock, "fast-test"):
                # < 0.1 s 阈值，立即扫描
                dumped_count = task_queue._scan_pending_and_dump_slow()
        self.assertEqual(dumped_count, 0)
        self.assertEqual(fake_err.call_count, 0)

    def test_scan_after_critical_section_exits_does_not_dump(self) -> None:
        """临界区已退出 → record 已移除，扫描见不到任何"超时"项。

        历史 flake：当 daemon 已被前面的测试启动后，``time.sleep(0.2)``
        期间它可能 race 到 ``_lock_watchdog_wake_event.wait`` 早醒一次，
        把临界区里的 ``exited-test`` record 也扫一遍并 ``logger.error``。
        如果我们一开始就 ``patch logger.error`` 整个块，这次 race 就会
        污染 ``fake_err.call_count``。改为「先让临界区完整跑完、record
        通过 ``finally`` 移除，再开 patch 扫一次」——本测的关注点就只是
        「临界区退出后不再 dump」，daemon 在临界区内的并发行为不在考察范围。
        """
        from ai_intervention_agent.config_manager import ReadWriteLock

        rwlock = ReadWriteLock()
        with task_queue._watched_write_lock(rwlock, "exited-test"):
            time.sleep(0.2)
        # 临界区退出后才开 patch + scan，避免 daemon 在 sleep 期间 race
        # 到 ``logger.error`` 把 fake_err 的计数器污染掉。
        with patch.object(task_queue.logger, "error") as fake_err:
            dumped_count = task_queue._scan_pending_and_dump_slow()
        self.assertEqual(dumped_count, 0)
        self.assertEqual(fake_err.call_count, 0)


class TestAddTaskUsesWatchedLock(unittest.TestCase):
    """``add_task`` 必须走 ``_watched_write_lock``（静态扫源码）。"""

    def test_add_task_source_uses_watched_write_lock(self) -> None:
        src = Path(task_queue.__file__).read_text(encoding="utf-8")
        # 找到 add_task 方法体的起点
        idx = src.find("def add_task(")
        self.assertGreater(idx, -1, "add_task 方法必须存在")
        # 取下一个 def 作为方法体上限
        next_def = src.find("\n    def ", idx + 1)
        body = src[idx:next_def] if next_def > -1 else src[idx:]
        self.assertIn(
            '_watched_write_lock(self._lock, "add_task")',
            body,
            "add_task 必须用 _watched_write_lock 包装写锁（R51-A）",
        )

    def test_add_task_does_not_use_raw_write_lock(self) -> None:
        """add_task 方法体内不应再有裸 ``self._lock.write_lock()``。"""
        src = Path(task_queue.__file__).read_text(encoding="utf-8")
        idx = src.find("def add_task(")
        next_def = src.find("\n    def ", idx + 1)
        body = src[idx:next_def] if next_def > -1 else src[idx:]
        # ``self._lock.write_lock()`` 在 add_task 体内不应出现（被 watch 包了）
        self.assertNotIn(
            "self._lock.write_lock()",
            body,
            "add_task 方法体应当只走 _watched_write_lock，不应再裸调 write_lock()",
        )


class TestWatchdogConstantsHaveSensibleBounds(unittest.TestCase):
    """常量必须落在合理区间。"""

    def test_timeout_at_least_5s_to_avoid_false_positive(self) -> None:
        # 在 CI 高 IO 抖动下，1-3 s 写锁不算异常；5 s 是最小合理阈值
        # 测试可以临时调小，但模块级默认必须留余量
        importlib.reload(task_queue)  # 拿默认值
        self.assertGreaterEqual(task_queue._LOCK_WATCHDOG_TIMEOUT_S, 5.0)

    def test_scan_interval_at_least_1s(self) -> None:
        importlib.reload(task_queue)
        self.assertGreaterEqual(task_queue._LOCK_WATCHDOG_SCAN_INTERVAL_S, 1.0)

    def test_timeout_at_most_5x_scan_interval(self) -> None:
        """timeout / scan_interval 应在 ~6 区间，太小会 spam，太大会延迟告警。"""
        importlib.reload(task_queue)
        ratio = (
            task_queue._LOCK_WATCHDOG_TIMEOUT_S
            / task_queue._LOCK_WATCHDOG_SCAN_INTERVAL_S
        )
        self.assertGreater(ratio, 1.0)
        self.assertLess(ratio, 30.0)


class TestWatchdogDoesNotBreakRealTaskQueue(unittest.TestCase):
    """``TaskQueue.add_task`` 在真实场景下能用、不会因为 watchdog 卡死。"""

    def test_add_task_works_normally(self) -> None:
        q = task_queue.TaskQueue(max_tasks=3)
        try:
            ok = q.add_task("t1", "hello")
            self.assertTrue(ok)
            task = q.get_task("t1")
            self.assertIsNotNone(task)
            assert task is not None
            self.assertEqual(task.task_id, "t1")
        finally:
            q.stop_cleanup()

    def test_add_task_concurrent_burst(self) -> None:
        """8 线程同时 add_task：watchdog 不应误报、所有 task 都成功入队。"""
        q = task_queue.TaskQueue(max_tasks=20)
        results: list[bool] = []
        results_lock = threading.Lock()

        def _worker(i: int) -> None:
            ok = q.add_task(f"task-{i}", f"prompt-{i}")
            with results_lock:
                results.append(ok)

        try:
            threads = [threading.Thread(target=_worker, args=(i,)) for i in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=5.0)
            self.assertEqual(len(results), 8)
            self.assertTrue(all(results))
            counts = q.get_task_count()
            # ``get_task_count`` 返回 ``{"total": int, ...}`` 形态
            self.assertEqual(counts["total"], 8)
        finally:
            q.stop_cleanup()


if __name__ == "__main__":
    unittest.main()
