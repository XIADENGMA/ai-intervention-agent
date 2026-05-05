"""
``TaskQueue.cleanup_completed_tasks_throttled`` 节流行为单元测试（R20.5）

背景
----
``GET /api/tasks`` 与 ``GET /api/tasks/<task_id>`` 历史上在每次请求都调用未
节流的 ``cleanup_completed_tasks(age_seconds=10)``。配合前端 2 s 轮询 + 后台
清理线程的 5 s 节奏，hot-path 上的 cleanup 调用频率被放大到后台节奏的
~5–10 倍。每次 cleanup 都要：

1. 加 ``self._lock``（与 ``add_task`` / ``complete_task`` / ``get_all_tasks``
   共用的粗粒度锁）；
2. ``datetime.now(UTC)`` syscall + tz 处理；
3. 遍历 ``self._tasks`` (O(n))。

R20.5 引入 ``cleanup_completed_tasks_throttled`` 把 hot-path 真实 cleanup 频率
封顶到 ``1 / throttle_seconds``，并把所有路由从 unthrottled 切到 throttled。

本文件锁住以下不变量
--------------------
1. ``cleanup_completed_tasks_throttled(throttle_seconds=N)`` 在 N 内连续调用
   只真实执行 1 次；
2. 节流 fast-path 不接触 ``self._tasks``（不影响并发 ``add_task`` /
   ``complete_task`` 的吞吐）；
3. ``throttle_seconds=0`` 退化为未节流行为（每次都跑）；
4. 节流后续调用过期窗口后能再次执行；
5. ``time.monotonic`` 单调时钟用于节流判断（不受系统时间漂移影响）；
6. ``GET /api/tasks`` 与 ``GET /api/tasks/<task_id>`` 路由源码使用 throttled
   版本（不允许回退到 unthrottled）；
7. 多线程并发命中节流 fast-path 时只有一个线程进入 slow-path（thundering herd
   防御）。
"""

from __future__ import annotations

import re
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from task_queue import TaskQueue, TaskStatus

REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_UI_TASK_ROUTE = REPO_ROOT / "web_ui_routes" / "task.py"


