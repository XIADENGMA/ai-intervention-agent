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
    "_make_resubmit_response",
    "_print_effective_config",
    "_process_image",
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
import threading  # used for server.threading.main_thread (tests patch this) + _sse_stats_cache_lock
import time

# R62：进程启动时戳（unix epoch 秒）。在 module import 时即被赋值，所以
# 它代表的是「server module 第一次被加载的时刻」——对一个 ``python -m
# server`` / ``uvx`` / fastmcp run 的进程，这一刻就是「进程开始干活」的
# 时间，足以作为 uptime 计算的基线。
# 这个值在整个进程生命周期中恒定不变，不持锁、不重置。
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

    # 使用 setattr 避免类型检查器将该赋值视为“覆盖/遮蔽”类定义
    setattr(rich_console_module, "Console", SilentConsole)  # noqa: B010
except ImportError:
    pass


def _resolve_server_version() -> str:
    """读取已安装包版本号，失败时返回开发占位符。

    通过 MCP initialize 协议暴露给 client，方便 client 做兼容判断 / 调试日志。
    """
    try:
        from importlib.metadata import PackageNotFoundError
        from importlib.metadata import version as _pkg_version

        try:
            return _pkg_version("ai-intervention-agent")
        except PackageNotFoundError:
            return "0.0.0+local"
    except Exception:
        return "0.0.0+local"


# R63：build 元信息（git commit / branch / dirty 状态）。
# ============================================================================
# 与 R62 ``runtime`` 互补：``runtime`` 给 Python 解释器视角，``build`` 给源码
# 视角——「这个 process 跑的是哪个 commit、是不是 dirty 工作树」。这是
# 生产 issue triage 的标配，比 ``version`` 字符串精确：``v1.5.45`` 可能对
# 应过 100 个 commit，但 ``git_commit=fa6f49d`` 只对应一份代码。
#
# 实现策略：
# - **Lazy 加 cache**：第一次调用 ``_resolve_build_info()`` 时一次性 fork
#   git subprocess（3 个），结果缓存到 ``_BUILD_INFO_CACHE``。后续调用直接
#   返回 dict 浅拷贝。对 server_info_resource 这种被频繁拉取的端点，避免
#   每次都启动 3 个 ``git`` subprocess。
# - **失败 graceful**：pip install / docker / pyinstaller 部署没有 ``.git``
#   目录，``git`` subprocess 会失败，cache 里就存 ``"unknown"``。client UI
#   不应当把 ``unknown`` 当告警。
# - **超时保护**：每个 ``git`` subprocess 限 2 s，防 corrupt repo 卡死整个
#   server_info 端点。
# - **Thread-safe**：双重检查锁定，避免多个 fastmcp task 同时 fork 3×N 个
#   git subprocess。
_BUILD_INFO_CACHE: dict[str, str] = {}
_BUILD_INFO_CACHE_LOCK: threading.Lock = threading.Lock()


def _resolve_build_info() -> dict[str, str]:
    """返回 ``{git_commit, git_branch, git_dirty}``，失败字段填 ``"unknown"``。

    Thread-safe + lazy + 单次缓存：第一次拿到的结果在整个进程生命周期内不
    会变（即使工作树后续被改了，cache 也不刷——这与 ``_PROCESS_STARTED_AT_UNIX``
    的语义一致：「我跑起来时是哪个 commit」）。

    返回 dict 是拷贝；调用方修改不影响 module-level cache。
    """
    global _BUILD_INFO_CACHE
    if _BUILD_INFO_CACHE:
        return dict(_BUILD_INFO_CACHE)

    with _BUILD_INFO_CACHE_LOCK:
        # 双重检查：进入锁后再看一次 cache，防止多个 thread 同时穿透
        if _BUILD_INFO_CACHE:
            return dict(_BUILD_INFO_CACHE)

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
        # ``git status --porcelain`` 输出非空 = 工作树 dirty
        # 这里检查的是工作树状态，不是 cache；空字符串 = clean。
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
        return dict(cache)


def _build_server_icons() -> list[Icon]:
    """启动时一次性把本地 icons 转成 data URI，让 server icons 完全 self-contained。

    设计取舍：
    - 使用 base64 data URI 而不是 GitHub raw URL，避免对 main 分支 push 状态的依赖
      （已发布版本即使 main 上图标资源被删，client 仍能渲染图标）
    - 多尺寸覆盖：32/192/512 + SVG，让 client UI 按显示密度自选
    - 总开销 ~17KB（base64 化），仅在 initialize 一次性下发，可忽略
    - 任何 icon 文件缺失时跳过，不影响 server 启动
    """
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
            # 单个图标失败不阻塞 server 启动
            continue
    return icons


# Server-level icons：让 ChatGPT Desktop / Claude Desktop / Cursor 等 client UI
# 在 MCP 服务器列表中显示项目图标，用户能直观区分多个 server。
_SERVER_ICONS: list[Icon] = _build_server_icons()

# MCP server 身份信息：name + instructions + version + website_url + icons
# - name：客户端工具列表显示
# - instructions：在 initialize 协议响应中下发，指导 LLM "什么时候用 / 什么时候不用"
#   这是让 LLM agent 正确选用工具最关键的一处文档
# - version：暴露给 client，便于做能力协商 / 故障排查
# - website_url：项目主页，client UI 可链接，方便用户查阅文档 / 反馈问题
# - icons：server-level 图标，client UI 用来在服务器列表中标识本服务
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
        "- 阻塞直到用户提交、自动重提示倒计时触发或后端超时。\n\n"
        "用户可以附上文字、选项和图片；返回值是 MCP 内容块（text + image）的列表。"
    ),
    version=_resolve_server_version(),
    website_url="https://github.com/xiadengma/ai-intervention-agent",
    icons=_SERVER_ICONS,
)
logger = EnhancedLogger(__name__)

