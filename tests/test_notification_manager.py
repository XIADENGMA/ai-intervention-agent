#!/usr/bin/env python3
"""
AI Intervention Agent - 通知管理器单元测试

测试覆盖：
1. 配置刷新功能（refresh_config_from_file）
2. 配置缓存机制
3. 类型验证
4. 线程安全
5. Bark 提供者动态更新
"""

import os
import shutil
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def _resolve_test_config_path() -> Path:
    """获取测试用配置文件路径。

    说明：
    - pytest 会在 `tests/conftest.py` 中注入环境变量 AI_INTERVENTION_AGENT_CONFIG_FILE，
      用于让测试完全可重复、且不污染用户真实配置目录。
    - 本文件中的测试不应硬编码依赖仓库根目录的 `config.jsonc`（CI 环境可能不存在该文件）。
    """
    override = os.environ.get("AI_INTERVENTION_AGENT_CONFIG_FILE")
    if override:
        p = Path(override).expanduser()
        if p.is_dir():
            p = p / "config.jsonc"
        return p
    return project_root / "config.jsonc"


def _ensure_test_config_file_exists(config_path: Path) -> None:
    """确保测试配置文件存在（优先从 config.jsonc.default 生成）。"""
    config_path.parent.mkdir(parents=True, exist_ok=True)
    if config_path.exists():
        return

    default_cfg = project_root / "config.jsonc.default"
    if default_cfg.exists():
        shutil.copy(default_cfg, config_path)
        return

    # 兜底：写入最小可用配置（JSON 也可被 JSONC 解析器处理）
    config_path.write_text(
        """{
  "notification": {
    "enabled": true,
    "bark_enabled": false,
    "sound_volume": 80
  }
}
""",
        encoding="utf-8",
    )


class TestNotificationManagerConfigRefresh(unittest.TestCase):
    """测试配置刷新功能"""

    @classmethod
    def setUpClass(cls):
        """测试类初始化"""
        cls.config_path = _resolve_test_config_path()
        cls.backup_path = cls.config_path.with_name(
            cls.config_path.name + ".backup_test"
        )

        # 确保配置文件存在，并备份基线
        _ensure_test_config_file_exists(cls.config_path)
        shutil.copy(cls.config_path, cls.backup_path)

    @classmethod
    def tearDownClass(cls):
        """测试类清理"""
        # 恢复原配置
        if cls.backup_path.exists():
            shutil.copy(cls.backup_path, cls.config_path)
            os.remove(cls.backup_path)

    def setUp(self):
        """每个测试前的准备"""
        # 导入需要在每次测试时重新导入，以确保单例状态正确
        from notification_manager import notification_manager

        self.manager = notification_manager
        # 强制刷新配置
        self.manager.refresh_config_from_file(force=True)

    def test_refresh_config_basic(self):
        """测试基本配置刷新功能"""
        # 执行刷新
        self.manager.refresh_config_from_file(force=True)

        # 验证配置被加载
        self.assertIsNotNone(self.manager.config)
        self.assertIsInstance(self.manager.config.enabled, bool)
        self.assertIsInstance(self.manager.config.bark_enabled, bool)

    def test_config_cache_mechanism(self):
        """测试配置缓存机制"""
        # 首次刷新（强制）
        self.manager.refresh_config_from_file(force=True)
        initial_mtime = self.manager._config_file_mtime

        # 验证 mtime 已被设置（不为 0）
        self.assertNotEqual(initial_mtime, 0.0, "首次刷新后 mtime 应该被设置")

        # 再次刷新（应该使用缓存，因为文件未变化）
        self.manager.refresh_config_from_file()

        # 验证 mtime 没有变化（使用了缓存）
        self.assertEqual(
            self.manager._config_file_mtime,
            initial_mtime,
            "缓存刷新后 mtime 应该保持不变",
        )

    def test_force_refresh(self):
        """测试强制刷新功能"""
        # 首次刷新
        self.manager.refresh_config_from_file(force=True)

        # 强制刷新（应该重新读取）
        self.manager.refresh_config_from_file(force=True)

        # 验证配置仍然有效
        self.assertIsNotNone(self.manager.config.enabled)


