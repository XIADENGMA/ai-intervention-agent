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
import os
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

    def test_parse_block_comment_markers_in_string(self):
        """测试字符串中的 /* */ 不应被当成注释"""
        from config_manager import parse_jsonc

        content = '{"message": "keep /* literal */ text"}'
        result = parse_jsonc(content)

        self.assertEqual(result["message"], "keep /* literal */ text")


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

    def test_jsonc_save_does_not_cross_update_same_named_keys(self):
        """JSONC 保留注释保存：同名键（如 enabled）不应跨 section 误更新，且 URL 不应被截断"""
        from config_manager import ConfigManager, parse_jsonc

        jsonc_content = """
        {
          // 通知配置（用于验证同名键 enabled 不被误改）
          "notification": {
            "enabled": true,
            "bark_url": "https://example.com/api//not_comment" // URL 中的 // 不是注释
          },
          // mDNS 配置（同样包含 enabled）
          "mdns": {
            "enabled": null
          }
        }
        """.strip()
        self.config_file.write_text(jsonc_content, encoding="utf-8")

        mgr = ConfigManager(str(self.config_file))

        # 仅更新 mdns.enabled，notification.enabled 必须保持原值 true
        mgr.set("mdns.enabled", False, save=True)
        mgr.force_save()

        saved = self.config_file.read_text(encoding="utf-8")
        self.assertIn('"bark_url": "https://example.com/api//not_comment"', saved)

        parsed = parse_jsonc(saved)
        self.assertEqual(parsed["notification"]["enabled"], True)
        self.assertEqual(parsed["mdns"]["enabled"], False)
        self.assertEqual(
            parsed["notification"]["bark_url"], "https://example.com/api//not_comment"
        )

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

    def test_reload_invalid_json_keeps_previous_config(self):
        """配置文件损坏/编辑中间态：reload 不应把内存配置回退到默认值"""
        from config_manager import ConfigManager

        # 写入一个非默认端口，便于验证是否发生“回退到默认值（8080）”
        test_config = {
            "notification": {"enabled": True, "sound_volume": 80},
            "web_ui": {"host": "127.0.0.1", "port": 18080},
        }
        with open(self.config_file, "w", encoding="utf-8") as f:
            json.dump(test_config, f)

        mgr = ConfigManager(str(self.config_file))
        self.assertEqual(mgr.get("web_ui.port"), 18080)

        # 将文件写成非法 JSON（模拟编辑中间态/损坏）
        with open(self.config_file, "w", encoding="utf-8") as f:
            f.write("{invalid json")

        # reload 不应抛异常，同时应保留上一次成功加载的配置
        mgr.reload()
        self.assertEqual(mgr.get("web_ui.port"), 18080)

    def test_reload_duplicate_allowed_networks_keeps_previous_config(self):
        """重复数组定义（allowed_networks）应被识别，reload 后应保留上次成功配置"""
        from config_manager import ConfigManager

        # 先写入一份“正确配置”，建立基线
        baseline_config = {
            "notification": {"enabled": True},
            "web_ui": {"host": "127.0.0.1", "port": 18081},
        }
        with open(self.config_file, "w", encoding="utf-8") as f:
            json.dump(baseline_config, f)

        mgr = ConfigManager(str(self.config_file))
        self.assertEqual(mgr.get("web_ui.port"), 18081)

        # 写入可解析但包含重复 allowed_networks 定义的 JSONC（json.loads 会保留最后一个键）
        duplicated = """
        {
          "web_ui": { "host": "127.0.0.1", "port": 18082 },
          "network_security": {
            "allowed_networks": ["127.0.0.0/8"],
            "allowed_networks": ["10.0.0.0/8"]
          }
        }
        """.strip()
        with open(self.config_file, "w", encoding="utf-8") as f:
            f.write(duplicated)

        # reload 后应回滚到 baseline（而不是应用损坏配置）
        mgr.reload()
        self.assertEqual(mgr.get("web_ui.port"), 18081)


