"""
config_utils 模块单元测试

测试覆盖：
    - clamp_value() 边界值限制
    - clamp_dataclass_field() dataclass 字段限制
    - get_compat_config() 向后兼容配置读取
    - get_typed_config() 类型转换和验证
    - validate_enum_value() 枚举值验证
"""

import unittest
from dataclasses import dataclass


class TestClampValue(unittest.TestCase):
    """测试 clamp_value() 函数"""

    def test_value_in_range(self):
        """测试值在范围内"""
        from config_utils import clamp_value

        self.assertEqual(clamp_value(50, 0, 100, "test"), 50)
        self.assertEqual(clamp_value(0, 0, 100, "test"), 0)
        self.assertEqual(clamp_value(100, 0, 100, "test"), 100)

    def test_value_below_min(self):
        """测试值小于最小值"""
        from config_utils import clamp_value

        self.assertEqual(clamp_value(-10, 0, 100, "test"), 0)
        self.assertEqual(clamp_value(-100, 0, 100, "test"), 0)

    def test_value_above_max(self):
        """测试值大于最大值"""
        from config_utils import clamp_value

        self.assertEqual(clamp_value(150, 0, 100, "test"), 100)
        self.assertEqual(clamp_value(1000, 0, 100, "test"), 100)

    def test_float_values(self):
        """测试浮点数"""
        from config_utils import clamp_value

        self.assertEqual(clamp_value(0.5, 0.0, 1.0, "test"), 0.5)
        self.assertEqual(clamp_value(-0.1, 0.0, 1.0, "test"), 0.0)
        self.assertEqual(clamp_value(1.5, 0.0, 1.0, "test"), 1.0)

    def test_log_warning_disabled(self):
        """测试禁用日志警告"""
        from config_utils import clamp_value

        # 不应引发异常
        result = clamp_value(-10, 0, 100, "test", log_warning=False)
        self.assertEqual(result, 0)


class TestClampDataclassField(unittest.TestCase):
    """测试 clamp_dataclass_field() 函数"""

    def test_field_in_range(self):
        """测试字段值在范围内"""
        from config_utils import clamp_dataclass_field

        @dataclass
        class TestConfig:
            timeout: int = 50

        config = TestConfig()
        clamp_dataclass_field(config, "timeout", 0, 100)
        self.assertEqual(config.timeout, 50)

    def test_field_below_min(self):
        """测试字段值小于最小值"""
        from config_utils import clamp_dataclass_field

        @dataclass
        class TestConfig:
            timeout: int = -10

        config = TestConfig()
        clamp_dataclass_field(config, "timeout", 0, 100)
        self.assertEqual(config.timeout, 0)

    def test_field_above_max(self):
        """测试字段值大于最大值"""
        from config_utils import clamp_dataclass_field

        @dataclass
        class TestConfig:
            timeout: int = 150

        config = TestConfig()
        clamp_dataclass_field(config, "timeout", 0, 100)
        self.assertEqual(config.timeout, 100)


class TestGetCompatConfig(unittest.TestCase):
    """测试 get_compat_config() 函数"""

    def test_new_key_exists(self):
        """测试新键存在"""
        from config_utils import get_compat_config

        config = {"http_request_timeout": 60}
        result = get_compat_config(config, "http_request_timeout", "timeout", 30)
        self.assertEqual(result, 60)

    def test_old_key_fallback(self):
        """测试旧键回退"""
        from config_utils import get_compat_config

        config = {"timeout": 60}
        result = get_compat_config(config, "http_request_timeout", "timeout", 30)
        self.assertEqual(result, 60)

    def test_default_value(self):
        """测试默认值"""
        from config_utils import get_compat_config

        config = {}
        result = get_compat_config(config, "http_request_timeout", "timeout", 30)
        self.assertEqual(result, 30)

    def test_new_key_priority(self):
        """测试新键优先于旧键"""
        from config_utils import get_compat_config

        config = {"http_request_timeout": 120, "timeout": 60}
        result = get_compat_config(config, "http_request_timeout", "timeout", 30)
        self.assertEqual(result, 120)

    def test_no_old_key(self):
        """测试无旧键"""
        from config_utils import get_compat_config

        config = {"new_key": 100}
        result = get_compat_config(config, "new_key", None, 50)
        self.assertEqual(result, 100)