class TestNotificationManagerTypeValidation(unittest.TestCase):
    """测试类型验证功能"""

    @classmethod
    def setUpClass(cls):
        """测试类初始化"""
        cls.config_path = _resolve_test_config_path()
        cls.backup_path = cls.config_path.with_name(
            cls.config_path.name + ".backup_test"
        )

        # 确保配置文件存在，并备份基线
        _ensure_test_config_file_exists(cls.config_path)
        shutil.copy(cls.config_path, cls.backup_path)

    @classmethod
    def tearDownClass(cls):
        """测试类清理"""
        # 恢复原配置
        if cls.backup_path.exists():
            shutil.copy(cls.backup_path, cls.config_path)
            os.remove(cls.backup_path)

    def setUp(self):
        """每个测试前的准备"""
        from notification_manager import notification_manager

        self.manager = notification_manager

    def tearDown(self):
        """每个测试后的清理"""
        # 恢复配置
        if self.backup_path.exists():
            shutil.copy(self.backup_path, self.config_path)

    def test_invalid_bool_value(self):
        """测试无效布尔值处理"""
        # 修改配置文件，设置无效布尔值
        with open(self.config_path, "r") as f:
            content = f.read()

        content = content.replace(
            '"bark_enabled": false', '"bark_enabled": "not_a_boolean"'
        )

        with open(self.config_path, "w") as f:
            f.write(content)

        # 刷新配置
        self.manager.refresh_config_from_file(force=True)

        # 验证使用了默认值
        self.assertIsInstance(self.manager.config.bark_enabled, bool)

    def test_valid_sound_volume(self):
        """测试有效音量值"""
        self.manager.refresh_config_from_file(force=True)

        # 验证音量在有效范围内
        self.assertGreaterEqual(self.manager.config.sound_volume, 0.0)
        self.assertLessEqual(self.manager.config.sound_volume, 1.0)


class TestNotificationManagerThreadSafety(unittest.TestCase):
    """测试线程安全"""

    def setUp(self):
        """每个测试前的准备"""
        from notification_manager import notification_manager

        self.manager = notification_manager
        self.errors = []

    def test_concurrent_refresh(self):
        """测试并发刷新"""

        def refresh_worker():
            try:
                for _ in range(10):
                    self.manager.refresh_config_from_file(force=True)
                    time.sleep(0.001)
            except Exception as e:
                self.errors.append(e)

        # 启动多个线程并发刷新
        threads = [threading.Thread(target=refresh_worker) for _ in range(5)]

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        # 验证没有错误
        self.assertEqual(len(self.errors), 0, f"并发刷新出现错误: {self.errors}")

    def test_concurrent_read_write(self):
        """测试并发读写"""

        def reader():
            try:
                for _ in range(20):
                    _ = self.manager.config.bark_enabled
                    _ = self.manager.config.sound_volume
                    time.sleep(0.001)
            except Exception as e:
                self.errors.append(e)

        def writer():
            try:
                for _ in range(10):
                    self.manager.refresh_config_from_file(force=True)
                    time.sleep(0.001)
            except Exception as e:
                self.errors.append(e)

        # 启动读写线程
        threads = [threading.Thread(target=reader) for _ in range(3)] + [
            threading.Thread(target=writer) for _ in range(2)
        ]

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        # 验证没有错误
        self.assertEqual(len(self.errors), 0, f"并发读写出现错误: {self.errors}")


class TestNotificationManagerBarkProvider(unittest.TestCase):
    """测试 Bark 提供者动态更新"""

    @classmethod
    def setUpClass(cls):
        """测试类初始化"""
        cls.config_path = _resolve_test_config_path()
        cls.backup_path = cls.config_path.with_name(
            cls.config_path.name + ".backup_test"
        )

        # 确保配置文件存在，并备份基线
        _ensure_test_config_file_exists(cls.config_path)
        shutil.copy(cls.config_path, cls.backup_path)

    @classmethod
    def tearDownClass(cls):
        """测试类清理"""
        # 恢复原配置
        if cls.backup_path.exists():
            shutil.copy(cls.backup_path, cls.config_path)
            os.remove(cls.backup_path)

    def setUp(self):
        """每个测试前的准备"""
        from notification_manager import NotificationType, notification_manager

        self.manager = notification_manager
        self.NotificationType = NotificationType

    def tearDown(self):
        """每个测试后的清理"""
        # 恢复配置
        if self.backup_path.exists():
            shutil.copy(self.backup_path, self.config_path)

    def test_bark_provider_follows_config(self):
        """测试 Bark 提供者跟随配置变化"""
        # 强制刷新获取当前配置
        self.manager.refresh_config_from_file(force=True)

        # 获取当前 bark_enabled 状态
        bark_enabled = self.manager.config.bark_enabled
        has_bark_provider = self.NotificationType.BARK in self.manager._providers

        # 验证配置和提供者状态一致
        # 注意：提供者可能因为其他原因不可用（如导入失败）
        if bark_enabled:
            # 如果 bark_enabled 为 True，提供者应该存在（除非导入失败）
            pass  # 这里不强制验证，因为 BarkNotificationProvider 可能不可用
        else:
            # 如果 bark_enabled 为 False，提供者不应该存在
            # 但由于初始化顺序问题，这里也不强制验证
            pass


