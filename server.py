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
from typing import Dict, Optional, Tuple

import requests
from fastmcp import FastMCP
from fastmcp.utilities.types import Image
from pydantic import Field
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config_manager import get_config
from enhanced_logging import EnhancedLogger
from task_queue import TaskQueue

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
    from rich.console import Console

    _devnull = io.StringIO()

    class SilentConsole(Console):
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

    rich_console_module.Console = SilentConsole
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
    from notification_manager import notification_manager
    from notification_providers import initialize_notification_system

    NOTIFICATION_AVAILABLE = True
    logger.info("通知系统已导入")
except ImportError as e:
    logger.warning(f"通知系统不可用: {e}")
    NOTIFICATION_AVAILABLE = False


class ServiceManager:
    """服务管理器 - 单例模式管理所有启动的服务进程"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if not getattr(self, "_initialized", False):
            with self._lock:
                if not getattr(self, "_initialized", False):
                    self._processes = {}
                    self._cleanup_registered = False
                    self._should_exit = False
                    self._initialized = True
                    self._register_cleanup()

    def _register_cleanup(self):
        """注册清理函数和信号处理器"""
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
        """信号处理器

        Args:
            signum: 信号编号
            frame: 当前栈帧
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
        """注册服务进程

        Args:
            name: 服务名称
            process: 进程对象
            config: Web UI 配置
        """
        with self._lock:
            self._processes[name] = {
                "process": process,
                "config": config,
                "start_time": time.time(),
            }
            logger.info(f"已注册服务进程: {name} (PID: {process.pid})")

    def unregister_process(self, name: str):
        """注销服务进程

        Args:
            name: 服务名称
        """
        with self._lock:
            if name in self._processes:
                del self._processes[name]
                logger.debug(f"已注销服务进程: {name}")

    def get_process(self, name: str) -> Optional[subprocess.Popen]:
        """获取服务进程

        Args:
            name: 服务名称

        Returns:
            Optional[subprocess.Popen]: 进程对象，不存在则返回 None
        """
        with self._lock:
            process_info = self._processes.get(name)
            return process_info["process"] if process_info else None

    def is_process_running(self, name: str) -> bool:
        """检查进程是否在运行

        Args:
            name: 服务名称

        Returns:
            bool: 进程是否运行中
        """
        process = self.get_process(name)
        if process is None:
            return False

        try:
            return process.poll() is None
        except Exception:
            return False

    def terminate_process(self, name: str, timeout: float = 5.0) -> bool:
        """终止进程并清理资源

        使用分级终止策略：优雅关闭 -> 强制终止 -> 资源清理

        Args:
            name: 服务名称
            timeout: 优雅关闭超时时间（秒）

        Returns:
            bool: 是否成功终止
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
        """优雅关闭进程

        Args:
            process: 进程对象
            name: 服务名称
            timeout: 超时时间（秒）

        Returns:
            bool: 是否成功关闭
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
        """强制终止进程

        Args:
            process: 进程对象
            name: 服务名称

        Returns:
            bool: 是否成功终止
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
        """清理进程相关资源

        Args:
            name: 服务名称
            process_info: 进程信息字典
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
        """等待端口释放

        Args:
            host: 主机地址
            port: 端口号
            timeout: 超时时间（秒）
        """
        start_time = time.time()
        while time.time() - start_time < timeout:
            if not is_web_service_running(host, port, timeout=1.0):
                logger.debug(f"端口 {host}:{port} 已释放")
                return
            time.sleep(0.5)
        logger.warning(f"端口 {host}:{port} 在 {timeout}秒内未释放")

    def cleanup_all(self):
        """清理所有服务进程，确保完全清理资源"""
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

    def get_status(self) -> Dict[str, Dict]:
        """获取所有服务状态

        Returns:
            Dict[str, Dict]: 服务状态字典，键为服务名，值为状态信息
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
    """Web UI 配置类

    Attributes:
        host: 绑定的主机地址
        port: 端口号
        timeout: 超时时间（秒）
        max_retries: 最大重试次数
        retry_delay: 重试延迟（秒）
    """

    host: str
    port: int
    timeout: int = 30
    max_retries: int = 3
    retry_delay: float = 1.0

    def __post_init__(self):
        """验证配置参数"""
        if not (1 <= self.port <= 65535):
            raise ValueError(f"端口号必须在 1-65535 范围内，当前值: {self.port}")
        if self.timeout <= 0:
            raise ValueError(f"超时时间必须大于 0，当前值: {self.timeout}")
        if self.max_retries < 0:
            raise ValueError(f"重试次数不能为负数，当前值: {self.max_retries}")


def get_web_ui_config() -> WebUIConfig:
    """获取 Web UI 配置

    Returns:
        Tuple[WebUIConfig, int]: 配置对象和自动重调超时时间

    Raises:
        ValueError: 配置参数错误或加载失败
    """
    try:
        config_mgr = get_config()
        web_ui_config = config_mgr.get_section("web_ui")
        feedback_config = config_mgr.get_section("feedback")
        network_security_config = config_mgr.get_section("network_security")

        host = network_security_config.get(
            "bind_interface", web_ui_config.get("host", "127.0.0.1")
        )
        port = web_ui_config.get("port", 8080)
        timeout = feedback_config.get("timeout", 300)
        auto_resubmit_timeout = feedback_config.get("auto_resubmit_timeout", 290)
        max_retries = web_ui_config.get("max_retries", 3)
        retry_delay = web_ui_config.get("retry_delay", 1.0)

        config = WebUIConfig(
            host=host,
            port=port,
            timeout=timeout,
            max_retries=max_retries,
            retry_delay=retry_delay,
        )
        logger.info(
            f"Web UI 配置加载成功: {host}:{port}, 自动重调超时: {auto_resubmit_timeout}秒"
        )
        return config, auto_resubmit_timeout
    except (ValueError, TypeError) as e:
        logger.error(f"配置参数错误: {e}")
        raise ValueError(f"Web UI 配置错误: {e}")
    except Exception as e:
        logger.error(f"配置文件加载失败: {e}")
        raise ValueError(f"Web UI 配置加载失败: {e}")


def validate_input(
    prompt: str, predefined_options: Optional[list] = None
) -> Tuple[str, list]:
    """验证和清理输入参数

    Args:
        prompt: 提示文本
        predefined_options: 预定义选项列表

    Returns:
        Tuple[str, list]: 清理后的提示文本和选项列表

    Raises:
        ValueError: prompt 类型错误
    """
    try:
        cleaned_prompt = prompt.strip()
    except AttributeError:
        raise ValueError("prompt 必须是字符串类型")
    if len(cleaned_prompt) > 10000:
        logger.warning(f"prompt 长度过长 ({len(cleaned_prompt)} 字符)，将被截断")
        cleaned_prompt = cleaned_prompt[:10000] + "..."

    cleaned_options = []
    if predefined_options:
        for option in predefined_options:
            if not isinstance(option, str):
                logger.warning(f"跳过非字符串选项: {option}")
                continue
            cleaned_option = option.strip()
            if cleaned_option and len(cleaned_option) <= 500:
                cleaned_options.append(cleaned_option)
            elif len(cleaned_option) > 500:
                logger.warning(f"选项过长被截断: {cleaned_option[:50]}...")
                cleaned_options.append(cleaned_option[:500] + "...")

    return cleaned_prompt, cleaned_options


def create_http_session(config: WebUIConfig) -> requests.Session:
    """创建配置了重试机制的 HTTP 会话

    Args:
        config: Web UI 配置

    Returns:
        requests.Session: 配置好的会话对象
    """
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
    session.timeout = config.timeout

    return session


def is_web_service_running(host: str, port: int, timeout: float = 2.0) -> bool:
    """检查 Web 服务是否正在运行

    Args:
        host: 主机地址
        port: 端口号
        timeout: 连接超时时间（秒）

    Returns:
        bool: 服务是否运行中
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
    """健康检查，验证服务是否正常响应

    Args:
        config: Web UI 配置

    Returns:
        bool: 服务是否健康
    """
    if not is_web_service_running(config.host, config.port):
        return False

    try:
        session = create_http_session(config)
        target_host = "localhost" if config.host == "0.0.0.0" else config.host
        health_url = f"http://{target_host}:{config.port}/api/config"

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
    """启动 Web 服务

    启动时清理所有残留任务，确保服务处于"无有效内容"状态

    Args:
        config: Web UI 配置
        script_dir: 脚本目录路径
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
        raise Exception(f"无法启动 Web 服务，文件未找到: {e}")
    except PermissionError as e:
        logger.error(f"权限不足，无法启动服务: {e}")
        raise Exception(f"权限不足，无法启动 Web 服务: {e}")
    except Exception as e:
        logger.error(f"启动服务进程时出错: {e}")
        # 如果启动失败，再次检查服务是否已经在运行
        if health_check_service(config):
            logger.info("服务已经在运行，继续使用现有服务")
            return
        else:
            raise Exception(f"启动 Web 服务失败: {e}")

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
    """更新Web服务的内容"""
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
        raise Exception("更新内容超时，请检查网络连接")
    except requests.exceptions.ConnectionError:
        logger.error(f"无法连接到 Web 服务: {url}")
        raise Exception("无法连接到 Web 服务，请确认服务正在运行")
    except requests.exceptions.RequestException as e:
        logger.error(f"更新内容时网络请求失败: {e}")
        raise Exception(f"更新内容失败: {e}")
    except Exception as e:
        logger.error(f"更新内容时出现未知错误: {e}")
        raise Exception(f"更新 Web 内容失败: {e}")


def parse_structured_response(response_data):
    """解析结构化的反馈数据，返回适合MCP的Content对象列表"""

    result = []
    text_parts = []

    # 调试信息：记录接收到的原始数据
    logger.debug("parse_structured_response 接收到的数据:")
    logger.debug(f"  - 原始数据类型: {type(response_data)}")
    logger.debug(f"  - 原始数据内容: {response_data}")

    # 1. 直接从新格式中获取用户输入和选择的选项
    user_input = response_data.get("user_input", "")
    selected_options = response_data.get("selected_options", [])

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

    # 3. 处理图片附件 - 使用 FastMCP 的 Image 类型
    for index, image in enumerate(response_data.get("images", [])):
        if isinstance(image, dict) and image.get("data"):
            try:
                # 解码 base64 数据
                image_data = base64.b64decode(image["data"])

                # 确定图片格式
                content_type = image.get("content_type", "image/jpeg")
                if content_type == "image/jpeg":
                    format_name = "jpeg"
                elif content_type == "image/png":
                    format_name = "png"
                elif content_type == "image/gif":
                    format_name = "gif"
                elif content_type == "image/webp":
                    format_name = "webp"
                else:
                    format_name = "jpeg"  # 默认格式

                # 创建 FastMCP Image 对象
                image_obj = Image(data=image_data, format=format_name)
                result.append(image_obj)

                # 添加图片信息到文本中
                filename = image.get("filename", f"image_{index + 1}")
                size = image.get("size", len(image_data))

                # 计算图片大小显示
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

    # 4. 添加文本内容
    logger.debug("准备添加文本内容:")
    logger.debug(f"  - text_parts: {text_parts}")
    logger.debug(f"  - text_parts长度: {len(text_parts)}")

    if text_parts:
        combined_text = "\n\n".join(text_parts)
        result.append(combined_text)
        logger.debug(f"添加合并文本: '{combined_text}'")
    else:
        logger.debug("text_parts为空，不添加文本内容")

    # 5. 如果没有任何内容，检查是否真的没有用户输入
    if not result:
        logger.debug("result为空，检查是否需要添加默认内容")
        # 检查是否有用户输入或选择的选项
        if user_input or selected_options:
            # 有内容但没有添加到result中，这是一个bug，应该添加文本内容
            if text_parts:
                combined_text = "\n\n".join(text_parts)
                result.append(combined_text)
                logger.debug(f"补充添加文本内容: '{combined_text}'")
            else:
                result.append("用户未提供任何内容")
                logger.debug("添加默认内容: '用户未提供任何内容'")
        else:
            result.append("用户未提供任何内容")
            logger.debug("添加默认内容: '用户未提供任何内容'")
    else:
        logger.debug(f"result不为空，包含 {len(result)} 个元素")

    logger.debug("最终返回结果:")
    for i, item in enumerate(result):
        if isinstance(item, str):
            logger.debug(
                f"  - [{i}] 文本: '{item[:100]}{'...' if len(item) > 100 else ''}'"
            )
        else:
            logger.debug(f"  - [{i}] 对象: {type(item)}")

    return result


def wait_for_feedback(config: WebUIConfig, timeout: int = 300) -> Dict[str, str]:
    """等待用户提交反馈"""
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


def wait_for_task_completion(task_id: str, timeout: int = 300) -> Dict[str, str]:
    """
    等待任务完成（通过HTTP API轮询）

    Args:
        task_id: 任务ID
        timeout: 超时时间（秒）

    Returns:
        Dict[str, str]: 任务结果
    """
    config, _ = get_web_ui_config()
    target_host = "localhost" if config.host == "0.0.0.0" else config.host
    api_url = f"http://{target_host}:{config.port}/api/tasks/{task_id}"

    start_time = time.time()
    logger.info(f"等待任务完成: {task_id}, 超时时间: {timeout}秒")

    while time.time() - start_time < timeout:
        try:
            response = requests.get(api_url, timeout=2)

            if response.status_code == 404:
                logger.warning(f"任务不存在: {task_id}")
                return {"error": "任务不存在"}

            if response.status_code != 200:
                logger.warning(f"获取任务状态失败: HTTP {response.status_code}")
                time.sleep(1)
                continue

            task_data = response.json()
            if task_data.get("success") and task_data.get("task"):
                task = task_data["task"]

                if task.get("status") == "completed" and task.get("result"):
                    logger.info(f"任务完成: {task_id}")
                    return task["result"]

        except requests.exceptions.RequestException as e:
            logger.warning(f"轮询任务状态失败: {e}")

        time.sleep(1)  # 每秒检查一次

    logger.warning(f"任务超时: {task_id}")
    return {"error": "任务超时"}


def ensure_web_ui_running(config):
    """确保 Web UI 正在运行，未运行则启动

    Args:
        config: Web UI 配置对象
    """
    try:
        response = requests.get(
            f"http://{config.host}:{config.port}/api/health", timeout=2
        )
        if response.status_code == 200:
            logger.debug("Web UI 已经在运行")
            return
    except Exception:
        pass

    logger.info("Web UI 未运行，正在启动...")
    script_dir = os.path.dirname(os.path.abspath(__file__))
    start_web_service(config, script_dir)
    time.sleep(2)


def launch_feedback_ui(
    summary: str,
    predefined_options: Optional[list[str]] = None,
    task_id: Optional[str] = None,
    timeout: int = 300,
) -> Dict[str, str]:
    """启动反馈界面，使用 TaskQueue 支持多任务并发

    Args:
        summary: 反馈摘要
        predefined_options: 预定义选项列表
        task_id: 任务ID，未提供则自动生成
        timeout: 超时时间（秒）

    Returns:
        Dict[str, str]: 用户反馈结果

    Raises:
        TimeoutError: 等待反馈超时
        ValueError: 参数验证失败
    """
    try:
        import os
        import random

        # 如果未提供 task_id，自动生成
        if not task_id:
            cwd = os.getcwd()
            project_name = os.path.basename(cwd)
            random_suffix = random.randint(1000, 9999)
            if project_name:
                task_id = f"{project_name}-{random_suffix}"
            else:
                task_id = f"default-{random_suffix}"

        # 验证输入参数
        cleaned_summary, cleaned_options = validate_input(summary, predefined_options)

        # 获取配置
        config, auto_resubmit_timeout = get_web_ui_config()

        logger.info(f"启动反馈界面: {cleaned_summary[:100]}... (task_id: {task_id})")

        # 确保 Web UI 正在运行
        ensure_web_ui_running(config)

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

        except requests.exceptions.RequestException as e:
            logger.error(f"添加任务请求失败: {e}")
            return {"error": f"无法连接到Web UI: {e}"}

        # 等待任务完成
        result = wait_for_task_completion(task_id, timeout=timeout)

        if "error" in result:
            logger.error(f"任务执行失败: {result['error']}")
            return {"error": result["error"]}

        logger.info("用户反馈收集完成")
        return result

    except ValueError as e:
        logger.error(f"输入参数错误: {e}")
        raise Exception(f"参数验证失败: {e}")
    except FileNotFoundError as e:
        logger.error(f"文件未找到: {e}")
        raise Exception(f"必要文件缺失: {e}")
    except Exception as e:
        logger.error(f"启动反馈界面失败: {e}")
        raise Exception(f"反馈界面启动失败: {e}")


@mcp.tool()
def interactive_feedback(
    message: str = Field(description="The specific question for the user"),
    predefined_options: Optional[list] = Field(
        default=None,
        description="Predefined options for the user to choose from (optional)",
    ),
    task_id: Optional[str] = Field(
        default=None,
        description="Task identifier to distinguish different tasks. If not provided, will auto-generate a unique ID based on project name. Format: alphanumeric + hyphens + underscores only, must be unique.",
    ),
) -> list:
    """Request interactive feedback from the user

    This tool creates an interactive feedback task in the Web UI (default: http://localhost:8081).
    Users can provide text input, select predefined options, and optionally upload images.

    Args:
        message: 向用户显示的问题或消息 (required)
        predefined_options: 可选的预定义选项列表 (optional, can be multi-selected)
        task_id: 任务标识符，用于区分不同任务 (required, auto-generated if not provided)
            - Format requirements: alphanumeric characters, hyphens (-), underscores (_)
            - Must be unique across all active tasks
            - Auto-generated format: "{project_name}-{random_4digits}"
            - Example: "my-project-1234" or "custom-task-001"

    Returns:
        包含用户反馈的列表，可能包含文本、选项和图片数据

    Raises:
        Exception: 当反馈收集失败时（如任务队列已满、任务ID重复、Web UI未响应等）

    Examples:
        interactive_feedback(
            message="Review the changes:",
            predefined_options=["Approve", "Request Changes", "Reject"],
            task_id="code-review-0001"
        )
    """
    try:
        # 使用类型提示，移除运行时检查以避免IDE警告
        predefined_options_list = predefined_options

        # 如果没有提供 task_id，则尝试自动生成
        if not task_id:
            # 尝试从当前工作目录获取项目名称
            cwd = os.getcwd()
            project_name = os.path.basename(cwd)
            random_suffix = random.randint(1000, 9999)
            if project_name:
                task_id = f"{project_name}-{random_suffix}"
            else:
                task_id = f"default-{random_suffix}"

        logger.info(f"收到反馈请求: {message[:50]}... (task_id: {task_id})")

        # 获取配置
        config, auto_resubmit_timeout = get_web_ui_config()

        # 确保 Web UI 正在运行
        ensure_web_ui_running(config)

        # 通过 HTTP API 添加任务
        target_host = "localhost" if config.host == "0.0.0.0" else config.host
        api_url = f"http://{target_host}:{config.port}/api/tasks"

        try:
            response = requests.post(
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
                logger.error(f"添加任务失败: HTTP {response.status_code}")
                return [f"添加任务失败: {response.json().get('error', '未知错误')}"]

            logger.info(f"任务已通过API添加到队列: {task_id}")

        except requests.exceptions.RequestException as e:
            logger.error(f"添加任务请求失败: {e}")
            return [f"无法连接到Web UI: {e}"]

        # 等待任务完成
        result = wait_for_task_completion(task_id, timeout=300)

        if "error" in result:
            logger.error(f"任务执行失败: {result['error']}")
            return [result["error"]]

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
                    # 旧格式
                    text_content = result.get("interactive_feedback", str(result))
                    return [text_content]
            else:
                return [str(result)]

    except Exception as e:
        logger.error(f"interactive_feedback 工具执行失败: {e}")
        # 返回错误信息而不是抛出异常，以便 MCP 客户端能够处理
        return [f"反馈收集失败: {str(e)}"]


class FeedbackServiceContext:
    """反馈服务上下文管理器

    用于管理反馈服务的生命周期，确保服务正确启动和清理
    """

    def __init__(self):
        self.service_manager = ServiceManager()
        self.config = None
        self.script_dir = None

    def __enter__(self):
        """进入上下文，初始化服务"""
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
        """退出上下文，清理服务"""
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
    ) -> Dict[str, str]:
        """在上下文中启动反馈界面

        Args:
            summary: 反馈摘要
            predefined_options: 预定义选项列表
            task_id: 任务ID
            timeout: 超时时间（秒）

        Returns:
            Dict[str, str]: 用户反馈结果
        """
        return launch_feedback_ui(summary, predefined_options, task_id, timeout)


def cleanup_services():
    """清理所有服务进程"""
    try:
        service_manager = ServiceManager()
        service_manager.cleanup_all()
        logger.info("服务清理完成")
    except Exception as e:
        logger.error(f"服务清理失败: {e}")


def main():
    """MCP 服务器主入口"""
    try:
        mcp_logger = _stdlib_logging.getLogger("mcp")
        mcp_logger.setLevel(_stdlib_logging.WARNING)

        fastmcp_logger = _stdlib_logging.getLogger("fastmcp")
        fastmcp_logger.setLevel(_stdlib_logging.WARNING)

        mcp.run(transport="stdio")
    except KeyboardInterrupt:
        logger.info("收到中断信号，正在关闭服务器")
        cleanup_services()
    except Exception as e:
        logger.error(f"服务器启动失败: {e}")
        cleanup_services()
        sys.exit(1)


if __name__ == "__main__":
    main()
