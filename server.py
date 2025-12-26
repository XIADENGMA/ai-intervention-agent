"""
AI Intervention Agent MCP 服务器核心模块

本模块提供基于 Model Context Protocol (MCP) 的交互式反馈服务，允许 AI 助手通过 Web UI
主动向用户请求反馈、确认和输入。

核心功能
--------
1. **MCP 工具集成**: 提供 `interactive_feedback` MCP 工具，支持文本输入、选项选择和图片上传
2. **Web UI 服务管理**: 自动启动、监控和清理 Web 反馈界面服务进程
3. **多任务并发**: 基于 TaskQueue 的任务队列，支持多个反馈任务同时展示和处理
4. **通知系统集成**: 支持 Web、声音、Bark 和系统通知，实时提醒用户响应反馈请求
5. **健壮的超时管理**: 前后端超时时间自动协调，确保后端始终有足够的时间等待前端响应

主要组件
--------
- ServiceManager: 单例模式的服务进程生命周期管理器，处理启动、终止、清理和信号
- WebUIConfig: Web UI 配置数据类，包含主机、端口、超时和重试参数
- interactive_feedback: MCP 工具函数，AI 助手调用此函数请求用户交互反馈
- FeedbackServiceContext: 上下文管理器，自动管理服务的启动和清理生命周期

工作流程
--------
1. AI 助手调用 `interactive_feedback` MCP 工具，传入消息和可选选项
2. 服务器自动生成唯一任务 ID，通过 HTTP API 将任务添加到 Web UI 的任务队列
3. Web UI 在浏览器中展示反馈界面，用户可输入文本、选择选项、上传图片
4. 用户提交反馈后，服务器通过轮询 API 获取反馈结果
5. 反馈数据（文本、选项、图片）被解析为 MCP 标准格式（TextContent + ImageContent）并返回给 AI 助手

配置要求
--------
- 依赖 config_manager 提供的全局配置（web_ui、feedback、network_security 配置段）
- 默认 Web UI 地址: http://127.0.0.1:8081
- 超时规则: 后端超时 = max(前端倒计时 + 60秒, 300秒)，确保后端始终等待足够长
- 支持通知管理器（notification_manager）和通知提供者（notification_providers）

线程安全
--------
- ServiceManager 使用双重检查锁实现线程安全的单例模式
- 所有服务注册、注销和清理操作使用 threading.Lock 保护
- 信号处理器（SIGINT、SIGTERM）确保优雅关闭，避免孤儿进程

典型用法
--------
作为 MCP 服务器运行（通过 stdio 传输）:
    python server.py

在其他 Python 代码中集成反馈服务:
    使用 FeedbackServiceContext 上下文管理器自动管理服务生命周期

注意事项
--------
- 本模块禁用了 Rich Console 和 FastMCP Banner 输出，避免污染 stdio 通信通道
- 所有日志输出重定向到 stderr，确保 stdout 仅用于 MCP 协议通信
- 服务启动时会清理所有残留任务，确保 Web UI 处于"无有效内容"状态
- launch_feedback_ui 函数已废弃，推荐直接使用 interactive_feedback MCP 工具

环境变量
--------
- NO_COLOR="1": 禁用彩色输出
- TERM="dumb": 禁用终端特性
- FASTMCP_NO_BANNER="1": 禁用 FastMCP Banner
- FASTMCP_QUIET="1": 静默模式

依赖模块
--------
- config_manager: 配置管理（JSONC 配置文件加载、热重载、跨平台）
- enhanced_logging: 增强日志（emoji、彩色输出、结构化日志）
- task_queue: 任务队列（多任务并发、状态管理、自动清理）
- notification_manager: 通知管理（Web、声音、Bark、系统通知）
- notification_providers: 通知提供者（具体通知类型的实现插件）
- web_ui: Web 反馈界面（Flask 服务、Markdown 渲染、安全策略）
"""

import asyncio
import atexit
import base64
import io
import os
import random
import signal
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import requests
from fastmcp import FastMCP
from mcp.types import ContentBlock, ImageContent, TextContent
from pydantic import Field
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config_manager import get_config
from config_utils import (
    clamp_dataclass_field,
    get_compat_config,
    truncate_string,
)
from enhanced_logging import EnhancedLogger
from task_queue import TaskQueue

# ===============================
# 【性能优化】全局缓存
# ===============================
# HTTP Session 缓存：避免每次请求都创建新的 session
_http_session_cache: dict = {}
_http_session_lock = threading.Lock()

# 配置缓存：避免频繁读取配置文件
_config_cache: dict = {"config": None, "timestamp": 0, "ttl": 10}  # 10秒 TTL
_config_cache_lock = threading.Lock()

# ===============================
# 【配置热更新】配置变更回调：清空 server.py 内部缓存
# ===============================
# 说明：
# - 配置文件被外部修改并由 ConfigManager 自动 reload 后，会触发回调
# - Web UI 子进程在页面内保存配置时，也会触发 ConfigManager 的回调（同进程内）
# - 这里清空缓存，让后续调用尽快读取到最新配置
_config_callbacks_registered = False
_config_callbacks_lock = threading.Lock()


def _invalidate_runtime_caches_on_config_change() -> None:
    """配置变更回调：清空 server.py 的配置缓存与 HTTP Session 缓存"""
    try:
        with _config_cache_lock:
            _config_cache["config"] = None
            _config_cache["timestamp"] = 0
    except Exception:
        pass

    try:
        with _http_session_lock:
            _http_session_cache.clear()
    except Exception:
        pass


def _ensure_config_change_callbacks_registered() -> None:
    """确保只注册一次配置变更回调（避免重复注册/重复清理缓存）"""
    global _config_callbacks_registered
    if _config_callbacks_registered:
        return
    with _config_callbacks_lock:
        if _config_callbacks_registered:
            return
        try:
            cfg = get_config()
            cfg.register_config_change_callback(
                _invalidate_runtime_caches_on_config_change
            )
        except Exception as e:
            # 回调注册失败不应影响主流程
            logger.debug(f"注册配置变更回调失败（忽略）: {e}")
        _config_callbacks_registered = True


# 禁用 FastMCP banner 和 Rich 输出，避免污染 stdio
os.environ["NO_COLOR"] = "1"
os.environ["TERM"] = "dumb"
os.environ["FASTMCP_NO_BANNER"] = "1"
os.environ["FASTMCP_QUIET"] = "1"

# 全局配置日志输出到 stderr，避免污染 stdio
import logging as _stdlib_logging

_root_logger = _stdlib_logging.getLogger()
_root_logger.setLevel(_stdlib_logging.WARNING)
_root_logger.handlers.clear()