class TestGetTypedConfig(unittest.TestCase):
    """测试 get_typed_config() 函数"""

    def test_int_conversion(self):
        """测试整数转换"""
        from config_utils import get_typed_config

        config = {"timeout": "30"}
        result = get_typed_config(config, "timeout", 60, int)
        self.assertEqual(result, 30)

    def test_float_conversion(self):
        """测试浮点数转换"""
        from config_utils import get_typed_config

        config = {"delay": "1.5"}
        result = get_typed_config(config, "delay", 1.0, float)
        self.assertEqual(result, 1.5)

    def test_bool_conversion_string(self):
        """测试布尔值字符串转换"""
        from config_utils import get_typed_config

        config = {"enabled": "true"}
        result = get_typed_config(config, "enabled", False, bool)
        self.assertTrue(result)

        config = {"enabled": "false"}
        result = get_typed_config(config, "enabled", True, bool)
        self.assertFalse(result)

    def test_invalid_type_uses_default(self):
        """测试无效类型使用默认值"""
        from config_utils import get_typed_config

        config = {"timeout": "invalid"}
        result = get_typed_config(config, "timeout", 60, int)
        self.assertEqual(result, 60)

    def test_with_boundary(self):
        """测试带边界验证"""
        from config_utils import get_typed_config

        config = {"timeout": "500"}
        result = get_typed_config(config, "timeout", 60, int, 1, 300)
        self.assertEqual(result, 300)  # 超过最大值，调整为 300

    def test_with_old_key(self):
        """测试向后兼容"""
        from config_utils import get_typed_config

        config = {"old_timeout": "120"}
        result = get_typed_config(
            config, "http_request_timeout", 60, int, 1, 300, "old_timeout"
        )
        self.assertEqual(result, 120)


class TestValidateEnumValue(unittest.TestCase):
    """测试 validate_enum_value() 函数"""

    def test_valid_value(self):
        """测试有效值"""
        from config_utils import validate_enum_value

        valid = ("none", "url", "copy")
        self.assertEqual(validate_enum_value("url", valid, "action", "none"), "url")
        self.assertEqual(validate_enum_value("none", valid, "action", "none"), "none")
        self.assertEqual(validate_enum_value("copy", valid, "action", "none"), "copy")

    def test_invalid_value_uses_default(self):
        """测试无效值使用默认值"""
        from config_utils import validate_enum_value

        valid = ("none", "url", "copy")
        self.assertEqual(
            validate_enum_value("invalid", valid, "action", "none"), "none"
        )
        self.assertEqual(validate_enum_value("", valid, "action", "none"), "none")


class TestTruncateString(unittest.TestCase):
    """测试 truncate_string() 函数"""

    def test_string_in_range(self):
        """测试字符串在长度范围内"""
        from config_utils import truncate_string

        self.assertEqual(truncate_string("hello", 10, "test"), "hello")
        self.assertEqual(truncate_string("hello", 5, "test"), "hello")

    def test_string_too_long(self):
        """测试字符串过长"""
        from config_utils import truncate_string

        self.assertEqual(truncate_string("hello world", 5, "test"), "hello")
        self.assertEqual(truncate_string("abcdefghij", 3, "test"), "abc")

    def test_empty_string_with_default(self):
        """测试空字符串使用默认值"""
        from config_utils import truncate_string

        self.assertEqual(truncate_string("", 10, "test", default="default"), "default")
        self.assertEqual(
            truncate_string("   ", 10, "test", default="default"), "default"
        )

    def test_empty_string_without_default(self):
        """测试空字符串无默认值"""
        from config_utils import truncate_string

        self.assertEqual(truncate_string("", 10, "test"), "")
        self.assertEqual(truncate_string("   ", 10, "test"), "   ")

    def test_none_value(self):
        """测试 None 值"""
        from config_utils import truncate_string

        self.assertEqual(truncate_string(None, 10, "test"), "")
        self.assertEqual(
            truncate_string(None, 10, "test", default="default"), "default"
        )


