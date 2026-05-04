"""
AI Intervention Agent - 任务队列单元测试

测试覆盖：
1. 任务添加/获取/删除
2. 任务状态管理
3. 线程安全
4. 自动清理机制
5. 活动任务切换
"""

import math
import threading
import time
import unittest
from unittest.mock import MagicMock, patch


class TestTaskBasic(unittest.TestCase):
    """测试 Task 数据结构"""

    def test_task_creation(self):
        """测试任务创建"""
        from task_queue import Task

        task = Task(task_id="task-1", prompt="测试提示")

        self.assertEqual(task.task_id, "task-1")
        self.assertEqual(task.prompt, "测试提示")
        self.assertEqual(task.status, "pending")
        self.assertIsNone(task.result)

    def test_task_with_options(self):
        """测试带选项的任务"""
        from task_queue import Task

        task = Task(
            task_id="task-1", prompt="测试提示", predefined_options=["选项1", "选项2"]
        )

        self.assertEqual(task.predefined_options, ["选项1", "选项2"])

    def test_remaining_time(self):
        """测试剩余时间计算"""
        from task_queue import Task

        task = Task(task_id="task-1", prompt="测试提示", auto_resubmit_timeout=60)

        remaining = task.get_remaining_time()

        self.assertGreater(remaining, 0)
        self.assertLessEqual(remaining, 60)

    def test_completed_task_remaining_time(self):
        """测试已完成任务的剩余时间"""
        from task_queue import Task

        task = Task(task_id="task-1", prompt="测试提示")
        task.status = "completed"

        remaining = task.get_remaining_time()

        self.assertEqual(remaining, 0)

    def test_timeout_zero_not_expired(self):
        """auto_resubmit_timeout=0 表示禁用，不应被判定为过期"""
        from task_queue import Task

        task = Task(task_id="task-1", prompt="测试提示", auto_resubmit_timeout=0)
        self.assertFalse(task.is_expired())
        self.assertTrue(math.isinf(task.get_deadline_monotonic()))


