"""MCP 服务器核心 - interactive_feedback 工具、多任务队列、通知集成。"""

__all__ = [
    "AUTO_RESUBMIT_TIMEOUT_DEFAULT",
    "AUTO_RESUBMIT_TIMEOUT_MAX",
    "AUTO_RESUBMIT_TIMEOUT_MIN",
    "BACKEND_BUFFER",
    "BACKEND_MIN",
    "FEEDBACK_TIMEOUT_DEFAULT",
    "FEEDBACK_TIMEOUT_MAX",
    "FEEDBACK_TIMEOUT_MIN",
    "MAX_MESSAGE_LENGTH",
    "MAX_OPTION_LENGTH",
    "PROMPT_MAX_LENGTH",
    "PROMPT_SUFFIX_DEFAULT",
    "RESUBMIT_PROMPT_DEFAULT",
    "FeedbackConfig",
    "FeedbackServiceContext",
    "ServiceManager",
    "WebUIConfig",
    "_append_prompt_suffix",
    "_cli_main",
    "_ensure_config_change_callbacks_registered",
    "_format_file_size",
    "_generate_task_id",
    "_guess_mime_type_from_data",
    "_invalidate_runtime_caches_on_config_change",
    "_is_sensitive_key",
    "_is_using_default_config",
    "_make_resubmit_response",
    "_print_effective_config",
    "_process_image",
    "_redact_sensitive",
    "calculate_backend_timeout",
    "cleanup_http_clients",
    "cleanup_services",
    "create_http_session",
    "ensure_web_ui_running",
    "get_async_client",
    "get_feedback_config",
    "get_feedback_prompts",
    "get_sync_client",
    "get_target_host",
    "get_task_queue",
    "get_web_ui_config",
    "health_check_service",
    "interactive_feedback",
    "is_web_service_running",
    "launch_feedback_ui",
    "main",
    "mcp",
    "parse_structured_response",
    "resolve_external_base_url",
    "start_web_service",
    "update_web_content",
    "validate_input",
    "validate_input_with_defaults",
    "wait_for_task_completion",
]

import argparse
import atexit  # noqa: F401  (kept for test-suite compatibility: tests patch server.atexit)
import io
import os
import random
import sys
import threading
import time
from typing import cast

_PROCESS_STARTED_AT_UNIX: float = time.time()

from fastmcp import FastMCP
from mcp.types import Icon, ToolAnnotations

from ai_intervention_agent.enhanced_logging import EnhancedLogger
from ai_intervention_agent.server_config import (
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
    resolve_external_base_url,
    validate_input,
    validate_input_with_defaults,
)
from ai_intervention_agent.service_manager import (
    ServiceManager,
    _ensure_config_change_callbacks_registered,
    _invalidate_runtime_caches_on_config_change,
    cleanup_http_clients,
    create_http_session,
    ensure_web_ui_running,
    get_async_client,
    get_sync_client,
    get_web_ui_config,
    health_check_service,
    is_web_service_running,
    start_web_service,
    update_web_content,
)

os.environ["NO_COLOR"] = "1"
os.environ["TERM"] = "dumb"
os.environ["FASTMCP_NO_BANNER"] = "1"
os.environ["FASTMCP_QUIET"] = "1"


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


try:
    import rich.console as rich_console_module

    _devnull = io.StringIO()

    class SilentConsole(rich_console_module.Console):
        def __init__(self, *args, **kwargs):
            for k in (
                "file",
                "force_terminal",
                "force_jupyter",
                "force_interactive",
                "quiet",
            ):
                kwargs.pop(k, None)
            super().__init__(
                *args,
                file=_devnull,
                force_terminal=False,
                force_jupyter=False,
                force_interactive=False,
                quiet=True,
                **kwargs,
            )

    setattr(rich_console_module, "Console", SilentConsole)  # noqa: B010
except ImportError:
    pass


def _resolve_server_version() -> str:
    """读取已安装包版本号，失败时返回开发占位符。"""
    try:
        from importlib.metadata import PackageNotFoundError
        from importlib.metadata import version as _pkg_version

        try:
            return _pkg_version("ai-intervention-agent")
        except PackageNotFoundError:
            return "0.0.0+local"
    except Exception:
        return "0.0.0+local"


_BUILD_INFO_CACHE: dict[str, str] = {}
_BUILD_INFO_CACHE_LOCK: threading.Lock = threading.Lock()