class TestFindConfigFileOverride(unittest.TestCase):
    """测试 find_config_file() 的环境变量覆盖逻辑"""

    def test_override_dir_trailing_slash_appends_filename_even_if_missing(self):
        """环境变量指向目录（以 / 结尾）时应拼接 config.jsonc，即使目录尚不存在"""
        from config_manager import find_config_file

        old = os.environ.get("AI_INTERVENTION_AGENT_CONFIG_FILE")
        try:
            with tempfile.TemporaryDirectory() as tmp:
                missing_dir = Path(tmp) / "not-exist-yet"
                os.environ["AI_INTERVENTION_AGENT_CONFIG_FILE"] = str(missing_dir) + "/"
                resolved = find_config_file("config.jsonc")
                self.assertEqual(resolved, missing_dir / "config.jsonc")
        finally:
            if old is None:
                os.environ.pop("AI_INTERVENTION_AGENT_CONFIG_FILE", None)
            else:
                os.environ["AI_INTERVENTION_AGENT_CONFIG_FILE"] = old

    def test_override_existing_dir_appends_filename(self):
        """环境变量指向已存在目录时应拼接 config.jsonc"""
        from config_manager import find_config_file

        old = os.environ.get("AI_INTERVENTION_AGENT_CONFIG_FILE")
        try:
            with tempfile.TemporaryDirectory() as tmp:
                os.environ["AI_INTERVENTION_AGENT_CONFIG_FILE"] = tmp
                resolved = find_config_file("config.jsonc")
                self.assertEqual(resolved, Path(tmp) / "config.jsonc")
        finally:
            if old is None:
                os.environ.pop("AI_INTERVENTION_AGENT_CONFIG_FILE", None)
            else:
                os.environ["AI_INTERVENTION_AGENT_CONFIG_FILE"] = old


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
                "access_control_enabled": True,
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


class TestConfigManagerAdvanced(unittest.TestCase):
    """配置管理器高级测试"""

    @classmethod
    def setUpClass(cls):
        """测试类初始化"""
        cls.test_dir = tempfile.mkdtemp()

    @classmethod
    def tearDownClass(cls):
        """测试类清理"""
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    def test_jsonc_with_trailing_comma(self):
        """测试带尾随逗号的 JSONC"""
        from config_manager import parse_jsonc

        # JSONC 应该能处理尾随逗号（虽然标准 JSON 不允许）
        content = '{"key": "value",}'
        # 这可能会抛出异常，因为 parse_jsonc 只移除注释
        with self.assertRaises(json.JSONDecodeError):
            parse_jsonc(content)

    def test_update_method(self):
        """测试批量更新方法"""
        from config_manager import ConfigManager

        config_file = Path(self.test_dir) / "update_test.json"
        with open(config_file, "w") as f:
            json.dump({"a": 1, "b": 2}, f)

        mgr = ConfigManager(str(config_file))

        # 批量更新
        mgr.update({"a": 10, "c": 30}, save=False)

        self.assertEqual(mgr.get("a"), 10)
        self.assertEqual(mgr.get("c"), 30)

    def test_force_save(self):
        """测试强制保存"""
        from config_manager import ConfigManager

        config_file = Path(self.test_dir) / "force_save_test.json"
        with open(config_file, "w") as f:
            json.dump({"test": True}, f)

        mgr = ConfigManager(str(config_file))
        mgr.set("test", False, save=False)
        mgr.force_save()

        # 重新加载验证
        with open(config_file, "r") as f:
            saved = json.load(f)

        self.assertEqual(saved.get("test"), False)

    def test_reload_config(self):
        """测试配置重载"""
        from config_manager import ConfigManager

        config_file = Path(self.test_dir) / "reload_test.json"
        with open(config_file, "w") as f:
            json.dump({"value": 1}, f)

        mgr = ConfigManager(str(config_file))
        self.assertEqual(mgr.get("value"), 1)

        # 外部修改文件
        with open(config_file, "w") as f:
            json.dump({"value": 2}, f)

        # 重载
        mgr.reload()

        self.assertEqual(mgr.get("value"), 2)

    def test_get_all_config(self):
        """测试获取所有配置"""
        from config_manager import ConfigManager

        config_file = Path(self.test_dir) / "getall_test.json"
        with open(config_file, "w") as f:
            json.dump({"a": 1, "b": {"c": 2}}, f)

        mgr = ConfigManager(str(config_file))
        all_config = mgr.get_all()

        self.assertIn("a", all_config)
        self.assertIn("b", all_config)

    def test_update_section(self):
        """测试更新配置段"""
        from config_manager import ConfigManager

        config_file = Path(self.test_dir) / "section_test.json"
        with open(config_file, "w") as f:
            json.dump({"notification": {"enabled": True}}, f)

        mgr = ConfigManager(str(config_file))

        # 更新配置段
        mgr.update_section(
            "notification", {"enabled": False, "new_key": "value"}, save=False
        )

        section = mgr.get_section("notification")
        self.assertEqual(section.get("enabled"), False)
        self.assertEqual(section.get("new_key"), "value")


