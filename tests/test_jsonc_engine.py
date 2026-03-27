"""jsonc_engine.py (JsoncEngineMixin) 单元测试。

直接测试 JSONC 解析/定位/更新引擎的核心方法，覆盖：
- 值提取（简单值、数组、转义字符串、注释干扰）
- 数组范围查找与替换（单行/多行、嵌套括号、行内注释）
- 简单值替换（字符串、布尔、null、数字、行尾注释保留）
- 对象范围定位（嵌套对象、多行注释、字符串中的大括号）
- network_security 段定位
"""

from __future__ import annotations

import json
import unittest
from typing import Any

from config_modules.jsonc_engine import JsoncEngineMixin


class _Engine(JsoncEngineMixin):
    """最小测试桩，仅继承 Mixin。"""

    _original_content: str = ""
    _exclude_network_security: Any = None


def _lines(text: str) -> list[str]:
    """辅助：多行字符串 → 行列表（保留换行符以模拟 str.split('\\n')）"""
    return text.split("\n")


class TestExtractCurrentValue(unittest.TestCase):
    """_extract_current_value 方法"""

    def setUp(self):
        self.engine = _Engine()

    def test_simple_string(self):
        lines = _lines('{\n  "name": "hello"\n}')
        self.assertEqual(self.engine._extract_current_value(lines, 1, "name"), "hello")

    def test_simple_number(self):
        lines = _lines('{\n  "port": 8080\n}')
        self.assertEqual(self.engine._extract_current_value(lines, 1, "port"), 8080)

    def test_simple_bool(self):
        lines = _lines('{\n  "enabled": true\n}')
        self.assertTrue(self.engine._extract_current_value(lines, 1, "enabled"))

    def test_simple_null(self):
        lines = _lines('{\n  "value": null\n}')
        self.assertIsNone(self.engine._extract_current_value(lines, 1, "value"))

    def test_inline_array(self):
        lines = _lines('{\n  "tags": ["a", "b"]\n}')
        self.assertEqual(
            self.engine._extract_current_value(lines, 1, "tags"), ["a", "b"]
        )

    def test_multiline_array(self):
        lines = _lines('{\n  "tags": [\n    "x",\n    "y"\n  ]\n}')
        self.assertEqual(
            self.engine._extract_current_value(lines, 1, "tags"), ["x", "y"]
        )

    def test_multiline_array_with_comment_lines(self):
        lines = _lines('{\n  "tags": [\n    // 注释\n    "only"\n  ]\n}')
        self.assertEqual(self.engine._extract_current_value(lines, 1, "tags"), ["only"])

    def test_value_with_trailing_comment(self):
        lines = _lines('{\n  "port": 3000 // 默认端口\n}')
        self.assertEqual(self.engine._extract_current_value(lines, 1, "port"), 3000)

    def test_value_with_trailing_comma(self):
        lines = _lines('{\n  "port": 3000,\n  "host": "localhost"\n}')
        self.assertEqual(self.engine._extract_current_value(lines, 1, "port"), 3000)

    def test_string_with_escape(self):
        lines = _lines('{\n  "path": "C:\\\\Users\\\\test"\n}')
        result = self.engine._extract_current_value(lines, 1, "path")
        self.assertEqual(result, "C:\\Users\\test")

    def test_key_not_found(self):
        lines = _lines('{\n  "other": 1\n}')
        self.assertIsNone(self.engine._extract_current_value(lines, 1, "missing"))

    def test_out_of_range_index(self):
        lines = _lines('{\n  "a": 1\n}')
        self.assertIsNone(self.engine._extract_current_value(lines, 99, "a"))

    def test_empty_array_inline(self):
        lines = _lines('{\n  "items": []\n}')
        self.assertEqual(self.engine._extract_current_value(lines, 1, "items"), [])


class TestFindArrayRangeSimple(unittest.TestCase):
    """_find_array_range_simple 方法"""

    def setUp(self):
        self.engine = _Engine()

    def test_single_line_array(self):
        lines = _lines('{\n  "arr": [1, 2, 3]\n}')
        self.assertEqual(self.engine._find_array_range_simple(lines, 1, "arr"), (1, 1))

    def test_multi_line_array(self):
        lines = _lines('{\n  "arr": [\n    1,\n    2\n  ]\n}')
        self.assertEqual(self.engine._find_array_range_simple(lines, 1, "arr"), (1, 4))

    def test_nested_brackets(self):
        lines = _lines('{\n  "arr": [\n    [1, 2],\n    [3]\n  ]\n}')
        self.assertEqual(self.engine._find_array_range_simple(lines, 1, "arr"), (1, 4))

    def test_no_match(self):
        lines = _lines('{\n  "other": 1\n}')
        self.assertEqual(self.engine._find_array_range_simple(lines, 1, "arr"), (1, 1))

    def test_unclosed_bracket(self):
        lines = _lines('{\n  "arr": [\n    1\n')
        self.assertEqual(self.engine._find_array_range_simple(lines, 1, "arr"), (1, 1))

    def test_bracket_inside_string(self):
        lines = _lines('{\n  "arr": [\n    "[not a bracket]",\n    "val"\n  ]\n}')
        self.assertEqual(self.engine._find_array_range_simple(lines, 1, "arr"), (1, 4))