# interactive_feedback / FeedbackServiceContext 等反馈逻辑已移至 server_feedback.py。
# 这里负责：1) 以 mcp 实例注册工具；2) re-export 保持向后兼容。
from ai_intervention_agent.server_feedback import (
    FeedbackServiceContext,
    launch_feedback_ui,
    wait_for_task_completion,
)
from ai_intervention_agent.server_feedback import (
    interactive_feedback as _interactive_feedback_impl,
)

# MCP 工具行为提示 (Tool Annotations，遵循 MCP spec 2025-11-25)
# ToolAnnotations 自 2024-11-05 引入，2025-11-25 仍向后兼容；当前 mcp SDK
# 1.26.x 的 ``LATEST_PROTOCOL_VERSION = "2025-11-25"``，README/docs 与代码
# 在 r44/r45 一致性 audit 中统一对齐到这一版本。
# 让 client (ChatGPT / Claude Desktop / Cursor) 准确理解 interactive_feedback 的副作用面：
# - 不修改源代码 / git / 数据库；只持久化任务事件并触发通知 -> 严格意义不是只读，readOnly=False
# - 不删除/覆盖任何用户资源 -> destructive=False，client 无需弹"危险操作"二次确认
# - 每次调用产生新任务事件 -> 非幂等
# - 与外部用户和通知服务交互 -> openWorld=True
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

# R37 FastMCP 最佳实践：注册 ErrorHandlingMiddleware
# ===================================================
#
# 缘由：FastMCP 3.x 官方推荐生产 server 把 `ErrorHandlingMiddleware` 作为
# 整条中间件链的最外层（参见 https://gofastmcp.com/servers/middleware §
# 「Execution Order」），让 *所有* 下游异常（包括 FastMCP 自带的
# DereferenceRefsMiddleware 在解析 schema $ref 时可能抛出的异常）都先经过它，
# 被统一捕获、按 MCP 错误码分类、写进 stderr 日志，并按
# `{error_type}:{method}` 累计计数，方便 client UI / 运维事后定位高频异常面。
#
# 实现细节：
#   - FastMCP 把所有 middleware 放在 `mcp.middleware: list[Middleware]`，运行
#     时按 `for mw in reversed(self.middleware): chain = partial(mw, ...)` 反向
#     折叠成洋葱链。也就是说 **list 中靠前 = 越靠外**（第一个先跑）。
#     `add_middleware()` 是 `append`，而我们要把 ErrorHandling 摆在最外层
#     以便兜住 DereferenceRefsMiddleware（FastMCP 在 __init__ 时已 append 进去），
#     因此必须用 `insert(0, ...)` 而不是 `add_middleware()`。
#   - 用独立 logger ``ai_intervention_agent.fastmcp_errors`` 而不是默认的
#     ``fastmcp.errors``：和项目其它子系统的 logger 命名空间对齐，运维
#     ``grep '^.*ai_intervention_agent\.' stderr.log`` 能拿到完整一面镜；
#     即便未来把 ``fastmcp`` 整体静音，本插件 error 日志依然会通过 root logger
#     落到 stderr handler。
#   - ``include_traceback=False``：默认只记一行紧凑日志（``Error in tools/call:
#     ValueError: ...``）。完整 traceback 在 ``server_feedback`` 自己的 try/
#     except 里已经用 ``logger.error(..., exc_info=True)`` 写过一份，不重复输
#     出避免日志噪音。
#   - ``transform_errors=True``：把 ``ValueError`` / ``TypeError`` / ``KeyError``
#     等裸异常映射成 ``McpError(-32602 Invalid params)`` 等标准错误码，client
#     端（Cursor / ChatGPT Desktop）能直接渲染合适提示而不是字符串拼接。
#     注意：``McpError`` 自身会被原样透传，不会被二次转换 / 计数为 unknown。
#   - 单例存储 ``_ERROR_HANDLING_MIDDLEWARE``：测试 / 运维入口可通过
#     ``server.get_mcp_error_stats()`` 查到累计计数，回归契约靠
#     ``tests/test_fastmcp_middleware_r37.py`` 静态检查。
from fastmcp.server.middleware.error_handling import ErrorHandlingMiddleware

_ERROR_HANDLING_MIDDLEWARE: ErrorHandlingMiddleware = ErrorHandlingMiddleware(
    logger=_stdlib_logging.getLogger("ai_intervention_agent.fastmcp_errors"),
    include_traceback=False,
    transform_errors=True,
)
mcp.middleware.insert(0, _ERROR_HANDLING_MIDDLEWARE)


def get_mcp_error_stats() -> dict[str, int]:
    """返回 MCP 中间件累计的异常计数（``{error_type}:{method}`` → 次数）。

    供运维 / 测试在不污染 server 进程的情况下抽样诊断热点异常路径。
    返回的是副本，外部修改不会影响内部累加器。
    """
    return _ERROR_HANDLING_MIDDLEWARE.get_error_stats()