def _resolve_build_info() -> dict[str, str]:
    """返回 ``{git_commit, git_branch, git_dirty}``，失败字段填 ``"unknown"``。"""
    global _BUILD_INFO_CACHE
    if _BUILD_INFO_CACHE:
        return _BUILD_INFO_CACHE.copy()

    with _BUILD_INFO_CACHE_LOCK:
        if _BUILD_INFO_CACHE:
            return _BUILD_INFO_CACHE.copy()

        import subprocess as _subprocess
        from pathlib import Path as _Path

        repo_root = _Path(__file__).resolve().parent
        cache: dict[str, str] = {}

        def _git(args: list[str]) -> str:
            try:
                out = _subprocess.check_output(
                    ["git", *args],
                    cwd=str(repo_root),
                    stderr=_subprocess.DEVNULL,
                    timeout=2.0,
                )
                return out.decode("utf-8", errors="replace").strip()
            except Exception:
                return "unknown"

        cache["git_commit"] = _git(["rev-parse", "--short", "HEAD"])
        cache["git_branch"] = _git(["rev-parse", "--abbrev-ref", "HEAD"])

        try:
            porc = (
                _subprocess.check_output(
                    ["git", "status", "--porcelain"],
                    cwd=str(repo_root),
                    stderr=_subprocess.DEVNULL,
                    timeout=2.0,
                )
                .decode("utf-8", errors="replace")
                .strip()
            )
            cache["git_dirty"] = "yes" if porc else "no"
        except Exception:
            cache["git_dirty"] = "unknown"

        _BUILD_INFO_CACHE = cache
        return cache.copy()


def reset_sse_stats_cache_for_testing() -> None:
    """R352 (cycle-39 #C2) · **Test-only**: 清空 ``_sse_stats_cache`` +
    重置 timestamp, 让下次 ``_fetch_sse_stats_cached`` 重新拉取。"""
    global _sse_stats_cache_ts
    with _sse_stats_cache_lock:
        _sse_stats_cache.clear()
        _sse_stats_cache_ts = 0.0


def reset_recent_logs_cache_for_testing() -> None:
    """R352 (cycle-39 #C2) · **Test-only**: 清空 ``_recent_logs_cache`` +
    重置 timestamp, 让下次 ``_fetch_recent_logs_cached`` 重新拉取。
    """
    global _recent_logs_cache_key, _recent_logs_cache_ts
    with _recent_logs_cache_lock:
        _recent_logs_cache.clear()
        _recent_logs_cache_key = ""
        _recent_logs_cache_ts = 0.0


def reset_build_info_cache_for_testing() -> None:
    """R352 (cycle-39 #C2) · **Test-only**: 清空 ``_BUILD_INFO_CACHE`` 让
    下次 ``_resolve_build_info()`` 重新调用 git subprocess。"""
    global _BUILD_INFO_CACHE
    with _BUILD_INFO_CACHE_LOCK:
        _BUILD_INFO_CACHE = {}


def _build_server_icons() -> list[Icon]:
    """启动时一次性把本地 icons 转成 data URI，让 server icons 完全 self-contained。"""
    from pathlib import Path

    from fastmcp.utilities.types import Image

    icons_dir = Path(__file__).resolve().parent / "icons"
    icon_specs: list[tuple[str, str, list[str]]] = [
        ("favicon-32.png", "image/png", ["32x32"]),
        ("icon-192.png", "image/png", ["192x192"]),
        ("icon-512.png", "image/png", ["512x512"]),
        ("icon.svg", "image/svg+xml", ["any"]),
    ]
    icons: list[Icon] = []
    for filename, mime, sizes in icon_specs:
        path = icons_dir / filename
        if not path.is_file():
            continue
        try:
            data_uri = Image(path=str(path)).to_data_uri()
            icons.append(Icon(src=data_uri, mimeType=mime, sizes=sizes))
        except Exception:
            continue
    return icons


_SERVER_ICONS: list[Icon] = _build_server_icons()