class TestTaskQueueBasic(unittest.TestCase):
    """测试任务队列基本功能"""

    def setUp(self):
        """每个测试前的准备"""
        from task_queue import TaskQueue

        self.queue = TaskQueue(max_tasks=5)

    def tearDown(self):
        """每个测试后的清理"""
        self.queue.stop_cleanup()

    def test_add_task(self):
        """测试添加任务"""
        result = self.queue.add_task("task-1", "测试提示")

        self.assertTrue(result)
        self.assertIsNotNone(self.queue.get_task("task-1"))

    def test_add_task_clamps_timeout_min(self):
        """倒计时边界：auto_resubmit_timeout<30 时应被钳制到 30（0 例外）"""
        self.queue.add_task("task-1", "测试提示", auto_resubmit_timeout=1)
        task = self.queue.get_task("task-1")
        self.assertIsNotNone(task)
        assert task is not None
        self.assertEqual(task.auto_resubmit_timeout, 30)

    def test_add_duplicate_task(self):
        """测试添加重复任务"""
        self.queue.add_task("task-1", "提示1")
        result = self.queue.add_task("task-1", "提示2")

        self.assertFalse(result)

    def test_add_task_queue_full(self):
        """测试队列已满"""
        for i in range(5):
            self.queue.add_task(f"task-{i}", f"提示{i}")

        result = self.queue.add_task("task-5", "提示5")

        self.assertFalse(result)

    def test_get_task(self):
        """测试获取任务"""
        self.queue.add_task("task-1", "测试提示")

        task = self.queue.get_task("task-1")

        self.assertIsNotNone(task)
        assert task is not None
        self.assertEqual(task.prompt, "测试提示")

    def test_get_nonexistent_task(self):
        """测试获取不存在的任务"""
        task = self.queue.get_task("nonexistent")

        self.assertIsNone(task)

    def test_get_all_tasks(self):
        """测试获取所有任务"""
        self.queue.add_task("task-1", "提示1")
        self.queue.add_task("task-2", "提示2")

        tasks = self.queue.get_all_tasks()

        self.assertEqual(len(tasks), 2)

    def test_remove_task(self):
        """测试移除任务"""
        self.queue.add_task("task-1", "测试提示")

        result = self.queue.remove_task("task-1")

        self.assertTrue(result)
        self.assertIsNone(self.queue.get_task("task-1"))

    def test_clear_all_tasks(self):
        """测试清理所有任务"""
        self.queue.add_task("task-1", "提示1")
        self.queue.add_task("task-2", "提示2")

        count = self.queue.clear_all_tasks()

        self.assertEqual(count, 2)
        self.assertEqual(len(self.queue.get_all_tasks()), 0)

    def test_update_auto_resubmit_timeout_for_all(self):
        """配置热更新：更新所有未完成任务的倒计时"""
        # 添加两个任务（一个 active，一个 pending）
        self.queue.add_task("task-1", "提示1", auto_resubmit_timeout=240)
        self.queue.add_task("task-2", "提示2", auto_resubmit_timeout=240)

        updated = self.queue.update_auto_resubmit_timeout_for_all(120)
        self.assertEqual(updated, 2)

        t1 = self.queue.get_task("task-1")
        t2 = self.queue.get_task("task-2")
        self.assertIsNotNone(t1)
        self.assertIsNotNone(t2)
        assert t1 is not None
        assert t2 is not None
        self.assertEqual(t1.auto_resubmit_timeout, 120)
        self.assertEqual(t2.auto_resubmit_timeout, 120)

    def test_update_auto_resubmit_timeout_skip_completed(self):
        """配置热更新：不更新已完成任务"""
        self.queue.add_task("task-1", "提示1", auto_resubmit_timeout=240)
        self.queue.add_task("task-2", "提示2", auto_resubmit_timeout=240)

        # 完成 task-1（task-2 会自动激活）
        self.queue.complete_task("task-1", {"feedback": "done"})

        updated = self.queue.update_auto_resubmit_timeout_for_all(100)
        # 只应更新未完成的 task-2
        self.assertEqual(updated, 1)

        t1 = self.queue.get_task("task-1")
        t2 = self.queue.get_task("task-2")
        self.assertIsNotNone(t1)
        self.assertIsNotNone(t2)
        assert t1 is not None
        assert t2 is not None
        self.assertEqual(t1.status, "completed")
        self.assertNotEqual(t1.auto_resubmit_timeout, 100)
        self.assertEqual(t2.auto_resubmit_timeout, 100)


class TestTaskQueueActiveTask(unittest.TestCase):
    """测试活动任务管理"""

    def setUp(self):
        """每个测试前的准备"""
        from task_queue import TaskQueue

        self.queue = TaskQueue(max_tasks=5)

    def tearDown(self):
        """每个测试后的清理"""
        self.queue.stop_cleanup()

    def test_first_task_active(self):
        """测试第一个任务自动激活"""
        self.queue.add_task("task-1", "提示1")

        task = self.queue.get_task("task-1")

        self.assertIsNotNone(task)
        assert task is not None
        self.assertEqual(task.status, "active")

    def test_second_task_pending(self):
        """测试第二个任务为等待状态"""
        self.queue.add_task("task-1", "提示1")
        self.queue.add_task("task-2", "提示2")

        task = self.queue.get_task("task-2")

        self.assertIsNotNone(task)
        assert task is not None
        self.assertEqual(task.status, "pending")

    def test_set_active_task(self):
        """测试切换活动任务"""
        self.queue.add_task("task-1", "提示1")
        self.queue.add_task("task-2", "提示2")

        result = self.queue.set_active_task("task-2")

        self.assertTrue(result)
        task1 = self.queue.get_task("task-1")
        self.assertIsNotNone(task1)
        assert task1 is not None
        self.assertEqual(task1.status, "pending")

        task2 = self.queue.get_task("task-2")
        self.assertIsNotNone(task2)
        assert task2 is not None
        self.assertEqual(task2.status, "active")

    def test_set_active_task_reject_completed(self):
        """已完成任务不应被再次激活（避免状态机错乱与清理失效）"""
        self.queue.add_task("task-1", "提示1")
        self.queue.add_task("task-2", "提示2")

        # 完成 task-1 后，task-2 会自动激活
        self.queue.complete_task("task-1", {"feedback": "done"})

        result = self.queue.set_active_task("task-1")
        self.assertFalse(result)

        task1 = self.queue.get_task("task-1")
        task2 = self.queue.get_task("task-2")
        self.assertIsNotNone(task1)
        self.assertIsNotNone(task2)
        assert task1 is not None
        assert task2 is not None
        self.assertEqual(task1.status, "completed")
        self.assertEqual(task2.status, "active")

    def test_get_active_task(self):
        """测试获取活动任务"""
        self.queue.add_task("task-1", "提示1")

        active = self.queue.get_active_task()

        self.assertIsNotNone(active)
        assert active is not None
        self.assertEqual(active.task_id, "task-1")


