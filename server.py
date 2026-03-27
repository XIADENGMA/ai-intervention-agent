"""MCP 服务器核心 - interactive_feedback 工具、Web UI 管理、多任务队列、通知集成。"""

import asyncio
import atexit
import io
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, cast

import httpx
from fastmcp import FastMCP
from mcp.types import TextContent
from pydantic import Field

from config_manager import get_config
from config_utils import get_compat_config
from enhanced_logging import EnhancedLogger
from exceptions import (
    ServiceConnectionError,
    ServiceTimeoutError,
    ServiceUnavailableError,
    ValidationError,
)
from server_config import (  # noqa: F401 — 向后兼容：外部模块和测试通过 `from server import X` 访问
    AUTO_RESUBMIT_TIMEOUT_DEFAULT,
    AUTO_RESUBMIT_TIMEOUT_MAX,
    AUTO_RESUBMIT_TIMEOUT_MIN,
    BACKEND_BUFFER,
    BACKEND_MIN,
    FEEDBACK_TIMEOUT_DEFAULT,
    FEEDBACK_TIMEOUT_MAX,
    FEEDBACK_TIMEOUT_MIN,
    MAX_MESSAGE_LENGTH,
    MAX_OPTION_LENGTH,
    PROMPT_MAX_LENGTH,
    PROMPT_SUFFIX_DEFAULT,
    RESUBMIT_PROMPT_DEFAULT,
    FeedbackConfig,
    WebUIConfig,
    _append_prompt_suffix,
    _format_file_size,
    _generate_task_id,
    _guess_mime_type_from_data,
    _make_resubmit_response,
    _process_image,
    calculate_backend_timeout,
    get_feedback_config,
    get_feedback_prompts,
    get_target_host,
    parse_structured_response,
    validate_input,
)
from task_queue import TaskQueue

# ===============================
# 【性能优化】全局缓存
# ===============================
# httpx 异步客户端（模块级单例，支持连接池复用）
_async_client: httpx.AsyncClient | None = None
_sync_client: httpx.Client | None = None

# 配置缓存：避免频繁读取配置文件
_config_cache: Dict[str, Any] = {
    "config": None,
    "timestamp": 0.0,
    "ttl": 10.0,
}  # 10秒 TTL
_config_cache_lock = threading.Lock()

# ===============================
# 【配置热更新】配置变更回调：清空 server.py 内部缓存
# ===============================
# 说明：
# - 配置文件被外部修改并由 ConfigManager 自动 reload 后，会触发回调
# - Web UI 子进程在页面内保存配置时，也会触发 ConfigManager 的回调（同进程内）
# - 这里清空缓存，让后续调用尽快读取到最新配置
_config_callbacks_registered: bool = False
_config_callbacks_lock = threading.Lock()


def _invalidate_runtime_caches_on_config_change() -> None:
    """配置变更回调：清空 server.py 的配置缓存，并关闭 httpx 客户端以便下次重建"""
    global _async_client, _sync_client
    try:
        with _config_cache_lock:
            _config_cache["config"] = None
            _config_cache["timestamp"] = 0
    except Exception:
        pass

    try:
        if _sync_client is not None and not _sync_client.is_closed:
            _sync_client.close()
        _sync_client = None
        _async_client = None
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

mcp: FastMCP = FastMCP("AI Intervention Agent MCP")
logger = EnhancedLogger(__name__)

# TaskQueue 主要由 Web UI 进程使用（web_ui.py 会导入 server.get_task_queue）。
# 为避免在 MCP 服务器进程里无意义地启动后台清理线程，这里采用懒加载 + 线程安全初始化。
_global_task_queue: TaskQueue | None = None
_global_task_queue_lock = threading.Lock()


def get_task_queue() -> TaskQueue:
    """获取全局任务队列实例

    返回:
        TaskQueue: 全局任务队列实例
    """
    global _global_task_queue
    if _global_task_queue is None:
        with _global_task_queue_lock:
            if _global_task_queue is None:
                _global_task_queue = TaskQueue(max_tasks=10)
    assert _global_task_queue is not None
    return _global_task_queue


def _shutdown_global_task_queue() -> None:
    """进程退出时尽量停止 TaskQueue 后台线程（幂等）。"""
    try:
        if _global_task_queue is not None:
            _global_task_queue.stop_cleanup()
    except Exception:
        # 退出阶段不再抛异常
        pass


atexit.register(_shutdown_global_task_queue)


try:
    from notification_manager import NotificationTrigger, notification_manager
    from notification_providers import initialize_notification_system

    NOTIFICATION_AVAILABLE = True
    logger.info("通知系统已导入")