class TestIntegration(unittest.TestCase):
    """集成测试"""

    def test_combined_usage(self):
        """测试组合使用场景"""
        from config_utils import get_typed_config, validate_enum_value

        config = {
            "http_request_timeout": "500",  # 需要限制到 300
            "bark_action": "invalid",  # 需要使用默认值
            "sound_volume": "-10",  # 需要限制到 0
        }

        timeout = get_typed_config(config, "http_request_timeout", 30, int, 1, 300)
        action = validate_enum_value(
            config.get("bark_action", "none"),
            ("none", "url", "copy"),
            "bark_action",
            "none",
        )
        volume = get_typed_config(config, "sound_volume", 80, int, 0, 100)

        self.assertEqual(timeout, 300)
        self.assertEqual(action, "none")
        self.assertEqual(volume, 0)

    def test_truncate_with_validation(self):
        """测试字符串截断与验证组合"""
        from config_utils import truncate_string, validate_enum_value

        # 模拟配置场景
        long_prompt = "a" * 1000
        truncated = truncate_string(long_prompt, 500, "prompt")
        self.assertEqual(len(truncated), 500)

        # 枚举验证后的值
        action = validate_enum_value("invalid", ("none", "url"), "action", "none")
        self.assertEqual(action, "none")


class TestConfigManagerTypedMethods(unittest.TestCase):
    """测试 ConfigManager 的类型安全获取方法"""

    def test_get_int(self):
        """测试 get_int 方法"""
        from config_manager import get_config

        config = get_config()
        # 测试获取存在的整数配置
        port = config.get_int("web_ui.port", 8080, 1, 65535)
        self.assertIsInstance(port, int)
        self.assertTrue(1 <= port <= 65535)

    def test_get_float(self):
        """测试 get_float 方法"""
        from config_manager import get_config

        config = get_config()
        # 测试获取不存在的配置使用默认值
        value = config.get_float("nonexistent.key", 0.5, 0.0, 1.0)
        self.assertEqual(value, 0.5)
        self.assertIsInstance(value, float)

    def test_get_bool(self):
        """测试 get_bool 方法"""
        from config_manager import get_config

        config = get_config()
        # 测试获取布尔配置
        enabled = config.get_bool("notification.enabled", True)
        self.assertIsInstance(enabled, bool)

    def test_get_str(self):
        """测试 get_str 方法"""
        from config_manager import get_config

        config = get_config()
        # 测试获取字符串配置
        host = config.get_str("web_ui.host", "127.0.0.1")
        self.assertIsInstance(host, str)

    def test_get_str_with_max_length(self):
        """测试 get_str 带长度限制"""
        from config_manager import get_config

        config = get_config()
        # 测试带长度限制的字符串获取
        value = config.get_str("nonexistent.key", "a" * 100, max_length=50)
        self.assertEqual(len(value), 50)

    def test_get_typed_with_boundary(self):
        """测试 get_typed 边界验证"""
        from config_manager import get_config

        config = get_config()
        # 测试边界验证
        value = config.get_typed("nonexistent.key", 1000, int, 0, 100)
        self.assertEqual(value, 100)  # 超过最大值，调整为 100


class TestConfigManagerFileWatcher(unittest.TestCase):
    """测试 ConfigManager 的文件监听功能"""

    def test_start_stop_file_watcher(self):
        """测试启动和停止文件监听器"""
        from config_manager import get_config

        config = get_config()

        # get_config() 可能会自动启动监听器；为了测试 start/stop 行为，这里先确保停掉
        config.stop_file_watcher()
        self.assertFalse(config.is_file_watcher_running)

        # 启动监听器
        config.start_file_watcher(interval=0.5)
        self.assertTrue(config.is_file_watcher_running)

        # 再次启动应该被忽略（不会重复启动）
        config.start_file_watcher(interval=0.5)
        self.assertTrue(config.is_file_watcher_running)

        # 停止监听器
        config.stop_file_watcher()
        self.assertFalse(config.is_file_watcher_running)

        # 再次停止应该被安全忽略
        config.stop_file_watcher()
        self.assertFalse(config.is_file_watcher_running)

    def test_register_config_change_callback(self):
        """测试注册和取消配置变更回调"""
        from config_manager import get_config

        config = get_config()
        callback_called = [False]

        def test_callback():
            callback_called[0] = True

        # 注册回调
        config.register_config_change_callback(test_callback)
        self.assertIn(test_callback, config._config_change_callbacks)

        # 手动触发回调
        config._trigger_config_change_callbacks()
        self.assertTrue(callback_called[0])

        # 取消注册
        config.unregister_config_change_callback(test_callback)
        self.assertNotIn(test_callback, config._config_change_callbacks)

    def test_callback_error_handling(self):
        """测试回调错误处理"""
        from config_manager import get_config

        config = get_config()

        def bad_callback():
            raise ValueError("测试错误")

        def good_callback():
            pass

        # 注册两个回调，一个会抛出异常
        config.register_config_change_callback(bad_callback)
        config.register_config_change_callback(good_callback)

        # 触发回调不应该抛出异常
        try:
            config._trigger_config_change_callbacks()
        except Exception as e:
            self.fail(f"回调触发不应该抛出异常: {e}")

        # 清理
        config.unregister_config_change_callback(bad_callback)
        config.unregister_config_change_callback(good_callback)