class TestJsoncFindArrayRange(unittest.TestCase):
    """_jsonc_find_array_range 静态方法（带注释感知）"""

    def test_single_line(self):
        lines = _lines('{\n  "arr": [1, 2]\n}')
        self.assertEqual(
            JsoncEngineMixin._jsonc_find_array_range(lines, 1, "arr"), (1, 1)
        )

    def test_multi_line_with_comments(self):
        lines = _lines('{\n  "arr": [\n    // 注释行\n    "a",\n    "b"\n  ]\n}')
        self.assertEqual(
            JsoncEngineMixin._jsonc_find_array_range(lines, 1, "arr"), (1, 5)
        )

    def test_no_match_returns_same(self):
        lines = _lines('{\n  "other": 1\n}')
        self.assertEqual(
            JsoncEngineMixin._jsonc_find_array_range(lines, 1, "arr"), (1, 1)
        )

    def test_unclosed_array(self):
        lines = _lines('{\n  "arr": [\n    1\n')
        self.assertEqual(
            JsoncEngineMixin._jsonc_find_array_range(lines, 1, "arr"), (1, 1)
        )

    def test_bracket_in_inline_comment(self):
        """行内注释中的 ] 不应结束数组"""
        lines = _lines('{\n  "arr": [\n    "a", // 包含 ] 的注释\n    "b"\n  ]\n}')
        self.assertEqual(
            JsoncEngineMixin._jsonc_find_array_range(lines, 1, "arr"), (1, 4)
        )


class TestJsoncUpdateArrayBlock(unittest.TestCase):
    """_jsonc_update_array_block 静态方法"""

    def test_single_line_replacement(self):
        lines = _lines('{\n  "arr": ["old"]\n}')
        result = JsoncEngineMixin._jsonc_update_array_block(
            lines, 1, 1, "arr", ["new1", "new2"]
        )
        self.assertEqual(len(result), 1)
        self.assertIn('"new1"', result[0])
        self.assertIn('"new2"', result[0])

    def test_multi_line_replacement(self):
        lines = _lines('{\n  "arr": [\n    "old1",\n    "old2"\n  ]\n}')
        result = JsoncEngineMixin._jsonc_update_array_block(
            lines, 1, 4, "arr", ["x", "y", "z"]
        )
        joined = "\n".join(result)
        self.assertIn('"x"', joined)
        self.assertIn('"y"', joined)
        self.assertIn('"z"', joined)
        self.assertTrue(result[-1].strip().startswith("]"))

    def test_preserves_element_comments(self):
        """元素行的尾部注释应保留到对应的新元素"""
        lines = _lines('{\n  "arr": [\n    "keep" // 重要\n  ]\n}')
        result = JsoncEngineMixin._jsonc_update_array_block(
            lines, 1, 3, "arr", ["keep", "added"]
        )
        joined = "\n".join(result)
        self.assertIn("// 重要", joined)

    def test_preserves_standalone_comments(self):
        """独立注释行应保留"""
        lines = _lines('{\n  "arr": [\n    // 分组标题\n    "a"\n  ]\n}')
        result = JsoncEngineMixin._jsonc_update_array_block(lines, 1, 4, "arr", ["b"])
        joined = "\n".join(result)
        self.assertIn("// 分组标题", joined)

    def test_empty_array(self):
        lines = _lines('{\n  "arr": [\n    "old"\n  ]\n}')
        result = JsoncEngineMixin._jsonc_update_array_block(lines, 1, 3, "arr", [])
        joined = "\n".join(result)
        self.assertIn("[", joined)
        self.assertIn("]", joined)

    def test_trailing_comma_preserved(self):
        """结束行有逗号时应保留"""
        lines = _lines('{\n  "arr": [\n    "a"\n  ],\n  "other": 1\n}')
        result = JsoncEngineMixin._jsonc_update_array_block(lines, 1, 3, "arr", ["b"])
        self.assertTrue(result[-1].rstrip().endswith(","))

    def test_single_line_no_match(self):
        """单行但模式不匹配 → 返回原行"""
        lines = _lines('{\n  "arr": "not-array"\n}')
        result = JsoncEngineMixin._jsonc_update_array_block(lines, 1, 1, "arr", ["x"])
        self.assertEqual(result, [lines[1]])