except ImportError as e:
    logger.warning(f"通知系统不可用: {e}", exc_info=True)
    NOTIFICATION_AVAILABLE = False


class ServiceManager:
    """服务进程生命周期管理器（线程安全单例）"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        """创建或返回单例实例（双重检查锁）"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """初始化服务管理器（仅首次创建时执行）"""
        if not getattr(self, "_initialized", False):
            with self._lock:
                if not getattr(self, "_initialized", False):
                    self._processes = {}
                    self._cleanup_registered = False
                    self._should_exit = False
                    self._initialized = True
                    self._register_cleanup()

    def _register_cleanup(self):
        """注册 atexit 清理函数和 SIGINT/SIGTERM 信号处理器"""
        if not self._cleanup_registered:
            atexit.register(self.cleanup_all, shutdown_notification_manager=True)
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
        """信号处理器：清理服务并设置退出标志（仅主线程）"""
        del frame
        logger.info(f"收到信号 {signum}，正在清理服务...")
        try:
            self.cleanup_all(shutdown_notification_manager=True)
        except Exception as e:
            logger.error(f"清理服务时出错: {e}", exc_info=True)

        import threading

        if threading.current_thread() is threading.main_thread():
            self._should_exit = True
        else:
            logger.info("非主线程收到信号，已清理服务但不强制退出")

    def register_process(
        self, name: str, process: subprocess.Popen, config: "WebUIConfig"
    ) -> None:
        """注册服务进程到管理器（线程安全）"""
        with self._lock:
            self._processes[name] = {
                "process": process,
                "config": config,
                "start_time": time.time(),
            }
            logger.info(f"已注册服务进程: {name} (PID: {process.pid})")

    def unregister_process(self, name: str) -> None:
        """从管理器注销服务进程（仅移除记录，不终止进程）"""
        with self._lock:
            if name in self._processes:
                del self._processes[name]
                logger.debug(f"已注销服务进程: {name}")

    def get_process(self, name: str) -> Optional[subprocess.Popen]:
        """获取指定服务的进程对象，不存在返回 None"""
        with self._lock:
            process_info = self._processes.get(name)
            return process_info["process"] if process_info else None

    def is_process_running(self, name: str) -> bool:
        """检查服务进程是否正在运行"""
        process = self.get_process(name)
        if process is None:
            return False

        try:
            return process.poll() is None
        except Exception:
            return False

    def terminate_process(self, name: str, timeout: float = 5.0) -> bool:
        """终止服务进程：优雅关闭 -> 强制终止 -> 资源清理 -> 端口释放"""
        with self._lock:
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
            logger.error(f"终止进程 {name} 时出错: {e}", exc_info=True)
            try:
                self._cleanup_process_resources(name, process_info)
            except Exception as cleanup_error:
                logger.error(f"清理进程资源时出错: {cleanup_error}", exc_info=True)
            return False
        finally:
            self.unregister_process(name)

    def _graceful_shutdown(
        self, process: subprocess.Popen, name: str, timeout: float
    ) -> bool:
        """发送 SIGTERM 并等待进程退出"""
        try:
            process.terminate()
            process.wait(timeout=timeout)
            logger.info(f"服务进程 {name} 已关闭")
            return True
        except subprocess.TimeoutExpired:
            logger.warning(f"服务进程 {name} 关闭超时")
            return False
        except Exception as e:
            logger.error(f"关闭进程 {name} 失败: {e}", exc_info=True)
            return False

    def _force_shutdown(self, process: subprocess.Popen, name: str) -> bool:
        """发送 SIGKILL 强制终止进程"""
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
            logger.error(f"强制终止进程 {name} 失败: {e}", exc_info=True)
            return False

    def _cleanup_process_resources(self, name: str, process_info: dict):
        """关闭进程的 stdin/stdout/stderr 文件句柄"""
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
            logger.error(f"清理进程 {name} 资源时出错: {e}", exc_info=True)

    def _wait_for_port_release(self, host: str, port: int, timeout: float = 10.0):
        """等待端口被释放（每 0.5 秒检查一次，最长 timeout 秒）"""
        start_time = time.time()
        while time.time() - start_time < timeout:
            if not is_web_service_running(host, port, timeout=1.0):
                logger.debug(f"端口 {host}:{port} 已释放")
                return
            time.sleep(0.5)
        logger.warning(f"端口 {host}:{port} 在 {timeout}秒内未释放")

    def cleanup_all(self, shutdown_notification_manager: bool = True) -> None:
        """清理所有已注册的服务进程（幂等操作，容错设计）"""
        with self._lock:
            processes_to_cleanup = list(self._processes.items())

        if not processes_to_cleanup:
            logger.debug("没有需要清理的进程")
        else:
            logger.info("开始清理所有服务进程...")
        cleanup_errors = []

        for name, _ in processes_to_cleanup:
            try:
                logger.debug(f"正在清理进程: {name}")
                success = self.terminate_process(name)
                if not success:
                    cleanup_errors.append(f"进程 {name} 清理失败")
            except Exception as e:
                error_msg = f"清理进程 {name} 时出错: {e}"
                logger.error(error_msg, exc_info=True)
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
                        logger.error(f"强制移除进程记录失败 {name}: {e}", exc_info=True)

        if cleanup_errors:
            logger.warning(f"服务进程清理完成，但有 {len(cleanup_errors)} 个错误:")
            for error in cleanup_errors:
                logger.warning(f"  - {error}")
        else:
            logger.info("所有服务进程清理完成")

        # 仅在“确定要退出进程”的清理路径里关闭通知线程池；重启场景需保留可用性
        if shutdown_notification_manager and NOTIFICATION_AVAILABLE:
            try:
                notification_manager.shutdown()
                logger.info("通知管理器线程池已关闭")
            except Exception as e:
                logger.warning(f"关闭通知管理器失败: {e}", exc_info=True)

    def get_status(self) -> Dict[str, Dict]:
        """获取所有服务的运行状态（pid, running, start_time, config）"""
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


def get_web_ui_config() -> Tuple[WebUIConfig, int]:
    """加载 Web UI 配置（带 10s TTL 缓存），返回 (WebUIConfig, auto_resubmit_timeout)
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
            return cast(Tuple[WebUIConfig, int], _config_cache["config"])

    # 缓存过期或不存在，重新加载配置
    try:
        config_mgr = get_config()
        web_ui_config = config_mgr.get_section("web_ui")
        feedback_config = config_mgr.get_section("feedback")
        network_security_config = config_mgr.get_section("network_security")

        host = str(
            network_security_config.get(
                "bind_interface", web_ui_config.get("host", "127.0.0.1")
            )
        )
        port = int(web_ui_config.get("port", 8080))

        # 【重构】使用 get_compat_config 简化向后兼容配置读取
        auto_resubmit_timeout = int(
            get_compat_config(
                feedback_config, "frontend_countdown", "auto_resubmit_timeout", 240
            )
        )
        max_retries = int(
            get_compat_config(web_ui_config, "http_max_retries", "max_retries", 3)
        )
        retry_delay = float(
            get_compat_config(web_ui_config, "http_retry_delay", "retry_delay", 1.0)
        )
        http_timeout = int(
            get_compat_config(web_ui_config, "http_request_timeout", "timeout", 30)
        )

        config = WebUIConfig(
            host=host,
            port=port,
            timeout=http_timeout,
            max_retries=max_retries,
            retry_delay=retry_delay,
        )

        # 【性能优化】更新缓存
        result: Tuple[WebUIConfig, int] = (config, auto_resubmit_timeout)
        with _config_cache_lock:
            _config_cache["config"] = result
            _config_cache["timestamp"] = current_time

        logger.info(
            f"Web UI 配置加载成功: {host}:{port}, 自动重调超时: {auto_resubmit_timeout}秒"
        )
        return result
    except (ValueError, TypeError) as e:
        logger.error(f"配置参数错误: {e}", exc_info=True)
        raise ValueError(f"Web UI 配置错误: {e}") from e
    except Exception as e:
        logger.error(f"配置文件加载失败: {e}", exc_info=True)
        raise ValueError(f"Web UI 配置加载失败: {e}") from e


