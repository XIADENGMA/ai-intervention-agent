import atexit
import base64
import os
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

# 使用增强的日志系统 - 解决重复输出和级别错误问题
from enhanced_logging import EnhancedLogger

mcp = FastMCP("AI Intervention Agent MCP")

# 创建增强日志实例
logger = EnhancedLogger(__name__)

# 导入通知系统
try:
    from notification_manager import (
        NotificationTrigger,
        notification_manager,
    )
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
        # 🔒 线程安全的初始化过程
        if not getattr(self, "_initialized", False):
            with self._lock:
                # 再次检查，防止竞态条件
                if not getattr(self, "_initialized", False):
                    self._processes = {}
                    self._cleanup_registered = False
                    self._should_exit = False  # 退出标志
                    self._initialized = True
                    self._register_cleanup()

    def _register_cleanup(self):
        """注册清理函数"""
        if not self._cleanup_registered:
            atexit.register(self.cleanup_all)
            # 只在主线程中注册信号处理器
            try:
                if hasattr(signal, "SIGINT"):
                    signal.signal(signal.SIGINT, self._signal_handler)
                if hasattr(signal, "SIGTERM"):
                    signal.signal(signal.SIGTERM, self._signal_handler)
                logger.debug("服务管理器信号处理器已注册")
            except ValueError as e:
                # 如果不在主线程中，信号处理器注册会失败，这是正常的
                logger.debug(f"信号处理器注册跳过（非主线程）: {e}")
            self._cleanup_registered = True
            logger.debug("服务管理器清理机制已注册")

    def _signal_handler(self, signum, frame):
        """信号处理器 - 兼容MCP异步架构"""
        del frame  # 未使用的参数
        logger.info(f"收到信号 {signum}，正在清理服务...")
        try:
            self.cleanup_all()
        except Exception as e:
            logger.error(f"清理服务时出错: {e}")

        # 在MCP环境中，不直接调用sys.exit，而是设置标志让主循环退出
        import threading

        if threading.current_thread() is threading.main_thread():
            # 只在主线程中设置退出标志
            self._should_exit = True
        else:
            # 在非主线程中，记录日志但不强制退出
            logger.info("非主线程收到信号，已清理服务但不强制退出")

    def register_process(
        self, name: str, process: subprocess.Popen, config: "WebUIConfig"
    ):
        """注册服务进程"""
        with self._lock:
            self._processes[name] = {
                "process": process,
                "config": config,
                "start_time": time.time(),
            }
            logger.info(f"已注册服务进程: {name} (PID: {process.pid})")

    def unregister_process(self, name: str):
        """注销服务进程"""
        with self._lock:
            if name in self._processes:
                del self._processes[name]
                logger.debug(f"已注销服务进程: {name}")

    def get_process(self, name: str) -> Optional[subprocess.Popen]:
        """获取服务进程"""
        with self._lock:
            process_info = self._processes.get(name)
            return process_info["process"] if process_info else None

    def is_process_running(self, name: str) -> bool:
        """检查进程是否在运行"""
        process = self.get_process(name)
        if process is None:
            return False

        try:
            # 检查进程是否还在运行
            return process.poll() is None
        except Exception:
            return False

    def terminate_process(self, name: str, timeout: float = 5.0) -> bool:
        """🔒 改进的进程终止方法 - 确保资源完全清理"""
        process_info = self._processes.get(name)
        if not process_info:
            return True

        process = process_info["process"]
        config = process_info["config"]

        try:
            # 检查进程是否已经结束
            if process.poll() is not None:
                logger.debug(f"进程 {name} 已经结束")
                self._cleanup_process_resources(name, process_info)
                return True

            logger.info(f"正在终止服务进程: {name} (PID: {process.pid})")

            # 分级终止策略：关闭 -> 强制终止 -> 系统清理
            success = self._graceful_shutdown(process, name, timeout)

            if not success:
                success = self._force_shutdown(process, name)

            # 无论终止是否成功，都要清理资源
            self._cleanup_process_resources(name, process_info)

            # 检查端口释放
            self._wait_for_port_release(config.host, config.port)

            return success

        except Exception as e:
            logger.error(f"终止进程 {name} 时出错: {e}")
            # 即使出错也要尝试清理资源
            try:
                self._cleanup_process_resources(name, process_info)
            except Exception as cleanup_error:
                logger.error(f"清理进程资源时出错: {cleanup_error}")
            return False
        finally:
            # 确保进程从管理器中移除
            self.unregister_process(name)

    def _graceful_shutdown(
        self, process: subprocess.Popen, name: str, timeout: float
    ) -> bool:
        """关闭进程"""
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
        """强制终止进程"""
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
        """清理进程相关资源"""
        try:
            process = process_info["process"]

            # 关闭进程的标准输入输出
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
        """等待端口释放"""
        start_time = time.time()
        while time.time() - start_time < timeout:
            if not is_web_service_running(host, port, timeout=1.0):
                logger.debug(f"端口 {host}:{port} 已释放")
                return
            time.sleep(0.5)
        logger.warning(f"端口 {host}:{port} 在 {timeout}秒内未释放")

    def cleanup_all(self):
        """🔒 改进的清理所有服务进程方法 - 确保完全清理"""
        if not self._processes:
            logger.debug("没有需要清理的进程")
            return

        logger.info("开始清理所有服务进程...")
        cleanup_errors = []

        # 获取需要清理的进程列表（避免在迭代时修改字典）
        with self._lock:
            processes_to_cleanup = list(self._processes.items())

        # 并行清理多个进程（如果有多个）
        for name, _ in processes_to_cleanup:  # process_info未使用，用_替代
            try:
                logger.debug(f"正在清理进程: {name}")
                success = self.terminate_process(name)
                if not success:
                    cleanup_errors.append(f"进程 {name} 清理失败")
            except Exception as e:
                error_msg = f"清理进程 {name} 时出错: {e}"
                logger.error(error_msg)
                cleanup_errors.append(error_msg)

        # 最终检查：确保所有进程都已从管理器中移除
        with self._lock:
            remaining_processes = list(self._processes.keys())
            if remaining_processes:
                logger.warning(f"仍有进程未清理完成: {remaining_processes}")
                # 强制清理剩余进程
                for name in remaining_processes:
                    try:
                        del self._processes[name]
                        logger.debug(f"强制移除进程记录: {name}")
                    except Exception as e:
                        logger.error(f"强制移除进程记录失败 {name}: {e}")

        # 报告清理结果
        if cleanup_errors:
            logger.warning(f"服务进程清理完成，但有 {len(cleanup_errors)} 个错误:")
            for error in cleanup_errors:
                logger.warning(f"  - {error}")
        else:
            logger.info("所有服务进程清理完成")

    def get_status(self) -> Dict[str, Dict]:
        """获取所有服务状态"""
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
    """Web UI 配置类"""

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
    """获取Web UI配置"""
    try:
        config_mgr = get_config()
        web_ui_config = config_mgr.get_section("web_ui")
        feedback_config = config_mgr.get_section("feedback")
        network_security_config = config_mgr.get_section("network_security")

        # 优先使用network_security配置中的bind_interface，然后是web_ui中的host
        host = network_security_config.get(
            "bind_interface", web_ui_config.get("host", "127.0.0.1")
        )
        port = web_ui_config.get("port", 8080)
        timeout = feedback_config.get("timeout", 300)
        max_retries = web_ui_config.get("max_retries", 3)
        retry_delay = web_ui_config.get("retry_delay", 1.0)

        config = WebUIConfig(
            host=host,
            port=port,
            timeout=timeout,
            max_retries=max_retries,
            retry_delay=retry_delay,
        )
        logger.info(f"Web UI 配置加载成功: {host}:{port}")
        return config
    except (ValueError, TypeError) as e:
        logger.error(f"配置参数错误: {e}")
        raise ValueError(f"Web UI 配置错误: {e}")
    except Exception as e:
        logger.error(f"配置文件加载失败: {e}")
        raise ValueError(f"Web UI 配置加载失败: {e}")