# R40 FastMCP 最佳实践：注册 Timing + Logging 中间件
# ===================================================
#
# 缘由：FastMCP 3.x 官方推荐生产 server 至少叠加这三层中间件——
# ``ErrorHandling`` / ``Timing`` / ``Logging``（参见 §「Combine Multiple
# Middleware」官方示例）。R37 已经把 ErrorHandling 接成最外层，本批次（r40）
# 补齐另外两层：
#
# - ``TimingMiddleware``：每个 ``request``（``tools/call`` / ``resources/read``
#   等）执行后写一行 ``Request <method> took X.XX ms`` 到 stderr，让运维 /
#   QA 能在不改业务代码的情况下抓 tool latency 异常（例如 web_ui 启动卡顿、
#   通知后端 timeout）；
# - ``LoggingMiddleware``：在 request 进入 / 退出时写结构化日志。开 ``include_
#   payload_length=True`` 但不开 ``include_payloads``——payload 里可能含用户
#   隐私（``message`` 字段是 LLM 与人类的对话），仅记长度足以诊断"工具被调用
#   了多少次、payload 大小分布"，又不会把对话内容落到磁盘。
#
# 顺序（``mcp.middleware`` 列表，前 = 外层）：
#   ``[ErrorHandling, DereferenceRefs(FastMCP 内置), Timing, Logging]``
# 也就是说运行链：
#   ``ErrorHandling → DereferenceRefs → Timing → Logging → handler``
# 这个排布让：
#   * Timing 测到的耗时不包含 ErrorHandling 的 try/except 建栈开销（micro），
#     但包含 handler + 内层 logging 序列化（合理，整体感受耗时）；
#   * Logging 在最内层看到的是已经 dereferenced 的 schema，日志噪音最小；
#   * 任何中间件自身抛异常都会被外层 ErrorHandling 兜住，不污染 stdio 通道。
#
# 日志默认级别 INFO（``log_level=20``）。项目根 logger 已设为 WARNING，所以
# 默认情况下两个中间件**不会输出**——按需把
# ``ai_intervention_agent.fastmcp_requests`` / ``ai_intervention_agent.fastmcp_timing``
# 单独提升到 INFO 即可开启 tracing，无需重启 server。
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


# R44 FastMCP 最佳实践：注册 RateLimitingMiddleware
# ===================================================
#
# 缘由：FastMCP 3.x 把 ``ErrorHandling`` / ``RateLimiting`` / ``Timing`` /
# ``Logging`` 称为生产 server 的「四件套」（参见
# https://gofastmcp.com/servers/middleware §「Combine Multiple Middleware」
# 官方示例）。R37 / R40 已补齐除 RateLimiting 之外的三件，本批次（r44）
# 收尾。
#
# 工具语义决定阈值：
#   - ``interactive_feedback`` 是阻塞工具，LLM 一旦调用就进入「等用户回复」
#     的真人环节，正常使用频率远低于每秒一次。
#   - 但 LLM 失控（bug / prompt 注入 / 错误重试逻辑）时可能在毫秒级反复
#     调用同一工具，触发 web_ui 子进程冷启动 / 通知风暴 / SSE 历史溢出，
#     给运维和用户都带来真实痛感。
#   - ``max_requests_per_second=10`` + ``burst_capacity=20`` 的 token bucket：
#     正常人类操作场景永远命中不到限流（用户提交→LLM 重新调，间隔通常 1s+），
#     但能在 LLM 死循环时把热点请求限制在合理范围、给运维报警留窗口。
#   - ``RateLimitError`` 被外层 ``ErrorHandlingMiddleware`` 兜住、按 method
#     计数为 ``RateLimitError:tools/call``，client UI 会拿到一行结构化错误
#     而不是字符串，便于人类 / agent 快速辨识"被限流了"。
#
# 顺序（``mcp.middleware`` 列表，前 = 外层）：
#   ``[ErrorHandling, RateLimiting, DereferenceRefs, Timing, Logging]``
# 也就是说运行链：
#   ``ErrorHandling → RateLimiting → DereferenceRefs → Timing → Logging``
# 关键点：``RateLimiting`` 在 ``DereferenceRefs`` 之前，限流命中时无需付
# schema 解析的开销；同时被外层 ``ErrorHandling`` 转换为标准 MCP 错误码
# 让 client 能正常渲染。
from fastmcp.server.middleware.rate_limiting import RateLimitingMiddleware

_RATE_LIMITING_MIDDLEWARE: RateLimitingMiddleware = RateLimitingMiddleware(
    max_requests_per_second=10.0,
    burst_capacity=20,
)
# ``insert(1, ...)`` 是把 RateLimiting 摆在 ErrorHandling（位置 0）之后、
# DereferenceRefs / Timing / Logging 之前——按 FastMCP 反向折叠规则，最终
# 实际执行顺序就是「ErrorHandling 最外、RateLimiting 紧随其后」。
mcp.middleware.insert(1, _RATE_LIMITING_MIDDLEWARE)


# R40 FastMCP 最佳实践：暴露 server 自检 resource
# ===================================================
#
# 让 client（Cursor / Claude Desktop / ChatGPT Desktop）通过 MCP `resources/
# read` 读取 ``aiia://server/info`` 拿到本服务器的 self-information：
#
#   - ``version`` / ``name``：与 initialize 协议一致，用于跨工具调试比对；
#   - ``transport``：当前传输（固定 stdio，未来若开 streamable-http 会变）；
#   - ``error_stats``：来自 ErrorHandlingMiddleware 的累计计数，运维快速看
#     "最近哪一类异常最频繁"；
#   - ``web_ui``：本服务的核心副服务（用户交互所在），best-effort 检测端口
#     是否在监听，让 client 一眼看出"反馈 UI 启不起来"还是"启起来了但是 LLM
#     没拿到回复"。
#
# 设计取舍：
#   - 同步函数：FastMCP resource 支持 sync/async 两种，sync 实现简单；
#   - best-effort：``web_ui`` 检查任何异常都吞掉，永远返回有效 dict 让 client
#     UI 不会在自检页面渲染崩溃；
#   - 不触发 web_ui 启动：本 resource 是只读自检，**不应**有副作用（不调用
#     ``ensure_web_ui_running``），否则会让"读自检页面"变成"启动整套服务"。
# R54-A：SSE-stats 跨进程 GET 的 1.0s TTL cache
# ============================================================================
# 缘由：``server_info_resource`` 暴露 sse_bus 子块需要去 web_ui 子进程拉
# ``/api/system/sse-stats``。client UI（PWA / VSCode webview）会高频 poll
# self-info（fast refresh / status badge tick），如果每次都 fire 一次 httpx，
# 会很快撞穿 sse-stats 的 60/min 速率限流，让真正用 sse-stats 的页面看到
# 429 错误。
#
# 解决：用一个 module-level dict + 单调时间戳做 1.0 秒 TTL 缓存。命中 cache
# 时不发 HTTP，未命中才发；只有成功结果写 cache（失败不写，让下次立刻重试）。
# 锁粒度只护读写 cache 元数据，``httpx.get`` 在锁外，避免一个慢请求把所有
# 并发 caller 串行起来。
#
# 这层缓存的数据**不可信任为 fresh**：如果 caller 关心毫秒级精度（不存在的
# 场景），应该绕开 self-info 直接打 sse-stats。本 cache 服务的是
# "sub-second cadence 的 client tick" 场景，1 秒粒度足够给 LLM / 人类阅读。
_SSE_STATS_CACHE_TTL_S: float = 1.0
_sse_stats_cache: dict[str, object] = {}
_sse_stats_cache_ts: float = 0.0
_sse_stats_cache_lock: threading.Lock = threading.Lock()


