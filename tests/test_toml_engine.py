"""toml_engine.py (TomlEngineMixin) 单元测试。

覆盖：
- TOML 解析（_parse_toml / _parse_toml_document）
- 保留注释格式的保存（_save_toml_with_comments）
- 递归 Table 更新（_update_toml_table）
- network_security 段操作（_save_network_security_toml）
"""

from __future__ import annotations

import unittest
from typing import Any

import tomlkit
from tomlkit.exceptions import TOMLKitError
from tomlkit.items import Table

from config_modules.toml_engine import TomlEngineMixin


class _Engine(TomlEngineMixin):
    """最小测试桩，继承 Mixin 并提供必要属性。"""

    _original_content: str = ""

    @staticmethod
    def _exclude_network_security(config: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in config.items() if k != "network_security"}


SAMPLE_TOML = """\
# 全局注释
[server]
host = "127.0.0.1"
port = 8080

[notification]
enabled = true
sound = "default"

[network_security]
enable_access_control = false
"""


class TestParseToml(unittest.TestCase):
    """_parse_toml 方法"""

    def test_parse_simple(self):
        result = TomlEngineMixin._parse_toml(SAMPLE_TOML)
        self.assertIsInstance(result, dict)
        self.assertEqual(result["server"]["host"], "127.0.0.1")
        self.assertEqual(result["server"]["port"], 8080)

    def test_parse_returns_plain_dict(self):
        result = TomlEngineMixin._parse_toml("[section]\nkey = 42\n")
        self.assertNotIsInstance(result, tomlkit.TOMLDocument)
        self.assertEqual(result["section"]["key"], 42)

    def test_parse_empty_document(self):
        result = TomlEngineMixin._parse_toml("")
        self.assertEqual(result, {})

    def test_parse_invalid_toml_raises(self):
        with self.assertRaises(TOMLKitError):
            TomlEngineMixin._parse_toml("[[invalid\n")


class TestParseTomlDocument(unittest.TestCase):
    """_parse_toml_document 方法"""

    def test_returns_toml_document(self):
        doc = TomlEngineMixin._parse_toml_document(SAMPLE_TOML)
        self.assertIsInstance(doc, tomlkit.TOMLDocument)

    def test_preserves_comments(self):
        doc = TomlEngineMixin._parse_toml_document(SAMPLE_TOML)
        dumped = tomlkit.dumps(doc)
        self.assertIn("# 全局注释", dumped)


class TestSaveTomlWithComments(unittest.TestCase):
    """_save_toml_with_comments 方法"""

    def setUp(self):
        self.engine = _Engine()

    def test_no_original_content_fallback(self):
        """无原始内容时应回退到纯 tomlkit.dumps"""
        self.engine._original_content = ""
        config = {"server": {"host": "0.0.0.0", "port": 9090}}
        result = self.engine._save_toml_with_comments(config)
        self.assertIn("host", result)
        self.assertIn("0.0.0.0", result)

    def test_preserves_comments(self):
        self.engine._original_content = SAMPLE_TOML
        config = {
            "server": {"host": "0.0.0.0", "port": 9090},
            "notification": {"enabled": False, "sound": "default"},
        }
        result = self.engine._save_toml_with_comments(config)
        self.assertIn("# 全局注释", result)
        self.assertIn("0.0.0.0", result)

    def test_excludes_network_security(self):
        self.engine._original_content = SAMPLE_TOML
        config = {
            "server": {"host": "127.0.0.1", "port": 8080},
            "notification": {"enabled": True, "sound": "default"},
            "network_security": {"enable_access_control": True},
        }
        result = self.engine._save_toml_with_comments(config)
        parsed = tomlkit.parse(result)
        self.assertFalse(parsed["network_security"]["enable_access_control"])  # type: ignore[index]

    def test_skips_network_security_key_in_iteration(self):
        """config_to_save 中如果还残留 network_security 键，循环中跳过"""
        self.engine._original_content = SAMPLE_TOML
        engine = self.engine
        engine._exclude_network_security = staticmethod(lambda c: c)  # type: ignore[assignment]
        config = {
            "server": {"host": "127.0.0.1", "port": 8080},
            "network_security": {"enable_access_control": True},
        }
        result = engine._save_toml_with_comments(config)
        self.assertIn("server", result)

    def test_existing_non_table_section_overwritten(self):
        """原始文档中某键对应的不是 Table（如字符串），则直接覆盖"""
        self.engine._original_content = 'top_key = "old_value"\n'
        config = {"top_key": {"nested": 42}}
        result = self.engine._save_toml_with_comments(config)
        parsed = tomlkit.parse(result)
        self.assertEqual(parsed["top_key"]["nested"], 42)  # type: ignore[index]

    def test_new_section_added_to_doc(self):
        """原始文档中没有的新 section 应被添加"""
        self.engine._original_content = "[server]\nhost = '127.0.0.1'\n"
        config = {"server": {"host": "127.0.0.1"}, "new_section": {"key": "value"}}
        result = self.engine._save_toml_with_comments(config)
        parsed = tomlkit.parse(result)
        self.assertEqual(parsed["new_section"]["key"], "value")  # type: ignore[index]

    def test_existing_non_dict_value_overwritten(self):
        """原始文档中 section 已存在且不是 dict，直接覆盖"""
        self.engine._original_content = "scalar = 42\n"
        config = {"scalar": 99}
        result = self.engine._save_toml_with_comments(config)
        parsed = tomlkit.parse(result)
        self.assertEqual(parsed["scalar"], 99)