class TestJsoncUpdateSimpleValue(unittest.TestCase):
    """_jsonc_update_simple_value 静态方法"""

    def test_string_value(self):
        line = '  "host": "old"'
        result = JsoncEngineMixin._jsonc_update_simple_value(line, "host", "new")
        self.assertIn('"new"', result)
        self.assertNotIn('"old"', result)

    def test_bool_true(self):
        line = '  "enabled": false'
        result = JsoncEngineMixin._jsonc_update_simple_value(line, "enabled", True)
        self.assertIn("true", result)

    def test_bool_false(self):
        line = '  "enabled": true'
        result = JsoncEngineMixin._jsonc_update_simple_value(line, "enabled", False)
        self.assertIn("false", result)

    def test_null_value(self):
        line = '  "value": "something"'
        result = JsoncEngineMixin._jsonc_update_simple_value(line, "value", None)
        self.assertIn("null", result)

    def test_number_value(self):
        line = '  "port": 3000'
        result = JsoncEngineMixin._jsonc_update_simple_value(line, "port", 8080)
        self.assertIn("8080", result)

    def test_preserves_trailing_comment(self):
        line = '  "port": 3000 // 默认'
        result = JsoncEngineMixin._jsonc_update_simple_value(line, "port", 9090)
        self.assertIn("9090", result)
        self.assertIn("// 默认", result)

    def test_preserves_trailing_comma(self):
        line = '  "port": 3000,'
        result = JsoncEngineMixin._jsonc_update_simple_value(line, "port", 9090)
        self.assertIn("9090", result)
        self.assertTrue(result.rstrip().endswith(","))

    def test_key_not_found(self):
        line = '  "other": 1'
        result = JsoncEngineMixin._jsonc_update_simple_value(line, "missing", 2)
        self.assertEqual(result, line)

    def test_string_with_escape(self):
        line = '  "msg": "hello"'
        result = JsoncEngineMixin._jsonc_update_simple_value(line, "msg", 'say "hi"')
        parsed = json.loads(result.split(":")[1].strip())
        self.assertEqual(parsed, 'say "hi"')

    def test_chinese_string(self):
        line = '  "label": "旧标签"'
        result = JsoncEngineMixin._jsonc_update_simple_value(line, "label", "新标签")
        self.assertIn("新标签", result)


class TestJsoncFindObjectEndLine(unittest.TestCase):
    """_jsonc_find_object_end_line 静态方法"""

    def test_simple_object(self):
        lines = _lines('{\n  "a": 1\n}')
        self.assertEqual(JsoncEngineMixin._jsonc_find_object_end_line(lines, 0), 2)

    def test_nested_object(self):
        lines = _lines('{\n  "inner": {\n    "x": 1\n  }\n}')
        self.assertEqual(JsoncEngineMixin._jsonc_find_object_end_line(lines, 0), 4)
        self.assertEqual(JsoncEngineMixin._jsonc_find_object_end_line(lines, 1), 3)

    def test_brace_in_string_ignored(self):
        lines = _lines('{\n  "pattern": "a{b}c"\n}')
        self.assertEqual(JsoncEngineMixin._jsonc_find_object_end_line(lines, 0), 2)

    def test_brace_in_single_line_comment(self):
        lines = _lines('{\n  "a": 1 // }\n}')
        self.assertEqual(JsoncEngineMixin._jsonc_find_object_end_line(lines, 0), 2)

    def test_brace_in_multi_line_comment(self):
        lines = _lines('{\n  /* } */\n  "a": 1\n}')
        self.assertEqual(JsoncEngineMixin._jsonc_find_object_end_line(lines, 0), 3)

    def test_end_limit(self):
        lines = _lines('{\n  "a": {\n    "b": 1\n  }\n}')
        result = JsoncEngineMixin._jsonc_find_object_end_line(lines, 0, end_limit=2)
        self.assertEqual(result, 2)

    def test_unclosed_object(self):
        lines = _lines('{\n  "a": 1\n')
        result = JsoncEngineMixin._jsonc_find_object_end_line(lines, 0)
        self.assertEqual(result, len(lines) - 1)

    def test_escaped_quote_in_string(self):
        """转义引号不应打断字符串解析"""
        lines = _lines('{\n  "msg": "he said \\"yes\\""\n}')
        self.assertEqual(JsoncEngineMixin._jsonc_find_object_end_line(lines, 0), 2)

    def test_multi_line_comment_spanning_lines(self):
        lines = _lines('{\n  /*\n   * 跨行注释\n   */\n  "a": 1\n}')
        self.assertEqual(JsoncEngineMixin._jsonc_find_object_end_line(lines, 0), 5)


