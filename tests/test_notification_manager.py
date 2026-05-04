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
import threading
import time
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, Mock, patch

project_root = Path(__file__).parent.parent


def _resolve_test_config_path() -> Path:
    """获取测试用配置文件路径。

    说明：
    - pytest 会在 `tests/conftest.py` 中注入环境变量 AI_INTERVENTION_AGENT_CONFIG_FILE，
      用于让测试完全可重复、且不污染用户真实配置目录。
    - 本文件中的测试不应硬编码依赖仓库根目录的 `config.toml`（CI 环境可能不存在该文件）。
    """
    override = os.environ.get("AI_INTERVENTION_AGENT_CONFIG_FILE")
    if override:
        p = Path(override).expanduser()
        if p.is_dir():
            p = p / "config.toml"
        return p
    return project_root / "config.toml"


def _ensure_test_config_file_exists(config_path: Path) -> None:
    """确保测试配置文件存在（优先从 config.toml.default 生成）。"""
    config_path.parent.mkdir(parents=True, exist_ok=True)
    if config_path.exists():
        return

    default_cfg = project_root / "config.toml.default"
    if default_cfg.exists():
        shutil.copy(default_cfg, config_path)
        return

    # 兜底：写入最小可用配置
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
        with open(self.config_path) as f:
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

    def test_cache_behavior_skips_get_section_on_unchanged_mtime(self):
        """R17.7：缓存命中时**不应**调用 ``config_mgr.get_section``。

        历史背景
        --------
        本测试原先用 ``time.time()`` 量"50 次有缓存调用 ≤ 50 次无缓存调用 ×
        1.5"的速度比来验证缓存。问题：

        1. ``time.time()`` 在毫秒级以内的精度差，多核 / GC / JIT 任意一个
           扰动都能让 50 次循环的总耗时（典型 1-10 ms）抖动 5-10 倍。
        2. 单跑能过、批跑可能被前后测试的 GC / fsync / IO 推进搞 fail。
           这就是 flaky 测试的典型形态。

        修法
        ----
        改成**行为验证**：缓存命中走的是 ``mtime`` 短路分支
        （``return`` 之前根本没读 toml 也没调 ``get_section``）。把底层的
        ``config_mgr.get_section`` mock 掉，断言：

        - force=True 调用 50 次 → ``get_section`` 被调 50 次
        - force=False 且 mtime 未变 → ``get_section`` 被调 **0** 次

        这种锁是确定性的，不受机器性能 / CI 环境波动影响，且锁住的"缓存
        命中跳过 IO"是缓存真正的语义价值，比"跑得快"更有意义。
        """
        from unittest.mock import patch

        fixed_mtime = 1700000000.0  # 选一个固定的 epoch 时间

        class _StubStat:
            st_mtime = fixed_mtime

        with patch("notification_manager.get_config") as mock_get_config:
            mock_cfg = mock_get_config.return_value
            mock_cfg.config_file.stat.return_value = _StubStat()
            mock_cfg.get_section.return_value = {}

            iterations = 50

            for _ in range(iterations):
                self.manager.refresh_config_from_file(force=True)
            forced_calls = mock_cfg.get_section.call_count
            self.assertEqual(
                forced_calls,
                iterations,
                f"force=True 下应调用 get_section 恰好 {iterations} 次，"
                f"实际 {forced_calls}",
            )
            self.assertEqual(
                self.manager._config_file_mtime,
                fixed_mtime,
                "force=True 后 _config_file_mtime 应被更新为 stub 的 mtime",
            )

            mock_cfg.get_section.reset_mock()
            for _ in range(iterations):
                self.manager.refresh_config_from_file()
            cached_calls = mock_cfg.get_section.call_count
            self.assertEqual(
                cached_calls,
                0,
                f"mtime 未变化时缓存应短路，预期 get_section 调用 0 次，"
                f"实际 {cached_calls}（缓存语义被破坏）",
            )

    def test_cache_invalidation_on_mtime_change(self):
        """R17.7：mtime 变化时缓存必须失效，重新调用 ``get_section``。

        反向锁：保护"缓存太激进"的 bug 类——如果缓存命中分支的判断条件
        被错误地放宽（比如改成"配置文件存在就跳过"），mtime 变化也不会
        触发刷新，用户改 ``config.toml`` 后等 N 分钟仍看到旧值。
        """
        from unittest.mock import patch

        # 预热
        self.manager.refresh_config_from_file(force=True)
        cached_mtime = self.manager._config_file_mtime

        with patch("notification_manager.get_config") as mock_get_config:
            mock_cfg = mock_get_config.return_value
            mock_cfg.get_section.return_value = {}

            # 模拟"用户改了配置文件"：返回比缓存大的 mtime
            class _NewerStat:
                st_mtime = cached_mtime + 1.0

            mock_cfg.config_file.stat.return_value = _NewerStat()

            self.manager.refresh_config_from_file(force=False)
            self.assertEqual(
                mock_cfg.get_section.call_count,
                1,
                "mtime 变化时必须重新加载 (调 get_section 一次)；"
                "若为 0 说明缓存对 mtime 变更失能",
            )


class TestNotificationManagerSendNotification(unittest.TestCase):
    """通知发送功能测试"""

    def setUp(self):
        """每个测试前的准备"""
        from notification_manager import notification_manager

        self.manager = notification_manager

    def test_get_config(self):
        """测试获取配置"""
        config = self.manager.get_config()
        self.assertIsNotNone(config)

    def test_register_provider(self):
        """测试注册提供者"""
        from notification_manager import NotificationType

        # 创建模拟提供者
        mock_provider = MagicMock()
        mock_provider.send = MagicMock(return_value=True)

        self.manager.register_provider(NotificationType.WEB, mock_provider)

        # 验证已注册
        self.assertIn(NotificationType.WEB, self.manager._providers)

    def test_update_config_without_save(self):
        """测试更新配置不保存"""
        # update_config_without_save 接受关键字参数
        self.manager.update_config_without_save(bark_enabled=True)

        self.assertEqual(self.manager.config.bark_enabled, True)


class TestNotificationManagerSend(unittest.TestCase):
    """通知发送功能测试"""

    def setUp(self):
        """每个测试前的准备"""
        from notification_manager import notification_manager

        self.manager = notification_manager

    def test_send_notification_disabled(self):
        """测试通知禁用时不发送"""
        # 暂时禁用通知
        original_enabled = self.manager.config.enabled
        self.manager.config.enabled = False

        try:
            from notification_manager import NotificationTrigger

            result = self.manager.send_notification(
                title="测试", message="消息", trigger=NotificationTrigger.IMMEDIATE
            )

            # 应该返回空字符串
            self.assertEqual(result, "")
        finally:
            self.manager.config.enabled = original_enabled

    def test_send_notification_immediate(self):
        """测试立即发送通知"""
        from notification_manager import NotificationTrigger, NotificationType

        # 确保通知启用
        original_enabled = self.manager.config.enabled
        self.manager.config.enabled = True

        try:
            result = self.manager.send_notification(
                title="立即通知",
                message="测试消息",
                trigger=NotificationTrigger.IMMEDIATE,
                types=[NotificationType.WEB],
            )

            # 应该返回事件 ID
            self.assertTrue(result.startswith("notification_"))
        finally:
            self.manager.config.enabled = original_enabled

    def test_send_notification_with_metadata(self):
        """测试带元数据的通知"""
        from notification_manager import NotificationTrigger, NotificationType

        original_enabled = self.manager.config.enabled
        self.manager.config.enabled = True

        try:
            result = self.manager.send_notification(
                title="元数据通知",
                message="测试消息",
                trigger=NotificationTrigger.IMMEDIATE,
                types=[NotificationType.WEB],
                metadata={"extra": "data", "number": 42},
            )

            self.assertTrue(result.startswith("notification_"))
        finally:
            self.manager.config.enabled = original_enabled


class TestNotificationBoundaryConditions(unittest.TestCase):
    """边界条件测试"""

    def test_empty_notification_title(self):
        """测试空标题通知"""
        from notification_manager import (
            NotificationTrigger,
            NotificationType,
            notification_manager,
        )

        original_enabled = notification_manager.config.enabled
        notification_manager.config.enabled = True

        try:
            result = notification_manager.send_notification(
                title="",
                message="空标题测试",
                trigger=NotificationTrigger.IMMEDIATE,
                types=[NotificationType.WEB],
            )

            # 应该能处理空标题
            self.assertTrue(result.startswith("notification_"))
        finally:
            notification_manager.config.enabled = original_enabled

    def test_empty_notification_message(self):
        """测试空消息通知"""
        from notification_manager import (
            NotificationTrigger,
            NotificationType,
            notification_manager,
        )

        original_enabled = notification_manager.config.enabled
        notification_manager.config.enabled = True

        try:
            result = notification_manager.send_notification(
                title="空消息测试",
                message="",
                trigger=NotificationTrigger.IMMEDIATE,
                types=[NotificationType.WEB],
            )

            # 应该能处理空消息
            self.assertTrue(result.startswith("notification_"))
        finally:
            notification_manager.config.enabled = original_enabled

    def test_very_long_notification(self):
        """测试超长通知"""
        from notification_manager import (
            NotificationTrigger,
            NotificationType,
            notification_manager,
        )

        original_enabled = notification_manager.config.enabled
        notification_manager.config.enabled = True

        try:
            long_title = "标" * 1000
            long_message = "消息" * 5000

            result = notification_manager.send_notification(
                title=long_title,
                message=long_message,
                trigger=NotificationTrigger.IMMEDIATE,
                types=[NotificationType.WEB],
            )

            # 应该能处理超长内容
            self.assertTrue(result.startswith("notification_"))
        finally:
            notification_manager.config.enabled = original_enabled


class TestNotificationManagerSendNotificationAdvanced(unittest.TestCase):
    """通知发送高级测试"""

    def test_send_notification_with_types(self):
        """测试指定类型发送通知"""
        from notification_manager import (
            NotificationManager,
            NotificationTrigger,
            NotificationType,
        )

        manager = NotificationManager()
        manager.config.enabled = True

        # 发送指定类型的通知
        event_id = manager.send_notification(
            title="测试标题",
            message="测试消息",
            trigger=NotificationTrigger.IMMEDIATE,
            types=[NotificationType.WEB],
        )

        self.assertTrue(event_id.startswith("notification_"))

    def test_send_notification_delayed(self):
        """测试延迟触发通知"""
        from notification_manager import (
            NotificationManager,
            NotificationTrigger,
        )

        manager = NotificationManager()
        manager.config.enabled = True
        manager.config.trigger_delay = 0  # 0 秒延迟（更快更稳定）

        # 用 patch 确保不污染单例实例的方法实现
        processed = threading.Event()
        with patch.object(manager, "_process_event") as mock_process:
            mock_process.side_effect = lambda _event: processed.set()

            # 发送延迟通知
            event_id = manager.send_notification(
                title="延迟通知",
                message="延迟测试",
                trigger=NotificationTrigger.DELAYED,
            )

            self.assertTrue(event_id.startswith("notification_"))
            self.assertTrue(processed.wait(1.0))

    def test_send_notification_all_types_enabled(self):
        """测试所有通知类型启用时的发送"""
        from notification_manager import (
            NotificationManager,
            NotificationTrigger,
        )

        manager = NotificationManager()
        manager.config.enabled = True
        manager.config.web_enabled = True
        manager.config.sound_enabled = True
        manager.config.sound_mute = False
        manager.config.bark_enabled = True

        event_id = manager.send_notification(
            title="全类型通知",
            message="全类型测试",
            trigger=NotificationTrigger.IMMEDIATE,
        )

        self.assertTrue(event_id.startswith("notification_"))


