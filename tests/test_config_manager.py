#!/usr/bin/env python3
"""
AI Intervention Agent - 配置管理器单元测试

测试覆盖：
1. JSONC 解析
2. 配置读取/写入
3. 线程安全（读写锁）
4. 配置合并
5. network_security 特殊处理
"""

import json
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


class TestJsoncParser(unittest.TestCase):
    """测试 JSONC 解析器"""

    def test_parse_simple_json(self):
        """测试简单 JSON 解析"""
        from config_manager import parse_jsonc

        content = '{"key": "value", "number": 42}'
        result = parse_jsonc(content)

        self.assertEqual(result["key"], "value")
        self.assertEqual(result["number"], 42)

    def test_parse_single_line_comment(self):
        """测试单行注释"""
        from config_manager import parse_jsonc

        content = """
        {
            "key": "value", // 这是注释
            "number": 42
        }
        """
        result = parse_jsonc(content)

        self.assertEqual(result["key"], "value")
        self.assertEqual(result["number"], 42)

    def test_parse_multi_line_comment(self):
        """测试多行注释"""
        from config_manager import parse_jsonc

        content = """
        {
            /* 这是
            多行注释 */
            "key": "value"
        }
        """
        result = parse_jsonc(content)

        self.assertEqual(result["key"], "value")

    def test_parse_comment_in_string(self):
        """测试字符串中的注释符号"""
        from config_manager import parse_jsonc

        content = '{"url": "http://example.com // not a comment"}'
        result = parse_jsonc(content)

        self.assertEqual(result["url"], "http://example.com // not a comment")


class TestConfigManagerBasic(unittest.TestCase):
    """测试配置管理器基本功能"""

    @classmethod
    def setUpClass(cls):
        """测试类初始化"""
        cls.test_dir = tempfile.mkdtemp()
        cls.config_file = Path(cls.test_dir) / "test_config.jsonc"

    @classmethod
    def tearDownClass(cls):
        """测试类清理"""
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    def setUp(self):
        """每个测试前的准备"""
        # 创建测试配置文件
        test_config = {
            "notification": {"enabled": True, "sound_volume": 80},
            "web_ui": {"host": "127.0.0.1", "port": 8080},
        }

        with open(self.config_file, "w", encoding="utf-8") as f:
            json.dump(test_config, f)

    def test_get_simple_key(self):
        """测试获取简单键"""
        from config_manager import ConfigManager

        mgr = ConfigManager(str(self.config_file))

        section = mgr.get("notification")
        self.assertIsNotNone(section)
        self.assertEqual(section.get("enabled"), True)

    def test_get_nested_key(self):
        """测试获取嵌套键"""
        from config_manager import ConfigManager

        mgr = ConfigManager(str(self.config_file))

        value = mgr.get("notification.enabled")
        self.assertEqual(value, True)

    def test_get_default_value(self):
        """测试默认值"""
        from config_manager import ConfigManager

        mgr = ConfigManager(str(self.config_file))

        value = mgr.get("nonexistent.key", "default")
        self.assertEqual(value, "default")

    def test_set_value(self):
        """测试设置值"""
        from config_manager import ConfigManager

        mgr = ConfigManager(str(self.config_file))

        mgr.set("notification.enabled", False, save=False)

        value = mgr.get("notification.enabled")
        self.assertEqual(value, False)

    def test_get_section(self):
        """测试获取配置段"""
        from config_manager import ConfigManager

        mgr = ConfigManager(str(self.config_file))

        section = mgr.get_section("notification")
        self.assertIsInstance(section, dict)
        self.assertIn("enabled", section)

    def test_get_section_cache_invalidation_on_set(self):
        """测试 set() 会失效 get_section() 的缓存，避免返回旧值"""
        from config_manager import ConfigManager

        mgr = ConfigManager(str(self.config_file))

        # 先读取一次，写入缓存
        section1 = mgr.get_section("notification")
        self.assertEqual(section1.get("enabled"), True)

        # 修改配置（不保存）
        mgr.set("notification.enabled", False, save=False)

        # 再次读取应立即反映最新值（如果缓存未失效会返回 True）
        section2 = mgr.get_section("notification")
        self.assertEqual(section2.get("enabled"), False)