class TestJsoncFindKeyLineInObjectRange(unittest.TestCase):
    """_jsonc_find_key_line_in_object_range 静态方法"""

    def test_find_top_level_key(self):
        lines = _lines('{\n  "alpha": 1,\n  "beta": 2\n}')
        self.assertEqual(
            JsoncEngineMixin._jsonc_find_key_line_in_object_range(
                lines, (0, 3), "beta"
            ),
            2,
        )

    def test_skip_nested_key(self):
        """嵌套对象中的同名键不应被匹配"""
        lines = _lines('{\n  "outer": {\n    "name": "inner"\n  },\n  "name": "top"\n}')
        self.assertEqual(
            JsoncEngineMixin._jsonc_find_key_line_in_object_range(
                lines, (0, 5), "name"
            ),
            4,
        )

    def test_key_not_found(self):
        lines = _lines('{\n  "a": 1\n}')
        self.assertEqual(
            JsoncEngineMixin._jsonc_find_key_line_in_object_range(
                lines, (0, 2), "missing"
            ),
            -1,
        )

    def test_invalid_range(self):
        lines = _lines('{\n  "a": 1\n}')
        self.assertEqual(
            JsoncEngineMixin._jsonc_find_key_line_in_object_range(lines, (-1, 2), "a"),
            -1,
        )
        self.assertEqual(
            JsoncEngineMixin._jsonc_find_key_line_in_object_range(lines, (2, 0), "a"),
            -1,
        )

    def test_key_in_comment_ignored(self):
        lines = _lines('{\n  // "hidden": 1\n  "visible": 2\n}')
        self.assertEqual(
            JsoncEngineMixin._jsonc_find_key_line_in_object_range(
                lines, (0, 3), "hidden"
            ),
            -1,
        )
        self.assertEqual(
            JsoncEngineMixin._jsonc_find_key_line_in_object_range(
                lines, (0, 3), "visible"
            ),
            2,
        )

    def test_key_in_multi_line_comment_ignored(self):
        lines = _lines('{\n  /*\n  "hidden": 1\n  */\n  "visible": 2\n}')
        self.assertEqual(
            JsoncEngineMixin._jsonc_find_key_line_in_object_range(
                lines, (0, 5), "hidden"
            ),
            -1,
        )

    def test_key_in_string_value_not_matched(self):
        """值中出现的键名不应匹配"""
        lines = _lines('{\n  "desc": "target is here",\n  "target": 1\n}')
        self.assertEqual(
            JsoncEngineMixin._jsonc_find_key_line_in_object_range(
                lines, (0, 3), "target"
            ),
            2,
        )


class TestJsoncFindObjectRange(unittest.TestCase):
    """_jsonc_find_object_range 方法"""

    def setUp(self):
        self.engine = _Engine()

    def test_top_level_object(self):
        lines = _lines('{\n  "section": {\n    "key": 1\n  }\n}')
        self.assertEqual(self.engine._jsonc_find_object_range(lines, "section"), (1, 3))

    def test_nested_object_with_parent(self):
        lines = _lines('{\n  "parent": {\n    "child": {\n      "x": 1\n    }\n  }\n}')
        parent_range = self.engine._jsonc_find_object_range(lines, "parent")
        self.assertEqual(parent_range, (1, 5))
        child_range = self.engine._jsonc_find_object_range(
            lines, "child", parent_object_range=parent_range
        )
        self.assertEqual(child_range, (2, 4))

    def test_key_not_found(self):
        lines = _lines('{\n  "a": 1\n}')
        self.assertEqual(
            self.engine._jsonc_find_object_range(lines, "missing"), (-1, -1)
        )

    def test_empty_lines(self):
        self.assertEqual(self.engine._jsonc_find_object_range([], "any"), (-1, -1))

    def test_parent_key_not_found(self):
        lines = _lines('{\n  "a": {\n    "b": 1\n  }\n}')
        self.assertEqual(
            self.engine._jsonc_find_object_range(
                lines, "missing", parent_object_range=(1, 3)
            ),
            (-1, -1),
        )

    def test_object_after_comment(self):
        lines = _lines('{\n  // 配置段\n  "section": {\n    "val": true\n  }\n}')
        self.assertEqual(self.engine._jsonc_find_object_range(lines, "section"), (2, 4))


