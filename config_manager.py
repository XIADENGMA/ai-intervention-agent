#!/usr/bin/env python3
"""
配置管理模块
统一管理应用程序的所有配置
"""

import json
import logging
import os
import platform
import re
import shutil
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Optional

try:
    from platformdirs import user_config_dir

    PLATFORMDIRS_AVAILABLE = True
except ImportError:
    PLATFORMDIRS_AVAILABLE = False

logger = logging.getLogger(__name__)


class ReadWriteLock:
    """读写锁实现

    允许多个读者同时访问，但写者独占访问，适用于读多写少的场景
    """

    def __init__(self):
        self._read_ready = threading.Condition(threading.RLock())
        self._readers = 0

    @contextmanager
    def read_lock(self):
        """获取读锁的上下文管理器

        Yields:
            None: 在持有读锁期间执行
        """
        self._read_ready.acquire()
        try:
            self._readers += 1
        finally:
            self._read_ready.release()

        try:
            yield
        finally:
            self._read_ready.acquire()
            try:
                self._readers -= 1
                if self._readers == 0:
                    self._read_ready.notify_all()
            finally:
                self._read_ready.release()

    @contextmanager
    def write_lock(self):
        """获取写锁的上下文管理器

        Yields:
            None: 在持有写锁期间执行（独占访问）
        """
        self._read_ready.acquire()
        try:
            while self._readers > 0:
                self._read_ready.wait()
            yield
        finally:
            self._read_ready.release()


def parse_jsonc(content: str) -> Dict[str, Any]:
    """解析 JSONC (JSON with Comments) 格式的内容

    Args:
        content: JSONC 格式的字符串内容

    Returns:
        Dict[str, Any]: 解析后的字典对象

    Raises:
        json.JSONDecodeError: JSON 解析失败
    """
    lines = content.split("\n")
    cleaned_lines = []
    in_multiline_comment = False

    for line in lines:
        if in_multiline_comment:
            # 查找多行注释结束
            if "*/" in line:
                line = line[line.find("*/") + 2 :]
                in_multiline_comment = False
            else:
                continue

        # 处理多行注释开始
        if "/*" in line:
            before_comment = line[: line.find("/*")]
            after_comment = line[line.find("/*") :]
            if "*/" in after_comment:
                # 单行内的多行注释
                line = before_comment + after_comment[after_comment.find("*/") + 2 :]
            else:
                # 多行注释开始
                line = before_comment
                in_multiline_comment = True

        # 移除单行注释 //（但要注意字符串内的 //）
        in_string = False
        escape_next = False
        comment_pos = -1

        for i, char in enumerate(line):
            if escape_next:
                escape_next = False
                continue
            if char == "\\":
                escape_next = True
                continue
            if char == '"':
                in_string = not in_string
                continue
            if (
                not in_string
                and char == "/"
                and i + 1 < len(line)
                and line[i + 1] == "/"
            ):
                comment_pos = i
                break

        if comment_pos >= 0:
            line = line[:comment_pos]

        cleaned_lines.append(line)

    cleaned_content = "\n".join(cleaned_lines)

    # 解析 JSON
    return json.loads(cleaned_content)


def _is_uvx_mode() -> bool:
    """检测是否为 uvx 方式运行

    通过检查以下特征判断：
    1. 执行路径是否包含 uvx 相关路径
    2. 环境变量是否包含 uvx 标识
    3. 当前工作目录是否为临时目录

    Returns:
        bool: True 表示 uvx 模式，False 表示开发模式
    """
    executable_path = sys.executable
    if "uvx" in executable_path or ".local/share/uvx" in executable_path:
        return True

    # 检查环境变量
    if os.getenv("UVX_PROJECT"):
        return True

    current_dir = Path.cwd()
    dev_files = ["pyproject.toml", "setup.py", "setup.cfg", ".git"]

    for path in [current_dir] + list(current_dir.parents):
        if any((path / dev_file).exists() for dev_file in dev_files):
            return False

    return True