def _fetch_sse_stats_cached(host: str, port: int) -> dict[str, object]:
    """1.0s TTL 包装 GET /api/system/sse-stats（R54-A）。

    返回值约定（永远是新建 dict，绝不返回内部缓存引用）：
    - 成功：``{emit_total, latest_event_id, gap_warnings_emitted,
      backpressure_discards, subscriber_count, history_size}``，可能附
      ``cached: True`` 标志（命中 cache）；
    - 失败：``{error: "<type>: <msg>"}`` 或 ``{error: "sse-stats HTTP 429"}``
      / ``{error: "sse-stats response not success: ..."}``。

    线程安全：cache 的 read-modify-write 受单一 ``threading.Lock`` 保护；
    实际网络调用（httpx.get）在锁外执行，避免一个慢请求阻塞所有 caller。
    """
    global _sse_stats_cache_ts
    now = time.monotonic()
    with _sse_stats_cache_lock:
        age = now - _sse_stats_cache_ts
        if _sse_stats_cache and age < _SSE_STATS_CACHE_TTL_S:
            cached_copy = dict(_sse_stats_cache)
            cached_copy["cached"] = True
            cached_copy["cache_age_s"] = round(age, 3)
            return cached_copy

    target_url = f"http://{host}:{port}/api/system/sse-stats"
    result: dict[str, object] = {}
    try:
        import httpx

        # 500 ms 上限：覆盖 loopback + 一次 round-trip 的 worst case。
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
                "emit_by_type",  # R61: per-event-type histogram
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


# R55：``recent_logs`` 跨进程拉取的 1.0s TTL cache（与 R54-A 同思路）。
# ============================================================================
# 缘由：``server_info_resource`` 的 ``recent_logs`` 子块需要从 web_ui 子进程
# 拉一份 ``/api/system/recent-logs``。这个端点限流 30/min，比 sse-stats 还
# 紧；client UI 任何 sub-second polling 都能在十秒内打穿。沿用 R54-A 的
# success-only / fine-grained-lock / always-fresh-copy 设计。
_RECENT_LOGS_CACHE_TTL_S: float = 1.0
_recent_logs_cache: dict[str, object] = {}
_recent_logs_cache_ts: float = 0.0
_recent_logs_cache_lock: threading.Lock = threading.Lock()