mcp: FastMCP = FastMCP(
    name="AI Intervention Agent MCP",
    instructions=(
        "本 MCP 服务暴露唯一工具 `interactive_feedback`，用于通过 Web UI 向人类用户请求"
        "澄清、决策或签收。\n\n"
        "**适合调用的场景**：\n"
        "1. 需求不明确，需要在继续前向用户确认。\n"
        "2. 存在多种方案，需要用户挑选。\n"
        "3. 方案 / 策略发生变更，需要用户显式批准。\n"
        "4. 即将宣布任务完成，需要最终确认。\n\n"
        "**不适合调用的场景**：\n"
        "- 你能基于现有上下文自行回答的问题。\n"
        "- 不需要人类决策的常规进度更新。\n\n"
        "**行为约定**：\n"
        "- 开放世界工具（与真人交互，可能推送通知）。\n"
        "- 非破坏性（不会修改源代码 / git / 数据库）。\n"
        "- 非幂等（每次调用都会创建一个新的反馈任务）。\n"
        "- 阻塞直到用户提交、自动重调倒计时触发或后端超时。\n\n"
        "用户可以附上文字、选项和图片；返回值是 MCP 内容块（text + image）的列表。"
    ),
    version=_resolve_server_version(),
    website_url="https://github.com/xiadengma/ai-intervention-agent",
    icons=_SERVER_ICONS,
)
logger = EnhancedLogger(__name__)


from ai_intervention_agent.server_feedback import (
    FeedbackServiceContext,
    launch_feedback_ui,
    wait_for_task_completion,
)
from ai_intervention_agent.server_feedback import (
    interactive_feedback as _interactive_feedback_impl,
)

_INTERACTIVE_FEEDBACK_ANNOTATIONS = ToolAnnotations(
    title="Interactive Feedback (人机协作反馈)",
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=False,
    openWorldHint=True,
)

interactive_feedback = mcp.tool(
    annotations=_INTERACTIVE_FEEDBACK_ANNOTATIONS,
    tags={"human-in-the-loop", "feedback", "approval"},
    version=_resolve_server_version(),
)(_interactive_feedback_impl)


from fastmcp.server.middleware.error_handling import ErrorHandlingMiddleware

_ERROR_HANDLING_MIDDLEWARE: ErrorHandlingMiddleware = ErrorHandlingMiddleware(
    logger=_stdlib_logging.getLogger("ai_intervention_agent.fastmcp_errors"),
    include_traceback=False,
    transform_errors=True,
)
mcp.middleware.insert(0, _ERROR_HANDLING_MIDDLEWARE)


def get_mcp_error_stats() -> dict[str, int]:
    """返回 MCP 中间件累计的异常计数（``{error_type}:{method}`` → 次数）。"""
    return _ERROR_HANDLING_MIDDLEWARE.get_error_stats()


from fastmcp.server.middleware.logging import LoggingMiddleware
from fastmcp.server.middleware.timing import TimingMiddleware

_TIMING_MIDDLEWARE: TimingMiddleware = TimingMiddleware(
    logger=_stdlib_logging.getLogger("ai_intervention_agent.fastmcp_timing"),
    log_level=_stdlib_logging.INFO,
)
_LOGGING_MIDDLEWARE: LoggingMiddleware = LoggingMiddleware(
    logger=_stdlib_logging.getLogger("ai_intervention_agent.fastmcp_requests"),
    log_level=_stdlib_logging.INFO,
    include_payloads=False,
    include_payload_length=True,
    max_payload_length=1000,
)
mcp.add_middleware(_TIMING_MIDDLEWARE)
mcp.add_middleware(_LOGGING_MIDDLEWARE)


from fastmcp.server.middleware.rate_limiting import RateLimitingMiddleware

_RATE_LIMITING_MIDDLEWARE: RateLimitingMiddleware = RateLimitingMiddleware(
    max_requests_per_second=10.0,
    burst_capacity=20,
)


mcp.middleware.insert(1, _RATE_LIMITING_MIDDLEWARE)


# 端点（``aiia_mcp_tool_calls_total{tool=...,status=success|failure}``）。


from ai_intervention_agent.mcp_tool_call_metrics import (
    ToolCallCounterMiddleware,
)
from ai_intervention_agent.mcp_tool_call_metrics import (
    get_mcp_tool_call_stats as get_mcp_tool_call_stats,
)

_TOOL_CALL_COUNTER_MIDDLEWARE: ToolCallCounterMiddleware = ToolCallCounterMiddleware()
mcp.middleware.insert(2, _TOOL_CALL_COUNTER_MIDDLEWARE)


# read` 读取 ``aiia://server/info`` 拿到本服务器的 self-information：