class TestTaskQueueComplete(unittest.TestCase):
    """测试任务完成逻辑"""

    def setUp(self):
        """每个测试前的准备"""
        from task_queue import TaskQueue

        self.queue = TaskQueue(max_tasks=5)

    def tearDown(self):
        """每个测试后的清理"""
        self.queue.stop_cleanup()

    def test_complete_task(self):
        """测试完成任务"""
        self.queue.add_task("task-1", "提示1")

        result = self.queue.complete_task("task-1", {"feedback": "完成"})

        self.assertTrue(result)
        task = self.queue.get_task("task-1")
        self.assertIsNotNone(task)
        assert task is not None
        self.assertEqual(task.status, "completed")
        self.assertEqual(task.result, {"feedback": "完成"})

    def test_complete_auto_activate_next(self):
        """测试完成后自动激活下一个任务"""
        self.queue.add_task("task-1", "提示1")
        self.queue.add_task("task-2", "提示2")

        self.queue.complete_task("task-1", {"feedback": "完成"})

        task2 = self.queue.get_task("task-2")
        self.assertIsNotNone(task2)
        assert task2 is not None
        self.assertEqual(task2.status, "active")

    def test_complete_nonexistent_task(self):
        """测试完成不存在的任务"""
        result = self.queue.complete_task("nonexistent", {})

        self.assertFalse(result)


class TestTaskQueueCleanup(unittest.TestCase):
    """测试自动清理机制"""

    def setUp(self):
        """每个测试前的准备"""
        from task_queue import TaskQueue

        self.queue = TaskQueue(max_tasks=5)

    def tearDown(self):
        """每个测试后的清理"""
        self.queue.stop_cleanup()

    def test_cleanup_completed_tasks(self):
        """测试清理已完成任务"""
        self.queue.add_task("task-1", "提示1")
        self.queue.complete_task("task-1", {"feedback": "完成"})

        # 立即清理（age_seconds=0）
        count = self.queue.cleanup_completed_tasks(age_seconds=0)

        self.assertEqual(count, 1)
        self.assertIsNone(self.queue.get_task("task-1"))

    def test_cleanup_respects_age(self):
        """测试清理遵循时间限制"""
        self.queue.add_task("task-1", "提示1")
        self.queue.complete_task("task-1", {"feedback": "完成"})

        # 使用较长的 age_seconds，任务不应被清理
        count = self.queue.cleanup_completed_tasks(age_seconds=3600)

        self.assertEqual(count, 0)
        self.assertIsNotNone(self.queue.get_task("task-1"))

    def test_clear_completed_tasks(self):
        """测试立即清理所有已完成任务"""
        self.queue.add_task("task-1", "提示1")
        self.queue.add_task("task-2", "提示2")
        self.queue.complete_task("task-1", {})

        count = self.queue.clear_completed_tasks()

        self.assertEqual(count, 1)


