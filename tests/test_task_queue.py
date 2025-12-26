#!/usr/bin/env python3
"""
AI Intervention Agent - 任务队列单元测试

测试覆盖：
1. 任务添加/获取/删除
2. 任务状态管理
3. 线程安全
4. 自动清理机制
5. 活动任务切换
"""

import sys
import threading
import time
import unittest
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


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


def run_tests():
    """运行所有测试"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    suite.addTests(loader.loadTestsFromTestCase(TestTaskBasic))
    suite.addTests(loader.loadTestsFromTestCase(TestTaskQueueBasic))
    suite.addTests(loader.loadTestsFromTestCase(TestTaskQueueActiveTask))
    suite.addTests(loader.loadTestsFromTestCase(TestTaskQueueComplete))
    suite.addTests(loader.loadTestsFromTestCase(TestTaskQueueCleanup))
    suite.addTests(loader.loadTestsFromTestCase(TestTaskQueueThreadSafety))
    suite.addTests(loader.loadTestsFromTestCase(TestTaskQueueStatistics))
    suite.addTests(loader.loadTestsFromTestCase(TestTaskQueueEdgeCases))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