_SSE_STATS_CACHE_TTL_S: float = 1.0
_sse_stats_cache: dict[str, object] = {}
_sse_stats_cache_ts: float = 0.0
_sse_stats_cache_lock: threading.Lock = threading.Lock()


def _fetch_sse_stats_cached(host: str, port: int) -> dict[str, object]:
    """1.0s TTL 包装 GET /api/system/sse-stats（R54-A）。"""
    global _sse_stats_cache_ts
    now = time.monotonic()
    with _sse_stats_cache_lock:
        age = now - _sse_stats_cache_ts
        if _sse_stats_cache and age < _SSE_STATS_CACHE_TTL_S:
            cached_copy = _sse_stats_cache.copy()
            cached_copy["cached"] = True
            cached_copy["cache_age_s"] = round(age, 3)
            return cached_copy

    target_url = f"http://{host}:{port}/api/system/sse-stats"
    result: dict[str, object] = {}
    try:
        import httpx

        resp = httpx.get(target_url, timeout=0.5)
    except Exception as net_exc:
        result["error"] = f"{type(net_exc).__name__}: {net_exc}"
        return result

    if resp.status_code == 200:
        try:
            body = resp.json()
        except Exception as json_exc:
            result["error"] = f"json decode failed: {json_exc!r}"
            return result
        if isinstance(body, dict) and body.get("success"):
            for key in (
                "emit_total",
                "latest_event_id",
                "gap_warnings_emitted",
                "backpressure_discards",
                "subscriber_count",
                "history_size",
                "heartbeat_total",
                "oversize_drops",
                "emit_by_type",
            ):
                if key in body:
                    result[key] = body[key]
            with _sse_stats_cache_lock:
                _sse_stats_cache.clear()
                _sse_stats_cache.update(result)
                _sse_stats_cache_ts = time.monotonic()
        else:
            result["error"] = f"sse-stats response not success: {body!r}"
    else:
        result["error"] = f"sse-stats HTTP {resp.status_code}"
    return result


_RECENT_LOGS_CACHE_TTL_S: float = 1.0
_recent_logs_cache: dict[str, object] = {}
_recent_logs_cache_key: str = ""
_recent_logs_cache_ts: float = 0.0
_recent_logs_cache_lock: threading.Lock = threading.Lock()


def _fetch_recent_logs_cached(
    host: str, port: int, limit: int = 20
) -> dict[str, object]:
    """1.0s TTL 包装 GET /api/system/recent-logs（R55）。"""
    global _recent_logs_cache_key, _recent_logs_cache_ts
    now = time.monotonic()
    limit_int = int(limit)
    cache_key = f"limit={limit_int}"
    with _recent_logs_cache_lock:
        age = now - _recent_logs_cache_ts
        if (
            _recent_logs_cache
            and age < _RECENT_LOGS_CACHE_TTL_S
            and _recent_logs_cache_key == cache_key
        ):
            cached_copy = _recent_logs_cache.copy()
            cached_copy["cached"] = True
            cached_copy["cache_age_s"] = round(age, 3)
            return cached_copy

    target_url = f"http://{host}:{port}/api/system/recent-logs?limit={limit_int}"
    result: dict[str, object] = {}
    try:
        import httpx

        resp = httpx.get(target_url, timeout=0.5)
    except Exception as net_exc:
        result["error"] = f"{type(net_exc).__name__}: {net_exc}"
        return result

    if resp.status_code == 200:
        try:
            body = resp.json()
        except Exception as json_exc:
            result["error"] = f"json decode failed: {json_exc!r}"
            return result
        if isinstance(body, dict) and body.get("success"):
            entries = body.get("entries")
            if isinstance(entries, list):
                result["entries"] = entries
                result["count"] = len(entries)
            else:
                result["entries"] = []
                result["count"] = 0
            with _recent_logs_cache_lock:
                _recent_logs_cache.clear()
                _recent_logs_cache.update(result)
                _recent_logs_cache_key = cache_key
                _recent_logs_cache_ts = time.monotonic()
        else:
            result["error"] = f"recent-logs response not success: {body!r}"
    else:
        result["error"] = f"recent-logs HTTP {resp.status_code}"
    return result