class TestConfigManagerThreadSafety(unittest.TestCase):
    """测试配置管理器线程安全"""

    @classmethod
    def setUpClass(cls):
        """测试类初始化"""
        cls.test_dir = tempfile.mkdtemp()
        cls.config_file = Path(cls.test_dir) / "test_config.jsonc"

    @classmethod
    def tearDownClass(cls):
        """测试类清理"""
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    def setUp(self):
        """每个测试前的准备"""
        test_config = {"notification": {"enabled": True}, "counter": 0}

        with open(self.config_file, "w", encoding="utf-8") as f:
            json.dump(test_config, f)

        from config_manager import ConfigManager

        self.mgr = ConfigManager(str(self.config_file))
        self.errors = []

    def test_concurrent_read(self):
        """测试并发读取"""

        def reader():
            try:
                for _ in range(50):
                    _ = self.mgr.get("notification.enabled")
                    time.sleep(0.001)
            except Exception as e:
                self.errors.append(e)

        threads = [threading.Thread(target=reader) for _ in range(5)]

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        self.assertEqual(len(self.errors), 0)

    def test_concurrent_read_write(self):
        """测试并发读写"""

        def reader():
            try:
                for _ in range(30):
                    _ = self.mgr.get("notification.enabled")
                    time.sleep(0.001)
            except Exception as e:
                self.errors.append(e)

        def writer():
            try:
                for i in range(20):
                    self.mgr.set("counter", i, save=False)
                    time.sleep(0.001)
            except Exception as e:
                self.errors.append(e)

        threads = [threading.Thread(target=reader) for _ in range(3)] + [
            threading.Thread(target=writer) for _ in range(2)
        ]

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        self.assertEqual(len(self.errors), 0)


class TestReadWriteLock(unittest.TestCase):
    """测试读写锁"""

    def test_multiple_readers(self):
        """测试多读者并发"""
        from config_manager import ReadWriteLock

        lock = ReadWriteLock()
        results = []

        def reader(n):
            with lock.read_lock():
                results.append(f"reader-{n}-start")
                time.sleep(0.01)
                results.append(f"reader-{n}-end")

        threads = [threading.Thread(target=reader, args=(i,)) for i in range(3)]

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        # 所有读者应该能并发执行
        self.assertEqual(len(results), 6)

    def test_writer_exclusive(self):
        """测试写者独占"""
        from config_manager import ReadWriteLock

        lock = ReadWriteLock()
        shared_value = [0]

        def writer():
            with lock.write_lock():
                temp = shared_value[0]
                time.sleep(0.01)
                shared_value[0] = temp + 1

        threads = [threading.Thread(target=writer) for _ in range(5)]

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        # 写操作应该正确串行执行
        self.assertEqual(shared_value[0], 5)


class TestNetworkSecurityConfig(unittest.TestCase):
    """测试 network_security 特殊处理"""

    @classmethod
    def setUpClass(cls):
        """测试类初始化"""
        cls.test_dir = tempfile.mkdtemp()
        cls.config_file = Path(cls.test_dir) / "test_config.jsonc"

    @classmethod
    def tearDownClass(cls):
        """测试类清理"""
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    def setUp(self):
        """每个测试前的准备"""
        test_config = {
            "notification": {"enabled": True},
            "network_security": {
                "bind_interface": "0.0.0.0",
                "allowed_networks": ["127.0.0.0/8"],
                "enable_access_control": True,
            },
        }

        with open(self.config_file, "w", encoding="utf-8") as f:
            json.dump(test_config, f)

    def test_network_security_not_in_memory(self):
        """测试 network_security 不加载到内存"""
        from config_manager import ConfigManager

        mgr = ConfigManager(str(self.config_file))

        # network_security 不应在内存配置中
        all_config = mgr.get_all()
        self.assertNotIn("network_security", all_config)

    def test_get_network_security_config(self):
        """测试获取 network_security 配置"""
        from config_manager import ConfigManager

        mgr = ConfigManager(str(self.config_file))

        ns_config = mgr.get_network_security_config()

        self.assertIsInstance(ns_config, dict)
        self.assertEqual(ns_config.get("bind_interface"), "0.0.0.0")
        self.assertIn("127.0.0.0/8", ns_config.get("allowed_networks", []))


def run_tests():
    """运行所有测试"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    suite.addTests(loader.loadTestsFromTestCase(TestJsoncParser))
    suite.addTests(loader.loadTestsFromTestCase(TestConfigManagerBasic))
    suite.addTests(loader.loadTestsFromTestCase(TestConfigManagerThreadSafety))
    suite.addTests(loader.loadTestsFromTestCase(TestReadWriteLock))
    suite.addTests(loader.loadTestsFromTestCase(TestNetworkSecurityConfig))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