def _fetch_recent_logs_cached(
    host: str, port: int, limit: int = 20
) -> dict[str, object]:
    """1.0s TTL 包装 GET /api/system/recent-logs（R55）。

    返回值约定：
    - 成功：``{entries: list[dict], count: int}``，可能附 ``cached: True``；
    - 失败：``{error: ...}``。永远是新建 dict。

    注意 ``limit`` 进 cache key 一起：不同 limit 视作不同请求，避免一个
    limit=20 的请求填了 cache 后，limit=50 命中误得到 truncated entries。
    """
    global _recent_logs_cache_ts
    now = time.monotonic()
    cache_key = f"limit={int(limit)}"
    with _recent_logs_cache_lock:
        age = now - _recent_logs_cache_ts
        if (
            _recent_logs_cache
            and age < _RECENT_LOGS_CACHE_TTL_S
            and _recent_logs_cache.get("_key") == cache_key
        ):
            cached_copy = {k: v for k, v in _recent_logs_cache.items() if k != "_key"}
            cached_copy["cached"] = True
            cached_copy["cache_age_s"] = round(age, 3)
            return cached_copy

    target_url = f"http://{host}:{port}/api/system/recent-logs?limit={int(limit)}"
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
                _recent_logs_cache["_key"] = cache_key
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
    """Return diagnostic self-information for this MCP server.

    R44 增强（仍然 best-effort，每一个子段都被独立 try/except 包住）：

    - ``runtime``：``python_version`` / ``python_executable`` / ``platform``，
      让运维诊断 "用 uv 还是 pipx 起的"、"哪个 interpreter"，无需 ssh 上去
      跑 ``which python``；
    - ``fastmcp``：直接读 ``importlib.metadata`` 报本地装的 fastmcp 版本，
      跨 client 比对兼容性时用得上；
    - ``middleware``：每个中间件的类名，按运行顺序排列。让 client 端能直
      观看到链路是否被外部 hook 改过，定位"为啥我没看到 timing 日志"这种
      问题；
    - ``task_queue``：当前队列长度（best-effort，不实例化新单例），让
      client 一眼看到"是不是有积压任务没人处理"。
    """
    info: dict[str, object] = {
        "name": mcp.name,
        "version": _resolve_server_version(),
        "transport": "stdio",
        "error_stats": get_mcp_error_stats(),
    }

    # R63：build 元信息（git commit / branch / dirty）
    # 给 issue triage 的精确锚点：``version`` 是 1.5.x 的 release 号（人类
    # 可读），``build`` 是 commit hash + branch（机器可读）。两者一起回答
    # 「这个 process 跑的是哪个 commit」。
    try:
        info["build"] = _resolve_build_info()
    except Exception as build_exc:
        info["build"] = {"error": f"{type(build_exc).__name__}: {build_exc}"}

    # R44 + R62：runtime 元信息块。
    # ----------------------------------------------------------------------
    # R44 起初只有 3 个字段（python_version / python_executable / platform 单
    # 行串）。R62 在原块上扩展进 ``python_implementation`` / ``started_at_unix``
    # / ``uptime_seconds`` 三个新字段——这些是 OS-level ``process`` 块（R60）
    # 之外、Python-level 的运行时元信息：哪个解释器实现、何时启动、跑了多久。
    # 整个块仍然在一个 try 里，任一字段失败都走 ``error`` 兜底，不影响顶层
    # ``info`` 的其他块。
    runtime_info: dict[str, object] = {}
    try:
        import platform as _platform

        runtime_info["python_version"] = sys.version.split()[0]
        runtime_info["python_executable"] = sys.executable
        runtime_info["platform"] = (
            f"{_platform.system()} {_platform.release()} ({_platform.machine()})"
        )
        # R62：新增字段，与上面 3 个老字段共存。``platform`` 单行串依然适合
        # 给 client UI 一行展示；新加的 ``python_implementation`` 让运维一
        # 眼分清 CPython / PyPy / Jython（生产偶发会有人 pin 错），而
        # ``uptime_seconds`` / ``started_at_unix`` 是「这个 process 跑了多
        # 久」的标准 SRE 指标。
        runtime_info["python_implementation"] = _platform.python_implementation()
        runtime_info["started_at_unix"] = round(_PROCESS_STARTED_AT_UNIX, 3)
        runtime_info["uptime_seconds"] = round(
            time.time() - _PROCESS_STARTED_AT_UNIX, 3
        )
    except Exception as runtime_exc:
        runtime_info["error"] = f"{type(runtime_exc).__name__}: {runtime_exc}"
    info["runtime"] = runtime_info

    # R60：进程级运行时指标 —— RSS / 用户 CPU 时间 / 线程数 / 文件描述符数。
    # 注意 ``platform`` 模块在 ``runtime_info`` 块里是 ``import platform as _platform``
    # 局部绑定的，作用域只在那个 ``try`` 内。这里再 import 一次给本块自己用。
    # ----------------------------------------------------------------
    # 让 client UI 在不外接 ``ps`` / ``htop`` / Grafana 的情况下也能看到
    # "MCP host 进程占多少内存、跑了多久 CPU、有多少线程"——这些是判断
    # 内存泄漏 / 线程逃逸 / FD 泄漏的最快入口。
    #
    # 不引入 ``psutil`` 依赖：用 stdlib ``resource`` + ``os``。
    # - ``resource.getrusage(RUSAGE_SELF)``：跨平台（macOS / Linux），
    #   ``ru_maxrss`` 单位 macOS 是 byte / Linux 是 KB —— 这里统一
    #   normalize 到 byte，client UI 拿到的字段单位永远一致；
    # - ``threading.active_count()`` / ``os.getpid()`` 都是 stdlib，
    #   零依赖；
    # - ``len(os.listdir('/proc/self/fd'))`` 是 Linux 专属，macOS 没
    #   ``/proc``，会 fallback 到 ``-1`` 表示 unsupported。
    # 任何子项失败都局部 ``error`` 不影响主块。
    process_info: dict[str, object] = {}
    try:
        import platform as _proc_platform

        process_info["pid"] = os.getpid()
        process_info["thread_count"] = threading.active_count()
        try:
            import resource as _resource

            ru = _resource.getrusage(_resource.RUSAGE_SELF)
            # ru_maxrss 单位差异：macOS bytes / Linux KB。判断方式：
            # 若 system 是 Darwin 直接当 bytes；否则按 KB × 1024 转 bytes。
            # 这样 client UI 永远看到 bytes 单位的 ``rss_bytes``。
            if _proc_platform.system() == "Darwin":
                process_info["rss_bytes"] = int(ru.ru_maxrss)
            else:
                process_info["rss_bytes"] = int(ru.ru_maxrss) * 1024
            process_info["user_cpu_seconds"] = round(ru.ru_utime, 3)
            process_info["sys_cpu_seconds"] = round(ru.ru_stime, 3)
        except Exception as ru_exc:
            process_info["resource_error"] = f"{type(ru_exc).__name__}: {ru_exc}"

        try:
            # Linux fd 数：``/proc/self/fd`` 目录下条目数 = 打开文件描述符
            # 数（含 socket、pipe、log file 等）。macOS / Windows 没 ``/proc``，
            # 这里 ``-1`` 表示 unsupported（client UI 应当展示成 "n/a" 而不是
            # 警报）。
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

    # task_queue snapshot —— 走 ``task_queue_singleton`` 而不是 ``server.get_task_queue``
    # 的实例化路径：本 resource 是"只读自检"，绝不应该因为读自检页面导致
    # 全局单例被构造出来（特别是 web_ui 子进程在用一份独立的单例的时候，
    # MCP server 进程读自检页不该副作用一份新队列）。``_global_task_queue``
    # 是 ``Optional[TaskQueue]``，None 表示尚未构造。
    task_queue_info: dict[str, object] = {}
    try:
        import ai_intervention_agent.task_queue_singleton as _tq_singleton

        existing = getattr(_tq_singleton, "_global_task_queue", None)
        if existing is None:
            task_queue_info["initialized"] = False
        else:
            task_queue_info["initialized"] = True
            try:
                # 新版 TaskQueue 暴露 ``size()`` / ``pending_count()``，但为了向后
                # 兼容（万一旧分支没有），这里 best-effort 探测，缺什么写什么。
                size_attr = getattr(existing, "size", None)
                if callable(size_attr):
                    task_queue_info["size"] = int(size_attr())
                pending_attr = getattr(existing, "pending_count", None)
                if callable(pending_attr):
                    task_queue_info["pending"] = int(pending_attr())
            except Exception as q_probe_exc:
                task_queue_info["probe_error"] = (
                    f"{type(q_probe_exc).__name__}: {q_probe_exc}"
                )
    except Exception as tq_exc:
        task_queue_info["error"] = f"{type(tq_exc).__name__}: {tq_exc}"
    info["task_queue"] = task_queue_info

    # R47：interactive_feedback 累计计数器。``server_feedback`` 顶层已经
    # 被 ``server.py`` import（见上方 ``from server_feedback import ...``），
    # 这里 ``getattr`` 拿单例 dict，避免重复 import 触发任何副作用。
    feedback_counters_info: dict[str, object] = {}
    try:
        import ai_intervention_agent.server_feedback as _sfb

        getter = getattr(_sfb, "get_feedback_counters", None)
        if callable(getter):
            feedback_counters_info = dict(getter())
        else:
            feedback_counters_info["error"] = (
                "get_feedback_counters not found on server_feedback"
            )
    except Exception as fb_exc:
        feedback_counters_info["error"] = f"{type(fb_exc).__name__}: {fb_exc}"
    info["interactive_feedback"] = feedback_counters_info

    # R50-A：SSE bus 计数器跨进程拉取
    # ----------------------------------------------------------------
    # 设计要点：
    # - SSE bus 是 ``web_ui_routes/task.py`` 模块级单例，跑在 web_ui 子进程
    #   里——MCP server 进程根本看不到它。所以这里走 HTTP best-effort：
    #   只有当 ``web_ui_info["running"]=True`` 时才尝试 GET 一次
    #   ``/api/system/sse-stats``。
    # - 短超时（500 ms）+ 任意异常吞掉：本 resource 的 sla 是"几十毫秒
    #   返回 dict"；万一 web_ui 在某个内部锁里 hang 住，不能让自检页面也
    #   一起 hang，宁可 sse_bus 块缺失。
    # - 不主动启动 web_ui：``web_ui_info["running"]`` 是上一段（R40 引入）
    #   通过 socket 探测得到的，不会触发 ensure_web_ui_running。读自检页
    #   仍是只读副作用。
    # - R54-A：``_fetch_sse_stats_cached`` 包了 1.0s TTL cache，避免 client UI
    #   高频 polling self-info（fast refresh / VSCode webview tick）时把
    #   ``/api/system/sse-stats`` 的 60/min 限流额度撞穿。命中 cache 时**完全
    #   不发请求**，未命中才发，并把成功结果写回；失败不写 cache 让下次重试。
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

    # R51-C / R55：最近 N 条 WARNING/ERROR 日志摘要（已脱敏，每条 ≤ 500 字符）。
    # 让 MCP client UI 在 server-info 页里直接看到"最近哪里出过错"，省去 ssh
    # 翻 stderr 的成本。
    #
    # R55 升级：跨进程聚合
    # - MCP server 进程的 ring 主要捕获 MCP-host / FastMCP middleware / 客户端
    #   交互层的告警（量很少，通常每天 0-3 条）；
    # - Web UI 子进程的 ring 才是真正的"业务故障源"——TaskQueue 锁告警、SSE
    #   bus backpressure、配置文件变更失败、Bark 推送失败、AppleScript 执行
    #   失败 等绝大多数 ERROR 都在那个 ring 里；
    # - 不聚合就等于 self-info 默认看不见 90% 的故障。这里把两边 ring 的 entries
    #   merge 成一份按 ts_unix 升序排列的列表，每条多一个 ``source`` 字段
    #   （``"mcp"`` / ``"web_ui"``）让 client UI 能一眼分辨故障来源。
    #
    # 跨进程拉取走 ``_fetch_recent_logs_cached``，复用 R54-A 的 1.0s TTL cache
    # 思路抑制 self-info 高频 polling 把 /api/system/recent-logs 的 30/min 限
    # 流额度撞穿。任何子获取失败都降级到 ``error`` 字段，绝不影响 mcp 侧的
    # entries 输出。
    recent_logs_info: dict[str, object] = {}
    try:
        from ai_intervention_agent.enhanced_logging import (
            get_recent_logs as _get_recent_logs,
        )

        mcp_entries: list[dict[str, object]] = []
        for ent in _get_recent_logs(limit=20):
            tagged = dict(ent)
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
                        tagged = dict(ent)
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

        # 合并按 ts_unix 升序，最新的在末尾。这样 client UI 可以直接 reverse
        # 显示成"最新事件在前"。如果 entries 没 ts_unix 字段（异常路径）保留
        # 末位，避免 sort key 异常。
        merged = mcp_entries + web_ui_entries
        merged.sort(key=lambda e: e.get("ts_unix", 0) if isinstance(e, dict) else 0)
        recent_logs_info["count"] = len(merged)
        recent_logs_info["entries"] = merged
    except Exception as log_exc:
        recent_logs_info["error"] = f"{type(log_exc).__name__}: {log_exc}"
    info["recent_logs"] = recent_logs_info

    return info