class TestUpdateTomlTable(unittest.TestCase):
    """_update_toml_table 静态方法"""

    def _make_table(self, toml_str: str, section: str) -> Table:
        doc = tomlkit.parse(toml_str)
        return doc[section]  # type: ignore[return-value]

    def test_update_existing_key(self):
        table = self._make_table("[s]\nk = 1\n", "s")
        TomlEngineMixin._update_toml_table(table, {"k": 2})
        self.assertEqual(table["k"], 2)

    def test_add_new_key(self):
        table = self._make_table("[s]\nk = 1\n", "s")
        TomlEngineMixin._update_toml_table(table, {"new_k": "hello"})
        self.assertEqual(table["new_k"], "hello")

    def test_recursive_nested_table_update(self):
        """嵌套 Table 应递归更新"""
        toml_str = "[s]\n[s.nested]\ninner = 1\n"
        table = self._make_table(toml_str, "s")
        TomlEngineMixin._update_toml_table(table, {"nested": {"inner": 99}})
        self.assertEqual(table["nested"]["inner"], 99)  # type: ignore[index]

    def test_nested_dict_replaces_non_table(self):
        """目标键存在但不是 Table 时，dict 值直接替换"""
        table = self._make_table("[s]\nk = 'string'\n", "s")
        TomlEngineMixin._update_toml_table(table, {"k": {"sub": 1}})
        self.assertEqual(table["k"], {"sub": 1})


class TestSaveNetworkSecurityToml(unittest.TestCase):
    """_save_network_security_toml 方法"""

    def setUp(self):
        self.engine = _Engine()

    def test_no_original_content_returns_empty(self):
        self.engine._original_content = ""
        result = self.engine._save_network_security_toml(
            {"enable_access_control": True}
        )
        self.assertEqual(result, "")

    def test_update_existing_ns_section(self):
        self.engine._original_content = SAMPLE_TOML
        result = self.engine._save_network_security_toml(
            {"enable_access_control": True}
        )
        parsed = tomlkit.parse(result)
        self.assertTrue(parsed["network_security"]["enable_access_control"])  # type: ignore[index]

    def test_create_ns_section_when_missing(self):
        self.engine._original_content = "[server]\nhost = '127.0.0.1'\n"
        result = self.engine._save_network_security_toml(
            {"enable_access_control": True}
        )
        parsed = tomlkit.parse(result)
        self.assertTrue(parsed["network_security"]["enable_access_control"])  # type: ignore[index]

    def test_preserves_other_sections(self):
        self.engine._original_content = SAMPLE_TOML
        result = self.engine._save_network_security_toml(
            {"enable_access_control": True}
        )
        parsed = tomlkit.parse(result)
        self.assertEqual(parsed["server"]["host"], "127.0.0.1")  # type: ignore[index]


if __name__ == "__main__":
    unittest.main()