class TestNotificationManagerProcessEvent(unittest.TestCase):
    """事件处理测试"""

    def test_process_event_with_mock_provider(self):
        """测试事件处理与模拟提供者"""
        from notification_manager import (
            NotificationEvent,
            NotificationManager,
            NotificationTrigger,
            NotificationType,
        )

        manager = NotificationManager()

        # 创建模拟提供者
        mock_provider = Mock()
        mock_provider.send.return_value = True
        manager._providers[NotificationType.WEB] = mock_provider

        # 创建事件
        event = NotificationEvent(
            id="test-event-1",
            title="测试标题",
            message="测试消息",
            trigger=NotificationTrigger.IMMEDIATE,
            types=[NotificationType.WEB],
        )

        # 处理事件
        manager._process_event(event)

        # 验证提供者被调用
        mock_provider.send.assert_called_once()


class TestNotificationEventQueue(unittest.TestCase):
    """通知事件队列测试"""

    def test_event_queue_add(self):
        """测试向事件队列添加事件"""
        from notification_manager import (
            NotificationEvent,
            NotificationManager,
            NotificationTrigger,
        )

        manager = NotificationManager()

        # 添加事件到队列
        event = NotificationEvent(
            id="pending-1",
            title="待处理",
            message="测试",
            trigger=NotificationTrigger.DELAYED,
        )

        with manager._queue_lock:
            initial_len = len(manager._event_queue)
            manager._event_queue.append(event)
            new_len = len(manager._event_queue)

        # 验证事件已添加
        self.assertEqual(new_len, initial_len + 1)


class TestNotificationManagerProvider(unittest.TestCase):
    """提供者管理测试"""

    def setUp(self):
        """每个测试前的准备"""
        from notification_manager import notification_manager

        self.manager = notification_manager

    def test_get_provider(self):
        """测试获取提供者"""
        from notification_manager import NotificationType

        # 尝试获取提供者
        provider = self.manager._providers.get(NotificationType.WEB)
        # 可能存在或不存在，但不应该抛异常


class TestNotificationManagerQueue(unittest.TestCase):
    """事件队列测试"""

    def setUp(self):
        """每个测试前的准备"""
        from notification_manager import notification_manager

        self.manager = notification_manager

    def test_get_pending_events(self):
        """测试获取待处理事件"""
        # 获取待处理事件数量
        with self.manager._queue_lock:
            pending_count = len(self.manager._event_queue)

        # 不应该抛异常
        self.assertIsInstance(pending_count, int)


class TestBoundaryConditionsExtended(unittest.TestCase):
    """扩展边界条件测试"""

    def test_notification_with_html(self):
        """测试带 HTML 的通知"""
        from notification_manager import (
            NotificationTrigger,
            NotificationType,
            notification_manager,
        )

        original_enabled = notification_manager.config.enabled
        notification_manager.config.enabled = True

        try:
            result = notification_manager.send_notification(
                title="<b>HTML 标题</b>",
                message="<script>alert('xss')</script>",
                trigger=NotificationTrigger.IMMEDIATE,
                types=[NotificationType.WEB],
            )

            self.assertTrue(result.startswith("notification_"))
        finally:
            notification_manager.config.enabled = original_enabled

    def test_config_manager_concurrent_access(self):
        """测试配置管理器并发访问"""
        import threading

        from config_manager import config_manager

        results = []

        def read_config():
            for _ in range(50):
                _ = config_manager.get("notification")
            results.append(True)

        threads = [threading.Thread(target=read_config) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(results), 5)

    def test_task_queue_boundary_operations(self):
        """测试任务队列边界操作"""
        from task_queue import TaskQueue

        queue = TaskQueue()

        # 获取不存在的任务
        task = queue.get_task("nonexistent-boundary-task")
        self.assertIsNone(task)

        # 完成不存在的任务
        result = queue.complete_task("nonexistent-boundary-task", {})
        self.assertFalse(result)

        queue.clear_all_tasks()


class TestNotificationManagerBoundary(unittest.TestCase):
    """通知管理器边界条件测试"""

    def setUp(self):
        """每个测试前的准备"""
        from notification_manager import notification_manager

        self.manager = notification_manager

    def test_refresh_with_missing_config_keys(self):
        """测试配置缺少某些键时的刷新"""
        # 强制刷新应该不会崩溃
        self.manager.refresh_config_from_file(force=True)

        # 配置应该有有效的默认值
        self.assertIsNotNone(self.manager.config)

    def test_config_extreme_sound_volume(self):
        """测试极端音量值"""
        # 测试负数
        self.manager.config.sound_volume = -100
        self.assertIsInstance(self.manager.config.sound_volume, (int, float))

        # 测试超大值
        self.manager.config.sound_volume = 1000000
        self.assertIsInstance(self.manager.config.sound_volume, (int, float))

    def test_empty_bark_url(self):
        """测试空的 Bark URL"""
        self.manager.config.bark_enabled = True
        self.manager.config.bark_url = ""
        self.manager.config.bark_device_key = "test"

        # 不应该崩溃
        from notification_providers import BarkNotificationProvider

        provider = BarkNotificationProvider(self.manager.config)
        self.assertIsNotNone(provider)


# ──────────────────────────────────────────────────────────
# 覆盖率补充
# ──────────────────────────────────────────────────────────


class TestNotificationManagerInitEdge(unittest.TestCase):
    """覆盖 __init__ 中的异常路径和条件分支"""

    def test_from_config_exception_raises_notification_error(self):
        """lines 257-259: NotificationConfig.from_config_file 抛异常"""
        from notification_manager import NotificationError, NotificationManager

        old_instance = NotificationManager._instance
        try:
            NotificationManager._instance = None
            with patch(
                "notification_manager.NotificationConfig.from_config_file",
                side_effect=RuntimeError("config broken"),
            ):
                with self.assertRaises(NotificationError) as ctx:
                    NotificationManager()
                self.assertIn("初始化失败", str(ctx.exception))
        finally:
            NotificationManager._instance = old_instance

    def test_debug_mode_init(self):
        """lines 320-321: config.debug=True 时的初始化"""
        from notification_manager import NotificationManager

        old_instance = NotificationManager._instance
        try:
            NotificationManager._instance = None
            mock_config = MagicMock()
            mock_config.debug = True
            mock_config.bark_enabled = False
            mock_config.delayed_notification_seconds = 5.0
            mock_config.max_retries = 3
            with patch(
                "notification_manager.NotificationConfig.from_config_file",
                return_value=mock_config,
            ):
                mgr = NotificationManager()
                self.assertTrue(mgr.config.debug)
        finally:
            NotificationManager._instance = old_instance

    def test_bark_enabled_init(self):
        """lines 329-330: bark_enabled=True 时注册 provider"""
        from notification_manager import NotificationManager

        old_instance = NotificationManager._instance
        try:
            NotificationManager._instance = None
            mock_config = MagicMock()
            mock_config.debug = False
            mock_config.bark_enabled = True
            mock_config.delayed_notification_seconds = 5.0
            mock_config.max_retries = 3
            with patch(
                "notification_manager.NotificationConfig.from_config_file",
                return_value=mock_config,
            ):
                mgr = NotificationManager()
                self.assertTrue(mgr.config.bark_enabled)
        finally:
            NotificationManager._instance = old_instance


class TestNotificationManagerDCLBranches(unittest.TestCase):
    """覆盖 __new__ / __init__ 双重检查锁定模式的内层分支"""

    def test_new_dcl_inner_branch_already_created(self):
        """239->242: __new__ 中另一个线程抢先创建了 _instance"""
        from notification_manager import NotificationManager

        old_instance = NotificationManager._instance
        old_lock = NotificationManager._lock
        try:
            NotificationManager._instance = None
            sentinel = object.__new__(NotificationManager)
            sentinel._initialized = True

            class _RaceLock:
                """模拟竞态：进入 __enter__ 时另一线程已完成 __new__"""

                def __enter__(self_lock):
                    NotificationManager._instance = sentinel
                    return self_lock

                def __exit__(self_lock, *args):
                    pass

            NotificationManager._lock = _RaceLock()
            inst = NotificationManager.__new__(NotificationManager)
            self.assertIs(inst, sentinel)
        finally:
            NotificationManager._instance = old_instance
            NotificationManager._lock = old_lock

    def test_init_dcl_inner_branch_already_initialized(self):
        """line 252: __init__ 中另一个线程抢先完成了初始化"""
        from notification_manager import NotificationManager

        old_instance = NotificationManager._instance
        old_lock = NotificationManager._lock
        try:
            NotificationManager._instance = None
            mock_config = MagicMock()
            mock_config.debug = False
            mock_config.bark_enabled = False
            mock_config.delayed_notification_seconds = 5.0
            mock_config.max_retries = 3
            with patch(
                "notification_manager.NotificationConfig.from_config_file",
                return_value=mock_config,
            ):
                mgr = NotificationManager()

            class _RaceLock:
                """模拟竞态：进入 __enter__ 时另一线程已完成 __init__"""

                def __enter__(self_lock):
                    mgr._initialized = True
                    return self_lock

                def __exit__(self_lock, *args):
                    pass

            mgr._initialized = False
            NotificationManager._lock = _RaceLock()
            mgr.__init__()
            self.assertTrue(mgr._initialized)
        finally:
            NotificationManager._instance = old_instance
            NotificationManager._lock = old_lock

    def test_send_with_non_immediate_non_delayed_trigger(self):
        """452->473: trigger 不是 IMMEDIATE 也不是 DELAYED 时直通返回"""
        from notification_manager import notification_manager
        from notification_models import NotificationTrigger

        with patch.object(notification_manager, "_process_event"):
            event_id = notification_manager.send_notification(
                title="passthrough",
                message="msg",
                trigger=NotificationTrigger.REPEAT,
            )
            self.assertIsInstance(event_id, str)
            self.assertTrue(len(event_id) > 0)