@mcp.resource(
    "aiia://server/info",
    name="Server Info",
    description=(
        "Self-information for ai-intervention-agent MCP server. Returns version, "
        "transport, runtime details, middleware chain, accumulated error stats, "
        "Web UI runtime status, and task-queue snapshot as JSON."
    ),
    mime_type="application/json",
    tags={"diagnostics", "self-info"},
)
def server_info_resource() -> dict[str, object]:
    """Return diagnostic self-information for this MCP server."""
    info: dict[str, object] = {
        "name": mcp.name,
        "version": _resolve_server_version(),
        "transport": "stdio",
        "error_stats": get_mcp_error_stats(),
    }

    try:
        info["build"] = _resolve_build_info()
    except Exception as build_exc:
        info["build"] = {"error": f"{type(build_exc).__name__}: {build_exc}"}

    runtime_info: dict[str, object] = {}
    try:
        import platform as _platform

        runtime_info["python_version"] = sys.version.split()[0]
        runtime_info["python_executable"] = sys.executable
        runtime_info["platform"] = (
            f"{_platform.system()} {_platform.release()} ({_platform.machine()})"
        )

        runtime_info["python_implementation"] = _platform.python_implementation()
        runtime_info["started_at_unix"] = round(_PROCESS_STARTED_AT_UNIX, 3)
        runtime_info["uptime_seconds"] = round(
            time.time() - _PROCESS_STARTED_AT_UNIX, 3
        )
    except Exception as runtime_exc:
        runtime_info["error"] = f"{type(runtime_exc).__name__}: {runtime_exc}"
    info["runtime"] = runtime_info

    process_info: dict[str, object] = {}
    try:
        import platform as _proc_platform

        process_info["pid"] = os.getpid()
        process_info["thread_count"] = threading.active_count()
        try:
            import resource as _resource

            ru = _resource.getrusage(_resource.RUSAGE_SELF)

            if _proc_platform.system() == "Darwin":
                process_info["rss_bytes"] = int(ru.ru_maxrss)
            else:
                process_info["rss_bytes"] = int(ru.ru_maxrss) * 1024
            process_info["user_cpu_seconds"] = round(ru.ru_utime, 3)
            process_info["sys_cpu_seconds"] = round(ru.ru_stime, 3)
        except Exception as ru_exc:
            process_info["resource_error"] = f"{type(ru_exc).__name__}: {ru_exc}"

        try:
            fd_dir = "/proc/self/fd"
            if os.path.isdir(fd_dir):
                process_info["open_fds"] = len(os.listdir(fd_dir))
            else:
                process_info["open_fds"] = -1
        except Exception as fd_exc:
            process_info["fd_error"] = f"{type(fd_exc).__name__}: {fd_exc}"
    except Exception as proc_exc:
        process_info["error"] = f"{type(proc_exc).__name__}: {proc_exc}"
    info["process"] = process_info

    fastmcp_info: dict[str, object] = {}
    try:
        from importlib.metadata import PackageNotFoundError as _PkgNotFound
        from importlib.metadata import version as _pkg_version

        try:
            fastmcp_info["version"] = _pkg_version("fastmcp")
        except _PkgNotFound:
            fastmcp_info["version"] = "unknown"
    except Exception as fmcp_exc:
        fastmcp_info["error"] = f"{type(fmcp_exc).__name__}: {fmcp_exc}"
    info["fastmcp"] = fastmcp_info

    try:
        info["middleware"] = [type(mw).__name__ for mw in mcp.middleware]
    except Exception as mw_exc:
        info["middleware_error"] = f"{type(mw_exc).__name__}: {mw_exc}"

    web_ui_info: dict[str, object] = {}
    try:
        config, _auto_resubmit = get_web_ui_config()
        host = get_target_host(config.host)
        port = int(config.port)
        web_ui_info["host"] = host
        web_ui_info["port"] = port
        try:
            web_ui_info["running"] = bool(is_web_service_running(host, port))
        except Exception as probe_exc:
            web_ui_info["running"] = False
            web_ui_info["probe_error"] = f"{type(probe_exc).__name__}: {probe_exc}"
    except Exception as cfg_exc:
        web_ui_info["error"] = f"{type(cfg_exc).__name__}: {cfg_exc}"
    info["web_ui"] = web_ui_info

    task_queue_info: dict[str, object] = {}
    try:
        import ai_intervention_agent.task_queue_singleton as _tq_singleton

        existing = getattr(_tq_singleton, "_global_task_queue", None)
        if existing is None:
            task_queue_info["initialized"] = False
        else:
            task_queue_info["initialized"] = True
            try:
                count_attr = getattr(existing, "get_task_count", None)
                if callable(count_attr):
                    counts = count_attr()
                    if isinstance(counts, dict):
                        task_queue_info["size"] = int(counts.get("total", 0))
                        task_queue_info["pending"] = int(counts.get("pending", 0))
            except Exception as q_probe_exc:
                task_queue_info["probe_error"] = (
                    f"{type(q_probe_exc).__name__}: {q_probe_exc}"
                )
    except Exception as tq_exc:
        task_queue_info["error"] = f"{type(tq_exc).__name__}: {tq_exc}"
    info["task_queue"] = task_queue_info

    feedback_counters_info: dict[str, object] = {}
    try:
        import ai_intervention_agent.server_feedback as _sfb

        getter = getattr(_sfb, "get_feedback_counters", None)
        if callable(getter):
            counters = getter()
            feedback_counters_info = (
                counters if isinstance(counters, dict) else dict(counters)
            )
        else:
            feedback_counters_info["error"] = (
                "get_feedback_counters not found on server_feedback"
            )
    except Exception as fb_exc:
        feedback_counters_info["error"] = f"{type(fb_exc).__name__}: {fb_exc}"
    info["interactive_feedback"] = feedback_counters_info

    sse_bus_info: dict[str, object] = {}
    try:
        if web_ui_info.get("running"):
            host = web_ui_info.get("host")
            port = web_ui_info.get("port")
            if isinstance(host, str) and isinstance(port, int) and port > 0:
                sse_bus_info = _fetch_sse_stats_cached(host, port)
            else:
                sse_bus_info["error"] = (
                    f"web_ui host/port not usable: host={host!r} port={port!r}"
                )
        else:
            sse_bus_info["available"] = False
            sse_bus_info["reason"] = "web_ui not running"
    except Exception as sse_exc:
        sse_bus_info["error"] = f"{type(sse_exc).__name__}: {sse_exc}"
    info["sse_bus"] = sse_bus_info

    recent_logs_info: dict[str, object] = {}
    try:
        from ai_intervention_agent.enhanced_logging import (
            get_recent_logs as _get_recent_logs,
        )

        mcp_entries: list[dict[str, object]] = []
        for ent in _get_recent_logs(limit=20):
            tagged = ent.copy()
            tagged["source"] = "mcp"
            mcp_entries.append(tagged)
        recent_logs_info["mcp_count"] = len(mcp_entries)

        web_ui_entries: list[dict[str, object]] = []
        web_ui_recent_meta: dict[str, object] = {}
        if web_ui_info.get("running"):
            host = web_ui_info.get("host")
            port = web_ui_info.get("port")
            if isinstance(host, str) and isinstance(port, int) and port > 0:
                fetched = _fetch_recent_logs_cached(host, port, limit=20)
                fetched_entries = fetched.get("entries")
                if isinstance(fetched_entries, list):
                    for ent in fetched_entries:
                        if not isinstance(ent, dict):
                            continue
                        tagged = cast("dict[str, object]", ent.copy())
                        tagged["source"] = "web_ui"
                        web_ui_entries.append(tagged)
                if "error" in fetched:
                    web_ui_recent_meta["error"] = fetched["error"]
                if fetched.get("cached"):
                    web_ui_recent_meta["cached"] = True
        else:
            web_ui_recent_meta["available"] = False
            web_ui_recent_meta["reason"] = "web_ui not running"

        recent_logs_info["web_ui_count"] = len(web_ui_entries)
        if web_ui_recent_meta:
            recent_logs_info["web_ui_meta"] = web_ui_recent_meta

        merged = mcp_entries + web_ui_entries
        merged.sort(key=lambda e: e.get("ts_unix", 0) if isinstance(e, dict) else 0)
        recent_logs_info["count"] = len(merged)
        recent_logs_info["entries"] = merged
    except Exception as log_exc:
        recent_logs_info["error"] = f"{type(log_exc).__name__}: {log_exc}"
    info["recent_logs"] = recent_logs_info

    return info