_stderr_handler = _stdlib_logging.StreamHandler(sys.stderr)
_stderr_handler.setLevel(_stdlib_logging.WARNING)
_stderr_formatter = _stdlib_logging.Formatter(
    "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
_stderr_handler.setFormatter(_stderr_formatter)
_root_logger.addHandler(_stderr_handler)
_root_logger.propagate = False

# 禁用 Rich Console 输出
try:
    import rich.console as rich_console_module

    _devnull = io.StringIO()

    class SilentConsole(rich_console_module.Console):
        def __init__(self, *args, **kwargs):
            super().__init__(
                file=_devnull,
                force_terminal=False,
                force_jupyter=False,
                force_interactive=False,
                quiet=True,
                *args,
                **kwargs,
            )

    # 使用 setattr 避免类型检查器将该赋值视为“覆盖/遮蔽”类定义
    setattr(rich_console_module, "Console", SilentConsole)  # noqa: B010
except ImportError:
    pass

mcp = FastMCP("AI Intervention Agent MCP")
logger = EnhancedLogger(__name__)
_global_task_queue = TaskQueue(max_tasks=10)


def get_task_queue() -> TaskQueue:
    """获取全局任务队列实例

    Returns:
        TaskQueue: 全局任务队列实例
    """
    return _global_task_queue


try:
    from notification_manager import NotificationTrigger, notification_manager
    from notification_providers import initialize_notification_system

    NOTIFICATION_AVAILABLE = True
    logger.info("通知系统已导入")
except ImportError as e:
    logger.warning(f"通知系统不可用: {e}")
    NOTIFICATION_AVAILABLE = False


class ServiceManager:
    """
    服务进程生命周期管理器（单例模式）

    功能概述
    --------
    负责管理所有 Web UI 服务进程的完整生命周期，包括注册、监控、终止和资源清理。
    使用单例模式确保全局唯一实例，提供线程安全的进程管理和优雅的退出机制。

    核心职责
    --------
    1. **进程注册**: 跟踪所有启动的服务进程（PID、配置、启动时间）
    2. **进程监控**: 检查进程运行状态，识别僵尸进程或异常退出
    3. **进程终止**: 使用分级策略（优雅关闭 -> 强制终止 -> 资源清理）安全停止进程
    4. **信号处理**: 捕获 SIGINT/SIGTERM 信号，确保进程不会意外成为孤儿进程
    5. **端口管理**: 等待端口释放，避免端口占用冲突
    6. **退出清理**: 通过 atexit 注册清理函数，确保程序退出时所有进程被终止

    单例实现
    --------
    使用双重检查锁（Double-Checked Locking）实现线程安全的单例模式：
    - 第一次检查: 避免不必要的锁竞争（性能优化）
    - 加锁: 确保只有一个线程创建实例
    - 第二次检查: 防止多个线程同时通过第一次检查后创建多个实例

    内部状态
    --------
    - _processes: Dict[str, Dict] - 进程注册表，键为服务名，值为进程信息字典
        {
            "process": subprocess.Popen,  # 进程对象
            "config": WebUIConfig,        # 服务配置
            "start_time": float           # 启动时间戳
        }
    - _cleanup_registered: bool - 标记是否已注册清理函数（避免重复注册）
    - _should_exit: bool - 退出标志，用于通知等待循环提前终止
    - _initialized: bool - 初始化标志，确保 __init__ 只执行一次

    线程安全
    --------
    - 所有修改 _processes 的操作都使用 _lock 保护
    - 单例创建使用双重检查锁，避免竞态条件
    - 信号处理器仅在主线程中设置退出标志

    信号处理
    --------
    - SIGINT（Ctrl+C）: 捕获并触发清理流程
    - SIGTERM（kill 命令）: 捕获并触发清理流程
    - 非主线程接收信号时: 执行清理但不强制退出（避免线程安全问题）

    使用场景
    --------
    - 自动管理 Web UI 服务进程的启动和关闭
    - 确保程序异常退出或被杀死时不会留下孤儿进程
    - 在测试场景中安全地启动和清理多个服务实例

    注意事项
    --------
    - 进程终止超时时间默认 5 秒，可在 terminate_process 中调整
    - 端口释放等待时间默认 10 秒，超时后会记录警告但不会阻塞
    - 清理失败的进程会被强制从注册表移除，避免阻塞后续清理操作
    - 信号处理器注册失败（如非主线程）会被忽略，不影响其他功能
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        """
        创建或返回单例实例（双重检查锁实现）

        返回
        ----
        ServiceManager
            全局唯一的 ServiceManager 实例

        线程安全
        --------
        使用双重检查锁确保多线程环境下只创建一个实例
        """
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """
        初始化服务管理器（仅在首次创建时执行）

        初始化流程
        ----------
        1. 检查是否已初始化（避免重复初始化）
        2. 初始化进程注册表和状态标志
        3. 注册清理函数和信号处理器

        线程安全
        --------
        使用 _lock 确保初始化代码只执行一次，即使多线程同时调用
        """
        if not getattr(self, "_initialized", False):
            with self._lock:
                if not getattr(self, "_initialized", False):
                    self._processes = {}
                    self._cleanup_registered = False
                    self._should_exit = False
                    self._initialized = True
                    self._register_cleanup()

    def _register_cleanup(self):
        """
        注册清理函数和信号处理器

        功能
        ----
        1. 通过 atexit 注册 cleanup_all，确保程序正常退出时清理所有进程
        2. 注册 SIGINT 和 SIGTERM 信号处理器，捕获 Ctrl+C 和 kill 命令
        3. 标记清理机制已注册，避免重复注册

        异常处理
        ----------
        - 信号处理器注册失败（如非主线程）会被忽略并记录调试信息
        - 注册失败不影响其他功能，但可能导致信号无法被正确捕获

        注意事项
        --------
        - 只能在主线程中成功注册信号处理器
        - atexit 注册会在所有退出场景中生效（包括异常退出）
        """
        if not self._cleanup_registered:
            atexit.register(self.cleanup_all)
            try:
                if hasattr(signal, "SIGINT"):
                    signal.signal(signal.SIGINT, self._signal_handler)
                if hasattr(signal, "SIGTERM"):
                    signal.signal(signal.SIGTERM, self._signal_handler)
                logger.debug("服务管理器信号处理器已注册")
            except ValueError as e:
                logger.debug(f"信号处理器注册跳过（非主线程）: {e}")
            self._cleanup_registered = True
            logger.debug("服务管理器清理机制已注册")

    def _signal_handler(self, signum, frame):
        """
        信号处理器，捕获 SIGINT 和 SIGTERM

        参数
        ----
        signum : int
            信号编号（SIGINT=2, SIGTERM=15）
        frame : FrameType
            当前栈帧对象（未使用）

        处理流程
        --------
        1. 记录接收到的信号编号
        2. 调用 cleanup_all() 清理所有服务进程
        3. 如果在主线程中，设置 _should_exit 标志通知等待循环退出
        4. 如果在子线程中，仅清理服务但不设置退出标志（避免线程安全问题）

        异常处理
        ----------
        清理过程中的异常会被捕获并记录，不会阻止后续处理

        线程安全
        --------
        只有主线程会设置 _should_exit 标志，子线程仅执行清理操作

        注意事项
        --------
        - 此函数在信号上下文中执行，应避免复杂操作
        - cleanup_all() 内部使用锁保护，确保线程安全
        """
        del frame
        logger.info(f"收到信号 {signum}，正在清理服务...")
        try:
            self.cleanup_all()
        except Exception as e:
            logger.error(f"清理服务时出错: {e}")

        import threading

        if threading.current_thread() is threading.main_thread():
            self._should_exit = True
        else:
            logger.info("非主线程收到信号，已清理服务但不强制退出")

    def register_process(
        self, name: str, process: subprocess.Popen, config: "WebUIConfig"
    ):
        """
        注册服务进程到管理器

        参数
        ----
        name : str
            服务名称，用作注册表键（格式: "web_ui_{host}_{port}"）
        process : subprocess.Popen
            启动的服务进程对象
        config : WebUIConfig
            服务的配置对象（包含 host、port、timeout 等）

        功能
        ----
        将进程信息添加到内部注册表 _processes，包含：
        - process: 进程对象，用于后续监控和终止
        - config: 配置对象，用于健康检查和端口管理
        - start_time: 启动时间戳，用于统计和调试

        线程安全
        --------
        使用 _lock 保护注册表修改操作

        使用场景
        --------
        - start_web_service() 启动服务后立即注册
        - 确保服务可以被 cleanup_all() 正确清理
        """
        with self._lock:
            self._processes[name] = {
                "process": process,
                "config": config,
                "start_time": time.time(),
            }
            logger.info(f"已注册服务进程: {name} (PID: {process.pid})")

    def unregister_process(self, name: str):
        """
        从管理器注销服务进程

        参数
        ----
        name : str
            服务名称

        功能
        ----
        从内部注册表 _processes 中移除指定进程的记录

        线程安全
        --------
        使用 _lock 保护注册表修改操作

        使用场景
        --------
        - terminate_process() 成功终止进程后调用
        - cleanup_all() 清理进程后强制移除记录

        注意事项
        --------
        - 不会终止进程本身，仅移除记录
        - 如果服务名不存在，操作会被忽略（不会抛出异常）
        """
        with self._lock:
            if name in self._processes:
                del self._processes[name]
                logger.debug(f"已注销服务进程: {name}")

    def get_process(self, name: str) -> Optional[subprocess.Popen]:
        """
        获取指定服务的进程对象

        参数
        ----
        name : str
            服务名称

        返回
        ----
        Optional[subprocess.Popen]
            进程对象（存在）或 None（不存在）

        线程安全
        --------
        使用 _lock 保护注册表读取操作

        使用场景
        --------
        - is_process_running() 检查进程状态
        - terminate_process() 获取要终止的进程
        """
        with self._lock:
            process_info = self._processes.get(name)
            return process_info["process"] if process_info else None

    def is_process_running(self, name: str) -> bool:
        """
        检查服务进程是否正在运行

        参数
        ----
        name : str
            服务名称

        返回
        ----
        bool
            True: 进程正在运行
            False: 进程不存在或已终止

        判断逻辑
        ----------
        1. 通过 get_process() 获取进程对象
        2. 如果进程不存在，返回 False
        3. 调用 process.poll() 检查进程状态：
           - None: 进程运行中（返回 True）
           - 非 None: 进程已退出（返回 False）

        异常处理
        ----------
        任何异常都会被捕获并返回 False（安全回退）

        使用场景
        --------
        - start_web_service() 检查服务是否已启动，避免重复启动
        - 健康检查前的快速状态验证
        """
        process = self.get_process(name)
        if process is None:
            return False

        try:
            return process.poll() is None
        except Exception:
            return False

    def terminate_process(self, name: str, timeout: float = 5.0) -> bool:
        """
        终止服务进程并清理所有相关资源

        参数
        ----
        name : str
            服务名称
        timeout : float, optional
            优雅关闭超时时间（秒），默认 5.0 秒

        返回
        ----
        bool
            True: 进程成功终止
            False: 终止过程中发生错误

        终止策略（分级）
        ----------------
        1. **检查进程状态**: 如果进程已退出，直接清理资源并返回
        2. **优雅关闭**: 发送 SIGTERM 信号，等待进程正常退出（最多 timeout 秒）
        3. **强制终止**: 如果优雅关闭超时，发送 SIGKILL 信号强制杀死进程
        4. **资源清理**: 关闭进程的 stdin、stdout、stderr 文件句柄
        5. **端口释放**: 等待端口被释放（最多 10 秒）
        6. **注销进程**: 从注册表中移除进程记录（finally 块确保执行）

        异常处理
        ----------
        - 终止过程中的异常会被捕获并记录
        - 资源清理失败会单独捕获，不影响注销操作
        - finally 块确保进程一定会从注册表中移除

        线程安全
        --------
        获取进程信息使用 _lock 保护（通过 _processes.get()）

        使用场景
        --------
        - cleanup_all() 批量清理所有进程
        - 手动停止特定服务
        - 服务异常后的清理重启

        注意事项
        --------
        - 如果进程不存在（未注册），直接返回 True（视为成功）
        - 端口释放超时不会导致返回 False，仅记录警告
        """
        process_info = self._processes.get(name)
        if not process_info:
            return True

        process = process_info["process"]
        config = process_info["config"]

        try:
            if process.poll() is not None:
                logger.debug(f"进程 {name} 已经结束")
                self._cleanup_process_resources(name, process_info)
                return True

            logger.info(f"正在终止服务进程: {name} (PID: {process.pid})")

            success = self._graceful_shutdown(process, name, timeout)

            if not success:
                success = self._force_shutdown(process, name)

            self._cleanup_process_resources(name, process_info)
            self._wait_for_port_release(config.host, config.port)

            return success

        except Exception as e:
            logger.error(f"终止进程 {name} 时出错: {e}")
            try:
                self._cleanup_process_resources(name, process_info)
            except Exception as cleanup_error:
                logger.error(f"清理进程资源时出错: {cleanup_error}")
            return False
        finally:
            self.unregister_process(name)

    def _graceful_shutdown(
        self, process: subprocess.Popen, name: str, timeout: float
    ) -> bool:
        """
        优雅关闭进程（发送 SIGTERM 信号）

        参数
        ----
        process : subprocess.Popen
            要关闭的进程对象
        name : str
            服务名称（用于日志）
        timeout : float
            等待进程退出的超时时间（秒）

        返回
        ----
        bool
            True: 进程在超时前成功退出
            False: 超时或发生异常

        工作流程
        --------
        1. 调用 process.terminate() 发送 SIGTERM 信号
        2. 调用 process.wait(timeout) 等待进程退出
        3. 如果在超时前退出，返回 True
        4. 如果超时，记录警告并返回 False

        异常处理
        ----------
        - subprocess.TimeoutExpired: 超时异常，返回 False
        - 其他异常: 记录错误并返回 False

        注意事项
        --------
        - SIGTERM 允许进程执行清理操作（如保存状态、关闭连接）
        - 不是所有进程都会响应 SIGTERM（可能需要强制终止）
        - Windows 上 terminate() 等同于 kill()（无优雅关闭）
        """
        try:
            process.terminate()
            process.wait(timeout=timeout)
            logger.info(f"服务进程 {name} 已关闭")
            return True
        except subprocess.TimeoutExpired:
            logger.warning(f"服务进程 {name} 关闭超时")
            return False
        except Exception as e:
            logger.error(f"关闭进程 {name} 失败: {e}")
            return False

    def _force_shutdown(self, process: subprocess.Popen, name: str) -> bool:
        """
        强制终止进程（发送 SIGKILL 信号）

        参数
        ----
        process : subprocess.Popen
            要强制终止的进程对象
        name : str
            服务名称（用于日志）

        返回
        ----
        bool
            True: 进程被成功杀死
            False: 仍然超时或发生异常

        工作流程
        --------
        1. 调用 process.kill() 发送 SIGKILL 信号（无法被捕获或忽略）
        2. 调用 process.wait(timeout=2.0) 等待进程被内核清理
        3. 如果在 2 秒内完成，返回 True
        4. 如果仍然超时（罕见），记录错误并返回 False

        异常处理
        ----------
        - subprocess.TimeoutExpired: 罕见情况，可能进程已成为僵尸进程
        - 其他异常: 记录错误并返回 False

        注意事项
        --------
        - SIGKILL 不允许进程执行任何清理操作（立即终止）
        - 可能导致数据丢失或资源泄漏（应优先使用 _graceful_shutdown）
        - 仅在优雅关闭失败后调用此方法
        - Windows 上 kill() 和 terminate() 行为一致

        使用场景
        --------
        - 优雅关闭超时后的备选方案
        - 进程无响应或卡死的情况
        """
        try:
            logger.warning(f"强制终止服务进程: {name}")
            process.kill()
            process.wait(timeout=2.0)
            logger.info(f"服务进程 {name} 已强制终止")
            return True
        except subprocess.TimeoutExpired:
            logger.error(f"强制终止进程 {name} 仍然超时")
            return False
        except Exception as e:
            logger.error(f"强制终止进程 {name} 失败: {e}")
            return False

    def _cleanup_process_resources(self, name: str, process_info: dict):
        """
        清理进程相关的文件句柄资源

        参数
        ----
        name : str
            服务名称（用于日志）
        process_info : dict
            进程信息字典，包含 "process" 键

        功能
        ----
        关闭进程的标准输入、输出和错误流文件句柄：
        - stdin: 防止管道阻塞
        - stdout: 释放文件描述符
        - stderr: 释放文件描述符

        异常处理
        ----------
        - 每个流的关闭操作独立进行，单个失败不影响其他
        - 所有异常都会被捕获并忽略（安全清理）
        - 整体清理失败会记录错误日志

        注意事项
        --------
        - 在进程终止后调用，确保没有数据残留在管道中
        - 即使流已经关闭，重复关闭也是安全的
        - 不会等待流中的数据被读取完毕（直接关闭）

        使用场景
        --------
        - terminate_process() 终止进程后清理资源
        - 防止文件描述符泄漏
        """
        try:
            process = process_info["process"]

            if hasattr(process, "stdin") and process.stdin:
                try:
                    process.stdin.close()
                except Exception:
                    pass

            if hasattr(process, "stdout") and process.stdout:
                try:
                    process.stdout.close()
                except Exception:
                    pass

            if hasattr(process, "stderr") and process.stderr:
                try:
                    process.stderr.close()
                except Exception:
                    pass

            logger.debug(f"进程 {name} 的资源已清理")

        except Exception as e:
            logger.error(f"清理进程 {name} 资源时出错: {e}")

    def _wait_for_port_release(self, host: str, port: int, timeout: float = 10.0):
        """
        等待端口被操作系统释放

        参数
        ----
        host : str
            主机地址（如 "127.0.0.1"、"0.0.0.0"）
        port : int
            端口号（1-65535）
        timeout : float, optional
            最大等待时间（秒），默认 10.0 秒

        功能
        ----
        循环检查端口是否可用（每 0.5 秒检查一次），直到：
        1. 端口被释放（is_web_service_running 返回 False）
        2. 超时（记录警告但不抛出异常）

        使用场景
        --------
        - 终止进程后确保端口可以被重新绑定
        - 避免"Address already in use"错误
        - 防止端口占用冲突

        注意事项
        --------
        - 超时不会导致函数失败，仅记录警告
        - 某些操作系统可能需要更长时间释放端口（尤其是 TIME_WAIT 状态）
        - 如果端口被其他进程占用，此函数无法检测到（需要额外检查）

        性能考虑
        ----------
        - 检查间隔 0.5 秒是平衡响应性和 CPU 占用的折中选择
        - 大部分情况下端口会在 1-2 秒内释放
        """
        start_time = time.time()
        while time.time() - start_time < timeout:
            if not is_web_service_running(host, port, timeout=1.0):
                logger.debug(f"端口 {host}:{port} 已释放")
                return
            time.sleep(0.5)
        logger.warning(f"端口 {host}:{port} 在 {timeout}秒内未释放")

    def cleanup_all(self):
        """
        清理所有已注册的服务进程，确保完全清理资源

        功能
        ----
        批量终止所有注册在 _processes 中的服务进程，并清理相关资源。
        使用容错设计，单个进程清理失败不会阻止其他进程的清理。

        清理流程
        --------
        1. 检查是否有进程需要清理（空注册表直接返回）
        2. 复制进程列表（避免在迭代时修改字典）
        3. 逐个调用 terminate_process() 清理进程
        4. 收集清理失败的进程和错误信息
        5. 强制移除仍然残留在注册表中的进程记录
        6. 汇总并记录清理结果

        异常处理
        ----------
        - 单个进程清理失败不会中断整体流程
        - 所有清理错误会被收集并统一记录
        - 强制移除记录失败也会被单独捕获和记录

        线程安全
        --------
        - 使用 _lock 保护进程列表的复制和最终的强制移除操作
        - terminate_process() 内部也使用锁保护

        使用场景
        --------
        - 程序正常退出时（通过 atexit 自动调用）
        - 接收到 SIGINT/SIGTERM 信号时（信号处理器调用）
        - 手动清理所有服务（如测试场景）

        注意事项
        --------
        - 此函数可能被多次调用（atexit + 信号处理器），但设计上是幂等的
        - 强制移除确保即使清理失败，进程记录也会被移除（避免后续误判）
        - 清理完成后注册表会被清空（_processes 为空字典）
        """
        if not self._processes:
            logger.debug("没有需要清理的进程")
            return

        logger.info("开始清理所有服务进程...")
        cleanup_errors = []

        with self._lock:
            processes_to_cleanup = list(self._processes.items())

        for name, _ in processes_to_cleanup:
            try:
                logger.debug(f"正在清理进程: {name}")
                success = self.terminate_process(name)
                if not success:
                    cleanup_errors.append(f"进程 {name} 清理失败")
            except Exception as e:
                error_msg = f"清理进程 {name} 时出错: {e}"
                logger.error(error_msg)
                cleanup_errors.append(error_msg)

        with self._lock:
            remaining_processes = list(self._processes.keys())
            if remaining_processes:
                logger.warning(f"仍有进程未清理完成: {remaining_processes}")
                for name in remaining_processes:
                    try:
                        del self._processes[name]
                        logger.debug(f"强制移除进程记录: {name}")
                    except Exception as e:
                        logger.error(f"强制移除进程记录失败 {name}: {e}")

        if cleanup_errors:
            logger.warning(f"服务进程清理完成，但有 {len(cleanup_errors)} 个错误:")
            for error in cleanup_errors:
                logger.warning(f"  - {error}")
        else:
            logger.info("所有服务进程清理完成")

        # 【修复】关闭通知管理器线程池，防止资源泄漏
        if NOTIFICATION_AVAILABLE:
            try:
                notification_manager.shutdown()
                logger.info("通知管理器线程池已关闭")
            except Exception as e:
                logger.warning(f"关闭通知管理器失败: {e}")

    def get_status(self) -> Dict[str, Dict]:
        """
        获取所有服务的运行状态信息

        返回
        ----
        Dict[str, Dict]
            服务状态字典，键为服务名，值为包含以下字段的状态字典：
            - "pid": 进程 ID（int）
            - "running": 是否正在运行（bool）
            - "start_time": 启动时间戳（float）
            - "config": 配置信息字典
                - "host": 绑定主机（str）
                - "port": 端口号（int）

        功能
        ----
        遍历所有已注册的服务进程，提取关键状态信息用于监控和调试。

        线程安全
        --------
        使用 _lock 保护 _processes 的遍历操作，确保读取一致性

        使用场景
        --------
        - 健康检查：验证服务是否正常运行
        - 调试诊断：查看所有服务的 PID 和配置
        - 监控面板：展示服务运行状态
        - 测试验证：确认服务启动成功

        注意事项
        --------
        - "running" 字段通过 process.poll() 判断（None 表示运行中）
        - 返回的是状态快照，调用后状态可能立即变化
        - 不会修改任何状态，仅读取操作
        """
        status = {}
        with self._lock:
            for name, info in self._processes.items():
                process = info["process"]
                status[name] = {
                    "pid": process.pid,
                    "running": process.poll() is None,
                    "start_time": info["start_time"],
                    "config": {
                        "host": info["config"].host,
                        "port": info["config"].port,
                    },
                }
        return status


@dataclass
class WebUIConfig:
    """
    Web UI 服务配置数据类

    功能概述
    --------
    封装 Web UI 服务的所有配置参数，包括网络绑定、超时设置和重试策略。
    使用 @dataclass 装饰器自动生成 __init__、__repr__ 等方法。

    属性
    ----
    host : str
        绑定的主机地址
        - "127.0.0.1": 仅本地访问（默认，安全）
        - "0.0.0.0": 允许外部访问（需配置网络安全策略）
        - 具体 IP 地址: 绑定到特定网络接口

    port : int
        Web 服务监听端口号（1-65535）
        默认: 8081

    timeout : int
        HTTP 请求超时时间（秒）
        默认: 30 秒
        适用于: 健康检查、API 请求、内容更新等

    max_retries : int
        HTTP 请求失败时的最大重试次数
        默认: 3 次
        适用于: 网络波动、临时故障等

    retry_delay : float
        重试之间的基础延迟时间（秒）
        默认: 1.0 秒
        实际延迟使用指数退避策略（backoff_factor）

    配置来源
    ----------
    - host: 优先使用 network_security.bind_interface，回退到 web_ui.host
    - port: web_ui.port
    - timeout: web_ui.timeout（HTTP 请求超时，与前端倒计时无关）
    - max_retries: web_ui.max_retries
    - retry_delay: web_ui.retry_delay

    验证规则
    --------
    在 __post_init__ 中自动验证参数有效性：
    - port: 必须在 1-65535 范围内
    - timeout: 必须大于 0
    - max_retries: 不能为负数

    使用场景
    --------
    - 创建 HTTP session（create_http_session）
    - 启动 Web 服务（start_web_service）
    - 健康检查（health_check_service）
    - 更新 Web 内容（update_web_content）

    注意事项
    --------
    - 此配置对象是不可变的（所有字段在创建后不应修改）
    - 重试策略使用 requests + urllib3.util.retry 实现
    - timeout 是 HTTP 层的超时，不是前端倒计时的 auto_resubmit_timeout
    """

    # 边界常量
    PORT_MIN = 1
    PORT_MAX = 65535
    PORT_PRIVILEGED = 1024  # 特权端口边界
    TIMEOUT_MIN = 1
    TIMEOUT_MAX = 300  # 最大 5 分钟
    MAX_RETRIES_MIN = 0
    MAX_RETRIES_MAX = 10
    RETRY_DELAY_MIN = 0.1
    RETRY_DELAY_MAX = 60.0

    host: str
    port: int
    timeout: int = 30
    max_retries: int = 3
    retry_delay: float = 1.0

    def __post_init__(self):
        """
        数据类初始化后的验证钩子

        功能
        ----
        自动验证所有配置参数的有效性，确保服务启动前发现配置错误。
        【优化】使用 config_utils.clamp_dataclass_field 简化边界检查。

        验证项
        ------
        1. 端口号范围: 1-65535，特权端口 (<1024) 警告
        2. 超时时间: 1-300 秒，超出范围自动调整
        3. 重试次数: 0-10 次，超出范围自动调整
        4. 重试延迟: 0.1-60.0 秒，超出范围自动调整

        异常
        ----
        ValueError
            端口号不在有效范围内时抛出
        """
        # 端口号验证（严格检查，无效直接抛异常）
        if not (self.PORT_MIN <= self.port <= self.PORT_MAX):
            raise ValueError(
                f"端口号必须在 {self.PORT_MIN}-{self.PORT_MAX} 范围内，当前值: {self.port}"
            )

        # 特权端口警告
        if self.port < self.PORT_PRIVILEGED:
            logger.warning(
                f"⚠️  端口 {self.port} 是特权端口（<{self.PORT_PRIVILEGED}），"
                f"可能需要 root/管理员权限才能绑定"
            )

        # 【重构】使用 clamp_dataclass_field 简化边界检查
        clamp_dataclass_field(self, "timeout", self.TIMEOUT_MIN, self.TIMEOUT_MAX)
        clamp_dataclass_field(
            self, "max_retries", self.MAX_RETRIES_MIN, self.MAX_RETRIES_MAX
        )
        clamp_dataclass_field(
            self, "retry_delay", self.RETRY_DELAY_MIN, self.RETRY_DELAY_MAX
        )


def get_web_ui_config() -> Tuple[WebUIConfig, int]:
    """
    从配置管理器加载 Web UI 配置（带缓存优化）

    返回
    ----
    Tuple[WebUIConfig, int]
        - WebUIConfig: Web UI 服务配置对象
        - int: 前端自动重新提交超时时间（auto_resubmit_timeout，单位秒）

    功能
    ----
    从全局配置文件（config.jsonc）中读取 Web UI 相关的所有配置参数，
    并构造 WebUIConfig 对象和提取前端倒计时时间。

    【性能优化】配置缓存
    ------------------
    - 缓存配置对象，避免每次调用都读取配置
    - 缓存有效期：10 秒（TTL）
    - 缓存过期后自动刷新
    - 支持热重载：缓存过期后会读取最新配置

    配置来源
    --------
    依赖以下配置段：
    1. **web_ui**: 主要配置（port、timeout、max_retries、retry_delay）
    2. **feedback**: 反馈配置（auto_resubmit_timeout）
    3. **network_security**: 网络安全配置（bind_interface）

    配置优先级
    ----------
    - host: network_security.bind_interface > web_ui.host > "127.0.0.1"
    - 其他字段: 配置文件值 > 函数内的默认值

    默认值
    ------
    - host: "127.0.0.1"（仅本地访问）
    - port: 8080
    - timeout: 30 秒（HTTP 请求超时）
    - max_retries: 3 次
    - retry_delay: 1.0 秒
    - auto_resubmit_timeout: 240 秒（前端倒计时）

    异常处理
    ----------
    ValueError
        - 配置参数类型错误（TypeError）
        - 配置参数验证失败（WebUIConfig.__post_init__）
        - 配置文件加载失败（ConfigManager 异常）

    使用场景
    --------
    - interactive_feedback() 工具初始化
    - launch_feedback_ui() 函数调用
    - start_web_service() 服务启动
    - wait_for_feedback() 等待反馈

    注意事项
    --------
    - auto_resubmit_timeout 是前端倒计时，不是 HTTP 请求超时
    - 配置加载失败会抛出 ValueError，调用者需要捕获处理
    - 【优化】配置缓存 10 秒，减少配置读取开销
    """
    # 【配置热更新】尽早注册回调，确保配置变更能立即清空缓存
    _ensure_config_change_callbacks_registered()

    # 【性能优化】检查缓存是否有效
    current_time = time.time()
    with _config_cache_lock:
        if (
            _config_cache["config"] is not None
            and current_time - _config_cache["timestamp"] < _config_cache["ttl"]
        ):
            logger.debug("使用缓存的 Web UI 配置")
            return _config_cache["config"]

    # 缓存过期或不存在，重新加载配置
    try:
        config_mgr = get_config()
        web_ui_config = config_mgr.get_section("web_ui")
        feedback_config = config_mgr.get_section("feedback")
        network_security_config = config_mgr.get_section("network_security")

        host = network_security_config.get(
            "bind_interface", web_ui_config.get("host", "127.0.0.1")
        )
        port = web_ui_config.get("port", 8080)

        # 【重构】使用 get_compat_config 简化向后兼容配置读取
        auto_resubmit_timeout = get_compat_config(
            feedback_config, "frontend_countdown", "auto_resubmit_timeout", 240
        )
        max_retries = get_compat_config(
            web_ui_config, "http_max_retries", "max_retries", 3
        )
        retry_delay = get_compat_config(
            web_ui_config, "http_retry_delay", "retry_delay", 1.0
        )
        http_timeout = get_compat_config(
            web_ui_config, "http_request_timeout", "timeout", 30
        )

        config = WebUIConfig(
            host=host,
            port=port,
            timeout=http_timeout,
            max_retries=max_retries,
            retry_delay=retry_delay,
        )

        # 【性能优化】更新缓存
        result = (config, auto_resubmit_timeout)
        with _config_cache_lock:
            _config_cache["config"] = result
            _config_cache["timestamp"] = current_time

        logger.info(
            f"Web UI 配置加载成功: {host}:{port}, 自动重调超时: {auto_resubmit_timeout}秒"
        )
        return result
    except (ValueError, TypeError) as e:
        logger.error(f"配置参数错误: {e}")
        raise ValueError(f"Web UI 配置错误: {e}") from e
    except Exception as e:
        logger.error(f"配置文件加载失败: {e}")
        raise ValueError(f"Web UI 配置加载失败: {e}") from e


# ============================================================================
# Feedback 配置常量和默认值
# ============================================================================

# 超时相关常量
FEEDBACK_TIMEOUT_DEFAULT = 600  # 默认后端最大等待时间（秒）
FEEDBACK_TIMEOUT_MIN = 60  # 后端最小等待时间（秒）
FEEDBACK_TIMEOUT_MAX = 3600  # 后端最大等待时间上限（秒，1小时）

AUTO_RESUBMIT_TIMEOUT_DEFAULT = 240  # 默认前端倒计时（秒）
AUTO_RESUBMIT_TIMEOUT_MIN = 30  # 前端最小倒计时（秒）
AUTO_RESUBMIT_TIMEOUT_MAX = 250  # 前端最大倒计时（秒）【优化】从290→250，预留安全余量
BACKEND_BUFFER = 40  # 后端缓冲时间（秒，前端+缓冲=后端最小）【优化】从60→40
BACKEND_MIN = 260  # 后端最低等待时间（秒）【优化】从300→260，预留40秒安全余量避免MCPHub 300秒硬超时

# 提示语相关常量
PROMPT_MAX_LENGTH = 500  # 提示语最大长度
RESUBMIT_PROMPT_DEFAULT = "请立即调用 interactive_feedback 工具"
PROMPT_SUFFIX_DEFAULT = "\n请积极调用 interactive_feedback 工具"

# 输入校验相关常量（用于 validate_input）
# 注意：这些常量也会被测试用例引用，保持为模块级常量
MAX_MESSAGE_LENGTH = 10000  # 用户输入/提示文本最大长度
MAX_OPTION_LENGTH = 500  # 单个预定义选项最大长度


@dataclass
class FeedbackConfig:
    """
    反馈配置数据类

    封装所有 feedback 配置字段，提供类型安全和边界验证。

    属性
    ----
    timeout : int
        后端最大等待时间（秒），范围 [60, 3600]
    auto_resubmit_timeout : int
        前端倒计时时间（秒），范围 [30, 290]，0 表示禁用
    resubmit_prompt : str
        错误/超时时返回的提示语
    prompt_suffix : str
        追加到用户反馈末尾的提示语
    """

    timeout: int
    auto_resubmit_timeout: int
    resubmit_prompt: str
    prompt_suffix: str

    def __post_init__(self):
        """
        验证配置值的边界条件

        【重构】使用 config_utils 辅助函数简化边界检查和字符串截断。
        注意：auto_resubmit_timeout 为 0 时表示禁用，需要特殊处理。
        """
        from config_utils import clamp_value

        # 【重构】使用 clamp_value 简化 timeout 验证
        self.timeout = clamp_value(
            self.timeout, FEEDBACK_TIMEOUT_MIN, FEEDBACK_TIMEOUT_MAX, "feedback.timeout"
        )

        # auto_resubmit_timeout 验证（0 表示禁用，其他值需在范围内）
        if self.auto_resubmit_timeout != 0:
            self.auto_resubmit_timeout = clamp_value(
                self.auto_resubmit_timeout,
                AUTO_RESUBMIT_TIMEOUT_MIN,
                AUTO_RESUBMIT_TIMEOUT_MAX,
                "feedback.auto_resubmit_timeout",
            )

        # 【重构】使用 truncate_string 简化字符串验证
        self.resubmit_prompt = truncate_string(
            self.resubmit_prompt,
            PROMPT_MAX_LENGTH,
            "feedback.resubmit_prompt",
            default=RESUBMIT_PROMPT_DEFAULT,
        )
        self.prompt_suffix = truncate_string(
            self.prompt_suffix,
            PROMPT_MAX_LENGTH,
            "feedback.prompt_suffix",
        )


def get_feedback_config() -> FeedbackConfig:
    """
    获取并验证完整的 feedback 配置

    返回
    ----
    FeedbackConfig
        验证后的反馈配置对象

    功能
    ----
    从配置文件读取 feedback 配置段，并进行类型转换和边界验证。

    配置字段
    --------
    - timeout: 后端最大等待时间（秒），默认 600，范围 [60, 3600]
    - auto_resubmit_timeout: 前端倒计时（秒），默认 240，范围 [30, 290]，0=禁用
    - resubmit_prompt: 错误/超时提示语，默认 "请立即调用 interactive_feedback 工具"
    - prompt_suffix: 反馈后缀，默认 "\\n请积极调用 interactive_feedback 工具"

    边界处理
    --------
    - 超出范围的值会被自动调整到边界值
    - 空字符串提示语会使用默认值
    - 过长的提示语会被截断

    异常处理
    --------
    配置加载失败时返回全默认值的 FeedbackConfig 对象
    """
    try:
        config_mgr = get_config()
        feedback_config = config_mgr.get_section("feedback")

        # 【重构】使用 get_compat_config 简化向后兼容配置读取
        timeout = int(
            get_compat_config(
                feedback_config, "backend_max_wait", "timeout", FEEDBACK_TIMEOUT_DEFAULT
            )
        )
        auto_resubmit_timeout = int(
            get_compat_config(
                feedback_config,
                "frontend_countdown",
                "auto_resubmit_timeout",
                AUTO_RESUBMIT_TIMEOUT_DEFAULT,
            )
        )
        resubmit_prompt = str(
            feedback_config.get("resubmit_prompt", RESUBMIT_PROMPT_DEFAULT)
        )
        prompt_suffix = str(feedback_config.get("prompt_suffix", PROMPT_SUFFIX_DEFAULT))

        return FeedbackConfig(
            timeout=timeout,
            auto_resubmit_timeout=auto_resubmit_timeout,
            resubmit_prompt=resubmit_prompt,
            prompt_suffix=prompt_suffix,
        )
    except (ValueError, TypeError) as e:
        logger.warning(f"获取反馈配置失败（类型错误），使用默认值: {e}")
        return FeedbackConfig(
            timeout=FEEDBACK_TIMEOUT_DEFAULT,
            auto_resubmit_timeout=AUTO_RESUBMIT_TIMEOUT_DEFAULT,
            resubmit_prompt=RESUBMIT_PROMPT_DEFAULT,
            prompt_suffix=PROMPT_SUFFIX_DEFAULT,
        )
    except Exception as e:
        logger.warning(f"获取反馈配置失败，使用默认值: {e}")
        return FeedbackConfig(
            timeout=FEEDBACK_TIMEOUT_DEFAULT,
            auto_resubmit_timeout=AUTO_RESUBMIT_TIMEOUT_DEFAULT,
            resubmit_prompt=RESUBMIT_PROMPT_DEFAULT,
            prompt_suffix=PROMPT_SUFFIX_DEFAULT,
        )


def calculate_backend_timeout(
    auto_resubmit_timeout: int, max_timeout: int = 0, infinite_wait: bool = False
) -> int:
    """
    统一计算后端等待超时时间

    参数
    ----
    auto_resubmit_timeout : int
        前端倒计时时间（秒），0 或负数表示禁用自动提交
    max_timeout : int, optional
        配置的最大超时时间（秒），默认 0 表示使用配置文件值
    infinite_wait : bool, optional
        是否启用无限等待模式，默认 False

    返回
    ----
    int
        后端等待超时时间（秒），0 表示无限等待

    计算规则
    --------
    1. 无限等待模式 (infinite_wait=True): 返回 0
    2. 禁用自动提交 (auto_resubmit_timeout <= 0): 返回 max(max_timeout, BACKEND_MIN)
    3. 正常模式: 返回 min(max(auto_resubmit_timeout + BACKEND_BUFFER, BACKEND_MIN), max_timeout)

    设计说明
    --------
    - 后端等待时间 = 前端倒计时 + 缓冲时间（60秒）
    - 后端最低等待 300 秒，确保有足够时间处理
    - 使用 feedback.timeout 作为上限，防止无限等待
    - 统一两个函数（interactive_feedback 和 launch_feedback_ui）的超时计算逻辑
    """
    if infinite_wait:
        return 0

    # 获取配置的最大超时时间
    if max_timeout <= 0:
        feedback_config = get_feedback_config()
        max_timeout = feedback_config.timeout

    if auto_resubmit_timeout <= 0:
        # 禁用自动提交时，使用配置的最大超时或默认最低值
        return max(max_timeout, BACKEND_MIN)

    # 正常模式：后端 = min(max(前端 + 缓冲, 最低), 最大)
    calculated = max(auto_resubmit_timeout + BACKEND_BUFFER, BACKEND_MIN)
    return min(calculated, max_timeout)


def get_feedback_prompts() -> Tuple[str, str]:
    """
    获取反馈提示语配置（兼容旧接口）

    返回
    ----
    Tuple[str, str]
        - resubmit_prompt: 错误/超时时返回的提示语（引导AI重新调用工具）
        - prompt_suffix: 追加到用户反馈末尾的提示语（保持会话连续性）

    功能
    ----
    从配置文件读取自定义的反馈提示语，支持用户自定义这些固定文本。
    此函数是 get_feedback_config() 的简化包装，保持向后兼容。

    默认值
    ------
    - resubmit_prompt: "请立即调用 interactive_feedback 工具"
    - prompt_suffix: "\\n请积极调用 interactive_feedback 工具"

    验证规则
    --------
    - 空字符串使用默认值
    - 超过 500 字符的提示语会被截断
    """
    config = get_feedback_config()
    return config.resubmit_prompt, config.prompt_suffix


def validate_input(
    prompt: str, predefined_options: Optional[list] = None
) -> Tuple[str, list]:
    """
    验证和清理用户输入参数，防止恶意或异常输入

    参数
    ----
    prompt : str
        提示文本或问题内容
    predefined_options : Optional[list], optional
        预定义选项列表，默认 None

    返回
    ----
    Tuple[str, list]
        - str: 清理后的提示文本（去除首尾空白、截断过长内容）
        - list: 清理后的选项列表（过滤非字符串、截断过长选项）

    功能
    ----
    1. **提示文本清理**:
       - 去除首尾空白字符（strip）
       - 长度限制: 最大 MAX_MESSAGE_LENGTH 字符，超出部分截断并添加 "..."
       - 类型检查: 必须是字符串，否则抛出 ValueError

    2. **选项列表清理**:
       - 过滤非字符串选项（记录警告）
       - 去除每个选项的首尾空白
       - 长度限制: 每个选项最大 MAX_OPTION_LENGTH 字符，超出部分截断并添加 "..."
       - 过滤空选项（strip 后为空）

    异常处理
    ----------
    ValueError
        prompt 不是字符串类型时抛出（AttributeError 转换为 ValueError）

    安全考虑
    ----------
    - 防止超长输入导致内存溢出或界面显示问题
    - 过滤非法类型的选项，避免序列化错误
    - 自动记录警告信息，便于调试和监控

    使用场景
    --------
    - launch_feedback_ui() 启动反馈界面前验证输入
    - update_web_content() 更新内容前清理数据
    - interactive_feedback() MCP 工具接收参数后验证

    注意事项
    --------
    - 截断操作会丢失部分信息，但保证系统稳定性
    - 空选项列表（None 或全部被过滤）会返回空列表 []
    - 截断的内容会添加 "..." 标记，用户可见
    """
    try:
        cleaned_prompt = prompt.strip()
    except AttributeError:
        raise ValueError("prompt 必须是字符串类型") from None
    if len(cleaned_prompt) > MAX_MESSAGE_LENGTH:
        logger.warning(
            f"prompt 长度过长 ({len(cleaned_prompt)} 字符)，将被截断到 {MAX_MESSAGE_LENGTH}"
        )
        cleaned_prompt = cleaned_prompt[:MAX_MESSAGE_LENGTH] + "..."

    cleaned_options = []
    if predefined_options:
        for option in predefined_options:
            if not isinstance(option, str):
                logger.warning(f"跳过非字符串选项: {option}")
                continue
            cleaned_option = option.strip()
            if cleaned_option and len(cleaned_option) <= MAX_OPTION_LENGTH:
                cleaned_options.append(cleaned_option)
            elif len(cleaned_option) > MAX_OPTION_LENGTH:
                logger.warning(f"选项过长被截断: {cleaned_option[:50]}...")
                cleaned_options.append(cleaned_option[:MAX_OPTION_LENGTH] + "...")

    return cleaned_prompt, cleaned_options


def create_http_session(config: WebUIConfig) -> requests.Session:
    """
    创建配置了重试机制和超时设置的 HTTP 会话（带缓存复用）

    参数
    ----
    config : WebUIConfig
        Web UI 配置对象（包含 max_retries、retry_delay、timeout）

    返回
    ----
    requests.Session
        配置好的 requests 会话对象，支持自动重试和超时控制

    功能
    ----
    使用 urllib3.util.retry.Retry 配置智能重试策略：
    1. **重试次数**: config.max_retries（默认 3 次）
    2. **退避策略**: 指数退避（backoff_factor），基础延迟为 config.retry_delay
       - 第 1 次重试: retry_delay * 2^0 秒
       - 第 2 次重试: retry_delay * 2^1 秒
       - 第 3 次重试: retry_delay * 2^2 秒
    3. **重试条件**: HTTP 状态码为 429（Too Many Requests）、500（服务器错误）、
       502（Bad Gateway）、503（服务不可用）、504（网关超时）
    4. **允许方法**: HEAD、GET、POST（幂等和非幂等请求）
    5. **超时设置**: config.timeout（默认 30 秒）

    挂载适配器
    ----------
    为 http:// 和 https:// 协议挂载相同的重试适配器，确保所有请求都使用重试策略。

    【性能优化】Session 缓存复用
    -------------------------
    - 基于配置参数生成缓存键
    - 复用已创建的 session 对象，避免重复创建
    - 减少 TCP 握手开销，提升高频请求性能

    使用场景
    --------
    - health_check_service() 健康检查请求
    - update_web_content() 更新内容请求
    - wait_for_feedback() 轮询反馈状态
    - wait_for_task_completion() 轮询任务完成

    性能考虑
    ----------
    - 重试策略可减少因临时网络波动导致的请求失败
    - 指数退避避免对服务器造成过大压力
    - 超时设置防止请求无限挂起
    - 【优化】Session 复用减少连接建立开销

    注意事项
    --------
    - requests 的超时应通过每次请求的 timeout 参数控制（避免给 Session 动态挂载属性）
    - POST 请求默认也会重试（非标准行为，但适用于本项目的幂等 API）
    - 重试不适用于连接错误（如服务未启动），仅适用于 HTTP 响应错误
    """
    # 【性能优化】基于配置参数生成缓存键，复用 session
    cache_key = f"{config.max_retries}_{config.retry_delay}_{config.timeout}"

    with _http_session_lock:
        if cache_key in _http_session_cache:
            logger.debug(f"复用已缓存的 HTTP Session: {cache_key}")
            return _http_session_cache[cache_key]

        # 创建新的 session
        session = requests.Session()

        retry_strategy = Retry(
            total=config.max_retries,
            backoff_factor=config.retry_delay,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "POST"],
        )

        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        # 缓存 session
        _http_session_cache[cache_key] = session
        logger.debug(f"创建并缓存新的 HTTP Session: {cache_key}")

        return session


def is_web_service_running(host: str, port: int, timeout: float = 2.0) -> bool:
    """
    检查 Web 服务是否正在运行（基于 TCP 端口连接性）

    参数
    ----
    host : str
        主机地址（如 "127.0.0.1"、"0.0.0.0"、域名）
    port : int
        端口号（1-65535）
    timeout : float, optional
        连接超时时间（秒），默认 2.0 秒

    返回
    ----
    bool
        True: 端口可连接（服务可能正在运行）
        False: 端口不可连接或检查失败

    功能
    ----
    使用 TCP socket 尝试连接指定的主机和端口，判断服务是否在监听。

    检查流程
    --------
    1. 验证端口号范围（1-65535）
    2. 转换 0.0.0.0 为 localhost（0.0.0.0 绑定所有接口，但客户端需连接具体地址）
    3. 创建 TCP socket 并设置超时
    4. 尝试连接（非阻塞检查）
    5. 根据连接结果返回布尔值

    异常处理
    ----------
    - socket.gaierror: 主机名解析失败（DNS 错误），返回 False
    - 其他异常: 捕获并记录错误，返回 False（安全回退）

    注意事项
    --------
    - **非应用层检查**: 仅验证端口可连接，不保证 HTTP 服务正常工作
    - **0.0.0.0 转换**: 服务绑定 0.0.0.0 时，客户端需连接 localhost 或具体 IP
    - **超时设置**: 较短的超时（2 秒）可快速失败，避免阻塞
    - **防火墙影响**: 防火墙可能阻止连接，导致误判

    使用场景
    --------
    - start_web_service() 检查服务是否已启动，避免重复启动
    - ServiceManager._wait_for_port_release() 等待端口释放
    - 快速状态检查（比 HTTP 请求更轻量）

    性能考虑
    ----------
    - connect_ex() 是非阻塞调用，不会挂起进程
    - 上下文管理器自动关闭 socket，无资源泄漏
    - 超时 2 秒在失败场景下快速返回
    """
    try:
        if not (1 <= port <= 65535):
            logger.error(f"无效端口号: {port}")
            return False

        target_host = "localhost" if host == "0.0.0.0" else host

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            result = sock.connect_ex((target_host, port))
            is_running = result == 0

            if is_running:
                logger.debug(f"Web 服务运行中: {target_host}:{port}")
            else:
                logger.debug(f"Web 服务未运行: {target_host}:{port}")

            return is_running

    except socket.gaierror as e:
        logger.error(f"主机名解析失败 {host}: {e}")
        return False
    except Exception as e:
        logger.error(f"检查服务状态时出错: {e}")
        return False


def health_check_service(config: WebUIConfig) -> bool:
    """
    应用层健康检查，验证 Web 服务是否正常响应 HTTP 请求

    参数
    ----
    config : WebUIConfig
        Web UI 配置对象（包含 host、port、timeout 等）

    返回
    ----
    bool
        True: 服务健康（端口可连接且 HTTP 请求成功）
        False: 服务不健康或检查失败

    功能
    ----
    执行两层检查，确保服务完全可用：
    1. **传输层检查**: 调用 is_web_service_running() 验证端口可连接
    2. **应用层检查**: 发送 HTTP GET 请求到 /api/health，验证服务正常响应

    检查流程
    --------
    1. 首先检查端口是否可连接（快速失败）
    2. 如果端口不可达，直接返回 False
    3. 创建 HTTP session 并发送 GET 请求到 /api/health
    4. 检查响应状态码（200 表示健康）
    5. 返回健康状态

    健康标准
    --------
    - 端口可连接（TCP 层）
    - HTTP 请求成功（状态码 200）
    - /api/health 端点可访问（Flask 应用正常运行）

    异常处理
    ----------
    - requests.exceptions.RequestException: 网络请求异常（连接错误、超时等），返回 False
    - 其他异常: 捕获并记录错误，返回 False（安全回退）

    使用场景
    --------
    - start_web_service() 启动服务后验证服务正常
    - ensure_web_ui_running() 检查服务是否需要重启
    - 定期健康检查（监控脚本）

    性能考虑
    ----------
    - 超时设置为 5 秒（比默认 30 秒更快）
    - 先检查端口（轻量），再发送 HTTP 请求（重量）
    - 使用带重试的 session（自动处理临时故障）

    注意事项
    --------
    - 仅验证 /api/health 端点，不保证所有功能正常
    - 0.0.0.0 地址会自动转换为 localhost
    - 健康检查失败不会抛出异常，仅返回 False
    - 重试策略可能延长检查时间（最多 3 次重试）
    - 【统一】与 ensure_web_ui_running() 使用相同端点
    """
    if not is_web_service_running(config.host, config.port):
        return False

    try:
        session = create_http_session(config)
        target_host = "localhost" if config.host == "0.0.0.0" else config.host
        health_url = f"http://{target_host}:{config.port}/api/health"

        response = session.get(health_url, timeout=5)
        is_healthy = response.status_code == 200

        if is_healthy:
            logger.debug("服务健康检查通过")
        else:
            logger.warning(f"服务健康检查失败，状态码: {response.status_code}")

        return is_healthy

    except requests.exceptions.RequestException as e:
        logger.error(f"健康检查请求失败: {e}")
        return False
    except Exception as e:
        logger.error(f"健康检查时出现未知错误: {e}")
        return False


def start_web_service(config: WebUIConfig, script_dir: str) -> None:
    """
    启动 Web UI 反馈服务（Flask 子进程）

    参数
    ----
    config : WebUIConfig
        Web UI 配置对象（包含 host、port、timeout 等）
    script_dir : str
        脚本目录路径（包含 web_ui.py 的目录）

    功能
    ----
    以子进程方式启动 Flask Web UI 服务，提供浏览器反馈界面。
    包含完整的启动流程、健康检查和错误处理。

    启动流程
    --------
    1. **任务清理**: 清空全局任务队列中的所有残留任务（确保"无有效内容"状态）
    2. **通知系统初始化**: 如果通知模块可用，初始化通知管理器和提供者
    3. **文件验证**: 检查 web_ui.py 是否存在
    4. **重复启动检查**: 检查服务是否已在运行（避免端口冲突）
    5. **进程启动**: 使用 subprocess.Popen 启动 web_ui.py
    6. **进程注册**: 将进程注册到 ServiceManager（确保可被清理）
    7. **健康检查轮询**: 每 0.5 秒检查一次服务是否启动成功（最多 15 秒）
    8. **成功返回或超时异常**: 服务启动成功返回，超时则抛出异常

    启动参数
    ----------
    传递给 web_ui.py 的命令行参数：
    - sys.executable: Python 解释器路径（确保使用相同的 Python 环境）
    - -u: 禁用输出缓冲（unbuffered），确保日志实时输出
    - web_ui.py: Flask 应用脚本路径
    - --prompt "": 初始提示文本为空（无有效内容状态）
    - --predefined-options "": 初始选项为空
    - --host: 绑定主机地址（如 127.0.0.1 或 0.0.0.0）
    - --port: 监听端口号

    进程配置
    ----------
    - stdout=subprocess.DEVNULL: 丢弃标准输出（避免污染 MCP stdio）
    - stderr=subprocess.DEVNULL: 丢弃标准错误（Flask 日志不通过 stderr）
    - stdin=subprocess.DEVNULL: 关闭标准输入（服务不需要交互）
    - close_fds=True: 关闭所有文件描述符（避免泄漏）

    健康检查
    ----------
    - 检查间隔: 0.5 秒
    - 最大等待时间: 15 秒
    - 检查方法: health_check_service()（TCP 连接 + HTTP 请求）
    - 进度日志: 每 2 秒记录一次等待状态

    异常处理
    ----------
    - FileNotFoundError: web_ui.py 或 Python 解释器不存在
    - PermissionError: 没有执行权限或端口绑定权限
    - 其他异常: 捕获并检查服务是否已运行（容错处理）
    - 超时: 15 秒内未通过健康检查，抛出 Exception

    幂等性
    --------
    - 重复调用不会导致多个进程（检查已运行状态）
    - 启动失败后会检查服务是否已由其他方式启动
    - 任务清理确保每次启动都是干净状态

    通知系统
    ----------
    如果通知模块可用（notification_manager 和 notification_providers 导入成功）：
    - 调用 initialize_notification_system() 初始化所有通知提供者
    - 初始化失败仅记录警告，不影响服务启动

    使用场景
    --------
    - interactive_feedback() 工具首次调用时
    - ensure_web_ui_running() 检测到服务未运行时
    - 测试脚本中手动启动服务

    注意事项
    --------
    - 子进程会继承父进程的环境变量
    - 服务进程的生命周期由 ServiceManager 管理
    - 服务异常退出不会自动重启（需要外部监控）
    - 端口被占用时会启动失败（超时异常）
    - 启动时的空内容状态符合"无有效内容"设计原则

    异常
    ----
    FileNotFoundError
        web_ui.py 文件不存在
    Exception
        - Python 解释器或脚本文件未找到
        - 权限不足
        - 启动失败且服务未运行
        - 启动超时（15 秒内未通过健康检查）
    """
    task_queue = get_task_queue()
    cleared_count = task_queue.clear_all_tasks()
    if cleared_count > 0:
        logger.info(f"服务启动时清理了 {cleared_count} 个残留任务")

    web_ui_path = os.path.join(script_dir, "web_ui.py")
    service_manager = ServiceManager()
    service_name = f"web_ui_{config.host}_{config.port}"

    if NOTIFICATION_AVAILABLE:
        try:
            initialize_notification_system(notification_manager.get_config())
            logger.info("通知系统初始化完成")
        except Exception as e:
            logger.warning(f"通知系统初始化失败: {e}")

    # 验证 web_ui.py 文件是否存在
    if not os.path.exists(web_ui_path):
        raise FileNotFoundError(f"Web UI 脚本不存在: {web_ui_path}")

    # 检查服务是否已经在运行
    if service_manager.is_process_running(service_name) or health_check_service(config):
        logger.info(f"Web 服务已在运行: http://{config.host}:{config.port}")
        return

    # 启动Web服务，初始为空内容
    args = [
        sys.executable,
        "-u",
        web_ui_path,
        "--prompt",
        "",  # 启动时为空，符合"无有效内容"状态
        "--predefined-options",
        "",
        "--host",
        config.host,
        "--port",
        str(config.port),
    ]

    # 在后台启动服务
    try:
        logger.info(f"启动 Web 服务进程: {' '.join(args)}")
        process = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            close_fds=True,
        )
        logger.info(f"Web 服务进程已启动，PID: {process.pid}")

        # 注册进程到服务管理器
        service_manager.register_process(service_name, process, config)

    except FileNotFoundError as e:
        logger.error(f"Python 解释器或脚本文件未找到: {e}")
        raise Exception(f"无法启动 Web 服务，文件未找到: {e}") from e
    except PermissionError as e:
        logger.error(f"权限不足，无法启动服务: {e}")
        raise Exception(f"权限不足，无法启动 Web 服务: {e}") from e
    except Exception as e:
        logger.error(f"启动服务进程时出错: {e}")
        # 如果启动失败，再次检查服务是否已经在运行
        if health_check_service(config):
            logger.info("服务已经在运行，继续使用现有服务")
            return
        else:
            raise Exception(f"启动 Web 服务失败: {e}") from e

    # 等待服务启动并进行健康检查
    max_wait = 15  # 最多等待15秒
    check_interval = 0.5  # 每0.5秒检查一次

    for attempt in range(int(max_wait / check_interval)):
        if health_check_service(config):
            logger.info(f"🌐 Web服务已启动: http://{config.host}:{config.port}")
            return

        if attempt % 4 == 0:  # 每2秒记录一次等待状态
            logger.debug(f"等待服务启动... ({attempt * check_interval:.1f}s)")

        time.sleep(check_interval)

    # 最终检查
    if health_check_service(config):
        logger.info(f"🌐 Web 服务启动成功: http://{config.host}:{config.port}")
    else:
        raise Exception(
            f"Web 服务启动超时 ({max_wait}秒)，请检查端口 {config.port} 是否被占用"
        )


def update_web_content(
    summary: str,
    predefined_options: Optional[list[str]],
    task_id: Optional[str],
    auto_resubmit_timeout: int,
    config: WebUIConfig,
) -> None:
    """
    通过 HTTP API 更新 Web UI 展示的内容

    参数
    ----
    summary : str
        反馈摘要或问题文本
    predefined_options : Optional[list[str]]
        预定义选项列表，用户可多选
    task_id : Optional[str]
        任务唯一标识符，None 表示更新主内容区
    auto_resubmit_timeout : int
        前端自动重新提交超时时间（秒）
    config : WebUIConfig
        Web UI 配置对象

    功能
    ----
    向 Web UI 的 /api/update 端点发送 POST 请求，更新浏览器中展示的反馈界面内容。

    API 请求
    --------
    - URL: http://{host}:{port}/api/update
    - Method: POST
    - Content-Type: application/json
    - Body:
        {
            "prompt": str,                    # 清理后的提示文本
            "predefined_options": list[str],  # 清理后的选项列表
            "task_id": str | null,            # 任务 ID
            "auto_resubmit_timeout": int      # 前端倒计时（秒）
        }

    处理流程
    --------
    1. 调用 validate_input() 验证和清理输入参数
    2. 转换 0.0.0.0 为 localhost（客户端连接地址）
    3. 构造 JSON 请求体
    4. 创建带重试的 HTTP session
    5. 发送 POST 请求
    6. 验证响应状态码和 JSON 格式
    7. 成功返回或抛出异常

    响应状态码
    ----------
    - 200: 更新成功，验证 JSON 响应中的 "status" 字段
    - 400: 请求参数错误（summary/options 格式问题）
    - 404: API 端点不存在（服务未正确启动）
    - 其他: 服务内部错误

    异常处理
    ----------
    - requests.exceptions.Timeout: 请求超时（超过 config.timeout 秒）
    - requests.exceptions.ConnectionError: 无法连接到服务（服务未启动或网络问题）
    - requests.exceptions.RequestException: 其他网络请求错误
    - Exception: 其他未知错误

    验证逻辑
    --------
    即使响应状态码为 200，也会尝试解析 JSON 并检查 "status" 字段：
    - 如果 "status" != "success"，记录警告（但不抛出异常）
    - 如果响应不是有效 JSON，记录警告（但不抛出异常）

    使用场景
    --------
    - 废弃（不再使用）: 旧架构中用于更新单一内容区
    - 新架构: 使用任务队列 API（/api/tasks）代替

    注意事项
    --------
    - 此函数不等待用户反馈，仅更新界面内容
    - 0.0.0.0 地址会自动转换为 localhost
    - 所有异常都会被转换为 Exception 抛出
    - 重试策略（3 次）在 create_http_session() 中配置
    - 超时时间使用 config.timeout（HTTP 层），不是 auto_resubmit_timeout（前端倒计时）

    异常
    ----
    Exception
        - 更新内容超时
        - 无法连接到 Web 服务
        - 更新内容失败（各种网络或服务错误）
    """
    # 验证输入
    cleaned_summary, cleaned_options = validate_input(summary, predefined_options)

    target_host = "localhost" if config.host == "0.0.0.0" else config.host
    url = f"http://{target_host}:{config.port}/api/update"

    data = {
        "prompt": cleaned_summary,
        "predefined_options": cleaned_options,
        "task_id": task_id,
        "auto_resubmit_timeout": auto_resubmit_timeout,
    }

    session = create_http_session(config)

    try:
        logger.debug(f"更新 Web 内容: {url} (task_id: {task_id})")
        response = session.post(url, json=data, timeout=config.timeout)

        if response.status_code == 200:
            logger.info(
                f"📝 内容已更新: {cleaned_summary[:50]}... (task_id: {task_id})"
            )

            # 验证更新是否成功
            try:
                result = response.json()
                if result.get("status") != "success":
                    logger.warning(f"更新响应状态异常: {result}")
            except ValueError:
                logger.warning("更新响应不是有效的 JSON 格式")

        elif response.status_code == 400:
            logger.error(f"更新请求参数错误: {response.text}")
            raise Exception(f"更新内容失败，请求参数错误: {response.text}")
        elif response.status_code == 404:
            logger.error("更新 API 端点不存在，可能服务未正确启动")
            raise Exception("更新 API 不可用，请检查服务状态")
        else:
            logger.error(f"更新内容失败，HTTP 状态码: {response.status_code}")
            raise Exception(f"更新内容失败，状态码: {response.status_code}")

    except requests.exceptions.Timeout:
        logger.error(f"更新内容超时 ({config.timeout}秒)")
        raise Exception("更新内容超时，请检查网络连接") from None
    except requests.exceptions.ConnectionError:
        logger.error(f"无法连接到 Web 服务: {url}")
        raise Exception("无法连接到 Web 服务，请确认服务正在运行") from None
    except requests.exceptions.RequestException as e:
        logger.error(f"更新内容时网络请求失败: {e}")
        raise Exception(f"更新内容失败: {e}") from e
    except Exception as e:
        logger.error(f"更新内容时出现未知错误: {e}")
        raise Exception(f"更新 Web 内容失败: {e}") from e


def parse_structured_response(
    response_data: Optional[Dict[str, Any]],
) -> list[ContentBlock]:
    """
    解析 Web UI 反馈数据并转换为 MCP 标准 Content 对象列表

    参数
    ----
    response_data : Optional[Dict[str, Any]]
        从 Web UI /api/feedback 或 /api/tasks/{id} 获取的反馈数据字典
        预期结构:
        {
            "user_input": str,           # 用户输入的文本
            "selected_options": list[str],  # 用户选择的选项列表
            "images": list[dict],        # 上传的图片列表
        }

    返回
    ----
    list
        MCP 标准 Content 对象列表，包含 TextContent 和/或 ImageContent：
        - TextContent: {"type": "text", "text": str}
        - ImageContent: {"type": "image", "data": str, "mimeType": str}

    功能
    ----
    将 Web UI 的反馈数据格式转换为 MCP 协议标准格式，供 AI 助手处理。

    处理流程
    --------
    1. **提取基础数据**: 从 response_data 提取 user_input 和 selected_options
    2. **构建文本部分**:
       - 如果有选项被选中，添加 "选择的选项: xxx"
       - 如果有用户输入，添加 "用户输入: xxx"
    3. **处理图片附件**:
       - 遍历 images 列表
       - 验证 base64 数据有效性
       - 创建 ImageContent 对象（纯 base64，不使用 data URI）
       - 添加图片元信息到文本部分（文件名、类型、大小）
    4. **合并文本内容**: 使用 "\n\n" 连接所有文本部分
    5. **添加 TextContent**: 将合并的文本包装为 TextContent 对象
    6. **处理空内容**: 如果没有任何内容，添加默认文本 "用户未提供任何内容"
    7. **返回结果列表**: 先返回 ImageContent，后返回 TextContent（MCP 惯例）

    MCP 标准格式
    ------------
    遵循 Model Context Protocol (MCP) 定义的 Content 对象格式：
    - **TextContent**: {"type": "text", "text": "具体文本内容"}
    - **ImageContent**: {"type": "image", "data": "纯base64字符串", "mimeType": "image/jpeg"}

    图片处理
    ----------
    - **Base64 编码**: 直接使用后端提供的纯 base64 字符串（不是 data URI）
    - **MIME 类型**: 从 content_type 字段获取（默认 "image/jpeg"）
    - **大小计算**: 优先使用 size 字段，否则估算（base64长度 * 3/4）
    - **大小显示**: 自动转换为 B/KB/MB 单位
    - **错误处理**: 单个图片处理失败不影响其他内容

    调试日志
    ----------
    记录详细的调试信息（debug 级别）：
    - 接收到的原始数据类型和内容
    - 解析后的 user_input 和 selected_options
    - 图片数量和处理状态
    - 文本部分的构建过程
    - 最终返回的 Content 对象列表

    异常处理
    ----------
    - 单个图片处理失败: 记录错误并添加"处理失败"文本，继续处理其他图片
    - 整体处理失败: 不会抛出异常，确保至少返回"用户未提供任何内容"

    使用场景
    --------
    - interactive_feedback() MCP 工具函数返回结果前调用
    - 将 Web UI 的 JSON 响应转换为 AI 助手可理解的格式

    注意事项
    --------
    - 图片的 base64 数据可能很大（几百 KB 到几 MB）
    - 返回的列表顺序: ImageContent 在前，TextContent 在后
    - 空内容也会返回列表（包含默认文本），不会返回空列表
    - 为了让 FastMCP/客户端（如 Cursor）正确识别并渲染图片，这里返回的是
      `mcp.types.TextContent` / `mcp.types.ImageContent` 模型实例（而非普通 dict）

    兼容性
    --------
    兼容旧格式的反馈数据：
    - 如果没有 user_input/selected_options 字段，尝试从其他字段提取
    - 如果没有 images 字段，跳过图片处理
    """

    result: list[ContentBlock] = []
    text_parts: list[str] = []

    # 兜底：确保 response_data 是可用字典
    if not isinstance(response_data, dict):
        response_data = {}

    # 调试信息：记录接收到的原始数据
    logger.debug("parse_structured_response 接收到的数据:")
    logger.debug(f"  - 原始数据类型: {type(response_data)}")
    logger.debug(f"  - 原始数据内容: {response_data}")

    # 1. 直接从新格式中获取用户输入和选择的选项
    # 兼容旧格式：interactive_feedback 字段
    legacy_text = response_data.get("interactive_feedback")
    user_input = response_data.get("user_input", "") or ""
    if (not user_input) and isinstance(legacy_text, str) and legacy_text.strip():
        user_input = legacy_text

    selected_options_raw = response_data.get("selected_options", [])
    if isinstance(selected_options_raw, list):
        selected_options = [str(x) for x in selected_options_raw if x is not None]
    else:
        selected_options = []

    # 调试信息：记录解析后的数据
    logger.debug("解析后的数据:")
    logger.debug(
        f"  - user_input: '{user_input}' (类型: {type(user_input)}, 长度: {len(user_input) if isinstance(user_input, str) else 'N/A'})"
    )
    logger.debug(
        f"  - selected_options: {selected_options} (类型: {type(selected_options)}, 长度: {len(selected_options) if isinstance(selected_options, list) else 'N/A'})"
    )
    logger.debug(f"  - images数量: {len(response_data.get('images', []))}")

    # 2. 构建返回的文本内容
    if selected_options:
        text_parts.append(f"选择的选项: {', '.join(selected_options)}")
        logger.debug(f"添加选项文本: '选择的选项: {', '.join(selected_options)}'")

    if user_input:
        text_parts.append(f"用户输入: {user_input}")
        logger.debug(f"添加用户输入文本: '用户输入: {user_input}'")
    else:
        logger.debug("用户输入为空，跳过添加用户输入文本")

    # 3. 处理图片附件 - 使用 MCP 标准协议格式
    images = response_data.get("images", []) or []
    for index, image in enumerate(images):
        if not isinstance(image, dict):
            continue

        try:
            base64_data = image.get("data")
            if not isinstance(base64_data, str) or not base64_data.strip():
                logger.warning(
                    f"图片 {index + 1} 的 data 字段无效: {type(base64_data)}"
                )
                text_parts.append(f"=== 图片 {index + 1} ===\n处理失败: 图片数据无效")
                continue

            base64_data = base64_data.strip()

            # 兼容 data URI（data:image/png;base64,...）
            inferred_mime_type: str | None = None
            if base64_data.startswith("data:") and ";base64," in base64_data:
                header, b64 = base64_data.split(",", 1)
                base64_data = b64.strip()
                # header 形如: data:image/png;base64
                if header.startswith("data:"):
                    inferred_mime_type = header[5:].split(";", 1)[0].strip() or None

            # MIME 类型兼容：content_type / mimeType / mime_type
            content_type = (
                image.get("content_type")
                or image.get("mimeType")
                or image.get("mime_type")
                or inferred_mime_type
                or "image/jpeg"
            )

            # 规范化 MIME 类型（去参数、统一小写、修正常见别名）
            # 参考：chrome-devtools-mcp 的 take_screenshot 返回格式（mimeType + 纯 base64）
            content_type = str(content_type).strip()
            if ";" in content_type:
                content_type = content_type.split(";", 1)[0].strip()
            content_type = content_type.lower()
            if content_type == "image/jpg":
                content_type = "image/jpeg"

            # 兜底：避免后端返回 application/octet-stream 等非图片 MIME，导致 MCP 客户端无法渲染
            if not content_type.startswith("image/"):
                guessed: str | None = None
                try:
                    snippet = base64_data[:256]
                    # base64 必须 4 字节对齐才能解码
                    snippet += "=" * ((4 - len(snippet) % 4) % 4)
                    raw = base64.b64decode(snippet, validate=False)

                    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
                        guessed = "image/png"
                    elif raw.startswith(b"\xff\xd8\xff"):
                        guessed = "image/jpeg"
                    elif raw.startswith(b"GIF87a") or raw.startswith(b"GIF89a"):
                        guessed = "image/gif"
                    elif (
                        raw.startswith(b"RIFF")
                        and len(raw) >= 12
                        and raw[8:12] == b"WEBP"
                    ):
                        guessed = "image/webp"
                    elif raw.startswith(b"BM"):
                        guessed = "image/bmp"
                    elif raw.startswith(b"II*\x00") or raw.startswith(b"MM\x00*"):
                        guessed = "image/tiff"
                    elif raw.startswith(b"\x00\x00\x01\x00"):
                        guessed = "image/x-icon"
                    else:
                        # SVG 可能是文本（UTF-8），做一个轻量兜底判断
                        raw_lower = raw.lstrip().lower()
                        if raw_lower.startswith(b"<svg") or b"<svg" in raw_lower[:200]:
                            guessed = "image/svg+xml"
                except Exception:
                    guessed = None

                content_type = guessed or "image/jpeg"

            result.append(
                ImageContent(
                    type="image",
                    data=base64_data,  # 纯 base64（不是 data URI）
                    mimeType=str(content_type),
                )
            )

            # 添加图片信息到文本中
            filename = image.get("filename", f"image_{index + 1}")
            size = image.get("size", len(base64_data) * 3 // 4)  # base64估算：3/4
            if size < 1024:
                size_str = f"{size} B"
            elif size < 1024 * 1024:
                size_str = f"{size / 1024:.1f} KB"
            else:
                size_str = f"{size / (1024 * 1024):.1f} MB"

            text_parts.append(
                f"=== 图片 {index + 1} ===\n文件名: {filename}\n类型: {content_type}\n大小: {size_str}"
            )
        except Exception as e:
            logger.error(f"处理图片 {index + 1} 时出错: {e}")
            text_parts.append(f"=== 图片 {index + 1} ===\n处理失败: {str(e)}")

    # 4. 添加文本内容（无论如何都返回一个 TextContent，避免返回空列表）
    if text_parts:
        combined_text = "\n\n".join(text_parts)
    else:
        combined_text = "用户未提供任何内容"

    # 追加提示语后缀（保持会话连续性）
    _, prompt_suffix = get_feedback_prompts()
    if prompt_suffix:
        combined_text += prompt_suffix

    result.append(TextContent(type="text", text=combined_text))

    logger.debug("最终返回结果:")
    for i, item in enumerate(result):
        if isinstance(item, TextContent):
            preview = item.text[:100] + ("..." if len(item.text) > 100 else "")
            logger.debug(f"  - [{i}] TextContent: '{preview}'")
        elif isinstance(item, ImageContent):
            logger.debug(
                f"  - [{i}] ImageContent: mimeType={item.mimeType}, data_length={len(item.data)}"
            )
        else:
            logger.debug(f"  - [{i}] 未知类型: {type(item)}")

    return result


def wait_for_feedback(config: WebUIConfig, timeout: int = 300) -> Dict[str, Any]:
    """
    ⚠️ **废弃函数**: 旧架构中等待用户提交反馈（单一内容区轮询）

    功能
    ----
    轮询 /api/config 和 /api/feedback 端点，检测内容状态变化和反馈提交。

    注意
    ----
    - **已废弃**: 新架构使用 wait_for_task_completion() 代替
    - 保留用于向后兼容
    - 基于内容状态变化检测（has_content 标志）
    - 最小超时 300 秒

    参数
    ----
    config : WebUIConfig
        Web UI配置
    timeout : int, optional
        超时时间（秒），默认300秒，最小300秒

    返回
    ----
    Dict[str, str]
        反馈数据字典或 {"error": "错误信息"}

    使用场景
    --------
    旧版本的反馈等待机制，现已被任务队列架构取代。
    """
    # 确保超时时间不小于300秒
    timeout = max(timeout, 300)
    target_host = "localhost" if config.host == "0.0.0.0" else config.host
    config_url = f"http://{target_host}:{config.port}/api/config"
    feedback_url = f"http://{target_host}:{config.port}/api/feedback"

    session = create_http_session(config)
    start_time = time.time()
    check_interval = 2.0  # 检查间隔
    last_progress_time = start_time
    progress_interval = 30.0  # 进度报告间隔

    if timeout == 0:
        logger.info("⏳ 等待用户反馈... (无限等待)")
    else:
        logger.info(f"⏳ 等待用户反馈... (超时: {timeout}秒)")

    # 首先获取当前状态
    last_has_content = True  # 默认假设有内容
    try:
        config_response = session.get(config_url, timeout=5)
        if config_response.status_code == 200:
            config_data = config_response.json()
            last_has_content = config_data.get("has_content", False)
            logger.debug(f"初始内容状态: {last_has_content}")
        else:
            logger.warning(f"获取初始状态失败，状态码: {config_response.status_code}")
    except requests.exceptions.RequestException as e:
        logger.warning(f"获取初始状态失败: {e}")

    consecutive_errors = 0
    max_consecutive_errors = 5

    # 如果timeout为0，则无限循环；否则按时间限制循环
    while timeout == 0 or time.time() - start_time < timeout:
        current_time = time.time()
        elapsed_time = current_time - start_time

        # 定期报告进度
        if current_time - last_progress_time >= progress_interval:
            if timeout == 0:
                logger.info("⏳ 继续等待用户反馈... (无限等待)")
            else:
                remaining_time = timeout - elapsed_time
                logger.info(f"⏳ 继续等待用户反馈... (剩余: {remaining_time:.0f}秒)")
            last_progress_time = current_time

        try:
            # 首先检查是否有反馈结果
            feedback_response = session.get(feedback_url, timeout=5)
            if feedback_response.status_code == 200:
                feedback_data = feedback_response.json()
                logger.debug(f"获取反馈数据: {feedback_data}")
                if feedback_data.get("status") == "success" and feedback_data.get(
                    "feedback"
                ):
                    logger.info("✅ 收到用户反馈")
                    logger.debug(f"返回反馈数据: {feedback_data['feedback']}")
                    return feedback_data["feedback"]

            # 然后检查内容状态变化
            config_response = session.get(config_url, timeout=5)
            if config_response.status_code == 200:
                config_data = config_response.json()
                current_has_content = config_data.get("has_content", False)

                # 如果从有内容变为无内容，说明用户提交了反馈
                if last_has_content and not current_has_content:
                    logger.debug("检测到内容状态变化，尝试获取反馈")
                    logger.debug(
                        f"状态变化: {last_has_content} -> {current_has_content}"
                    )

                    # 再次尝试获取反馈内容
                    feedback_response = session.get(feedback_url, timeout=5)
                    if feedback_response.status_code == 200:
                        feedback_data = feedback_response.json()
                        logger.debug(f"状态变化后获取反馈数据: {feedback_data}")
                        if feedback_data.get(
                            "status"
                        ) == "success" and feedback_data.get("feedback"):
                            logger.info("✅ 收到用户反馈")
                            logger.debug(
                                f"状态变化后返回反馈数据: {feedback_data['feedback']}"
                            )
                            return feedback_data["feedback"]

                    # 如果没有获取到具体反馈内容，返回默认结果
                    logger.info("✅ 收到用户反馈（无具体内容）")
                    logger.debug("返回默认空结果")
                    return {"user_input": "", "selected_options": [], "images": []}

                last_has_content = current_has_content
                consecutive_errors = 0  # 重置错误计数
            else:
                logger.warning(
                    f"获取配置状态失败，状态码: {config_response.status_code}"
                )
                consecutive_errors += 1

        except requests.exceptions.Timeout:
            logger.warning("检查反馈状态超时")
            consecutive_errors += 1
        except requests.exceptions.ConnectionError:
            logger.warning("连接 Web 服务失败")
            consecutive_errors += 1
        except requests.exceptions.RequestException as e:
            logger.warning(f"检查反馈状态时网络错误: {e}")
            consecutive_errors += 1
        except Exception as e:
            logger.error(f"检查反馈状态时出现未知错误: {e}")
            consecutive_errors += 1

        # 如果连续错误过多，可能服务已经停止
        if consecutive_errors >= max_consecutive_errors:
            logger.error(f"连续 {consecutive_errors} 次检查失败，可能服务已停止")
            raise Exception("Web 服务连接失败，请检查服务状态")

        # 如果有错误，缩短等待时间
        sleep_time = check_interval if consecutive_errors == 0 else 1.0

        # 检查是否需要退出
        service_manager = ServiceManager()
        if getattr(service_manager, "_should_exit", False):
            logger.info("收到退出信号，停止等待用户反馈")
            raise KeyboardInterrupt("收到退出信号")

        try:
            time.sleep(sleep_time)
        except KeyboardInterrupt:
            logger.info("等待用户反馈被中断")
            raise

    # 超时处理（只有在设置了超时时间时才会到达这里）
    if timeout > 0:
        logger.error(f"等待用户反馈超时 ({timeout}秒)")
        raise Exception(f"等待用户反馈超时 ({timeout}秒)，请检查用户是否看到了反馈界面")
    else:
        # timeout=0时不应该到达这里，但为了安全起见
        logger.error("无限等待模式异常退出")
        raise Exception("无限等待模式异常退出")


async def wait_for_task_completion(task_id: str, timeout: int = 260) -> Dict[str, Any]:
    """
    通过轮询 HTTP API 等待任务完成（异步版本）

    参数
    ----
    task_id : str
        任务唯一标识符
    timeout : int, optional
        超时时间（秒），默认 260 秒，最小 260 秒（后端最低等待时间）
        【优化】从 300 秒改为 260 秒，预留 40 秒安全余量避免 MCPHub 300 秒硬超时

    返回
    ----
    Dict[str, str]
        任务结果字典：
        - 成功: 返回 task["result"]（包含 user_input、selected_options、images）
        - 超时/任务不存在: {"text": resubmit_prompt}（引导 AI 重新调用工具）

    功能
    ----
    轮询 Web UI 的 /api/tasks/{task_id} 端点，检查任务状态直到完成或超时。
    使用异步等待，不阻塞事件循环，允许并发处理其他 MCP 请求。
    【优化】使用单调时间（time.monotonic()）计算超时，不受系统时间调整影响。

    轮询流程
    --------
    1. 确保超时时间不小于 260 秒（后端最低等待时间）
    2. 获取 Web UI 配置和 API URL
    3. 【优化】使用 time.monotonic() 记录开始时刻
    4. 循环轮询（每 1 秒一次）：
       - 在线程池中发送 GET /api/tasks/{task_id} 请求
       - 检查响应状态码（404=不存在，200=成功）
       - 解析任务状态和结果
       - 如果 status="completed" 且有 result，返回结果
       - 使用 await asyncio.sleep(1) 异步等待，不阻塞事件循环
    5. 超时后**主动返回超时结果**，而不是被 MCPHub 掐断

    API 响应格式
    ------------
    成功响应:
    {
        "success": true,
        "task": {
            "id": str,
            "prompt": str,
            "options": list,
            "status": "pending" | "active" | "completed",
            "result": dict,  # 包含 user_input、selected_options、images
            "created_at": float,
            "completed_at": float
        }
    }

    超时计算
    ----------
    - 最小超时: 260 秒（后端最低等待时间，预留40秒安全余量）
    - 实际超时: max(传入timeout, 260)
    - 【优化】使用 time.monotonic() 单调时间，不受系统时间调整影响
    - 超时后立即返回，不等待当前轮询完成

    异常处理
    ----------
    - requests.exceptions.RequestException: 记录警告并继续轮询（网络波动容错）
    - HTTP 404: 任务不存在，返回 resubmit_prompt 引导重新调用
    - HTTP 非 200: 记录警告并继续轮询（临时错误容错）

    性能考虑
    ----------
    - 轮询间隔: 1 秒（平衡响应性和服务器负载）
    - 请求超时: 2 秒（快速失败）
    - 轮询次数: timeout 秒数（如 260 次）
    - 异步等待不阻塞事件循环，允许并发处理其他请求

    使用场景
    --------
    - interactive_feedback() MCP 工具等待用户反馈
    - launch_feedback_ui() 函数等待用户反馈
    - 任务队列架构的核心等待机制

    注意事项
    --------
    - 任务完成后，Web UI 会从队列中移除任务（可能导致 404）
    - 轮询失败不会立即返回错误，会继续尝试（容错设计）
    - 超时时间应该大于前端倒计时时间（通常为前端 + 40 秒）
    - 返回的 result 字典格式取决于 Web UI 的实现
    - 使用 asyncio.to_thread 在线程池中运行同步 HTTP 请求
    - 【优化】使用单调时间，避免系统时间调整导致的超时判断错误
    """
    # 【优化】确保超时时间不小于 BACKEND_MIN 秒（0表示无限等待，保持不变）
    if timeout > 0:
        timeout = max(timeout, BACKEND_MIN)

    config, _ = get_web_ui_config()
    target_host = "localhost" if config.host == "0.0.0.0" else config.host
    api_url = f"http://{target_host}:{config.port}/api/tasks/{task_id}"

    # 【优化】使用单调时间（monotonic），不受系统时间调整影响
    start_time_monotonic = time.monotonic()
    deadline_monotonic = start_time_monotonic + timeout if timeout > 0 else float("inf")

    if timeout == 0:
        logger.info(f"等待任务完成: {task_id}, 超时时间: 无限等待")
    else:
        logger.info(f"等待任务完成: {task_id}, 超时时间: {timeout}秒（使用单调时间）")

    while timeout == 0 or time.monotonic() < deadline_monotonic:
        try:
            # 在线程池中执行同步 HTTP 请求，不阻塞事件循环
            response = await asyncio.to_thread(requests.get, api_url, timeout=2)

            if response.status_code == 404:
                # 任务不存在（可能已被清理或前端自动提交），引导 AI 重新调用工具
                logger.warning(f"任务不存在: {task_id}，引导重新调用")
                resubmit_prompt, _ = get_feedback_prompts()
                return {"text": resubmit_prompt}

            if response.status_code != 200:
                logger.warning(f"获取任务状态失败: HTTP {response.status_code}")
                await asyncio.sleep(1)  # 异步等待，不阻塞事件循环
                continue

            task_data = response.json()
            if task_data.get("success") and task_data.get("task"):
                task = task_data["task"]

                if task.get("status") == "completed" and task.get("result"):
                    logger.info(f"任务完成: {task_id}")
                    return task["result"]

        except requests.exceptions.RequestException as e:
            logger.warning(f"轮询任务状态失败: {e}")

        await asyncio.sleep(1)  # 异步等待，不阻塞事件循环

    # 【优化】后端主动返回超时结果，而不是被 MCPHub 掐断
    elapsed = time.monotonic() - start_time_monotonic
    logger.error(
        f"任务超时: {task_id}, 等待时间已超过 {elapsed:.1f} 秒（使用单调时间判断）"
    )
    # 返回配置的提示语，引导 AI 重新调用工具
    resubmit_prompt, _ = get_feedback_prompts()
    return {"text": resubmit_prompt}


async def ensure_web_ui_running(config):
    """
    确保 Web UI 服务正在运行，未运行则自动启动（异步版本）

    参数
    ----
    config : WebUIConfig
        Web UI 配置对象

    功能
    ----
    检查 Web UI 服务的健康状态，如果未运行则自动启动。
    提供服务自愈能力，确保 interactive_feedback() 工具始终可用。
    使用异步 I/O，不阻塞事件循环。

    检查流程
    --------
    1. 在线程池中发送 GET /api/health 请求（超时 2 秒）
    2. 如果响应状态码为 200，表示服务已运行，直接返回
    3. 如果请求失败（异常或非 200），判断服务未运行
    4. 在线程池中调用 start_web_service() 启动服务
    5. 异步等待 2 秒确保服务完全启动

    使用场景
    --------
    - interactive_feedback() 工具调用前
    - launch_feedback_ui() 函数调用前（通过 asyncio.run）
    - 确保服务可用性

    注意事项
    --------
    - 健康检查超时设置为 2 秒（快速失败）
    - 所有异常都会被捕获并视为服务未运行
    - 启动后等待 2 秒，可能不足以完全启动（但 start_web_service 内部有更完整的等待逻辑）
    - 不会抛出异常，启动失败由 start_web_service() 处理
    - 使用 asyncio.to_thread 在线程池中运行同步操作，不阻塞事件循环
    """
    try:
        # 在线程池中执行同步 HTTP 请求
        response = await asyncio.to_thread(
            requests.get, f"http://{config.host}:{config.port}/api/health", timeout=2
        )
        if response.status_code == 200:
            logger.debug("Web UI 已经在运行")
            return
    except Exception:
        pass

    logger.info("Web UI 未运行，正在启动...")
    script_dir = os.path.dirname(os.path.abspath(__file__))
    # 在线程池中执行服务启动（因为 start_web_service 可能是同步的）
    await asyncio.to_thread(start_web_service, config, script_dir)
    await asyncio.sleep(2)  # 异步等待，不阻塞事件循环


def launch_feedback_ui(
    summary: str,
    predefined_options: Optional[list[str]] = None,
    task_id: Optional[str] = None,
    timeout: int = 300,
) -> Dict[str, Any]:
    """
    ⚠️ **废弃函数**: 启动反馈界面（旧版 API，请使用 interactive_feedback() MCP 工具代替）

    功能
    ----
    通过 HTTP API 创建反馈任务并等待用户提交。基于任务队列架构。

    注意
    ----
    - **已废弃**: 推荐使用 `interactive_feedback()` MCP 工具
    - 保留用于向后兼容
    - task_id 参数被忽略，系统自动生成
    - 最小超时 300 秒

    参数
    ----
    summary : str
        反馈摘要或问题
    predefined_options : Optional[list[str]], optional
        预定义选项列表
    task_id : Optional[str], optional
        （废弃）任务ID，将被忽略
    timeout : int, optional
        超时时间（秒），默认300秒，最小300秒

    返回
    ----
    Dict[str, str]
        用户反馈结果字典或 {"error": "错误信息"}

    工作流程
    --------
    1. 自动生成唯一 task_id（忽略传入的 task_id 参数）
    2. 验证和清理输入参数
    3. 获取配置
    4. 确保 Web UI 运行
    5. 通过 POST /api/tasks 创建任务
    6. 计算后端超时时间 = max(前端 + 60秒, 传入timeout, 300秒)
    7. 轮询等待任务完成
    8. 返回结果

    异常
    ----
    Exception
        - 参数验证失败
        - 文件未找到
        - 反馈界面启动失败

    使用场景
    --------
    旧版本的 Python API，现已被 MCP 工具架构取代。
    """
    # 确保超时时间不小于300秒（0表示无限等待，保持不变）
    if timeout > 0:
        timeout = max(timeout, 300)
    try:
        import time

        # 自动生成唯一 task_id（使用时间戳+随机数确保唯一性）
        # task_id 参数将被忽略，始终使用自动生成
        cwd = os.getcwd()
        project_name = os.path.basename(cwd) or "task"
        timestamp = int(time.time() * 1000) % 1000000
        random_suffix = random.randint(100, 999)
        task_id = f"{project_name}-{timestamp}-{random_suffix}"

        # 验证输入参数
        cleaned_summary, cleaned_options = validate_input(summary, predefined_options)

        # 获取配置
        config, auto_resubmit_timeout = get_web_ui_config()

        logger.info(
            f"启动反馈界面: {cleaned_summary[:100]}... (自动生成task_id: {task_id})"
        )

        # 确保 Web UI 正在运行（在同步函数中运行异步函数）
        asyncio.run(ensure_web_ui_running(config))

        # 通过 HTTP API 向 web_ui 添加任务
        target_host = "localhost" if config.host == "0.0.0.0" else config.host
        api_url = f"http://{target_host}:{config.port}/api/tasks"

        try:
            response = requests.post(
                api_url,
                json={
                    "task_id": task_id,
                    "prompt": cleaned_summary,
                    "predefined_options": cleaned_options,
                    "auto_resubmit_timeout": auto_resubmit_timeout,
                },
                timeout=5,
            )

            if response.status_code != 200:
                logger.error(f"添加任务失败: HTTP {response.status_code}")
                return {
                    "error": f"添加任务失败: {response.json().get('error', '未知错误')}"
                }

            logger.info(f"任务已通过API添加到队列: {task_id}")

            # 【新增】发送通知（立即触发，不阻塞主流程）
            if NOTIFICATION_AVAILABLE:
                try:
                    # 【关键修复】从配置文件刷新配置，解决跨进程配置不同步问题
                    # Web UI 以子进程方式运行，配置更新只发生在 Web UI 进程中
                    # MCP 服务器进程需要在发送通知前同步最新配置
                    notification_manager.refresh_config_from_file()

                    # 截断消息，避免过长（Bark 有长度限制）
                    notification_message = cleaned_summary[:100]
                    if len(cleaned_summary) > 100:
                        notification_message += "..."

                    # 发送通知（types=None 使用配置的默认类型）
                    event_id = notification_manager.send_notification(
                        title="新的反馈请求",
                        message=notification_message,
                        trigger=NotificationTrigger.IMMEDIATE,
                        types=None,  # 自动根据配置选择（包括 Bark）
                        metadata={"task_id": task_id, "source": "launch_feedback_ui"},
                    )

                    if event_id:
                        logger.debug(
                            f"已为任务 {task_id} 发送通知，事件 ID: {event_id}"
                        )
                    else:
                        logger.debug(f"任务 {task_id} 通知已跳过（通知系统已禁用）")

                except Exception as e:
                    # 通知失败不影响任务创建，仅记录警告
                    logger.warning(f"发送任务通知失败: {e}，任务 {task_id} 已正常创建")
            else:
                logger.debug("通知系统不可用，跳过通知发送")

        except requests.exceptions.RequestException as e:
            logger.error(f"添加任务请求失败: {e}")
            return {"error": f"无法连接到Web UI: {e}"}

        # 【优化】使用统一的超时计算函数
        # timeout=0 表示无限等待模式
        backend_timeout = calculate_backend_timeout(
            auto_resubmit_timeout,
            max_timeout=max(timeout, 0),  # 传入的 timeout 参数作为参考
            infinite_wait=(timeout == 0),
        )
        logger.info(
            f"后端等待时间: {backend_timeout}秒 (前端倒计时: {auto_resubmit_timeout}秒, 传入timeout: {timeout}秒)"
        )
        # 在同步函数中运行异步函数（废弃的 API，保持向后兼容）
        result = asyncio.run(wait_for_task_completion(task_id, timeout=backend_timeout))

        if "error" in result:
            logger.error(f"任务执行失败: {result['error']}")
            return {"error": result["error"]}

        logger.info("用户反馈收集完成")
        return result

    except ValueError as e:
        logger.error(f"输入参数错误: {e}")
        raise Exception(f"参数验证失败: {e}") from e
    except FileNotFoundError as e:
        logger.error(f"文件未找到: {e}")
        raise Exception(f"必要文件缺失: {e}") from e
    except Exception as e:
        logger.error(f"启动反馈界面失败: {e}")
        raise Exception(f"反馈界面启动失败: {e}") from e


@mcp.tool()
async def interactive_feedback(
    message: str = Field(description="The specific question for the user"),
    predefined_options: Optional[list] = Field(
        default=None,
        description="Predefined options for the user to choose from (optional)",
    ),
) -> list:
    """
    MCP 工具：请求用户通过 Web UI 提供交互式反馈

    参数
    ----
    message : str, required
        向用户显示的问题或消息（Markdown 格式支持）
        最大长度: 10000 字符（超出部分自动截断）
    predefined_options : Optional[list], optional
        预定义选项列表，用户可多选或单选
        - 每个选项最大长度: 500 字符
        - 非字符串选项会被自动过滤
        - None 或空列表表示无预定义选项

    返回
    ----
    list
        MCP 标准 Content 对象列表，包含用户反馈：
        - TextContent: {"type": "text", "text": str}
          包含选项选择和用户输入的文本
        - ImageContent: {"type": "image", "data": str, "mimeType": str}
          用户上传的图片（base64 编码）

    示例
    ----
    简单文本反馈:
        interactive_feedback(message="确认删除文件吗？")

    带选项的反馈:
        interactive_feedback(
            message="选择代码风格：",
            predefined_options=["Google", "PEP8", "Airbnb"]
        )

    复杂问题:
        interactive_feedback(
            message=\"\"\"请审查以下更改：
            1. 重构了 ServiceManager 类
            2. 添加了多任务支持
            3. 优化了通知系统

            请选择操作：\"\"\",
            predefined_options=["Approve", "Request Changes", "Reject"]
        )
    """
    try:
        # 使用类型提示，移除运行时检查以避免IDE警告
        predefined_options_list = predefined_options

        # 自动生成唯一 task_id（使用时间戳+随机数确保唯一性）
        import time

        cwd = os.getcwd()
        project_name = os.path.basename(cwd) or "task"
        # 使用毫秒时间戳和随机数的组合，几乎不可能冲突
        timestamp = int(time.time() * 1000) % 1000000  # 取后6位毫秒时间戳
        random_suffix = random.randint(100, 999)
        task_id = f"{project_name}-{timestamp}-{random_suffix}"

        logger.info(f"收到反馈请求: {message[:50]}... (自动生成task_id: {task_id})")

        # 获取配置
        config, auto_resubmit_timeout = get_web_ui_config()

        # 确保 Web UI 正在运行
        await ensure_web_ui_running(config)

        # 通过 HTTP API 添加任务
        target_host = "localhost" if config.host == "0.0.0.0" else config.host
        api_url = f"http://{target_host}:{config.port}/api/tasks"

        try:
            # 在线程池中执行同步 HTTP 请求，不阻塞事件循环
            response = await asyncio.to_thread(
                requests.post,
                api_url,
                json={
                    "task_id": task_id,
                    "prompt": message,
                    "predefined_options": predefined_options_list,
                    "auto_resubmit_timeout": auto_resubmit_timeout,
                },
                timeout=5,
            )

            if response.status_code != 200:
                # 记录详细错误信息到日志
                error_detail = response.json().get("error", "未知错误")
                logger.error(
                    f"添加任务失败: HTTP {response.status_code}, 详情: {error_detail}"
                )
                # 返回配置的提示语，引导 AI 重新调用工具
                resubmit_prompt, _ = get_feedback_prompts()
                return [TextContent(type="text", text=resubmit_prompt)]

            logger.info(f"任务已通过API添加到队列: {task_id}")

            # 【新增】发送通知（立即触发，不阻塞主流程）
            if NOTIFICATION_AVAILABLE:
                try:
                    # 【关键修复】从配置文件刷新配置，解决跨进程配置不同步问题
                    # Web UI 以子进程方式运行，配置更新只发生在 Web UI 进程中
                    # MCP 服务器进程需要在发送通知前同步最新配置
                    notification_manager.refresh_config_from_file()

                    # 截断消息，避免过长（Bark 有长度限制）
                    notification_message = message[:100]
                    if len(message) > 100:
                        notification_message += "..."

                    # 发送通知（types=None 使用配置的默认类型）
                    event_id = notification_manager.send_notification(
                        title="新的反馈请求",
                        message=notification_message,
                        trigger=NotificationTrigger.IMMEDIATE,
                        types=None,  # 自动根据配置选择（包括 Bark）
                        metadata={"task_id": task_id, "source": "interactive_feedback"},
                    )

                    if event_id:
                        logger.debug(
                            f"已为任务 {task_id} 发送通知，事件 ID: {event_id}"
                        )
                    else:
                        logger.debug(f"任务 {task_id} 通知已跳过（通知系统已禁用）")

                except Exception as e:
                    # 通知失败不影响任务创建，仅记录警告
                    logger.warning(f"发送任务通知失败: {e}，任务 {task_id} 已正常创建")
            else:
                logger.debug("通知系统不可用，跳过通知发送")

        except requests.exceptions.RequestException as e:
            # 记录连接失败的详细错误
            logger.error(f"添加任务请求失败，无法连接到 Web UI: {e}")
            # 返回配置的提示语，引导 AI 重新调用工具
            resubmit_prompt, _ = get_feedback_prompts()
            return [TextContent(type="text", text=resubmit_prompt)]

        # 【优化】使用统一的超时计算函数，利用 feedback.timeout 作为上限
        backend_timeout = calculate_backend_timeout(auto_resubmit_timeout)
        logger.info(
            f"后端等待时间: {backend_timeout}秒 (前端倒计时: {auto_resubmit_timeout}秒)"
        )
        result = await wait_for_task_completion(task_id, timeout=backend_timeout)

        if "error" in result:
            # 记录任务执行失败的详细错误
            logger.error(f"任务执行失败: {result['error']}, 任务 ID: {task_id}")
            # 返回配置的提示语，引导 AI 重新调用工具
            resubmit_prompt, _ = get_feedback_prompts()
            return [TextContent(type="text", text=resubmit_prompt)]

        logger.info("反馈请求处理完成")

        # 检查是否有结构化的反馈数据（包含图片）
        if isinstance(result, dict) and "images" in result:
            return parse_structured_response(result)
        else:
            # 兼容旧格式：只有文本反馈
            if isinstance(result, dict):
                # 检查是否是新格式
                if "user_input" in result or "selected_options" in result:
                    return parse_structured_response(result)
                else:
                    # 旧格式 - 使用 MCP 标准 TextContent 格式
                    text_content = result.get("interactive_feedback", str(result))
                    return [TextContent(type="text", text=text_content)]
            else:
                # 简单字符串结果 - 使用 MCP 标准 TextContent 格式
                return [TextContent(type="text", text=str(result))]

    except Exception as e:
        logger.error(f"interactive_feedback 工具执行失败: {e}")
        # 返回配置的提示语，引导 AI 重新调用工具
        resubmit_prompt, _ = get_feedback_prompts()
        return [TextContent(type="text", text=resubmit_prompt)]


class FeedbackServiceContext:
    """
    反馈服务生命周期上下文管理器

    功能概述
    --------
    自动管理反馈服务的启动和清理，使用 Python 的 with 语句确保资源正确释放。
    适用于需要完全控制服务生命周期的场景。

    核心特性
    --------
    1. **自动清理**: 退出上下文时自动清理所有服务进程
    2. **异常安全**: 即使发生异常也确保服务被清理
    3. **配置管理**: 自动加载和保存配置
    4. **日志记录**: 记录初始化、清理和异常信息

    内部状态
    --------
    - service_manager: ServiceManager 实例（单例）
    - config: WebUIConfig 配置对象
    - script_dir: 脚本目录路径
    - auto_resubmit_timeout: 前端自动重新提交超时时间

    使用场景
    --------
    - 测试脚本中临时启动反馈服务
    - 需要精确控制服务生命周期的场景
    - 批量收集多个反馈（一次启动，多次调用）

    注意事项
    --------
    - **现代架构**: 推荐使用 interactive_feedback() MCP 工具代替
    - 本类主要用于向后兼容和特殊场景
    - 不会自动启动服务，需要手动调用 launch_feedback_ui()
    - 退出上下文会清理所有服务进程（包括其他方式启动的）

    线程安全
    --------
    - 通过 ServiceManager 单例保证线程安全
    - 不支持并发使用多个 FeedbackServiceContext 实例
    """

    def __init__(self):
        """
        初始化上下文管理器

        初始化流程
        ----------
        1. 获取全局 ServiceManager 实例（单例）
        2. 初始化配置和脚本目录为 None（延迟加载）

        注意事项
        --------
        - 构造函数不加载配置（延迟到 __enter__ 方法）
        - 不会启动服务（需要手动调用 launch_feedback_ui）
        """
        self.service_manager = ServiceManager()
        self.config = None
        self.script_dir = None

    def __enter__(self):
        """
        进入上下文，初始化配置

        功能
        ----
        加载 Web UI 配置和脚本目录，准备启动服务。

        初始化流程
        ----------
        1. 调用 get_web_ui_config() 加载配置
        2. 获取当前脚本的目录路径
        3. 保存配置和脚本目录到实例变量
        4. 记录初始化成功日志
        5. 返回 self（用于 with 语句）

        返回
        ----
        FeedbackServiceContext
            上下文管理器实例本身

        异常处理
        ----------
        配置加载失败会抛出异常并中断上下文进入。

        使用场景
        --------
        自动被 with 语句调用，无需手动调用。
        """
        try:
            self.config, self.auto_resubmit_timeout = get_web_ui_config()
            self.script_dir = os.path.dirname(os.path.abspath(__file__))
            logger.info(
                f"反馈服务上下文已初始化，自动重调超时: {self.auto_resubmit_timeout}秒"
            )
            return self
        except Exception as e:
            logger.error(f"初始化反馈服务上下文失败: {e}")
            raise

    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        退出上下文，清理所有服务进程

        参数
        ----
        exc_type : type | None
            异常类型（如果有异常）
        exc_val : Exception | None
            异常实例（如果有异常）
        exc_tb : traceback | None
            异常堆栈（未使用）

        功能
        ----
        无论正常退出还是异常退出，都确保所有服务进程被清理。

        清理流程
        --------
        1. 调用 service_manager.cleanup_all() 清理所有进程
        2. 根据退出类型记录不同级别的日志：
           - KeyboardInterrupt: info 级别
           - 其他异常: error 级别（包含异常详情）
           - 正常退出: info 级别
        3. 捕获清理过程中的异常并记录

        返回
        ----
        None
            不抑制异常，异常会继续传播

        异常处理
        ----------
        清理过程中的异常会被捕获并记录，但不会抑制原始异常。

        注意事项
        --------
        - 退出上下文会清理所有服务进程（不仅限于本上下文启动的）
        - 异常信息会被记录但不会抑制
        - 确保清理函数一定被调用（即使发生异常）
        """
        del exc_tb
        try:
            self.service_manager.cleanup_all()
            if exc_type is KeyboardInterrupt:
                logger.info("收到中断信号，服务已清理")
            elif exc_type is not None:
                logger.error(f"异常退出，服务已清理: {exc_type.__name__}: {exc_val}")
            else:
                logger.info("正常退出，服务已清理")
        except Exception as e:
            logger.error(f"清理服务时出错: {e}")

    def launch_feedback_ui(
        self,
        summary: str,
        predefined_options: Optional[list[str]] = None,
        task_id: Optional[str] = None,
        timeout: int = 300,
    ) -> Dict[str, Any]:
        """
        在上下文中启动反馈界面

        功能
        ----
        委托给全局 launch_feedback_ui() 函数处理。

        参数
        ----
        summary : str
            反馈摘要
        predefined_options : Optional[list[str]], optional
            预定义选项列表
        task_id : Optional[str], optional
            任务ID（废弃参数，会被忽略）
        timeout : int, optional
            超时时间（秒），默认300秒

        返回
        ----
        Dict[str, str]
            用户反馈结果

        注意事项
        --------
        - 这是一个简单的委托方法
        - 实际逻辑在全局 launch_feedback_ui() 函数中
        - 不使用上下文的配置（函数内部重新加载配置）
        """
        return launch_feedback_ui(summary, predefined_options, task_id, timeout)


def cleanup_services():
    """
    清理所有启动的服务进程

    功能
    ----
    获取全局 ServiceManager 实例并调用 cleanup_all() 清理所有已注册的服务进程。

    使用场景
    --------
    - main() 函数捕获 KeyboardInterrupt 时
    - main() 函数捕获其他异常时
    - 程序退出前的清理操作

    异常处理
    ----------
    捕获所有异常并记录错误，确保清理过程不会中断程序退出。

    注意事项
    --------
    - 通过 ServiceManager 单例模式访问进程注册表
    - 清理失败不会抛出异常，仅记录错误日志
    """
    try:
        service_manager = ServiceManager()
        service_manager.cleanup_all()
        logger.info("服务清理完成")
    except Exception as e:
        logger.error(f"服务清理失败: {e}")


def main():
    """
    MCP 服务器主入口函数

    功能
    ----
    配置日志级别并启动 FastMCP 服务器，使用 stdio 传输协议与 AI 助手通信。
    包含自动重试机制，提高服务稳定性。

    运行流程
    --------
    1. 降低 mcp 和 fastmcp 日志级别为 WARNING（避免污染 stdio）
    2. 调用 mcp.run(transport="stdio") 启动 MCP 服务器
    3. 服务器持续运行，监听 stdio 上的 MCP 协议消息
    4. 捕获中断信号（Ctrl+C）或异常，执行清理
    5. 如果发生异常，最多重试 3 次，每次间隔 1 秒

    异常处理
    ----------
    - KeyboardInterrupt: 捕获 Ctrl+C，清理服务后正常退出
    - 其他异常: 记录错误，清理服务，尝试重启（最多 3 次）
    - 重试失败: 达到最大重试次数后以状态码 1 退出

    重试策略
    ----------
    - 最大重试次数: 3 次
    - 重试间隔: 1 秒
    - 每次重试前清理所有服务进程
    - 记录完整的错误堆栈和重试历史

    日志配置
    ----------
    - mcp 日志级别: WARNING
    - fastmcp 日志级别: WARNING
    - 避免 DEBUG/INFO 日志污染 stdio 通信通道

    传输协议
    ----------
    使用 stdio 传输，MCP 消息通过标准输入/输出进行交换：
    - stdin: 接收来自 AI 助手的请求
    - stdout: 发送 MCP 响应（必须保持纯净）
    - stderr: 日志输出

    使用场景
    --------
    - 直接运行: python server.py
    - 作为 MCP 服务器被 AI 助手调用

    注意事项
    --------
    - 必须确保 stdout 仅用于 MCP 协议通信
    - 所有日志输出重定向到 stderr
    - 服务进程由 ServiceManager 管理，退出时自动清理
    - 重试机制可以自动恢复临时性错误
    """
    # 配置日志级别（在重试循环外，只配置一次）
    mcp_logger = _stdlib_logging.getLogger("mcp")
    mcp_logger.setLevel(_stdlib_logging.WARNING)

    fastmcp_logger = _stdlib_logging.getLogger("fastmcp")
    fastmcp_logger.setLevel(_stdlib_logging.WARNING)

    # 重试配置
    max_retries = 3
    retry_count = 0

    while retry_count < max_retries:
        try:
            if retry_count > 0:
                logger.info(f"尝试重新启动 MCP 服务器 (第 {retry_count + 1} 次)")

            mcp.run(transport="stdio", show_banner=False)

            # 如果 mcp.run() 正常退出（不抛异常），跳出循环
            logger.info("MCP 服务器正常退出")
            break

        except KeyboardInterrupt:
            logger.info("收到中断信号，正在关闭服务器")
            cleanup_services()
            break  # 用户中断，不重试

        except Exception as e:
            retry_count += 1
            logger.error(
                f"MCP 服务器运行时错误 (第 {retry_count}/{max_retries} 次): {e}",
                exc_info=True,
            )

            # 清理服务进程
            cleanup_services()

            if retry_count < max_retries:
                logger.warning("将在 1 秒后尝试重启服务器...")
                time.sleep(1)
            else:
                logger.error(f"达到最大重试次数 ({max_retries})，服务退出")
                sys.exit(1)


if __name__ == "__main__":
    main()