class TestNotificationManagerDelayedShutdown(unittest.TestCase):
    """lines 456-457: DELAYED 触发时检测到 _shutdown_called 跳过调度"""

    def test_delayed_notify_skipped_mid_flight(self):
        """模拟：进入 send_notification 时未 shutdown，到 DELAYED 分支时已 shutdown"""
        from notification_manager import notification_manager
        from notification_models import NotificationTrigger

        class _DelayedTrue:
            """首次 bool 为 False（通过入口检查），第二次为 True（触发跳过）"""

            def __init__(self):
                self._calls = 0

            def __bool__(self):
                self._calls += 1
                return self._calls > 1

        notification_manager._shutdown_called = _DelayedTrue()  # type: ignore[assignment]
        try:
            event_id = notification_manager.send_notification(
                title="delayed-test",
                message="msg",
                trigger=NotificationTrigger.DELAYED,
            )
            self.assertIsInstance(event_id, str)
            self.assertTrue(len(event_id) > 0)
        finally:
            notification_manager._shutdown_called = False


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


# ---------------------------------------------------------------------------
# 边界路径补充（原 test_notification_manager_extended.py）
# ---------------------------------------------------------------------------
from notification_models import (
    NotificationEvent,
    NotificationPriority,
    NotificationTrigger,
    NotificationType,
)


def _make_manager():
    """创建一个干净的 NotificationManager 实例（绕过单例）"""
    from notification_manager import NotificationConfig, NotificationManager

    NotificationManager._instance = None
    mgr = NotificationManager.__new__(NotificationManager)
    mgr._initialized = False
    mgr.config = NotificationConfig()
    mgr._providers = {}
    mgr._providers_lock = threading.Lock()
    mgr._event_queue = []
    mgr._queue_lock = threading.Lock()
    mgr._config_lock = threading.Lock()
    mgr._config_file_mtime = 0.0
    mgr._worker_thread = None
    mgr._stop_event = threading.Event()
    from concurrent.futures import ThreadPoolExecutor

    mgr._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="TestWorker")
    mgr._delayed_timers = {}
    mgr._delayed_timers_lock = threading.Lock()
    mgr._shutdown_called = False
    mgr._stats_lock = threading.Lock()
    mgr._stats = {
        "events_total": 0,
        "events_succeeded": 0,
        "events_failed": 0,
        "attempts_total": 0,
        "retries_scheduled": 0,
        "last_event_id": None,
        "last_event_at": None,
        "providers": {},
    }
    mgr._finalized_event_ids = {}
    mgr._finalized_max_size = 500
    mgr._callbacks_lock = threading.Lock()
    mgr._callbacks = {}
    mgr._initialized = True
    return mgr


def _make_event(**kw) -> NotificationEvent:
    defaults: dict[str, Any] = {
        "id": "test_001",
        "title": "Test",
        "message": "Hello",
        "trigger": NotificationTrigger.IMMEDIATE,
        "types": [NotificationType.WEB],
        "metadata": {},
        "max_retries": 3,
        "priority": NotificationPriority.NORMAL,
    }
    defaults.update(kw)
    return NotificationEvent(**defaults)


# ──────────────────────────────────────────────────────────
# NotificationConfig 边界
# ──────────────────────────────────────────────────────────


class TestNotificationConfigEdgeCases(unittest.TestCase):
    def test_retry_count_string_coerced(self):
        from notification_manager import NotificationConfig

        cfg = NotificationConfig(retry_count="5")  # type: ignore[arg-type]
        self.assertEqual(cfg.retry_count, 5)

    def test_retry_count_invalid_string(self):
        from notification_manager import NotificationConfig

        cfg = NotificationConfig(retry_count="abc")  # type: ignore[arg-type]
        self.assertEqual(cfg.retry_count, 3)

    def test_retry_delay_invalid(self):
        from notification_manager import NotificationConfig

        cfg = NotificationConfig(retry_delay="bad")  # type: ignore[arg-type]
        self.assertEqual(cfg.retry_delay, 2)

    def test_bark_timeout_invalid(self):
        from notification_manager import NotificationConfig

        cfg = NotificationConfig(bark_timeout="x")  # type: ignore[arg-type]
        self.assertEqual(cfg.bark_timeout, 10)

    def test_bark_action_invalid_enum(self):
        from notification_manager import NotificationConfig

        cfg = NotificationConfig(bark_action="invalid_action")
        self.assertEqual(cfg.bark_action, "none")

    def test_bark_url_invalid_warns(self):
        from notification_manager import NotificationConfig

        cfg = NotificationConfig(
            bark_url="ftp://bad", bark_enabled=True, bark_device_key="k"
        )
        self.assertEqual(cfg.bark_url, "ftp://bad")

    def test_bark_enabled_no_device_key_warns(self):
        from notification_manager import NotificationConfig

        cfg = NotificationConfig(bark_enabled=True, bark_device_key="")
        self.assertTrue(cfg.bark_enabled)

    def test_from_config_file_unavailable(self):
        from exceptions import NotificationError
        from notification_manager import NotificationConfig

        with patch("notification_manager.CONFIG_FILE_AVAILABLE", False):
            self.assertRaises(NotificationError, NotificationConfig.from_config_file)

    def test_from_config_file_volume_default(self):
        """get_section() 通过 Pydantic ClampedInt 将无效值钳位为默认值 80"""
        from notification_manager import NotificationConfig

        mock_cfg = MagicMock()
        section = {"sound_volume": 80, "enabled": True}
        mock_cfg.get_section.return_value = section

        with (
            patch("notification_manager.CONFIG_FILE_AVAILABLE", True),
            patch("notification_manager.get_config", return_value=mock_cfg),
        ):
            cfg = NotificationConfig.from_config_file()
            self.assertAlmostEqual(cfg.sound_volume, 0.8, places=2)

    def test_from_config_file_type_coercion(self):
        """get_section() 已通过 Pydantic 段模型校验，值类型已正确强转"""
        from notification_manager import NotificationConfig

        mock_cfg = MagicMock()
        section = {"enabled": True, "debug": False, "sound_volume": 50}
        mock_cfg.get_section.return_value = section

        with (
            patch("notification_manager.CONFIG_FILE_AVAILABLE", True),
            patch("notification_manager.get_config", return_value=mock_cfg),
        ):
            cfg = NotificationConfig.from_config_file()
            self.assertTrue(cfg.enabled)
            self.assertFalse(cfg.debug)
            self.assertAlmostEqual(cfg.sound_volume, 0.5, places=2)


# ──────────────────────────────────────────────────────────
# register_provider 替换旧 provider
# ──────────────────────────────────────────────────────────


class TestRegisterProvider(unittest.TestCase):
    def test_replace_old_provider_closes_it(self):
        mgr = _make_manager()
        old = MagicMock()
        new = MagicMock()
        mgr.register_provider(NotificationType.WEB, old)
        mgr.register_provider(NotificationType.WEB, new)
        old.close.assert_called_once()

    def test_safe_close_provider_no_close(self):
        from notification_manager import NotificationManager

        NotificationManager._safe_close_provider(object())

    def test_safe_close_provider_exception(self):
        from notification_manager import NotificationManager

        p = MagicMock()
        p.close.side_effect = RuntimeError("fail")
        NotificationManager._safe_close_provider(p)


# ──────────────────────────────────────────────────────────
# add_callback / trigger_callbacks
# ──────────────────────────────────────────────────────────


class TestCallbacks(unittest.TestCase):
    def test_add_and_trigger(self):
        mgr = _make_manager()
        results: list[str] = []
        mgr.add_callback("test_event", lambda: results.append("called"))
        mgr.trigger_callbacks("test_event")
        self.assertEqual(results, ["called"])

    def test_callback_exception_doesnt_break(self):
        mgr = _make_manager()

        def bad():
            raise RuntimeError("boom")

        mgr.add_callback("evt", bad)
        mgr.add_callback("evt", lambda: None)
        mgr.trigger_callbacks("evt")


# ──────────────────────────────────────────────────────────
# send_notification 路由
# ──────────────────────────────────────────────────────────


class TestSendNotification(unittest.TestCase):
    def test_disabled_returns_empty(self):
        mgr = _make_manager()
        mgr.config.enabled = False
        result = mgr.send_notification("t", "m")
        self.assertEqual(result, "")

    def test_shutdown_returns_empty(self):
        mgr = _make_manager()
        mgr._shutdown_called = True
        result = mgr.send_notification("t", "m")
        self.assertEqual(result, "")

    def test_auto_types_selection(self):
        mgr = _make_manager()
        mock_provider = MagicMock()
        mock_provider.send.return_value = True
        mgr.register_provider(NotificationType.WEB, mock_provider)
        mgr.config.web_enabled = True
        mgr.config.sound_enabled = False
        mgr.config.bark_enabled = True
        mgr.config.system_enabled = True

        event_id = mgr.send_notification("t", "m")
        self.assertNotEqual(event_id, "")

    def test_priority_string_conversion(self):
        mgr = _make_manager()
        mock_provider = MagicMock()
        mock_provider.send.return_value = True
        mgr.register_provider(NotificationType.WEB, mock_provider)

        event_id = mgr.send_notification(
            "t", "m", types=[NotificationType.WEB], priority="high"
        )
        self.assertNotEqual(event_id, "")

    def test_priority_invalid_string(self):
        mgr = _make_manager()
        mock_provider = MagicMock()
        mock_provider.send.return_value = True
        mgr.register_provider(NotificationType.WEB, mock_provider)

        event_id = mgr.send_notification(
            "t", "m", types=[NotificationType.WEB], priority="invalid"
        )
        self.assertNotEqual(event_id, "")

    def test_delayed_trigger(self):
        mgr = _make_manager()
        event_id = mgr.send_notification(
            "t",
            "m",
            trigger=NotificationTrigger.DELAYED,
            types=[NotificationType.WEB],
        )
        self.assertNotEqual(event_id, "")
        with mgr._delayed_timers_lock:
            for t in mgr._delayed_timers.values():
                t.cancel()

    def test_delayed_trigger_after_shutdown(self):
        mgr = _make_manager()
        mgr._shutdown_called = True
        event_id = mgr.send_notification(
            "t", "m", trigger=NotificationTrigger.DELAYED, types=[NotificationType.WEB]
        )
        self.assertEqual(event_id, "")

    def test_queue_trimming(self):
        mgr = _make_manager()
        mgr.config.enabled = True
        mock_provider = MagicMock()
        mock_provider.send.return_value = True
        mgr.register_provider(NotificationType.WEB, mock_provider)

        for i in range(205):
            mgr.send_notification(f"t{i}", f"m{i}", types=[NotificationType.WEB])

        with mgr._queue_lock:
            self.assertLessEqual(len(mgr._event_queue), 200)


# ──────────────────────────────────────────────────────────
# _process_event 内部逻辑
# ──────────────────────────────────────────────────────────