from ai_intervention_agent.task_queue_singleton import (  # noqa: F401  (re-export for back-compat)
    _shutdown_global_task_queue,
    get_task_queue,
)


def cleanup_services(shutdown_notification_manager: bool = True) -> None:
    """清理所有启动的服务进程"""
    cleanup_http_clients()

    try:
        svc_mgr = ServiceManager()
        svc_mgr.cleanup_all(shutdown_notification_manager=shutdown_notification_manager)
        logger.info("服务清理完成")
    except Exception as e:
        logger.error(f"服务清理失败: {e}", exc_info=True)


def _build_arg_parser() -> argparse.ArgumentParser:
    """构造 ``ai-intervention-agent`` 的 CLI 解析器。"""
    parser = argparse.ArgumentParser(
        prog="ai-intervention-agent",
        description=(
            "MCP server providing the interactive_feedback tool — lets AI "
            "agents pause to ask humans for clarification, decisions, or "
            "sign-off via a local Web UI."
        ),
        epilog=(
            "Run without arguments to start the MCP stdio server (the "
            "default way Cursor / Claude Desktop / mcp-cli invoke this "
            "binary). Configure host/port/language via "
            "AI_INTERVENTION_AGENT_WEB_UI_HOST/PORT/LANGUAGE env vars or "
            "your config.toml. See docs/configuration.md for the full "
            "configuration surface."
        ),
    )
    parser.add_argument(
        "--version",
        "-V",
        action="version",
        version=f"%(prog)s {_resolve_server_version()}",
        help="Print version and exit.",
    )
    parser.add_argument(
        "--print-config",
        action="store_true",
        default=False,
        help=(
            "Print the effective merged config (config.toml + env "
            "overrides) as JSON to stdout, then exit 0. Useful for "
            "debugging 'why does my port show 8181 instead of 8080?' "
            "— the output includes config_file_path, web_ui resolved "
            "host/port/language, and the active "
            "AI_INTERVENTION_AGENT_WEB_UI_* env overrides. "
            "network_security details are omitted (sensitive)."
        ),
    )
    return parser


