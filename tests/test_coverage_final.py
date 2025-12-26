#!/usr/bin/env python3
"""
AI Intervention Agent - 最终覆盖率提升测试

专注于提升 notification_manager.py 和 config_manager.py 的覆盖率
"""

import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


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


class TestConfigManagerExportImportAdvanced(unittest.TestCase):
    """配置导入导出高级测试"""

    def test_export_config_to_dict(self):
        """测试导出配置为字典"""
        from config_manager import get_config

        config = get_config()
        exported = config.export_config()

        self.assertIsInstance(exported, dict)
        # 导出格式包含 config 键
        self.assertIn("config", exported)
        self.assertIn("notification", exported.get("config", {}))

    def test_import_config_merge_mode(self):
        """测试合并模式导入配置"""
        from config_manager import get_config

        config = get_config()

        # 备份原始值
        original_enabled = config.get("notification.enabled")

        # 导入新配置（合并模式）
        result = config.import_config({"notification": {"enabled": True}}, merge=True)

        self.assertTrue(result)

        # 恢复原始值
        config.set("notification.enabled", original_enabled)

    def test_export_import_roundtrip(self):
        """测试导出-导入往返"""
        from config_manager import get_config

        config = get_config()

        # 导出
        exported = config.export_config()

        # 导入（应该不改变任何东西）
        result = config.import_config(exported, merge=True)

        self.assertTrue(result)


class TestConfigManagerTypedGettersAdvanced(unittest.TestCase):
    """类型化获取器高级测试"""

    def test_get_int_with_float(self):
        """测试从浮点数获取整数"""
        from config_manager import get_config

        config = get_config()

        # 设置浮点数值
        config.set("test.float_value", 3.7)

        # 获取为整数
        result = config.get_int("test.float_value", default=0)
        self.assertEqual(result, 3)  # 应该被截断为 3

        # 清理
        config.set("test.float_value", None)

    def test_get_float_with_int(self):
        """测试从整数获取浮点数"""
        from config_manager import get_config

        config = get_config()

        # 设置整数值
        config.set("test.int_value", 42)

        # 获取为浮点数
        result = config.get_float("test.int_value", default=0.0)
        self.assertEqual(result, 42.0)

        # 清理
        config.set("test.int_value", None)

    def test_get_bool_with_int_zero(self):
        """测试从 0 获取布尔值"""
        from config_manager import get_config

        config = get_config()

        # 设置整数 0
        config.set("test.zero_value", 0)

        # 获取为布尔值
        result = config.get_bool("test.zero_value", default=True)
        self.assertFalse(result)

        # 清理
        config.set("test.zero_value", None)

    def test_get_str_with_number(self):
        """测试从数字获取字符串"""
        from config_manager import get_config

        config = get_config()

        # 设置数字值
        config.set("test.number_value", 123)

        # 获取为字符串
        result = config.get_str("test.number_value", default="")
        self.assertEqual(result, "123")

        # 清理
        config.set("test.number_value", None)


class TestNotificationConfigValidation(unittest.TestCase):
    """通知配置验证测试"""

    def test_config_sound_volume_boundary_low(self):
        """测试声音音量下边界"""
        from notification_manager import NotificationConfig

        config = NotificationConfig(sound_volume=-10)
        self.assertEqual(config.sound_volume, 0.0)

    def test_config_sound_volume_boundary_high(self):
        """测试声音音量上边界"""
        from notification_manager import NotificationConfig

        config = NotificationConfig(sound_volume=150)
        self.assertEqual(config.sound_volume, 1.0)

    def test_config_bark_action_invalid(self):
        """测试无效的 Bark 动作"""
        from notification_manager import NotificationConfig

        config = NotificationConfig(bark_action="invalid_action")
        self.assertEqual(config.bark_action, "none")

    def test_config_bark_url_empty_when_enabled(self):
        """测试 Bark 启用但 URL 为空"""
        from notification_manager import NotificationConfig

        config = NotificationConfig(
            bark_enabled=True, bark_url="", bark_device_key="test_key"
        )
        # URL 为空时，bark_enabled 可能仍为 True（取决于实现）
        # 这里验证配置创建成功
        self.assertIsNotNone(config)


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


