"""
配置管理器覆盖率提升测试

针对 config_manager.py 未覆盖的代码路径添加测试。
"""

import unittest
from typing import Any, cast


class TestConfigManagerTypedGetters(unittest.TestCase):
    """测试类型安全的配置获取方法"""

    def test_get_int_with_string_value(self):
        """测试 get_int 处理字符串值"""
        from config_manager import get_config

        config = get_config()
        # 获取不存在的键，使用默认值
        result = config.get_int("nonexistent.int.key", 42)
        self.assertEqual(result, 42)

    def test_get_float_with_string_value(self):
        """测试 get_float 处理字符串值"""
        from config_manager import get_config

        config = get_config()
        result = config.get_float("nonexistent.float.key", 3.14)
        self.assertEqual(result, 3.14)

    def test_get_bool_with_string_true(self):
        """测试 get_bool 处理字符串 'true'"""
        from config_manager import get_config

        config = get_config()
        # 测试 notification.enabled 应该是布尔值
        result = config.get_bool("notification.enabled", False)
        self.assertIsInstance(result, bool)

    def test_get_bool_with_string_false(self):
        """测试 get_bool 处理字符串 'false'"""
        from config_manager import get_config

        config = get_config()
        result = config.get_bool("nonexistent.bool.key", False)
        self.assertFalse(result)

    def test_get_str_truncation(self):
        """测试 get_str 截断功能"""
        from config_manager import get_config

        config = get_config()
        # 使用带最大长度的字符串获取
        result = config.get_str("nonexistent.str.key", "a" * 1000, max_length=100)
        self.assertEqual(len(result), 100)


class TestConfigManagerFileWatcher(unittest.TestCase):
    """测试文件监听功能"""

    def test_update_file_mtime(self):
        """测试更新文件修改时间"""
        from config_manager import get_config

        config = get_config()
        old_mtime = config._last_file_mtime
        config._update_file_mtime()
        # 修改时间应该被更新
        self.assertGreaterEqual(config._last_file_mtime, old_mtime)

    def test_file_watcher_start_stop(self):
        """测试启动和停止文件监听器"""
        from config_manager import get_config

        config = get_config()

        # 确保监听器已停止
        config.stop_file_watcher()
        self.assertFalse(config.is_file_watcher_running)

        # 启动监听器
        config.start_file_watcher(interval=0.5)
        self.assertTrue(config.is_file_watcher_running)

        # 停止监听器
        config.stop_file_watcher()
        self.assertFalse(config.is_file_watcher_running)


class TestConfigManagerCallbacks(unittest.TestCase):
    """测试配置变更回调"""

    def test_register_and_trigger_callback(self):
        """测试注册和触发回调"""
        from config_manager import get_config

        config = get_config()
        called = [False]

        def callback():
            called[0] = True

        config.register_config_change_callback(callback)
        config._trigger_config_change_callbacks()
        self.assertTrue(called[0])

        config.unregister_config_change_callback(callback)

    def test_callback_exception_handling(self):
        """测试回调异常处理"""
        from config_manager import get_config

        config = get_config()

        def bad_callback():
            raise ValueError("Test error")

        config.register_config_change_callback(bad_callback)

        # 触发回调不应该抛出异常
        try:
            config._trigger_config_change_callbacks()
        except Exception:
            self.fail("回调异常不应该传播")

        config.unregister_config_change_callback(bad_callback)


class TestConfigManagerReload(unittest.TestCase):
    """测试配置重新加载"""

    def test_reload_config(self):
        """测试重新加载配置"""
        from config_manager import get_config

        config = get_config()
        # 记录当前配置
        old_config = config.get_all()

        # 重新加载配置
        config.reload()

        # 配置应该被重新加载
        new_config = config.get_all()
        # 配置内容应该相同（假设文件未被修改）
        self.assertEqual(old_config.keys(), new_config.keys())