# R20.8 性能优化：TaskQueue 单例的实现已迁移到独立模块 ``task_queue_singleton``。
#
# 历史背景：``get_task_queue`` 仅由 Web UI 子进程使用（web_ui.py / web_ui_routes
# 会调用），但旧实现放在本模块导致 web_ui 子进程因 ``from server import
# get_task_queue`` 拖入整条 ``fastmcp`` / ``mcp`` / ``loguru`` 依赖链，凭空多
# 出约 310 ms 启动延迟。迁移后 Web UI 子进程改从 ``task_queue_singleton``
# 直接导入，跳过整个 MCP server 模块；本模块通过下方 re-export 保留公开 API
# ``server.get_task_queue`` / ``server._shutdown_global_task_queue``，外部调用
# 者无感知。
#
# 注：``server._global_task_queue`` 这个模块级变量**不再**在本模块定义——
# 测试代码若需要直接 patch 全局单例，应改写 ``task_queue_singleton._global_task_queue``。
from ai_intervention_agent.task_queue_singleton import (  # noqa: F401  (re-export for back-compat)
    _shutdown_global_task_queue,
    get_task_queue,
)


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
    cleanup_http_clients()

    try:
        svc_mgr = ServiceManager()
        svc_mgr.cleanup_all(shutdown_notification_manager=shutdown_notification_manager)
        logger.info("服务清理完成")
    except Exception as e:
        logger.error(f"服务清理失败: {e}", exc_info=True)