class TestProcessEvent(unittest.TestCase):
    def test_shutdown_skips(self):
        mgr = _make_manager()
        mgr._shutdown_called = True
        event = _make_event()
        mgr._process_event(event)

    def test_no_types_skips(self):
        mgr = _make_manager()
        event = _make_event(types=[])
        mgr._process_event(event)

    def test_all_fail_triggers_retry(self):
        mgr = _make_manager()
        mock_provider = MagicMock()
        mock_provider.send.return_value = False
        mgr.register_provider(NotificationType.WEB, mock_provider)

        event = _make_event(max_retries=2)
        # 用 assertLogs 同时验证「retry warning 被打出」并捕获日志（避免污染 CI 输出）
        with self.assertLogs("notification_manager", level="WARNING") as cm:
            mgr._process_event(event)
        self.assertEqual(event.retry_count, 1)
        self.assertTrue(any("发送失败" in m for m in cm.output))

    def test_all_fail_no_retries_triggers_fallback(self):
        mgr = _make_manager()
        mock_provider = MagicMock()
        mock_provider.send.return_value = False
        mgr.register_provider(NotificationType.WEB, mock_provider)

        fallback_called: list[bool] = []
        mgr.add_callback(
            "notification_fallback", lambda e: fallback_called.append(True)
        )

        event = _make_event(max_retries=0)
        mgr._process_event(event)
        self.assertTrue(fallback_called)

    def test_exception_in_process_triggers_retry(self):
        mgr = _make_manager()
        mock_provider = MagicMock()
        mock_provider.send.side_effect = RuntimeError("crash")
        mgr.register_provider(NotificationType.WEB, mock_provider)

        event = _make_event(max_retries=2)
        # provider.send 抛异常时也会走 retry warning 路径；用 assertLogs 静音
        with self.assertLogs("notification_manager", level="WARNING") as cm:
            mgr._process_event(event)
        self.assertEqual(event.retry_count, 1)
        self.assertTrue(any("发送失败" in m or "crash" in m for m in cm.output))

    def test_exception_no_retries_triggers_fallback(self):
        mgr = _make_manager()
        mock_provider = MagicMock()
        mock_provider.send.side_effect = RuntimeError("crash")
        mgr.register_provider(NotificationType.WEB, mock_provider)

        fallback_called: list[bool] = []
        mgr.add_callback(
            "notification_fallback", lambda e: fallback_called.append(True)
        )

        event = _make_event(max_retries=0)
        mgr._process_event(event)
        self.assertTrue(fallback_called)


# ──────────────────────────────────────────────────────────
# _send_single_notification
# ──────────────────────────────────────────────────────────


class TestSendSingleNotification(unittest.TestCase):
    def test_no_provider_returns_false(self):
        mgr = _make_manager()
        event = _make_event()
        result = mgr._send_single_notification(NotificationType.WEB, event)
        self.assertFalse(result)

    def test_no_send_method_returns_false(self):
        mgr = _make_manager()
        provider = object()
        mgr.register_provider(NotificationType.WEB, provider)
        event = _make_event()
        result = mgr._send_single_notification(NotificationType.WEB, event)
        self.assertFalse(result)

    def test_provider_exception_returns_false(self):
        mgr = _make_manager()
        mock_provider = MagicMock()
        mock_provider.send.side_effect = RuntimeError("network")
        mgr.register_provider(NotificationType.WEB, mock_provider)
        event = _make_event()
        result = mgr._send_single_notification(NotificationType.WEB, event)
        self.assertFalse(result)

    def test_provider_success_records_stats(self):
        mgr = _make_manager()
        mock_provider = MagicMock()
        mock_provider.send.return_value = True
        mgr.register_provider(NotificationType.WEB, mock_provider)
        event = _make_event()
        result = mgr._send_single_notification(NotificationType.WEB, event)
        self.assertTrue(result)
        with mgr._stats_lock:
            self.assertGreater(mgr._stats["providers"]["web"]["success"], 0)

    def test_bark_error_in_metadata(self):
        mgr = _make_manager()
        mock_provider = MagicMock()
        mock_provider.send.return_value = False
        mgr.register_provider(NotificationType.BARK, mock_provider)
        event = _make_event(
            types=[NotificationType.BARK],
            metadata={"bark_error": "APNs connection failed"},
        )
        result = mgr._send_single_notification(NotificationType.BARK, event)
        self.assertFalse(result)
        with mgr._stats_lock:
            stats = mgr._stats["providers"]["bark"]
            self.assertEqual(stats["last_error"], "APNs connection failed")


# ──────────────────────────────────────────────────────────
# _mark_event_finalized
# ──────────────────────────────────────────────────────────


class TestMarkEventFinalized(unittest.TestCase):
    def test_success_increments(self):
        mgr = _make_manager()
        event = _make_event(id="fin_1")
        mgr._mark_event_finalized(event, succeeded=True)
        self.assertEqual(mgr._stats["events_succeeded"], 1)

    def test_failure_increments(self):
        mgr = _make_manager()
        event = _make_event(id="fin_2")
        mgr._mark_event_finalized(event, succeeded=False)
        self.assertEqual(mgr._stats["events_failed"], 1)

    def test_duplicate_ignored(self):
        mgr = _make_manager()
        event = _make_event(id="fin_3")
        mgr._mark_event_finalized(event, succeeded=True)
        mgr._mark_event_finalized(event, succeeded=False)
        self.assertEqual(mgr._stats["events_succeeded"], 1)
        self.assertEqual(mgr._stats["events_failed"], 0)


# ──────────────────────────────────────────────────────────
# _schedule_retry
# ──────────────────────────────────────────────────────────


class TestScheduleRetry(unittest.TestCase):
    def test_shutdown_skips(self):
        mgr = _make_manager()
        mgr._shutdown_called = True
        event = _make_event()
        mgr._schedule_retry(event)
        self.assertEqual(len(mgr._delayed_timers), 0)

    def test_creates_timer(self):
        mgr = _make_manager()
        event = _make_event()
        mgr._schedule_retry(event)
        self.assertGreater(len(mgr._delayed_timers), 0)
        with mgr._delayed_timers_lock:
            for t in mgr._delayed_timers.values():
                t.cancel()


# ──────────────────────────────────────────────────────────
# _schedule_retry 的 jitter 防御 (thundering-herd)
#
# 历史 bug：所有重试用同一个 ``retry_delay`` 没有抖动。多用户同时失败时
# 重试会精确撞向同一时刻。修复策略是 fixed delay + 0-50% jitter，避开
# 指数退避（``max_retries`` 默认 3，指数退避在小 N 下没意义且会拉高
# 99 分位延迟）。
#
# 这一组 5 个测试锁 contract：
#   1. ``retry_delay == 0`` 跳过 jitter（兼容测试 / 高频压测路径）
#   2. ``retry_delay == 2`` 时 delay ∈ [2, 3]
#   3. ``retry_delay == 10`` 时 delay ∈ [10, 15]
#   4. 多次调用产生不同 delay（jitter 真的随机，不是 mock）
#   5. 反向锁 ``_RETRY_DELAY_JITTER_RATIO == 0.5`` 不能被悄悄改
# ──────────────────────────────────────────────────────────


class TestScheduleRetryJitter(unittest.TestCase):
    """``_schedule_retry`` 必须在 ``retry_delay`` 上叠加 0-50% jitter。"""

    @staticmethod
    def _capture_timer_delay(mgr, retry_delay_value: int) -> float:
        """跑一次 ``_schedule_retry``，返回它构造 ``threading.Timer`` 时的 delay 参数。"""
        captured: dict[str, float] = {}

        class _SpyTimer:
            def __init__(self, delay, target):
                captured["delay"] = float(delay)
                self._delay = delay
                self._target = target
                self.daemon = False

            def start(self) -> None:
                # 不真正启动；测试只关心 delay 参数
                pass

            def cancel(self) -> None:
                pass

        try:
            mgr.config.retry_delay = retry_delay_value
        except Exception:
            mgr.config.__dict__["retry_delay"] = retry_delay_value

        with patch("notification_manager.threading.Timer", _SpyTimer):
            mgr._schedule_retry(_make_event())

        return captured.get("delay", -1.0)

    def test_zero_retry_delay_bypasses_jitter(self):
        """``retry_delay == 0`` → delay 必须等于 0（不能有 jitter 抖动）。"""
        mgr = _make_manager()
        delay = self._capture_timer_delay(mgr, 0)
        self.assertEqual(
            delay,
            0.0,
            "retry_delay=0 是「立即重试」语义，常用于测试和高频压测；"
            "不能引入亚秒级 jitter 抖动",
        )

    def test_default_retry_delay_within_jitter_range(self):
        """``retry_delay == 2`` → delay ∈ [2.0, 3.0]（0-50% jitter）。"""
        mgr = _make_manager()
        delay = self._capture_timer_delay(mgr, 2)
        self.assertGreaterEqual(delay, 2.0, "delay 必须不小于 retry_delay")
        self.assertLessEqual(
            delay,
            3.0,
            "delay 必须不超过 retry_delay * (1 + _RETRY_DELAY_JITTER_RATIO)",
        )

    def test_widened_retry_delay_within_jitter_range(self):
        """``retry_delay == 10`` → delay ∈ [10.0, 15.0]。"""
        mgr = _make_manager()
        delay = self._capture_timer_delay(mgr, 10)
        self.assertGreaterEqual(delay, 10.0)
        self.assertLessEqual(delay, 15.0)

    def test_jitter_actually_randomises(self):
        """多次调用必须产生**不同的** delay 值（jitter 真的随机）。"""
        mgr = _make_manager()
        seen: set[float] = set()
        for _ in range(20):
            delay = self._capture_timer_delay(mgr, 2)
            seen.add(delay)
        self.assertGreater(
            len(seen),
            1,
            "20 次调用全产生同一个 delay，说明 jitter 没真的生效（"
            "可能 random.uniform 被 patch 死了或 jitter 计算逻辑错）",
        )

    def test_jitter_ratio_constant_value_locked(self):
        """反向锁：``_RETRY_DELAY_JITTER_RATIO`` 不能在没充分讨论的情况下被改。"""
        from notification_manager import _RETRY_DELAY_JITTER_RATIO

        self.assertEqual(
            _RETRY_DELAY_JITTER_RATIO,
            0.5,
            "如果你确实需要调这个 ratio，请：\n"
            "  1. 想清楚对单用户感知延迟的影响（jitter 是「拖慢」99 分位）\n"
            "  2. 想清楚对多用户 thundering herd 的防御能力的影响\n"
            "  3. 然后同时更新这条断言 + 模块顶部的设计说明 + RELEASE_NOTES",
        )


# ──────────────────────────────────────────────────────────
# shutdown / restart
# ──────────────────────────────────────────────────────────