def get_async_client(config: WebUIConfig) -> httpx.AsyncClient:
    """获取（或创建）模块级异步 HTTP 客户端，支持连接池复用和自动重试。"""
    global _async_client
    if _async_client is None or _async_client.is_closed:
        transport = httpx.AsyncHTTPTransport(retries=config.max_retries)
        _async_client = httpx.AsyncClient(
            transport=transport,
            timeout=httpx.Timeout(config.timeout, connect=5.0),
        )
    return _async_client


def get_sync_client(config: WebUIConfig) -> httpx.Client:
    """获取（或创建）模块级同步 HTTP 客户端，用于同步代码路径。"""
    global _sync_client
    if _sync_client is None or _sync_client.is_closed:
        transport = httpx.HTTPTransport(retries=config.max_retries)
        _sync_client = httpx.Client(
            transport=transport,
            timeout=httpx.Timeout(config.timeout, connect=5.0),
        )
    return _sync_client


def create_http_session(config: WebUIConfig) -> httpx.Client:
    """向后兼容：返回同步 httpx.Client（替代旧 requests.Session）。"""
    return get_sync_client(config)


def is_web_service_running(host: str, port: int, timeout: float = 2.0) -> bool:
    """TCP 端口检查，验证服务是否在监听"""
    try:
        if not (1 <= port <= 65535):
            logger.error(f"无效端口号: {port}")
            return False

        target_host = get_target_host(host)

        # 同时兼容 IPv4/IPv6/hostname（例如 ::1 / localhost）
        try:
            addrinfos = socket.getaddrinfo(
                target_host,
                port,
                type=socket.SOCK_STREAM,
            )
        except socket.gaierror as e:
            logger.error(f"主机名解析失败 {host}: {e}", exc_info=True)
            return False

        for family, socktype, proto, _canonname, sockaddr in addrinfos:
            try:
                with socket.socket(family, socktype, proto) as sock:
                    sock.settimeout(timeout)
                    if sock.connect_ex(sockaddr) == 0:
                        logger.debug(f"Web 服务运行中: {target_host}:{port}")
                        return True
            except OSError:
                # 尝试下一个地址（例如 IPv6 失败后回落 IPv4）
                continue

        logger.debug(f"Web 服务未运行: {target_host}:{port}")
        return False
    except Exception as e:
        logger.error(f"检查服务状态时出错: {e}", exc_info=True)
        return False