def find_config_file(config_filename: str = "config.jsonc") -> Path:
    """查找配置文件路径

    根据运行方式查找配置文件：
    - uvx 方式：只使用用户配置目录的全局配置
    - 开发模式：优先当前目录，然后用户配置目录

    跨平台配置目录位置：
    - Linux: ~/.config/ai-intervention-agent/
    - macOS: ~/Library/Application Support/ai-intervention-agent/
    - Windows: %APPDATA%/ai-intervention-agent/

    Args:
        config_filename: 配置文件名，默认为 "config.jsonc"

    Returns:
        Path: 配置文件的路径对象
    """
    # 检测是否为uvx方式运行
    is_uvx_mode = _is_uvx_mode()

    if is_uvx_mode:
        logger.info("检测到uvx运行模式，使用用户配置目录")
    else:
        logger.info("检测到开发模式，优先使用当前目录配置")

    if not is_uvx_mode:
        # 开发模式：1. 检查当前工作目录
        current_dir_config = Path(config_filename)
        if current_dir_config.exists():
            logger.info(f"使用当前目录的配置文件: {current_dir_config.absolute()}")
            return current_dir_config

        # 向后兼容：检查当前目录的.json文件
        if config_filename == "config.jsonc":
            current_dir_json = Path("config.json")
            if current_dir_json.exists():
                logger.info(
                    f"使用当前目录的JSON配置文件: {current_dir_json.absolute()}"
                )
                return current_dir_json

    # 2. 检查用户配置目录（使用跨平台标准位置）
    try:
        # 尝试使用 platformdirs 库获取标准配置目录
        try:
            if not PLATFORMDIRS_AVAILABLE:
                raise ImportError("platformdirs not available")
            user_config_dir_path = Path(user_config_dir("ai-intervention-agent"))
        except ImportError:
            # 如果没有 platformdirs，回退到手动判断
            user_config_dir_path = _get_user_config_dir_fallback()

        user_config_file = user_config_dir_path / config_filename

        if user_config_file.exists():
            logger.info(f"使用用户配置目录的配置文件: {user_config_file}")
            return user_config_file

        # 向后兼容：检查用户配置目录的.json文件
        if config_filename == "config.jsonc":
            user_json_file = user_config_dir_path / "config.json"
            if user_json_file.exists():
                logger.info(f"使用用户配置目录的JSON配置文件: {user_json_file}")
                return user_json_file

        # 3. 如果都不存在，返回用户配置目录路径（用于创建默认配置）
        logger.info(f"配置文件不存在，将在用户配置目录创建: {user_config_file}")
        return user_config_file

    except Exception as e:
        logger.warning(f"获取用户配置目录失败: {e}，使用当前目录")
        return Path(config_filename)


def _get_user_config_dir_fallback() -> Path:
    """获取用户配置目录的回退实现

    不依赖 platformdirs，手动判断平台并返回标准配置目录

    Returns:
        Path: 用户配置目录路径
    """
    system = platform.system().lower()
    home = Path.home()

    if system == "windows":
        appdata = os.getenv("APPDATA")
        if appdata:
            return Path(appdata) / "ai-intervention-agent"
        else:
            return home / "AppData" / "Roaming" / "ai-intervention-agent"
    elif system == "darwin":
        return home / "Library" / "Application Support" / "ai-intervention-agent"
    else:
        xdg_config_home = os.getenv("XDG_CONFIG_HOME")
        if xdg_config_home:
            return Path(xdg_config_home) / "ai-intervention-agent"
        else:
            return home / ".config" / "ai-intervention-agent"