_SENSITIVE_KEY_SUBSTRINGS: tuple[str, ...] = (
    "device_key",
    "device-key",
    "api_key",
    "api-key",
    "apikey",
    "auth_token",
    "auth-token",
    "token",
    "password",
    "passwd",
    "secret",
    "private_key",
    "private-key",
    "client_secret",
    "client-secret",
    "webhook_url",
    "webhook-url",
    "bot_token",
    "bot-token",
    "session_key",
    "session-key",
    "credential",
)
_REDACTED_VALUE = "***REDACTED***"


def _is_sensitive_key(key: str) -> bool:
    """匹配规则：key 名 normalized 后包含任意 ``_SENSITIVE_KEY_SUBSTRINGS`` 子串。"""

    def _norm(s: str) -> str:
        return s.lower().replace("_", "").replace("-", "")

    normalized = _norm(key)
    return any(_norm(needle) in normalized for needle in _SENSITIVE_KEY_SUBSTRINGS)


def _redact_sensitive(value: object) -> object:
    """递归扫一棵 config 子树，把敏感字段的值替换成 ``***REDACTED***``。"""
    if isinstance(value, dict):
        out: dict[object, object] = {}
        for k, v in value.items():
            if isinstance(k, str) and _is_sensitive_key(k):
                out[k] = _REDACTED_VALUE
            else:
                out[k] = _redact_sensitive(v)
        return out
    if isinstance(value, (list, tuple)):
        return [_redact_sensitive(item) for item in value]
    return value


def _is_using_default_config(config_file_path: object) -> bool:
    """CR#16 F-3：判断 ``config_file_path`` 是否指向项目 bundled 默认配置。"""
    if not isinstance(config_file_path, str) or not config_file_path:
        return True
    try:
        from pathlib import Path

        cfg_path = Path(config_file_path).resolve()
        pkg_root = Path(__file__).resolve().parent.parent.parent
        return str(cfg_path).startswith(str(pkg_root) + os.sep) or str(cfg_path) == str(
            pkg_root / "config.toml"
        )
    except Exception as exc:
        logger.debug(f"--print-config: using_defaults 判定失败: {exc!r}")
        return False