def health_check_service(config: WebUIConfig) -> bool:
    """HTTP /api/health 检查，验证服务是否正常"""
    if not is_web_service_running(config.host, config.port):
        return False

    try:
        session = create_http_session(config)
        target_host = get_target_host(config.host)
        health_url = f"http://{target_host}:{config.port}/api/health"

        response = session.get(health_url, timeout=5)
        is_healthy = bool(response.status_code == 200)

        if is_healthy:
            logger.debug("服务健康检查通过")
        else:
            logger.warning(f"服务健康检查失败，状态码: {response.status_code}")

        return is_healthy

    except httpx.HTTPError as e:
        logger.error(f"健康检查请求失败: {e}", exc_info=True)
        return False
    except Exception as e:
        logger.error(f"健康检查时出现未知错误: {e}", exc_info=True)
        return False


def start_web_service(config: WebUIConfig, script_dir: Path) -> None:
    """启动 Flask Web UI 子进程，含健康检查"""
    web_ui_path = script_dir / "web_ui.py"
    service_manager = ServiceManager()
    service_name = f"web_ui_{config.host}_{config.port}"

    if NOTIFICATION_AVAILABLE:
        try:
            initialize_notification_system(notification_manager.get_config())
            logger.info("通知系统初始化完成")
        except Exception as e:
            logger.warning(f"通知系统初始化失败: {e}", exc_info=True)

    # 验证 web_ui.py 文件是否存在
    if not web_ui_path.exists():
        raise FileNotFoundError(f"Web UI 脚本不存在: {web_ui_path}")

    # 检查服务是否已经在运行
    if service_manager.is_process_running(service_name) or health_check_service(config):
        logger.info(
            f"Web 服务已在运行: http://{get_target_host(config.host)}:{config.port}"
        )
        return

    # 启动Web服务，初始为空内容
    args = [
        sys.executable,
        "-u",
        str(web_ui_path),
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
        logger.error(f"Python 解释器或脚本文件未找到: {e}", exc_info=True)
        raise ServiceUnavailableError(
            f"无法启动 Web 服务，文件未找到: {e}", code="file_not_found"
        ) from e
    except PermissionError as e:
        logger.error(f"权限不足，无法启动服务: {e}", exc_info=True)
        raise ServiceUnavailableError(
            f"权限不足，无法启动 Web 服务: {e}", code="permission_denied"
        ) from e
    except Exception as e:
        logger.error(f"启动服务进程时出错: {e}", exc_info=True)
        if health_check_service(config):
            logger.info("服务已经在运行，继续使用现有服务")
            return
        else:
            raise ServiceUnavailableError(
                f"启动 Web 服务失败: {e}", code="start_failed"
            ) from e

    # 等待服务启动并进行健康检查
    # 【资源管理】如果最终启动失败，需主动终止刚启动的子进程，避免残留后台进程占用端口
    max_wait = 15  # 最多等待15秒
    check_interval = 0.5  # 每0.5秒检查一次

    try:
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
            return

        raise ServiceTimeoutError(
            f"Web 服务启动超时 ({max_wait}秒)，请检查端口 {config.port} 是否被占用",
            code="start_timeout",
        )
    except Exception:
        # 启动阶段失败：尽力清理本次启动的子进程与端口占用
        try:
            service_manager.terminate_process(service_name)
        except Exception as cleanup_error:
            logger.error(
                f"启动失败后清理 Web 服务进程失败: {cleanup_error}", exc_info=True
            )
        raise


def update_web_content(
    summary: str,
    predefined_options: Optional[list[str]],
    task_id: Optional[str],
    auto_resubmit_timeout: int,
    config: WebUIConfig,
) -> None:
    """POST /api/update 更新 Web UI 内容"""
    # 验证输入
    cleaned_summary, cleaned_options = validate_input(summary, predefined_options)

    target_host = get_target_host(config.host)
    url = f"http://{target_host}:{config.port}/api/update"

    data = {
        "prompt": cleaned_summary,
        "predefined_options": cleaned_options,
        "task_id": task_id,
        "auto_resubmit_timeout": auto_resubmit_timeout,
    }

    session = create_http_session(config)

    try:
        logger.debug(
            f"更新 Web 内容: {url} (task_id: {task_id}, prompt_len: {len(cleaned_summary)}, options: {len(cleaned_options or [])})"
        )
        response = session.post(url, json=data, timeout=config.timeout)

        if response.status_code == 200:
            try:
                result = response.json()
            except ValueError:
                logger.error("更新响应不是有效的 JSON 格式（200）")
                raise ServiceConnectionError(
                    "更新内容失败：响应不是有效的 JSON", code="invalid_json"
                ) from None

            if not isinstance(result, dict):
                logger.error(f"更新响应类型异常（200）: {type(result)}")
                raise ServiceConnectionError(
                    "更新内容失败：响应格式异常", code="invalid_response"
                ) from None

            if result.get("status") != "success":
                err = result.get("error") or "unknown_error"
                msg = result.get("message") or ""
                logger.error(
                    f"更新响应 status!=success（200）: error={err} msg_len={len(str(msg))} task_id={task_id}"
                )
                raise ServiceConnectionError(
                    f"更新内容失败：{err}{(': ' + str(msg)) if msg else ''}",
                    code="update_rejected",
                ) from None

            logger.info(
                f"内容已更新 (task_id: {task_id}, prompt_len: {len(cleaned_summary)}, options: {len(cleaned_options or [])})"
            )

        elif response.status_code == 400:
            err_text = (response.text or "").strip()
            try:
                result = response.json()
                if isinstance(result, dict):
                    err = result.get("error") or "bad_request"
                    msg = result.get("message") or ""
                    raise ValidationError(
                        f"更新内容失败：请求参数不合法（{err}）{(': ' + str(msg)) if msg else ''}",
                        code="bad_request",
                    ) from None
            except ValueError:
                pass
            logger.error(f"更新请求参数错误: {err_text[:500]}")
            raise ValidationError(
                f"更新内容失败：请求参数不合法: {err_text[:500]}", code="bad_request"
            ) from None
        elif response.status_code == 429:
            retry_after = response.headers.get("Retry-After", "").strip()
            err_text = (response.text or "").strip()
            logger.warning(
                f"更新请求被限流（429） task_id={task_id} retry_after={retry_after or '-'}"
            )
            hint = f"（Retry-After={retry_after}）" if retry_after else ""
            raise ServiceConnectionError(
                f"更新内容失败：请求被限流，请稍后重试{hint}{(': ' + err_text[:200]) if err_text else ''}",
                code="rate_limited",
            ) from None
        elif response.status_code == 404:
            logger.error("更新 API 端点不存在，可能服务未正确启动")
            raise ServiceUnavailableError(
                "更新接口不可用（/api/update 未找到）。请确认 Web UI 服务已启动且版本匹配。",
                code="endpoint_not_found",
            )
        elif 500 <= response.status_code <= 599:
            err_text = (response.text or "").strip()
            logger.error(f"更新内容失败（服务端错误）HTTP {response.status_code}")
            raise ServiceConnectionError(
                f"更新内容失败：服务端错误（HTTP {response.status_code}）{(': ' + err_text[:200]) if err_text else ''}",
                code="server_error",
            ) from None
        else:
            err_text = (response.text or "").strip()
            logger.error(f"更新内容失败，HTTP 状态码: {response.status_code}")
            raise ServiceConnectionError(
                f"更新内容失败，状态码: {response.status_code}{(': ' + err_text[:200]) if err_text else ''}",
                code="unexpected_status",
            ) from None

    except httpx.TimeoutException:
        logger.error(f"更新内容超时 ({config.timeout}秒)", exc_info=True)
        raise ServiceTimeoutError(
            "更新内容超时，请检查网络连接或稍后重试", code="timeout"
        ) from None
    except httpx.ConnectError:
        logger.error(f"无法连接到 Web 服务: {url}", exc_info=True)
        raise ServiceUnavailableError(
            "无法连接到 Web UI 服务，请确认服务正在运行，并检查地址/端口（如 web_ui.host/web_ui.port 或 VS Code 的 serverUrl 设置）。",
            code="connection_refused",
        ) from None
    except httpx.HTTPError as e:
        logger.error(f"更新内容时网络请求失败: {e}", exc_info=True)
        raise ServiceConnectionError(f"更新内容失败: {e}", code="request_failed") from e
    except (
        ServiceConnectionError,
        ServiceTimeoutError,
        ServiceUnavailableError,
        ValidationError,
    ):
        raise
    except Exception as e:
        logger.error(f"更新内容时出现未知错误: {e}", exc_info=True)
        raise ServiceConnectionError(f"更新 Web 内容失败: {e}", code="unknown") from e


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
            "task_id": str,
            "prompt": str,
            "predefined_options": list,
            "status": "pending" | "active" | "completed",
            "result": dict,  # 包含 user_input、selected_options、images
            "created_at": str,  # ISO 8601
            "auto_resubmit_timeout": int
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
    - httpx.HTTPError: 记录警告并继续轮询（网络波动容错）
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
    - 使用 httpx.AsyncClient 原生异步 HTTP 请求
    - 【优化】使用单调时间，避免系统时间调整导致的超时判断错误
    """
    # 【优化】确保超时时间不小于 BACKEND_MIN 秒（0表示无限等待，保持不变）
    if timeout > 0:
        timeout = max(timeout, BACKEND_MIN)

    config, _ = get_web_ui_config()
    target_host = get_target_host(config.host)
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
            config_tuple = get_web_ui_config()
            client = get_async_client(config_tuple[0])
            response = await client.get(api_url, timeout=2)

            if response.status_code == 404:
                # 任务不存在（可能已被清理或前端自动提交），引导 AI 重新调用工具
                logger.warning(f"任务不存在: {task_id}，引导重新调用")
                return _make_resubmit_response(as_mcp=False)

            if response.status_code != 200:
                logger.warning(f"获取任务状态失败: HTTP {response.status_code}")
                await asyncio.sleep(1)  # 异步等待，不阻塞事件循环
                continue

            try:
                task_data = response.json()
            except ValueError as e:
                # 服务端可能在异常情况下返回 HTML/纯文本；这里降级为“继续轮询”
                logger.warning(f"任务状态响应不是有效 JSON: {e}", exc_info=True)
                await asyncio.sleep(1)
                continue

            if not isinstance(task_data, dict):
                logger.warning(
                    f"任务状态响应类型异常: {type(task_data)}，已忽略并继续轮询"
                )
                await asyncio.sleep(1)
                continue

            if task_data.get("success") and task_data.get("task"):
                task = task_data["task"]
                if isinstance(task, dict):
                    if task.get("status") == "completed" and task.get("result"):
                        logger.info(f"任务完成: {task_id}")
                        return cast(Dict[str, Any], task["result"])

        except httpx.HTTPError as e:
            logger.warning(f"轮询任务状态失败: {e}", exc_info=True)

        await asyncio.sleep(1)  # 异步等待，不阻塞事件循环

    # 【优化】后端主动返回超时结果，而不是被 MCPHub 掐断
    elapsed = time.monotonic() - start_time_monotonic
    logger.error(
        f"任务超时: {task_id}, 等待时间已超过 {elapsed:.1f} 秒（使用单调时间判断）"
    )
    # 返回配置的提示语，引导 AI 重新调用工具
    return _make_resubmit_response(as_mcp=False)


async def ensure_web_ui_running(config: WebUIConfig) -> None:
    """检查并自动启动 Web UI 服务（异步）"""
    try:
        target_host = get_target_host(config.host)
        client = get_async_client(config)
        response = await client.get(
            f"http://{target_host}:{config.port}/api/health",
            timeout=2,
        )
        if response.status_code == 200:
            logger.debug("Web UI 已经在运行")
            return
    except Exception as e:
        logger.debug(f"Web UI 健康检查失败，将尝试启动: {e}", exc_info=True)

    logger.info("Web UI 未运行，正在启动...")
    script_dir = Path(__file__).resolve().parent
    await asyncio.to_thread(start_web_service, config, script_dir)
    await asyncio.sleep(2)


def launch_feedback_ui(
    summary: str,
    predefined_options: Optional[list[str]] = None,
    task_id: Optional[str] = None,
    timeout: int = 300,
) -> Dict[str, Any]:
    """废弃：旧版 Python API，推荐使用 interactive_feedback() MCP 工具"""
    # 确保超时时间不小于300秒（0表示无限等待，保持不变）
    if timeout > 0:
        timeout = max(timeout, 300)
    try:
        # 自动生成唯一 task_id（task_id 参数将被忽略，始终使用自动生成）
        task_id = _generate_task_id()

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
        target_host = get_target_host(config.host)
        api_url = f"http://{target_host}:{config.port}/api/tasks"

        try:
            client = get_sync_client(config)
            response = client.post(
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
                error_detail = "未知错误"
                try:
                    payload = response.json()
                    if isinstance(payload, dict):
                        error_detail = str(payload.get("error", error_detail))
                    else:
                        error_detail = str(payload)
                except ValueError:
                    try:
                        if response.text:
                            error_detail = response.text[:200]
                    except Exception:
                        pass
                logger.error(
                    f"添加任务失败: HTTP {response.status_code}, 详情: {error_detail}"
                )
                return {
                    "error": f"添加任务失败: {error_detail}",
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
                        title="新的交互反馈请求",
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
                    logger.warning(
                        f"发送任务通知失败: {e}，任务 {task_id} 已正常创建",
                        exc_info=True,
                    )
            else:
                logger.debug("通知系统不可用，跳过通知发送")

        except httpx.HTTPError as e:
            logger.error(f"添加任务请求失败: {e}", exc_info=True)
            return {
                "error": f"无法连接到 Web UI：{e}。请确认 Web UI 服务已启动，并检查地址/端口配置（如 web_ui.host/web_ui.port 或 VS Code 的 serverUrl）。"
            }

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
        logger.error(f"输入参数错误: {e}", exc_info=True)
        raise ValidationError(f"参数验证失败: {e}", code="invalid_params") from e
    except FileNotFoundError as e:
        logger.error(f"文件未找到: {e}", exc_info=True)
        raise ServiceUnavailableError(
            f"必要文件缺失: {e}", code="file_not_found"
        ) from e
    except (
        ServiceConnectionError,
        ServiceTimeoutError,
        ServiceUnavailableError,
        ValidationError,
    ):
        raise
    except Exception as e:
        logger.error(f"启动反馈界面失败: {e}", exc_info=True)
        raise ServiceUnavailableError(
            f"反馈界面启动失败: {e}", code="start_failed"
        ) from e


@mcp.tool()
async def interactive_feedback(
    message: str = Field(description="向用户展示的具体问题/提示（支持 Markdown）"),
    predefined_options: Optional[list] = Field(
        default=None,
        description="可选的预定义选项列表，供用户单选/多选",
    ),
) -> list:
    """
    MCP 工具：请求用户通过 Web UI 提供交互反馈

    参数
    ----
    message : str, 必填
        向用户显示的问题或消息（Markdown 格式支持）
        最大长度: 10000 字符（超出部分自动截断）
    predefined_options : Optional[list], 可选
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
        # 输入清理：截断过长内容，过滤非法选项（对齐工具契约/避免后端 400）
        cleaned_message, cleaned_options = validate_input(message, predefined_options)
        predefined_options_list = cleaned_options

        # 自动生成唯一 task_id（避免极端并发下碰撞）
        task_id = _generate_task_id()

        logger.info(
            f"收到反馈请求: {cleaned_message[:50]}... (自动生成task_id: {task_id})"
        )

        # 获取配置
        config, auto_resubmit_timeout = get_web_ui_config()

        # 确保 Web UI 正在运行
        await ensure_web_ui_running(config)

        # 通过 HTTP API 添加任务
        target_host = get_target_host(config.host)
        api_url = f"http://{target_host}:{config.port}/api/tasks"

        try:
            client = get_async_client(config)
            response = await client.post(
                api_url,
                json={
                    "task_id": task_id,
                    "prompt": cleaned_message,
                    "predefined_options": predefined_options_list,
                    "auto_resubmit_timeout": auto_resubmit_timeout,
                },
                timeout=5,
            )

            if response.status_code != 200:
                # 记录详细错误信息到日志
                error_detail = "未知错误"
                try:
                    payload = response.json()
                    if isinstance(payload, dict):
                        error_detail = str(payload.get("error", error_detail))
                    else:
                        error_detail = str(payload)
                except ValueError as e:
                    logger.warning(
                        f"添加任务失败响应不是有效 JSON: {e}",
                        exc_info=True,
                    )
                    try:
                        if response.text:
                            error_detail = response.text[:200]
                    except Exception:
                        # response.text 读取失败不应影响主流程
                        pass
                logger.error(
                    f"添加任务失败: HTTP {response.status_code}, 详情: {error_detail}"
                )
                # 返回配置的提示语，引导 AI 重新调用工具
                return _make_resubmit_response()

            logger.info(f"任务已通过API添加到队列: {task_id}")

            # 【新增】发送通知（立即触发，不阻塞主流程）
            if NOTIFICATION_AVAILABLE:
                try:
                    # 【关键修复】从配置文件刷新配置，解决跨进程配置不同步问题
                    # Web UI 以子进程方式运行，配置更新只发生在 Web UI 进程中
                    # MCP 服务器进程需要在发送通知前同步最新配置
                    notification_manager.refresh_config_from_file()

                    # 截断消息，避免过长（Bark 有长度限制）
                    notification_message = cleaned_message[:100]
                    if len(cleaned_message) > 100:
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
                    logger.warning(
                        f"发送任务通知失败: {e}，任务 {task_id} 已正常创建",
                        exc_info=True,
                    )
            else:
                logger.debug("通知系统不可用，跳过通知发送")

        except httpx.HTTPError as e:
            logger.error(f"添加任务请求失败，无法连接到 Web UI: {e}", exc_info=True)
            # 返回配置的提示语，引导 AI 重新调用工具
            return _make_resubmit_response()

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
            return _make_resubmit_response()

        logger.info("反馈请求处理完成")

        # 解析返回：兼容新旧格式 + 兜底处理 {"text": "..."} 降级返回
        if isinstance(result, dict):
            # wait_for_task_completion 的降级返回（超时/404）：{"text": "..."}
            if set(result.keys()) == {"text"} and isinstance(result.get("text"), str):
                return [TextContent(type="text", text=str(result["text"]))]

            # 新格式（结构化 JSON，可能含 images）
            if (
                "images" in result
                or "user_input" in result
                or "selected_options" in result
            ):
                return parse_structured_response(result)

            # 旧格式：只有文本反馈
            legacy = result.get("interactive_feedback")
            if isinstance(legacy, str) and legacy.strip():
                return [TextContent(type="text", text=_append_prompt_suffix(legacy))]

            # 最后兜底：尽量取 text 字段，否则转字符串
            fallback = (
                result.get("text")
                if isinstance(result.get("text"), str)
                else str(result)
            )
            return [TextContent(type="text", text=_append_prompt_suffix(str(fallback)))]

        # 简单字符串结果
        return [TextContent(type="text", text=_append_prompt_suffix(str(result)))]

    except Exception as e:
        logger.error(f"interactive_feedback 工具执行失败: {e}", exc_info=True)
        # 返回配置的提示语，引导 AI 重新调用工具
        return _make_resubmit_response()


class FeedbackServiceContext:
    """反馈服务上下文管理器 - 自动管理服务启动和清理"""

    def __init__(self):
        """初始化，延迟加载配置"""
        self.service_manager = ServiceManager()
        self.config = None
        self.script_dir = None

    def __enter__(self):
        """加载配置并返回 self"""
        try:
            self.config, self.auto_resubmit_timeout = get_web_ui_config()
            self.script_dir = Path(__file__).resolve().parent
            logger.info(
                f"反馈服务上下文已初始化，自动重调超时: {self.auto_resubmit_timeout}秒"
            )
            return self
        except Exception as e:
            logger.error(f"初始化反馈服务上下文失败: {e}", exc_info=True)
            raise

    def __exit__(self, exc_type, exc_val, exc_tb):
        """清理所有服务进程
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
            # 上下文退出不等同于进程退出：仅清理子进程/端口等资源，保留通知线程池可用性
            self.service_manager.cleanup_all(shutdown_notification_manager=False)
            if exc_type is KeyboardInterrupt:
                logger.info("收到中断信号，服务已清理")
            elif exc_type is not None:
                logger.error(f"异常退出，服务已清理: {exc_type.__name__}: {exc_val}")
            else:
                logger.info("正常退出，服务已清理")
        except Exception as e:
            logger.error(f"清理服务时出错: {e}", exc_info=True)

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


def cleanup_services(shutdown_notification_manager: bool = True) -> None:
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
    global _sync_client, _async_client
    try:
        if _sync_client is not None and not _sync_client.is_closed:
            _sync_client.close()
    except Exception:
        pass
    _sync_client = None
    _async_client = None

    try:
        service_manager = ServiceManager()
        service_manager.cleanup_all(
            shutdown_notification_manager=shutdown_notification_manager
        )
        logger.info("服务清理完成")
    except Exception as e:
        logger.error(f"服务清理失败: {e}", exc_info=True)


def main() -> None:
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

            if retry_count < max_retries:
                # 仅清理子进程/端口等资源，保留通知线程池，便于同进程重启
                cleanup_services(shutdown_notification_manager=False)
                logger.warning("将在 1 秒后尝试重启服务器...")
                time.sleep(1)
            else:
                # 达到最大重试次数：准备退出进程，做全量清理
                cleanup_services(shutdown_notification_manager=True)
                logger.error(f"达到最大重试次数 ({max_retries})，服务退出")
                sys.exit(1)


if __name__ == "__main__":
    main()
