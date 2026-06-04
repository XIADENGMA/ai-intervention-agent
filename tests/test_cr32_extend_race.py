"""cr32 §3.1 fix [medium]：``extend_deadline`` 并发竞态回归。

背景
----
CR#32 §3.1 指出 ``Task.extend_deadline`` 的 ``read extends_used → check →
write extends_used+1`` 不在锁内，HTTP 路由直接调用会让两个并发请求同时
通过 ``< max_extends`` 检查，最终 ``auto_resubmit_timeout`` 累加两次但
``extends_used`` 只 +1。修复方案是新增 ``TaskQueue.extend_task_deadline``
facade，在 ``self._lock`` 写锁内串行化整个读改写。

本测试套件锁三件事：

1. **facade 存在且语义正确**（单线程也对）。
2. **并发竞态被消除**：10 个线程同时各调 1 次 extend，最终
   ``extends_used <= max_extends``，且 ``auto_resubmit_timeout`` 累加值
   严格等于 ``base + extends_used * seconds``（不是 10 * seconds）。
3. **route handler 走 facade 而不是直接 ``task.extend_deadline``**：把
   route 源码 grep 一下，确认它调用了 facade 名字。这一步是 anti-regression
   —— 防止有人后续 "为了减少一次方法调用" 把 facade 拆掉直接走 task 方法。

边界
----
- 完成态 / disabled 态 / 超出范围 / 上限已达 4 种 reject 路径必须保持
  和 ``Task.extend_deadline`` 一致的 ``error_code`` 字符串（不重写）。
- facade 返回的 ``extends_used_after`` / ``auto_resubmit_timeout_after``
  必须反映**当前** task 状态（无论 success/failure）—— 让前端能立即同步
  按钮的 disabled 状态而不必再发一次 GET。
"""

from __future__ import annotations

import re
import threading
import unittest
from pathlib import Path

from ai_intervention_agent.task_queue import TaskQueue

REPO_ROOT = Path(__file__).resolve().parent.parent
ROUTE_FILE = REPO_ROOT / "src" / "ai_intervention_agent" / "web_ui_routes" / "task.py"


# ---------------------------------------------------------------------------
# 1. facade 存在 + 单线程语义
# ---------------------------------------------------------------------------


class TestFacadeSingleThreadedSemantics(unittest.TestCase):
    def setUp(self) -> None:
        self.q = TaskQueue()
        # 加一个 base timeout=120 的任务（保证 ``[10, 300]`` 内可扩展）
        ok = self.q.add_task(
            task_id="t-base",
            prompt="x",
            auto_resubmit_timeout=120,
        )
        self.assertTrue(ok)

    def test_facade_method_exists(self) -> None:
        self.assertTrue(
            hasattr(self.q, "extend_task_deadline"),
            "TaskQueue 必须暴露 extend_task_deadline facade",
        )
        self.assertTrue(
            callable(self.q.extend_task_deadline),
            "extend_task_deadline 必须可调用",
        )

    def test_success_returns_full_tuple(self) -> None:
        success, error_code, extends_used, timeout_after = self.q.extend_task_deadline(
            "t-base", 60
        )
        self.assertTrue(success)
        self.assertIsNone(error_code)
        self.assertEqual(extends_used, 1)
        self.assertEqual(timeout_after, 180)  # 120 + 60

    def test_unknown_task_returns_task_not_found(self) -> None:
        success, error_code, extends_used, timeout_after = self.q.extend_task_deadline(
            "no-such-task", 60
        )
        self.assertFalse(success)
        self.assertEqual(error_code, "task_not_found")
        self.assertEqual(extends_used, 0)
        self.assertEqual(timeout_after, 0)

    def test_invalid_seconds_returns_invalid(self) -> None:
        success, error_code, extends_used, timeout_after = self.q.extend_task_deadline(
            "t-base",
            5,  # below min_seconds=10
        )
        self.assertFalse(success)
        self.assertEqual(error_code, "invalid_seconds")
        # 状态字段反映**当前** task（未变）
        self.assertEqual(extends_used, 0)
        self.assertEqual(timeout_after, 120)

    def test_limit_reached_returns_limit_error(self) -> None:
        # max_extends=2，第三次必须返回 extends_limit_reached
        for _ in range(2):
            success, _, _, _ = self.q.extend_task_deadline("t-base", 60, max_extends=2)
            self.assertTrue(success)
        success, error_code, extends_used, timeout_after = self.q.extend_task_deadline(
            "t-base", 60, max_extends=2
        )
        self.assertFalse(success)
        self.assertEqual(error_code, "extends_limit_reached")
        self.assertEqual(extends_used, 2)
        # timeout 没变（上限拦截在 +=之前）
        self.assertEqual(timeout_after, 240)

    def test_auto_resubmit_disabled_returns_disabled_error(self) -> None:
        # auto_resubmit_timeout = 0 表示禁用
        ok = self.q.add_task(
            task_id="t-disabled",
            prompt="x",
            auto_resubmit_timeout=0,
        )
        self.assertTrue(ok)
        success, error_code, _, _ = self.q.extend_task_deadline("t-disabled", 60)
        self.assertFalse(success)
        self.assertEqual(error_code, "auto_resubmit_disabled")

    def test_completed_task_returns_completed_error(self) -> None:
        self.q.complete_task("t-base", {"feedback": "done"})
        success, error_code, _, _ = self.q.extend_task_deadline("t-base", 60)
        self.assertFalse(success)
        self.assertEqual(error_code, "task_completed")


# ---------------------------------------------------------------------------
# 2. 并发竞态：facade 保证读改写串行
# ---------------------------------------------------------------------------