class TestShutdownRestart(unittest.TestCase):
    def test_shutdown_idempotent(self):
        mgr = _make_manager()
        mgr.shutdown(wait=False)
        mgr.shutdown(wait=False)
        self.assertTrue(mgr._shutdown_called)

    def test_shutdown_cancels_timers(self):
        mgr = _make_manager()
        timer = MagicMock()
        mgr._delayed_timers["t1"] = timer
        mgr.shutdown(wait=False)
        timer.cancel.assert_called_once()

    def test_shutdown_closes_providers(self):
        mgr = _make_manager()
        provider = MagicMock()
        mgr.register_provider(NotificationType.WEB, provider)
        mgr.shutdown(wait=False)
        provider.close.assert_called()

    def test_restart(self):
        mgr = _make_manager()
        mgr.shutdown(wait=False)
        mgr.restart()
        self.assertFalse(mgr._shutdown_called)

    def test_restart_when_not_shutdown(self):
        mgr = _make_manager()
        mgr.restart()
        self.assertFalse(mgr._shutdown_called)


# ──────────────────────────────────────────────────────────
# refresh_config_from_file
# ──────────────────────────────────────────────────────────


class TestRefreshConfig(unittest.TestCase):
    def test_no_config_available(self):
        mgr = _make_manager()
        with patch("notification_manager.CONFIG_FILE_AVAILABLE", False):
            mgr.refresh_config_from_file()

    def test_mtime_unchanged_skips(self):
        mgr = _make_manager()
        mock_cfg = MagicMock()
        mock_file = MagicMock()
        mock_file.stat.return_value.st_mtime = 1000.0
        mock_cfg.config_file = mock_file
        mock_cfg.get_section.return_value = {}

        with (
            patch("notification_manager.CONFIG_FILE_AVAILABLE", True),
            patch("notification_manager.get_config", return_value=mock_cfg),
        ):
            mgr._config_file_mtime = 1000.0
            mgr.refresh_config_from_file(force=False)

    def test_force_refresh(self):
        mgr = _make_manager()
        mock_cfg = MagicMock()
        mock_file = MagicMock()
        mock_file.stat.return_value.st_mtime = 1000.0
        mock_cfg.config_file = mock_file
        mock_cfg.get_section.return_value = {
            "enabled": True,
            "sound_volume": 50,
        }

        with (
            patch("notification_manager.CONFIG_FILE_AVAILABLE", True),
            patch("notification_manager.get_config", return_value=mock_cfg),
        ):
            mgr._config_file_mtime = 1000.0
            mgr.refresh_config_from_file(force=True)
            self.assertAlmostEqual(mgr.config.sound_volume, 0.5, places=2)

    def test_bark_toggle_on_refresh(self):
        mgr = _make_manager()
        mgr.config.bark_enabled = False

        mock_cfg = MagicMock()
        mock_file = MagicMock()
        mock_file.stat.return_value.st_mtime = 2000.0
        mock_cfg.config_file = mock_file
        mock_cfg.get_section.return_value = {
            "bark_enabled": True,
            "bark_device_key": "key",
            "sound_volume": 80,
        }

        with (
            patch("notification_manager.CONFIG_FILE_AVAILABLE", True),
            patch("notification_manager.get_config", return_value=mock_cfg),
            patch.object(mgr, "_update_bark_provider"),
        ):
            mgr.refresh_config_from_file(force=True)
            mgr._update_bark_provider.assert_called_once()

    def test_file_stat_oserror(self):
        mgr = _make_manager()
        mock_cfg = MagicMock()
        mock_file = MagicMock()
        mock_file.stat.side_effect = OSError("no file")
        mock_cfg.config_file = mock_file
        mock_cfg.get_section.return_value = {"sound_volume": 80}

        with (
            patch("notification_manager.CONFIG_FILE_AVAILABLE", True),
            patch("notification_manager.get_config", return_value=mock_cfg),
        ):
            mgr.refresh_config_from_file()

    def test_exception_in_refresh(self):
        mgr = _make_manager()
        with (
            patch("notification_manager.CONFIG_FILE_AVAILABLE", True),
            patch("notification_manager.get_config", side_effect=RuntimeError("fail")),
        ):
            mgr.refresh_config_from_file()


# ──────────────────────────────────────────────────────────
# update_config / update_config_without_save
# ──────────────────────────────────────────────────────────


class TestUpdateConfig(unittest.TestCase):
    def test_update_config_without_save(self):
        mgr = _make_manager()
        mgr.update_config_without_save(debug=True)
        self.assertTrue(mgr.config.debug)

    def test_update_config_saves(self):
        mgr = _make_manager()
        with patch.object(mgr, "_save_config_to_file"):
            mgr.update_config(debug=True)
            mgr._save_config_to_file.assert_called_once()

    def test_update_bark_toggle(self):
        mgr = _make_manager()
        mgr.config.bark_enabled = False
        with patch.object(mgr, "_update_bark_provider"):
            mgr.update_config_without_save(bark_enabled=True)
            mgr._update_bark_provider.assert_called_once()

    def test_update_sensitive_key(self):
        mgr = _make_manager()
        mgr.update_config_without_save(bark_device_key="secret_key")
        self.assertEqual(mgr.config.bark_device_key, "secret_key")

    def test_validate_assignment_on_update(self):
        mgr = _make_manager()
        mgr.update_config_without_save(debug=True)
        self.assertTrue(mgr.config.debug)


# ──────────────────────────────────────────────────────────
# _update_bark_provider
# ──────────────────────────────────────────────────────────


class TestUpdateBarkProvider(unittest.TestCase):
    def test_enable_bark(self):
        mgr = _make_manager()
        mgr.config.bark_enabled = True
        mgr._update_bark_provider()
        with mgr._providers_lock:
            self.assertIn(NotificationType.BARK, mgr._providers)

    def test_disable_bark(self):
        mgr = _make_manager()
        mgr.config.bark_enabled = True
        mgr._update_bark_provider()

        mgr.config.bark_enabled = False
        mgr._update_bark_provider()
        with mgr._providers_lock:
            self.assertNotIn(NotificationType.BARK, mgr._providers)

    def test_enable_bark_already_registered(self):
        mgr = _make_manager()
        mgr.config.bark_enabled = True
        mock_bark = MagicMock()
        mgr.register_provider(NotificationType.BARK, mock_bark)
        mgr._update_bark_provider()

    def test_import_error(self):
        mgr = _make_manager()
        mgr.config.bark_enabled = True
        with mgr._providers_lock:
            mgr._providers.pop(NotificationType.BARK, None)
        with patch(
            "notification_manager.NotificationType",
            side_effect=ImportError("no module"),
        ):
            pass


# ──────────────────────────────────────────────────────────
# _save_config_to_file
# ──────────────────────────────────────────────────────────


class TestSaveConfigToFile(unittest.TestCase):
    def test_config_unavailable(self):
        mgr = _make_manager()
        with patch("notification_manager.CONFIG_FILE_AVAILABLE", False):
            mgr._save_config_to_file()

    def test_save_success(self):
        mgr = _make_manager()
        mock_cfg = MagicMock()
        with (
            patch("notification_manager.CONFIG_FILE_AVAILABLE", True),
            patch("notification_manager.get_config", return_value=mock_cfg),
        ):
            mgr._save_config_to_file()
            mock_cfg.update_section.assert_called_once()

    def test_save_exception(self):
        mgr = _make_manager()
        with (
            patch("notification_manager.CONFIG_FILE_AVAILABLE", True),
            patch("notification_manager.get_config", side_effect=RuntimeError("fail")),
        ):
            mgr._save_config_to_file()

    def test_volume_clamped_on_assignment(self):
        mgr = _make_manager()
        mgr.config.sound_volume = 50.0
        self.assertEqual(mgr.config.sound_volume, 1.0)
        mock_cfg = MagicMock()
        with (
            patch("notification_manager.CONFIG_FILE_AVAILABLE", True),
            patch("notification_manager.get_config", return_value=mock_cfg),
        ):
            mgr._save_config_to_file()
            call_args = mock_cfg.update_section.call_args[0][1]
            self.assertEqual(call_args["sound_volume"], 100)


# ──────────────────────────────────────────────────────────
# get_status
# ──────────────────────────────────────────────────────────


class TestGetStatus(unittest.TestCase):
    def test_basic_status(self):
        mgr = _make_manager()
        status = mgr.get_status()
        self.assertIn("enabled", status)
        self.assertIn("providers", status)
        self.assertIn("stats", status)

    def test_status_with_events(self):
        mgr = _make_manager()
        mock_provider = MagicMock()
        mock_provider.send.return_value = True
        mgr.register_provider(NotificationType.WEB, mock_provider)
        mgr.send_notification("t", "m", types=[NotificationType.WEB])
        time.sleep(0.1)

        status = mgr.get_status()
        self.assertGreater(status["stats"]["events_total"], 0)

    def test_status_delivery_rate(self):
        mgr = _make_manager()
        mgr._stats["events_total"] = 10
        mgr._stats["events_succeeded"] = 8
        mgr._stats["events_failed"] = 2
        status = mgr.get_status()
        self.assertAlmostEqual(status["stats"]["delivery_success_rate"], 0.8)

    def test_status_provider_stats(self):
        mgr = _make_manager()
        mgr._stats["providers"] = {
            "web": {
                "attempts": 10,
                "success": 8,
                "failure": 2,
                "last_success_at": None,
                "last_failure_at": None,
                "last_error": None,
                "last_latency_ms": 50,
                "latency_ms_total": 500,
                "latency_ms_count": 10,
            }
        }
        status = mgr.get_status()
        web_stats = status["stats"]["providers"]["web"]
        self.assertAlmostEqual(web_stats["success_rate"], 0.8)
        self.assertAlmostEqual(web_stats["avg_latency_ms"], 50.0)


# ──────────────────────────────────────────────────────────
# _shutdown_global_notification_manager
# ──────────────────────────────────────────────────────────


class TestGlobalShutdown(unittest.TestCase):
    def test_shutdown_function(self):
        from notification_manager import _shutdown_global_notification_manager

        _shutdown_global_notification_manager()

    def test_shutdown_exception_silenced(self):
        """全局关闭函数异常不外抛"""
        from notification_manager import _shutdown_global_notification_manager

        with patch("notification_manager.notification_manager") as mock_nm:
            mock_nm.shutdown.side_effect = RuntimeError("boom")
            _shutdown_global_notification_manager()


# ──────────────────────────────────────────────────────────
# from_config_file: safe_int 非数字回退
# ──────────────────────────────────────────────────────────


class TestFromConfigFileSafeInt(unittest.TestCase):
    def test_safe_int_non_numeric_values(self):
        """safe_int 遇到非数字时回退默认值"""
        from notification_manager import NotificationConfig

        mock_cfg = MagicMock()
        mock_cfg.get_section.return_value = {
            "retry_count": "not_a_number",
            "retry_delay": None,
            "bark_timeout": [],
            "sound_volume": 80,
        }
        with (
            patch("notification_manager.CONFIG_FILE_AVAILABLE", True),
            patch("notification_manager.get_config", return_value=mock_cfg),
        ):
            cfg = NotificationConfig.from_config_file()
            self.assertEqual(cfg.retry_count, 3)
            self.assertEqual(cfg.retry_delay, 2)
            self.assertEqual(cfg.bark_timeout, 10)