class TestConfigManagerJsoncSave(unittest.TestCase):
    """JSONC 保存功能测试"""

    @classmethod
    def setUpClass(cls):
        """测试类初始化"""
        cls.test_dir = tempfile.mkdtemp()

    @classmethod
    def tearDownClass(cls):
        """测试类清理"""
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    def test_save_preserves_content(self):
        """测试保存保留内容"""
        from config_manager import ConfigManager

        config_file = Path(self.test_dir) / "preserve_test.jsonc"
        initial_content = """{
    // 配置注释
    "key": "value",
    "number": 42
}"""

        with open(config_file, "w") as f:
            f.write(initial_content)

        mgr = ConfigManager(str(config_file))
        mgr.set("number", 100, save=True)

        # 等待延迟保存
        time.sleep(0.01)  # 减少等待时间
        mgr.force_save()

        # 读取保存后的内容
        with open(config_file, "r") as f:
            saved_content = f.read()

        # 验证值已更新
        from config_manager import parse_jsonc

        saved_config = parse_jsonc(saved_content)
        self.assertEqual(saved_config.get("number"), 100)


# ============================================================================
# notification_manager.py 覆盖率提升
# ============================================================================


class TestConfigManagerDelayedSave(unittest.TestCase):
    """配置管理器延迟保存测试"""

    @classmethod
    def setUpClass(cls):
        """测试类初始化"""
        cls.test_dir = tempfile.mkdtemp()

    @classmethod
    def tearDownClass(cls):
        """测试类清理"""
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    def test_delayed_save(self):
        """测试延迟保存"""
        from config_manager import ConfigManager

        config_file = Path(self.test_dir) / "delayed_save.json"
        with open(config_file, "w") as f:
            json.dump({"test": 1}, f)

        mgr = ConfigManager(str(config_file))

        # 设置值，启用延迟保存
        mgr.set("test", 2, save=True)

        # 强制保存
        mgr.force_save()

        # 验证保存成功
        with open(config_file, "r") as f:
            saved = json.load(f)

        self.assertEqual(saved.get("test"), 2)


class TestConfigManagerNestedConfig(unittest.TestCase):
    """嵌套配置测试"""

    @classmethod
    def setUpClass(cls):
        """测试类初始化"""
        cls.test_dir = tempfile.mkdtemp()

    @classmethod
    def tearDownClass(cls):
        """测试类清理"""
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    def test_nested_get(self):
        """测试嵌套获取"""
        from config_manager import ConfigManager

        config_file = Path(self.test_dir) / "nested.json"
        with open(config_file, "w") as f:
            json.dump({"level1": {"level2": {"level3": "deep_value"}}}, f)

        mgr = ConfigManager(str(config_file))

        # 获取嵌套值
        section = mgr.get_section("level1")
        self.assertIsNotNone(section)
        self.assertIn("level2", section)

    def test_nested_update(self):
        """测试嵌套更新"""
        from config_manager import ConfigManager

        config_file = Path(self.test_dir) / "nested_update.json"
        with open(config_file, "w") as f:
            json.dump({"section": {"key1": "value1"}}, f)

        mgr = ConfigManager(str(config_file))

        # 更新嵌套配置段
        mgr.update_section("section", {"key2": "value2"}, save=False)

        section = mgr.get_section("section")
        self.assertEqual(section.get("key1"), "value1")
        self.assertEqual(section.get("key2"), "value2")


