#!/usr/bin/env python3
"""
AI Intervention Agent - 性能测试

测试各模块的性能和并发处理能力
"""

import sys
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor, as_completed


class TestConfigManagerPerformance(unittest.TestCase):
    """配置管理器性能测试"""

    def test_config_read_performance(self):
        """测试配置读取性能"""
        from config_manager import config_manager

        start_time = time.time()

        # 执行 1000 次配置读取
        for _ in range(1000):
            _ = config_manager.get("notification")

        elapsed = time.time() - start_time

        # 1000 次读取应该在 1 秒内完成
        self.assertLess(elapsed, 1.0, f"配置读取过慢: {elapsed:.3f}s")
        print(f"\n配置读取性能: 1000 次读取耗时 {elapsed:.3f}s")

    def test_config_concurrent_read(self):
        """测试配置并发读取"""
        from config_manager import config_manager

        results = []

        def read_config():
            for _ in range(100):
                _ = config_manager.get("notification")
            return True

        start_time = time.time()

        # 10 个线程并发读取
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(read_config) for _ in range(10)]
            for future in as_completed(futures):
                results.append(future.result())

        elapsed = time.time() - start_time

        # 所有读取应该成功
        self.assertEqual(len(results), 10)
        self.assertTrue(all(results))
        print(f"\n并发配置读取: 10 线程各 100 次，耗时 {elapsed:.3f}s")


class TestNotificationManagerPerformance(unittest.TestCase):
    """通知管理器性能测试"""

    def test_notification_send_performance(self):
        """测试通知发送性能"""
        from notification_manager import (
            NotificationTrigger,
            NotificationType,
            notification_manager,
        )

        # send_notification 是异步的（事件被推到线程池后立即返回），如果不禁用 retry，
        # 性能测试结束后线程池里残留的事件还会跑 retry 链路 → 污染后续测试窗口的 CI 输出
        # （会冒出 "通知发送失败，将在 2s 后重试" WARNING）。设 retry_count=0 让失败的
        # 通知直接 finalize 而不 retry；性能测试本身不验证 retry 行为，对断言无影响。
        original_enabled = notification_manager.config.enabled
        original_retry_count = notification_manager.config.retry_count
        notification_manager.config.enabled = True
        notification_manager.config.retry_count = 0

        try:
            start_time = time.time()

            for i in range(100):
                notification_manager.send_notification(
                    title=f"性能测试 {i}",
                    message=f"测试消息 {i}",
                    trigger=NotificationTrigger.IMMEDIATE,
                    types=[NotificationType.WEB],
                )

            elapsed = time.time() - start_time

            self.assertLess(elapsed, 2.0, f"通知发送过慢: {elapsed:.3f}s")
            print(f"\n通知发送性能: 100 个通知耗时 {elapsed:.3f}s")
        finally:
            notification_manager.config.enabled = original_enabled
            notification_manager.config.retry_count = original_retry_count

    def test_config_refresh_performance(self):
        """测试配置刷新性能"""
        from notification_manager import notification_manager

        start_time = time.time()

        # 执行 100 次配置刷新
        for _ in range(100):
            notification_manager.refresh_config_from_file()

        elapsed = time.time() - start_time

        # 100 次刷新应该在 1 秒内完成
        self.assertLess(elapsed, 1.0, f"配置刷新过慢: {elapsed:.3f}s")
        print(f"\n配置刷新性能: 100 次刷新耗时 {elapsed:.3f}s")