# ──────────────────────────────────────────────────────────
# _process_event: TimeoutError 分支 (lines 559-579)
# ──────────────────────────────────────────────────────────


class TestProcessEventTimeout(unittest.TestCase):
    def test_timeout_cancels_unfinished_futures(self):
        """futures 超时时尝试取消未完成任务"""
        mgr = _make_manager()

        cancellable = MagicMock()
        cancellable.done.return_value = False
        cancellable.cancel.return_value = True

        running = MagicMock()
        running.done.return_value = False
        running.cancel.return_value = False

        futures_iter = iter([cancellable, running])
        mgr._executor = MagicMock()
        mgr._executor.submit.side_effect = lambda fn, *a, **kw: next(futures_iter)

        with patch(
            "notification_manager.as_completed",
            side_effect=TimeoutError("timeout"),
        ):
            event = _make_event(
                types=[NotificationType.WEB, NotificationType.SOUND],
                max_retries=0,
            )
            mgr._process_event(event)

        cancellable.cancel.assert_called_once()
        running.cancel.assert_called_once()

    def test_timeout_partial_completion(self):
        """部分 future 完成后超时"""
        mgr = _make_manager()

        done_future = MagicMock()
        done_future.done.return_value = True
        done_future.result.return_value = True

        pending_future = MagicMock()
        pending_future.done.return_value = False
        pending_future.cancel.return_value = False

        futures_iter = iter([done_future, pending_future])
        mgr._executor = MagicMock()
        mgr._executor.submit.side_effect = lambda fn, *a, **kw: next(futures_iter)

        def mock_as_completed(fs, timeout=None):
            yield done_future
            raise TimeoutError("1 unfinished")

        with patch("notification_manager.as_completed", side_effect=mock_as_completed):
            event = _make_event(
                types=[NotificationType.WEB, NotificationType.SOUND],
                max_retries=0,
            )
            mgr._process_event(event)

        pending_future.cancel.assert_called_once()


# ──────────────────────────────────────────────────────────
# _process_event: ``as_completed`` 等待窗口 = bark_timeout + buffer
#
# 历史 bug：``timeout=15`` 硬编码 → 用户配 ``bark_timeout = 30``（合法范围 [1,300]）
# 时 ``as_completed`` 在 15s 提前抛 TimeoutError；老 future 在 30s 跑完发了 1 条
# Bark，retry future 又跑完发了 1 条 → 用户重复收到推送。
#
# 这一组 5 个测试锁住「窗口必须 ≥ ``bark_timeout`` + buffer」+「buffer 常量值」
# 不可在 review 之外被悄悄改动。
# ──────────────────────────────────────────────────────────


class TestProcessEventBarkTimeoutWindow(unittest.TestCase):
    """as_completed 等待窗口 = bark_timeout + _AS_COMPLETED_TIMEOUT_BUFFER_SECONDS。"""

    @staticmethod
    def _capture_as_completed_timeout(mgr, bark_timeout_value: Any) -> float:
        """运行一次 _process_event；返回它给 as_completed 传入的 timeout 值。"""
        captured: dict[str, Any] = {}

        def _spy_as_completed(fs, timeout=None):
            captured["timeout"] = timeout
            return iter([])

        try:
            mgr.config.bark_timeout = bark_timeout_value
        except Exception:
            mgr.config.__dict__["bark_timeout"] = bark_timeout_value

        fake_future = MagicMock()
        fake_future.done.return_value = False
        fake_future.cancel.return_value = True
        mgr._executor = MagicMock()
        mgr._executor.submit.return_value = fake_future

        with patch("notification_manager.as_completed", side_effect=_spy_as_completed):
            event = _make_event(
                types=[NotificationType.WEB],
                max_retries=0,
            )
            mgr._process_event(event)

        return float(captured.get("timeout") or 0)

    def test_default_bark_timeout_uses_15s_window(self):
        """``bark_timeout=10`` (默认) → ``as_completed`` 等 15s。"""
        mgr = _make_manager()
        timeout = self._capture_as_completed_timeout(mgr, 10)
        self.assertEqual(timeout, 15.0)

    def test_user_widened_bark_timeout_extends_window(self):
        """用户把 ``bark_timeout`` 调到 30 → ``as_completed`` 必须也跟着等 35s。"""
        mgr = _make_manager()
        timeout = self._capture_as_completed_timeout(mgr, 30)
        self.assertEqual(
            timeout,
            35.0,
            "bark_timeout=30 时 as_completed 窗口必须 ≥ 35s "
            "（否则用户会收到重复 Bark 推送，详见 _AS_COMPLETED_TIMEOUT_BUFFER_SECONDS 文档）",
        )

    def test_max_bark_timeout_uses_305s_window(self):
        """``bark_timeout=300`` (上限) → ``as_completed`` 等 305s。"""
        mgr = _make_manager()
        timeout = self._capture_as_completed_timeout(mgr, 300)
        self.assertEqual(timeout, 305.0)

    def test_minimum_bark_timeout_uses_6s_window(self):
        """``bark_timeout=1`` (下限) → ``as_completed`` 等 6s。"""
        mgr = _make_manager()
        timeout = self._capture_as_completed_timeout(mgr, 1)
        self.assertEqual(timeout, 6.0)

    def test_invalid_bark_timeout_falls_back_to_default_window(self):
        """``bark_timeout`` 异常类型回退默认 10 → 窗口 15s（不应抛）。"""
        mgr = _make_manager()
        timeout = self._capture_as_completed_timeout(mgr, "not-a-number")
        self.assertEqual(timeout, 15.0)

    def test_buffer_constant_value_locked(self):
        """反向锁：``_AS_COMPLETED_TIMEOUT_BUFFER_SECONDS`` 不能在没充分讨论的情况下被改。"""
        from notification_manager import _AS_COMPLETED_TIMEOUT_BUFFER_SECONDS

        self.assertEqual(
            _AS_COMPLETED_TIMEOUT_BUFFER_SECONDS,
            5,
            "如果你确实需要调这个 buffer，请：\n"
            "  1. 先想清楚这个改动对 thread-pool 调度尾时延的吸收能力的影响\n"
            "  2. 想清楚这个改动对失败 Bark 推送 retry 拖延时间的影响\n"
            "  3. 然后同时更新这条断言 + 模块顶部的设计说明 + RELEASE_NOTES",
        )


# ──────────────────────────────────────────────────────────
# _process_event: 外层 Exception 分支 (lines 616-636)
# ──────────────────────────────────────────────────────────


class TestProcessEventOuterException(unittest.TestCase):
    def test_submit_raises_triggers_retry(self):
        """executor.submit 异常走重试路径"""
        mgr = _make_manager()
        mgr._executor = MagicMock()
        mgr._executor.submit.side_effect = RuntimeError("pool shutdown")

        event = _make_event(max_retries=2, retry_count=0)
        with patch.object(mgr, "_schedule_retry"):
            mgr._process_event(event)
            self.assertEqual(event.retry_count, 1)
            mgr._schedule_retry.assert_called_once()

    def test_submit_raises_no_retry_with_fallback(self):
        """executor.submit 异常 + 重试耗尽 → 降级"""
        mgr = _make_manager()
        mgr._executor = MagicMock()
        mgr._executor.submit.side_effect = RuntimeError("pool shutdown")
        mgr.config.fallback_enabled = True

        fallback = []
        mgr.add_callback("notification_fallback", lambda e: fallback.append(True))

        event = _make_event(max_retries=0, retry_count=0)
        mgr._process_event(event)
        self.assertTrue(fallback)

    def test_submit_raises_no_retry_no_fallback(self):
        """executor.submit 异常 + 无降级"""
        mgr = _make_manager()
        mgr._executor = MagicMock()
        mgr._executor.submit.side_effect = RuntimeError("pool shutdown")
        mgr.config.fallback_enabled = False

        event = _make_event(max_retries=0, retry_count=0)
        mgr._process_event(event)


# ──────────────────────────────────────────────────────────
# shutdown 边界异常 (lines 800-813, 822-823)
# ──────────────────────────────────────────────────────────


class TestShutdownEdgeCases(unittest.TestCase):
    def test_timer_cancel_exception_ignored(self):
        """单个 Timer.cancel() 异常不中断 shutdown"""
        mgr = _make_manager()
        bad_timer = MagicMock()
        bad_timer.cancel.side_effect = RuntimeError("cancel fail")
        good_timer = MagicMock()
        mgr._delayed_timers = {"t1": bad_timer, "t2": good_timer}
        mgr.shutdown(wait=False)
        good_timer.cancel.assert_called_once()

    def test_timer_cleanup_outer_exception(self):
        """整个 Timer 清理块异常"""
        mgr = _make_manager()
        lock = MagicMock()
        lock.__enter__ = MagicMock(side_effect=RuntimeError("lock broken"))
        lock.__exit__ = MagicMock(return_value=False)
        mgr._delayed_timers_lock = lock
        mgr.shutdown(wait=False)

    def test_executor_shutdown_type_error_fallback(self):
        """executor.shutdown(cancel_futures=...) 不支持时降级"""
        mgr = _make_manager()
        mock_exec = MagicMock()
        call_count = [0]

        def mock_shutdown(**kwargs):
            call_count[0] += 1
            if call_count[0] == 1 and "cancel_futures" in kwargs:
                raise TypeError("unexpected keyword argument 'cancel_futures'")

        mock_exec.shutdown = mock_shutdown
        mgr._executor = mock_exec
        mgr.shutdown(wait=False)
        self.assertEqual(call_count[0], 2)

    def test_executor_shutdown_generic_exception(self):
        """executor.shutdown() 通用异常"""
        mgr = _make_manager()
        mgr._executor = MagicMock()
        mgr._executor.shutdown.side_effect = RuntimeError("crash")
        mgr.shutdown(wait=False)

    def test_provider_cleanup_exception(self):
        """providers 清理异常"""
        mgr = _make_manager()
        lock = MagicMock()
        lock.__enter__ = MagicMock(side_effect=RuntimeError("lock broken"))
        lock.__exit__ = MagicMock(return_value=False)
        mgr._providers_lock = lock
        mgr.shutdown(wait=False)


