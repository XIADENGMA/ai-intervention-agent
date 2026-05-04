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
    "_ensure_config_change_callbacks_registered",
    "_format_file_size",
    "_generate_task_id",
    "_guess_mime_type_from_data",
    "_invalidate_runtime_caches_on_config_change",
    "_make_resubmit_response",
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

import atexit
import io
import os
import sys
import threading
import time

from fastmcp import FastMCP
from mcp.types import Icon, ToolAnnotations

from enhanced_logging import EnhancedLogger
from server_config import (
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
from service_manager import (
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
from server_feedback import (
    FeedbackServiceContext,
    launch_feedback_ui,
    wait_for_task_completion,
)
from server_feedback import (
    interactive_feedback as _interactive_feedback_impl,
)

# MCP 工具行为提示 (Tool Annotations，遵循 MCP spec 2024-11-05+)
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

interactive_feedback = mcp.tool(annotations=_INTERACTIVE_FEEDBACK_ANNOTATIONS)(
    _interactive_feedback_impl
)

# TaskQueue 仅由 Web UI 子进程使用（web_ui.py / web_ui_routes 会调用 get_task_queue()）。
# MCP 服务器主进程中此函数从未被调用，因此不会创建 TaskQueue 实例或后台清理线程。
# 采用懒加载 + 双重检查锁定，确保线程安全且无不必要的资源消耗。
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
                from pathlib import Path

                persist_path = str(
                    Path(__file__).resolve().parent / "data" / "tasks.json"
                )
                _global_task_queue = TaskQueue(max_tasks=10, persist_path=persist_path)
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