def _build_arg_parser() -> argparse.ArgumentParser:
    """构造 ``ai-intervention-agent`` 的 CLI 解析器。

    设计目标
    ----
    符合 PyPI CLI 事实标准（pip / ruff / uv / black 等）：
    ``--version`` / ``--help`` 必须可用，否则 ``uvx ai-intervention-agent
    --version`` 会卡进 MCP stdio loop 永远 hang，用户得 Ctrl+C 才能退。

    向后兼容
    ----
    无任何参数时（``argv == []``），parser 不报错，调用方继续走原
    ``mcp.run(transport="stdio")`` 路径——这是 MCP client (Cursor /
    Claude Desktop / mcp-cli) 调起 server 的默认调用形态。

    扩展点
    ----
    后续若要加 ``--log-level`` / ``--config-file`` 等运行时 flag，在此添加
    ``parser.add_argument`` 即可；但请注意：相同配置项已经有 env vars
    （``AI_INTERVENTION_AGENT_LOG_LEVEL`` / ``_CONFIG_FILE``）和
    ``config.toml`` 两条路径，加 CLI 会形成 3 套并存——增加用户认知
    负担。除非有强需求，否则避免重复造轮子。
    """
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


def _print_effective_config() -> int:
    """实现 ``--print-config``：dump merged config 到 stdout 后退出。

    输出内容
    --------
    一个 JSON object 含三个 top-level key：

    * ``config_file_path``：当前 ConfigManager 加载的文件绝对路径
      （与 ``/api/system/health`` 的同名字段、``find_config_file()``
      返回值一致）；
    * ``web_ui``：调用 ``service_manager.get_web_ui_config()`` 拿到
      的 **已 merge env override** 的 host / port / language——也就
      是进程实际会绑的地址，不是 ``config.toml`` 写的原值；
    * ``env_overrides``：当前生效的 web_ui env vars 名单（与
      ``/api/system/health`` 的 ``web_ui_env_overrides`` 字段语义
      一致）。

    R53-F 契约
    ----------
    与 health endpoint 同样的安全契约——``network_security`` 整段被
    ``ConfigManager.get_all()`` 显式过滤，**不会**dump 出 IP 白名单
    / CIDR / token 类敏感信息。

    返回码：0 = 成功打印，1 = 探测失败（仍输出一个 JSON object 带
    ``error`` 字段，让脚本能机器解析）。
    """
    import json as _json

    from ai_intervention_agent import service_manager as _sm
    from ai_intervention_agent.config_manager import get_config

    payload: dict[str, object] = {}
    try:
        cfg = get_config()
        config_file = getattr(cfg, "config_file", None)
        payload["config_file_path"] = str(config_file) if config_file else None
        all_config = cfg.get_all()
        web_ui_section = (
            dict(all_config.get("web_ui", {}))
            if isinstance(all_config.get("web_ui"), dict)
            else {}
        )
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

    try:
        merged_tuple = _sm.get_web_ui_config()
        # service_manager.get_web_ui_config() 历史签名是 (WebUIConfig, timeout)；
        # 我们只关心 WebUIConfig，timeout 单独看（多取一个字段不破坏向前兼容）
        merged = merged_tuple[0] if isinstance(merged_tuple, tuple) else merged_tuple
        web_ui_section.update(
            {
                "host": merged.host,
                "port": merged.port,
                "language": merged.language,
            }
        )
    except Exception as exc:
        # 故意继续渲染 partial payload —— 前面 get_config() 已经做了 hard-fail
        # 兜底，这里只是 service_manager 的 cache / merge layer 软失败，给
        # 用户 best-effort 输出仍然有用（至少能看到 config_file_path）。
        # 不算 silent failure：debug log 留下证据，运维能 grep。
        logger.debug(
            f"--print-config: get_web_ui_config 失败，跳过 merge overlay: {exc!r}"
        )
    payload["web_ui"] = web_ui_section

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
        # 极端罕见：chroot / sandbox 让 os.environ 抛异常。继续输出空 dict
        # 比整体崩好——env_overrides={} 与 health endpoint 的 fail-safe
        # 语义一致（参考 `_safe_web_ui_env_overrides`）。
        logger.debug(f"--print-config: os.environ 访问失败: {exc!r}")
    payload["env_overrides"] = active_env

    print(_json.dumps(payload, ensure_ascii=False, indent=2), flush=True)
    return 0


