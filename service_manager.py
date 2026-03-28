"""Web 服务编排层 - 进程生命周期管理、HTTP 客户端、Web UI 启动与健康检查。"""

import asyncio
import atexit
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, cast

import httpx

from config_manager import get_config
from config_utils import get_compat_config
from enhanced_logging import EnhancedLogger
from exceptions import (
    ServiceConnectionError,
    ServiceTimeoutError,
    ServiceUnavailableError,
    ValidationError,
)
from server_config import WebUIConfig, get_target_host, validate_input

logger = EnhancedLogger(__name__)

# ---------------------------------------------------------------------------
# 通知系统（可选依赖）
# ---------------------------------------------------------------------------
try:
    from notification_manager import notification_manager
    from notification_providers import initialize_notification_system

    NOTIFICATION_AVAILABLE = True
except ImportError:
    NOTIFICATION_AVAILABLE = False

# ---------------------------------------------------------------------------
# HTTP 客户端单例 + 配置缓存
# ---------------------------------------------------------------------------
_async_client: httpx.AsyncClient | None = None
_sync_client: httpx.Client | None = None
_http_client_lock = threading.Lock()

_config_cache: Dict[str, Any] = {"config": None, "timestamp": 0.0, "ttl": 10.0}
_config_cache_lock = threading.Lock()

_config_callbacks_registered: bool = False
_config_callbacks_lock = threading.Lock()


def _close_async_client_best_effort(client: httpx.AsyncClient) -> None:
    """在同步上下文中尽力关闭异步 HTTP 客户端的连接池。"""
    if client is None or client.is_closed:
        return
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(client.aclose())
    except RuntimeError:
        try:
            asyncio.run(client.aclose())
        except Exception:
            logger.debug("无法关闭异步 HTTP 客户端（无可用事件循环），将由 GC 回收")


def _invalidate_runtime_caches_on_config_change() -> None:
    """配置变更回调：清空配置缓存 + 关闭 httpx 客户端以便下次重建"""
    global _async_client, _sync_client
    try:
        with _config_cache_lock:
            _config_cache["config"] = None
            _config_cache["timestamp"] = 0
    except Exception:
        pass

    try:
        with _http_client_lock:
            if _sync_client is not None and not _sync_client.is_closed:
                _sync_client.close()
            _sync_client = None
            old_async = _async_client
            _async_client = None
        _close_async_client_best_effort(old_async)
    except Exception:
        pass


def _ensure_config_change_callbacks_registered() -> None:
    """确保只注册一次配置变更回调"""
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
            logger.debug(f"注册配置变更回调失败（忽略）: {e}")
        _config_callbacks_registered = True


# ---------------------------------------------------------------------------
# HTTP 客户端管理
# ---------------------------------------------------------------------------


def get_async_client(config: WebUIConfig) -> httpx.AsyncClient:
    """获取（或创建）模块级异步 HTTP 客户端，支持连接池复用和自动重试。"""
    global _async_client
    if _async_client is None or _async_client.is_closed:
        with _http_client_lock:
            if _async_client is None or _async_client.is_closed:
                transport = httpx.AsyncHTTPTransport(retries=config.max_retries)
                _async_client = httpx.AsyncClient(
                    transport=transport,
                    timeout=httpx.Timeout(config.timeout, connect=5.0),
                )
    return _async_client


def get_sync_client(config: WebUIConfig) -> httpx.Client:
    """获取（或创建）模块级同步 HTTP 客户端。"""
    global _sync_client
    if _sync_client is None or _sync_client.is_closed:
        with _http_client_lock:
            if _sync_client is None or _sync_client.is_closed:
                transport = httpx.HTTPTransport(retries=config.max_retries)
                _sync_client = httpx.Client(
                    transport=transport,
                    timeout=httpx.Timeout(config.timeout, connect=5.0),
                )
    return _sync_client


def create_http_session(config: WebUIConfig) -> httpx.Client:
    """向后兼容：返回同步 httpx.Client。"""
    return get_sync_client(config)


# ---------------------------------------------------------------------------
# Web 服务状态检查
# ---------------------------------------------------------------------------


def is_web_service_running(host: str, port: int, timeout: float = 2.0) -> bool:
    """TCP 端口检查，验证服务是否在监听"""
    try:
        if not (1 <= port <= 65535):
            logger.error(f"无效端口号: {port}")
            return False

        target_host = get_target_host(host)

        try:
            addrinfos = socket.getaddrinfo(target_host, port, type=socket.SOCK_STREAM)
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


# ---------------------------------------------------------------------------
# ServiceManager 单例
# ---------------------------------------------------------------------------