class TestReadWriteLockContextManager(unittest.TestCase):
    """读写锁测试"""

    def test_read_lock_context_manager(self):
        """测试读锁上下文管理器"""
        from config_manager import ReadWriteLock

        lock = ReadWriteLock()

        # 使用上下文管理器获取读锁
        with lock.read_lock():
            # 在读锁内部可以执行操作
            self.assertEqual(lock._readers, 1)

        # 离开上下文后读者计数应该为 0
        self.assertEqual(lock._readers, 0)

    def test_write_lock_context_manager(self):
        """测试写锁上下文管理器"""
        from config_manager import ReadWriteLock

        lock = ReadWriteLock()

        # 使用上下文管理器获取写锁
        with lock.write_lock():
            # 在写锁内部可以执行操作
            pass

    def test_concurrent_read_context(self):
        """测试并发读（上下文管理器）"""
        from config_manager import ReadWriteLock

        lock = ReadWriteLock()
        results = []

        def reader(id):
            with lock.read_lock():
                time.sleep(0.01)
                results.append(f"read_{id}")

        threads = [threading.Thread(target=reader, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 所有读操作应该完成
        self.assertEqual(len(results), 5)


class TestParseJsonc(unittest.TestCase):
    """JSONC 解析测试"""

    def test_single_line_comment(self):
        """测试单行注释"""
        from config_manager import parse_jsonc

        content = """
{
    // 这是注释
    "key": "value"
}"""
        result = parse_jsonc(content)

        self.assertEqual(result["key"], "value")

    def test_multi_line_comment(self):
        """测试多行注释"""
        from config_manager import parse_jsonc

        content = """
{
    /* 这是
       多行注释 */
    "key": "value"
}"""
        result = parse_jsonc(content)

        self.assertEqual(result["key"], "value")

    def test_comment_in_string(self):
        """测试字符串中的注释符号"""
        from config_manager import parse_jsonc

        content = """
{
    "url": "http://example.com/path"
}"""
        result = parse_jsonc(content)

        self.assertEqual(result["url"], "http://example.com/path")


class TestConfigManagerBoolConversion(unittest.TestCase):
    """配置布尔值转换测试"""

    @classmethod
    def setUpClass(cls):
        """测试类初始化"""
        cls.test_dir = tempfile.mkdtemp()

    @classmethod
    def tearDownClass(cls):
        """测试类清理"""
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    def test_bool_true_values(self):
        """测试各种真值"""
        from config_manager import ConfigManager

        config_file = Path(self.test_dir) / "bool_true.json"
        with open(config_file, "w") as f:
            json.dump(
                {
                    "bool_true": True,
                    "string_true": "true",
                    "string_yes": "yes",
                    "number_one": 1,
                },
                f,
            )

        mgr = ConfigManager(str(config_file))

        self.assertTrue(mgr.get("bool_true"))
        self.assertEqual(mgr.get("string_true"), "true")

    def test_bool_false_values(self):
        """测试各种假值"""
        from config_manager import ConfigManager

        config_file = Path(self.test_dir) / "bool_false.json"
        with open(config_file, "w") as f:
            json.dump(
                {"bool_false": False, "string_false": "false", "number_zero": 0}, f
            )

        mgr = ConfigManager(str(config_file))

        self.assertFalse(mgr.get("bool_false"))


# ============================================================================
# 边界条件测试
# ============================================================================


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


class TestConfigManagerNetworkSecurity(unittest.TestCase):
    """网络安全配置测试"""

    def test_get_network_security_config(self):
        """测试获取网络安全配置"""
        from config_manager import config_manager

        security_config = config_manager.get_network_security_config()

        self.assertIsNotNone(security_config)
        self.assertIsInstance(security_config, dict)

    def test_network_security_has_bind_interface(self):
        """测试网络安全配置包含绑定接口"""
        from config_manager import config_manager

        security_config = config_manager.get_network_security_config()

        # 应该有 bind_interface 字段
        self.assertIn("bind_interface", security_config)


class TestConfigManagerWebUI(unittest.TestCase):
    """Web UI 配置测试"""

    def test_get_web_ui_config(self):
        """测试获取 Web UI 配置"""
        from config_manager import config_manager

        web_ui_config = config_manager.get_section("web_ui")

        self.assertIsNotNone(web_ui_config)


class TestConfigManagerNotificationSection(unittest.TestCase):
    """通知配置段测试"""

    def test_get_notification_section(self):
        """测试获取通知配置段"""
        from config_manager import config_manager

        notification = config_manager.get_section("notification")

        self.assertIsNotNone(notification)
        self.assertIsInstance(notification, dict)


class TestConfigManagerDefaults(unittest.TestCase):
    """默认值测试"""

    def test_get_with_default(self):
        """测试获取不存在的键返回默认值"""
        from config_manager import config_manager

        result = config_manager.get("nonexistent_key_12345", "default_value")

        self.assertEqual(result, "default_value")

    def test_get_section_default(self):
        """测试获取不存在的配置段返回默认值"""
        from config_manager import config_manager

        result = config_manager.get_section("nonexistent_section_12345")

        # 应该返回空字典或 None
        self.assertTrue(result is None or result == {})


# ============================================================================
# notification_providers.py 剩余路径测试
# ============================================================================


class TestConfigManagerFinalPush(unittest.TestCase):
    """Config Manager 最终冲刺测试"""

    def test_get_all_sections(self):
        """测试获取所有配置段"""
        from config_manager import config_manager

        all_config = config_manager.get_all()

        self.assertIsInstance(all_config, dict)
        self.assertGreater(len(all_config), 0)

    def test_get_multiple_sections(self):
        """测试获取多个配置段"""
        from config_manager import config_manager

        # 获取多个配置段
        notification = config_manager.get_section("notification")
        web_ui = config_manager.get_section("web_ui")

        self.assertIsNotNone(notification)
        self.assertIsNotNone(web_ui)


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