class TestTaskQueuePerformance(unittest.TestCase):
    """任务队列性能测试"""

    def setUp(self):
        """每个测试前的准备"""
        from task_queue import TaskQueue

        # 性能测试要加 100 个任务（test_task_add_performance）和 50 个并发任务
        # （test_task_concurrent_operations），都超过 TaskQueue 默认 max_tasks=10
        # 限制；用大上限避免触发"队列已满" WARNING 污染 CI 输出。
        self.queue = TaskQueue(max_tasks=2000)

    def tearDown(self):
        """每个测试后的清理"""
        self.queue.clear_all_tasks()

    def test_task_add_performance(self):
        """测试任务添加性能"""
        start_time = time.time()

        # 添加 100 个任务
        for i in range(100):
            self.queue.add_task(f"perf-task-{i}", f"性能测试任务 {i}")

        elapsed = time.time() - start_time

        # 100 个任务添加应该在 0.5 秒内完成
        self.assertLess(elapsed, 0.5, f"任务添加过慢: {elapsed:.3f}s")
        print(f"\n任务添加性能: 100 个任务耗时 {elapsed:.3f}s")

    def test_task_concurrent_operations(self):
        """测试任务并发操作"""
        results = []

        def add_tasks(start_idx):
            for i in range(10):
                self.queue.add_task(
                    f"concurrent-task-{start_idx}-{i}", f"并发测试任务 {start_idx}-{i}"
                )
            return True

        start_time = time.time()

        # 5 个线程并发添加任务
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(add_tasks, i) for i in range(5)]
            for future in as_completed(futures):
                results.append(future.result())

        elapsed = time.time() - start_time

        self.assertEqual(len(results), 5)
        self.assertTrue(all(results))
        print(f"\n并发任务操作: 5 线程各 10 个任务，耗时 {elapsed:.3f}s")


class TestLogDeduplicatorPerformance(unittest.TestCase):
    """日志去重器性能测试"""

    def test_dedup_performance(self):
        """测试去重性能"""
        from enhanced_logging import LogDeduplicator

        dedup = LogDeduplicator(time_window=5.0)

        start_time = time.time()

        # 执行 10000 次去重检查
        for i in range(10000):
            dedup.should_log(f"message_{i % 100}")  # 重复消息

        elapsed = time.time() - start_time

        # 10000 次检查应该在 1 秒内完成
        self.assertLess(elapsed, 1.0, f"去重检查过慢: {elapsed:.3f}s")
        print(f"\n日志去重性能: 10000 次检查耗时 {elapsed:.3f}s")


class TestFileValidatorPerformance(unittest.TestCase):
    """文件验证器性能测试"""

    def test_validator_creation_performance(self):
        """测试验证器创建性能"""
        from file_validator import FileValidator

        start_time = time.time()

        # 执行 1000 次创建
        for _ in range(1000):
            _ = FileValidator()

        elapsed = time.time() - start_time

        # 1000 次创建应该在 0.5 秒内完成
        self.assertLess(elapsed, 0.5, f"验证器创建过慢: {elapsed:.3f}s")
        print(f"\n验证器创建性能: 1000 次创建耗时 {elapsed:.3f}s")


class TestWebUIPerformance(unittest.TestCase):
    """Web UI 性能测试"""

    @classmethod
    def setUpClass(cls):
        """测试类初始化"""
        from web_ui import WebFeedbackUI

        cls.web_ui = WebFeedbackUI(prompt="性能测试", task_id="perf-test", port=8990)
        cls.app = cls.web_ui.app
        cls.app.config["TESTING"] = True
        cls.client = cls.app.test_client()

    def test_api_response_time(self):
        """测试 API 响应时间"""
        start_time = time.time()

        # 执行 100 次 API 调用
        for _ in range(100):
            self.client.get("/api/tasks")

        elapsed = time.time() - start_time

        # 100 次调用应该在 2 秒内完成
        self.assertLess(elapsed, 2.0, f"API 响应过慢: {elapsed:.3f}s")
        print(f"\nAPI 响应性能: 100 次调用耗时 {elapsed:.3f}s")

    def test_concurrent_api_calls(self):
        """测试并发 API 调用"""
        results = []

        def call_api():
            for _ in range(20):
                response = self.client.get("/api/tasks")
                if response.status_code == 200:
                    return True
            return True

        start_time = time.time()

        # 5 个线程并发调用
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(call_api) for _ in range(5)]
            for future in as_completed(futures):
                results.append(future.result())

        elapsed = time.time() - start_time

        self.assertEqual(len(results), 5)
        print(f"\n并发 API 调用: 5 线程各 20 次，耗时 {elapsed:.3f}s")