class ServiceManager:
    """服务进程生命周期管理器（线程安全单例）"""

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
                    self._processes: Dict[str, Dict] = {}
                    self._cleanup_registered = False
                    self._should_exit = False
                    self._initialized = True
                    self._register_cleanup()

    def _register_cleanup(self):
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
        del frame
        logger.info(f"收到信号 {signum}，正在清理服务...")
        try:
            self.cleanup_all(shutdown_notification_manager=True)
        except Exception as e:
            logger.error(f"清理服务时出错: {e}", exc_info=True)

        if threading.current_thread() is threading.main_thread():
            self._should_exit = True
        else:
            logger.info("非主线程收到信号，已清理服务但不强制退出")

    def register_process(
        self, name: str, process: subprocess.Popen, config: WebUIConfig
    ) -> None:
        with self._lock:
            self._processes[name] = {
                "process": process,
                "config": config,
                "start_time": time.time(),
            }
            logger.info(f"已注册服务进程: {name} (PID: {process.pid})")

    def unregister_process(self, name: str) -> None:
        with self._lock:
            if name in self._processes:
                del self._processes[name]
                logger.debug(f"已注销服务进程: {name}")

    def get_process(self, name: str) -> Optional[subprocess.Popen]:
        with self._lock:
            process_info = self._processes.get(name)
            return process_info["process"] if process_info else None

    def is_process_running(self, name: str) -> bool:
        process = self.get_process(name)
        if process is None:
            return False
        try:
            return process.poll() is None
        except Exception:
            return False

    def terminate_process(self, name: str, timeout: float = 5.0) -> bool:
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
        try:
            process = process_info["process"]
            for attr in ("stdin", "stdout", "stderr"):
                handle = getattr(process, attr, None)
                if handle:
                    try:
                        handle.close()
                    except Exception:
                        pass
            logger.debug(f"进程 {name} 的资源已清理")
        except Exception as e:
            logger.error(f"清理进程 {name} 资源时出错: {e}", exc_info=True)

    def _wait_for_port_release(self, host: str, port: int, timeout: float = 10.0):
        start_time = time.monotonic()
        while time.monotonic() - start_time < timeout:
            if not is_web_service_running(host, port, timeout=1.0):
                logger.debug(f"端口 {host}:{port} 已释放")
                return
            time.sleep(0.5)
        logger.warning(f"端口 {host}:{port} 在 {timeout}秒内未释放")

    def cleanup_all(self, shutdown_notification_manager: bool = True) -> None:
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

        if shutdown_notification_manager and NOTIFICATION_AVAILABLE:
            try:
                notification_manager.shutdown()
                logger.info("通知管理器线程池已关闭")
            except Exception as e:
                logger.warning(f"关闭通知管理器失败: {e}", exc_info=True)

        try:
            cleanup_http_clients()
            logger.debug("HTTP 客户端已清理")
        except Exception as e:
            logger.debug(f"清理 HTTP 客户端时出错（忽略）: {e}")

    def get_status(self) -> Dict[str, Dict]:
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


# ---------------------------------------------------------------------------
# 配置加载
# ---------------------------------------------------------------------------


def get_web_ui_config() -> Tuple[WebUIConfig, int]:
    """加载 Web UI 配置（带 10s TTL 缓存），返回 (WebUIConfig, auto_resubmit_timeout)"""
    _ensure_config_change_callbacks_registered()

    current_time = time.monotonic()
    with _config_cache_lock:
        if (
            _config_cache["config"] is not None
            and current_time - _config_cache["timestamp"] < _config_cache["ttl"]
        ):
            logger.debug("使用缓存的 Web UI 配置")
            return cast(Tuple[WebUIConfig, int], _config_cache["config"])

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

        language = str(web_ui_config.get("language", "auto"))

        config = WebUIConfig(
            host=host,
            port=port,
            language=language,
            timeout=http_timeout,
            max_retries=max_retries,
            retry_delay=retry_delay,
        )

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


# ---------------------------------------------------------------------------
# Web 服务启动 / 内容更新 / 状态确认
# ---------------------------------------------------------------------------


def _get_web_ui_log_path(script_dir: Path) -> Path:
    """获取 Web UI 子进程日志文件路径，自动创建 logs 目录并截断过大文件。"""
    log_dir = script_dir / "logs"
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / "web_ui.log"
    # 超过 5MB 时截断为空，简易日志轮转
    try:
        if log_path.exists() and log_path.stat().st_size > 5 * 1024 * 1024:
            log_path.write_text("")
    except OSError:
        pass
    return log_path


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

    if not web_ui_path.exists():
        raise FileNotFoundError(f"Web UI 脚本不存在: {web_ui_path}")

    if service_manager.is_process_running(service_name) or health_check_service(config):
        logger.info(
            f"Web 服务已在运行: http://{get_target_host(config.host)}:{config.port}"
        )
        return

    args = [
        sys.executable,
        "-u",
        str(web_ui_path),
        "--prompt",
        "",
        "--predefined-options",
        "",
        "--host",
        config.host,
        "--port",
        str(config.port),
    ]

    log_path = _get_web_ui_log_path(script_dir)
    log_file = None
    try:
        log_file = open(log_path, "a", encoding="utf-8")  # noqa: SIM115
        logger.info(f"Web UI 子进程日志将写入: {log_path}")
    except OSError as e:
        logger.warning(f"无法打开日志文件 {log_path}: {e}，子进程日志将被丢弃")

    try:
        logger.info(f"启动 Web 服务进程: {' '.join(args)}")
        process = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=log_file if log_file is not None else subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            close_fds=True,
        )
        logger.info(f"Web 服务进程已启动，PID: {process.pid}")
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
        raise ServiceUnavailableError(
            f"启动 Web 服务失败: {e}", code="start_failed"
        ) from e

    max_wait = 15
    check_interval = 0.5

    try:
        for attempt in range(int(max_wait / check_interval)):
            if health_check_service(config):
                logger.info(f"🌐 Web服务已启动: http://{config.host}:{config.port}")
                return
            if attempt % 4 == 0:
                logger.debug(f"等待服务启动... ({attempt * check_interval:.1f}s)")
            time.sleep(check_interval)

        if health_check_service(config):
            logger.info(f"🌐 Web 服务启动成功: http://{config.host}:{config.port}")
            return

        raise ServiceTimeoutError(
            f"Web 服务启动超时 ({max_wait}秒)，请检查端口 {config.port} 是否被占用",
            code="start_timeout",
        )
    except Exception:
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


def cleanup_http_clients() -> None:
    """清理 HTTP 客户端（供 server.cleanup_services 调用）"""
    global _sync_client, _async_client
    with _http_client_lock:
        try:
            if _sync_client is not None and not _sync_client.is_closed:
                _sync_client.close()
        except Exception:
            pass
        _sync_client = None
        old_async = _async_client
        _async_client = None
    _close_async_client_best_effort(old_async)