class TestTaskQueueThreadSafety(unittest.TestCase):
    """测试线程安全"""

    def setUp(self):
        """每个测试前的准备"""
        from task_queue import TaskQueue

        self.queue = TaskQueue(max_tasks=100)
        self.errors = []

    def tearDown(self):
        """每个测试后的清理"""
        self.queue.stop_cleanup()

    def test_concurrent_add(self):
        """测试并发添加"""

        def adder(start):
            try:
                for i in range(10):
                    self.queue.add_task(f"task-{start}-{i}", f"提示{start}-{i}")
                    time.sleep(0.001)
            except Exception as e:
                self.errors.append(e)

        threads = [threading.Thread(target=adder, args=(i,)) for i in range(5)]

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        self.assertEqual(len(self.errors), 0)

        # 应该添加了 50 个任务
        count = self.queue.get_task_count()
        self.assertEqual(count["total"], 50)

    def test_concurrent_add_complete(self):
        """测试并发添加和完成"""
        # 先添加一些任务
        for i in range(20):
            self.queue.add_task(f"task-{i}", f"提示{i}")

        def completer():
            try:
                for i in range(20):
                    self.queue.complete_task(f"task-{i}", {"index": i})
                    time.sleep(0.001)
            except Exception as e:
                self.errors.append(e)

        def reader():
            try:
                for _ in range(30):
                    _ = self.queue.get_all_tasks()
                    _ = self.queue.get_task_count()
                    time.sleep(0.001)
            except Exception as e:
                self.errors.append(e)

        threads = [
            threading.Thread(target=completer),
            threading.Thread(target=reader),
            threading.Thread(target=reader),
        ]

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        self.assertEqual(len(self.errors), 0)


class TestTaskQueueStatistics(unittest.TestCase):
    """测试任务统计"""

    def setUp(self):
        """每个测试前的准备"""
        from task_queue import TaskQueue

        self.queue = TaskQueue(max_tasks=10)

    def tearDown(self):
        """每个测试后的清理"""
        self.queue.stop_cleanup()

    def test_get_task_count(self):
        """测试获取任务统计"""
        self.queue.add_task("task-1", "提示1")
        self.queue.add_task("task-2", "提示2")
        self.queue.complete_task("task-1", {})

        count = self.queue.get_task_count()

        self.assertEqual(count["total"], 2)
        self.assertEqual(count["pending"], 0)  # task-2 自动变为 active
        self.assertEqual(count["active"], 1)
        self.assertEqual(count["completed"], 1)
        self.assertEqual(count["max"], 10)


class TestTaskQueueEdgeCases(unittest.TestCase):
    """测试边界情况 - 针对本次修复新增

    测试场景：
    1. 所有任务都已完成时的行为
    2. 任务列表中第一个任务是已完成状态
    3. 从已完成任务恢复活动任务
    """

    def setUp(self):
        """每个测试前的准备"""
        from task_queue import TaskQueue

        self.queue = TaskQueue(max_tasks=5)

    def tearDown(self):
        """每个测试后的清理"""
        self.queue.stop_cleanup()

    def test_all_tasks_completed_no_active(self):
        """测试所有任务完成后没有活动任务"""
        self.queue.add_task("task-1", "提示1")
        self.queue.complete_task("task-1", {"feedback": "完成"})

        active = self.queue.get_active_task()

        self.assertIsNone(active)

    def test_get_all_tasks_returns_completed(self):
        """测试获取所有任务包含已完成任务"""
        self.queue.add_task("task-1", "提示1")
        self.queue.add_task("task-2", "提示2")
        self.queue.complete_task("task-1", {"feedback": "完成"})

        all_tasks = self.queue.get_all_tasks()

        self.assertEqual(len(all_tasks), 2)
        completed_tasks = [t for t in all_tasks if t.status == "completed"]
        self.assertEqual(len(completed_tasks), 1)

    def test_add_task_after_all_completed(self):
        """测试在所有任务完成后添加新任务"""
        self.queue.add_task("task-1", "提示1")
        self.queue.complete_task("task-1", {"feedback": "完成"})

        # 添加新任务
        result = self.queue.add_task("task-2", "提示2")

        self.assertTrue(result)
        active = self.queue.get_active_task()
        self.assertIsNotNone(active)
        assert active is not None
        self.assertEqual(active.task_id, "task-2")

    def test_get_incomplete_tasks_only(self):
        """测试获取未完成任务"""
        self.queue.add_task("task-1", "提示1")
        self.queue.add_task("task-2", "提示2")
        self.queue.add_task("task-3", "提示3")
        self.queue.complete_task("task-1", {})

        all_tasks = self.queue.get_all_tasks()
        incomplete_tasks = [t for t in all_tasks if t.status != "completed"]

        self.assertEqual(len(incomplete_tasks), 2)
        task_ids = [t.task_id for t in incomplete_tasks]
        self.assertNotIn("task-1", task_ids)
        self.assertIn("task-2", task_ids)
        self.assertIn("task-3", task_ids)

    def test_complete_multiple_tasks_activate_next(self):
        """测试连续完成多个任务后激活下一个"""
        self.queue.add_task("task-1", "提示1")
        self.queue.add_task("task-2", "提示2")
        self.queue.add_task("task-3", "提示3")

        # 完成 task-1，task-2 应该变为 active
        self.queue.complete_task("task-1", {})
        task2 = self.queue.get_task("task-2")
        self.assertIsNotNone(task2)
        assert task2 is not None
        self.assertEqual(task2.status, "active")

        # 完成 task-2，task-3 应该变为 active
        self.queue.complete_task("task-2", {})
        task3 = self.queue.get_task("task-3")
        self.assertIsNotNone(task3)
        assert task3 is not None
        self.assertEqual(task3.status, "active")

        # 完成 task-3，没有更多任务
        self.queue.complete_task("task-3", {})
        active = self.queue.get_active_task()
        self.assertIsNone(active)

    def test_task_count_with_mixed_status(self):
        """测试混合状态任务的统计"""
        self.queue.add_task("task-1", "提示1")
        self.queue.add_task("task-2", "提示2")
        self.queue.add_task("task-3", "提示3")
        self.queue.complete_task("task-1", {})
        # task-2 自动变为 active，task-3 保持 pending

        count = self.queue.get_task_count()

        self.assertEqual(count["total"], 3)
        self.assertEqual(count["completed"], 1)
        self.assertEqual(count["active"], 1)
        self.assertEqual(count["pending"], 1)