class TestCleanupThrottle(unittest.TestCase):
    def setUp(self) -> None:
        self.queue = TaskQueue(max_tasks=10)
        self.addCleanup(self.queue.stop_cleanup)

    def _add_completed_task(self, task_id: str, completed_seconds_ago: float) -> None:
        """构造一个 status=COMPLETED 且 completed_at 已过期的任务。"""
        from datetime import UTC, datetime, timedelta

        added = self.queue.add_task(task_id=task_id, prompt=f"test-{task_id}")
        self.assertTrue(added)
        # 直接拿任务对象写状态（绕过 complete_task 自带的延迟删除回调链）
        with self.queue._lock:
            task = self.queue._tasks[task_id]
            task.status = TaskStatus.COMPLETED
            task.completed_at = datetime.now(UTC) - timedelta(
                seconds=completed_seconds_ago
            )

    def test_throttled_runs_once_within_window(self) -> None:
        """节流窗口内连续调用只真实清理 1 次。"""
        # 准备：1 个完成 30s 的任务（age_seconds=10 应清理）
        self._add_completed_task("t1", completed_seconds_ago=30)

        # 第 1 次：节流时间戳为 -inf，必触发 → 任务被清理
        first = self.queue.cleanup_completed_tasks_throttled(
            age_seconds=10, throttle_seconds=10.0
        )
        self.assertEqual(first, 1)

        # 再准备一个完成的任务
        self._add_completed_task("t2", completed_seconds_ago=30)

        # 第 2 次：还在 10s 节流窗口内 → 节流命中，返回 0
        second = self.queue.cleanup_completed_tasks_throttled(
            age_seconds=10, throttle_seconds=10.0
        )
        self.assertEqual(
            second,
            0,
            "节流窗口内的二次调用必须返回 0（fast path），即使有可清理任务",
        )

        # t2 仍在内存中，证明节流真的阻止了 cleanup
        with self.queue._lock:
            self.assertIn("t2", self.queue._tasks)

    def test_throttled_runs_again_after_window(self) -> None:
        """节流窗口过期后再次调用必须真实执行。"""
        # 第 1 次跑掉初始 -inf 状态
        self.queue.cleanup_completed_tasks_throttled(throttle_seconds=10.0)

        # 准备 1 个待清理任务
        self._add_completed_task("t3", completed_seconds_ago=30)

        # mock monotonic 跳过节流窗口
        original_monotonic = time.monotonic
        offset = [0.0]

        def fake_monotonic() -> float:
            return original_monotonic() + offset[0]

        with patch("task_queue.time.monotonic", side_effect=fake_monotonic):
            # 立刻调用：在节流窗口内
            zero = self.queue.cleanup_completed_tasks_throttled(throttle_seconds=10.0)
            self.assertEqual(zero, 0)

            # 时间快进 11s（超过 10s 窗口）
            offset[0] = 11.0
            after = self.queue.cleanup_completed_tasks_throttled(throttle_seconds=10.0)
            self.assertEqual(after, 1, "节流窗口过期后必须真实清理")

    def test_throttle_zero_disables_throttle(self) -> None:
        """``throttle_seconds=0`` 退化为未节流行为（每次都跑）。"""
        # 在 setUp 后立即调用：第一次不在节流内（init 是 -inf）
        self.queue.cleanup_completed_tasks_throttled(throttle_seconds=0.0)

        self._add_completed_task("t4", completed_seconds_ago=30)
        again = self.queue.cleanup_completed_tasks_throttled(throttle_seconds=0.0)
        self.assertEqual(again, 1, "throttle_seconds=0 必须每次都真实执行")

    def test_fast_path_does_not_touch_main_lock(self) -> None:
        """节流 fast-path 不应持有 self._lock —— 否则与 add/complete 路径互锁。"""
        # 跑一次让节流时间戳进入 throttle 窗口
        self.queue.cleanup_completed_tasks_throttled(throttle_seconds=60.0)

        # 持有 self._lock 模拟 add_task 长时操作
        with self.queue._lock:
            # 在另一线程跑 throttled cleanup（理论上应立即返回 0，不被阻塞）
            result_holder: dict[str, int | None] = {"value": None}
            done = threading.Event()

            def hit_fast_path() -> None:
                result_holder["value"] = self.queue.cleanup_completed_tasks_throttled(
                    throttle_seconds=60.0
                )
                done.set()

            t = threading.Thread(target=hit_fast_path)
            t.start()
            # 100 ms 内必须完成（fast path 不持 main lock）
            self.assertTrue(
                done.wait(timeout=1.0),
                "fast-path 节流命中时不应被 self._lock 阻塞",
            )
            t.join()
            self.assertEqual(result_holder["value"], 0)

    def test_uses_monotonic_clock_not_wall_clock(self) -> None:
        """节流必须使用 ``time.monotonic`` —— 系统时间被 NTP / 用户调整后仍正常。"""
        # 跑一次进入节流窗口
        self.queue.cleanup_completed_tasks_throttled(throttle_seconds=60.0)

        self._add_completed_task("t5", completed_seconds_ago=30)

        # 模拟系统时间倒退 1 小时（NTP 突然往回跳的极端场景）
        original_time = time.time
        with patch("task_queue.time.time", side_effect=lambda: original_time() - 3600):
            # 节流仍然命中，不会因 wall clock 倒退而出现"负 elapsed"
            result = self.queue.cleanup_completed_tasks_throttled(throttle_seconds=60.0)
            self.assertEqual(
                result, 0, "wall clock 倒退后节流仍必须命中（依赖 monotonic）"
            )

    def test_concurrent_callers_only_one_runs(self) -> None:
        """多线程同时命中过期节流窗口时，只有一个线程进入 slow-path。

        防御 thundering-herd：多个 client 同时拿到 stale 节流戳并 race 进 slow
        path 会触发 N 次未节流 cleanup，回到 R20.5 修复前的反模式。
        """
        # 让节流时间戳进入 fresh 窗口（防止 -inf 直接通过）
        self.queue.cleanup_completed_tasks_throttled(throttle_seconds=60.0)

        # 准备 5 个待清理任务（每次 cleanup 都会清理掉所有 5 个）
        for i in range(5):
            self._add_completed_task(f"c{i}", completed_seconds_ago=30)

        # mock 节流窗口立即过期
        original_monotonic = time.monotonic
        offset = [0.0]

        def fake_monotonic() -> float:
            return original_monotonic() + offset[0]

        # 让所有线程看到 elapsed >= throttle 的 monotonic
        offset[0] = 100.0

        # 计数 slow-path 进入次数：spy cleanup_completed_tasks
        call_count = [0]
        original_cleanup = self.queue.cleanup_completed_tasks

        def spy_cleanup(*args, **kwargs):
            call_count[0] += 1
            return original_cleanup(*args, **kwargs)

        with (
            patch("task_queue.time.monotonic", side_effect=fake_monotonic),
            patch.object(
                self.queue, "cleanup_completed_tasks", side_effect=spy_cleanup
            ),
        ):
            barrier = threading.Barrier(8)

            def worker() -> None:
                barrier.wait()
                self.queue.cleanup_completed_tasks_throttled(throttle_seconds=60.0)

            threads = [threading.Thread(target=worker) for _ in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        self.assertEqual(
            call_count[0],
            1,
            f"8 个并发线程同时命中过期节流时只能有 1 个进入 slow-path，"
            f"实际进入了 {call_count[0]} 次（thundering herd 防御失效）",
        )


class TestRouteSourceUsesThrottled(unittest.TestCase):
    """源码不变量：API 路由不允许回退到未节流的 cleanup_completed_tasks。"""

    def test_get_tasks_route_uses_throttled(self) -> None:
        text = WEB_UI_TASK_ROUTE.read_text(encoding="utf-8")
        # 用 ace-grep 风格：找 GET /api/tasks 路由块内的 cleanup 调用
        get_tasks_match = re.search(
            r'@self\.app\.route\("/api/tasks", methods=\["GET"\]\).*?def get_tasks.*?'
            r"(?=@self\.app\.route|\Z)",
            text,
            re.DOTALL,
        )
        self.assertIsNotNone(get_tasks_match, "未能定位 GET /api/tasks 路由块")
        assert get_tasks_match is not None
        block = get_tasks_match.group(0)

        # block 内只能出现 throttled 版本，不允许出现未节流的 cleanup_completed_tasks(
        self.assertNotRegex(
            block,
            r"\bcleanup_completed_tasks\s*\(",
            "GET /api/tasks 不允许调用未节流的 cleanup_completed_tasks——必须用 "
            "cleanup_completed_tasks_throttled。回退到 hot-path unthrottled "
            "会撤销 R20.5 的性能优化，恢复 ~5-10x 冗余 cleanup 调用。",
        )
        self.assertIn(
            "cleanup_completed_tasks_throttled",
            block,
            "GET /api/tasks 必须调用 cleanup_completed_tasks_throttled",
        )

    def test_get_task_detail_route_uses_throttled(self) -> None:
        text = WEB_UI_TASK_ROUTE.read_text(encoding="utf-8")
        get_task_match = re.search(
            r'@self\.app\.route\("/api/tasks/<task_id>", methods=\["GET"\]\).*?'
            r"def get_task.*?(?=@self\.app\.route|\Z)",
            text,
            re.DOTALL,
        )
        self.assertIsNotNone(get_task_match, "未能定位 GET /api/tasks/<task_id> 路由块")
        assert get_task_match is not None
        block = get_task_match.group(0)

        self.assertNotRegex(
            block,
            r"\bcleanup_completed_tasks\s*\(",
            "GET /api/tasks/<task_id> 不允许调用未节流的 cleanup_completed_tasks",
        )
        self.assertIn(
            "cleanup_completed_tasks_throttled",
            block,
            "GET /api/tasks/<task_id> 必须调用 cleanup_completed_tasks_throttled",
        )


if __name__ == "__main__":
    unittest.main()