class TestJsoncFindTopLevelKeyLine(unittest.TestCase):
    """_jsonc_find_top_level_key_line 静态方法"""

    def test_find_key(self):
        lines = _lines('{\n  "first": 1,\n  "second": 2\n}')
        self.assertEqual(
            JsoncEngineMixin._jsonc_find_top_level_key_line(lines, "second"), 2
        )

    def test_skip_nested(self):
        lines = _lines('{\n  "obj": {\n    "name": "inner"\n  },\n  "name": "top"\n}')
        self.assertEqual(
            JsoncEngineMixin._jsonc_find_top_level_key_line(lines, "name"), 4
        )

    def test_not_found(self):
        lines = _lines('{\n  "a": 1\n}')
        self.assertEqual(
            JsoncEngineMixin._jsonc_find_top_level_key_line(lines, "missing"), -1
        )

    def test_empty_lines(self):
        self.assertEqual(JsoncEngineMixin._jsonc_find_top_level_key_line([], "a"), -1)

    def test_key_in_comment_ignored(self):
        lines = _lines('{\n  // "hidden": 1\n  "real": 2\n}')
        self.assertEqual(
            JsoncEngineMixin._jsonc_find_top_level_key_line(lines, "hidden"), -1
        )

    def test_key_in_block_comment_not_filtered(self):
        """已知局限：单行 /* */ 注释中的键会被误匹配（项目中仅使用 // 注释）"""
        lines = _lines('{\n  /* "hidden": 1 */\n  "real": 2\n}')
        result = JsoncEngineMixin._jsonc_find_top_level_key_line(lines, "hidden")
        self.assertNotEqual(result, -1)


class TestFindNetworkSecurityRange(unittest.TestCase):
    """_find_network_security_range 方法"""

    def setUp(self):
        self.engine = _Engine()

    def test_found(self):
        lines = _lines(
            '{\n  "network_security": {\n    "bind_interface": "0.0.0.0"\n  }\n}'
        )
        self.assertEqual(self.engine._find_network_security_range(lines), (1, 3))

    def test_not_found(self):
        lines = _lines('{\n  "other": 1\n}')
        self.assertEqual(self.engine._find_network_security_range(lines), (-1, -1))

    def test_commented_out(self):
        lines = _lines('{\n  // "network_security": {}\n}')
        self.assertEqual(self.engine._find_network_security_range(lines), (-1, -1))

    def test_nested_braces(self):
        lines = _lines(
            '{\n  "network_security": {\n    "sub": {\n      "x": 1\n    }\n  }\n}'
        )
        self.assertEqual(self.engine._find_network_security_range(lines), (1, 5))

    def test_unclosed(self):
        lines = _lines('{\n  "network_security": {\n    "a": 1\n')
        start, end = self.engine._find_network_security_range(lines)
        self.assertEqual(start, 1)
        self.assertEqual(end, len(lines) - 1)

    def test_string_with_brace(self):
        lines = _lines('{\n  "network_security": {\n    "pattern": "a{b}c"\n  }\n}')
        self.assertEqual(self.engine._find_network_security_range(lines), (1, 3))


class TestJsoncUpdateDictInObjectRange(unittest.TestCase):
    """_jsonc_update_dict_in_object_range 方法（递归更新）"""

    def setUp(self):
        self.engine = _Engine()

    def test_simple_key_update(self):
        lines = ["{\n", '  "section": {\n', '    "port": 3000\n', "  }\n", "}\n"]
        self.engine._jsonc_update_dict_in_object_range({"port": 9090}, lines, 1, 3)
        joined = "".join(lines)
        self.assertIn("9090", joined)

    def test_nested_dict_update(self):
        lines = _lines(
            '{\n  "parent": {\n    "child": {\n      "val": 1\n    }\n  }\n}'
        )
        self.engine._jsonc_update_dict_in_object_range(
            {"child": {"val": 99}}, lines, 1, 5
        )
        joined = "\n".join(lines)
        self.assertIn("99", joined)

    def test_array_update_in_range(self):
        lines = _lines('{\n  "section": {\n    "tags": ["old"]\n  }\n}')
        self.engine._jsonc_update_dict_in_object_range(
            {"tags": ["new1", "new2"]}, lines, 1, 3
        )
        joined = "\n".join(lines)
        self.assertIn("new1", joined)
        self.assertIn("new2", joined)

    def test_invalid_range_noop(self):
        lines = _lines('{\n  "a": 1\n}')
        original = list(lines)
        self.engine._jsonc_update_dict_in_object_range({"a": 2}, lines, -1, -1)
        self.assertEqual(lines, original)

    def test_missing_key_skipped(self):
        lines = _lines('{\n  "section": {\n    "existing": 1\n  }\n}')
        self.engine._jsonc_update_dict_in_object_range({"nonexistent": 99}, lines, 1, 3)
        joined = "\n".join(lines)
        self.assertNotIn("99", joined)

    def test_empty_config_noop(self):
        lines = _lines('{\n  "section": {\n    "a": 1\n  }\n}')
        original = list(lines)
        self.engine._jsonc_update_dict_in_object_range(None, lines, 1, 3)  # type: ignore[arg-type]
        self.assertEqual(lines, original)