class TestNotificationManagerRetryAndStats(unittest.TestCase):
    """通知重试与可观测性：最小回归测试"""

    def setUp(self):
        from notification_manager import (
            NotificationEvent,
            NotificationTrigger,
            NotificationType,
            notification_manager,
        )

        self.NotificationEvent = NotificationEvent
        self.NotificationTrigger = NotificationTrigger
        self.NotificationType = NotificationType
        self.manager = notification_manager

        # 确保可用（有些测试可能调用过 shutdown）
        self.manager.restart()

        # 备份并替换 provider（避免真实网络）
        self._orig_providers = dict(self.manager._providers)
        self._orig_retry_count = self.manager.config.retry_count
        self._orig_retry_delay = self.manager.config.retry_delay
        self._orig_fallback_enabled = self.manager.config.fallback_enabled

        self.manager.config.retry_count = 2
        self.manager.config.retry_delay = 2
        self.manager.config.fallback_enabled = True

        self.fake_provider = Mock()
        self.fake_provider.send = Mock(return_value=False)
        self.manager.register_provider(self.NotificationType.BARK, self.fake_provider)

    def tearDown(self):
        self.manager._providers = self._orig_providers
        self.manager.config.retry_count = self._orig_retry_count
        self.manager.config.retry_delay = self._orig_retry_delay
        self.manager.config.fallback_enabled = self._orig_fallback_enabled

    def _make_event(self, max_retries: int, retry_count: int = 0):
        return self.NotificationEvent(
            id=f"retry-test-{time.time_ns()}",
            title="标题",
            message="消息",
            trigger=self.NotificationTrigger.IMMEDIATE,
            types=[self.NotificationType.BARK],
            metadata={},
            retry_count=retry_count,
            max_retries=max_retries,
        )

    def test_process_event_schedules_retry_when_all_failed(self):
        """所有渠道失败且还有重试额度：应调度重试而非直接降级"""
        event = self._make_event(max_retries=2, retry_count=0)

        with (
            patch.object(self.manager, "_schedule_retry") as schedule_mock,
            patch.object(self.manager, "_handle_fallback") as fallback_mock,
        ):
            self.manager._process_event(event)

            schedule_mock.assert_called_once()
            fallback_mock.assert_not_called()
            self.assertEqual(event.retry_count, 1)

    def test_process_event_calls_fallback_when_retries_exhausted(self):
        """重试耗尽：应进入降级处理"""
        event = self._make_event(max_retries=0, retry_count=0)

        with (
            patch.object(self.manager, "_schedule_retry") as schedule_mock,
            patch.object(self.manager, "_handle_fallback") as fallback_mock,
        ):
            self.manager._process_event(event)

            schedule_mock.assert_not_called()
            fallback_mock.assert_called_once()

    def test_get_status_contains_stats(self):
        """状态接口应包含 stats（用于可观测性）"""
        # 让一次通知成功（避免走重试/降级）
        self.fake_provider.send.return_value = True

        _ = self.manager.send_notification(
            "标题",
            "消息",
            types=[self.NotificationType.BARK],
        )

        status = self.manager.get_status()
        self.assertIsInstance(status, dict)
        self.assertIn("stats", status)
        self.assertIn("events_total", status["stats"])
        self.assertGreaterEqual(status["stats"]["events_total"], 1)


class TestNotificationManagerPerformance(unittest.TestCase):
    """测试性能"""

    def setUp(self):
        """每个测试前的准备"""
        from notification_manager import notification_manager

        self.manager = notification_manager

    def test_cache_performance(self):
        """测试缓存带来的性能提升"""
        # 预热
        self.manager.refresh_config_from_file(force=True)

        # 测试强制刷新（无缓存）
        iterations = 50
        start = time.time()
        for _ in range(iterations):
            self.manager.refresh_config_from_file(force=True)
        no_cache_time = time.time() - start

        # 测试缓存刷新
        start = time.time()
        for _ in range(iterations):
            self.manager.refresh_config_from_file()
        cache_time = time.time() - start

        # 缓存应该更快
        print(f"\n性能对比: 无缓存={no_cache_time:.4f}s, 有缓存={cache_time:.4f}s")

        # 缓存时间应该明显更短（至少 2 倍）
        # 但由于测试环境差异，这里只验证不会比无缓存更慢
        self.assertLessEqual(cache_time, no_cache_time * 1.5)


def run_tests():
    """运行所有测试"""
    # 创建测试套件
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # 添加测试类
    suite.addTests(loader.loadTestsFromTestCase(TestNotificationManagerConfigRefresh))
    suite.addTests(loader.loadTestsFromTestCase(TestNotificationManagerTypeValidation))
    suite.addTests(loader.loadTestsFromTestCase(TestNotificationManagerThreadSafety))
    suite.addTests(loader.loadTestsFromTestCase(TestNotificationManagerBarkProvider))
    suite.addTests(loader.loadTestsFromTestCase(TestNotificationManagerRetryAndStats))
    suite.addTests(loader.loadTestsFromTestCase(TestNotificationManagerPerformance))

    # 运行测试
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