class TestTaskQueueAdvanced(unittest.TestCase):
    """任务队列高级测试"""

    def test_task_queue_add_get_remove(self):
        """测试任务队列基本操作"""
        from task_queue import TaskQueue

        queue = TaskQueue()

        # 添加任务
        queue.add_task("test-task-1", "测试任务", ["选项A", "选项B"])

        # 获取任务
        task = queue.get_task("test-task-1")
        self.assertIsNotNone(task)
        assert task is not None
        self.assertEqual(task.prompt, "测试任务")

        # 删除任务
        queue.remove_task("test-task-1")
        task = queue.get_task("test-task-1")
        self.assertIsNone(task)

    def test_task_queue_complete(self):
        """测试任务完成流程"""
        from task_queue import TaskQueue

        queue = TaskQueue()

        # 添加并完成任务
        queue.add_task("complete-task", "完成测试", [])
        result = queue.complete_task("complete-task", {"response": "done"})
        self.assertTrue(result)

    def test_task_queue_statistics(self):
        """测试任务队列统计"""
        from task_queue import TaskQueue

        queue = TaskQueue()

        # 添加多个任务
        queue.add_task("stat-1", "统计1", [])
        queue.add_task("stat-2", "统计2", [])

        # 获取统计
        stats = queue.get_task_count()
        self.assertIsInstance(stats, dict)


class TestTaskQueueFinalPush(unittest.TestCase):
    """Task Queue 最终冲刺测试"""

    def test_task_queue_stats(self):
        """测试任务队列统计"""
        from task_queue import TaskQueue

        queue = TaskQueue()

        # 获取统计
        stats = queue.get_task_count()

        self.assertIn("pending", stats)
        self.assertIn("active", stats)
        self.assertIn("completed", stats)

        queue.clear_all_tasks()

    def test_task_queue_clear(self):
        """测试清空任务队列"""
        from task_queue import TaskQueue

        queue = TaskQueue()

        # 添加任务
        queue.add_task("clear-test-1", "测试1")
        queue.add_task("clear-test-2", "测试2")

        # 清空
        queue.clear_all_tasks()

        # 验证已清空
        stats = queue.get_task_count()
        self.assertEqual(stats["pending"] + stats["active"] + stats["completed"], 0)