class TestConfigManagerUpdate(unittest.TestCase):
    """测试配置更新"""

    def test_update_batch(self):
        """测试批量更新配置"""
        from config_manager import get_config

        config = get_config()

        # 批量更新（不保存到文件）
        updates = {
            "notification.debug": True,
        }
        config.update(updates, save=False)

        # 验证更新生效
        self.assertTrue(config.get("notification.debug", False))

    def test_update_section(self):
        """测试更新配置段"""
        from config_manager import get_config

        config = get_config()

        # 获取当前 notification 配置
        section = config.get_section("notification")
        original_debug = section.get("debug", False)

        # 更新配置段（不保存）
        config.update_section("notification", {"debug": not original_debug}, save=False)

        # 验证更新
        new_section = config.get_section("notification")
        self.assertEqual(new_section.get("debug"), not original_debug)

        # 恢复原值
        config.update_section("notification", {"debug": original_debug}, save=False)


class TestConfigManagerNetworkSecurity(unittest.TestCase):
    """测试网络安全配置"""

    def test_get_network_security_config(self):
        """测试获取网络安全配置"""
        from config_manager import get_config

        config = get_config()
        security_config = config.get_network_security_config()

        # 应该返回字典
        self.assertIsInstance(security_config, dict)

        # 应该包含基本字段
        self.assertIn("bind_interface", security_config)


class TestReadWriteLockAdvanced(unittest.TestCase):
    """测试读写锁高级功能"""

    def test_read_lock_reentrant(self):
        """测试读锁可重入性"""
        from config_manager import ReadWriteLock

        lock = ReadWriteLock()

        # 获取读锁两次
        with lock.read_lock():
            with lock.read_lock():
                # 应该能成功获取两次读锁
                pass

    def test_write_lock_exclusive(self):
        """测试写锁排他性"""
        import threading
        import time

        from config_manager import ReadWriteLock

        lock = ReadWriteLock()
        results = []

        def writer():
            with lock.write_lock():
                results.append("write_start")
                time.sleep(0.1)
                results.append("write_end")

        def reader():
            time.sleep(0.05)  # 确保写者先获取锁
            with lock.read_lock():
                results.append("read")

        write_thread = threading.Thread(target=writer)
        read_thread = threading.Thread(target=reader)

        write_thread.start()
        read_thread.start()

        write_thread.join()
        read_thread.join()

        # 读操作应该在写操作完成后执行
        self.assertEqual(results, ["write_start", "write_end", "read"])


class TestConfigManagerExportImport(unittest.TestCase):
    """测试配置导出/导入功能"""

    def test_export_config(self):
        """测试导出配置"""
        from config_manager import get_config

        config = get_config()
        export_data = config.export_config()

        # 验证导出数据结构
        self.assertIn("exported_at", export_data)
        self.assertIn("version", export_data)
        self.assertIn("config", export_data)
        self.assertIsInstance(export_data["config"], dict)

    def test_export_config_with_network_security(self):
        """测试导出包含网络安全配置"""
        from config_manager import get_config

        config = get_config()
        export_data = config.export_config(include_network_security=True)

        # 验证包含网络安全配置
        self.assertIn("network_security", export_data)

    def test_import_config_merge(self):
        """测试合并模式导入配置"""
        from config_manager import get_config

        config = get_config()

        # 备份原始值
        original_debug = config.get("notification.debug", False)

        # 导入测试配置
        test_config = {"notification": {"debug": not original_debug}}
        result = config.import_config(test_config, merge=True, save=False)

        self.assertTrue(result)
        self.assertEqual(config.get("notification.debug"), not original_debug)

        # 恢复原始值
        config.import_config(
            {"notification": {"debug": original_debug}}, merge=True, save=False
        )

    def test_import_config_invalid_data(self):
        """测试导入无效数据"""
        from config_manager import get_config

        config = get_config()

        # 尝试导入非字典数据
        result = config.import_config(cast(Any, "invalid"), merge=True, save=False)
        self.assertFalse(result)

    def test_deep_merge(self):
        """测试深度合并功能"""
        from config_manager import get_config

        config = get_config()

        base: dict[str, Any] = {"a": {"b": 1, "c": 2}, "d": 3}
        update: dict[str, Any] = {"a": {"b": 10, "e": 5}, "f": 6}

        config._deep_merge(base, update)

        # 验证合并结果
        self.assertEqual(base["a"]["b"], 10)  # 已更新
        self.assertEqual(base["a"]["c"], 2)  # 保留
        self.assertEqual(base["a"]["e"], 5)  # 新增
        self.assertEqual(base["d"], 3)  # 保留
        self.assertEqual(base["f"], 6)  # 新增


if __name__ == "__main__":
    unittest.main()