class TestServerFunctionPerformance(unittest.TestCase):
    """服务器函数性能测试"""

    def test_validate_input_performance(self):
        """测试输入验证性能"""
        from server import validate_input

        start_time = time.time()

        # 执行 10000 次验证
        for i in range(10000):
            validate_input(f"测试消息 {i}", [f"选项 {j}" for j in range(5)])

        elapsed = time.time() - start_time

        # 10000 次验证应该在 1 秒内完成
        self.assertLess(elapsed, 1.0, f"输入验证过慢: {elapsed:.3f}s")
        print(f"\n输入验证性能: 10000 次验证耗时 {elapsed:.3f}s")

    def test_parse_response_performance(self):
        """测试响应解析性能"""
        from server import parse_structured_response

        response = {
            "user_input": "测试输入",
            "selected_options": ["选项1", "选项2"],
            "images": [],
        }

        start_time = time.time()

        # 执行 10000 次解析
        for _ in range(10000):
            parse_structured_response(response)

        elapsed = time.time() - start_time

        # 10000 次解析应该在 5 秒内完成（CI 环境和覆盖率模式会变慢）
        self.assertLess(elapsed, 5.0, f"响应解析过慢: {elapsed:.3f}s")
        print(f"\n响应解析性能: 10000 次解析耗时 {elapsed:.3f}s")


class TestHighConcurrency(unittest.TestCase):
    """高并发测试"""

    def test_task_queue_high_concurrency(self):
        """测试任务队列高并发"""
        from task_queue import TaskQueue

        queue = TaskQueue(max_tasks=1000)
        errors = []

        def worker(thread_id):
            try:
                for i in range(100):
                    task_id = f"task-{thread_id}-{i}"
                    queue.add_task(task_id, f"提示{thread_id}-{i}")
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        queue.stop_cleanup()

        self.assertEqual(len(errors), 0)
        # 应该成功添加 1000 个任务
        count = queue.get_task_count()
        self.assertEqual(count["total"], 1000)

    def test_config_manager_concurrent_access(self):
        """测试配置管理器并发访问"""
        from notification_manager import notification_manager

        errors = []
        iterations = 50

        def reader():
            try:
                for _ in range(iterations):
                    _ = notification_manager.config.bark_enabled
                    _ = notification_manager.config.sound_volume
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        def writer():
            try:
                for _ in range(iterations):
                    notification_manager.refresh_config_from_file(force=True)
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=reader) for _ in range(5)] + [
            threading.Thread(target=writer) for _ in range(2)
        ]

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0)

    def test_file_validator_concurrent_validation(self):
        """测试文件验证器并发验证"""
        from file_validator import validate_uploaded_file

        png_data = b"\x89\x50\x4e\x47\x0d\x0a\x1a\x0a" + b"\x00" * 100
        errors = []

        def validator(thread_id):
            try:
                for i in range(50):
                    result = validate_uploaded_file(
                        png_data, f"test_{thread_id}_{i}.png"
                    )
                    if not result["valid"]:
                        errors.append(f"Validation failed: {result}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=validator, args=(i,)) for i in range(10)]

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0)


# ============================================================================
# 集成测试
# ============================================================================


def run_tests():
    """运行所有性能测试"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    suite.addTests(loader.loadTestsFromTestCase(TestConfigManagerPerformance))
    suite.addTests(loader.loadTestsFromTestCase(TestNotificationManagerPerformance))
    suite.addTests(loader.loadTestsFromTestCase(TestTaskQueuePerformance))
    suite.addTests(loader.loadTestsFromTestCase(TestLogDeduplicatorPerformance))
    suite.addTests(loader.loadTestsFromTestCase(TestFileValidatorPerformance))
    suite.addTests(loader.loadTestsFromTestCase(TestWebUIPerformance))
    suite.addTests(loader.loadTestsFromTestCase(TestServerFunctionPerformance))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