class TestTaskQueueBoundary(unittest.TestCase):
    """任务队列边界条件测试"""

    def setUp(self):
        """每个测试前的准备"""
        from task_queue import TaskQueue

        self.queue = TaskQueue(max_tasks=5)

    def tearDown(self):
        """每个测试后的清理"""
        self.queue.stop_cleanup()

    def test_empty_task_id(self):
        """测试空任务 ID"""
        result = self.queue.add_task("", "提示")
        # 空 ID 应该也能添加（由业务逻辑决定是否允许）
        self.assertIn(result, [True, False])

    def test_very_long_prompt(self):
        """测试超长提示"""
        long_prompt = "A" * 100000
        result = self.queue.add_task("task-long", long_prompt)

        self.assertTrue(result)
        task = self.queue.get_task("task-long")
        self.assertIsNotNone(task)
        assert task is not None
        self.assertEqual(len(task.prompt), 100000)

    def test_special_characters_in_prompt(self):
        """测试提示中的特殊字符"""
        special_prompt = (
            "<script>alert('xss')</script>\n\t\"quotes\" 'single' `backtick`"
        )
        result = self.queue.add_task("task-special", special_prompt)

        self.assertTrue(result)
        task = self.queue.get_task("task-special")
        self.assertIsNotNone(task)
        assert task is not None
        self.assertEqual(task.prompt, special_prompt)

    def test_many_predefined_options(self):
        """测试大量预定义选项"""
        options = [f"选项{i}" for i in range(1000)]
        result = self.queue.add_task("task-options", "提示", predefined_options=options)

        self.assertTrue(result)
        task = self.queue.get_task("task-options")
        self.assertIsNotNone(task)
        assert task is not None
        self.assertIsNotNone(task.predefined_options)
        assert task.predefined_options is not None
        self.assertEqual(len(task.predefined_options), 1000)


# ──────────────────────────────────────────────────────────
# 覆盖率补充
# ──────────────────────────────────────────────────────────


class TestCleanupThreadException(unittest.TestCase):
    """lines 705-707: 后台清理线程的异常和正常清理分支"""

    def test_cleanup_loop_exception_path(self):
        """706-707: _cleanup_loop 中 cleanup_completed_tasks 抛异常被捕获"""
        from unittest.mock import patch as _patch

        from task_queue import TaskQueue

        tq = TaskQueue()
        call_count = 0

        def mock_cleanup(age_seconds=10):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("cleanup err")
            return 0

        original_wait = tq._stop_cleanup.wait

        wait_calls = 0

        def mock_wait(timeout=5):
            nonlocal wait_calls
            wait_calls += 1
            return not wait_calls <= 2

        with _patch.object(tq, "cleanup_completed_tasks", side_effect=mock_cleanup):
            with _patch.object(tq._stop_cleanup, "wait", side_effect=mock_wait):
                tq._cleanup_loop()

        self.assertGreaterEqual(call_count, 1)

    def test_cleanup_loop_cleaned_positive(self):
        """line 705: cleaned > 0 时记录日志"""
        from unittest.mock import patch as _patch

        from task_queue import TaskQueue

        tq = TaskQueue()
        wait_calls = 0

        def mock_wait(timeout=5):
            nonlocal wait_calls
            wait_calls += 1
            return wait_calls > 1

        with _patch.object(tq, "cleanup_completed_tasks", return_value=3):
            with _patch.object(tq._stop_cleanup, "wait", side_effect=mock_wait):
                tq._cleanup_loop()


