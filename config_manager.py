#!/usr/bin/env python3
"""
配置管理模块

【核心功能】
统一管理应用程序的所有配置，提供跨平台的配置文件管理能力。

【主要特性】
- JSONC 格式支持：支持带注释的 JSON 配置文件，保留用户注释
- 跨平台配置目录：自动识别不同操作系统的标准配置目录位置
- 运行模式检测：区分 uvx 运行模式和开发模式，智能选择配置文件位置
- 配置热重载：支持运行时重新加载配置文件
- 网络安全配置独立管理：network_security 配置段特殊处理，不加载到内存
- 线程安全：使用读写锁实现高性能的并发访问控制
- 延迟保存优化：批量配置更新时减少磁盘 I/O 次数
- 配置验证：保存后自动验证配置文件格式和结构

【配置文件位置】
- 开发模式：优先使用当前目录的 config.jsonc，其次用户配置目录
- uvx 模式：仅使用用户配置目录的全局配置
- Linux: ~/.config/ai-intervention-agent/config.jsonc
- macOS: ~/Library/Application Support/ai-intervention-agent/config.jsonc
- Windows: %APPDATA%/ai-intervention-agent/config.jsonc

【使用方式】
通过模块级全局实例 config_manager 访问配置，或使用 get_config() 函数获取实例。

【配置段说明】
- notification: 通知系统配置（Web、声音、Bark 推送）
- web_ui: Web UI 服务器配置（地址、端口、重试策略）
- network_security: 网络安全配置（访问控制、IP 白名单/黑名单）
- feedback: 反馈系统配置（超时设置）

【线程安全保证】
- 使用读写锁（ReadWriteLock）实现读多写少的高效并发
- 所有公共方法均为线程安全
- 支持多线程并发读取配置，写入时独占访问
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
    """读写锁实现

    【设计目的】
    实现读写锁模式，允许多个读者并发访问，但写者需要独占访问。
    适用于读多写少的场景，提升并发性能。

    【锁模式】
    - 读模式：多个线程可同时持有读锁，互不阻塞
    - 写模式：只有一个线程可持有写锁，且必须等待所有读锁释放

    【实现原理】
    - 使用 Condition 变量协调读写线程
    - 使用计数器 _readers 追踪当前读者数量
    - 写者在进入前等待所有读者退出
    - 最后一个读者退出时通知等待的写者

    【使用场景】
    - ConfigManager 的配置读取和更新
    - 其他读多写少的共享资源访问

    【线程安全】
    - 基于 threading.Condition 和 threading.RLock 实现
    - 保证读写操作的正确同步
    """

    def __init__(self):
        """初始化读写锁

        【内部状态】
        - _read_ready: Condition 变量，用于协调读写线程
        - _readers: 当前持有读锁的线程数量
        """
        self._read_ready = threading.Condition(threading.RLock())
        self._readers = 0

    @contextmanager
    def read_lock(self):
        """获取读锁的上下文管理器

        【功能说明】
        获取读锁以访问共享资源。多个线程可同时持有读锁。

        【使用流程】
        1. 获取 Condition 锁
        2. 增加读者计数
        3. 释放 Condition 锁
        4. 执行用户代码（持有读锁期间）
        5. 重新获取 Condition 锁
        6. 减少读者计数
        7. 如果是最后一个读者，通知等待的写者
        8. 释放 Condition 锁

        【阻塞条件】
        - 仅在写者持有锁时阻塞
        - 读者之间不会相互阻塞

        【典型用法】
        在 ConfigManager.get() 方法中使用

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

        【功能说明】
        获取写锁以独占访问共享资源。写者必须等待所有读者退出。

        【使用流程】
        1. 获取 Condition 锁
        2. 等待所有读者退出（_readers == 0）
        3. 执行用户代码（持有写锁期间，独占访问）
        4. 释放 Condition 锁

        【阻塞条件】
        - 有读者持有读锁时阻塞
        - 其他写者持有写锁时阻塞

        【独占性】
        - 持有写锁期间，任何读者和写者都无法获取锁
        - 保证数据修改的原子性和一致性

        【典型用法】
        在 ConfigManager.set() 和 ConfigManager.update() 方法中使用

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

    【功能说明】
    将带注释的 JSON 字符串解析为 Python 字典对象。

    【支持的注释格式】
    - 单行注释：// 注释内容（到行尾）
    - 多行注释：/* 注释内容 */（可跨行）

    【处理流程】
    1. 逐行扫描输入内容
    2. 识别并移除多行注释块
    3. 识别并移除单行注释（排除字符串内的 //）
    4. 拼接清理后的内容
    5. 使用标准 json.loads 解析

    【注意事项】
    - 字符串内的 // 和 /* */ 不会被视为注释
    - 处理转义字符以避免误判字符串边界
    - 保留原始 JSON 的换行和缩进（清理后）

    【错误处理】
    - 注释清理过程中的错误会导致解析失败
    - JSON 语法错误会抛出 json.JSONDecodeError

    【性能考虑】
    - 逐字符扫描，适用于中小型配置文件
    - 对于大型文件可能性能不佳

    Args:
        content: JSONC 格式的字符串内容

    Returns:
        Dict[str, Any]: 解析后的字典对象

    Raises:
        json.JSONDecodeError: JSON 解析失败时抛出
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

    【功能说明】
    判断应用是通过 uvx 工具运行还是开发模式运行，影响配置文件位置选择。

    【检测特征】
    1. 执行路径检查：sys.executable 是否包含 "uvx" 或 ".local/share/uvx"
    2. 环境变量检查：是否存在 UVX_PROJECT 环境变量
    3. 项目文件检查：当前目录及父目录是否包含开发文件
       - pyproject.toml：Python 项目配置
       - setup.py / setup.cfg：传统 Python 打包文件
       - .git：Git 版本控制目录

    【判断逻辑】
    - 如果检测到 uvx 特征 → 返回 True（uvx 模式）
    - 如果检测到开发文件 → 返回 False（开发模式）
    - 都未检测到 → 返回 True（默认为 uvx 模式）

    【模式影响】
    - uvx 模式：仅使用用户配置目录的全局配置
    - 开发模式：优先使用当前目录的配置文件

    【设计考虑】
    - uvx 模式通常用于生产环境或用户安装的应用
    - 开发模式允许开发者在项目目录调试配置
    - 避免 uvx 模式下意外使用临时目录的配置

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

    【功能说明】
    根据运行模式智能查找配置文件位置，支持开发模式和 uvx 生产模式。

    【查找策略】
    **uvx 模式**（生产环境）：
    - 仅使用用户配置目录的全局配置
    - 避免使用临时目录中的配置文件
    - 确保配置持久化且全局一致

    **开发模式**（本地开发）：
    1. 优先级1：当前工作目录的 config.jsonc
    2. 优先级2：当前工作目录的 config.json（向后兼容）
    3. 优先级3：用户配置目录的 config.jsonc
    4. 优先级4：用户配置目录的 config.json（向后兼容）
    5. 默认：返回用户配置目录路径（用于创建新配置）

    【跨平台配置目录】
    自动适配不同操作系统的标准配置目录：
    - **Linux**: ~/.config/ai-intervention-agent/
    - **macOS**: ~/Library/Application Support/ai-intervention-agent/
    - **Windows**: %APPDATA%/ai-intervention-agent/

    【配置目录获取】
    - 优先使用 platformdirs 库（如果可用）
    - 回退到 _get_user_config_dir_fallback 手动判断

    【向后兼容】
    - 支持 .jsonc 和 .json 两种扩展名
    - 优先使用 .jsonc 格式（支持注释）
    - 自动查找并使用旧的 .json 配置文件

    【文件不存在处理】
    - 返回用户配置目录的目标路径
    - 由 ConfigManager 负责创建默认配置文件
    - 记录日志说明将创建新配置

    【异常处理】
    - 配置目录获取失败时回退到当前目录
    - 记录警告日志但不抛出异常
    - 确保应用能在各种环境下启动

    Args:
        config_filename: 配置文件名，默认为 "config.jsonc"

    Returns:
        Path: 配置文件的路径对象（可能尚不存在）
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
    """获取用户配置目录的回退实现

    【功能说明】
    在 platformdirs 库不可用时，手动判断操作系统并返回标准配置目录路径。

    【支持的平台】
    - **Windows**: %APPDATA%/ai-intervention-agent 或 ~/AppData/Roaming/ai-intervention-agent
    - **macOS (darwin)**: ~/Library/Application Support/ai-intervention-agent
    - **Linux 和其他 Unix**: $XDG_CONFIG_HOME/ai-intervention-agent 或 ~/.config/ai-intervention-agent

    【平台检测】
    使用 platform.system() 识别操作系统：
    - "windows" → Windows 路径
    - "darwin" → macOS 路径
    - 其他 → Linux/Unix 路径

    【环境变量支持】
    - Windows: 优先使用 APPDATA 环境变量
    - Linux: 优先使用 XDG_CONFIG_HOME 环境变量（符合 XDG 规范）

    【回退路径】
    环境变量不存在时使用硬编码的标准路径：
    - Windows: ~/AppData/Roaming/ai-intervention-agent
    - macOS: ~/Library/Application Support/ai-intervention-agent
    - Linux: ~/.config/ai-intervention-agent

    【设计考虑】
    - 遵循各平台的标准配置目录规范
    - 确保在没有第三方库时也能正常工作
    - 使用 Path.home() 获取用户主目录，跨平台兼容

    Returns:
        Path: 用户配置目录路径（不包含配置文件名）
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

    【设计模式】
    单例模式（通过模块级全局实例 config_manager 实现）

    【核心职责】
    1. 配置文件加载和解析（JSONC 和 JSON 格式）
    2. 配置值的读取和更新（支持嵌套键）
    3. 配置文件的持久化（保留注释和格式）
    4. 线程安全的并发访问控制
    5. 性能优化（延迟保存、读写锁、缓存）

    【主要特性】
    - **JSONC 支持**：保留用户在配置文件中的注释和格式
    - **跨平台**：自动适配不同操作系统的配置目录
    - **热重载**：支持运行时重新加载配置文件
    - **网络安全配置独立管理**：network_security 段不加载到内存，特殊方法读取（带缓存）
    - **线程安全**：使用读写锁实现高性能并发访问
    - **延迟保存**：批量配置更新时减少磁盘 I/O
    - **配置验证**：保存后自动验证文件格式和结构

    【配置段管理】
    - notification: 加载到内存，正常访问
    - web_ui: 加载到内存，正常访问
    - feedback: 加载到内存，正常访问
    - network_security: **不加载到内存**，使用 get_network_security_config() 特殊读取（带 30 秒缓存）

    【线程安全】
    - 读操作使用读锁，允许多线程并发读取
    - 写操作使用写锁，独占访问
    - 延迟保存使用额外的 RLock 保护定时器

    【性能优化】
    - 延迟保存机制：批量更新后统一保存，减少磁盘 I/O
    - 读写锁：读多写少场景下提升并发性能
    - 值变化检测：跳过未变化的配置更新
    - **network_security 缓存**：30 秒 TTL，减少文件读取

    【使用方式】
    通过模块级全局实例 config_manager 访问，避免手动创建实例。
    """

    def __init__(self, config_file: str = "config.jsonc"):
        """初始化配置管理器

        【初始化流程】
        1. 查找配置文件路径（根据运行模式）
        2. 初始化内部状态（配置字典、锁、定时器）
        3. 加载配置文件内容
        4. 合并默认配置（确保新增配置项存在）

        【内部状态】
        - config_file: 配置文件路径（Path 对象）
        - _config: 内存中的配置字典（不含 network_security）
        - _rw_lock: 读写锁，用于配置读写
        - _lock: 可重入锁，用于延迟保存定时器
        - _original_content: 原始文件内容（用于保留注释）
        - _last_access_time: 最后访问时间（用于统计）
        - _pending_changes: 待写入的配置变更字典
        - _save_timer: 延迟保存定时器
        - _save_delay: 延迟保存时间（默认3秒）
        - _last_save_time: 上次保存时间

        【配置文件查找】
        使用 find_config_file() 根据运行模式查找配置文件位置

        【默认配置】
        如果配置文件不存在，自动创建带注释的默认配置文件

        Args:
            config_file: 配置文件名，默认为 "config.jsonc"
        """
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
        """获取默认配置

        【功能说明】
        返回应用程序的默认配置字典，用于初始化和合并配置。

        【配置段说明】
        - **notification**: 通知系统配置
          * enabled: 通知总开关
          * web_enabled: Web 浏览器通知
          * sound_enabled, sound_volume: 声音通知
          * bark_enabled, bark_url, bark_device_key: Bark 推送服务
          * mobile_optimized, mobile_vibrate: 移动设备优化

        - **web_ui**: Web UI 服务器配置
          * host: 绑定地址（默认 127.0.0.1，仅本地访问）
          * port: 监听端口（默认 8080）
          * debug: 调试模式
          * max_retries, retry_delay: 重试策略

        - **network_security**: 网络安全配置（特殊处理，不加载到内存）
          * bind_interface: 绑定网络接口
          * allowed_networks: IP 白名单（CIDR 格式）
          * blocked_ips: IP 黑名单
          * enable_access_control: 是否启用访问控制

        - **feedback**: 反馈系统配置
          * timeout: 反馈超时时间（秒）

        【安全性考虑】
        - host 默认为 127.0.0.1（仅本地访问），提升安全性
        - allowed_networks 包含常见私有网络段，防止公网直接访问
        - enable_access_control 默认启用，保护 Web UI

        【使用场景】
        - 配置文件不存在时创建默认配置
        - 合并配置时补充缺失的配置项
        - 获取配置项的默认值

        Returns:
            Dict[str, Any]: 默认配置字典，包含所有配置段
        """
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
        """加载配置文件

        【功能说明】
        从磁盘加载配置文件并解析到内存中的 _config 字典。

        【加载流程】
        1. 检查配置文件是否存在
        2. 如果存在：
           - 读取文件内容
           - 保存原始内容（用于保留注释）
           - 根据扩展名选择解析器（JSONC 或 JSON）
           - 排除 network_security 配置段（不加载到内存）
           - 记录成功日志
        3. 如果不存在：
           - 使用默认配置
           - 排除 network_security 配置段
           - 调用 _create_default_config_file 创建文件
           - 记录创建日志
        4. 合并默认配置（确保所有配置项存在）

        【network_security 特殊处理】
        - **设计原因**：网络安全配置非常敏感，独立管理更安全
        - **实现方式**：加载时完全排除该配置段
        - **访问方式**：通过 get_network_security_config() 特殊方法直接读取文件
        - **好处**：防止意外修改、减少内存占用、提高安全性

        【文件格式识别】
        - .jsonc 后缀：使用 parse_jsonc 解析（支持注释）
        - .json 后缀：使用 json.loads 解析（标准 JSON）

        【合并策略】
        - 保持用户配置的优先级
        - 仅添加缺失的默认配置项
        - 递归合并嵌套字典
        - 确保 network_security 不被合并

        【异常处理】
        - 文件读取失败：记录错误日志，使用默认配置
        - 解析失败：记录错误日志，使用默认配置
        - 不抛出异常，确保应用能启动

        【线程安全】
        - 使用 _lock 保护整个加载过程
        - 确保配置加载的原子性
        """
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
        """合并配置，确保所有默认键都存在，但保持现有值不变

        【功能说明】
        将默认配置与当前配置合并，补充缺失的配置项，但保持用户配置优先。

        【合并原则】
        1. 用户配置优先：现有配置项的值不会被默认值覆盖
        2. 补充缺失项：仅添加默认配置中存在但当前配置中缺失的键
        3. 递归合并：对嵌套字典递归应用相同的合并逻辑
        4. 排除特殊配置：确保 network_security 不被合并

        【处理流程】
        1. 以当前配置为基础创建结果字典
        2. 遍历默认配置的所有键
        3. 跳过 network_security 配置段（特殊处理）
        4. 对于缺失的键，直接使用默认值
        5. 对于已存在的嵌套字典，递归合并
        6. 最终移除结果中的 network_security（双重保险）

        【使用场景】
        - 应用启动时合并配置文件和默认配置
        - 应用版本更新后添加新的配置项
        - 确保所有代码依赖的配置项都存在

        【示例逻辑】
        假设：
        - default = {"a": 1, "b": {"b1": 2, "b2": 3}}
        - current = {"a": 100, "b": {"b1": 200}}
        结果：
        - result = {"a": 100, "b": {"b1": 200, "b2": 3}}
        说明：a 和 b.b1 保持用户值，b.b2 从默认配置补充

        【network_security 处理】
        - 多次检查确保该配置段不被合并
        - 记录调试日志标记排除操作

        Args:
            default: 默认配置字典
            current: 当前配置字典

        Returns:
            Dict[str, Any]: 合并后的配置字典，包含所有默认键但保持用户值
        """
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
        """从当前行中提取配置值

        【功能说明】
        从配置文件的特定行中提取指定键的当前值。

        【处理类型】
        - 数组值：调用 _find_array_range_simple 查找数组范围并提取
        - 简单值：使用正则表达式直接提取

        【使用场景】
        - _save_jsonc_with_comments 中检查值是否变化
        - 避免不必要的配置更新

        Args:
            lines: 文件内容行列表
            line_index: 目标行索引
            key: 配置键名

        Returns:
            Any: 提取的配置值，提取失败返回 None
        """
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
        """简化版的数组范围查找

        【功能说明】
        查找多行数组的开始和结束行号。

        【查找逻辑】
        - 确认开始行匹配数组开始模式
        - 逐字符扫描，追踪括号层级
        - 处理字符串和转义字符
        - 找到匹配的右括号时返回范围

        【使用场景】
        - _extract_current_value 中提取数组值
        - 简化版实现，用于值比较

        Args:
            lines: 文件内容行列表
            start_line: 数组开始行索引
            key: 数组键名

        Returns:
            tuple: (开始行, 结束行)，如果不是数组返回 (start_line, start_line)
        """
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
        """找到 network_security 配置段的行范围

        【功能说明】
        扫描文件内容，查找 network_security 配置段的起止行号。

        【查找逻辑】
        - 查找包含 "network_security" 的行（排除注释）
        - 追踪大括号层级，找到匹配的右大括号
        - 处理字符串和转义字符
        - 返回配置段的行范围

        【使用场景】
        - _save_jsonc_with_comments 中跳过 network_security 段
        - 确保不修改网络安全配置

        Args:
            lines: 文件内容行列表

        Returns:
            tuple: (开始行, 结束行)，未找到返回 (-1, -1)
        """
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
        """保存 JSONC 格式配置，保留原有注释和格式

        【核心功能】
        智能更新 JSONC 配置文件，保留用户的注释、格式和空行。这是配置管理器最复杂的方法之一。

        【设计原则】
        - 保留原始文件的所有注释
        - 保持原有的缩进和格式
        - 仅更新变化的配置项
        - 完全排除 network_security 配置段

        【处理流程】
        1. 排除 network_security 配置（双重保险）
        2. 如果没有原始内容，使用标准 JSON 格式
        3. 按行处理原始文件内容
        4. 定位 network_security 段范围并跳过
        5. 递归处理配置段，更新变化的值
        6. 拼接处理后的行返回

        【嵌套函数】（约4个内部函数）
        - find_array_range: 查找多行数组的行范围
        - update_array_block: 更新数组块，保留格式
        - update_simple_value: 更新简单值，保留注释
        - process_config_section: 递归处理配置段

        【数组处理】
        - 单行数组：直接替换
        - 多行数组：保留格式、缩进和元素注释
        - 元素注释：尝试匹配并保留

        【简单值处理】
        - 精确定位值的起止位置
        - 保留行尾注释和逗号
        - 处理字符串、布尔、数字、null

        【值变化检测】
        - 使用 _extract_current_value 读取当前值
        - 仅当值变化时才更新
        - 减少不必要的文件修改

        【network_security 保护】
        - 多层检查确保不修改该配置段
        - 定位该段的行范围并跳过
        - 记录调试日志标记跳过操作

        【复杂度】
        - 约300行代码
        - 包含4个嵌套函数
        - 处理多种边界情况
        - 是保留JSONC注释的关键实现

        【使用场景】
        - _save_config_immediate 中保存 JSONC 文件
        - 确保用户注释不丢失
        - 保持配置文件可读性

        Args:
            config: 要保存的配置字典

        Returns:
            str: 更新后的 JSONC 内容字符串
        """
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
        """创建带注释的默认配置文件

        【功能说明】
        在配置文件不存在时，创建一个带详细注释的默认配置文件。

        【创建流程】
        1. 确保配置文件目录存在
        2. 尝试使用模板文件（config.jsonc.default）
        3. 如果模板文件存在：
           - 复制模板文件到目标位置
           - 读取模板内容作为原始内容
           - 记录成功日志
        4. 如果模板文件不存在：
           - 使用默认配置字典生成 JSON 文件
           - 排除 network_security 配置段
           - 记录警告日志
        5. 失败时进行回退处理

        【模板文件】
        - 位置：与本模块同目录的 config.jsonc.default
        - 优点：包含详细的配置说明和注释
        - 格式：JSONC（支持注释）

        【回退机制】
        - 模板不存在：使用默认配置生成 JSON
        - 复制失败：使用默认配置生成 JSON
        - 生成失败：抛出异常，阻止应用启动

        【network_security 处理】
        - 从默认配置中排除该配置段
        - 模板文件中应包含 network_security 注释说明
        - 确保不在内存配置中出现

        【目录创建】
        - parents=True：创建所有必需的父目录
        - exist_ok=True：目录已存在时不报错

        【异常处理】
        - 记录错误日志
        - 尝试回退方案
        - 回退也失败时抛出异常

        Raises:
            Exception: 所有创建方法都失败时抛出
        """
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
        """性能优化：调度延迟保存配置文件

        【功能说明】
        调度一个延迟保存任务，在指定时间后保存配置文件。

        【处理流程】
        1. 取消之前的保存定时器（如果存在）
        2. 创建新的 threading.Timer，延迟 _save_delay 秒
        3. 启动定时器
        4. 记录调试日志

        【延迟保存机制】
        - 默认延迟：3秒（_save_delay）
        - 多次调用：每次调用都会取消之前的定时器，重新计时
        - 效果：批量更新后只执行一次保存操作

        【性能优化原理】
        - 避免频繁的磁盘 I/O
        - 批量更新时合并到一次保存
        - 减少配置文件的写入次数

        【使用场景】
        - set() 方法调用后（如果 save=True）
        - update() 方法调用后（如果 save=True）
        - update_section() 方法调用后（如果 save=True）

        【取消机制】
        - force_save() 会取消延迟保存并立即保存
        - 多次调度会取消前一个定时器

        【线程安全】
        - 使用 _lock 保护定时器操作
        - 确保定时器的创建和取消是线程安全的
        """
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
        """性能优化：延迟保存配置文件

        【功能说明】
        由延迟保存定时器触发，应用所有待保存的变更并写入文件。

        【执行流程】
        1. 清空定时器引用
        2. 应用所有 _pending_changes 中的配置变更
        3. 清空 _pending_changes 字典
        4. 调用 _save_config_immediate 立即保存
        5. 更新最后保存时间
        6. 记录调试日志

        【待保存变更】
        - _pending_changes 字典存储所有待保存的配置项
        - 键为配置路径，值为新值
        - 通过 _set_config_value 应用到 _config

        【触发时机】
        - 由 _schedule_save 创建的定时器触发
        - 默认延迟3秒后执行
        - 多次更新会合并到一次保存

        【异常处理】
        - 捕获所有异常并记录错误日志
        - 不向上传播异常，避免影响其他操作
        - 保存失败不影响内存中的配置状态

        【线程安全】
        - 使用 _lock 保护整个保存过程
        - 确保应用变更和保存操作的原子性

        【性能考虑】
        - 批量应用变更，减少锁的持有时间
        - 一次性写入文件，减少磁盘 I/O
        """
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
        """设置配置值（内部方法，不触发保存）

        【功能说明】
        直接更新配置字典中的值，不触发保存操作。

        【处理流程】
        1. 将键按 "." 分割成路径列表
        2. 从 _config 字典开始逐层导航到目标位置
        3. 对于不存在的中间字典，自动创建空字典
        4. 设置最终键的值

        【自动路径创建】
        如果键路径 "a.b.c" 中 "a" 或 "b" 不存在，会自动创建：
        - _config["a"] = {}
        - _config["a"]["b"] = {}
        - _config["a"]["b"]["c"] = value

        【使用场景】
        - set() 方法内部调用，更新单个配置项
        - update() 方法内部调用，批量更新配置
        - _delayed_save() 应用待保存的变更

        【与 set() 的区别】
        - _set_config_value：仅更新内存，不触发保存，不加锁，不检查值变化
        - set()：更新内存 + 触发保存，加锁保护，检查值变化

        【线程安全】
        - 不加锁，由调用方保证线程安全
        - 通常在已持有写锁的上下文中调用

        Args:
            key: 配置键，支持点号分隔的嵌套路径
            value: 要设置的新值
        """
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
        """保存配置文件（使用延迟保存优化）

        【功能说明】
        触发配置保存，使用延迟保存机制优化性能。

        【实现方式】
        直接调用 _schedule_save() 调度延迟保存任务。

        【延迟保存】
        - 不立即保存，而是调度延迟任务
        - 默认延迟3秒后执行
        - 多次调用会合并到一次保存

        【使用场景】
        - set() 方法内部调用（save=True 时）
        - update() 方法内部调用（save=True 时）
        - update_section() 方法内部调用（save=True 时）

        【性能优势】
        - 批量更新时减少磁盘 I/O
        - 频繁配置更改时避免重复保存
        - 提升配置更新的响应速度

        【与 force_save() 的区别】
        - _save_config：延迟保存，性能优先
        - force_save：立即保存，可靠性优先

        【注意事项】
        - 如果应用立即退出，可能丢失未保存的变更
        - 关键操作后应使用 force_save() 确保持久化
        """
        self._schedule_save()

    def _save_config_immediate(self):
        """立即保存配置文件（原始保存逻辑）

        【功能说明】
        立即将内存中的配置写入磁盘文件，绕过延迟保存机制。

        【保存流程】
        1. 确保配置文件目录存在
        2. 打开配置文件进行写入
        3. 根据文件格式选择保存方式：
           - JSONC 文件且有原始内容：调用 _save_jsonc_with_comments 保留注释
           - 其他情况：使用标准 JSON 格式保存
        4. 更新 _original_content（用于下次保存）
        5. 记录调试日志
        6. 调用 _validate_saved_config 验证保存的文件

        【JSONC 格式处理】
        - 文件扩展名为 .jsonc 且有原始内容时，尝试保留注释和格式
        - 使用 _save_jsonc_with_comments 方法智能更新配置
        - 保留用户在配置文件中的注释和格式

        【JSON 格式处理】
        - 使用 json.dumps 生成标准 JSON 格式
        - indent=2：美化输出，缩进2个空格
        - ensure_ascii=False：支持中文等非ASCII字符

        【目录创建】
        - parents=True：创建所有必需的父目录
        - exist_ok=True：目录已存在时不报错

        【文件验证】
        - 保存后自动验证文件格式和结构
        - 检测配置损坏和格式错误
        - 验证失败会抛出异常

        【异常处理】
        - 捕获所有异常并记录错误日志
        - 向上传播异常，由调用方决定如何处理
        - 保存失败会导致配置不一致，需要特别注意

        【使用场景】
        - force_save() 立即保存
        - _delayed_save() 延迟保存执行
        - 不应直接调用，使用 force_save() 或 _save_config()

        Raises:
            Exception: 文件写入失败、验证失败时抛出
        """
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
        """验证保存的配置文件是否有效

        【功能说明】
        保存配置文件后，验证文件格式和结构是否正确。

        【验证流程】
        1. 读取配置文件内容
        2. 根据文件扩展名选择解析器
        3. 尝试解析配置文件
        4. 调用 _validate_config_structure 验证结构
        5. 记录验证通过日志

        【验证内容】
        - JSON 语法正确性
        - 配置结构完整性
        - 数组定义无重复
        - network_security 配置格式

        【异常处理】
        - 解析失败：记录错误日志并抛出异常
        - 结构错误：记录错误日志并抛出异常
        - 验证失败会阻止配置保存

        【使用场景】
        - _save_config_immediate 保存后自动调用
        - 确保保存的文件可被正确读取
        - 及早发现配置文件损坏

        Raises:
            Exception: 配置文件解析失败或结构验证失败时抛出
        """
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
        """验证配置文件结构，检查是否存在格式损坏

        【功能说明】
        深度验证配置文件的结构完整性，检测常见的格式损坏问题。

        【验证项目】
        1. 数组定义重复检查：
           - 扫描文件内容查找数组定义行
           - 检测 allowed_networks 等数组是否重复定义
           - 重复定义是格式损坏的典型标志

        2. network_security 配置验证（如果存在）：
           - allowed_networks 必须是数组类型
           - 数组元素必须都是字符串
           - 验证 IP 地址/网络段格式（CIDR）

        【格式损坏检测】
        - 重复的数组定义
        - 无效的数据类型
        - 非字符串的网络地址

        【使用场景】
        - _validate_saved_config 中调用
        - 保存后验证文件结构
        - 防止配置文件被破坏

        【异常处理】
        - 检测到格式损坏时抛出 ValueError
        - 包含详细的错误信息（行号、字段名）
        - 记录调试日志

        Args:
            parsed_config: 已解析的配置字典
            content: 原始文件内容字符串

        Raises:
            ValueError: 检测到配置格式损坏时抛出
        """
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
        """获取配置值，支持点号分隔的嵌套键 - 使用读锁提高并发性能

        【功能说明】
        从配置字典中读取指定键的值，支持点号分隔的嵌套路径。

        【键路径格式】
        - 简单键：直接访问顶层配置，如 "notification"
        - 嵌套键：使用点号分隔，如 "notification.sound_volume"
        - 深度嵌套：支持任意深度，如 "web_ui.retry.max_attempts"

        【查找过程】
        1. 将键按 "." 分割成路径列表
        2. 从 _config 字典开始逐层导航
        3. 遇到 KeyError 或 TypeError 时返回默认值

        【线程安全】
        - 使用读锁（ReadWriteLock.read_lock）
        - 允许多个线程并发读取
        - 读操作不阻塞其他读操作

        【性能优化】
        - 更新最后访问时间（用于统计）
        - 读锁机制提升并发性能

        【特殊配置访问】
        - **network_security 配置**：不在 _config 中，返回 None 或默认值
        - 应使用 get_network_security_config() 特殊方法访问

        【错误处理】
        - 键不存在：返回 default 参数值
        - 中间路径不是字典：返回 default 参数值
        - 不抛出异常，确保调用安全

        Args:
            key: 配置键，支持点号分隔的嵌套路径
            default: 键不存在时的默认返回值，默认为 None

        Returns:
            Any: 配置值，如果键不存在则返回 default
        """
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
        """设置配置值，支持点号分隔的嵌套键 - 使用写锁确保原子操作

        【功能说明】
        更新配置字典中指定键的值，支持点号分隔的嵌套路径。

        【键路径格式】
        - 简单键：更新顶层配置，如 "enabled"
        - 嵌套键：使用点号分隔，如 "notification.sound_volume"
        - 自动创建中间路径：如果中间字典不存在，自动创建

        【更新流程】
        1. 获取写锁（独占访问）
        2. 更新最后访问时间
        3. 检查当前值是否与新值相同（性能优化）
        4. 如果值未变化，记录日志并跳过
        5. 如果值变化：
           - 立即更新内存中的 _config
           - 如果 save=True，将变更加入待保存队列并调度延迟保存
           - 如果 save=False，仅更新内存
        6. 记录调试日志

        【性能优化】
        - 值变化检测：跳过未变化的更新，减少不必要的保存
        - 延迟保存机制：批量更新时统一保存，减少磁盘 I/O
        - 读写锁：写操作独占，但不影响其他读操作

        【保存机制】
        - save=True（默认）：更新后调度延迟保存（3秒后）
        - save=False：仅更新内存，不保存到文件
        - 延迟保存：多次更新会合并到一次保存操作

        【线程安全】
        - 使用写锁（ReadWriteLock.write_lock）
        - 独占访问，阻塞其他读写操作
        - 确保配置更新的原子性

        【自动路径创建】
        - 如果中间字典不存在，自动创建空字典
        - 使用 _set_config_value 内部方法处理路径导航

        【特殊配置更新】
        - **network_security 配置**：不在 _config 中，更新会被忽略
        - 应通过修改配置文件并调用 reload() 更新

        Args:
            key: 配置键，支持点号分隔的嵌套路径
            value: 要设置的新值，可以是任意类型
            save: 是否保存到文件，默认为 True
        """
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
        """批量更新配置 - 使用写锁确保原子操作

        【功能说明】
        一次性更新多个配置项，比多次调用 set() 更高效。

        【更新流程】
        1. 获取写锁（独占访问）
        2. 更新最后访问时间
        3. 过滤出真正有变化的配置项（性能优化）
        4. 如果没有变化，记录日志并跳过
        5. 如果有变化：
           - 立即更新内存中的 _config
           - 如果 save=True，将所有变更加入待保存队列并调度延迟保存
           - 如果 save=False，仅更新内存
        6. 记录每个配置项的更新日志
        7. 记录批量更新完成日志

        【性能优化】
        - 值变化检测：仅处理真正有变化的配置项
        - 批量缓冲：所有变更合并到一次保存操作
        - 单次调度：无论更新多少配置项，只调度一次延迟保存
        - 减少磁盘 I/O：相比多次 set() 大幅减少磁盘操作

        【保存机制】
        - save=True（默认）：批量更新后调度延迟保存（3秒后）
        - save=False：仅更新内存，不保存到文件
        - 延迟保存：多次批量更新也会合并到一次保存操作

        【线程安全】
        - 使用写锁（ReadWriteLock.write_lock）
        - 独占访问，阻塞其他读写操作
        - 确保批量更新的原子性

        【使用场景】
        - 初始化时批量设置多个配置项
        - 应用设置页面保存多个配置更改
        - 配置迁移或导入

        【与 set() 的对比】
        - set()：单个配置项更新
        - update()：多个配置项批量更新，性能更优

        Args:
            updates: 配置更新字典，键为配置路径，值为新值
            save: 是否保存到文件，默认为 True
        """
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
        """强制立即保存配置文件（用于关键操作）

        【功能说明】
        立即保存配置文件，绕过延迟保存机制。

        【使用场景】
        - 应用退出前保存配置
        - 关键配置更改需要立即持久化
        - 测试环境中验证配置保存
        - 避免延迟保存导致的配置丢失

        【执行流程】
        1. 取消延迟保存定时器（如果存在）
        2. 应用所有待写入的配置变更
        3. 调用 _save_config_immediate 立即保存
        4. 更新最后保存时间
        5. 记录调试日志

        【与延迟保存的对比】
        - 延迟保存：批量更新后3秒保存，减少磁盘 I/O
        - 强制保存：立即保存，确保配置持久化

        【线程安全】
        - 使用 _lock 保护整个保存过程
        - 确保保存操作的原子性

        【性能考虑】
        - 频繁调用会导致磁盘 I/O 增加
        - 应仅在必要时使用
        - 一般情况下依赖延迟保存机制即可
        """
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
        """获取配置段（返回副本，防止外部修改影响内部状态）

        【功能说明】
        获取指定名称的整个配置段字典的深拷贝。

        【配置段】
        - notification: 通知系统配置
        - web_ui: Web UI 服务器配置
        - feedback: 反馈系统配置
        - network_security: 网络安全配置（特殊处理）

        【特殊处理】
        - **network_security 配置段**：不在内存中，通过 get_network_security_config() 从文件读取
        - 其他配置段：通过 get() 方法从内存读取

        【性能优化】
        - 使用 section 缓存层减少深拷贝开销
        - 缓存有效期默认 10 秒，可通过 use_cache=False 强制刷新

        【返回值】
        - 配置段存在：返回该配置段字典的**深拷贝**
        - 配置段不存在：返回空字典 {}

        【安全性】
        - 【修复】返回深拷贝，外部修改不会影响内部配置状态
        - 需要修改配置请使用 update_section() 或 set() 方法

        【使用场景】
        - 获取某个功能模块的所有配置
        - 配置页面展示某个配置段
        - 批量读取配置项

        Args:
            section: 配置段名称（顶层配置键）
            use_cache: 是否使用缓存（默认 True）

        Returns:
            Dict[str, Any]: 配置段字典的深拷贝，如果不存在则返回空字典
        """
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
        """更新配置段

        【功能说明】
        批量更新指定配置段内的多个配置项。

        【更新流程】
        1. 获取当前配置段的所有配置
        2. 检查是否有配置项真的发生变化
        3. 如果没有变化，记录日志并跳过
        4. 如果有变化：
           - 应用更新到配置段
           - 更新内存中的 _config
           - 如果 save=True，调度延迟保存
        5. 记录更新日志

        【值变化检测】
        - 逐项比较新旧值
        - 仅当至少有一项变化时才执行更新
        - 记录每项变化的调试日志

        【保存机制】
        - save=True（默认）：更新后调度延迟保存
        - save=False：仅更新内存，不保存到文件

        【线程安全】
        - 使用 _lock 保护整个更新过程
        - 确保配置段更新的原子性

        【使用场景】
        - 更新某个功能模块的多个配置
        - 从 API 接收配置段更新
        - 配置导入或迁移

        【与 update() 的对比】
        - update()：支持跨配置段的更新，键需要完整路径
        - update_section()：限定在单个配置段内，键无需前缀

        Args:
            section: 配置段名称（顶层配置键）
            updates: 配置更新字典，键为配置段内的键名，值为新值
            save: 是否保存到文件，默认为 True
        """
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
        """重新加载配置文件

        【功能说明】
        从磁盘重新加载配置文件，覆盖内存中的配置。

        【使用场景】
        - 配置文件被外部修改后需要重新加载
        - 开发调试时频繁修改配置
        - 配置热更新，无需重启应用
        - 恢复到文件中的配置（放弃内存中的未保存更改）

        【注意事项】
        - 内存中未保存的配置更改会丢失
        - 调用前应考虑是否需要 force_save()
        - 重新加载会触发完整的配置文件解析流程

        【执行流程】
        1. 记录信息日志
        2. 调用 _load_config() 重新加载
        3. 重新解析配置文件
        4. 合并默认配置
        5. 更新 _original_content

        【线程安全】
        - _load_config() 内部使用锁保护
        - 重新加载期间其他操作会被阻塞
        """
        logger.info("重新加载配置文件")
        self._load_config()
        # 【缓存优化】重新加载后失效所有缓存
        self.invalidate_all_caches()

    # ========================================================================
    # 缓存管理方法
    # ========================================================================

    def invalidate_section_cache(self, section: str):
        """失效指定 section 的缓存

        【功能说明】
        使指定配置段的缓存失效，下次访问时会重新从内存中读取。

        Args:
            section: 配置段名称
        """
        if section in self._section_cache:
            del self._section_cache[section]
            self._section_cache_time.pop(section, None)
            self._cache_stats["invalidations"] += 1
            logger.debug(f"已失效 section 缓存: {section}")

    def invalidate_all_caches(self):
        """失效所有缓存

        【功能说明】
        清空所有配置缓存，包括 section 缓存和 network_security 缓存。
        """
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
        """获取缓存统计信息

        【功能说明】
        返回缓存的命中率、未命中率等统计信息。

        Returns:
            Dict: {
                "hits": 缓存命中次数,
                "misses": 缓存未命中次数,
                "invalidations": 缓存失效次数,
                "hit_rate": 命中率 (0.0-1.0),
                "section_cache_size": 当前 section 缓存数量,
                "network_security_cached": network_security 是否已缓存
            }
        """
        total = self._cache_stats["hits"] + self._cache_stats["misses"]
        hit_rate = self._cache_stats["hits"] / total if total > 0 else 0.0

        return {
            **self._cache_stats,
            "hit_rate": round(hit_rate, 4),
            "section_cache_size": len(self._section_cache),
            "network_security_cached": self._network_security_cache is not None,
        }

    def reset_cache_stats(self):
        """重置缓存统计

        【功能说明】
        将缓存统计信息归零，用于新一轮统计。
        """
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
        """设置缓存有效期

        【功能说明】
        动态调整缓存有效期（TTL）。

        Args:
            section_ttl: section 缓存有效期（秒），None 表示不修改
            network_security_ttl: network_security 缓存有效期（秒），None 表示不修改
        """
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
        """获取所有配置

        【功能说明】
        返回内存中所有配置的副本。

        【返回值】
        - 配置字典的浅拷贝
        - **不包含** network_security 配置段
        - 修改返回的字典不影响内存中的配置

        【使用场景】
        - 配置导出或备份
        - 配置页面展示所有配置
        - 配置比较或差异分析
        - API 返回完整配置

        【性能考虑】
        - 返回副本，避免外部直接修改内部状态
        - 浅拷贝，嵌套字典仍是引用
        - 对于大型配置可能有性能开销

        【线程安全】
        - 使用 _lock 保护拷贝操作
        - 确保返回一致的配置快照

        【network_security 配置】
        - 使用 get_network_security_config() 单独获取
        - 不会包含在返回值中

        Returns:
            Dict[str, Any]: 所有配置的副本（不含 network_security）
        """
        with self._lock:
            return self._config.copy()

    def get_network_security_config(self) -> Dict[str, Any]:
        """特殊方法：从文件读取 network_security 配置（带缓存优化）

        【设计原因】
        network_security 配置包含敏感的网络访问控制信息，独立管理更安全：
        - 防止意外修改或泄露
        - 减少内存占用
        - 降低安全风险
        - 明确区分安全配置和业务配置

        【功能说明】
        从配置文件读取 network_security 配置段，带有 30 秒缓存优化。

        【性能优化 - 缓存机制】
        - 缓存有效期：30 秒（TTL）
        - 缓存命中：直接返回缓存数据，避免文件 I/O
        - 缓存过期：重新读取文件并更新缓存
        - 线程安全：使用锁保护缓存访问

        【读取流程】
        1. 检查缓存是否有效（30 秒内）
        2. 缓存有效：直接返回缓存数据
        3. 缓存过期/不存在：
           - 检查配置文件是否存在
           - 读取文件内容
           - 根据扩展名选择解析器（JSONC 或 JSON）
           - 提取 network_security 配置段
           - 更新缓存
        4. 发生异常时返回默认配置

        【默认配置】
        - bind_interface: "0.0.0.0"（允许所有接口）
        - allowed_networks: 包含本地和私有网络段
        - blocked_ips: 空列表
        - enable_access_control: True（启用访问控制）

        【使用场景】
        - Web UI 启动时读取网络安全配置
        - 检查客户端 IP 是否允许访问
        - 配置页面展示网络安全设置
        - API 返回网络安全配置

        【性能考虑】
        - 【优化】30 秒缓存减少文件 I/O
        - 缓存过期后自动刷新
        - 支持热重载：修改配置文件后 30 秒内生效

        【错误处理】
        - 文件不存在：返回默认配置
        - 解析失败：记录错误日志，返回默认配置
        - 配置段缺失：返回默认配置
        - 不抛出异常，确保应用能正常启动

        Returns:
            Dict[str, Any]: network_security 配置字典，如果读取失败则返回默认配置
        """
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
        """获取配置值，带类型转换和边界验证

        【功能说明】
        获取配置值并自动进行类型转换和边界验证。
        如果转换失败或值超出边界，返回默认值或调整后的值。

        【支持的类型】
        - int: 整数类型
        - float: 浮点数类型
        - bool: 布尔类型（支持字符串 "true"/"false"）
        - str: 字符串类型

        【边界验证】
        - min_val: 最小值（包含），仅对 int/float 有效
        - max_val: 最大值（包含），仅对 int/float 有效
        - 超出边界的值会被自动调整

        【使用场景】
        - 获取需要类型安全的配置值
        - 避免在使用配置值前手动转换和验证

        Args:
            key: 配置键，支持点号分隔的嵌套路径
            default: 默认值
            value_type: 目标类型（int, float, bool, str）
            min_val: 最小值（可选）
            max_val: 最大值（可选）

        Returns:
            Any: 类型转换和边界验证后的配置值

        Example:
            >>> config.get_typed("web_ui.port", 8080, int, 1, 65535)
            8081
            >>> config.get_typed("notification.enabled", True, bool)
            True
        """
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
        """获取整数配置值

        Args:
            key: 配置键
            default: 默认值
            min_val: 最小值（可选）
            max_val: 最大值（可选）

        Returns:
            int: 整数配置值
        """
        return self.get_typed(key, default, int, min_val, max_val)

    def get_float(
        self,
        key: str,
        default: float = 0.0,
        min_val: Optional[float] = None,
        max_val: Optional[float] = None,
    ) -> float:
        """获取浮点数配置值

        Args:
            key: 配置键
            default: 默认值
            min_val: 最小值（可选）
            max_val: 最大值（可选）

        Returns:
            float: 浮点数配置值
        """
        return self.get_typed(key, default, float, min_val, max_val)

    def get_bool(self, key: str, default: bool = False) -> bool:
        """获取布尔配置值

        Args:
            key: 配置键
            default: 默认值

        Returns:
            bool: 布尔配置值
        """
        return self.get_typed(key, default, bool)

    def get_str(
        self,
        key: str,
        default: str = "",
        max_length: Optional[int] = None,
    ) -> str:
        """获取字符串配置值

        Args:
            key: 配置键
            default: 默认值
            max_length: 最大长度（可选，超出会截断）

        Returns:
            str: 字符串配置值
        """
        from config_utils import truncate_string

        value = self.get_typed(key, default, str)
        if max_length is not None:
            return truncate_string(value, max_length, key, default=default)
        return value

    # ========================================================================
    # 文件监听功能
    # ========================================================================

    def _update_file_mtime(self):
        """更新文件修改时间记录"""
        try:
            if self.config_file.exists():
                self._last_file_mtime = self.config_file.stat().st_mtime
        except Exception as e:
            logger.warning(f"获取文件修改时间失败: {e}")

    def start_file_watcher(self, interval: float = 2.0):
        """
        启动配置文件监听

        【功能说明】
        启动一个后台线程，定期检查配置文件是否被修改。
        当检测到文件变化时，自动重新加载配置并触发回调。

        【参数】
        interval : float
            检查间隔时间（秒），默认 2.0 秒

        【使用场景】
        - 开发调试时希望配置实时生效
        - 需要支持外部工具修改配置文件
        - 多进程共享配置文件时

        【注意事项】
        - 已启动的监听器不会重复启动
        - 使用守护线程，主程序退出时自动终止
        - 文件变化检测基于修改时间（mtime）
        """
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
        """
        停止配置文件监听

        【功能说明】
        停止后台文件监听线程。

        【注意事项】
        - 会等待当前监听周期完成后再停止
        - 可以安全地多次调用
        """
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
        """关闭配置管理器并清理后台资源

        目的：
        - 避免后台线程/定时器在测试或程序退出时阻塞进程
        - 为单测与脚本提供显式的资源释放入口

        当前清理项：
        - 文件监听线程（start_file_watcher）
        - 延迟保存定时器（_save_timer）

        注意：
        - 该方法是幂等的，可安全多次调用
        """
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
        """
        文件监听循环

        【内部方法】
        后台线程的主循环，定期检查配置文件修改时间。
        """
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
        """
        注册配置变更回调函数

        【功能说明】
        当配置文件被修改并重新加载后，会调用所有注册的回调函数。

        【参数】
        callback : callable
            回调函数，无参数，无返回值
            函数签名: def callback() -> None

        【使用场景】
        - 通知其他模块配置已更新
        - 触发配置相关的重新初始化
        - 更新缓存或状态

        【示例】
        >>> def on_config_change():
        ...     print("配置已更新")
        >>> config.register_config_change_callback(on_config_change)
        """
        if callback not in self._config_change_callbacks:
            self._config_change_callbacks.append(callback)
            cb_name = getattr(callback, "__name__", None) or repr(callback)
            logger.debug(f"已注册配置变更回调: {cb_name}")

    def unregister_config_change_callback(self, callback: Callable[[], None]):
        """
        取消注册配置变更回调函数

        【参数】
        callback : callable
            要取消的回调函数
        """
        if callback in self._config_change_callbacks:
            self._config_change_callbacks.remove(callback)
            cb_name = getattr(callback, "__name__", None) or repr(callback)
            logger.debug(f"已取消配置变更回调: {cb_name}")

    def _trigger_config_change_callbacks(self):
        """
        触发所有配置变更回调

        【内部方法】
        配置文件重新加载后调用，依次执行所有注册的回调函数。
        """
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
        """
        导出当前配置

        【功能说明】
        导出内存中的所有配置为字典格式，可用于备份或迁移。

        【参数】
        include_network_security : bool
            是否包含网络安全配置，默认 False（安全考虑）

        【返回】
        Dict[str, Any]
            包含所有配置的字典

        【使用场景】
        - 配置备份
        - 配置迁移到其他环境
        - 配置对比

        【示例】
        >>> config = get_config()
        >>> backup = config.export_config()
        >>> with open('config_backup.json', 'w') as f:
        ...     json.dump(backup, f, indent=2, ensure_ascii=False)
        """
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
        """
        导入配置

        【功能说明】
        从字典导入配置，支持合并或覆盖模式。

        【参数】
        config_data : Dict[str, Any]
            要导入的配置数据
        merge : bool
            True: 合并模式（保留未指定的配置项）
            False: 覆盖模式（完全替换现有配置）
        save : bool
            是否保存到文件，默认 True

        【返回】
        bool
            导入是否成功

        【注意事项】
        - 导入前会验证配置格式
        - network_security 配置需要单独处理
        - 合并模式下，只更新存在的键

        【示例】
        >>> config = get_config()
        >>> with open('config_backup.json', 'r') as f:
        ...     backup = json.load(f)
        >>> config.import_config(backup['config'], merge=True)
        """
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
        """
        深度合并字典

        【内部方法】
        递归合并 update 到 base 中。

        【参数】
        base : Dict
            基础字典（会被修改）
        update : Dict
            要合并的更新字典
        """
        for key, value in update.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._deep_merge(base[key], value)
            else:
                base[key] = value

    def backup_config(self, backup_path: Optional[str] = None) -> str:
        """
        备份当前配置到文件

        【功能说明】
        将当前配置导出并保存到备份文件。

        【参数】
        backup_path : Optional[str]
            备份文件路径，默认为 config.jsonc.backup

        【返回】
        str
            备份文件的完整路径

        【示例】
        >>> config = get_config()
        >>> backup_file = config.backup_config()
        >>> print(f"配置已备份到: {backup_file}")
        """
        import json

        if backup_path is None:
            backup_path = str(self.config_file) + ".backup"

        export_data = self.export_config(include_network_security=True)

        with open(backup_path, "w", encoding="utf-8") as f:
            json.dump(export_data, f, indent=2, ensure_ascii=False)

        logger.info(f"配置已备份到: {backup_path}")
        return backup_path

    def restore_config(self, backup_path: str) -> bool:
        """
        从备份文件恢复配置

        【功能说明】
        从备份文件导入配置并覆盖当前配置。

        【参数】
        backup_path : str
            备份文件路径

        【返回】
        bool
            恢复是否成功

        【示例】
        >>> config = get_config()
        >>> config.restore_config('config.jsonc.backup')
        """
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
    """获取配置管理器实例

    【功能说明】
    返回全局唯一的配置管理器实例。

    【单例模式】
    - config_manager 在模块加载时创建
    - 整个应用生命周期内只有一个实例
    - 所有模块共享同一个配置状态

    【使用方式】
    推荐使用此函数获取配置管理器，而非直接访问 config_manager 变量。

    【线程安全】
    - config_manager 实例本身线程安全
    - 可从多线程安全调用此函数

    Returns:
        ConfigManager: 全局配置管理器实例
    """
    # 【配置热更新】默认启用文件监听（2 秒轮询，按你的选择 A + C）
    # 目的：外部编辑 config.jsonc 后无需重启即可生效
    try:
        if not config_manager.is_file_watcher_running:
            config_manager.start_file_watcher(interval=2.0)
    except Exception:
        # 配置系统属于基础设施：监听启动失败不应影响主流程
        pass

    return config_manager