class TestExtendDeadlineRaceEliminated(unittest.TestCase):
    """cr32 §3.1 中描述的核心 race：10 线程同时 extend 1 个 task，
    最终 ``extends_used <= max_extends`` 而 ``timeout`` 累计值严格等于
    ``base + extends_used * seconds`` 而**不是** ``base + N_THREADS * seconds``。

    没有 facade 时（直接调用 ``task.extend_deadline``）会观察到：
    - extends_used = max_extends = 3
    - timeout = base + 3 * 60 = 300  ✗ wrong baseline
    - 但实际上 ``auto_resubmit_timeout += seconds`` 被执行了多于 3 次
      （比如 5 次或 7 次，取决于线程交错），timeout = base + 5*60 / 7*60。

    有 facade 时严格：extends_used = N_SUCCESS, timeout = base + N_SUCCESS * 60。
    """

    N_THREADS = 10
    MAX_EXTENDS = 3
    SECONDS_PER_EXTEND = 60
    BASE_TIMEOUT = 120

    def setUp(self) -> None:
        self.q = TaskQueue()
        ok = self.q.add_task(
            task_id="t-race",
            prompt="x",
            auto_resubmit_timeout=self.BASE_TIMEOUT,
        )
        self.assertTrue(ok)

    def test_concurrent_extends_respect_max_extends(self) -> None:
        results: list[tuple[bool, str | None, int, int]] = []
        results_lock = threading.Lock()
        barrier = threading.Barrier(self.N_THREADS)

        def worker() -> None:
            barrier.wait()  # 让所有线程尽可能同时进入 facade
            r = self.q.extend_task_deadline(
                "t-race",
                self.SECONDS_PER_EXTEND,
                max_extends=self.MAX_EXTENDS,
                min_seconds=10,
                max_seconds=300,
            )
            with results_lock:
                results.append(r)

        threads = [threading.Thread(target=worker) for _ in range(self.N_THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        for t in threads:
            self.assertFalse(t.is_alive(), "所有 worker 必须在 10s 内完成")

        successes = [r for r in results if r[0]]
        failures = [r for r in results if not r[0]]

        self.assertEqual(
            len(results),
            self.N_THREADS,
            "每个线程都必须有结果",
        )
        self.assertEqual(
            len(successes),
            self.MAX_EXTENDS,
            f"成功次数必须 = max_extends({self.MAX_EXTENDS})，实际 {len(successes)}",
        )
        self.assertEqual(
            len(failures),
            self.N_THREADS - self.MAX_EXTENDS,
            "剩余必须全部失败（extends_limit_reached）",
        )
        for f in failures:
            self.assertEqual(
                f[1],
                "extends_limit_reached",
                f"失败 reason 必须是 extends_limit_reached，实际 {f[1]}",
            )

        # 关键 invariant：timeout 累加值严格等于 base + N_SUCCESS * seconds
        task = self.q.get_task("t-race")
        self.assertIsNotNone(task)
        # ``assert`` 给 ty 静态类型检查器明确收紧 ``Task | None`` → ``Task``，
        # 避免下面三个字段访问被识别为 None.attr error
        assert task is not None
        expected_timeout = (
            self.BASE_TIMEOUT + self.MAX_EXTENDS * self.SECONDS_PER_EXTEND
        )
        self.assertEqual(
            task.auto_resubmit_timeout,
            expected_timeout,
            f"timeout 累加必须严格 = base+{self.MAX_EXTENDS}*sec="
            f"{expected_timeout}，实际 {task.auto_resubmit_timeout}。"
            "如果实际 > 期望，说明 race 未被锁修复（有些线程通过了 < check 但又 += 了）。",
        )
        self.assertEqual(
            task.extends_used,
            self.MAX_EXTENDS,
            f"extends_used 必须严格 = {self.MAX_EXTENDS}",
        )


# ---------------------------------------------------------------------------
# 3. route handler 走 facade（anti-regression）
# ---------------------------------------------------------------------------


class TestRouteUsesQueueFacade(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.route_src = ROUTE_FILE.read_text(encoding="utf-8")

    def test_route_calls_task_queue_facade(self) -> None:
        # ``task_queue.extend_task_deadline(`` 应该至少出现一次
        self.assertRegex(
            self.route_src,
            r"task_queue\.extend_task_deadline\s*\(",
            "extend_task_deadline 路由必须调用 task_queue.extend_task_deadline facade。"
            "如果你看到这条 assert 失败，请阅读 cr32 §3.1 — 不要把锁绕过去。",
        )

    def test_route_does_not_call_task_extend_deadline_directly(self) -> None:
        """防止有人 "为了少一次方法调用" 把 facade 拆掉直接走 task.extend_deadline。

        允许的写法是 ``task_queue.extend_task_deadline(...)``（在锁内）。
        禁止的写法是 ``task.extend_deadline(...)``（锁外）。这条 invariant
        让违规改动立刻被这个测试拦下。
        """
        # 把"task_queue.extend_task_deadline" 出现的位置先 mask 掉，避免它
        # 误中后面的 task.extend_deadline 全词匹配
        masked = re.sub(
            r"task_queue\.extend_task_deadline\s*\([^)]*\)",
            "__FACADE_CALL__",
            self.route_src,
            flags=re.DOTALL,
        )
        # 现在 masked 里如果还出现 task.extend_deadline(，说明真的有锁外直调
        offenders = re.findall(r"\btask\.extend_deadline\s*\(", masked)
        self.assertEqual(
            offenders,
            [],
            f"web_ui_routes/task.py 不允许直接调用 task.extend_deadline()。"
            f"发现 {len(offenders)} 处违规。请走 task_queue.extend_task_deadline 走锁。",
        )


if __name__ == "__main__":
    unittest.main()