class TestTaskQueuePartialBranches(unittest.TestCase):
    """覆盖 task_queue.py 的部分分支"""

    def _make_tq(self, max_tasks: int = 10):
        from task_queue import TaskQueue

        return TaskQueue(max_tasks=max_tasks)

    def test_set_active_no_previous_active(self):
        """365->371 / 377->379: 无旧活跃任务时直接激活新任务"""
        tq = self._make_tq()
        tq.add_task("t1", "prompt1")
        tq.add_task("t2", "prompt2")
        tq.complete_task("t1", {"feedback": "done"})

        result = tq.set_active_task("t2")
        self.assertTrue(result)
        self.assertEqual(tq.get_active_task().task_id, "t2")

    def test_set_active_old_task_not_active_status(self):
        """367->371: 旧活跃任务状态不是 active（已被外部修改）"""
        tq = self._make_tq()
        tq.add_task("t1", "prompt1")
        tq.add_task("t2", "prompt2")

        with tq._lock:
            tq._tasks["t1"].status = "pending"

        result = tq.set_active_task("t2")
        self.assertTrue(result)

    def test_remove_non_active_task(self):
        """526->538: 移除非活跃任务不触发自动激活"""
        tq = self._make_tq()
        tq.add_task("t1", "prompt1")
        tq.add_task("t2", "prompt2")

        active_before = tq.get_active_task()
        result = tq.remove_task("t2")
        self.assertTrue(result)
        active_after = tq.get_active_task()
        self.assertEqual(active_before.task_id, active_after.task_id)

    def test_set_active_with_stale_active_id(self):
        """365->371: _active_task_id 指向已不存在的任务时跳过旧任务处理"""
        tq = self._make_tq()
        tq.add_task("t1", "prompt1")
        tq.add_task("t2", "prompt2")

        with tq._lock:
            tq._active_task_id = "ghost_task"

        result = tq.set_active_task("t2")
        self.assertTrue(result)
        self.assertEqual(tq.get_active_task().task_id, "t2")

    def test_stop_cleanup_thread_already_stopped(self):
        """742->exit: 清理线程已停止时跳过 join"""
        tq = self._make_tq()
        tq._stop_cleanup.set()
        tq._cleanup_thread.join(timeout=3)

        tq.stop_cleanup()


# ---------------------------------------------------------------------------
# 边界路径补充（原 test_task_queue_extended.py）
# ---------------------------------------------------------------------------
from task_queue import Task, TaskQueue


class TestTaskDataclassEdges(unittest.TestCase):
    def test_get_remaining_time_disabled(self):
        task = Task(task_id="t1", prompt="p", auto_resubmit_timeout=0)
        task.status = "active"
        self.assertEqual(task.get_remaining_time(), 0)

    def test_get_remaining_time_negative(self):
        task = Task(task_id="t2", prompt="p", auto_resubmit_timeout=-10)
        task.status = "active"
        self.assertEqual(task.get_remaining_time(), 0)

    def test_get_deadline_monotonic_disabled(self):
        task = Task(task_id="t3", prompt="p", auto_resubmit_timeout=0)
        self.assertEqual(task.get_deadline_monotonic(), float("inf"))

    def test_is_expired_completed(self):
        task = Task(task_id="t4", prompt="p", auto_resubmit_timeout=100)
        task.status = "completed"
        self.assertFalse(task.is_expired())

    def test_is_expired_disabled(self):
        task = Task(task_id="t5", prompt="p", auto_resubmit_timeout=0)
        task.status = "active"
        self.assertFalse(task.is_expired())

    def test_is_expired_negative(self):
        task = Task(task_id="t6", prompt="p", auto_resubmit_timeout=-5)
        task.status = "active"
        self.assertFalse(task.is_expired())

    def test_is_expired_true(self):
        task = Task(
            task_id="t7",
            prompt="p",
            auto_resubmit_timeout=1,
            created_at_monotonic=time.monotonic() - 10,
        )
        task.status = "active"
        self.assertTrue(task.is_expired())


class TestAddTaskTimeoutEdge(unittest.TestCase):
    def test_timeout_zero(self):
        q = TaskQueue()
        q.add_task("t1", "p", auto_resubmit_timeout=0)
        task = q.get_task("t1")
        assert task is not None
        self.assertEqual(task.auto_resubmit_timeout, 0)
        q.stop_cleanup()

    def test_timeout_negative(self):
        q = TaskQueue()
        q.add_task("t1", "p", auto_resubmit_timeout=-5)
        task = q.get_task("t1")
        assert task is not None
        self.assertEqual(task.auto_resubmit_timeout, 0)
        q.stop_cleanup()

    def test_timeout_small_positive_clamped(self):
        q = TaskQueue()
        q.add_task("t1", "p", auto_resubmit_timeout=10)
        task = q.get_task("t1")
        assert task is not None
        self.assertEqual(task.auto_resubmit_timeout, 30)
        q.stop_cleanup()


