"""jsonc_engine.py 扩展单元测试。

覆盖基础测试未触及的内部解析路径：
- 转义字符在字符串中的处理（escape_next 路径）
- 多行注释（/* ... */）的跨行解析
- JSON 解码失败的降级路径
- _save_jsonc_with_comments 中 network_security 跳过逻辑
- _jsonc_process_config_section 中 section 未找到的跳过逻辑
"""

from __future__ import annotations

import unittest
from typing import Any

from config_modules.jsonc_engine import JsoncEngineMixin


class _Engine(JsoncEngineMixin):
    """最小测试桩。"""

    _original_content: str = ""
    _exclude_network_security: Any = None


def _lines(text: str) -> list[str]:
    return text.split("\n")


# =====================================================================
# _extract_current_value 边界路径
# =====================================================================


class TestExtractCurrentValueEdgePaths(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = _Engine()

    def test_multiline_array_non_string_element_skipped(self):
        """多行数组中非引号元素被跳过（47->43 分支）"""
        lines = _lines('{\n  "arr": [\n    123,\n    "valid"\n  ]\n}')
        result = self.engine._extract_current_value(lines, 1, "arr")
        self.assertEqual(result, ["valid"])

    def test_multiline_array_json_decode_failure(self):
        """多行数组中引号包裹但 JSON 解码失败的元素被跳过（lines 50-51）"""
        lines = _lines('{\n  "arr": [\n    "ok",\n    "bad\\xvalue"\n  ]\n}')
        result = self.engine._extract_current_value(lines, 1, "arr")
        self.assertIsInstance(result, list)
        self.assertIn("ok", result)

    def test_simple_value_json_decode_fallback(self):
        """非法 JSON 值降级为原始字符串返回（lines 86-87）"""
        lines = _lines('{\n  "note": undefined\n}')
        result = self.engine._extract_current_value(lines, 1, "note")
        self.assertEqual(result, "undefined")

    def test_inline_array_regex_no_match_returns_none(self):
        """行内含 [ 但无闭合 ] 时内联数组正则不匹配 → None（39->90 分支）"""
        lines = _lines('{\n  "data": "has[open"\n}')
        result = self.engine._extract_current_value(lines, 1, "data")
        self.assertIsNone(result)


# =====================================================================
# _find_array_range_simple 转义字符路径
# =====================================================================


class TestFindArrayRangeSimpleEscape(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = _Engine()

    def test_backslash_in_string_element(self):
        """数组字符串中包含反斜杠时 escape_next 路径被触发（lines 106-110）"""
        lines = _lines('{\n  "paths": [\n    "C:\\\\Users",\n    "D:\\\\Data"\n  ]\n}')
        start, end = self.engine._find_array_range_simple(lines, 1, "paths")
        self.assertEqual(start, 1)
        self.assertEqual(end, 4)


# =====================================================================
# _jsonc_find_array_range 转义字符路径
# =====================================================================


class TestJsoncFindArrayRangeEscape(unittest.TestCase):
    def test_backslash_in_string(self):
        """数组中字符串含反斜杠时 escape_next 路径被触发（lines 152-158）"""
        lines = _lines('{\n  "paths": [\n    "C:\\\\Users\\\\test",\n    "ok"\n  ]\n}')
        start, end = JsoncEngineMixin._jsonc_find_array_range(lines, 1, "paths")
        self.assertEqual(start, 1)
        self.assertEqual(end, 4)


# =====================================================================
# _jsonc_update_array_block 边界路径
# =====================================================================


class TestJsoncUpdateArrayBlockEdge(unittest.TestCase):
    def test_element_comment_json_decode_failure(self):
        """元素行含 " 和 // 但元素部分 JSON 解析失败（lines 230-231）

        需要行内同时含 `"` 和 `//`，且 // 前的部分无法被 json.loads 解析。
        """
        lines = _lines('{\n  "arr": [\n    "bad"extra // 注释\n  ]\n}')
        result = JsoncEngineMixin._jsonc_update_array_block(lines, 1, 3, "arr", ["new"])
        joined = "\n".join(result)
        self.assertIn('"new"', joined)

    def test_multiline_prefix_no_match(self):
        """多行数组 start_pattern 不匹配时返回空列表（211->257 分支）"""
        lines = _lines('{\n  "arr": "not an array start [\n  ]\n}')
        result = JsoncEngineMixin._jsonc_update_array_block(lines, 1, 2, "arr", ["val"])
        self.assertIsInstance(result, list)


# =====================================================================
# _jsonc_find_object_end_line：单行注释含大括号
# =====================================================================


class TestFindObjectEndLineSingleLineComment(unittest.TestCase):
    def test_brace_after_single_line_comment_start(self):
        """单行注释标记后的 } 不应结束对象（line 338: in_single_line_comment break）

        构造场景：行首为非注释代码，中间出现 // 注释，注释后有 }。
        真正的 } 在下一行。
        """
        lines = _lines('{\n  "a": 1 // comment with }\n}')
        result = JsoncEngineMixin._jsonc_find_object_end_line(lines, 0)
        self.assertEqual(result, 2)


# =====================================================================
# _jsonc_find_key_line_in_object_range：转义/注释路径
# =====================================================================


class TestFindKeyLineInObjectRangeEscapeAndComment(unittest.TestCase):
    def test_escaped_quote_in_string_value(self):
        """值中含 \\" 转义引号时不应打断字符串状态（lines 438-444）"""
        lines = _lines('{\n  "msg": "he said \\"hello\\"",\n  "target": 42\n}')
        result = JsoncEngineMixin._jsonc_find_key_line_in_object_range(
            lines, (0, 3), "target"
        )
        self.assertEqual(result, 2)

    def test_comment_brace_not_counted(self):
        """// 注释中的 } 不影响 brace 深度追踪"""
        lines = _lines(
            '{\n  "outer": {\n    "x": 1 // 注释含 }\n  },\n  "target": 42\n}'
        )
        result = JsoncEngineMixin._jsonc_find_key_line_in_object_range(
            lines, (0, 5), "target"
        )
        self.assertEqual(result, 4)

    def test_multiline_comment_in_object(self):
        """/* ... */ 注释跨行时 brace 追踪不应受干扰"""
        lines = _lines(
            '{\n  /*\n  "hidden": {\n  */\n  "visible": {\n    "x": 1\n  }\n}'
        )
        result = JsoncEngineMixin._jsonc_find_key_line_in_object_range(
            lines, (0, 7), "visible"
        )
        self.assertEqual(result, 4)


# =====================================================================
# _jsonc_find_object_range (top-level path)：注释/转义路径
# =====================================================================


class TestFindObjectRangeParserPaths(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = _Engine()

    def test_multiline_comment_before_section(self):
        """/* ... */ 注释在 section 前方时不干扰定位（lines 528-533, 553-555）"""
        lines = _lines(
            '{\n  /*\n   * 多行注释 {\n   */\n  "target": {\n    "v": 1\n  }\n}'
        )
        result = self.engine._jsonc_find_object_range(lines, "target")
        self.assertEqual(result, (4, 6))

    def test_escaped_string_before_section(self):
        """值字符串含反斜杠时 escape_next 路径被触发（lines 537-543）"""
        lines = _lines(
            '{\n  "path": "C:\\\\Users\\\\test",\n  "section": {\n    "k": 1\n  }\n}'
        )
        result = self.engine._jsonc_find_object_range(lines, "section")
        self.assertEqual(result, (2, 4))

    def test_single_line_comment_between_keys(self):
        """// 注释在键之间时 in_single_line_comment 路径被触发（line 525）"""
        lines = _lines('{\n  "a": 1, // 注释 {\n  "section": {\n    "k": 1\n  }\n}')
        result = self.engine._jsonc_find_object_range(lines, "section")
        self.assertEqual(result, (2, 4))


# =====================================================================
# _jsonc_find_top_level_key_line：多行注释/转义路径
# =====================================================================


class TestFindTopLevelKeyLineParserPaths(unittest.TestCase):
    def test_multiline_comment_contains_key(self):
        """多行注释内含目标键名时不应匹配（lines 606-611, 631-633）"""
        lines = _lines('{\n  /*\n  "hidden": 999\n  */\n  "visible": 1\n}')
        result = JsoncEngineMixin._jsonc_find_top_level_key_line(lines, "hidden")
        self.assertEqual(result, -1)
        result2 = JsoncEngineMixin._jsonc_find_top_level_key_line(lines, "visible")
        self.assertEqual(result2, 4)

    def test_escaped_char_in_string_value(self):
        """值中含反斜杠时不应打断解析（lines 615-621）"""
        lines = _lines('{\n  "path": "C:\\\\Users\\\\foo",\n  "target": 42\n}')
        result = JsoncEngineMixin._jsonc_find_top_level_key_line(lines, "target")
        self.assertEqual(result, 2)

    def test_comment_brace_not_counted_top_level(self):
        """// 注释中的 } 不影响顶层 brace 深度追踪"""
        lines = _lines(
            '{\n  "outer": {\n    "x": 1 // 注释含 }\n  },\n  "target": 42\n}'
        )
        result = JsoncEngineMixin._jsonc_find_top_level_key_line(lines, "target")
        self.assertEqual(result, 4)


# =====================================================================
# _jsonc_process_config_section：section 未找到路径
# =====================================================================


class TestProcessConfigSectionNotFound(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = _Engine()

    def test_section_not_found_in_file(self):
        """配置中的 section 在 JSONC 文件中不存在时跳过（line 731）"""
        lines = _lines('{\n  "web_ui": {\n    "port": 3000\n  }\n}')
        original = list(lines)
        self.engine._jsonc_process_config_section(
            {"missing_section": {"key": "val"}},
            lines,
            (-1, -1),
        )
        self.assertEqual(lines, original)


# =====================================================================
# _find_network_security_range：转义字符路径
# =====================================================================


class TestFindNetworkSecurityRangeEscape(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = _Engine()

    def test_escape_in_value(self):
        """值中含反斜杠时 escape_next 路径被触发（lines 764-768）"""
        lines = _lines(
            '{\n  "network_security": {\n    "label": "path\\\\value"\n  }\n}'
        )
        result = self.engine._find_network_security_range(lines)
        self.assertEqual(result, (1, 3))


# =====================================================================
# _save_jsonc_with_comments：network_security 跳过路径
# =====================================================================


class TestSaveJsoncWithCommentsNetworkSecuritySkip(unittest.TestCase):
    def test_network_security_skipped_in_output(self):
        """_save_jsonc_with_comments 应跳过 network_security 键（line 803）

        构造场景：_exclude_network_security 故意不过滤，
        验证 save 内部循环仍跳过 network_security。
        """
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


# =====================================================================
# _jsonc_update_dict_in_object_range：dict child 未找到路径
# =====================================================================


class TestUpdateDictChildNotFound(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = _Engine()

    def test_nested_dict_child_not_found(self):
        """嵌套 dict 子对象在文件中不存在时跳过（677->684 分支）"""
        lines = _lines('{\n  "section": {\n    "port": 3000\n  }\n}')
        original_joined = "\n".join(lines)
        self.engine._jsonc_update_dict_in_object_range(
            {"nonexistent_child": {"key": "val"}}, lines, 1, 3
        )
        self.assertEqual("\n".join(lines), original_joined)


if __name__ == "__main__":
    unittest.main()