class TestJsoncProcessConfigSection(unittest.TestCase):
    """_jsonc_process_config_section 方法"""

    def setUp(self):
        self.engine = _Engine()

    def test_skips_network_security(self):
        lines = _lines(
            '{\n  "network_security": {\n    "bind_interface": "0.0.0.0"\n  }\n}'
        )
        original = list(lines)
        self.engine._jsonc_process_config_section(
            {"network_security": {"bind_interface": "127.0.0.1"}},
            lines,
            (1, 3),
        )
        self.assertEqual(lines, original)

    def test_updates_other_section(self):
        lines = _lines(
            '{\n  "web_ui": {\n    "port": 3000\n  },\n  "network_security": {\n    "bind_interface": "0.0.0.0"\n  }\n}'
        )
        self.engine._jsonc_process_config_section(
            {"web_ui": {"port": 9090}},
            lines,
            (4, 6),
        )
        joined = "\n".join(lines)
        self.assertIn("9090", joined)

    def test_non_dict_input(self):
        lines = _lines('{\n  "a": 1\n}')
        self.engine._jsonc_process_config_section("not a dict", lines, (-1, -1))  # type: ignore[arg-type]

    def test_non_dict_values_skipped(self):
        lines = _lines('{\n  "scalar": 1\n}')
        original = list(lines)
        self.engine._jsonc_process_config_section({"scalar": 2}, lines, (-1, -1))
        self.assertEqual(lines, original)


class TestSaveJsoncWithComments(unittest.TestCase):
    """_save_jsonc_with_comments 方法（集成测试）"""

    def setUp(self):
        self.engine = _Engine()

    def _make_engine_with_content(self, content: str) -> _Engine:
        """创建带有 _original_content 和必要属性的 engine"""
        engine = _Engine()
        engine._original_content = content
        engine._exclude_network_security = lambda c: {
            k: v for k, v in c.items() if k != "network_security"
        }
        return engine

    def test_no_original_content_fallback_to_json(self):
        engine = _Engine()
        engine._original_content = ""
        engine._exclude_network_security = lambda c: c
        result = engine._save_jsonc_with_comments({"key": "value"})
        parsed = json.loads(result)
        self.assertEqual(parsed["key"], "value")

    def test_preserves_comments(self):
        content = '{\n  // 注释\n  "port": 3000\n}'
        engine = self._make_engine_with_content(content)
        result = engine._save_jsonc_with_comments({"port": 9090})
        self.assertIn("// 注释", result)
        self.assertIn("9090", result)

    def test_updates_nested_object(self):
        content = '{\n  "section": {\n    "val": 1\n  }\n}'
        engine = self._make_engine_with_content(content)
        result = engine._save_jsonc_with_comments({"section": {"val": 99}})
        self.assertIn("99", result)

    def test_updates_top_level_array(self):
        content = '{\n  "tags": ["old"]\n}'
        engine = self._make_engine_with_content(content)
        result = engine._save_jsonc_with_comments({"tags": ["new"]})
        self.assertIn('"new"', result)

    def test_updates_top_level_scalar(self):
        content = '{\n  "debug": false\n}'
        engine = self._make_engine_with_content(content)
        result = engine._save_jsonc_with_comments({"debug": True})
        self.assertIn("true", result)

    def test_missing_key_preserved(self):
        content = '{\n  "existing": 1\n}'
        engine = self._make_engine_with_content(content)
        result = engine._save_jsonc_with_comments({"nonexistent": 99})
        self.assertNotIn("99", result)
        self.assertIn('"existing": 1', result)

    def test_updates_top_level_multiline_array(self):
        content = '{\n  "items": [\n    "a",\n    "b"\n  ]\n}'
        engine = self._make_engine_with_content(content)
        result = engine._save_jsonc_with_comments({"items": ["x", "y", "z"]})
        self.assertIn('"x"', result)
        self.assertIn('"z"', result)