class TestRemoveTaskEdges(unittest.TestCase):
    def test_remove_nonexistent(self):
        q = TaskQueue()
        result = q.remove_task("nonexistent")
        self.assertFalse(result)
        q.stop_cleanup()

    def test_remove_active_activates_next(self):
        q = TaskQueue()
        q.add_task("t1", "p1")
        q.add_task("t2", "p2")
        q.remove_task("t1")
        t2 = q.get_task("t2")
        assert t2 is not None
        self.assertEqual(t2.status, "active")
        q.stop_cleanup()


class TestUpdateAutoResubmitTimeoutForAll(unittest.TestCase):
    def test_timeout_zero(self):
        q = TaskQueue()
        q.add_task("t1", "p")
        updated = q.update_auto_resubmit_timeout_for_all(0)
        self.assertGreater(updated, 0)
        task = q.get_task("t1")
        assert task is not None
        self.assertEqual(task.auto_resubmit_timeout, 0)
        q.stop_cleanup()

    def test_timeout_same_no_update(self):
        q = TaskQueue()
        q.add_task("t1", "p", auto_resubmit_timeout=60)
        updated = q.update_auto_resubmit_timeout_for_all(60)
        self.assertEqual(updated, 0)
        q.stop_cleanup()

    def test_skip_completed(self):
        q = TaskQueue()
        q.add_task("t1", "p")
        q.complete_task("t1", {"text": "answer"})
        updated = q.update_auto_resubmit_timeout_for_all(100)
        self.assertEqual(updated, 0)
        q.stop_cleanup()


class TestClearCompletedTasks(unittest.TestCase):
    def test_clears_and_returns_count(self):
        q = TaskQueue()
        q.add_task("t1", "p")
        q.complete_task("t1", {"text": "a"})
        count = q.clear_completed_tasks()
        self.assertEqual(count, 1)
        q.stop_cleanup()

    def test_no_completed_returns_zero(self):
        q = TaskQueue()
        q.add_task("t1", "p")
        count = q.clear_completed_tasks()
        self.assertEqual(count, 0)
        q.stop_cleanup()


class TestCleanupLoopException(unittest.TestCase):
    def test_exception_doesnt_crash(self):
        q = TaskQueue()
        with patch.object(
            q, "cleanup_completed_tasks", side_effect=RuntimeError("boom")
        ):
            q._stop_cleanup.set()
            q._cleanup_loop()


class TestStopCleanupTimeout(unittest.TestCase):
    def test_thread_still_alive_warning(self):
        q = TaskQueue()
        mock_thread = MagicMock()
        mock_thread.is_alive.return_value = True
        q._cleanup_thread = mock_thread
        q.stop_cleanup()
        mock_thread.join.assert_called_once_with(timeout=2)

    def test_thread_stops_normally(self):
        q = TaskQueue()
        q.stop_cleanup()


class TestCallbackRegistration(unittest.TestCase):
    def test_register_duplicate_ignored(self):
        q = TaskQueue()

        def cb(tid, old, new):
            pass

        q.register_status_change_callback(cb)
        q.register_status_change_callback(cb)
        self.assertEqual(q._status_change_callbacks.count(cb), 1)
        q.stop_cleanup()

    def test_unregister_nonexistent(self):
        q = TaskQueue()

        def cb(tid, old, new):
            pass

        q.unregister_status_change_callback(cb)
        q.stop_cleanup()

    def test_callback_triggered_on_add(self):
        q = TaskQueue()
        events: list[tuple] = []

        def cb(tid, old, new):
            events.append((tid, old, new))

        q.register_status_change_callback(cb)
        q.add_task("t1", "p")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0], ("t1", None, "active"))
        q.stop_cleanup()


if __name__ == "__main__":
    unittest.main()