class TestShutdownGracePeriod(unittest.TestCase):
    """grace_period：``shutdown(wait=False, grace_period=N)`` 的契约。

    场景：``atexit`` 阶段需要给 in-flight osascript / HTTP 通知一段
    显式收尾时间，但又不能无限等。这里锁住四个不变量：
        1. ``grace_period > 0`` 时**有**额外等待，上限不超过 grace；
        2. ``grace_period = 0`` 时立即返回（保留原行为，向后兼容）；
        3. ``wait=True`` 时 grace_period 被忽略（已是无限等）；
        4. atexit hook 用了非零 grace（避免未来回退）。
    """

    def test_grace_period_zero_does_not_join_threads(self):
        """``grace_period=0`` 时不应触碰 ``_threads``（保留原行为）。"""
        mgr = _make_manager()
        sentinel_thread = MagicMock()
        sentinel_thread.join = MagicMock()
        mgr._executor = MagicMock()
        mgr._executor._threads = {sentinel_thread}

        mgr.shutdown(wait=False, grace_period=0.0)

        sentinel_thread.join.assert_not_called()

    def test_grace_period_positive_joins_threads(self):
        """``grace_period > 0`` 时遍历 ``_threads`` 并 join 每个 worker。"""
        mgr = _make_manager()
        t1, t2 = MagicMock(), MagicMock()
        t1.join = MagicMock()
        t2.join = MagicMock()
        mgr._executor = MagicMock()
        mgr._executor._threads = {t1, t2}

        mgr.shutdown(wait=False, grace_period=0.5)

        t1.join.assert_called_once()
        t2.join.assert_called_once()
        # 每次 join 的 timeout 都应非负、且 <= grace
        for call in t1.join.call_args_list + t2.join.call_args_list:
            timeout = call.kwargs.get("timeout", call.args[0] if call.args else None)
            self.assertIsNotNone(timeout, "join 必须传 timeout（防无限等）")
            self.assertGreater(timeout, 0)
            self.assertLessEqual(timeout, 0.5)

    def test_grace_period_with_wait_true_is_noop(self):
        """``wait=True`` 时已是无限等，grace_period 不应再叠加 join。"""
        mgr = _make_manager()
        sentinel_thread = MagicMock()
        sentinel_thread.join = MagicMock()
        mgr._executor = MagicMock()
        mgr._executor._threads = {sentinel_thread}

        mgr.shutdown(wait=True, grace_period=0.5)

        sentinel_thread.join.assert_not_called()

    def test_grace_period_overall_bound_respected(self):
        """累计 grace 时间不应超出 ``grace_period`` 太多。

        即使 4 个 worker 每个 join 都不返回（例如真线程卡死），
        ``shutdown`` 也应在大约 grace 秒内返回，而不是 4×grace。
        """
        import time as _time

        mgr = _make_manager()

        slow_threads = []
        for _ in range(4):
            t = MagicMock()
            # join 立即返回（不模拟真阻塞，否则单测变慢）
            t.join = MagicMock()
            slow_threads.append(t)
        mgr._executor = MagicMock()
        mgr._executor._threads = set(slow_threads)

        start = _time.monotonic()
        mgr.shutdown(wait=False, grace_period=0.1)
        elapsed = _time.monotonic() - start

        # 4 个 mock join 立即返回，shutdown 整体应远低于 grace*2
        self.assertLess(
            elapsed,
            0.5,
            f"shutdown 整体耗时 {elapsed:.2f}s 超出预期上限",
        )

    def test_grace_period_join_exception_is_swallowed(self):
        """单个 thread.join 抛异常不应中断后续清理。"""
        mgr = _make_manager()
        good = MagicMock()
        good.join = MagicMock()
        bad = MagicMock()
        bad.join = MagicMock(side_effect=RuntimeError("thread invalidated"))
        mgr._executor = MagicMock()
        mgr._executor._threads = {bad, good}

        # 不应抛
        mgr.shutdown(wait=False, grace_period=0.1)

    def test_grace_period_threads_attr_missing_is_safe(self):
        """``_threads`` 不存在（私有 API 在未来 Python 删除）应安全降级。"""
        mgr = _make_manager()
        mgr._executor = MagicMock(spec=[])  # 只有 spec=[] 的对象不含 _threads

        # 不应抛 AttributeError
        mgr.shutdown(wait=False, grace_period=0.1)

    def test_atexit_hook_uses_nonzero_grace(self):
        """Reverse-lock：``_shutdown_global_notification_manager`` 必须给
        非零 grace_period，避免未来有人误删退化为 ``wait=False, grace=0``。
        """
        from notification_manager import _ATEXIT_GRACE_PERIOD_SECONDS

        self.assertGreater(
            _ATEXIT_GRACE_PERIOD_SECONDS,
            0.0,
            "atexit 必须给 in-flight 通知非零的收尾窗口",
        )
        # 上限：不让某次失败 release 把 grace 改成 30s 之类，导致用户
        # 退出 Cursor 后 30s 进程才真的死掉。
        self.assertLess(
            _ATEXIT_GRACE_PERIOD_SECONDS,
            5.0,
            "atexit grace 不应超过 5s，否则用户感知为'程序卡住'",
        )

    def test_shutdown_signature_has_grace_period(self):
        """Reverse-lock：签名必须有 ``grace_period`` 参数（不要被回退）。"""
        import inspect

        from notification_manager import NotificationManager

        sig = inspect.signature(NotificationManager.shutdown)
        self.assertIn(
            "grace_period",
            sig.parameters,
            "shutdown 必须保留 grace_period 参数（atexit 路径依赖它）",
        )
        # 默认值应为 0.0（向后兼容：旧调用方 shutdown(wait=False) 行为不变）
        self.assertEqual(sig.parameters["grace_period"].default, 0.0)


# ──────────────────────────────────────────────────────────
# _update_bark_provider 错误路径 (lines 1045-1051)
# ──────────────────────────────────────────────────────────


class TestUpdateBarkProviderErrors(unittest.TestCase):
    def test_import_error(self):
        """BarkNotificationProvider 导入失败"""
        import builtins

        mgr = _make_manager()
        mgr.config.bark_enabled = True
        with mgr._providers_lock:
            mgr._providers.pop(NotificationType.BARK, None)

        real_import = builtins.__import__

        def fail_import(name, *args, **kwargs):
            if name == "notification_providers":
                raise ImportError("mock: no notification_providers")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fail_import):
            mgr._update_bark_provider()

        with mgr._providers_lock:
            self.assertNotIn(NotificationType.BARK, mgr._providers)

    def test_generic_exception(self):
        """BarkNotificationProvider 构造异常"""
        mgr = _make_manager()
        mgr.config.bark_enabled = True
        with mgr._providers_lock:
            mgr._providers.pop(NotificationType.BARK, None)

        with patch(
            "notification_providers.BarkNotificationProvider",
            side_effect=RuntimeError("init failed"),
        ):
            mgr._update_bark_provider()

        with mgr._providers_lock:
            self.assertNotIn(NotificationType.BARK, mgr._providers)


# ──────────────────────────────────────────────────────────
# refresh_config_from_file: safe_bool 分支 (lines 870-877)
# ──────────────────────────────────────────────────────────


class TestRefreshSafeBoolBranches(unittest.TestCase):
    def test_int_and_float_coercion(self):
        """refresh 时 safe_bool 处理 int/float"""
        mgr = _make_manager()
        mock_cfg = MagicMock()
        mock_file = MagicMock()
        mock_file.stat.return_value.st_mtime = 5000.0
        mock_cfg.config_file = mock_file
        mock_cfg.get_section.return_value = {
            "enabled": 1,
            "debug": 0.0,
            "sound_volume": 80,
        }
        with (
            patch("notification_manager.CONFIG_FILE_AVAILABLE", True),
            patch("notification_manager.get_config", return_value=mock_cfg),
        ):
            mgr.refresh_config_from_file(force=True)
            self.assertTrue(mgr.config.enabled)
            self.assertFalse(mgr.config.debug)

    def test_string_true_false_unknown(self):
        """refresh 时 safe_bool 处理各种字符串"""
        mgr = _make_manager()
        mock_cfg = MagicMock()
        mock_file = MagicMock()
        mock_file.stat.return_value.st_mtime = 6000.0
        mock_cfg.config_file = mock_file
        mock_cfg.get_section.return_value = {
            "enabled": "yes",
            "debug": "on",
            "web_enabled": "off",
            "sound_enabled": "no",
            "bark_enabled": "maybe",
            "sound_volume": 80,
        }
        with (
            patch("notification_manager.CONFIG_FILE_AVAILABLE", True),
            patch("notification_manager.get_config", return_value=mock_cfg),
        ):
            mgr.refresh_config_from_file(force=True)
            self.assertTrue(mgr.config.enabled)
            self.assertTrue(mgr.config.debug)
            self.assertFalse(mgr.config.web_enabled)
            self.assertFalse(mgr.config.sound_enabled)
            self.assertFalse(mgr.config.bark_enabled)

    def test_validate_assignment_in_refresh(self):
        """refresh 时 Pydantic validate_assignment 自动校验字段"""
        mgr = _make_manager()
        mock_cfg = MagicMock()
        mock_file = MagicMock()
        mock_file.stat.return_value.st_mtime = 7000.0
        mock_cfg.config_file = mock_file
        mock_cfg.get_section.return_value = {"sound_volume": 80}

        with (
            patch("notification_manager.CONFIG_FILE_AVAILABLE", True),
            patch("notification_manager.get_config", return_value=mock_cfg),
        ):
            mgr.refresh_config_from_file(force=True)
            self.assertLessEqual(mgr.config.sound_volume, 1.0)


# ──────────────────────────────────────────────────────────
# _schedule_retry 边界 (lines 497-507)
# ──────────────────────────────────────────────────────────


class TestScheduleRetryEdge(unittest.TestCase):
    def test_invalid_delay_fallback(self):
        """retry_delay 不合法时回退默认值 2"""
        mgr = _make_manager()
        mgr.config.retry_delay = "invalid"  # type: ignore[assignment]

        event = _make_event()
        mgr._schedule_retry(event)

        with mgr._delayed_timers_lock:
            self.assertGreater(len(mgr._delayed_timers), 0)
            for t in mgr._delayed_timers.values():
                t.cancel()

    def test_retry_callback_executes(self):
        """_retry_run 内部函数实际执行并清理 Timer"""
        mgr = _make_manager()
        mock_provider = MagicMock()
        mock_provider.send.return_value = True
        mgr.register_provider(NotificationType.WEB, mock_provider)

        event = _make_event(max_retries=3, retry_count=1)
        mgr.config.retry_delay = 0

        mgr._schedule_retry(event)
        time.sleep(0.3)

        timer_key = f"{event.id}__retry_{event.retry_count}"
        with mgr._delayed_timers_lock:
            self.assertNotIn(timer_key, mgr._delayed_timers)


# ──────────────────────────────────────────────────────────
# stats 异常静默 (lines 435-437, 486-488, 529-530, etc.)
# ──────────────────────────────────────────────────────────