class TestJsoncProcessConfigSectionOnlyInRange(unittest.TestCase):
    """_jsonc_process_config_section_only_in_range 方法"""

    def setUp(self):
        self.engine = _Engine()

    def test_updates_within_range(self):
        lines = _lines(
            '{\n  "network_security": {\n    "bind_interface": "0.0.0.0"\n  }\n}'
        )
        self.engine._jsonc_process_config_section_only_in_range(
            {"bind_interface": "127.0.0.1"}, lines, (1, 3)
        )
        joined = "\n".join(lines)
        self.assertIn("127.0.0.1", joined)

    def test_invalid_range_noop(self):
        lines = _lines('{\n  "a": 1\n}')
        original = list(lines)
        self.engine._jsonc_process_config_section_only_in_range(
            {"a": 2}, lines, (-1, -1)
        )
        self.assertEqual(lines, original)


# ---------------------------------------------------------------------------
# 边界路径补充（原 test_jsonc_engine_extended.py）
# ---------------------------------------------------------------------------


class TestExtractCurrentValueEdgePaths(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = _Engine()

    def test_multiline_array_non_string_element_skipped(self):
        lines = _lines('{\n  "arr": [\n    123,\n    "valid"\n  ]\n}')
        result = self.engine._extract_current_value(lines, 1, "arr")
        self.assertEqual(result, ["valid"])

    def test_multiline_array_json_decode_failure(self):
        lines = _lines('{\n  "arr": [\n    "ok",\n    "bad\\xvalue"\n  ]\n}')
        result = self.engine._extract_current_value(lines, 1, "arr")
        self.assertIsInstance(result, list)
        self.assertIn("ok", result)

    def test_simple_value_json_decode_fallback(self):
        lines = _lines('{\n  "note": undefined\n}')
        result = self.engine._extract_current_value(lines, 1, "note")
        self.assertEqual(result, "undefined")

    def test_inline_array_regex_no_match_returns_none(self):
        lines = _lines('{\n  "data": "has[open"\n}')
        result = self.engine._extract_current_value(lines, 1, "data")
        self.assertIsNone(result)


class TestFindArrayRangeSimpleEscape(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = _Engine()

    def test_backslash_in_string_element(self):
        lines = _lines('{\n  "paths": [\n    "C:\\\\Users",\n    "D:\\\\Data"\n  ]\n}')
        start, end = self.engine._find_array_range_simple(lines, 1, "paths")
        self.assertEqual(start, 1)
        self.assertEqual(end, 4)


class TestJsoncFindArrayRangeEscape(unittest.TestCase):
    def test_backslash_in_string(self):
        lines = _lines('{\n  "paths": [\n    "C:\\\\Users\\\\test",\n    "ok"\n  ]\n}')
        start, end = JsoncEngineMixin._jsonc_find_array_range(lines, 1, "paths")
        self.assertEqual(start, 1)
        self.assertEqual(end, 4)


class TestJsoncUpdateArrayBlockEdge(unittest.TestCase):
    def test_element_comment_json_decode_failure(self):
        lines = _lines('{\n  "arr": [\n    "bad"extra // 注释\n  ]\n}')
        result = JsoncEngineMixin._jsonc_update_array_block(lines, 1, 3, "arr", ["new"])
        joined = "\n".join(result)
        self.assertIn('"new"', joined)

    def test_multiline_prefix_no_match(self):
        lines = _lines('{\n  "arr": "not an array start [\n  ]\n}')
        result = JsoncEngineMixin._jsonc_update_array_block(lines, 1, 2, "arr", ["val"])
        self.assertIsInstance(result, list)


class TestFindObjectEndLineSingleLineComment(unittest.TestCase):
    def test_brace_after_single_line_comment_start(self):
        lines = _lines('{\n  "a": 1 // comment with }\n}')
        result = JsoncEngineMixin._jsonc_find_object_end_line(lines, 0)
        self.assertEqual(result, 2)


class TestFindKeyLineInObjectRangeEscapeAndComment(unittest.TestCase):
    def test_escaped_quote_in_string_value(self):
        lines = _lines('{\n  "msg": "he said \\"hello\\"",\n  "target": 42\n}')
        result = JsoncEngineMixin._jsonc_find_key_line_in_object_range(
            lines, (0, 3), "target"
        )
        self.assertEqual(result, 2)

    def test_comment_brace_not_counted(self):
        lines = _lines(
            '{\n  "outer": {\n    "x": 1 // 注释含 }\n  },\n  "target": 42\n}'
        )
        result = JsoncEngineMixin._jsonc_find_key_line_in_object_range(
            lines, (0, 5), "target"
        )
        self.assertEqual(result, 4)

    def test_multiline_comment_in_object(self):
        lines = _lines(
            '{\n  /*\n  "hidden": {\n  */\n  "visible": {\n    "x": 1\n  }\n}'
        )
        result = JsoncEngineMixin._jsonc_find_key_line_in_object_range(
            lines, (0, 7), "visible"
        )
        self.assertEqual(result, 4)


class TestFindObjectRangeParserPaths(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = _Engine()

    def test_multiline_comment_before_section(self):
        lines = _lines(
            '{\n  /*\n   * 多行注释 {\n   */\n  "target": {\n    "v": 1\n  }\n}'
        )
        result = self.engine._jsonc_find_object_range(lines, "target")
        self.assertEqual(result, (4, 6))

    def test_escaped_string_before_section(self):
        lines = _lines(
            '{\n  "path": "C:\\\\Users\\\\test",\n  "section": {\n    "k": 1\n  }\n}'
        )
        result = self.engine._jsonc_find_object_range(lines, "section")
        self.assertEqual(result, (2, 4))

    def test_single_line_comment_between_keys(self):
        lines = _lines('{\n  "a": 1, // 注释 {\n  "section": {\n    "k": 1\n  }\n}')
        result = self.engine._jsonc_find_object_range(lines, "section")
        self.assertEqual(result, (2, 4))


class TestFindTopLevelKeyLineParserPaths(unittest.TestCase):
    def test_multiline_comment_contains_key(self):
        lines = _lines('{\n  /*\n  "hidden": 999\n  */\n  "visible": 1\n}')
        result = JsoncEngineMixin._jsonc_find_top_level_key_line(lines, "hidden")
        self.assertEqual(result, -1)
        result2 = JsoncEngineMixin._jsonc_find_top_level_key_line(lines, "visible")
        self.assertEqual(result2, 4)

    def test_escaped_char_in_string_value(self):
        lines = _lines('{\n  "path": "C:\\\\Users\\\\foo",\n  "target": 42\n}')
        result = JsoncEngineMixin._jsonc_find_top_level_key_line(lines, "target")
        self.assertEqual(result, 2)

    def test_comment_brace_not_counted_top_level(self):
        lines = _lines(
            '{\n  "outer": {\n    "x": 1 // 注释含 }\n  },\n  "target": 42\n}'
        )
        result = JsoncEngineMixin._jsonc_find_top_level_key_line(lines, "target")
        self.assertEqual(result, 4)


class TestProcessConfigSectionNotFound(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = _Engine()

    def test_section_not_found_in_file(self):
        lines = _lines('{\n  "web_ui": {\n    "port": 3000\n  }\n}')
        original = list(lines)
        self.engine._jsonc_process_config_section(
            {"missing_section": {"key": "val"}}, lines, (-1, -1)
        )
        self.assertEqual(lines, original)


class TestFindNetworkSecurityRangeEscape(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = _Engine()

    def test_escape_in_value(self):
        lines = _lines(
            '{\n  "network_security": {\n    "label": "path\\\\value"\n  }\n}'
        )
        result = self.engine._find_network_security_range(lines)
        self.assertEqual(result, (1, 3))


class TestSaveJsoncWithCommentsNetworkSecuritySkip(unittest.TestCase):
    def test_network_security_skipped_in_output(self):
        engine = _Engine()
        content = (
            "{\n"
            '  "network_security": {\n'
            '    "bind_interface": "0.0.0.0"\n'
            "  },\n"
            '  "port": 3000\n'
            "}"
        )
        engine._original_content = content
        engine._exclude_network_security = lambda c: c
        result = engine._save_jsonc_with_comments(
            {"network_security": {"bind_interface": "1.2.3.4"}, "port": 9090}
        )
        self.assertIn("9090", result)
        self.assertNotIn("1.2.3.4", result)
        self.assertIn("0.0.0.0", result)


class TestUpdateDictChildNotFound(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = _Engine()

    def test_nested_dict_child_not_found(self):
        lines = _lines('{\n  "section": {\n    "port": 3000\n  }\n}')
        original_joined = "\n".join(lines)
        self.engine._jsonc_update_dict_in_object_range(
            {"nonexistent_child": {"key": "val"}}, lines, 1, 3
        )
        self.assertEqual("\n".join(lines), original_joined)


if __name__ == "__main__":
    unittest.main()