class ConfigManager:
    """配置管理器

    统一管理应用程序配置，支持：
    - JSONC 格式配置文件
    - 跨平台配置目录
    - 配置热重载
    - 网络安全配置独立管理
    - 线程安全的读写操作
    """

    def __init__(self, config_file: str = "config.jsonc"):
        # 使用新的配置文件查找逻辑
        self.config_file = find_config_file(config_file)

        self._config = {}
        # 使用读写锁提高并发性能
        self._rw_lock = ReadWriteLock()
        self._lock = threading.RLock()  # 保留原有锁用于向后兼容
        self._original_content: Optional[str] = None  # 保存原始文件内容
        self._last_access_time = time.time()  # 跟踪最后访问时间

        # 性能优化：配置写入缓冲机制
        self._pending_changes = {}  # 待写入的配置变更
        self._save_timer: Optional[threading.Timer] = None  # 延迟保存定时器
        self._save_delay = 3.0  # 延迟保存时间（秒）
        self._last_save_time = 0  # 上次保存时间

        self._load_config()

    def _get_default_config(self) -> Dict[str, Any]:
        """获取默认配置"""
        return {
            "notification": {
                "enabled": True,
                "web_enabled": True,
                "auto_request_permission": True,
                "sound_enabled": True,
                "sound_mute": False,
                "sound_volume": 80,
                "mobile_optimized": True,
                "mobile_vibrate": True,
                "bark_enabled": False,
                "bark_url": "https://api.day.app/push",
                "bark_device_key": "",
                "bark_icon": "",
                "bark_action": "none",
            },
            "web_ui": {
                "host": "127.0.0.1",  # 默认仅本地访问，提升安全性
                "port": 8080,
                "debug": False,
                "max_retries": 3,
                "retry_delay": 1.0,
            },
            "network_security": {
                "bind_interface": "0.0.0.0",  # 允许所有接口访问
                "allowed_networks": [
                    "127.0.0.0/8",  # 本地回环地址
                    "::1/128",  # IPv6本地回环地址
                    "192.168.0.0/16",  # 私有网络 192.168.x.x
                    "10.0.0.0/8",  # 私有网络 10.x.x.x
                    "172.16.0.0/12",  # 私有网络 172.16.x.x - 172.31.x.x
                ],
                "blocked_ips": [],  # IP黑名单
                "enable_access_control": True,  # 是否启用访问控制
            },
            "feedback": {"timeout": 600},
        }

    def _load_config(self):
        """加载配置文件"""
        with self._lock:
            try:
                if self.config_file.exists():
                    with open(self.config_file, "r", encoding="utf-8") as f:
                        content = f.read()

                    # 保存原始内容（用于保留注释）
                    self._original_content = content

                    # 根据文件扩展名选择解析方式
                    if self.config_file.suffix.lower() == ".jsonc":
                        full_config = parse_jsonc(content)
                        logger.info(f"JSONC 配置文件已加载: {self.config_file}")
                    else:
                        full_config = json.loads(content)
                        logger.info(f"JSON 配置文件已加载: {self.config_file}")

                    # 完全排除 network_security，不加载到内存中
                    self._config = {}
                    for key, value in full_config.items():
                        if key != "network_security":
                            self._config[key] = value

                    if "network_security" in full_config:
                        logger.debug("network_security 配置已排除，不加载到内存中")
                else:
                    # 创建默认配置文件
                    self._config = self._get_default_config()
                    # 从默认配置中也排除 network_security
                    if "network_security" in self._config:
                        del self._config["network_security"]
                    self._create_default_config_file()
                    logger.info(f"创建默认配置文件: {self.config_file}")

                # 合并默认配置（确保新增的配置项存在）
                default_config = self._get_default_config()
                # 从默认配置中排除 network_security
                if "network_security" in default_config:
                    del default_config["network_security"]

                self._config = self._merge_config(default_config, self._config)

            except Exception as e:
                logger.error(f"加载配置文件失败: {e}")
                self._config = self._get_default_config()
                # 从默认配置中排除 network_security
                if "network_security" in self._config:
                    del self._config["network_security"]

    def _merge_config(
        self, default: Dict[str, Any], current: Dict[str, Any]
    ) -> Dict[str, Any]:
        """合并配置，确保所有默认键都存在，但保持现有值不变"""
        result = current.copy()  # 以当前配置为基础

        # 只添加缺失的默认键，不修改现有值
        for key, default_value in default.items():
            # 额外安全措施：确保不合并 network_security
            if key == "network_security":
                logger.debug("_merge_config: 跳过 network_security 配置")
                continue

            if key not in result:
                # 缺失的键，使用默认值
                result[key] = default_value
            elif isinstance(result[key], dict) and isinstance(default_value, dict):
                # 递归合并嵌套字典，但保持现有值优先
                result[key] = self._merge_config(default_value, result[key])

        # 确保结果中不包含 network_security
        if "network_security" in result:
            del result["network_security"]
            logger.debug("_merge_config: 从合并结果中移除 network_security")

        return result

    def _extract_current_value(self, lines: list, line_index: int, key: str) -> Any:
        """从当前行中提取配置值"""
        try:
            line = lines[line_index]
            # 对于数组类型
            if "[" in line:
                start_line, end_line = self._find_array_range_simple(
                    lines, line_index, key
                )
                if start_line == end_line:
                    # 单行数组
                    pattern = rf'"{re.escape(key)}"\s*:\s*(\[.*?\])'
                    match = re.search(pattern, line)
                    if match:
                        return json.loads(match.group(1))
                else:
                    # 多行数组，重新构建数组
                    array_content = []
                    for i in range(start_line + 1, end_line):
                        array_line = lines[i].strip()
                        if array_line and not array_line.startswith("//"):
                            # 提取数组元素
                            element = array_line.rstrip(",").strip()
                            if element.startswith('"') and element.endswith('"'):
                                try:
                                    array_content.append(json.loads(element))
                                except (json.JSONDecodeError, ValueError):
                                    pass
                    return array_content
            else:
                # 简单值
                pattern = rf'"{re.escape(key)}"\s*:\s*([^,\n\r]+)'
                match = re.search(pattern, line)
                if match:
                    value_str = match.group(1).strip()
                    # 移除行尾注释
                    if "//" in value_str:
                        value_str = value_str.split("//")[0].strip()
                    try:
                        return json.loads(value_str)
                    except (json.JSONDecodeError, ValueError):
                        return value_str
        except Exception:
            pass
        return None

    def _find_array_range_simple(self, lines: list, start_line: int, key: str) -> tuple:
        """简化版的数组范围查找"""
        # 确认开始行确实是数组开始
        start_pattern = rf'"{re.escape(key)}"\s*:\s*\['
        if not re.search(start_pattern, lines[start_line]):
            return start_line, start_line

        # 查找数组结束位置
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

    def _find_network_security_range(self, lines: list) -> tuple:
        """找到 network_security 配置段的行范围"""
        start_line = -1
        end_line = -1

        # 查找 network_security 段的开始
        for i, line in enumerate(lines):
            if (
                '"network_security"' in line
                and ":" in line
                and not line.strip().startswith("//")
            ):
                start_line = i
                break

        if start_line == -1:
            return (-1, -1)  # 未找到 network_security 段

        # 查找对应的结束位置（找到匹配的右大括号）
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

    def _save_jsonc_with_comments(self, config: Dict[str, Any]) -> str:
        """保存 JSONC 格式配置，保留原有注释和格式"""
        # 双重保险：确保 network_security 不被处理
        config_to_save = config.copy()
        if "network_security" in config_to_save:
            del config_to_save["network_security"]
            logger.debug("_save_jsonc_with_comments: 排除 network_security 配置")

        if not self._original_content:
            # 如果没有原始内容，使用标准 JSON 格式
            return json.dumps(config_to_save, indent=2, ensure_ascii=False)

        lines = self._original_content.split("\n")
        result_lines = lines.copy()

        # 找到 network_security 段的行范围，确保不会修改该段内容
        network_security_range = self._find_network_security_range(lines)

        def find_array_range(lines: list, start_line: int, key: str) -> tuple:
            """找到多行数组的开始和结束位置"""
            # 确认开始行确实是数组开始
            start_pattern = rf'\s*"{re.escape(key)}"\s*:\s*\['
            if not re.search(start_pattern, lines[start_line]):
                logger.debug(
                    f"第{start_line}行不匹配数组开始模式: {lines[start_line].strip()}"
                )
                return start_line, start_line

            # 查找数组结束位置
            bracket_count = 0
            in_string = False
            escape_next = False
            in_single_line_comment = False

            for i in range(start_line, len(lines)):
                line = lines[i]
                in_single_line_comment = False  # 每行重置单行注释状态

                j = 0
                while j < len(line):
                    char = line[j]

                    # 处理转义字符
                    if escape_next:
                        escape_next = False
                        j += 1
                        continue
                    if char == "\\":
                        escape_next = True
                        j += 1
                        continue

                    # 处理字符串
                    if char == '"' and not in_single_line_comment:
                        in_string = not in_string
                        j += 1
                        continue

                    # 处理单行注释
                    if not in_string and j < len(line) - 1 and line[j : j + 2] == "//":
                        in_single_line_comment = True
                        break  # 跳过本行剩余部分

                    # 处理括号（只在非字符串、非注释中）
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

            # 如果没有找到结束括号，记录警告并返回开始行
            logger.warning(f"未找到数组 '{key}' 的结束括号，可能存在格式问题")
            return start_line, start_line

        def update_array_block(
            lines: list, start_line: int, end_line: int, key: str, value: list
        ) -> list:
            """更新整个数组块，保留原有的多行格式和注释"""
            logger.debug(
                f"更新数组 '{key}': 行范围 {start_line}-{end_line}, 新值: {value}"
            )

            if start_line == end_line:
                # 单行数组，直接替换
                line = lines[start_line]
                pattern = rf'(\s*"{re.escape(key)}"\s*:\s*)\[.*?\](.*)'
                match = re.match(pattern, line)
                if match:
                    prefix, suffix = match.groups()
                    array_str = json.dumps(value, ensure_ascii=False)
                    new_line = f"{prefix}{array_str}{suffix}"
                    logger.debug(
                        f"单行数组替换: '{line.strip()}' -> '{new_line.strip()}'"
                    )
                    return [new_line]
                else:
                    logger.warning(f"无法匹配单行数组模式，保持原行: {line.strip()}")
                return [line]

            # 多行数组，保持原有格式
            new_lines = []
            original_start_line = lines[start_line]

            # 保留数组开始行的格式
            start_pattern = rf'(\s*"{re.escape(key)}"\s*:\s*)\[.*'
            match = re.match(start_pattern, original_start_line)
            if match:
                prefix = match.group(1)
                new_lines.append(f"{prefix}[")

                # 提取原始数组中的注释和元素注释
                array_comments = []
                element_comments = {}  # 存储每个元素对应的注释

                for i in range(start_line + 1, end_line):
                    line = lines[i].strip()
                    if line.startswith("//"):
                        array_comments.append(lines[i])
                    elif '"' in line and "//" in line:
                        # 提取元素值和注释
                        parts = line.split("//", 1)
                        if len(parts) == 2:
                            element_part = parts[0].strip().rstrip(",").strip()
                            comment_part = "//" + parts[1]
                            # 尝试解析元素值
                            try:
                                element_value = json.loads(element_part)
                                element_comments[element_value] = comment_part
                            except (json.JSONDecodeError, ValueError):
                                pass

                # 添加数组开头的注释（如果有的话）
                if array_comments:
                    new_lines.extend(array_comments)

                # 添加数组元素，保持原有的缩进格式和行内注释
                base_indent = len(original_start_line) - len(
                    original_start_line.lstrip()
                )
                element_indent = "  " * (base_indent // 2 + 1)

                for i, item in enumerate(value):
                    item_str = json.dumps(item, ensure_ascii=False)
                    # 查找对应的注释
                    comment = element_comments.get(item, "")
                    if comment:
                        comment = f" {comment}"

                    if i == len(value) - 1:
                        # 最后一个元素不加逗号
                        new_lines.append(f"{element_indent}{item_str}{comment}")
                    else:
                        new_lines.append(f"{element_indent}{item_str},{comment}")

                # 添加结束括号，保持与开始行相同的缩进
                end_indent = " " * base_indent
                end_line_content = lines[end_line]
                end_suffix = ""
                if "," in end_line_content:
                    end_suffix = ","
                new_lines.append(f"{end_indent}]{end_suffix}")

            return new_lines

        def update_simple_value(line: str, key: str, value: Any) -> str:
            """更新简单值（非数组），保留行尾注释和逗号"""
            # 使用更简单但更可靠的方法：先找到键值对的位置，然后精确替换值部分
            key_pattern = rf'(\s*"{re.escape(key)}"\s*:\s*)'
            key_match = re.search(key_pattern, line)

            if not key_match:
                return line

            value_start = key_match.end()

            # 从值开始位置查找值的结束位置
            remaining = line[value_start:]

            # 格式化新值
            if isinstance(value, str):
                new_value = json.dumps(value, ensure_ascii=False)
            elif isinstance(value, bool):
                new_value = "true" if value else "false"
            elif value is None:
                new_value = "null"
            else:
                new_value = json.dumps(value, ensure_ascii=False)

            # 找到值的结束位置（遇到逗号、注释或行尾）
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
                # 如果没有找到结束标记，值延续到行尾
                value_end = len(remaining)

            # 重新构造行
            suffix = remaining[value_end:]
            return f"{line[:value_start]}{new_value}{suffix}"

        def process_config_section(config_dict: Dict[str, Any], section_name: str = ""):
            """递归处理配置段"""
            for key, value in config_dict.items():
                current_key = f"{section_name}.{key}" if section_name else key

                # network_security 配置已在调用前被完全排除，这里不需要额外处理

                if isinstance(value, dict):
                    # 递归处理嵌套对象
                    process_config_section(value, current_key)
                else:
                    # 查找键的定义行
                    for i, line in enumerate(result_lines):
                        # 检查当前行是否在 network_security 段内，如果是则跳过
                        if (
                            network_security_range[0] != -1
                            and network_security_range[0]
                            <= i
                            <= network_security_range[1]
                        ):
                            continue

                        # 确保匹配的是键的定义行，而不是注释或其他内容
                        if (
                            f'"{key}"' in line
                            and not line.strip().startswith("//")
                            and ":" in line
                            and line.strip().find(f'"{key}"') < line.strip().find(":")
                        ):
                            # 检查值是否真的发生了变化
                            current_value = self._extract_current_value(
                                result_lines, i, key
                            )
                            if current_value != value:
                                if isinstance(value, list):
                                    # 处理数组类型
                                    start_line, end_line = find_array_range(
                                        result_lines, i, key
                                    )
                                    logger.debug(
                                        f"找到数组 '{key}' 范围: {start_line}-{end_line}"
                                    )

                                    # 记录原始数组内容
                                    original_lines = result_lines[
                                        start_line : end_line + 1
                                    ]
                                    logger.debug(
                                        f"原始数组内容: {[line.strip() for line in original_lines]}"
                                    )

                                    new_array_lines = update_array_block(
                                        result_lines, start_line, end_line, key, value
                                    )

                                    # 记录新数组内容
                                    logger.debug(
                                        f"新数组内容: {[line.strip() for line in new_array_lines]}"
                                    )

                                    # 替换原有的数组行
                                    result_lines[start_line : end_line + 1] = (
                                        new_array_lines
                                    )
                                    logger.debug(f"数组 '{key}' 替换完成")
                                else:
                                    # 处理简单值
                                    result_lines[i] = update_simple_value(
                                        line, key, value
                                    )
                            break

        # 处理配置更新
        process_config_section(config_to_save)

        return "\n".join(result_lines)

    def _create_default_config_file(self):
        """创建带注释的默认配置文件"""
        try:
            # 确保配置文件目录存在
            self.config_file.parent.mkdir(parents=True, exist_ok=True)

            # 尝试使用模板文件
            template_file = Path(__file__).parent / "config.jsonc.default"
            if template_file.exists():
                # 使用模板文件创建配置
                shutil.copy2(template_file, self.config_file)

                # 读取模板文件内容用于保留注释
                with open(template_file, "r", encoding="utf-8") as f:
                    self._original_content = f.read()

                logger.info(f"已从模板文件创建默认配置文件: {self.config_file}")
            else:
                # 回退到使用默认配置字典创建JSON文件
                logger.warning(
                    f"模板文件不存在: {template_file}，使用默认配置创建JSON文件"
                )
                # 获取默认配置并排除 network_security
                default_config = self._get_default_config()
                if "network_security" in default_config:
                    del default_config["network_security"]
                    logger.debug("从默认配置中排除 network_security")

                content = json.dumps(default_config, indent=2, ensure_ascii=False)

                with open(self.config_file, "w", encoding="utf-8") as f:
                    f.write(content)

                # 保存原始内容
                self._original_content = content
                logger.info(f"已创建默认JSON配置文件: {self.config_file}")

        except Exception as e:
            logger.error(f"创建默认配置文件失败: {e}")
            # 如果创建配置文件失败，回退到普通JSON文件
            try:
                # 获取默认配置并排除 network_security
                default_config = self._get_default_config()
                if "network_security" in default_config:
                    del default_config["network_security"]
                    logger.debug("从回退默认配置中排除 network_security")

                content = json.dumps(default_config, indent=2, ensure_ascii=False)
                with open(self.config_file, "w", encoding="utf-8") as f:
                    f.write(content)
                self._original_content = content
                logger.info(f"回退创建JSON配置文件成功: {self.config_file}")
            except Exception as fallback_error:
                logger.error(f"回退创建配置文件也失败: {fallback_error}")
                raise

    def _schedule_save(self):
        """性能优化：调度延迟保存配置文件"""
        with self._lock:
            # 取消之前的保存定时器
            if self._save_timer is not None:
                self._save_timer.cancel()

            # 设置新的延迟保存定时器
            self._save_timer = threading.Timer(self._save_delay, self._delayed_save)
            self._save_timer.start()
            logger.debug(f"已调度配置保存，将在 {self._save_delay} 秒后执行")

    def _delayed_save(self):
        """性能优化：延迟保存配置文件"""
        try:
            with self._lock:
                self._save_timer = None
                # 应用待写入的变更
                if self._pending_changes:
                    logger.debug(
                        f"应用 {len(self._pending_changes)} 个待写入的配置变更"
                    )
                    for key, value in self._pending_changes.items():
                        self._set_config_value(key, value)
                    self._pending_changes.clear()

                # 执行实际保存
                self._save_config_immediate()
                self._last_save_time = time.time()
                logger.debug("延迟配置保存完成")
        except Exception as e:
            logger.error(f"延迟保存配置失败: {e}")

    def _set_config_value(self, key: str, value: Any):
        """设置配置值（内部方法，不触发保存）"""
        keys = key.split(".")
        config = self._config

        # 导航到目标位置
        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]

        # 设置值
        config[keys[-1]] = value

    def _save_config(self):
        """保存配置文件（使用延迟保存优化）"""
        self._schedule_save()

    def _save_config_immediate(self):
        """立即保存配置文件（原始保存逻辑）"""
        try:
            # 确保配置文件目录存在
            self.config_file.parent.mkdir(parents=True, exist_ok=True)

            with open(self.config_file, "w", encoding="utf-8") as f:
                if (
                    self.config_file.suffix.lower() == ".jsonc"
                    and self._original_content
                ):
                    # 对于 JSONC 文件，尝试保留注释
                    content = self._save_jsonc_with_comments(self._config)
                    f.write(content)
                    # 更新原始内容，确保下次更新基于最新内容
                    self._original_content = content
                    logger.debug(
                        f"JSONC 配置文件已保存（保留注释）: {self.config_file}"
                    )
                else:
                    # 对于 JSON 文件或没有原始内容的情况，使用标准 JSON 格式
                    content = json.dumps(self._config, indent=2, ensure_ascii=False)
                    f.write(content)
                    # 更新原始内容
                    self._original_content = content
                    logger.debug(f"JSON 配置文件已保存: {self.config_file}")

            # 验证保存的文件是否有效
            self._validate_saved_config()

        except Exception as e:
            logger.error(f"保存配置文件失败: {e}")
            raise

    def _validate_saved_config(self):
        """验证保存的配置文件是否有效"""
        try:
            with open(self.config_file, "r", encoding="utf-8") as f:
                content = f.read()

            # 尝试解析配置文件
            if self.config_file.suffix.lower() == ".jsonc":
                parsed_config = parse_jsonc(content)
            else:
                parsed_config = json.loads(content)

            # 额外验证：检查是否存在重复的数组元素（格式损坏的标志）
            self._validate_config_structure(parsed_config, content)

            logger.debug("配置文件验证通过")
        except Exception as e:
            logger.error(f"配置文件验证失败: {e}")
            raise

    def _validate_config_structure(self, parsed_config: Dict[str, Any], content: str):
        """验证配置文件结构，检查是否存在格式损坏"""
        # 检查是否存在重复的数组定义（格式损坏的典型标志）
        lines = content.split("\n")
        array_definitions = {}

        for i, line in enumerate(lines):
            # 查找数组定义行
            if '"allowed_networks"' in line and "[" in line:
                if "allowed_networks" in array_definitions:
                    logger.error(
                        f"检测到重复的数组定义 'allowed_networks' 在第{i + 1}行"
                    )
                    raise ValueError(f"配置文件格式损坏：重复的数组定义在第{i + 1}行")
                array_definitions["allowed_networks"] = i + 1

        # 验证network_security配置（如果存在）应该格式正确
        if "network_security" in parsed_config:
            ns_config = parsed_config["network_security"]
            if "allowed_networks" in ns_config:
                allowed_networks = ns_config["allowed_networks"]
                if not isinstance(allowed_networks, list):
                    raise ValueError("network_security.allowed_networks 应该是数组类型")

                # 检查数组元素是否有效
                for network in allowed_networks:
                    if not isinstance(network, str):
                        raise ValueError(
                            f"network_security.allowed_networks 包含无效元素: {network}"
                        )

        logger.debug("配置文件结构验证通过")

    def get(self, key: str, default: Any = None) -> Any:
        """获取配置值，支持点号分隔的嵌套键 - 使用读锁提高并发性能"""
        with self._rw_lock.read_lock():
            self._last_access_time = time.time()
            keys = key.split(".")
            value = self._config
            try:
                for k in keys:
                    value = value[k]
                return value
            except (KeyError, TypeError):
                return default

    def set(self, key: str, value: Any, save: bool = True):
        """设置配置值，支持点号分隔的嵌套键 - 使用写锁确保原子操作"""
        with self._rw_lock.write_lock():
            self._last_access_time = time.time()

            # 性能优化：检查当前值是否与新值相同
            current_value = self.get(key)
            if current_value == value:
                logger.debug(f"配置值未变化，跳过更新: {key} = {value}")
                return

            # 性能优化：使用缓冲机制
            if save:
                # 将变更添加到待写入队列
                self._pending_changes[key] = value
                # 立即更新内存中的配置
                self._set_config_value(key, value)
                # 调度延迟保存
                self._save_config()
            else:
                # 直接更新内存中的配置，不保存
                self._set_config_value(key, value)

            logger.debug(f"配置已更新: {key} = {value}")

    def update(self, updates: Dict[str, Any], save: bool = True):
        """批量更新配置 - 使用写锁确保原子操作"""
        with self._rw_lock.write_lock():
            self._last_access_time = time.time()

            # 性能优化：过滤出真正有变化的配置项
            actual_changes = {}
            for key, value in updates.items():
                current_value = self.get(key)
                if current_value != value:
                    actual_changes[key] = value

            if not actual_changes:
                logger.debug("批量更新中没有配置变化，跳过保存")
                return

            # 性能优化：使用批量缓冲机制
            if save:
                # 将所有变更添加到待写入队列
                self._pending_changes.update(actual_changes)
                # 立即更新内存中的配置
                for key, value in actual_changes.items():
                    self._set_config_value(key, value)
                    logger.debug(f"配置已更新: {key} = {value}")
                # 调度延迟保存（只调度一次）
                self._save_config()
            else:
                # 直接更新内存中的配置，不保存
                for key, value in actual_changes.items():
                    self._set_config_value(key, value)
                    logger.debug(f"配置已更新: {key} = {value}")

            logger.debug(f"批量更新完成，共更新 {len(actual_changes)} 个配置项")

    def force_save(self):
        """强制立即保存配置文件（用于关键操作）"""
        with self._lock:
            # 取消延迟保存定时器
            if self._save_timer is not None:
                self._save_timer.cancel()
                self._save_timer = None

            # 应用所有待写入的变更
            if self._pending_changes:
                logger.debug(
                    f"强制保存：应用 {len(self._pending_changes)} 个待写入的配置变更"
                )
                for key, value in self._pending_changes.items():
                    self._set_config_value(key, value)
                self._pending_changes.clear()

            # 立即保存
            self._save_config_immediate()
            self._last_save_time = time.time()
            logger.debug("强制配置保存完成")

    def get_section(self, section: str) -> Dict[str, Any]:
        """获取配置段"""
        # 特殊处理 network_security 配置段
        if section == "network_security":
            return self.get_network_security_config()
        return self.get(section, {})

    def update_section(self, section: str, updates: Dict[str, Any], save: bool = True):
        """更新配置段"""
        with self._lock:
            current_section = self.get_section(section)

            # 检查是否有任何值真的发生了变化
            has_changes = False
            for key, new_value in updates.items():
                current_value = current_section.get(key)
                if current_value != new_value:
                    has_changes = True
                    logger.debug(
                        f"配置项 '{section}.{key}' 发生变化: {current_value} -> {new_value}"
                    )

            if not has_changes:
                logger.debug(f"配置段 '{section}' 未发生变化，跳过保存")
                return

            # 应用更新
            current_section.update(updates)

            # 直接更新配置并保存，避免重复的值比较
            keys = section.split(".")
            config = self._config
            for k in keys[:-1]:
                if k not in config:
                    config[k] = {}
                config = config[k]
            config[keys[-1]] = current_section

            if save:
                self._save_config()

            logger.debug(f"配置段已更新: {section}")

    def reload(self):
        """重新加载配置文件"""
        logger.info("重新加载配置文件")
        self._load_config()

    def get_all(self) -> Dict[str, Any]:
        """获取所有配置"""
        with self._lock:
            return self._config.copy()

    def get_network_security_config(self) -> Dict[str, Any]:
        """特殊方法：直接从文件读取 network_security 配置

        由于 network_security 配置不加载到内存中，需要特殊方法来读取
        """
        try:
            if not self.config_file.exists():
                # 如果配置文件不存在，返回默认的 network_security 配置
                default_config = self._get_default_config()
                return default_config.get("network_security", {})

            with open(self.config_file, "r", encoding="utf-8") as f:
                content = f.read()

            # 根据文件扩展名选择解析方式
            if self.config_file.suffix.lower() == ".jsonc":
                full_config = parse_jsonc(content)
            else:
                full_config = json.loads(content)

            network_security_config = full_config.get("network_security", {})

            # 如果文件中没有network_security配置，返回默认配置
            if not network_security_config:
                default_config = self._get_default_config()
                network_security_config = default_config.get("network_security", {})
                logger.debug("配置文件中未找到network_security，使用默认配置")

            return network_security_config

        except Exception as e:
            logger.error(f"读取 network_security 配置失败: {e}")
            # 返回默认的 network_security 配置
            default_config = self._get_default_config()
            return default_config.get("network_security", {})


# 全局配置管理器实例
config_manager = ConfigManager()


def get_config() -> ConfigManager:
    """获取配置管理器实例"""
    return config_manager
