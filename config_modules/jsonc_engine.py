"""JSONC 解析/定位/更新引擎 Mixin。

提供 ConfigManager 在保存/更新 JSONC 配置文件时所需的
所有行级定位、数组块替换、简单值替换以及嵌套对象递归更新能力。
"""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Any, Dict, cast

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class JsoncEngineMixin:
    """JSONC 格式配置文件的解析/定位/更新方法集合。"""

    # ------------------------------------------------------------------
    # 值提取
    # ------------------------------------------------------------------

    def _extract_current_value(self, lines: list, line_index: int, key: str) -> Any:
        """从配置文件的指定行提取键值（支持数组和简单值）"""
        try:
            line = lines[line_index]
            if "[" in line:
                start_line, end_line = self._find_array_range_simple(
                    lines, line_index, key
                )
                if start_line == end_line:
                    pattern = rf'"{re.escape(key)}"\s*:\s*(\[.*?\])'
                    match = re.search(pattern, line)
                    if match:
                        return json.loads(match.group(1))
                else:
                    array_content = []
                    for i in range(start_line + 1, end_line):
                        array_line = lines[i].strip()
                        if array_line and not array_line.startswith("//"):
                            element = array_line.rstrip(",").strip()
                            if element.startswith('"') and element.endswith('"'):
                                try:
                                    array_content.append(json.loads(element))
                                except (json.JSONDecodeError, ValueError):
                                    pass
                    return array_content
            else:
                key_pattern = rf'"{re.escape(key)}"\s*:\s*'
                key_match = re.search(key_pattern, line)
                if key_match:
                    value_start = key_match.end()
                    remaining = line[value_start:]

                    value_end = 0
                    in_string = False
                    escape_next = False

                    for i, char in enumerate(remaining):
                        if escape_next:
                            escape_next = False
                            continue
                        if char == "\\":
                            escape_next = True
                            continue
                        if char == '"':
                            in_string = not in_string
                            continue
                        if not in_string:
                            if char in ",\n\r" or remaining[i:].lstrip().startswith(
                                ("//", "/*")
                            ):
                                value_end = i
                                break
                    else:
                        value_end = len(remaining)

                    value_str = remaining[:value_end].strip()
                    try:
                        return json.loads(value_str)
                    except (json.JSONDecodeError, ValueError):
                        return value_str
        except Exception:
            pass
        return None

    def _find_array_range_simple(self, lines: list, start_line: int, key: str) -> tuple:
        """查找多行数组的开始和结束行号"""
        start_pattern = rf'"{re.escape(key)}"\s*:\s*\['
        if not re.search(start_pattern, lines[start_line]):
            return start_line, start_line

        bracket_count = 0
        in_string = False
        escape_next = False

        for i in range(start_line, len(lines)):
            line = lines[i]
            for char in line:
                if escape_next:
                    escape_next = False
                    continue
                if char == "\\":
                    escape_next = True
                    continue
                if char == '"':
                    in_string = not in_string
                    continue
                if not in_string:
                    if char == "[":
                        bracket_count += 1
                    elif char == "]":
                        bracket_count -= 1
                        if bracket_count == 0:
                            return start_line, i

        return start_line, start_line

    # ------------------------------------------------------------------
    # JSONC 保存辅助方法
    # ------------------------------------------------------------------

    @staticmethod
    def _jsonc_find_array_range(lines: list, start_line: int, key: str) -> tuple:
        """找到多行数组的开始和结束位置"""
        start_pattern = rf'\s*"{re.escape(key)}"\s*:\s*\['
        if not re.search(start_pattern, lines[start_line]):
            logger.debug(
                f"第{start_line}行不匹配数组开始模式: {lines[start_line].strip()}"
            )
            return start_line, start_line

        bracket_count = 0
        in_string = False
        escape_next = False
        in_single_line_comment = False

        for i in range(start_line, len(lines)):
            line = lines[i]
            in_single_line_comment = False

            j = 0
            while j < len(line):
                char = line[j]

                if escape_next:
                    escape_next = False
                    j += 1
                    continue
                if char == "\\":
                    escape_next = True
                    j += 1
                    continue

                if char == '"' and not in_single_line_comment:
                    in_string = not in_string
                    j += 1
                    continue

                if not in_string and j < len(line) - 1 and line[j : j + 2] == "//":
                    in_single_line_comment = True
                    break

                if not in_string and not in_single_line_comment:
                    if char == "[":
                        bracket_count += 1
                        logger.debug(f"第{i}行找到开括号，计数: {bracket_count}")
                    elif char == "]":
                        bracket_count -= 1
                        logger.debug(f"第{i}行找到闭括号，计数: {bracket_count}")
                        if bracket_count == 0:
                            logger.debug(f"数组 '{key}' 范围: {start_line}-{i}")
                            return start_line, i

                j += 1

        logger.warning(f"未找到数组 '{key}' 的结束括号，可能存在格式问题")
        return start_line, start_line

    @staticmethod
    def _jsonc_update_array_block(
        lines: list, start_line: int, end_line: int, key: str, value: list
    ) -> list:
        """更新整个数组块，保留原有的多行格式和注释"""
        logger.debug(f"更新数组 '{key}': 行范围 {start_line}-{end_line}, 新值: {value}")

        if start_line == end_line:
            line = lines[start_line]
            pattern = rf'(\s*"{re.escape(key)}"\s*:\s*)\[.*?\](.*)'
            match = re.match(pattern, line)
            if match:
                prefix, suffix = match.groups()
                array_str = json.dumps(value, ensure_ascii=False)
                new_line = f"{prefix}{array_str}{suffix}"
                logger.debug(f"单行数组替换: '{line.strip()}' -> '{new_line.strip()}'")
                return [new_line]
            else:
                logger.warning(f"无法匹配单行数组模式，保持原行: {line.strip()}")
            return [line]

        new_lines = []
        original_start_line = lines[start_line]

        start_pattern = rf'(\s*"{re.escape(key)}"\s*:\s*)\[.*'
        match = re.match(start_pattern, original_start_line)
        if match:
            prefix = match.group(1)
            new_lines.append(f"{prefix}[")

            array_comments = []
            element_comments = {}

            for i in range(start_line + 1, end_line):
                line = lines[i].strip()
                if line.startswith("//"):
                    array_comments.append(lines[i])
                elif '"' in line and "//" in line:
                    parts = line.split("//", 1)
                    if len(parts) == 2:
                        element_part = parts[0].strip().rstrip(",").strip()
                        comment_part = "//" + parts[1]
                        try:
                            element_value = json.loads(element_part)
                            element_comments[element_value] = comment_part
                        except (json.JSONDecodeError, ValueError):
                            pass

            if array_comments:
                new_lines.extend(array_comments)

            base_indent = len(original_start_line) - len(original_start_line.lstrip())
            element_indent = "  " * (base_indent // 2 + 1)

            for i, item in enumerate(value):
                item_str = json.dumps(item, ensure_ascii=False)
                comment = element_comments.get(item, "")
                if comment:
                    comment = f" {comment}"

                if i == len(value) - 1:
                    new_lines.append(f"{element_indent}{item_str}{comment}")
                else:
                    new_lines.append(f"{element_indent}{item_str},{comment}")

            end_indent = " " * base_indent
            end_line_content = lines[end_line]
            end_suffix = ""
            if "," in end_line_content:
                end_suffix = ","
            new_lines.append(f"{end_indent}]{end_suffix}")

        return new_lines

    @staticmethod
    def _jsonc_update_simple_value(line: str, key: str, value: Any) -> str:
        """更新简单值（非数组），保留行尾注释和逗号"""
        key_pattern = rf'(\s*"{re.escape(key)}"\s*:\s*)'
        key_match = re.search(key_pattern, line)

        if not key_match:
            return line

        value_start = key_match.end()
        remaining = line[value_start:]

        if isinstance(value, str):
            new_value = json.dumps(value, ensure_ascii=False)
        elif isinstance(value, bool):
            new_value = "true" if value else "false"
        elif value is None:
            new_value = "null"
        else:
            new_value = json.dumps(value, ensure_ascii=False)

        value_end = 0
        in_string = False
        escape_next = False

        for i, char in enumerate(remaining):
            if escape_next:
                escape_next = False
                continue
            if char == "\\":
                escape_next = True
                continue
            if char == '"':
                in_string = not in_string
                continue
            if not in_string:
                if char in ",\n\r" or remaining[i:].lstrip().startswith("//"):
                    value_end = i
                    break
        else:
            value_end = len(remaining)

        suffix = remaining[value_end:]
        return f"{line[:value_start]}{new_value}{suffix}"

    # ------------------------------------------------------------------
    # JSONC 定位/更新（基于"对象范围"，避免同名键误匹配）
    # ------------------------------------------------------------------

    @staticmethod
    def _jsonc_find_object_end_line(
        lines: list[str], start_line: int, end_limit: int | None = None
    ) -> int:
        """
        从 start_line 开始，找到与该对象匹配的右大括号所在行号。

        约束：
        - 忽略字符串与注释中的括号
        - 允许 key 行与 '{' 同行或换行
        """
        if end_limit is None:
            end_limit = len(lines) - 1

        brace_count = 0
        found_open = False
        in_string = False
        escape_next = False
        in_single_line_comment = False
        in_multi_line_comment = False

        for i in range(start_line, min(end_limit, len(lines) - 1) + 1):
            line = lines[i]
            in_single_line_comment = False
            j = 0
            while j < len(line):
                ch = line[j]
                next_two = line[j : j + 2]

                if in_single_line_comment:
                    break

                if in_multi_line_comment:
                    if next_two == "*/":
                        in_multi_line_comment = False
                        j += 2
                        continue
                    j += 1
                    continue

                if in_string:
                    if escape_next:
                        escape_next = False
                        j += 1
                        continue
                    if ch == "\\":
                        escape_next = True
                        j += 1
                        continue
                    if ch == '"':
                        in_string = False
                    j += 1
                    continue

                if next_two == "//":
                    in_single_line_comment = True
                    break
                if next_two == "/*":
                    in_multi_line_comment = True
                    j += 2
                    continue
                if ch == '"':
                    in_string = True
                    j += 1
                    continue

                if ch == "{":
                    brace_count += 1
                    found_open = True
                elif ch == "}":
                    if found_open and brace_count > 0:
                        brace_count -= 1
                        if brace_count == 0:
                            return i

                j += 1

        return min(end_limit, len(lines) - 1)

    @staticmethod
    def _jsonc_find_key_line_in_object_range(
        lines: list[str], obj_range: tuple[int, int], key: str
    ) -> int:
        """
        在给定对象范围内查找 key 的定义行（仅匹配该对象的第一层属性，避免落到嵌套对象）。
        """
        start_line, end_line = obj_range
        if start_line < 0 or end_line < 0 or start_line > end_line:
            return -1

        key_pattern = re.compile(rf'\s*"{re.escape(key)}"\s*:')

        brace_depth = 0
        started = False
        in_string = False
        escape_next = False
        in_single_line_comment = False
        in_multi_line_comment = False

        for i in range(start_line, min(end_line, len(lines) - 1) + 1):
            line = lines[i]

            if started and brace_depth == 1 and not in_multi_line_comment:
                stripped = line.lstrip()
                if (
                    stripped
                    and not stripped.startswith("//")
                    and key_pattern.search(line)
                ):
                    return i

            in_single_line_comment = False
            j = 0
            while j < len(line):
                ch = line[j]
                next_two = line[j : j + 2]

                if in_single_line_comment:
                    break

                if in_multi_line_comment:
                    if next_two == "*/":
                        in_multi_line_comment = False
                        j += 2
                        continue
                    j += 1
                    continue

                if in_string:
                    if escape_next:
                        escape_next = False
                        j += 1
                        continue
                    if ch == "\\":
                        escape_next = True
                        j += 1
                        continue
                    if ch == '"':
                        in_string = False
                    j += 1
                    continue

                if next_two == "//":
                    in_single_line_comment = True
                    break
                if next_two == "/*":
                    in_multi_line_comment = True
                    j += 2
                    continue
                if ch == '"':
                    in_string = True
                    j += 1
                    continue

                if ch == "{":
                    brace_depth += 1
                    started = True
                elif ch == "}":
                    if started and brace_depth > 0:
                        brace_depth -= 1

                j += 1

        return -1

    def _jsonc_find_object_range(
        self,
        lines: list[str],
        key: str,
        parent_object_range: tuple[int, int] | None = None,
    ) -> tuple[int, int]:
        """
        查找 JSONC 中某个 object 字段（"key": { ... }）的行范围 (start_line, end_line)。

        - parent_object_range=None：在文件顶层对象（depth==1）中查找
        - parent_object_range!=None：在父对象第一层属性中查找
        """
        if not lines:
            return (-1, -1)

        if parent_object_range is not None:
            key_line = self._jsonc_find_key_line_in_object_range(
                lines, parent_object_range, key
            )
            if key_line == -1:
                return (-1, -1)
            end_line = self._jsonc_find_object_end_line(
                lines, key_line, end_limit=parent_object_range[1]
            )
            return (key_line, end_line)

        key_pattern = re.compile(rf'\s*"{re.escape(key)}"\s*:')
        brace_depth = 0
        started = False
        in_string = False
        escape_next = False
        in_single_line_comment = False
        in_multi_line_comment = False

        for i, line in enumerate(lines):
            if started and brace_depth == 1 and not in_multi_line_comment:
                stripped = line.lstrip()
                if (
                    stripped
                    and not stripped.startswith("//")
                    and key_pattern.search(line)
                ):
                    end_line = self._jsonc_find_object_end_line(lines, i)
                    return (i, end_line)

            in_single_line_comment = False
            j = 0
            while j < len(line):
                ch = line[j]
                next_two = line[j : j + 2]

                if in_single_line_comment:
                    break

                if in_multi_line_comment:
                    if next_two == "*/":
                        in_multi_line_comment = False
                        j += 2
                        continue
                    j += 1
                    continue

                if in_string:
                    if escape_next:
                        escape_next = False
                        j += 1
                        continue
                    if ch == "\\":
                        escape_next = True
                        j += 1
                        continue
                    if ch == '"':
                        in_string = False
                    j += 1
                    continue

                if next_two == "//":
                    in_single_line_comment = True
                    break
                if next_two == "/*":
                    in_multi_line_comment = True
                    j += 2
                    continue
                if ch == '"':
                    in_string = True
                    j += 1
                    continue

                if ch == "{":
                    brace_depth += 1
                    started = True
                elif ch == "}":
                    if started and brace_depth > 0:
                        brace_depth -= 1

                j += 1

        return (-1, -1)

    @staticmethod
    def _jsonc_find_top_level_key_line(lines: list[str], key: str) -> int:
        """在文件顶层对象（depth==1）查找 key 的定义行（避免落到嵌套对象）。"""
        if not lines:
            return -1

        key_pattern = re.compile(rf'\s*"{re.escape(key)}"\s*:')
        brace_depth = 0
        started = False
        in_string = False
        escape_next = False
        in_single_line_comment = False
        in_multi_line_comment = False

        for i, line in enumerate(lines):
            if started and brace_depth == 1 and not in_multi_line_comment:
                stripped = line.lstrip()
                if (
                    stripped
                    and not stripped.startswith("//")
                    and key_pattern.search(line)
                ):
                    return i

            in_single_line_comment = False
            j = 0
            while j < len(line):
                ch = line[j]
                next_two = line[j : j + 2]

                if in_single_line_comment:
                    break

                if in_multi_line_comment:
                    if next_two == "*/":
                        in_multi_line_comment = False
                        j += 2
                        continue
                    j += 1
                    continue

                if in_string:
                    if escape_next:
                        escape_next = False
                        j += 1
                        continue
                    if ch == "\\":
                        escape_next = True
                        j += 1
                        continue
                    if ch == '"':
                        in_string = False
                    j += 1
                    continue

                if next_two == "//":
                    in_single_line_comment = True
                    break
                if next_two == "/*":
                    in_multi_line_comment = True
                    j += 2
                    continue
                if ch == '"':
                    in_string = True
                    j += 1
                    continue

                if ch == "{":
                    brace_depth += 1
                    started = True
                elif ch == "}":
                    if started and brace_depth > 0:
                        brace_depth -= 1

                j += 1

        return -1

    def _jsonc_update_dict_in_object_range(
        self,
        config_dict: Dict[str, Any],
        result_lines: list[str],
        object_start_line: int,
        object_end_line: int,
    ) -> None:
        """
        在给定对象范围内更新 config_dict 的键值（递归支持嵌套对象）。

        说明：
        - 仅更新文件中已存在的键（不做插入），避免破坏原有格式/注释结构
        - 数组使用块更新，简单值使用行内替换（保留行尾注释/逗号）
        """
        if object_start_line < 0 or object_end_line < 0:
            return

        for key, value in (config_dict or {}).items():
            current_end_line = self._jsonc_find_object_end_line(
                result_lines, object_start_line, end_limit=len(result_lines) - 1
            )
            obj_range = (object_start_line, current_end_line)

            if isinstance(value, dict):
                child_range = self._jsonc_find_object_range(
                    result_lines, key, parent_object_range=obj_range
                )
                if child_range[0] != -1:
                    self._jsonc_update_dict_in_object_range(
                        cast(Dict[str, Any], value),
                        result_lines,
                        child_range[0],
                        child_range[1],
                    )
                continue

            line_index = self._jsonc_find_key_line_in_object_range(
                result_lines, obj_range, key
            )
            if line_index == -1:
                continue

            if isinstance(value, list):
                start_line, end_line = self._jsonc_find_array_range(
                    result_lines, line_index, key
                )
                new_array_lines = self._jsonc_update_array_block(
                    result_lines, start_line, end_line, key, value
                )
                result_lines[start_line : end_line + 1] = new_array_lines
            else:
                result_lines[line_index] = self._jsonc_update_simple_value(
                    result_lines[line_index], key, value
                )

    def _jsonc_process_config_section(
        self,
        config_dict: Dict[str, Any],
        result_lines: list,
        network_security_range: tuple,
        section_name: str = "",
    ):
        """
        兼容保留：旧实现曾按 key 字符串全局匹配，存在同名键误更新风险（例如 enabled/debug）。

        新实现按"顶层 section 对象范围"更新，避免跨 section 写错配置。
        """
        del section_name
        if not isinstance(config_dict, dict):
            return

        for top_key, top_value in config_dict.items():
            if top_key == "network_security":
                continue
            if not isinstance(top_value, dict):
                continue

            obj_range = self._jsonc_find_object_range(
                cast(list[str], result_lines), str(top_key), parent_object_range=None
            )
            if obj_range[0] == -1:
                continue

            self._jsonc_update_dict_in_object_range(
                cast(Dict[str, Any], top_value),
                cast(list[str], result_lines),
                obj_range[0],
                obj_range[1],
            )

    def _find_network_security_range(self, lines: list) -> tuple:
        """查找 network_security 配置段的行范围，未找到返回 (-1, -1)"""
        start_line = -1

        for i, line in enumerate(lines):
            if (
                '"network_security"' in line
                and ":" in line
                and not line.strip().startswith("//")
            ):
                start_line = i
                break

        if start_line == -1:
            return (-1, -1)

        brace_count = 0
        in_string = False
        escape_next = False

        for i in range(start_line, len(lines)):
            line = lines[i]
            for char in line:
                if escape_next:
                    escape_next = False
                    continue
                if char == "\\":
                    escape_next = True
                    continue
                if char == '"':
                    in_string = not in_string
                    continue
                if not in_string:
                    if char == "{":
                        brace_count += 1
                    elif char == "}":
                        brace_count -= 1
                        if brace_count == 0:
                            end_line = i
                            logger.debug(
                                f"找到 network_security 段范围: {start_line}-{end_line}"
                            )
                            return (start_line, end_line)

        logger.warning("未找到 network_security 段的结束位置")
        return (start_line, len(lines) - 1)

    # ------------------------------------------------------------------
    # JSONC 保存（保留注释格式）
    # ------------------------------------------------------------------

    def _save_jsonc_with_comments(self, config: Dict[str, Any]) -> str:
        """保存 JSONC 配置并保留原有注释和格式，排除 network_security"""
        config_to_save = self._exclude_network_security(config.copy())  # type: ignore[attr-defined]

        if not self._original_content:  # type: ignore[attr-defined]
            return json.dumps(config_to_save, indent=2, ensure_ascii=False)

        lines = self._original_content.split("\n")  # type: ignore[attr-defined]
        result_lines = lines.copy()

        for top_key, top_value in config_to_save.items():
            if top_key == "network_security":
                continue
            if isinstance(top_value, dict):
                obj_range = self._jsonc_find_object_range(result_lines, str(top_key))
                if obj_range[0] == -1:
                    continue

                self._jsonc_update_dict_in_object_range(
                    cast(Dict[str, Any], top_value),
                    result_lines,
                    obj_range[0],
                    obj_range[1],
                )
            else:
                line_index = self._jsonc_find_top_level_key_line(
                    result_lines, str(top_key)
                )
                if line_index == -1:
                    continue

                if isinstance(top_value, list):
                    start_line, end_line = self._jsonc_find_array_range(
                        result_lines, line_index, str(top_key)
                    )
                    new_array_lines = self._jsonc_update_array_block(
                        result_lines,
                        start_line,
                        end_line,
                        str(top_key),
                        cast(list, top_value),
                    )
                    result_lines[start_line : end_line + 1] = new_array_lines
                else:
                    result_lines[line_index] = self._jsonc_update_simple_value(
                        result_lines[line_index], str(top_key), top_value
                    )

        return "\n".join(result_lines)

    def _jsonc_process_config_section_only_in_range(
        self, config_dict: Dict[str, Any], result_lines: list, ns_range: tuple
    ):
        """仅在指定对象范围内递归更新 key/value（用于 network_security 段写回）"""
        start_line, end_line = ns_range
        if start_line < 0 or end_line < 0:
            return
        self._jsonc_update_dict_in_object_range(
            config_dict, cast(list[str], result_lines), start_line, end_line
        )