def main(argv: list[str] | None = None) -> None:
    """
    MCP 服务器主入口函数

    功能
    ----
    解析 CLI（``--version`` / ``--help``）后启动 FastMCP 服务器，使用 stdio
    传输协议与 AI 助手通信。包含自动重试机制，提高服务稳定性。

    参数
    ----
    argv : list[str] | None
        CLI 参数列表（不含 prog name）。默认 ``None`` 时 argparse 自动从
        ``sys.argv[1:]`` 取，与 console_script 入口的零参数调用契约一致。
        测试可以传 ``["--version"]`` / ``["-V"]`` / ``["--help"]`` /
        ``[]`` 等显式 argv 走分支。

    运行流程
    --------
    0. 解析 CLI 参数（``--version`` 会直接 ``sys.exit(0)``，不进入下面）
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
    - CLI 自省: ``ai-intervention-agent --version`` / ``--help``

    注意事项
    --------
    - 必须确保 stdout 仅用于 MCP 协议通信
    - 所有日志输出重定向到 stderr
    - 服务进程由 ServiceManager 管理，退出时自动清理
    - 重试机制可以自动恢复临时性错误
    - ``argparse`` 的 ``--version`` / ``--help`` 用 ``sys.exit(0)``
      退出，**绝不**会进入 stdio loop——避免 ``uvx
      ai-intervention-agent --version`` hang 死的常见 PyPI CLI footgun。

    向后兼容契约
    ------------
    **``argv is None`` 时跳过 CLI 解析**，直接走 stdio loop。这是为了
    保留 ``main()`` 零参数调用契约——历史上 ``test_server_functions``
    / ``test_server_main_retry_backoff`` / ``test_diagnostic_event_log_r40``
    都用 ``main()`` 不传 argv 来直接测试 stdio loop 启动行为，
    PyPA console_script wrapper 也是零参数调用 ``main()``。如果默认
    fallback 到 ``sys.argv[1:]``，pytest 自己的 ``sys.argv`` 会被错当
    成 server CLI flag，整套测试都会炸 ``argparse.SystemExit(2)``。

    需要 CLI 解析时（如 ``ai-intervention-agent --version``），由
    ``_cli_main()`` console_script 入口或 ``__main__`` 块显式传
    ``sys.argv[1:]`` 调用。
    """
    # ``argv is not None`` 才解析；保护 ``main()`` 零参数老契约。
    if argv is not None:
        ns = _build_arg_parser().parse_args(argv)
        # ``--print-config`` 是 dump-and-exit 操作（与 ``--version`` 同性
        # 质），所以在进入 stdio loop 前用 ``sys.exit`` 立即退出，避免
        # 把 dump 出来的 JSON 当成 MCP protocol 输出污染 stdio。
        if getattr(ns, "print_config", False):
            sys.exit(_print_effective_config())

    # 配置日志级别（在重试循环外，只配置一次）
    mcp_logger = _stdlib_logging.getLogger("mcp")
    mcp_logger.setLevel(_stdlib_logging.WARNING)

    fastmcp_logger = _stdlib_logging.getLogger("fastmcp")
    fastmcp_logger.setLevel(_stdlib_logging.WARNING)

    # R40 P0-S3：启动 banner —— 借鉴 cursor-count v0.4.5 设计，
    # 让"贴一段 stderr 输出"就能一眼看出"server 跑在哪个版本 / 哪个 transport
    # / 装了哪些中间件 / Python 版本是什么"。banner 只在 server 进程启动
    # 一次，对运行性能零影响。
    #
    # 走 ``logger.warning`` 而不是 ``logger.info``：项目 root logger 默认
    # WARNING，info banner 会被 sink 过滤掉。banner 是诊断必备信息，应当
    # 默认就打出来；用 WARNING 级别表示"这不是错误，只是一定要被看到的
    # 启动证据"，与项目其它子系统的 ``logger.warning`` 用法一致。
    middleware_names = [type(mw).__name__ for mw in mcp.middleware]
    logger.warning(
        f"event=server.boot version={_resolve_server_version()} "
        f"transport=stdio mcp_name={mcp.name!r} "
        f"python={sys.version.split()[0]} "
        f"middleware={','.join(middleware_names)}"
    )

    # 重试配置
    # 历史上是 ``time.sleep(1)`` 固定 1s 间隔，如果同一台机器同时跑多个 MCP
    # 实例（IDE 多 worker / Cursor + VS Code 同时调起），每次 mcp.run() 同
    # 类失败（例如 stdio EOF / 上游服务挂掉）后所有实例会在 t+1 / t+2 同步
    # 重试，撞向同一个下游资源 → thundering herd。
    #
    # 改成 ``base × 2^(n-1) + jitter`` 指数退避（行业最佳实践，AWS Architecture
    # Blog "Exponential Backoff and Jitter" / Google SRE Workbook §22）：
    #   - 第 1 次重试：1s + jitter[0, 0.5s)
    #   - 第 2 次重试：2s + jitter[0, 1.0s)
    # ``MAX_RETRIES = 3`` 仍然只允许 2 次重试（第 3 次失败就 exit），所以
    # cap 到 4s 在这里实际不会触发，但保留 upper bound 是 future-proof：
    # 如果未来把 MAX_RETRIES 调大，jitter 不会让单次等待无限增长。
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
                # 达到最大重试次数：准备退出进程，做全量清理
                cleanup_services(shutdown_notification_manager=True)
                logger.error(f"达到最大重试次数 ({max_retries})，服务退出")
                sys.exit(1)


def _cli_main() -> None:
    """PyPA console_script 入口（``[project.scripts]`` 注册到此函数）。

    setuptools / hatchling 生成的 console_script wrapper 等价于：

        from ai_intervention_agent.server import _cli_main
        sys.exit(_cli_main())

    **不会**把 ``sys.argv`` 传给入口函数（这是 PyPA 标准行为，与
    ``argparse.ArgumentParser().parse_args()`` 默认从 sys.argv 读的
    自动行为耦合）。本 wrapper 显式从 ``sys.argv[1:]`` 抽取 CLI argv
    后调 ``main(argv)``，让 ``main()`` 自己的零参数调用契约
    （= 直接走 stdio loop）不被破坏——见 ``main()`` docstring 里的
    「向后兼容契约」段落。
    """
    main(sys.argv[1:])


if __name__ == "__main__":
    # 显式 sys.argv[1:] 让 ``python -m ai_intervention_agent.server --version``
    # 与 ``ai-intervention-agent --version`` 走完全相同的 argparse 路径。
    _cli_main()