def _print_effective_config() -> int:
    """实现 ``--print-config``：dump merged config 到 stdout 后退出。"""
    import json as _json

    from ai_intervention_agent import service_manager as _sm
    from ai_intervention_agent.config_manager import get_config

    payload: dict[str, object] = {}
    try:
        cfg = get_config()
        config_file = getattr(cfg, "config_file", None)
        payload["config_file_path"] = str(config_file) if config_file else None
        all_config = cfg.get_all()

        sections_full: dict[str, object] = {
            k: v for k, v in all_config.items() if isinstance(v, dict)
        }
        web_ui_raw = all_config.get("web_ui")
        web_ui_section = web_ui_raw.copy() if isinstance(web_ui_raw, dict) else {}
    except Exception as exc:
        print(
            _json.dumps(
                {"error": f"config probe failed: {exc!r}"},
                ensure_ascii=False,
                indent=2,
            ),
            flush=True,
        )
        return 1

    payload["using_defaults"] = _is_using_default_config(payload["config_file_path"])

    try:
        merged_tuple = _sm.get_web_ui_config()

        merged = merged_tuple[0] if isinstance(merged_tuple, tuple) else merged_tuple
        web_ui_section.update(
            {
                "host": merged.host,
                "port": merged.port,
                "language": merged.language,
            }
        )
    except Exception as exc:
        logger.debug(
            f"--print-config: get_web_ui_config 失败，跳过 merge overlay: {exc!r}"
        )

    sections_full["web_ui"] = web_ui_section

    payload["web_ui"] = web_ui_section

    payload["sections"] = _redact_sensitive(sections_full)

    payload["web_ui"] = _redact_sensitive(web_ui_section)

    active_env: dict[str, str] = {}
    try:
        for env_name in (
            _sm._ENV_WEB_UI_HOST,
            _sm._ENV_WEB_UI_PORT,
            _sm._ENV_WEB_UI_LANGUAGE,
        ):
            raw = os.environ.get(env_name)
            if raw is None:
                continue
            stripped = raw.strip()
            if stripped:
                active_env[env_name] = stripped
    except Exception as exc:
        logger.debug(f"--print-config: os.environ 访问失败: {exc!r}")
    payload["env_overrides"] = active_env

    print(_json.dumps(payload, ensure_ascii=False, indent=2), flush=True)
    return 0


def main(argv: list[str] | None = None) -> None:
    """MCP 服务器主入口函数"""

    if argv is not None:
        ns = _build_arg_parser().parse_args(argv)

        if getattr(ns, "print_config", False):
            sys.exit(_print_effective_config())

    mcp_logger = _stdlib_logging.getLogger("mcp")
    mcp_logger.setLevel(_stdlib_logging.WARNING)

    fastmcp_logger = _stdlib_logging.getLogger("fastmcp")
    fastmcp_logger.setLevel(_stdlib_logging.WARNING)

    middleware_names = [type(mw).__name__ for mw in mcp.middleware]
    logger.warning(
        f"event=server.boot version={_resolve_server_version()} "
        f"transport=stdio mcp_name={mcp.name!r} "
        f"python={sys.version.split()[0]} "
        f"middleware={','.join(middleware_names)}"
    )

    max_retries = 3
    retry_count = 0
    _RETRY_BASE_DELAY_SECONDS = 1.0
    _RETRY_MAX_DELAY_SECONDS = 4.0
    _RETRY_JITTER_RATIO = 0.5

    while retry_count < max_retries:
        try:
            if retry_count > 0:
                logger.info(f"尝试重新启动 MCP 服务器 (第 {retry_count + 1} 次)")

            mcp.run(transport="stdio", show_banner=False)

            logger.info("MCP 服务器正常退出")
            break

        except KeyboardInterrupt:
            logger.info("收到中断信号，正在关闭服务器")
            cleanup_services()
            break

        except Exception as e:
            retry_count += 1
            logger.error(
                f"MCP 服务器运行时错误 (第 {retry_count}/{max_retries} 次): {e}",
                exc_info=True,
            )

            if retry_count < max_retries:
                cleanup_services(shutdown_notification_manager=False)

                base = min(
                    _RETRY_BASE_DELAY_SECONDS * (2 ** (retry_count - 1)),
                    _RETRY_MAX_DELAY_SECONDS,
                )
                jitter = random.uniform(0.0, base * _RETRY_JITTER_RATIO)
                delay = base + jitter
                logger.warning(
                    f"将在 {delay:.2f}s 后尝试重启服务器（指数退避 + jitter）..."
                )
                time.sleep(delay)
            else:
                cleanup_services(shutdown_notification_manager=True)
                logger.error(f"达到最大重试次数 ({max_retries})，服务退出")
                sys.exit(1)


def _cli_main() -> None:
    """PyPA console_script 入口（``[project.scripts]`` 注册到此函数）。"""
    main(sys.argv[1:])


if __name__ == "__main__":
    _cli_main()