class TestConfigManagerFileWatcherAdvanced(unittest.TestCase):
    """文件监听器高级测试"""

    def test_file_watcher_callback_triggered(self):
        """测试文件监听器回调触发"""

        import os
        import tempfile

        from config_manager import ConfigManager

        # 使用临时配置文件，避免污染用户真实配置
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "test_config.jsonc"
            config_path.write_text(
                '{\n  "notification": { "enabled": true },\n  "web_ui": { "host": "127.0.0.1", "port": 8080 },\n  "network_security": { "bind_interface": "127.0.0.1", "allowed_networks": ["127.0.0.0/8"], "blocked_ips": [], "access_control_enabled": true },\n  "feedback": { "backend_max_wait": 600, "frontend_countdown": 240, "resubmit_prompt": "", "prompt_suffix": "" }\n}\n',
                encoding="utf-8",
            )

            config = ConfigManager(str(config_path))

            callback_event = threading.Event()

            def test_callback():
                callback_event.set()

            # 注册回调并启动监听器
            config.register_config_change_callback(test_callback)
            config.start_file_watcher(interval=0.05)

            try:
                # 修改文件内容并更新时间戳，触发监听器检测
                time.sleep(0.1)
                config_path.write_text(
                    config_path.read_text(encoding="utf-8") + "\n",
                    encoding="utf-8",
                )
                os.utime(config_path, None)

                self.assertTrue(
                    callback_event.wait(1.0), "文件变更回调未在预期时间内触发"
                )
            finally:
                # 显式清理后台资源，确保测试可重复
                config.stop_file_watcher()
                config.shutdown()
                config.unregister_config_change_callback(test_callback)


class TestConfigUtilsAdvanced(unittest.TestCase):
    """配置工具高级测试"""

    def test_clamp_value_normal(self):
        """测试 clamp_value 正常情况"""
        from config_utils import clamp_value

        result = clamp_value(50, 0, 100, "test_field")
        self.assertEqual(result, 50)

    def test_clamp_value_below_min(self):
        """测试 clamp_value 低于最小值"""
        from config_utils import clamp_value

        result = clamp_value(-10, 0, 100, "test_field")
        self.assertEqual(result, 0)

    def test_clamp_value_above_max(self):
        """测试 clamp_value 高于最大值"""
        from config_utils import clamp_value

        result = clamp_value(150, 0, 100, "test_field")
        self.assertEqual(result, 100)

    def test_validate_enum_value_valid(self):
        """测试 validate_enum_value 有效值"""
        from config_utils import validate_enum_value

        # 签名: validate_enum_value(value, valid_values, field_name, default)
        result = validate_enum_value(
            "url", ("none", "url", "copy"), "bark_action", "none"
        )
        self.assertEqual(result, "url")

    def test_validate_enum_value_invalid(self):
        """测试 validate_enum_value 无效值"""
        from config_utils import validate_enum_value

        # 签名: validate_enum_value(value, valid_values, field_name, default)
        result = validate_enum_value("invalid", ("a", "b", "c"), "test_field", "a")
        self.assertEqual(result, "a")

    def test_truncate_string_normal(self):
        """测试 truncate_string 正常情况"""
        from config_utils import truncate_string

        result = truncate_string("hello", 100, "default")
        self.assertEqual(result, "hello")

    def test_truncate_string_long(self):
        """测试 truncate_string 截断长字符串"""
        from config_utils import truncate_string

        result = truncate_string("a" * 200, 100, "default")
        self.assertEqual(len(result), 100)


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


if __name__ == "__main__":
    unittest.main()