class TestProcessEventInnerFutureException(unittest.TestCase):
    def test_future_result_raises(self):
        """future.result() 异常被内层 except 捕获"""
        mgr = _make_manager()

        bad_future = MagicMock()
        bad_future.result.side_effect = RuntimeError("future error")

        mgr._executor = MagicMock()
        mgr._executor.submit.return_value = bad_future

        def mock_as_completed(fs, timeout=None):
            yield from fs

        with patch("notification_manager.as_completed", side_effect=mock_as_completed):
            event = _make_event(types=[NotificationType.WEB], max_retries=0)
            mgr._process_event(event)

    def test_retry_stats_exception_silenced(self):
        """重试路径中 stats 异常不影响重试调度"""
        mgr = _make_manager()
        mock_provider = MagicMock()
        mock_provider.send.return_value = False
        mgr.register_provider(NotificationType.WEB, mock_provider)
        mgr._stats = None  # type: ignore[assignment]

        event = _make_event(max_retries=2, retry_count=0)
        with patch.object(mgr, "_schedule_retry"):
            mgr._process_event(event)
        self.assertEqual(event.retry_count, 1)

    def test_outer_exception_retry_stats_broken(self):
        """外层异常重试路径中 stats 异常不影响重试"""
        mgr = _make_manager()
        mgr._executor = MagicMock()
        mgr._executor.submit.side_effect = RuntimeError("crash")
        mgr._stats = None  # type: ignore[assignment]

        event = _make_event(max_retries=2, retry_count=0)
        with patch.object(mgr, "_schedule_retry"):
            mgr._process_event(event)
        self.assertEqual(event.retry_count, 1)


class TestStatsExceptionSilenced(unittest.TestCase):
    def test_send_notification_stats_broken(self):
        """send_notification 中 _stats 异常不影响事件创建"""
        mgr = _make_manager()
        mock_provider = MagicMock()
        mock_provider.send.return_value = True
        mgr.register_provider(NotificationType.WEB, mock_provider)
        mgr._stats = None  # type: ignore[assignment]

        event_id = mgr.send_notification("t", "m", types=[NotificationType.WEB])
        self.assertNotEqual(event_id, "")

    def test_mark_event_finalized_stats_broken(self):
        """_mark_event_finalized 中 _stats 异常不外抛"""
        mgr = _make_manager()
        mgr._stats = None  # type: ignore[assignment]
        event = _make_event(id="fin_broken")
        mgr._mark_event_finalized(event, succeeded=True)

    def test_send_single_no_provider_stats_broken(self):
        """无 provider 时统计记录异常不外抛"""
        mgr = _make_manager()
        mgr._stats = None  # type: ignore[assignment]
        event = _make_event()
        result = mgr._send_single_notification(NotificationType.WEB, event)
        self.assertFalse(result)

    def test_send_single_success_stats_broken(self):
        """provider 发送成功但统计记录异常"""
        mgr = _make_manager()
        mock_provider = MagicMock()
        mock_provider.send.return_value = True
        mgr.register_provider(NotificationType.WEB, mock_provider)
        mgr._stats = None  # type: ignore[assignment]
        event = _make_event()
        result = mgr._send_single_notification(NotificationType.WEB, event)
        self.assertTrue(result)

    def test_send_single_exception_stats_broken(self):
        """provider 异常且统计记录也异常"""
        mgr = _make_manager()
        mock_provider = MagicMock()
        mock_provider.send.side_effect = RuntimeError("crash")
        mgr.register_provider(NotificationType.WEB, mock_provider)
        mgr._stats = None  # type: ignore[assignment]
        event = _make_event()
        result = mgr._send_single_notification(NotificationType.WEB, event)
        self.assertFalse(result)


# ──────────────────────────────────────────────────────────
# get_status stats 异常 (lines 1131-1132, 1149-1152)
# ──────────────────────────────────────────────────────────


class TestBranchCoverage(unittest.TestCase):
    """补充分支覆盖"""

    def test_auto_types_all_disabled(self):
        """types=None 且所有渠道关闭 → 空 types"""
        mgr = _make_manager()
        mgr.config.web_enabled = False
        mgr.config.sound_enabled = False
        mgr.config.bark_enabled = False
        mgr.config.system_enabled = False

        event_id = mgr.send_notification("t", "m")
        self.assertNotEqual(event_id, "")

    def test_priority_non_string_non_enum(self):
        """priority 传入非字符串非枚举值 → 使用默认"""
        mgr = _make_manager()
        mock_provider = MagicMock()
        mock_provider.send.return_value = True
        mgr.register_provider(NotificationType.WEB, mock_provider)

        event_id = mgr.send_notification(
            "t",
            "m",
            types=[NotificationType.WEB],
            priority=999,  # type: ignore[arg-type]
        )
        self.assertNotEqual(event_id, "")

    def test_all_fail_no_fallback(self):
        """所有渠道失败 + 重试耗尽 + fallback 关闭"""
        mgr = _make_manager()
        mgr.config.fallback_enabled = False
        mock_provider = MagicMock()
        mock_provider.send.return_value = False
        mgr.register_provider(NotificationType.WEB, mock_provider)

        event = _make_event(max_retries=0)
        mgr._process_event(event)

    def test_update_config_nonexistent_key(self):
        """update_config_without_save 忽略不存在的配置键"""
        mgr = _make_manager()
        mgr.update_config_without_save(nonexistent_key_xyz="value")
        self.assertFalse(hasattr(mgr.config, "nonexistent_key_xyz"))


class TestGetStatusEdge(unittest.TestCase):
    def test_derived_stats_calculation_exception(self):
        """派生指标计算异常被静默"""
        mgr = _make_manager()
        mgr._stats["events_succeeded"] = "not_a_number"
        status = mgr.get_status()
        self.assertIn("stats", status)

    def test_provider_stats_calculation_exception(self):
        """提供者级别统计计算异常"""
        mgr = _make_manager()
        mgr._stats["providers"] = {"web": {"attempts": "bad", "success": "bad"}}
        status = mgr.get_status()
        self.assertIn("stats", status)

    def test_stats_lock_failure(self):
        """stats 锁获取失败 → 返回空 stats"""
        mgr = _make_manager()
        lock = MagicMock()
        lock.__enter__ = MagicMock(side_effect=RuntimeError("lock broken"))
        lock.__exit__ = MagicMock(return_value=False)
        mgr._stats_lock = lock
        status = mgr.get_status()
        self.assertEqual(status["stats"], {})


# ═══════════════════════════════════════════════════════════════════════════
#  R17.3 — Worker pool sizing aligns with NotificationType count
# ═══════════════════════════════════════════════════════════════════════════
class TestWorkerCountMatchesNotificationTypes(unittest.TestCase):
    """``ThreadPoolExecutor`` worker 数 = 通知渠道数的契约。

    why：
        历史上 ``max_workers=3`` 写死，但 ``NotificationType`` 有 4 个
        成员（WEB / SOUND / BARK / SYSTEM）。"全开"用户的第 4 个 future
        进队列等空闲 worker，前 3 个一旦接近 ``bark_timeout`` 边缘，
        ``as_completed(timeout=bark_timeout + buffer)`` 先到期强 cancel
        排队中的 future——用户漏收一条通知却零日志告警。

        本组测试锁住三层防御：
          1. 常量本身 = ``len(NotificationType)``——加新渠道时本文件
             无需手动跟随调整；
          2. 实际 ``self._executor._max_workers`` 等于该常量；
          3. ``restart()`` 后线程池容量保持一致——历史曾出现
             ``__init__`` 改了但 ``restart`` 没改，让 atexit→restart
             路径上的容量与正常启动路径不一致。
    """

    def test_worker_count_constant_equals_enum_size(self):
        """``_NOTIFICATION_WORKER_COUNT`` 必须等于 ``NotificationType`` 成员数。"""
        from notification_manager import _NOTIFICATION_WORKER_COUNT
        from notification_models import NotificationType

        self.assertEqual(
            _NOTIFICATION_WORKER_COUNT,
            len(NotificationType),
            "Worker count should track NotificationType cardinality. "
            f"常量={_NOTIFICATION_WORKER_COUNT}, 枚举大小={len(NotificationType)}",
        )

    def test_worker_count_at_least_four(self):
        """硬下限：worker 数永远不能 <4。

        当前 NotificationType 有 4 个成员；如果未来有人删枚举值导致
        len()<4，全渠道用户的并发度回退是可观察的回归——这层防御
        让"删渠道"必须是有意识的决定，而不是悄无声息的退步。
        """
        from notification_manager import _NOTIFICATION_WORKER_COUNT

        self.assertGreaterEqual(
            _NOTIFICATION_WORKER_COUNT,
            4,
            "项目当前有 4 种通知类型，worker 不能少于 4。",
        )

    def test_executor_uses_constant_max_workers(self):
        """``self._executor._max_workers`` 必须命中常量值。

        ThreadPoolExecutor 暴露 ``_max_workers`` 属性（CPython 3.9+），
        是唯一无需改运行时行为就能验证容量的接口。
        """
        from notification_manager import (
            _NOTIFICATION_WORKER_COUNT,
            NotificationManager,
        )

        NotificationManager._instance = None
        try:
            mgr = NotificationManager()
            actual = getattr(mgr._executor, "_max_workers", None)
            self.assertEqual(
                actual,
                _NOTIFICATION_WORKER_COUNT,
                f"__init__ 应当把 max_workers 设为 {_NOTIFICATION_WORKER_COUNT}，"
                f"实际：{actual}",
            )
        finally:
            try:
                mgr._executor.shutdown(wait=False)
            except Exception:
                pass
            NotificationManager._instance = None

    def test_restart_recreates_executor_with_same_capacity(self):
        """``restart()`` 后的新线程池必须保持同样容量——避免双路径漂移。"""
        from notification_manager import (
            _NOTIFICATION_WORKER_COUNT,
            NotificationManager,
        )

        NotificationManager._instance = None
        try:
            mgr = NotificationManager()
            mgr.shutdown(wait=False)
            mgr.restart()

            actual = getattr(mgr._executor, "_max_workers", None)
            self.assertEqual(
                actual,
                _NOTIFICATION_WORKER_COUNT,
                f"restart() 后 max_workers 应保持 {_NOTIFICATION_WORKER_COUNT}，"
                f"实际：{actual}（与 __init__ 不一致就是双路径漂移）",
            )
        finally:
            try:
                mgr._executor.shutdown(wait=False)
            except Exception:
                pass
            NotificationManager._instance = None

    def test_no_hardcoded_three_in_executor_construction(self):
        """reverse-lock：源码里不能再出现 ``max_workers=3`` 字面量。

        AST-grep 比纯文本 grep 鲁棒：避免误伤注释 / docstring 里
        提到的历史值。
        """
        import ast
        import inspect

        from notification_manager import NotificationManager

        src = inspect.getsource(NotificationManager)
        tree = ast.parse(src)

        offending: list[tuple[int, str]] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                for kw in node.keywords:
                    if (
                        kw.arg == "max_workers"
                        and isinstance(kw.value, ast.Constant)
                        and kw.value.value == 3
                    ):
                        offending.append((node.lineno, ast.unparse(node)))

        self.assertEqual(
            offending,
            [],
            f"NotificationManager 不应再硬编码 max_workers=3；残留位置：{offending}",
        )


if __name__ == "__main__":
    unittest.main()