def validate_input(
    prompt: str, predefined_options: Optional[list] = None
) -> Tuple[str, list]:
    """验证输入参数"""
    # 验证和清理 prompt
    try:
        cleaned_prompt = prompt.strip()
    except AttributeError:
        raise ValueError("prompt 必须是字符串类型")
    if len(cleaned_prompt) > 10000:  # 限制长度
        logger.warning(f"prompt 长度过长 ({len(cleaned_prompt)} 字符)，将被截断")
        cleaned_prompt = cleaned_prompt[:10000] + "..."

    # 验证 predefined_options
    cleaned_options = []
    if predefined_options:
        for option in predefined_options:
            if not isinstance(option, str):
                logger.warning(f"跳过非字符串选项: {option}")
                continue
            cleaned_option = option.strip()
            if cleaned_option and len(cleaned_option) <= 500:  # 限制选项长度
                cleaned_options.append(cleaned_option)
            elif len(cleaned_option) > 500:
                logger.warning(f"选项过长被截断: {cleaned_option[:50]}...")
                cleaned_options.append(cleaned_option[:500] + "...")

    return cleaned_prompt, cleaned_options


def create_http_session(config: WebUIConfig) -> requests.Session:
    """创建配置了重试机制的 HTTP 会话"""
    session = requests.Session()

    # 配置重试策略
    retry_strategy = Retry(
        total=config.max_retries,
        backoff_factor=config.retry_delay,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["HEAD", "GET", "POST"],
    )

    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    # 设置默认超时
    session.timeout = config.timeout

    return session