class TestTaskQueueStatusCallback(unittest.TestCase):
    """测试 TaskQueue 的任务状态回调功能"""

    def test_register_unregister_callback(self):
        """测试注册和取消回调"""
        from task_queue import TaskQueue

        queue = TaskQueue(max_tasks=5)
        status_changes = []

        def test_callback(task_id, old_status, new_status):
            status_changes.append((task_id, old_status, new_status))

        # 注册回调
        queue.register_status_change_callback(test_callback)
        self.assertIn(test_callback, queue._status_change_callbacks)

        # 添加任务应触发回调
        queue.add_task("task-1", "Test prompt")
        self.assertEqual(len(status_changes), 1)
        self.assertEqual(status_changes[0], ("task-1", None, "active"))

        # 取消注册
        queue.unregister_status_change_callback(test_callback)
        self.assertNotIn(test_callback, queue._status_change_callbacks)

        # 添加另一个任务不应触发回调
        queue.add_task("task-2", "Test prompt 2")
        self.assertEqual(len(status_changes), 1)  # 仍然是 1

        # 清理
        queue.stop_cleanup()

    def test_complete_task_callback(self):
        """测试任务完成时的回调"""
        from task_queue import TaskQueue

        queue = TaskQueue(max_tasks=5)
        status_changes = []

        def test_callback(task_id, old_status, new_status):
            status_changes.append((task_id, old_status, new_status))

        queue.register_status_change_callback(test_callback)

        # 添加两个任务
        queue.add_task("task-1", "Test 1")
        queue.add_task("task-2", "Test 2")

        # 清空回调记录
        status_changes.clear()

        # 完成第一个任务
        queue.complete_task("task-1", {"feedback": "done"})

        # 应该有两个回调：task-1 完成，task-2 激活
        self.assertEqual(len(status_changes), 2)
        self.assertEqual(status_changes[0], ("task-1", "active", "completed"))
        self.assertEqual(status_changes[1], ("task-2", "pending", "active"))

        # 清理
        queue.unregister_status_change_callback(test_callback)
        queue.stop_cleanup()

    def test_remove_task_callback(self):
        """测试任务移除时的回调"""
        from task_queue import TaskQueue

        queue = TaskQueue(max_tasks=5)
        status_changes = []

        def test_callback(task_id, old_status, new_status):
            status_changes.append((task_id, old_status, new_status))

        queue.register_status_change_callback(test_callback)

        # 添加两个任务
        queue.add_task("task-1", "Test 1")
        queue.add_task("task-2", "Test 2")

        # 清空回调记录
        status_changes.clear()

        # 移除活动任务
        queue.remove_task("task-1")

        # 应该有两个回调：task-1 移除，task-2 激活
        self.assertEqual(len(status_changes), 2)
        self.assertEqual(status_changes[0], ("task-1", "active", "removed"))
        self.assertEqual(status_changes[1], ("task-2", "pending", "active"))

        # 清理
        queue.unregister_status_change_callback(test_callback)
        queue.stop_cleanup()

    def test_callback_error_handling(self):
        """测试回调错误处理"""
        from task_queue import TaskQueue

        queue = TaskQueue(max_tasks=5)

        def bad_callback(task_id, old_status, new_status):
            raise ValueError("测试错误")

        queue.register_status_change_callback(bad_callback)

        # 添加任务不应该抛出异常
        try:
            queue.add_task("task-1", "Test prompt")
        except Exception as e:
            self.fail(f"回调错误不应该传播: {e}")

        # 清理
        queue.unregister_status_change_callback(bad_callback)
        queue.stop_cleanup()


if __name__ == "__main__":
    unittest.main()
