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
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock, patch

from exceptions import ConfigValidationError


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
        cls.config_file = Path(cls.test_dir) / "test_config.toml"

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

    def test_toml_save_does_not_cross_update_same_named_keys(self):
        """TOML 保留注释保存：同名键（如 enabled）不应跨 section 误更新"""
        from config_manager import ConfigManager

        toml_content = """\
# 通知配置
[notification]
enabled = true
bark_url = "https://example.com/api/push"

# mDNS 配置
[mdns]
enabled = "auto"
"""
        toml_file = self.config_file.with_suffix(".toml")
        toml_file.write_text(toml_content, encoding="utf-8")

        mgr = ConfigManager(str(toml_file))

        mgr.set("mdns.enabled", False, save=True)
        mgr.force_save()

        saved = toml_file.read_text(encoding="utf-8")
        import tomlkit

        parsed = tomlkit.parse(saved)
        self.assertEqual(parsed["notification"]["enabled"], True)  # type: ignore[index]
        self.assertEqual(parsed["mdns"]["enabled"], False)  # type: ignore[index]
        self.assertEqual(
            parsed["notification"]["bark_url"],  # type: ignore[index]
            "https://example.com/api/push",
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

    def test_reload_invalid_toml_keeps_previous_config(self):
        """配置文件损坏/编辑中间态：reload 不应把内存配置回退到默认值"""
        from config_manager import ConfigManager

        test_content = """\
[notification]
enabled = true
sound_volume = 80

[web_ui]
host = "127.0.0.1"
port = 18080
"""
        self.config_file.write_text(test_content, encoding="utf-8")

        mgr = ConfigManager(str(self.config_file))
        self.assertEqual(mgr.get("web_ui.port"), 18080)

        self.config_file.write_text("[[invalid toml", encoding="utf-8")

        mgr.reload()
        self.assertEqual(mgr.get("web_ui.port"), 18080)

    def test_reload_duplicate_keys_toml_keeps_previous_config(self):
        """TOML 解析器会拒绝重复键，reload 后应保留上次成功配置"""
        from config_manager import ConfigManager

        baseline = """\
[notification]
enabled = true

[web_ui]
host = "127.0.0.1"
port = 18081
"""
        self.config_file.write_text(baseline, encoding="utf-8")

        mgr = ConfigManager(str(self.config_file))
        self.assertEqual(mgr.get("web_ui.port"), 18081)

        # TOML 格式不允许重复表头 → 解析器会报错
        duplicated = """\
[web_ui]
host = "127.0.0.1"
port = 18082

[web_ui]
port = 18083
"""
        self.config_file.write_text(duplicated, encoding="utf-8")

        mgr.reload()
        self.assertEqual(mgr.get("web_ui.port"), 18081)


class TestFindConfigFileOverride(unittest.TestCase):
    """测试 find_config_file() 的环境变量覆盖逻辑"""

    def test_override_dir_trailing_slash_appends_filename_even_if_missing(self):
        """环境变量指向目录（以 / 结尾）时应拼接 config.toml，即使目录尚不存在"""
        from config_manager import find_config_file

        old = os.environ.get("AI_INTERVENTION_AGENT_CONFIG_FILE")
        try:
            with tempfile.TemporaryDirectory() as tmp:
                missing_dir = Path(tmp) / "not-exist-yet"
                os.environ["AI_INTERVENTION_AGENT_CONFIG_FILE"] = str(missing_dir) + "/"
                resolved = find_config_file("config.toml")
                self.assertEqual(resolved, missing_dir / "config.toml")
        finally:
            if old is None:
                os.environ.pop("AI_INTERVENTION_AGENT_CONFIG_FILE", None)
            else:
                os.environ["AI_INTERVENTION_AGENT_CONFIG_FILE"] = old

    def test_override_existing_dir_appends_filename(self):
        """环境变量指向已存在目录时应拼接 config.toml"""
        from config_manager import find_config_file

        old = os.environ.get("AI_INTERVENTION_AGENT_CONFIG_FILE")
        try:
            with tempfile.TemporaryDirectory() as tmp:
                os.environ["AI_INTERVENTION_AGENT_CONFIG_FILE"] = tmp
                resolved = find_config_file("config.toml")
                self.assertEqual(resolved, Path(tmp) / "config.toml")
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
        cls.config_file = Path(cls.test_dir) / "test_config.toml"

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
        cls.config_file = Path(cls.test_dir) / "test_config.toml"

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
        """测试带尾随逗号的 JSONC — parse_jsonc 应正确处理"""
        from config_manager import parse_jsonc

        result = parse_jsonc('{"key": "value",}')
        self.assertEqual(result, {"key": "value"})

        result2 = parse_jsonc('{"arr": [1, 2, 3,]}')
        self.assertEqual(result2, {"arr": [1, 2, 3]})

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
        with open(config_file) as f:
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
        """测试 TOML 保存保留内容"""
        import tomlkit

        from config_manager import ConfigManager

        config_file = Path(self.test_dir) / "preserve_test.toml"
        initial_content = """\
# 配置注释
key = "value"
number = 42
"""

        with open(config_file, "w") as f:
            f.write(initial_content)

        mgr = ConfigManager(str(config_file))
        mgr.set("number", 100, save=True)

        time.sleep(0.01)
        mgr.force_save()

        with open(config_file) as f:
            saved_content = f.read()

        saved_config = tomlkit.parse(saved_content).unwrap()  # type: ignore[union-attr]
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
        with open(config_file) as f:
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
            config_path = Path(tmpdir) / "test_config.toml"
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


class TestConfigManagerFileWatcherBasic(unittest.TestCase):
    """测试文件监听功能"""

    def test_update_file_mtime(self):
        """测试更新文件修改时间：调用后应与磁盘 mtime 一致"""
        from config_manager import get_config

        config = get_config()
        config._update_file_mtime()
        expected = config.config_file.stat().st_mtime
        self.assertEqual(config._last_file_mtime, expected)

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


class TestReloadDiscardsPendingChanges(unittest.TestCase):
    """reload 时必须清空 ``_pending_changes`` + 取消 ``_save_timer``。

    文档参见 ``ConfigManager._load_config`` 的 docstring；这里
    精确锁住"external-edit-wins"语义。
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.path = Path(self.tmpdir) / "rl.toml"
        self.path.write_text(
            '[notification]\nbark_url = "https://A"\n', encoding="utf-8"
        )

    def tearDown(self):
        try:
            shutil.rmtree(self.tmpdir, ignore_errors=True)
        except Exception:
            pass

    def test_pending_changes_cleared_on_reload(self):
        """``cfg.set(..., save=True)`` → reload → pending 必须被清空"""
        from config_manager import ConfigManager

        mgr = ConfigManager(str(self.path))
        mgr.stop_file_watcher()
        try:
            mgr.set("notification.bark_url", "https://process-side", save=True)
            self.assertNotEqual(mgr._pending_changes, {})
            mgr.reload()
            self.assertEqual(
                mgr._pending_changes,
                {},
                "reload() 必须清空 _pending_changes，否则 _delayed_save "
                "fires 时会把进程内 stale-set 默默写回，覆盖外部编辑",
            )
        finally:
            mgr.shutdown()

    def test_save_timer_cancelled_on_reload(self):
        """reload 必须取消 ``_save_timer``，timer 不能在 reload 后还能 fire"""
        from config_manager import ConfigManager

        mgr = ConfigManager(str(self.path))
        mgr.stop_file_watcher()
        try:
            mgr.set("notification.bark_url", "https://process-side", save=True)
            timer = mgr._save_timer
            self.assertIsNotNone(timer)
            mgr.reload()
            self.assertIsNone(
                mgr._save_timer,
                "reload() 必须取消 _save_timer 并置 None，否则旧 timer "
                "回调可能在 reload 后异步写盘，污染 disk-truth",
            )
        finally:
            mgr.shutdown()

    def test_external_edit_wins_after_reload(self):
        """完整 race 重现：set → 模拟外部 edit → reload → disk 必须保留外部值"""
        from config_manager import ConfigManager

        mgr = ConfigManager(str(self.path))
        mgr.stop_file_watcher()
        try:
            # T=0: 进程内 set（pending）
            mgr.set("notification.bark_url", "https://process-side", save=True)

            # T=1: 外部编辑 disk
            self.path.write_text(
                '[notification]\nbark_url = "https://external"\n',
                encoding="utf-8",
            )

            # T=2: reload（模拟 file_watcher）
            mgr.reload()

            # T=3+: 即使 _delayed_save 被外力 trigger，pending 已空 → no-op
            mgr._delayed_save()

            # disk 必须仍是 "external"，不应被 stale "process-side" 覆盖
            disk_text = self.path.read_text(encoding="utf-8")
            self.assertIn(
                "https://external",
                disk_text,
                "external-edit-wins 失败：进程内 stale set 覆盖了外部编辑",
            )
            self.assertNotIn(
                "https://process-side",
                disk_text,
                "external-edit-wins 失败：disk 仍残留 stale process-side 值",
            )
        finally:
            mgr.shutdown()

    def test_initial_load_does_not_warn_on_empty_pending(self):
        """``__init__`` 调用 ``_load_config`` 时 pending 必为空，no-op 路径不应报警"""
        from config_manager import ConfigManager

        with self.assertNoLogs(level="WARNING"):
            mgr = ConfigManager(str(self.path))
            try:
                self.assertEqual(mgr._pending_changes, {})
            finally:
                mgr.shutdown()


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


class TestConfigManagerNetworkSecurityBasic(unittest.TestCase):
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


class TestReadWriteLockStress(unittest.TestCase):
    """测试读写锁高级功能"""

    def test_read_lock_reentrant(self):
        """测试读锁可重入性"""
        from config_manager import ReadWriteLock

        lock = ReadWriteLock()

        # 获取读锁两次
        with lock.read_lock(), lock.read_lock():
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

    def test_restore_config_restores_network_security(self):
        """restore_config 应恢复备份中的 network_security"""
        import tempfile
        from pathlib import Path

        from config_manager import ConfigManager

        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "test_config.toml"
            backup_path = Path(temp_dir) / "backup.json"

            config_path.write_text(
                """\
[web_ui]
port = 8080

[network_security]
allowed_networks = ["127.0.0.0/8"]
blocked_ips = []
access_control_enabled = true
""",
                encoding="utf-8",
            )

            manager = ConfigManager(str(config_path))
            manager.backup_config(str(backup_path))

            config_path.write_text(
                """\
[web_ui]
port = 9000

[network_security]
allowed_networks = ["10.0.0.0/8"]
blocked_ips = ["8.8.8.8"]
access_control_enabled = false
""",
                encoding="utf-8",
            )

            self.assertTrue(manager.restore_config(str(backup_path)))
            restored = manager.get_network_security_config()

            self.assertEqual(restored["allowed_networks"], ["127.0.0.0/8"])
            self.assertEqual(restored["blocked_ips"], [])
            self.assertTrue(restored["access_control_enabled"])


class TestConfigManagerAdvancedFeatures(unittest.TestCase):
    """配置管理器高级功能测试"""

    @classmethod
    def setUpClass(cls):
        """测试类初始化"""
        cls.test_dir = tempfile.mkdtemp()

    @classmethod
    def tearDownClass(cls):
        """测试类清理"""
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    def test_config_with_comments(self):
        """测试带注释的 TOML 配置"""
        from config_manager import ConfigManager

        config_file = Path(self.test_dir) / "comments.toml"
        content = """\
# 这是 TOML 注释
key1 = "value1"
# 第二个键
key2 = "value2"
"""

        with open(config_file, "w") as f:
            f.write(content)

        mgr = ConfigManager(str(config_file))

        self.assertEqual(mgr.get("key1"), "value1")
        self.assertEqual(mgr.get("key2"), "value2")

    def test_config_deep_nested(self):
        """测试深度嵌套配置"""
        from config_manager import ConfigManager

        config_file = Path(self.test_dir) / "deep_nested.json"
        config = {"level1": {"level2": {"level3": {"level4": {"value": "deep"}}}}}

        with open(config_file, "w") as f:
            json.dump(config, f)

        mgr = ConfigManager(str(config_file))

        level1 = mgr.get_section("level1")
        self.assertIn("level2", level1)

    def test_config_array_values(self):
        """测试数组值配置"""
        from config_manager import ConfigManager

        config_file = Path(self.test_dir) / "array.json"
        config = {"items": ["item1", "item2", "item3"], "numbers": [1, 2, 3, 4, 5]}

        with open(config_file, "w") as f:
            json.dump(config, f)

        mgr = ConfigManager(str(config_file))

        items = mgr.get("items")
        self.assertEqual(len(items), 3)

    def test_config_special_characters(self):
        """测试特殊字符配置"""
        from config_manager import ConfigManager

        config_file = Path(self.test_dir) / "special.json"
        config = {
            "url": "https://example.com/path?query=value&other=123",
            "unicode": "中文测试 日本語 한국어",
            "emoji": "🎉 🚀 ✅",
        }

        with open(config_file, "w") as f:
            json.dump(config, f, ensure_ascii=False)

        mgr = ConfigManager(str(config_file))

        self.assertIn("https://", mgr.get("url"))
        self.assertIn("中文", mgr.get("unicode"))


class TestConfigManagerNetworkSecurityAdvanced(unittest.TestCase):
    """网络安全配置高级测试"""

    def test_get_network_security_config_full(self):
        """测试获取完整网络安全配置"""
        from config_manager import config_manager

        security = config_manager.get_network_security_config()

        # 检查必要字段
        self.assertIn("bind_interface", security)
        self.assertIn("allowed_networks", security)
        # 支持新旧两种配置名称
        self.assertTrue("access_control_enabled" in security)

    def test_network_security_allowed_networks(self):
        """测试允许的网络列表"""
        from config_manager import config_manager

        security = config_manager.get_network_security_config()
        allowed = security.get("allowed_networks", [])

        self.assertIsInstance(allowed, list)


class TestReadWriteLockDeep(unittest.TestCase):
    """读写锁高级测试"""

    def test_write_lock_exclusive(self):
        """测试写锁独占"""
        from config_manager import ReadWriteLock

        lock = ReadWriteLock()
        results = []

        def writer():
            with lock.write_lock():
                results.append("write_start")
                time.sleep(0.05)
                results.append("write_end")

        def reader():
            with lock.read_lock():
                results.append("read")

        # 启动写线程
        t1 = threading.Thread(target=writer)
        t1.start()
        time.sleep(0.01)  # 确保写锁先获取

        # 启动读线程
        t2 = threading.Thread(target=reader)
        t2.start()

        t1.join()
        t2.join()

        # 写操作应该先完成
        self.assertEqual(results[0], "write_start")
        self.assertEqual(results[1], "write_end")


# ============================================================================
# 跨模块集成测试
# ============================================================================


class TestConfigManagerBoundary(unittest.TestCase):
    """配置管理器边界条件测试"""

    @classmethod
    def setUpClass(cls):
        """测试类初始化"""
        cls.test_dir = tempfile.mkdtemp()

    @classmethod
    def tearDownClass(cls):
        """测试类清理"""
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    def test_parse_empty_jsonc(self):
        """测试解析空 JSONC"""
        from config_manager import parse_jsonc

        result = parse_jsonc("{}")
        self.assertEqual(result, {})

    def test_parse_only_comments(self):
        """测试只有注释的 JSONC"""
        from config_manager import parse_jsonc

        content = """
        // 这是注释
        /* 多行注释 */
        {}
        """
        result = parse_jsonc(content)
        self.assertEqual(result, {})

    def test_deeply_nested_config(self):
        """测试深度嵌套配置"""
        from config_manager import ConfigManager

        config_file = Path(self.test_dir) / "nested.json"
        nested_config = {"level1": {"level2": {"level3": {"level4": {"value": 42}}}}}

        with open(config_file, "w") as f:
            json.dump(nested_config, f)

        mgr = ConfigManager(str(config_file))

        # 测试深度获取
        value = mgr.get("level1.level2.level3.level4.value")
        self.assertEqual(value, 42)

    def test_unicode_config_values(self):
        """测试 Unicode 配置值"""
        from config_manager import ConfigManager

        config_file = Path(self.test_dir) / "unicode.json"
        unicode_config = {
            "chinese": "中文测试",
            "japanese": "日本語テスト",
            "emoji": "🎉🚀💻",
            "mixed": "Hello 世界 🌍",
        }

        with open(config_file, "w", encoding="utf-8") as f:
            json.dump(unicode_config, f, ensure_ascii=False)

        mgr = ConfigManager(str(config_file))

        self.assertEqual(mgr.get("chinese"), "中文测试")
        self.assertEqual(mgr.get("emoji"), "🎉🚀💻")

    def test_special_characters_in_value(self):
        """测试值中的特殊字符"""
        from config_manager import ConfigManager

        config_file = Path(self.test_dir) / "special.json"
        special_config = {
            "url": "http://example.com/path?param=value&other=123",
            "path": "/home/user/文件夹/file.txt",
            "regex": "^[a-z]+\\d+$",
        }

        with open(config_file, "w", encoding="utf-8") as f:
            json.dump(special_config, f)

        mgr = ConfigManager(str(config_file))

        self.assertEqual(
            mgr.get("url"), "http://example.com/path?param=value&other=123"
        )


class TestConfigManagerExceptions(unittest.TestCase):
    """配置管理器异常处理测试"""

    @classmethod
    def setUpClass(cls):
        """测试类初始化"""
        cls.test_dir = tempfile.mkdtemp()

    @classmethod
    def tearDownClass(cls):
        """测试类清理"""
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    def test_malformed_json(self):
        """测试畸形 JSON"""
        from config_manager import parse_jsonc

        with self.assertRaises(json.JSONDecodeError):
            parse_jsonc("{invalid json")

    def test_missing_config_file(self):
        """测试配置文件不存在"""
        from config_manager import ConfigManager

        # 应该创建默认配置
        mgr = ConfigManager(str(Path(self.test_dir) / "nonexistent.json"))
        self.assertIsNotNone(mgr.get_all())

    def test_permission_denied_simulation(self):
        """测试权限错误模拟"""
        from config_manager import ConfigManager

        config_file = Path(self.test_dir) / "test_perm.json"
        with open(config_file, "w") as f:
            json.dump({"test": True}, f)

        mgr = ConfigManager(str(config_file))

        # 即使保存失败，内存配置应该还在
        mgr.set("test", False, save=False)
        self.assertEqual(mgr.get("test"), False)


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


# ---------------------------------------------------------------------------
# 边界路径补充（原 test_config_manager_extended.py）
# ---------------------------------------------------------------------------


from config_manager import (
    ConfigManager,
    _get_user_config_dir_fallback,
    _is_uvx_mode,
    _sanitize_config_value_for_log,
    find_config_file,
)

# ──────────────────────────────────────────────────────────
# 辅助工具函数测试
# ──────────────────────────────────────────────────────────


class TestSanitizeConfigValue(unittest.TestCase):
    """_sanitize_config_value_for_log"""

    def test_sensitive_key_redacted(self):
        self.assertEqual(
            _sanitize_config_value_for_log("bark_token", "abc"), "<redacted>"
        )

    def test_normal_key_shown(self):
        self.assertEqual(
            _sanitize_config_value_for_log("host", "127.0.0.1"), "127.0.0.1"
        )

    def test_long_value_truncated(self):
        result = _sanitize_config_value_for_log("data", "x" * 300)
        self.assertTrue(result.endswith("..."))
        self.assertLessEqual(len(result), 204)

    def test_unprintable_value(self):
        class Bad:
            def __str__(self):
                raise RuntimeError("no str")

        result = _sanitize_config_value_for_log("key", Bad())
        self.assertEqual(result, "<unprintable>")


# ──────────────────────────────────────────────────────────
# _is_uvx_mode 检测逻辑
# ──────────────────────────────────────────────────────────


class TestIsUvxMode(unittest.TestCase):
    def test_uvx_in_executable(self):
        with patch("config_manager.sys") as mock_sys:
            mock_sys.executable = "/home/user/.local/share/uvx/python3.11/bin/python"
            self.assertTrue(_is_uvx_mode())

    def test_uvx_project_env(self):
        with (
            patch("config_manager.sys") as mock_sys,
            patch.dict(os.environ, {"UVX_PROJECT": "ai-intervention-agent"}),
        ):
            mock_sys.executable = "/usr/bin/python3"
            self.assertTrue(_is_uvx_mode())

    def test_dev_mode_in_repo(self):
        result = _is_uvx_mode()
        self.assertFalse(result)


# ──────────────────────────────────────────────────────────
# find_config_file 路径查找
# ──────────────────────────────────────────────────────────


class TestFindConfigFile(unittest.TestCase):
    def test_absolute_path_returned_directly(self):
        result = find_config_file("/tmp/my_config.toml")
        self.assertEqual(result, Path("/tmp/my_config.toml"))

    def test_relative_path_with_directory(self):
        result = find_config_file("subdir/config.toml")
        self.assertEqual(result, Path("subdir/config.toml"))

    def test_env_override(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "test.toml"
            cfg.write_text("{}")
            with patch.dict(
                os.environ, {"AI_INTERVENTION_AGENT_CONFIG_FILE": str(cfg)}
            ):
                result = find_config_file()
                self.assertEqual(result, cfg)

    def test_env_override_directory(self):
        with (
            tempfile.TemporaryDirectory() as td,
            patch.dict(os.environ, {"AI_INTERVENTION_AGENT_CONFIG_FILE": td + "/"}),
        ):
            result = find_config_file()
            self.assertEqual(result, Path(td) / "config.toml")


# ──────────────────────────────────────────────────────────
# _get_user_config_dir_fallback 跨平台
# ──────────────────────────────────────────────────────────


class TestGetUserConfigDirFallback(unittest.TestCase):
    def test_darwin(self):
        with patch("config_manager.platform.system", return_value="Darwin"):
            result = _get_user_config_dir_fallback()
            self.assertIn("Library", str(result))
            self.assertTrue(str(result).endswith("ai-intervention-agent"))

    def test_windows_with_appdata(self):
        with (
            patch("config_manager.platform.system", return_value="Windows"),
            patch.dict(os.environ, {"APPDATA": "/fake/appdata"}),
        ):
            result = _get_user_config_dir_fallback()
            self.assertEqual(result, Path("/fake/appdata/ai-intervention-agent"))

    def test_windows_without_appdata(self):
        env = os.environ.copy()
        env.pop("APPDATA", None)
        with (
            patch("config_manager.platform.system", return_value="Windows"),
            patch.dict(os.environ, env, clear=True),
        ):
            result = _get_user_config_dir_fallback()
            self.assertIn("ai-intervention-agent", str(result))

    def test_linux_with_xdg(self):
        with (
            patch("config_manager.platform.system", return_value="Linux"),
            patch.dict(os.environ, {"XDG_CONFIG_HOME": "/xdg/config"}),
        ):
            result = _get_user_config_dir_fallback()
            self.assertEqual(result, Path("/xdg/config/ai-intervention-agent"))

    def test_linux_without_xdg(self):
        env = os.environ.copy()
        env.pop("XDG_CONFIG_HOME", None)
        with (
            patch("config_manager.platform.system", return_value="Linux"),
            patch.dict(os.environ, env, clear=True),
        ):
            result = _get_user_config_dir_fallback()
            self.assertIn(".config", str(result))


# ──────────────────────────────────────────────────────────
# update() / set() 路由 network_security
# ──────────────────────────────────────────────────────────


class TestUpdateNetworkSecurity(unittest.TestCase):
    def _mgr(self) -> ConfigManager:
        return ConfigManager()

    def test_update_network_security_dict(self):
        mgr = self._mgr()
        mgr.update(
            {"network_security": {"bind_interface": "127.0.0.1"}},
            save=True,
        )
        ns = mgr.get_network_security_config()
        self.assertEqual(ns["bind_interface"], "127.0.0.1")

    def test_update_network_security_dotted_key(self):
        mgr = self._mgr()
        mgr.update(
            {"network_security.bind_interface": "0.0.0.0"},
            save=True,
        )
        ns = mgr.get_network_security_config()
        self.assertIn(ns["bind_interface"], ("0.0.0.0", "127.0.0.1"))

    def test_update_network_security_invalid_dotted(self):
        mgr = self._mgr()
        with self.assertRaises(ConfigValidationError):
            mgr.update({"network_security.nested.field": "val"}, save=False)

    def test_update_network_security_only(self):
        mgr = self._mgr()
        mgr.update(
            {"network_security": {"access_control_enabled": False}},
            save=True,
        )

    def test_update_no_actual_changes(self):
        mgr = self._mgr()
        current = mgr.get("notification", {})
        mgr.update({"notification": current}, save=False)


class TestSetNetworkSecurityRouting(unittest.TestCase):
    """set() 方法 network_security 路由分支"""

    def test_set_network_security_dict(self):
        mgr = ConfigManager()
        mgr.set("network_security", {"bind_interface": "127.0.0.1"}, save=True)
        ns = mgr.get_network_security_config()
        self.assertEqual(ns["bind_interface"], "127.0.0.1")

    def test_set_network_security_non_dict_raises(self):
        mgr = ConfigManager()
        with self.assertRaises(ConfigValidationError):
            mgr.set("network_security", "bad", save=False)

    def test_set_network_security_dotted(self):
        mgr = ConfigManager()
        mgr.set("network_security.bind_interface", "0.0.0.0", save=True)

    def test_set_network_security_dotted_invalid(self):
        mgr = ConfigManager()
        with self.assertRaises(ConfigValidationError):
            mgr.set("network_security.a.b", "val", save=False)

    def test_set_network_security_dotted_empty_field(self):
        mgr = ConfigManager()
        with self.assertRaises(ConfigValidationError):
            mgr.set("network_security.", "val", save=False)

    def test_set_empty_key_invalidates_all(self):
        """空 key 会走 invalidate_all_caches 分支"""
        mgr = ConfigManager()
        mgr.set("", "test_value", save=False)


# ──────────────────────────────────────────────────────────
# update_section 路由
# ──────────────────────────────────────────────────────────


class TestUpdateSectionNetworkSecurity(unittest.TestCase):
    def test_update_section_network_security(self):
        mgr = ConfigManager()
        mgr.update_section("network_security", {"bind_interface": "0.0.0.0"}, save=True)

    def test_update_section_network_security_non_dict(self):
        mgr = ConfigManager()
        with self.assertRaises(ConfigValidationError):
            mgr.update_section("network_security", "not dict", save=False)  # type: ignore[arg-type]

    def test_update_section_no_changes(self):
        mgr = ConfigManager()
        current = mgr.get_section("notification")
        mgr.update_section("notification", current, save=False)  # type: ignore[arg-type]


# ──────────────────────────────────────────────────────────
# _validate_config_structure 分支
# ──────────────────────────────────────────────────────────


class TestValidateConfigStructure(unittest.TestCase):
    def _mgr(self) -> ConfigManager:
        return ConfigManager()

    def _json_mgr(self) -> ConfigManager:
        """返回配置文件为 .json 格式的 ConfigManager，使 JSON 重复检测生效"""
        mgr = ConfigManager()
        mgr.config_file = Path("/tmp/test.json")
        return mgr

    def test_duplicate_blocked_ips(self):
        content = '{\n"blocked_ips": [],\n"blocked_ips": []\n}'
        parsed = json.loads(content)
        with self.assertRaises(ConfigValidationError):
            self._json_mgr()._validate_config_structure(parsed, content)

    def test_network_security_not_dict(self):
        content = '{"network_security": "bad"}'
        parsed = json.loads(content)
        with self.assertRaises(ConfigValidationError):
            self._mgr()._validate_config_structure(parsed, content)

    def test_allowed_networks_not_list(self):
        content = '{"network_security": {"allowed_networks": "bad"}}'
        parsed = json.loads(content)
        with self.assertRaises(ConfigValidationError):
            self._mgr()._validate_config_structure(parsed, content)

    def test_allowed_networks_invalid_element(self):
        content = '{"network_security": {"allowed_networks": [123]}}'
        parsed = json.loads(content)
        with self.assertRaises(ConfigValidationError):
            self._mgr()._validate_config_structure(parsed, content)

    def test_toml_skips_duplicate_check(self):
        """TOML 模式下跳过 JSON 重复数组检测（TOML 解析器自身会拒绝重复键）"""
        content = '{\n"blocked_ips": [],\n"blocked_ips": []\n}'
        parsed = json.loads(content)
        self._mgr()._validate_config_structure(parsed, content)

    def test_json_comment_line_skipped(self):
        """JSON 模式：# 注释行被正确跳过"""
        content = '# "allowed_networks": []\n{"key": "value"}'
        parsed = {"key": "value"}
        self._json_mgr()._validate_config_structure(parsed, content)


# ──────────────────────────────────────────────────────────
# section 缓存
# ──────────────────────────────────────────────────────────


class TestSectionCache(unittest.TestCase):
    def test_cache_hit(self):
        mgr = ConfigManager()
        mgr.reset_cache_stats()
        mgr.get_section("notification")
        mgr.get_section("notification")
        stats = mgr.get_cache_stats()
        self.assertGreater(stats["hits"], 0)

    def test_cache_miss_after_invalidation(self):
        mgr = ConfigManager()
        mgr.get_section("notification")
        mgr.invalidate_section_cache("notification")
        mgr.reset_cache_stats()
        mgr.get_section("notification")
        stats = mgr.get_cache_stats()
        self.assertEqual(stats["misses"], 1)

    def test_cache_network_security_special(self):
        mgr = ConfigManager()
        result = mgr.get_section("network_security")
        self.assertIn("bind_interface", result)

    def test_cache_ttl_expired(self):
        mgr = ConfigManager()
        mgr.set_cache_ttl(section_ttl=0.1)
        mgr.get_section("notification")
        time.sleep(0.15)
        mgr.reset_cache_stats()
        mgr.get_section("notification")
        stats = mgr.get_cache_stats()
        self.assertGreater(stats["misses"], 0)

    def test_get_section_no_cache(self):
        mgr = ConfigManager()
        mgr.reset_cache_stats()
        mgr.get_section("notification", use_cache=False)
        stats = mgr.get_cache_stats()
        self.assertEqual(stats["misses"], 1)


# ──────────────────────────────────────────────────────────
# cache stats 和 TTL
# ──────────────────────────────────────────────────────────


class TestCacheStatsAndTTL(unittest.TestCase):
    def test_get_cache_stats(self):
        mgr = ConfigManager()
        stats = mgr.get_cache_stats()
        self.assertIn("hits", stats)
        self.assertIn("misses", stats)
        self.assertIn("hit_rate", stats)
        self.assertIn("section_cache_size", stats)

    def test_reset_cache_stats(self):
        mgr = ConfigManager()
        mgr.get_section("notification")
        mgr.reset_cache_stats()
        stats = mgr.get_cache_stats()
        self.assertEqual(stats["hits"], 0)
        self.assertEqual(stats["misses"], 0)

    def test_set_cache_ttl(self):
        mgr = ConfigManager()
        mgr.set_cache_ttl(section_ttl=10.0, network_security_ttl=30.0)
        self.assertEqual(mgr._section_cache_ttl, 10.0)
        self.assertEqual(mgr._network_security_cache_ttl, 30.0)

    def test_set_cache_ttl_minimum(self):
        mgr = ConfigManager()
        mgr.set_cache_ttl(section_ttl=0.001, network_security_ttl=0.001)
        self.assertGreaterEqual(mgr._section_cache_ttl, 0.1)
        self.assertGreaterEqual(mgr._network_security_cache_ttl, 1.0)

    def test_set_cache_ttl_none_no_change(self):
        mgr = ConfigManager()
        original_s = mgr._section_cache_ttl
        original_ns = mgr._network_security_cache_ttl
        mgr.set_cache_ttl()
        self.assertEqual(mgr._section_cache_ttl, original_s)
        self.assertEqual(mgr._network_security_cache_ttl, original_ns)


# ──────────────────────────────────────────────────────────
# _coerce_bool
# ──────────────────────────────────────────────────────────


class TestCoerceBool(unittest.TestCase):
    def test_bool_true(self):
        self.assertTrue(ConfigManager._coerce_bool(True))

    def test_bool_false(self):
        self.assertFalse(ConfigManager._coerce_bool(False))

    def test_none_default_true(self):
        self.assertTrue(ConfigManager._coerce_bool(None, default=True))

    def test_none_default_false(self):
        self.assertFalse(ConfigManager._coerce_bool(None, default=False))

    def test_int_truthy(self):
        self.assertTrue(ConfigManager._coerce_bool(1))
        self.assertFalse(ConfigManager._coerce_bool(0))

    def test_float_truthy(self):
        self.assertTrue(ConfigManager._coerce_bool(1.0))
        self.assertFalse(ConfigManager._coerce_bool(0.0))

    def test_string_true_values(self):
        for val in ("true", "True", "1", "yes", "y", "on", "YES", "ON"):
            self.assertTrue(ConfigManager._coerce_bool(val), f"failed for '{val}'")

    def test_string_false_values(self):
        for val in ("false", "False", "0", "no", "n", "off", "NO", "OFF"):
            self.assertFalse(ConfigManager._coerce_bool(val), f"failed for '{val}'")

    def test_string_unknown_returns_default(self):
        self.assertTrue(ConfigManager._coerce_bool("maybe", default=True))
        self.assertFalse(ConfigManager._coerce_bool("maybe", default=False))

    def test_other_object_uses_bool(self):
        self.assertTrue(ConfigManager._coerce_bool([1, 2]))
        self.assertFalse(ConfigManager._coerce_bool([]))

    def test_exception_returns_default(self):
        class BadBool:
            def __bool__(self):
                raise RuntimeError("boom")

        self.assertTrue(ConfigManager._coerce_bool(BadBool(), default=True))
        self.assertFalse(ConfigManager._coerce_bool(BadBool(), default=False))


# ──────────────────────────────────────────────────────────
# Typed getters
# ──────────────────────────────────────────────────────────


class TestTypedGetters(unittest.TestCase):
    def _mgr(self) -> ConfigManager:
        return ConfigManager()

    def test_get_int_with_bounds(self):
        mgr = self._mgr()
        mgr.set("test_int", 50, save=False)
        result = mgr.get_int("test_int", default=0, min_val=10, max_val=100)
        self.assertEqual(result, 50)

    def test_get_int_min_only(self):
        mgr = self._mgr()
        mgr.set("test_int_min", 5, save=False)
        result = mgr.get_int("test_int_min", default=0, min_val=10)
        self.assertGreaterEqual(result, 10)

    def test_get_int_max_only(self):
        mgr = self._mgr()
        mgr.set("test_int_max", 200, save=False)
        result = mgr.get_int("test_int_max", default=0, max_val=100)
        self.assertLessEqual(result, 100)

    def test_get_int_invalid_type_returns_default(self):
        mgr = self._mgr()
        mgr.set("test_bad", "not_a_number", save=False)
        result = mgr.get_int("test_bad", default=42)
        self.assertEqual(result, 42)

    def test_get_float_with_bounds(self):
        mgr = self._mgr()
        mgr.set("test_float", 0.5, save=False)
        result = mgr.get_float("test_float", default=0.0, min_val=0.0, max_val=1.0)
        self.assertEqual(result, 0.5)

    def test_get_float_min_only(self):
        mgr = self._mgr()
        mgr.set("f_min", -5.0, save=False)
        result = mgr.get_float("f_min", default=0.0, min_val=0.0)
        self.assertGreaterEqual(result, 0.0)

    def test_get_float_max_only(self):
        mgr = self._mgr()
        mgr.set("f_max", 999.0, save=False)
        result = mgr.get_float("f_max", default=0.0, max_val=100.0)
        self.assertLessEqual(result, 100.0)

    def test_get_bool(self):
        mgr = self._mgr()
        mgr.set("test_bool", True, save=False)
        self.assertTrue(mgr.get_bool("test_bool"))

    def test_get_bool_string_true(self):
        mgr = self._mgr()
        mgr.set("test_bool_str", "true", save=False)
        self.assertTrue(mgr.get_bool("test_bool_str"))

    def test_get_bool_int_conversion(self):
        mgr = self._mgr()
        mgr.set("test_bool_int", 0, save=False)
        self.assertFalse(mgr.get_bool("test_bool_int"))

    def test_get_str(self):
        mgr = self._mgr()
        mgr.set("test_str", "hello", save=False)
        self.assertEqual(mgr.get_str("test_str"), "hello")

    def test_get_str_truncate(self):
        mgr = self._mgr()
        mgr.set("test_str_long", "a" * 100, save=False)
        result = mgr.get_str("test_str_long", max_length=10)
        self.assertLessEqual(len(result), 15)


# ──────────────────────────────────────────────────────────
# _delayed_save 和 _schedule_save
# ──────────────────────────────────────────────────────────


class TestDelayedSave(unittest.TestCase):
    def test_delayed_save_applies_pending(self):
        mgr = ConfigManager()
        mgr._pending_changes = {"notification.debug": True}
        mgr._delayed_save()
        self.assertTrue(mgr.get("notification.debug"))
        self.assertEqual(mgr._pending_changes, {})

    def test_delayed_save_exception(self):
        mgr = ConfigManager()
        mgr._pending_changes = {"k": "v"}
        with patch.object(mgr, "_save_config_immediate", side_effect=OSError("disk")):
            mgr._delayed_save()

    def test_schedule_save_replaces_timer(self):
        mgr = ConfigManager()
        mock_timer = MagicMock()
        mgr._save_timer = mock_timer
        mgr._schedule_save()
        mock_timer.cancel.assert_called_once()
        self.assertIsNotNone(mgr._save_timer)
        if mgr._save_timer:
            mgr._save_timer.cancel()


# ──────────────────────────────────────────────────────────
# _create_default_config_file 分支
# ──────────────────────────────────────────────────────────


class TestCreateDefaultConfigFile(unittest.TestCase):
    def test_no_template_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "config.json"
            mgr = ConfigManager.__new__(ConfigManager)
            mgr.config_file = cfg
            mgr._config = {}
            mgr._original_content = None
            mgr._lock = __import__("threading").RLock()

            with patch("config_manager.Path") as mock_path_cls:
                template_mock = MagicMock()
                template_mock.exists.return_value = False

                real_parent = cfg.parent

                class FakePath:
                    def __init__(self, *a, **kw):
                        self._real = Path(*a, **kw)

                    def __truediv__(self, other):
                        if other == "config.toml.default":
                            return template_mock
                        return self._real / other

                    @property
                    def parent(self):
                        return real_parent

                mock_path_cls.side_effect = FakePath
                mock_path_cls.__file__ = __file__

                mgr._create_default_config_file()

            self.assertTrue(cfg.exists())
            content = json.loads(cfg.read_text())
            self.assertIn("notification", content)


# ──────────────────────────────────────────────────────────
# _load_config 异常分支
# ──────────────────────────────────────────────────────────


class TestLoadConfigExceptions(unittest.TestCase):
    def test_load_config_first_load_failure_uses_defaults(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "config.json"
            cfg.write_text("{invalid json")
            mgr = ConfigManager(str(cfg))
            self.assertIn("notification", mgr._config)

    def test_load_config_reload_failure_keeps_previous(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "config.json"
            cfg.write_text('{"notification": {"debug": true}}')
            mgr = ConfigManager(str(cfg))
            self.assertTrue(mgr.get("notification.debug"))

            cfg.write_text("{broken")
            mgr.reload()
            self.assertTrue(mgr.get("notification.debug"))


# ──────────────────────────────────────────────────────────
# _merge_config 的 network_security 跳过
# ──────────────────────────────────────────────────────────


class TestMergeConfig(unittest.TestCase):
    def test_network_security_excluded(self):
        mgr = ConfigManager()
        default = {"network_security": {"k": "v"}, "other": {"a": 1}}
        current: dict[str, Any] = {"other": {"a": 2}}
        result = mgr._merge_config(default, current)
        self.assertNotIn("network_security", result)
        self.assertEqual(result["other"]["a"], 2)


# ──────────────────────────────────────────────────────────
# update() save=True 分支（批量缓冲）
# ──────────────────────────────────────────────────────────


class TestUpdateWithSave(unittest.TestCase):
    def test_update_save_true_schedules_save(self):
        mgr = ConfigManager()
        mgr.update({"notification.debug": True}, save=True)
        self.assertTrue(mgr.get("notification.debug"))
        if mgr._save_timer:
            mgr._save_timer.cancel()

    def test_update_callback_exception_ignored(self):
        mgr = ConfigManager()

        def bad_callback():
            raise RuntimeError("boom")

        mgr.register_config_change_callback(bad_callback)
        mgr.update({"notification.debug": True}, save=False)


# ──────────────────────────────────────────────────────────
# get_config / _shutdown_global_config_manager
# ──────────────────────────────────────────────────────────


class TestGetConfig(unittest.TestCase):
    def test_returns_config_manager(self):
        from config_manager import get_config

        result = get_config()
        self.assertIsInstance(result, ConfigManager)

    def test_get_config_exception_safe(self):
        from config_manager import get_config

        with patch.object(
            ConfigManager, "start_file_watcher", side_effect=RuntimeError("fail")
        ):
            result = get_config()
            self.assertIsInstance(result, ConfigManager)


class TestShutdownGlobal(unittest.TestCase):
    def test_shutdown_function_exists(self):
        from config_manager import _shutdown_global_config_manager

        _shutdown_global_config_manager()

    def test_shutdown_exception_safe(self):
        from config_manager import _shutdown_global_config_manager

        with patch.object(ConfigManager, "shutdown", side_effect=RuntimeError("fail")):
            _shutdown_global_config_manager()


# ──────────────────────────────────────────────────────────
# _save_config_immediate 异常与 JSON 保存路径
# ──────────────────────────────────────────────────────────


class TestSaveConfigImmediate(unittest.TestCase):
    def test_save_json_format(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "config.json"
            cfg.write_text('{"notification": {"debug": false}}')
            mgr = ConfigManager(str(cfg))
            mgr.set("notification.debug", True, save=False)
            mgr._save_config_immediate()
            content = json.loads(cfg.read_text())
            self.assertTrue(content["notification"]["debug"])

    def test_save_exception_propagated(self):
        mgr = ConfigManager()
        with patch("builtins.open", side_effect=PermissionError("no write")):
            with self.assertRaises(PermissionError):
                mgr._save_config_immediate()


# ──────────────────────────────────────────────────────────
# ReadWriteLock 写锁等待读者
# ──────────────────────────────────────────────────────────


class TestReadWriteLockWait(unittest.TestCase):
    def test_write_waits_for_readers(self):
        import threading

        from config_manager import ReadWriteLock

        lock = ReadWriteLock()
        log: list[str] = []
        barrier = threading.Event()

        def reader():
            with lock.read_lock():
                log.append("read_start")
                barrier.set()
                time.sleep(0.05)
                log.append("read_end")

        def writer():
            barrier.wait()
            with lock.write_lock():
                log.append("write")

        rt = threading.Thread(target=reader)
        wt = threading.Thread(target=writer)
        rt.start()
        wt.start()
        rt.join(timeout=2)
        wt.join(timeout=2)

        self.assertEqual(log.index("read_end") < log.index("write"), True)


# ──────────────────────────────────────────────────────────
# find_config_file 开发模式分支 (269-322)
# ──────────────────────────────────────────────────────────


class TestFindConfigFileDev(unittest.TestCase):
    """_is_uvx_mode() == False 时的 find_config_file 路径"""

    def test_dev_mode_current_dir_exists(self):
        """开发模式下，当前目录存在 config.toml 时直接返回"""
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "config.toml"
            cfg.write_text("[notification]\nenabled = true\n")
            with (
                patch("config_manager._is_uvx_mode", return_value=False),
                patch.dict(os.environ, {}, clear=False),
                patch("config_manager.Path") as MockPath,
            ):
                os.environ.pop("AI_INTERVENTION_AGENT_CONFIG_FILE", None)

                mock_instance = MagicMock()
                mock_instance.is_absolute.return_value = False
                mock_instance.parent = Path(".")
                mock_instance.expanduser.return_value = mock_instance

                toml_mock = MagicMock()
                toml_mock.exists.return_value = True
                toml_mock.absolute.return_value = cfg

                call_count = 0

                def path_side_effect(arg="config.toml"):
                    nonlocal call_count
                    if arg == "config.toml":
                        call_count += 1
                        if call_count == 1:
                            return mock_instance
                        return toml_mock
                    return Path(arg)

                MockPath.side_effect = path_side_effect
                MockPath.__truediv__ = Path.__truediv__

                result = find_config_file("config.toml")
                self.assertEqual(result, toml_mock)

    def test_dev_mode_json_fallback(self):
        """开发模式下，config.toml/jsonc 不存在但 config.json 存在时回退"""
        with (
            patch("config_manager._is_uvx_mode", return_value=False),
            patch.dict(os.environ, {}, clear=False),
        ):
            os.environ.pop("AI_INTERVENTION_AGENT_CONFIG_FILE", None)
            with tempfile.TemporaryDirectory() as td:
                json_file = Path(td) / "config.json"
                json_file.write_text("{}")
                with patch("config_manager.Path") as MockPath:
                    mock_instance = MagicMock()
                    mock_instance.is_absolute.return_value = False
                    mock_instance.parent = Path(".")
                    mock_instance.expanduser.return_value = mock_instance

                    toml_mock = MagicMock()
                    toml_mock.exists.return_value = False
                    jsonc_mock = MagicMock()
                    jsonc_mock.exists.return_value = False
                    json_mock = MagicMock()
                    json_mock.exists.return_value = True
                    json_mock.absolute.return_value = json_file

                    call_count = 0

                    def path_side_effect(arg="config.toml"):
                        nonlocal call_count
                        if arg == "config.toml":
                            call_count += 1
                            if call_count == 1:
                                return mock_instance
                            return toml_mock
                        if arg == "config.jsonc":
                            return jsonc_mock
                        if arg == "config.json":
                            return json_mock
                        return Path(arg)

                    MockPath.side_effect = path_side_effect

                    result = find_config_file("config.toml")
                    self.assertEqual(result, json_mock)


# ──────────────────────────────────────────────────────────
# _is_uvx_mode 异常降级 (231-235)
# ──────────────────────────────────────────────────────────


class TestIsUvxModeException(unittest.TestCase):
    def test_exception_returns_true(self):
        with (
            patch("config_manager.sys") as mock_sys,
            patch("config_manager.Path") as MockPath,
            patch.dict(os.environ, {}, clear=False),
        ):
            os.environ.pop("UVX_PROJECT", None)
            mock_sys.executable = "/usr/bin/python3"
            MockPath.side_effect = RuntimeError("boom")
            self.assertTrue(_is_uvx_mode())


# ──────────────────────────────────────────────────────────
# set() / update() / update_section() 回调异常 (880-881, 962-963, 1097-1098)
# ──────────────────────────────────────────────────────────


class TestCallbackExceptions(unittest.TestCase):
    def test_set_callback_exception_ignored(self):
        mgr = ConfigManager()
        mgr.register_config_change_callback(
            lambda: (_ for _ in ()).throw(RuntimeError("x"))
        )
        mgr.set("notification.debug", True, save=False)

    def test_update_callback_exception_ignored(self):
        mgr = ConfigManager()

        def bad():
            raise RuntimeError("boom")

        mgr.register_config_change_callback(bad)
        mgr.update({"notification.debug": True}, save=False)

    def test_update_section_callback_exception_ignored(self):
        mgr = ConfigManager()

        def bad():
            raise RuntimeError("section boom")

        mgr.register_config_change_callback(bad)
        mgr.update_section("notification", {"debug": True}, save=False)


# ──────────────────────────────────────────────────────────
# update_section 嵌套 key 创建 (1079-1081)
# ──────────────────────────────────────────────────────────


class TestUpdateSectionNestedKey(unittest.TestCase):
    def test_nested_section_key_creation(self):
        mgr = ConfigManager()
        mgr.update_section("notification.sub", {"key": "val"}, save=False)
        result = mgr.get("notification.sub", {})
        self.assertEqual(result.get("key"), "val")


# ──────────────────────────────────────────────────────────
# update() save=True（批量保存） (926-934)
# ──────────────────────────────────────────────────────────


class TestUpdateSaveTrue(unittest.TestCase):
    def test_update_save_true_pending_changes(self):
        mgr = ConfigManager()
        mgr.update(
            {"notification.debug": True, "notification.sound_volume": 50},
            save=True,
        )
        self.assertTrue(mgr.get("notification.debug"))
        self.assertEqual(mgr.get("notification.sound_volume"), 50)
        if mgr._save_timer:
            mgr._save_timer.cancel()


# ──────────────────────────────────────────────────────────
# update() 中 empty section / network_security 缓存失效 (946-950)
# ──────────────────────────────────────────────────────────


class TestUpdateCacheInvalidation(unittest.TestCase):
    def test_update_invalidates_all_on_empty_key(self):
        mgr = ConfigManager()
        mgr.get_section("notification")
        mgr.update({"": "val"}, save=False)
        stats = mgr.get_cache_stats()
        self.assertGreater(stats["invalidations"], 0)


# ──────────────────────────────────────────────────────────
# _validate_saved_config 异常 (745-747)
# ──────────────────────────────────────────────────────────


class TestValidateSavedConfigException(unittest.TestCase):
    def test_validation_failure_raises(self):
        mgr = ConfigManager()
        with (
            patch("builtins.open", side_effect=OSError("can't read")),
            self.assertRaises(IOError),
        ):
            mgr._validate_saved_config()


# ──────────────────────────────────────────────────────────
# _create_default_config_file 双重失败 (622-636)
# ──────────────────────────────────────────────────────────


class TestCreateDefaultConfigFallbackFailure(unittest.TestCase):
    def test_first_write_fails_then_fallback_succeeds(self):
        import shutil

        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "config.json"
            mgr = ConfigManager.__new__(ConfigManager)
            mgr.config_file = cfg
            mgr._config = {}
            mgr._original_content = None
            mgr._lock = __import__("threading").RLock()

            call_count = 0
            original_copy2 = shutil.copy2

            def failing_copy(*a, **kw):
                nonlocal call_count
                call_count += 1
                raise PermissionError("can't copy")

            with patch("config_manager.shutil.copy2", side_effect=failing_copy):
                mgr._create_default_config_file()

            self.assertTrue(cfg.exists())

    def test_total_failure_raises(self):
        mgr = ConfigManager.__new__(ConfigManager)
        mgr.config_file = Path("/nonexistent/deeply/nested/config.json")
        mgr._config = {}
        mgr._original_content = None
        mgr._lock = __import__("threading").RLock()

        with (
            patch("config_manager.shutil.copy2", side_effect=PermissionError("no")),
            patch("builtins.open", side_effect=PermissionError("no write")),
            self.assertRaises(PermissionError),
        ):
            mgr._create_default_config_file()


# ──────────────────────────────────────────────────────────
# get_config 文件监听异常 (1322-1324)
# ──────────────────────────────────────────────────────────


class TestGetConfigWatcherException(unittest.TestCase):
    def test_watcher_start_exception_returns_manager(self):
        from config_manager import config_manager as global_mgr
        from config_manager import get_config

        global_mgr._file_watcher_running = False
        with patch.object(
            ConfigManager, "start_file_watcher", side_effect=OSError("bad")
        ):
            result = get_config()
            self.assertIsInstance(result, ConfigManager)


# ──────────────────────────────────────────────────────────
# _trigger 方法本身抛异常（覆盖 set/update/update_section 的外层 except）
# ──────────────────────────────────────────────────────────


class TestTriggerCallbackMethodException(unittest.TestCase):
    """_trigger_config_change_callbacks 方法自身异常（非回调内异常）"""

    def test_set_trigger_method_exception(self):
        mgr = ConfigManager()
        with patch.object(
            mgr, "_trigger_config_change_callbacks", side_effect=RuntimeError("lock")
        ):
            mgr.set("notification.debug", True, save=False)

    def test_update_trigger_method_exception(self):
        mgr = ConfigManager()
        with patch.object(
            mgr, "_trigger_config_change_callbacks", side_effect=RuntimeError("lock")
        ):
            mgr.update({"notification.debug": True}, save=False)

    def test_update_section_trigger_method_exception(self):
        mgr = ConfigManager()
        with patch.object(
            mgr, "_trigger_config_change_callbacks", side_effect=RuntimeError("lock")
        ):
            mgr.update_section("notification", {"debug": True}, save=False)


# ──────────────────────────────────────────────────────────
# update_section 嵌套 key 中间路径不存在 (1079-1081)
# ──────────────────────────────────────────────────────────


class TestUpdateSectionDeepNested(unittest.TestCase):
    def test_creates_intermediate_dict(self):
        mgr = ConfigManager()
        mgr.update_section("brand_new.child", {"key": "val"}, save=False)
        result = mgr.get("brand_new", {})
        self.assertIsInstance(result, dict)
        self.assertEqual(result.get("child", {}).get("key"), "val")


# ──────────────────────────────────────────────────────────
# set() 中 empty key 走 invalidate_all_caches (865)
# ──────────────────────────────────────────────────────────


class TestSetEmptyKeyInvalidation(unittest.TestCase):
    def test_set_network_security_section_value_in_memory(self):
        """直接在 _config 中设置 key="network_security.xxx" 的情况
        因为 set() 会先路由到专用方法，这里测试空 section 的分支"""
        mgr = ConfigManager()
        mgr.get_section("notification")
        mgr.set("", "x", save=False)


# ──────────────────────────────────────────────────────────
# _delayed_save 没有 pending_changes (658->667)
# ──────────────────────────────────────────────────────────


class TestDelayedSaveNoPending(unittest.TestCase):
    def test_no_pending_changes(self):
        mgr = ConfigManager()
        mgr._pending_changes = {}
        mgr._delayed_save()


# ──────────────────────────────────────────────────────────
# find_config_file uvx 模式用户配置目录分支 (293-322)
# ──────────────────────────────────────────────────────────


class TestFindConfigFileUvxMode(unittest.TestCase):
    def test_uvx_mode_user_config_exists(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "config.jsonc"
            cfg.write_text("{}")
            with (
                patch("config_manager._is_uvx_mode", return_value=True),
                patch("config_manager.user_config_dir", return_value=td),
                patch("config_manager.PLATFORMDIRS_AVAILABLE", True),
                patch.dict(os.environ, {}, clear=False),
            ):
                os.environ.pop("AI_INTERVENTION_AGENT_CONFIG_FILE", None)
                result = find_config_file("config.jsonc")
                self.assertEqual(result, cfg)

    def test_uvx_mode_json_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            json_f = Path(td) / "config.json"
            json_f.write_text("{}")
            with (
                patch("config_manager._is_uvx_mode", return_value=True),
                patch("config_manager.user_config_dir", return_value=td),
                patch("config_manager.PLATFORMDIRS_AVAILABLE", True),
                patch.dict(os.environ, {}, clear=False),
            ):
                os.environ.pop("AI_INTERVENTION_AGENT_CONFIG_FILE", None)
                result = find_config_file("config.jsonc")
                self.assertEqual(result, json_f)

    def test_uvx_mode_no_file_creates_path(self):
        with tempfile.TemporaryDirectory() as td:
            empty_dir = Path(td) / "empty"
            empty_dir.mkdir()
            with (
                patch("config_manager._is_uvx_mode", return_value=True),
                patch("config_manager.user_config_dir", return_value=str(empty_dir)),
                patch("config_manager.PLATFORMDIRS_AVAILABLE", True),
                patch.dict(os.environ, {}, clear=False),
            ):
                os.environ.pop("AI_INTERVENTION_AGENT_CONFIG_FILE", None)
                result = find_config_file("config.jsonc")
                self.assertEqual(result, empty_dir / "config.jsonc")

    def test_uvx_mode_platformdirs_unavailable(self):
        with tempfile.TemporaryDirectory() as td:
            with (
                patch("config_manager._is_uvx_mode", return_value=True),
                patch("config_manager.PLATFORMDIRS_AVAILABLE", False),
                patch(
                    "config_manager._get_user_config_dir_fallback",
                    return_value=Path(td),
                ),
                patch.dict(os.environ, {}, clear=False),
            ):
                os.environ.pop("AI_INTERVENTION_AGENT_CONFIG_FILE", None)
                result = find_config_file("config.jsonc")
                self.assertEqual(result, Path(td) / "config.jsonc")

    def test_uvx_mode_exception_fallback(self):
        with (
            patch("config_manager._is_uvx_mode", return_value=True),
            patch("config_manager.PLATFORMDIRS_AVAILABLE", False),
            patch(
                "config_manager._get_user_config_dir_fallback",
                side_effect=RuntimeError("fail"),
            ),
            patch.dict(os.environ, {}, clear=False),
        ):
            os.environ.pop("AI_INTERVENTION_AGENT_CONFIG_FILE", None)
            result = find_config_file("config.jsonc")
            self.assertEqual(result, Path("config.jsonc"))


# ──────────────────────────────────────────────────────────
# file_watcher.py 边界分支
# ──────────────────────────────────────────────────────────


class TestFileWatcherEdgeCases(unittest.TestCase):
    """覆盖 file_watcher.py 剩余缺失行/分支"""

    def test_start_watcher_initial_sync_exception(self):
        """lines 54-55: start_file_watcher 首次 mtime 同步异常"""
        mgr = ConfigManager()
        mgr.stop_file_watcher()
        with patch.object(
            type(mgr.config_file), "exists", side_effect=OSError("read err")
        ):
            mgr.start_file_watcher(interval=60.0)
        self.assertTrue(mgr.is_file_watcher_running)
        mgr.stop_file_watcher()

    def test_shutdown_cancel_timer_exception(self):
        """shutdown 先 force_save（取消定时器）再自身取消，异常不影响流程"""
        mgr = ConfigManager()
        mock_timer = MagicMock()
        mock_timer.cancel.side_effect = RuntimeError("cancel fail")
        mgr._save_timer = mock_timer
        mgr.shutdown()
        assert mock_timer.cancel.call_count >= 1

    def test_update_file_mtime_file_not_exist(self):
        """branch 24->exit: 文件不存在时 _update_file_mtime 跳过"""
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "nonexist.jsonc"
            mgr = ConfigManager(str(cfg_path))
            old_mtime = mgr._last_file_mtime
            mgr._update_file_mtime()
            self.assertEqual(mgr._last_file_mtime, old_mtime)

    def test_stop_file_watcher_thread_none(self):
        """branch 80->82: 线程对象为 None 但 running=True"""
        mgr = ConfigManager()
        mgr.stop_file_watcher()
        mgr._file_watcher_running = True
        mgr._file_watcher_thread = None
        mgr.stop_file_watcher()
        self.assertFalse(mgr.is_file_watcher_running)


class TestMigrateJsoncToToml(unittest.TestCase):
    """_migrate_jsonc_to_toml() 自动迁移逻辑"""

    def test_migrate_jsonc_file(self):
        """JSONC 文件应被迁移为 TOML，旧文件变 .bak"""
        with tempfile.TemporaryDirectory() as td:
            jsonc_path = Path(td) / "config.jsonc"
            jsonc_path.write_text(
                '{\n  "server": {"host": "127.0.0.1", "port": 8080}\n}',
                encoding="utf-8",
            )
            mgr = ConfigManager(str(jsonc_path))
            result = mgr._migrate_jsonc_to_toml()
            self.assertTrue(result)
            self.assertTrue(mgr.config_file.suffix == ".toml")
            self.assertTrue(mgr.config_file.exists())
            self.assertTrue(Path(td, "config.jsonc.bak").exists())
            import tomlkit

            content = mgr.config_file.read_text(encoding="utf-8")
            parsed = tomlkit.parse(content)
            self.assertEqual(parsed["server"]["host"], "127.0.0.1")  # type: ignore[index]

    def test_migrate_json_file(self):
        """JSON 文件应被迁移为 TOML"""
        with tempfile.TemporaryDirectory() as td:
            json_path = Path(td) / "config.json"
            json_path.write_text('{"server": {"host": "0.0.0.0"}}', encoding="utf-8")
            mgr = ConfigManager(str(json_path))
            result = mgr._migrate_jsonc_to_toml()
            self.assertTrue(result)
            self.assertTrue(mgr.config_file.suffix == ".toml")

    def test_migrate_converts_mdns_null_to_auto(self):
        """mdns.enabled=null 应被转换为 'auto'"""
        with tempfile.TemporaryDirectory() as td:
            jsonc_path = Path(td) / "config.jsonc"
            jsonc_path.write_text('{"mdns": {"enabled": null}}', encoding="utf-8")
            mgr = ConfigManager(str(jsonc_path))
            result = mgr._migrate_jsonc_to_toml()
            self.assertTrue(result)
            import tomlkit

            content = mgr.config_file.read_text(encoding="utf-8")
            parsed = tomlkit.parse(content)
            self.assertEqual(parsed["mdns"]["enabled"], "auto")  # type: ignore[index]

    def test_migrate_preserves_mdns_true(self):
        """mdns.enabled=true 不应被改为 'auto'"""
        with tempfile.TemporaryDirectory() as td:
            jsonc_path = Path(td) / "config.jsonc"
            jsonc_path.write_text('{"mdns": {"enabled": true}}', encoding="utf-8")
            mgr = ConfigManager(str(jsonc_path))
            result = mgr._migrate_jsonc_to_toml()
            self.assertTrue(result)
            import tomlkit

            content = mgr.config_file.read_text(encoding="utf-8")
            parsed = tomlkit.parse(content)
            self.assertTrue(parsed["mdns"]["enabled"])  # type: ignore[index]

    def test_migrate_failure_returns_false(self):
        """迁移失败（如文件读取异常）应返回 False"""
        with tempfile.TemporaryDirectory() as td:
            jsonc_path = Path(td) / "config.jsonc"
            jsonc_path.write_text('{"server": {"host": "x"}}', encoding="utf-8")
            mgr = ConfigManager(str(jsonc_path))
            with patch("builtins.open", side_effect=PermissionError("no read")):
                result = mgr._migrate_jsonc_to_toml()
            self.assertFalse(result)

    def test_migrate_without_template(self):
        """当 config.toml.default 模板不存在时的回退路径"""
        with tempfile.TemporaryDirectory() as td:
            jsonc_path = Path(td) / "config.jsonc"
            jsonc_path.write_text('{"server": {"host": "test"}}', encoding="utf-8")
            mgr = ConfigManager(str(jsonc_path))
            real_path = Path
            orig_truediv = Path.__truediv__

            def fake_truediv(self, other):
                result = orig_truediv(self, other)
                if str(other) == "config.toml.default":
                    mock_p = MagicMock()
                    mock_p.exists.return_value = False
                    return mock_p
                return result

            with patch.object(Path, "__truediv__", fake_truediv):
                result = mgr._migrate_jsonc_to_toml()
            self.assertTrue(result)
            self.assertTrue(mgr.config_file.suffix == ".toml")
            import tomlkit

            content = mgr.config_file.read_text(encoding="utf-8")
            parsed = tomlkit.parse(content)
            self.assertEqual(parsed["server"]["host"], "test")  # type: ignore[index]

    def test_migrate_adds_new_section_to_template(self):
        """迁移数据中有模板没有的 section 时应追加"""
        with tempfile.TemporaryDirectory() as td:
            jsonc_path = Path(td) / "config.jsonc"
            jsonc_path.write_text(
                '{"custom_section": {"key": "value"}, "server": {"host": "x"}}',
                encoding="utf-8",
            )
            mgr = ConfigManager(str(jsonc_path))
            result = mgr._migrate_jsonc_to_toml()
            self.assertTrue(result)
            import tomlkit

            content = mgr.config_file.read_text(encoding="utf-8")
            parsed = tomlkit.parse(content)
            self.assertEqual(parsed["custom_section"]["key"], "value")  # type: ignore[index]

    def test_load_config_triggers_migration(self):
        """_load_config 应在非 TOML 且非显式路径时触发自动迁移"""
        with tempfile.TemporaryDirectory() as td:
            jsonc_path = Path(td) / "config.jsonc"
            jsonc_path.write_text('{"server": {"host": "migrated"}}', encoding="utf-8")
            mgr = ConfigManager.__new__(ConfigManager)
            mgr._lock = __import__("threading").RLock()
            mgr._config = {}
            mgr._original_content = ""
            mgr._callbacks = {}
            mgr._section_cache = {}
            mgr._save_timer = None
            mgr._pending_changes = False
            mgr._file_watcher_running = False
            mgr._file_watcher_thread = None
            mgr._last_file_mtime = 0.0
            mgr.config_file = jsonc_path
            mgr._explicit_path = False
            mgr._load_config()
            self.assertTrue(mgr.config_file.suffix == ".toml")
            self.assertEqual(mgr.get("server.host"), "migrated")

    def test_load_config_skips_migration_for_explicit_path(self):
        """显式路径（_explicit_path=True）时不应触发迁移"""
        with tempfile.TemporaryDirectory() as td:
            jsonc_path = Path(td) / "config.jsonc"
            jsonc_path.write_text(
                '{"server": {"host": "stay_jsonc"}}', encoding="utf-8"
            )
            mgr = ConfigManager(str(jsonc_path))
            self.assertTrue(mgr.config_file.suffix == ".jsonc")
            self.assertEqual(mgr.get("server.host"), "stay_jsonc")


if __name__ == "__main__":
    unittest.main()
