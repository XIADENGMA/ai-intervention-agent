#!/usr/bin/env python3
"""
配置管理模块：JSONC/JSON 配置文件的跨平台加载、读写、热重载。

核心特性：读写锁并发、延迟保存优化、network_security 独立管理、文件变更监听。
通过 get_config() 获取全局 ConfigManager 实例。
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
from collections.abc import Callable
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
    """
    读写锁：多读者并发、写者独占，基于 Condition + RLock 实现。
    """

    def __init__(self):
        """初始化读写锁"""
        self._read_ready = threading.Condition(threading.RLock())
        self._readers = 0

    @contextmanager
    def read_lock(self):
        """获取读锁（多读者并发，仅在写者持有锁时阻塞）"""
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
        """获取写锁（独占访问，等待所有读者退出）"""
        self._read_ready.acquire()
        try:
            while self._readers > 0:
                self._read_ready.wait()
            yield
        finally:
            self._read_ready.release()


def parse_jsonc(content: str) -> Dict[str, Any]:
    """
    解析 JSONC（带注释的 JSON）为字典，支持 // 单行注释和 /* */ 多行注释。

    Raises:
        json.JSONDecodeError: JSON 语法错误时抛出
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
    """
    检测是否为 uvx 运行模式（影响配置文件位置选择）。

    检测特征：执行路径含 uvx、UVX_PROJECT 环境变量、项目目录无开发文件。
    uvx 模式使用用户配置目录；开发模式优先使用当前目录配置。
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
    """
    查找配置文件路径，支持环境变量覆盖、uvx 模式和开发模式。

    查找优先级（开发模式）：当前目录 > 用户配置目录 > 创建新配置。
    uvx 模式仅使用用户配置目录。支持 .jsonc/.json 两种格式。
    跨平台配置目录：Linux ~/.config、macOS ~/Library/Application Support、Windows %APPDATA%。
    """
    # 如果调用方显式传入了路径（绝对路径或包含目录层级），应尊重该路径
    # 典型场景：单测/工具代码使用临时文件路径，不应被环境变量覆盖
    requested_path = Path(config_filename).expanduser()
    if requested_path.is_absolute() or requested_path.parent != Path("."):
        return requested_path

    # 【可测试性/可运维性】允许通过环境变量覆盖配置文件路径
    # - 典型用途：pytest/CI 使用临时配置，避免读取用户 ~/.config
    # - 典型用途：容器/部署场景下显式指定配置文件位置
    override = os.environ.get("AI_INTERVENTION_AGENT_CONFIG_FILE")
    if override:
        override_path = Path(override).expanduser()
        # 支持传入目录：自动拼接默认文件名
        if override_path.is_dir():
            override_path = override_path / config_filename
        logger.info(
            f"使用环境变量 AI_INTERVENTION_AGENT_CONFIG_FILE 指定配置文件: {override_path}"
        )
        return override_path

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
    """
    platformdirs 不可用时的回退实现，返回跨平台标准配置目录。

    Windows: %APPDATA%、macOS: ~/Library/Application Support、Linux: $XDG_CONFIG_HOME 或 ~/.config。
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
    """
    配置管理器：JSONC/JSON 配置文件的加载、读写、持久化、热重载。

    核心特性：读写锁并发控制、延迟保存优化、network_security 独立管理（带缓存）、
    文件变更监听、配置导入导出。通过模块级 config_manager 全局实例访问。
    """

    def __init__(self, config_file: str = "config.jsonc"):
        """初始化配置管理器：查找配置文件、初始化锁和缓存、加载配置、启动文件监听"""
        # 使用新的配置文件查找逻辑
        self.config_file = find_config_file(config_file)

        # 初始化配置字典
        self._config = {}

        # 初始化锁机制
        self._rw_lock = ReadWriteLock()  # 读写锁，用于配置读写
        self._lock = threading.RLock()  # 可重入锁，用于延迟保存定时器

        # 初始化文件内容和访问时间
        self._original_content: Optional[str] = None  # 保存原始文件内容（用于保留注释）
        self._last_access_time = time.time()  # 跟踪最后访问时间

        # 性能优化：配置写入缓冲机制
        self._pending_changes = {}  # 待写入的配置变更
        self._save_timer: Optional[threading.Timer] = None  # 延迟保存定时器
        self._save_delay = 3.0  # 延迟保存时间（秒）
        self._last_save_time = 0  # 上次保存时间

        # 【性能优化】network_security 配置缓存
        self._network_security_cache: Optional[Dict[str, Any]] = None
        self._network_security_cache_time: float = 0
        self._network_security_cache_ttl: float = 30.0  # 30 秒缓存有效期

        # 【性能优化】通用 section 缓存层
        self._section_cache: Dict[str, Dict[str, Any]] = {}  # section 名称 -> 缓存数据
        self._section_cache_time: Dict[str, float] = {}  # section 名称 -> 缓存时间
        self._section_cache_ttl: float = 10.0  # section 缓存有效期（秒）

        # 【性能优化】缓存统计
        self._cache_stats = {
            "hits": 0,  # 缓存命中次数
            "misses": 0,  # 缓存未命中次数
            "invalidations": 0,  # 缓存失效次数
        }

        # 【新增】文件监听相关属性
        self._file_watcher_thread: Optional[threading.Thread] = None
        self._file_watcher_running = False
        self._file_watcher_stop_event = threading.Event()  # 用于优雅停止
        self._file_watcher_interval = 2.0  # 检查间隔（秒）
        self._last_file_mtime: float = 0  # 上次文件修改时间
        self._config_change_callbacks: list[
            Callable[[], None]
        ] = []  # 配置变更回调函数列表

        # 加载配置文件
        self._load_config()

        # 初始化文件修改时间
        self._update_file_mtime()

    def _get_default_config(self) -> Dict[str, Any]:
        """返回默认配置字典（notification、web_ui、mdns、network_security、feedback）"""
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
            "mdns": {
                # 是否启用 mDNS
                # - True/False: 强制启用/禁用
                # - None: 自动（当 bind_interface 不是 127.0.0.1/localhost/::1 时启用）
                "enabled": None,
                # mDNS 主机名（默认 ai.local）
                "hostname": "ai.local",
                # DNS-SD 服务实例名（用于服务发现列表展示）
                "service_name": "AI Intervention Agent",
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

    @staticmethod
    def _exclude_network_security(config: Dict[str, Any]) -> Dict[str, Any]:
        """从配置字典中排除 network_security（返回新字典或原地修改）"""
        if "network_security" in config:
            del config["network_security"]
            logger.debug("已从配置中排除 network_security")
        return config

    def _load_config(self):
        """从磁盘加载配置文件，排除 network_security，合并默认配置"""
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
                    self._config = self._exclude_network_security(
                        self._get_default_config()
                    )
                    self._create_default_config_file()
                    logger.info(f"创建默认配置文件: {self.config_file}")

                # 合并默认配置（确保新增的配置项存在）
                default_config = self._exclude_network_security(
                    self._get_default_config()
                )
                self._config = self._merge_config(default_config, self._config)

            except Exception as e:
                logger.error(f"加载配置文件失败: {e}")
                self._config = self._exclude_network_security(
                    self._get_default_config()
                )

    def _merge_config(
        self, default: Dict[str, Any], current: Dict[str, Any]
    ) -> Dict[str, Any]:
        """递归合并配置：补充缺失的默认键，保持用户值优先，排除 network_security"""
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
        self._exclude_network_security(result)
        return result

    def _extract_current_value(self, lines: list, line_index: int, key: str) -> Any:
        """从配置文件的指定行提取键值（支持数组和简单值）"""
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
        """查找多行数组的开始和结束行号"""
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

    # ========================================================================
    # JSONC 保存辅助方法（从 _save_jsonc_with_comments 提取）
    # ========================================================================

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

    def _jsonc_process_config_section(
        self,
        config_dict: Dict[str, Any],
        result_lines: list,
        network_security_range: tuple,
        section_name: str = "",
    ):
        """递归处理配置段，更新变化的值"""
        for key, value in config_dict.items():
            current_key = f"{section_name}.{key}" if section_name else key

            if isinstance(value, dict):
                self._jsonc_process_config_section(
                    value, result_lines, network_security_range, current_key
                )
            else:
                for i, line in enumerate(result_lines):
                    if (
                        network_security_range[0] != -1
                        and network_security_range[0] <= i <= network_security_range[1]
                    ):
                        continue

                    if (
                        f'"{key}"' in line
                        and not line.strip().startswith("//")
                        and ":" in line
                        and line.strip().find(f'"{key}"') < line.strip().find(":")
                    ):
                        current_value = self._extract_current_value(
                            result_lines, i, key
                        )
                        if current_value != value:
                            if isinstance(value, list):
                                start_line, end_line = self._jsonc_find_array_range(
                                    result_lines, i, key
                                )
                                logger.debug(
                                    f"找到数组 '{key}' 范围: {start_line}-{end_line}"
                                )

                                new_array_lines = self._jsonc_update_array_block(
                                    result_lines, start_line, end_line, key, value
                                )

                                result_lines[start_line : end_line + 1] = (
                                    new_array_lines
                                )
                                logger.debug(f"数组 '{key}' 替换完成")
                            else:
                                result_lines[i] = self._jsonc_update_simple_value(
                                    line, key, value
                                )
                        break

    def _find_network_security_range(self, lines: list) -> tuple:
        """查找 network_security 配置段的行范围，未找到返回 (-1, -1)"""
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
        """保存 JSONC 配置并保留原有注释和格式，排除 network_security"""
        # 双重保险：确保 network_security 不被处理
        config_to_save = self._exclude_network_security(config.copy())

        if not self._original_content:
            return json.dumps(config_to_save, indent=2, ensure_ascii=False)

        lines = self._original_content.split("\n")
        result_lines = lines.copy()

        network_security_range = self._find_network_security_range(lines)

        # 使用提取的类方法处理配置更新
        self._jsonc_process_config_section(
            config_to_save, result_lines, network_security_range
        )

        return "\n".join(result_lines)

    def _create_default_config_file(self):
        """创建带注释的默认配置文件（优先使用模板，回退到默认配置字典）"""
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
                default_config = self._exclude_network_security(
                    self._get_default_config()
                )
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
                default_config = self._exclude_network_security(
                    self._get_default_config()
                )
                content = json.dumps(default_config, indent=2, ensure_ascii=False)
                with open(self.config_file, "w", encoding="utf-8") as f:
                    f.write(content)
                self._original_content = content
                logger.info(f"回退创建JSON配置文件成功: {self.config_file}")
            except Exception as fallback_error:
                logger.error(f"回退创建配置文件也失败: {fallback_error}")
                raise

    def _schedule_save(self):
        """调度延迟保存（默认3秒后执行，多次调用合并为一次保存）"""
        with self._lock:
            # 取消之前的保存定时器
            if self._save_timer is not None:
                self._save_timer.cancel()

            # 设置新的延迟保存定时器
            self._save_timer = threading.Timer(self._save_delay, self._delayed_save)
            # 【可靠性】Timer 默认非守护线程，可能导致测试/进程退出被阻塞
            self._save_timer.daemon = True
            self._save_timer.start()
            logger.debug(f"已调度配置保存，将在 {self._save_delay} 秒后执行")

    def _delayed_save(self):
        """延迟保存定时器回调：应用待保存变更并写入文件"""
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
        """内部方法：设置配置值（不触发保存，自动创建中间路径）"""
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
        """触发延迟保存（通过 _schedule_save 调度）"""
        self._schedule_save()

    def _save_config_immediate(self):
        """立即将配置写入文件（JSONC 保留注释，JSON 标准格式），保存后验证"""
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

            # 【关键修复】更新文件修改时间缓存，避免文件监听器把“自己写入”误判为外部变更
            # 这样可以减少重复 reload/回调，降低噪声与额外 I/O
            self._update_file_mtime()

        except Exception as e:
            logger.error(f"保存配置文件失败: {e}")
            raise

    def _validate_saved_config(self):
        """验证保存的配置文件格式和结构是否正确"""
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
        """验证配置结构完整性（检测重复数组定义、network_security 格式等）"""
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
        """获取配置值（支持点号分隔的嵌套键如 'notification.sound_volume'，线程安全）"""
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
        """设置配置值（支持嵌套键，自动创建中间路径，值变化检测，可选延迟保存）"""
        changed = False
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

            # 【缓存优化】失效相关 section 缓存，避免 get_section() 返回旧值
            section = key.split(".")[0] if key else ""
            if section == "network_security":
                # network_security 有独立缓存层，直接清空所有缓存更稳妥
                self.invalidate_all_caches()
            elif section:
                self.invalidate_section_cache(section)
            else:
                self.invalidate_all_caches()

            changed = True
            logger.debug(f"配置已更新: {key} = {value}")

        # 【热更新】配置在内存中更新后，触发回调通知其他模块（在锁外执行，避免死锁）
        if changed:
            try:
                self._trigger_config_change_callbacks()
            except Exception as e:
                logger.debug(f"触发配置变更回调失败（忽略）: {e}")

    def update(self, updates: Dict[str, Any], save: bool = True):
        """批量更新配置（仅处理变化项，合并为一次延迟保存，原子操作）"""
        changed_sections: set[str] = set()
        changed = False
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

            # 【缓存优化】失效涉及到的 section 缓存，避免 get_section() 返回旧值
            for changed_key in actual_changes.keys():
                section = changed_key.split(".")[0] if changed_key else ""
                if section:
                    changed_sections.add(section)

            if "network_security" in changed_sections or not changed_sections:
                self.invalidate_all_caches()
            else:
                for section in changed_sections:
                    self.invalidate_section_cache(section)

            changed = True
            logger.debug(f"批量更新完成，共更新 {len(actual_changes)} 个配置项")

        # 【热更新】配置在内存中更新后，触发回调通知其他模块（在锁外执行，避免死锁）
        if changed:
            try:
                self._trigger_config_change_callbacks()
            except Exception as e:
                logger.debug(f"触发配置变更回调失败（忽略）: {e}")

    def force_save(self):
        """强制立即保存配置文件（取消延迟保存，应用所有待保存变更）"""
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

    def get_section(self, section: str, use_cache: bool = True) -> Dict[str, Any]:
        """获取配置段的深拷贝（带缓存优化，network_security 特殊处理）"""
        import copy

        current_time = time.time()

        # 特殊处理 network_security 配置段
        if section == "network_security":
            # get_network_security_config 已经返回独立对象，但为一致性仍返回拷贝
            return copy.deepcopy(self.get_network_security_config())

        # 【性能优化】检查 section 缓存
        if use_cache and section in self._section_cache:
            cache_time = self._section_cache_time.get(section, 0)
            if current_time - cache_time < self._section_cache_ttl:
                self._cache_stats["hits"] += 1
                logger.debug(f"缓存命中: section={section}")
                return copy.deepcopy(self._section_cache[section])

        # 缓存未命中或已过期
        self._cache_stats["misses"] += 1
        result = self.get(section, {})
        result_copy = copy.deepcopy(result) if result else {}

        # 更新缓存
        self._section_cache[section] = result_copy
        self._section_cache_time[section] = current_time

        return copy.deepcopy(result_copy)

    def update_section(self, section: str, updates: Dict[str, Any], save: bool = True):
        """更新配置段（检测变化，触发回调，可选延迟保存）"""
        changed = False
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

            # 【缓存优化】失效该 section 的缓存
            self.invalidate_section_cache(section)

            changed = True
            logger.debug(f"配置段已更新: {section}")

        # 【热更新】配置段更新后触发回调（在锁外执行，避免死锁）
        if changed:
            try:
                self._trigger_config_change_callbacks()
            except Exception as e:
                logger.debug(f"触发配置变更回调失败（忽略）: {e}")

    def reload(self):
        """从磁盘重新加载配置文件（覆盖内存配置，失效缓存）"""
        logger.info("重新加载配置文件")
        self._load_config()
        # 【缓存优化】重新加载后失效所有缓存
        self.invalidate_all_caches()

    # ========================================================================
    # 缓存管理方法
    # ========================================================================

    def invalidate_section_cache(self, section: str):
        """失效指定配置段的缓存"""
        if section in self._section_cache:
            del self._section_cache[section]
            self._section_cache_time.pop(section, None)
            self._cache_stats["invalidations"] += 1
            logger.debug(f"已失效 section 缓存: {section}")

    def invalidate_all_caches(self):
        """清空所有配置缓存"""
        # 清空 section 缓存
        invalidated_count = len(self._section_cache)
        self._section_cache.clear()
        self._section_cache_time.clear()

        # 清空 network_security 缓存
        self._network_security_cache = None
        self._network_security_cache_time = 0

        self._cache_stats["invalidations"] += invalidated_count + 1
        logger.debug(f"已失效所有缓存 (共 {invalidated_count + 1} 个)")

    def get_cache_stats(self) -> Dict[str, Any]:
        """获取缓存统计（命中/未命中/失效次数、命中率等）"""
        total = self._cache_stats["hits"] + self._cache_stats["misses"]
        hit_rate = self._cache_stats["hits"] / total if total > 0 else 0.0

        return {
            **self._cache_stats,
            "hit_rate": round(hit_rate, 4),
            "section_cache_size": len(self._section_cache),
            "network_security_cached": self._network_security_cache is not None,
        }

    def reset_cache_stats(self):
        """重置缓存统计信息"""
        self._cache_stats = {
            "hits": 0,
            "misses": 0,
            "invalidations": 0,
        }
        logger.debug("已重置缓存统计")

    def set_cache_ttl(
        self,
        section_ttl: float | None = None,
        network_security_ttl: float | None = None,
    ):
        """设置缓存有效期（TTL）"""
        if section_ttl is not None:
            self._section_cache_ttl = max(0.1, section_ttl)  # 最小 0.1 秒
            logger.debug(f"section 缓存 TTL 已设置为: {self._section_cache_ttl}s")

        if network_security_ttl is not None:
            self._network_security_cache_ttl = max(
                1.0, network_security_ttl
            )  # 最小 1 秒
            logger.debug(
                f"network_security 缓存 TTL 已设置为: {self._network_security_cache_ttl}s"
            )

    def get_all(self) -> Dict[str, Any]:
        """获取所有配置的副本（不含 network_security）"""
        with self._lock:
            return self._config.copy()

    def get_network_security_config(self) -> Dict[str, Any]:
        """从文件读取 network_security 配置（带 30 秒缓存，失败返回默认配置）"""
        # 【性能优化】检查缓存是否有效
        current_time = time.time()
        with self._lock:
            if (
                self._network_security_cache is not None
                and current_time - self._network_security_cache_time
                < self._network_security_cache_ttl
            ):
                logger.debug("使用缓存的 network_security 配置")
                return self._network_security_cache

        # 缓存过期或不存在，从文件读取
        try:
            if not self.config_file.exists():
                # 如果配置文件不存在，返回默认的 network_security 配置
                default_config = self._get_default_config()
                result = default_config.get("network_security", {})
                # 缓存默认配置
                with self._lock:
                    self._network_security_cache = result
                    self._network_security_cache_time = current_time
                return result

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

            # 【性能优化】更新缓存
            with self._lock:
                self._network_security_cache = network_security_config
                self._network_security_cache_time = current_time
                logger.debug("已更新 network_security 配置缓存")

            return network_security_config

        except Exception as e:
            logger.error(f"读取 network_security 配置失败: {e}")
            # 返回默认的 network_security 配置
            default_config = self._get_default_config()
            return default_config.get("network_security", {})

    # ========================================================================
    # 类型安全的配置获取方法
    # ========================================================================

    def get_typed(
        self,
        key: str,
        default: Any,
        value_type: type,
        min_val: Optional[Any] = None,
        max_val: Optional[Any] = None,
    ) -> Any:
        """获取配置值，带类型转换和边界验证"""
        from config_utils import clamp_value

        raw_value = self.get(key, default)

        try:
            # 布尔类型特殊处理
            if value_type is bool:
                if isinstance(raw_value, bool):
                    return raw_value
                if isinstance(raw_value, str):
                    return raw_value.lower() in ("true", "1", "yes", "on")
                return bool(raw_value)

            # 其他类型转换
            converted = value_type(raw_value)

            # 边界验证（仅对数值类型）
            if value_type in (int, float) and (
                min_val is not None or max_val is not None
            ):
                if min_val is not None and max_val is not None:
                    return clamp_value(converted, min_val, max_val, key)
                elif min_val is not None:
                    return max(converted, min_val)
                elif max_val is not None:
                    return min(converted, max_val)

            return converted

        except (ValueError, TypeError) as e:
            logger.warning(f"配置 '{key}' 类型转换失败: {e}，使用默认值 {default}")
            return default

    def get_int(
        self,
        key: str,
        default: int = 0,
        min_val: Optional[int] = None,
        max_val: Optional[int] = None,
    ) -> int:
        """获取整数配置值"""
        return self.get_typed(key, default, int, min_val, max_val)

    def get_float(
        self,
        key: str,
        default: float = 0.0,
        min_val: Optional[float] = None,
        max_val: Optional[float] = None,
    ) -> float:
        """获取浮点数配置值"""
        return self.get_typed(key, default, float, min_val, max_val)

    def get_bool(self, key: str, default: bool = False) -> bool:
        """获取布尔配置值"""
        return self.get_typed(key, default, bool)

    def get_str(
        self,
        key: str,
        default: str = "",
        max_length: Optional[int] = None,
    ) -> str:
        """获取字符串配置值（可选截断）"""
        from config_utils import truncate_string

        value = self.get_typed(key, default, str)
        if max_length is not None:
            return truncate_string(value, max_length, key, default=default)
        return value

    # ========================================================================
    # 文件监听功能
    # ========================================================================

    def _update_file_mtime(self):
        """更新文件修改时间缓存"""
        try:
            if self.config_file.exists():
                self._last_file_mtime = self.config_file.stat().st_mtime
        except Exception as e:
            logger.warning(f"获取文件修改时间失败: {e}")

    def start_file_watcher(self, interval: float = 2.0):
        """启动配置文件监听（后台守护线程，检测文件变化自动重载）"""
        if self._file_watcher_running:
            logger.debug("文件监听器已在运行")
            return

        self._file_watcher_interval = interval
        self._file_watcher_running = True
        self._file_watcher_stop_event.clear()  # 清除停止事件
        # 【关键修复】不要在启动监听器时直接覆盖 _last_file_mtime
        # 否则会导致“文件已被外部修改，但因为启动监听器重置了 mtime 基线而丢失一次 reload”
        try:
            if self.config_file.exists():
                current_mtime = self.config_file.stat().st_mtime
                if self._last_file_mtime and current_mtime > self._last_file_mtime:
                    logger.info("启动监听器时发现配置文件已变化，先执行一次重新加载")
                    self._last_file_mtime = current_mtime
                    self.reload()
                    self._trigger_config_change_callbacks()
                elif self._last_file_mtime == 0:
                    # 极端场景：之前没有记录过 mtime，则初始化基线
                    self._last_file_mtime = current_mtime
        except Exception as e:
            logger.warning(f"启动监听器时同步配置文件状态失败: {e}")

        self._file_watcher_thread = threading.Thread(
            target=self._file_watcher_loop,
            name="ConfigFileWatcher",
            daemon=True,  # 守护线程，主程序退出时自动终止
        )
        self._file_watcher_thread.start()
        logger.info(f"配置文件监听器已启动，检查间隔: {interval} 秒")

    def stop_file_watcher(self):
        """停止配置文件监听"""
        if not self._file_watcher_running:
            logger.debug("文件监听器未运行")
            return

        self._file_watcher_running = False
        self._file_watcher_stop_event.set()  # 发送停止信号
        if self._file_watcher_thread:
            self._file_watcher_thread.join(timeout=1.0)  # 快速超时
            self._file_watcher_thread = None
        logger.info("配置文件监听器已停止")

    def shutdown(self):
        """关闭配置管理器：停止文件监听、取消延迟保存定时器（幂等）"""
        # 先停文件监听（内部已幂等）
        try:
            self.stop_file_watcher()
        except Exception as e:
            logger.debug(f"关闭文件监听器失败（忽略）: {e}")

        # 再取消延迟保存定时器，避免 Timer 线程阻塞退出
        try:
            with self._lock:
                if self._save_timer is not None:
                    self._save_timer.cancel()
                    self._save_timer = None
        except Exception as e:
            logger.debug(f"取消延迟保存定时器失败（忽略）: {e}")

    def _file_watcher_loop(self):
        """文件监听循环（后台线程主循环）"""
        logger.debug("文件监听循环已启动")
        while self._file_watcher_running:
            try:
                # 检查文件是否被修改
                if self.config_file.exists():
                    current_mtime = self.config_file.stat().st_mtime
                    if current_mtime > self._last_file_mtime:
                        logger.info("检测到配置文件变化，自动重新加载")
                        self._last_file_mtime = current_mtime
                        self.reload()
                        # 触发配置变更回调
                        self._trigger_config_change_callbacks()
            except Exception as e:
                logger.warning(f"文件监听检查失败: {e}")

            # 等待下一个检查周期（使用可中断的等待）
            if self._file_watcher_stop_event.wait(self._file_watcher_interval):
                break  # 收到停止信号，退出循环

    def register_config_change_callback(self, callback: Callable[[], None]):
        """注册配置变更回调函数"""
        if callback not in self._config_change_callbacks:
            self._config_change_callbacks.append(callback)
            cb_name = getattr(callback, "__name__", None) or repr(callback)
            logger.debug(f"已注册配置变更回调: {cb_name}")

    def unregister_config_change_callback(self, callback: Callable[[], None]):
        """取消注册配置变更回调函数"""
        if callback in self._config_change_callbacks:
            self._config_change_callbacks.remove(callback)
            cb_name = getattr(callback, "__name__", None) or repr(callback)
            logger.debug(f"已取消配置变更回调: {cb_name}")

    def _trigger_config_change_callbacks(self):
        """触发所有配置变更回调"""
        for callback in self._config_change_callbacks:
            try:
                callback()
            except Exception as e:
                cb_name = getattr(callback, "__name__", None) or repr(callback)
                logger.error(f"配置变更回调执行失败 ({cb_name}): {e}")

    @property
    def is_file_watcher_running(self) -> bool:
        """检查文件监听器是否在运行"""
        return self._file_watcher_running

    # ========================================================================
    # 配置导出/导入功能
    # ========================================================================

    def export_config(self, include_network_security: bool = False) -> Dict[str, Any]:
        """导出当前配置（可选包含 network_security）"""
        with self._rw_lock.read_lock():
            export_data = {
                "exported_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "version": "1.0",
                "config": self._config.copy(),
            }

            if include_network_security:
                export_data["network_security"] = self.get_network_security_config()

            return export_data

    def import_config(
        self, config_data: Dict[str, Any], merge: bool = True, save: bool = True
    ) -> bool:
        """导入配置（支持合并或覆盖模式）"""
        try:
            # 验证配置数据
            if not isinstance(config_data, dict):
                logger.error("导入失败：配置数据必须是字典格式")
                return False

            # 提取配置（支持两种格式）
            if "config" in config_data:
                # 从 export_config 导出的格式
                actual_config = config_data["config"]
            else:
                # 直接的配置字典
                actual_config = config_data

            with self._rw_lock.write_lock():
                if merge:
                    # 合并模式：深度合并配置
                    self._deep_merge(self._config, actual_config)
                    logger.info("配置已合并导入")
                else:
                    # 覆盖模式：完全替换
                    self._config = actual_config.copy()
                    logger.info("配置已覆盖导入")

                if save:
                    self._pending_changes.update(actual_config)
                    self._save_config()

            # 触发配置变更回调
            self._trigger_config_change_callbacks()

            return True

        except Exception as e:
            logger.error(f"导入配置失败: {e}")
            return False

    def _deep_merge(self, base: Dict, update: Dict):
        """递归合并 update 到 base"""
        for key, value in update.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._deep_merge(base[key], value)
            else:
                base[key] = value

    def backup_config(self, backup_path: Optional[str] = None) -> str:
        """备份当前配置到文件"""
        import json

        if backup_path is None:
            backup_path = str(self.config_file) + ".backup"

        export_data = self.export_config(include_network_security=True)

        with open(backup_path, "w", encoding="utf-8") as f:
            json.dump(export_data, f, indent=2, ensure_ascii=False)

        logger.info(f"配置已备份到: {backup_path}")
        return backup_path

    def restore_config(self, backup_path: str) -> bool:
        """从备份文件恢复配置"""
        import json

        try:
            with open(backup_path, "r", encoding="utf-8") as f:
                backup_data = json.load(f)

            success = self.import_config(backup_data, merge=False, save=True)
            if success:
                logger.info(f"配置已从 {backup_path} 恢复")
            return success

        except FileNotFoundError:
            logger.error(f"备份文件不存在: {backup_path}")
            return False
        except json.JSONDecodeError as e:
            logger.error(f"备份文件格式错误: {e}")
            return False
        except Exception as e:
            logger.error(f"恢复配置失败: {e}")
            return False


# 全局配置管理器实例
config_manager = ConfigManager()

# 【资源生命周期】进程退出时尽量清理后台资源（文件监听/Timer）
# - 避免测试环境出现“退出卡住/资源未释放”类问题
# - shutdown() 本身幂等，重复调用安全
import atexit  # noqa: E402


def _shutdown_global_config_manager():
    try:
        config_manager.shutdown()
    except Exception:
        # 退出阶段不再抛异常
        pass


atexit.register(_shutdown_global_config_manager)


def get_config() -> ConfigManager:
    """获取全局配置管理器实例（自动启动文件监听）"""
    # 【配置热更新】默认启用文件监听（2 秒轮询，按你的选择 A + C）
    # 目的：外部编辑 config.jsonc 后无需重启即可生效
    try:
        if not config_manager.is_file_watcher_running:
            config_manager.start_file_watcher(interval=2.0)
    except Exception:
        # 配置系统属于基础设施：监听启动失败不应影响主流程
        pass

    return config_manager