def is_web_service_running(host: str, port: int, timeout: float = 2.0) -> bool:
    """检查Web服务是否正在运行"""
    try:
        # 验证主机和端口
        if not (1 <= port <= 65535):
            logger.error(f"无效端口号: {port}")
            return False

        # 尝试连接到指定的主机和端口
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
    """健康检查：验证服务是否正常响应"""
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
    """启动Web服务 - 启动时为"无有效内容"状态"""
    web_ui_path = os.path.join(script_dir, "web_ui.py")
    service_manager = ServiceManager()
    service_name = f"web_ui_{config.host}_{config.port}"

    # 初始化通知系统
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
    summary: str, predefined_options: Optional[list[str]], config: WebUIConfig
) -> None:
    """更新Web服务的内容"""
    # 验证输入
    cleaned_summary, cleaned_options = validate_input(summary, predefined_options)

    target_host = "localhost" if config.host == "0.0.0.0" else config.host
    url = f"http://{target_host}:{config.port}/api/update"

    data = {"prompt": cleaned_summary, "predefined_options": cleaned_options}

    session = create_http_session(config)

    try:
        logger.debug(f"更新 Web 内容: {url}")
        response = session.post(url, json=data, timeout=config.timeout)

        if response.status_code == 200:
            logger.info(f"📝 内容已更新: {cleaned_summary[:50]}...")

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


def launch_feedback_ui(
    summary: str, predefined_options: Optional[list[str]] = None, timeout: int = 300
) -> Dict[str, str]:
    """启动反馈界面 - 使用Web服务工作流程"""
    try:
        # 验证输入参数
        cleaned_summary, cleaned_options = validate_input(summary, predefined_options)

        # 获取配置
        script_dir = os.path.dirname(os.path.abspath(__file__))
        config = get_web_ui_config()

        logger.info(f"启动反馈界面: {cleaned_summary[:100]}...")

        # 检查服务是否已经运行，如果没有则启动
        if not health_check_service(config):
            logger.info("Web 服务未运行，正在启动...")
            start_web_service(config, script_dir)
        else:
            logger.info("Web 服务已在运行，直接更新内容")

        # 传递消息和选项，在页面上显示（无论是第一次还是后续调用）
        update_web_content(cleaned_summary, cleaned_options, config)

        # 发送通知（如果可用）
        if NOTIFICATION_AVAILABLE and cleaned_summary.strip():
            try:
                # 尝试从Web界面获取最新的通知配置
                try:
                    target_host = (
                        "localhost" if config.host == "0.0.0.0" else config.host
                    )
                    config_url = f"http://{target_host}:{config.port}/api/get-notification-config"
                    response = requests.get(config_url, timeout=2)
                    if response.ok:
                        web_config = response.json()
                        if web_config.get("status") == "success":
                            # 更新通知管理器配置（不保存到文件，避免重复保存）
                            notification_manager.update_config_without_save(
                                **web_config["config"]
                            )
                            logger.debug("已从Web界面同步通知配置")
                except Exception as e:
                    logger.debug(f"无法从Web界面获取配置，使用默认配置: {e}")

                notification_manager.send_notification(
                    title="AI Intervention Agent",
                    message="新的反馈请求已到达，请查看并回复",
                    trigger=NotificationTrigger.IMMEDIATE,
                    metadata={
                        "summary_preview": cleaned_summary[:100],
                        "options_count": len(cleaned_options) if cleaned_options else 0,
                        "timestamp": time.time(),
                    },
                )
                logger.debug("反馈请求通知已发送")
            except Exception as e:
                logger.warning(f"发送通知失败: {e}")

        # 等待用户反馈，传递timeout参数
        result = wait_for_feedback(config, timeout)
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
) -> list:
    """Request interactive feedback from the user

    Args:
        message: 向用户显示的问题或消息
        predefined_options: 可选的预定义选项列表

    Returns:
        包含用户反馈的字典

    Raises:
        Exception: 当反馈收集失败时
    """
    try:
        # 使用类型提示，移除运行时检查以避免IDE警告
        predefined_options_list = predefined_options

        logger.info(f"收到反馈请求: {message[:50]}...")
        result = launch_feedback_ui(message, predefined_options_list)
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
    """反馈服务上下文管理器"""

    def __init__(self):
        self.service_manager = ServiceManager()
        self.config = None
        self.script_dir = None

    def __enter__(self):
        """进入上下文"""
        try:
            self.config = get_web_ui_config()
            self.script_dir = os.path.dirname(os.path.abspath(__file__))
            logger.info("反馈服务上下文已初始化")
            return self
        except Exception as e:
            logger.error(f"初始化反馈服务上下文失败: {e}")
            raise

    def __exit__(self, exc_type, exc_val, exc_tb):
        """退出上下文"""
        del exc_tb  # 未使用的参数
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
        timeout: int = 300,
    ) -> Dict[str, str]:
        """在上下文中启动反馈界面"""
        return launch_feedback_ui(summary, predefined_options, timeout)


def cleanup_services():
    """清理所有服务进程的便捷函数"""
    try:
        service_manager = ServiceManager()
        service_manager.cleanup_all()
        logger.info("服务清理完成")
    except Exception as e:
        logger.error(f"服务清理失败: {e}")


def main():
    """Main entry point for the AI Intervention Agent MCP server."""
    try:
        logger.info("启动 AI Intervention Agent MCP 服务器")
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
