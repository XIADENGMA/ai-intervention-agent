"""反馈交互层 - interactive_feedback 工具实现、任务轮询与上下文管理。

该模块从 `server.py` 抽取反馈相关逻辑，避免在 MCP 入口文件里堆积业务代码。
注意：`interactive_feedback` 的 MCP 工具注册由 `server.py` 持有的 `mcp` 实例完成，
本模块内的 `interactive_feedback` 为“未装饰”的实现函数。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from pathlib import Path
from typing import Any, cast

import httpx
from fastmcp.exceptions import ToolError
from mcp.types import TextContent
from pydantic import Field

import server_config
import service_manager
from enhanced_logging import EnhancedLogger
from exceptions import (
    ServiceConnectionError,
    ServiceTimeoutError,
    ServiceUnavailableError,
    ValidationError,
)

logger = EnhancedLogger(__name__)


try:
    from notification_manager import NotificationTrigger, notification_manager
    from notification_models import NotificationType

    NOTIFICATION_AVAILABLE = True
    logger.info("通知系统已导入")
except ImportError as e:
    logger.warning(f"通知系统不可用: {e}", exc_info=True)
    NOTIFICATION_AVAILABLE = False


async def _close_orphan_task_best_effort(task_id: str, host: str, port: int) -> None:
    """R13·B1 · timeout / cancel 路径的 ghost-task 兜底清理。

    历史教训：``wait_for_task_completion`` 在 ``TimeoutError`` 路径仅返回
    ``_make_resubmit_response()`` 给 MCP 客户端，**不**通知 web_ui。
    后果：

        T0   AI invokes interactive_feedback → POST /api/tasks 加 task A
             → web_ui task_queue: A=ACTIVE
        T1+  user 离开，超过 backend_timeout（默认 600s）
        T2   server.py 这边 ``asyncio.wait_for`` TimeoutError
             → 返回 resubmit prompt 给 AI
             → web_ui task_queue: **A 仍 ACTIVE**
        T3   AI 收到 resubmit，重新 invoke interactive_feedback
             → POST /api/tasks 加 task B
             → web_ui: A=ACTIVE, B=PENDING
        T4   user 回来在前端看到的是 ``current_prompt``（绑定 active）
             = task A 的 prompt
        T5   user 提交反馈 → /api/submit → ``task_queue.complete_task(A)``
             → A=COMPLETED, B 升级为 ACTIVE 但 server.py 这边等的是 B
                的 SSE，永远等不到 → 又一次 timeout → 死循环。

    本函数 fire-and-forget POST ``/api/tasks/<task_id>/close`` 通知
    web_ui ``task_queue.remove_task(task_id)``，让 active 槽腾出来。
    所有失败（连接错 / HTTP 非 200 / 网络 timeout）一律吞掉只 debug 日志，
    因为父协程已经在 timeout / cancel 通道，cleanup 不该把它进一步阻塞。
    ``CancelledError`` 必须 re-raise，否则父 cancel 语义被吞，asyncio
    loop 关闭时会 warn。
    """
    close_url = f"http://{host}:{port}/api/tasks/{task_id}/close"
    try:
        cfg = service_manager.get_web_ui_config()[0]
        client = service_manager.get_async_client(cfg)
        # 2s timeout：足够 LAN/loopback 内一次 close；远超肯定是 web_ui 死了，
        # best-effort 放手即可。
        resp = await client.post(close_url, timeout=2)
        if resp.status_code == 200:
            logger.info(f"timeout/cancel 路径已清理 ghost task: {task_id}")
        else:
            # 404 通常是 web_ui 已经把它清掉了（用户主动 close 过一次或者
            # 后台清理 GC 提前命中），这是正常路径不报警；其它非 200 才警。
            level = logger.debug if resp.status_code == 404 else logger.warning
            level(f"清理 ghost task {task_id} 收到非 200: HTTP {resp.status_code}")
    except asyncio.CancelledError:
        # 父 cancel 优先 —— 不能在 cleanup 路径吞 cancel，会破坏 asyncio
        # 取消语义并触发 "Task was destroyed but it is pending!" 警告。
        raise
    except Exception as e:
        # httpx.HTTPError / 连接拒绝 / DNS 错 / 任何其它都进这里：cleanup
        # 是 best-effort，不该打断主路径返回 resubmit_response。
        logger.debug(f"清理 ghost task {task_id} 失败（已忽略，best-effort）: {e}")


async def wait_for_task_completion(task_id: str, timeout: int = 260) -> dict[str, Any]:
    """SSE 事件驱动 + HTTP 轮询保底等待任务完成。

    双通道并行：SSE 提供 <50ms 实时检测，HTTP 轮询（每 2s）作为 SSE 断连的安全网。
    任一通道检测到完成即终止另一通道。

    【R13·B1 ghost-task cleanup】timeout / 父 cancel 路径下，本函数会
    在 finally 中通过 ``_close_orphan_task_best_effort`` 通知 web_ui
    清理 ``task_queue`` 中的孤儿任务，避免重新 invoke 后旧 task 占着
    active 槽位让前端展示错乱的 prompt。
    """
    if timeout > 0:
        timeout = max(timeout, server_config.BACKEND_MIN)

    config, _ = service_manager.get_web_ui_config()
    target_host = server_config.get_target_host(config.host)
    api_url = f"http://{target_host}:{config.port}/api/tasks/{task_id}"
    sse_url = f"http://{target_host}:{config.port}/api/events"

    start_time_monotonic = time.monotonic()
    effective_timeout: float | None = float(timeout) if timeout > 0 else None

    logger.info(
        f"等待任务完成: {task_id}, "
        f"超时: {'无限等待' if timeout == 0 else f'{timeout}秒'}（SSE + 轮询）"
    )

    completion = asyncio.Event()
    result_box: list[Any] = [None]

    async def _fetch_result() -> dict[str, Any] | None:
        """获取已完成任务的结果，404 返回重调提示。"""
        try:
            cfg = service_manager.get_web_ui_config()[0]
            client = service_manager.get_async_client(cfg)
            resp = await client.get(api_url, timeout=2)
            if resp.status_code == 404:
                return server_config._make_resubmit_response(as_mcp=False)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("success") and data.get("task"):
                    task = data["task"]
                    if (
                        isinstance(task, dict)
                        and task.get("status") == "completed"
                        and task.get("result")
                    ):
                        return task["result"]
        except Exception as e:
            logger.debug(f"获取任务结果失败: {e}")
        return None

    async def _sse_listener() -> None:
        """SSE 实时通道：收到 task_changed(completed) 即通知完成。"""
        try:
            async with (
                httpx.AsyncClient() as sc,
                sc.stream(
                    "GET", sse_url, timeout=httpx.Timeout(None, connect=5.0)
                ) as resp,
            ):
                logger.debug(f"SSE 连接已建立: {task_id}")
                async for line in resp.aiter_lines():
                    if completion.is_set():
                        return
                    stripped = line.strip()
                    if not stripped.startswith("data: "):
                        continue
                    try:
                        ev = json.loads(stripped[6:])
                    except (json.JSONDecodeError, ValueError):
                        continue
                    if (
                        ev.get("task_id") == task_id
                        and ev.get("new_status") == "completed"
                    ):
                        logger.info(f"SSE 检测到任务完成: {task_id}")
                        r = await _fetch_result()
                        if r is not None:
                            result_box[0] = r
                        completion.set()
                        return
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.debug(f"SSE 监听失败（依赖轮询保底）: {e}")

    async def _poll_fallback() -> None:
        """HTTP 轮询保底：每 2s 检查一次，SSE 断开时仍能检测完成。"""
        _INTERVAL = 2.0
        while not completion.is_set():
            r = await _fetch_result()
            if r is not None:
                result_box[0] = r
                completion.set()
                return
            try:
                await asyncio.wait_for(completion.wait(), timeout=_INTERVAL)
                return
            except TimeoutError:
                pass

    sse_task = asyncio.create_task(_sse_listener())
    poll_task = asyncio.create_task(_poll_fallback())

    try:
        await asyncio.wait_for(completion.wait(), timeout=effective_timeout)
    except TimeoutError:
        elapsed = time.monotonic() - start_time_monotonic
        logger.error(f"任务超时: {task_id}, 等待 {elapsed:.1f}s")
        return cast(dict[str, Any], server_config._make_resubmit_response(as_mcp=False))
    finally:
        sse_task.cancel()
        poll_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await sse_task
        with contextlib.suppress(asyncio.CancelledError):
            await poll_task

        # R13·B1 ghost-task cleanup
        # 仅在没拿到 result 时才 close —— 拿到 result 说明 web_ui 已经
        # 通过 /api/submit → task_queue.complete_task 把 task 标记
        # completed 了，再 close 是 race（且后台 cleanup 线程会在 10s
        # 后 GC，不需要重复操作）。
        if result_box[0] is None:
            await _close_orphan_task_best_effort(task_id, target_host, config.port)

    if result_box[0] is not None:
        logger.info(f"任务完成: {task_id}")
        return cast(dict[str, Any], result_box[0])

    r = await _fetch_result()
    if r is not None:
        return r

    return cast(dict[str, Any], server_config._make_resubmit_response(as_mcp=False))


def launch_feedback_ui(
    summary: str,
    predefined_options: list[str] | None = None,
    task_id: str | None = None,
    timeout: int = 300,
) -> dict[str, Any]:
    """废弃：旧版 Python API，推荐使用 interactive_feedback() MCP 工具"""
    # 确保超时时间不小于300秒（0表示无限等待，保持不变）
    if timeout > 0:
        timeout = max(timeout, 300)
    try:
        # 自动生成唯一 task_id（task_id 参数将被忽略，始终使用自动生成）
        task_id = server_config._generate_task_id()

        # 验证输入参数
        cleaned_summary, cleaned_options = server_config.validate_input(
            summary, predefined_options
        )

        # 获取配置
        config, auto_resubmit_timeout = service_manager.get_web_ui_config()

        logger.info(
            f"启动反馈界面: {cleaned_summary[:100]}... (自动生成task_id: {task_id})"
        )

        # 确保 Web UI 正在运行（在同步函数中运行异步函数）
        asyncio.run(service_manager.ensure_web_ui_running(config))

        # 通过 HTTP API 向 web_ui 添加任务
        target_host = server_config.get_target_host(config.host)
        api_url = f"http://{target_host}:{config.port}/api/tasks"

        try:
            client = service_manager.get_sync_client(config)
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

                    # MCP 主进程统一发送：系统通知 + 声音 + Bark
                    # Bark 由后端发起，避免"插件+MCP"场景下 Bark 丢失（前端不再触发 /api/notify-new-tasks）
                    # 通知发送走 NotificationManager 的线程池（15s 超时），失败/超时不阻塞任务创建
                    mcp_types = [
                        NotificationType.SYSTEM,
                        NotificationType.SOUND,
                        NotificationType.BARK,
                    ]
                    base_url = ""
                    try:
                        base_url = server_config.resolve_external_base_url(config)
                    except Exception as exc:
                        logger.debug(f"解析 external_base_url 失败: {exc}")

                    notif_metadata: dict[str, Any] = {
                        "task_id": task_id,
                        "source": "launch_feedback_ui",
                    }
                    if base_url:
                        notif_metadata["base_url"] = base_url

                    event_id = notification_manager.send_notification(
                        title="新的交互反馈请求",
                        message=notification_message,
                        trigger=NotificationTrigger.IMMEDIATE,
                        types=mcp_types,
                        metadata=notif_metadata,
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
        backend_timeout = server_config.calculate_backend_timeout(
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


async def interactive_feedback(
    message: str | None = Field(
        default=None,
        description=(
            "Question, summary, or proposal to display to the human user. "
            "MUST be a non-empty string. Supports CommonMark / GitHub-Flavored Markdown "
            "(headings, lists, tables, fenced code blocks, links, inline code). "
            "Recommended length: 1-2000 characters; hard limit 10000 (longer input is truncated). "
            "Best practices: (1) state the question clearly in the first line; "
            "(2) include the recommended/default answer when proposing options; "
            '(3) escape special characters properly in JSON (use \\" for quotes, \\n for newlines). '
            "If omitted, the server falls back to `summary` or `prompt` for cross-tool compatibility."
        ),
    ),
    predefined_options: list | None = Field(
        default=None,
        description=(
            "Optional list of predefined choices the user can pick from "
            "(rendered as multi-select checkboxes alongside a free-text reply). "
            "MUST be either null/omitted or a JSON array of strings; non-string items are dropped. "
            "Each option: 1-500 characters (longer items are truncated). "
            "Tips: (1) keep options short, action-oriented and mutually distinguishable; "
            "(2) if you have a recommended/default answer, place it first and mark it (e.g. '[Recommended] ...'); "
            "(3) the user may also ignore options and reply with free text. "
            "If omitted, the server falls back to `options` for cross-tool compatibility."
        ),
    ),
    summary: str | None = Field(
        default=None,
        description=(
            "Compatibility alias for `message` (used by noopstudios/Minidoracat "
            "interactive-feedback-mcp variants). Ignored when `message` is provided."
        ),
    ),
    prompt: str | None = Field(
        default=None,
        description="Compatibility alias for `message`. Ignored when `message` is provided.",
    ),
    options: list | None = Field(
        default=None,
        description=(
            "Compatibility alias for `predefined_options`. "
            "Ignored when `predefined_options` is provided."
        ),
    ),
    project_directory: str | None = Field(
        default=None,
        description=(
            "Accepted for compatibility with other feedback MCP variants; this server "
            "ignores it (project context is taken from the running Web UI / config)."
        ),
    ),
    submit_button_text: str | None = Field(
        default=None,
        description="Accepted for compatibility; this server uses its own UI labels.",
    ),
    timeout: int | None = Field(
        default=None,
        description=(
            "Accepted for compatibility; this server uses its own configured backend "
            "timeout and auto-resubmit countdown."
        ),
    ),
    feedback_type: str | None = Field(
        default=None,
        description="Accepted for compatibility; ignored by this server.",
    ),
    priority: str | None = Field(
        default=None,
        description="Accepted for compatibility; ignored by this server.",
    ),
    language: str | None = Field(
        default=None,
        description="Accepted for compatibility; UI language follows the user's saved settings.",
    ),
    tags: list | None = Field(
        default=None,
        description="Accepted for compatibility; ignored by this server.",
    ),
    user_id: str | None = Field(
        default=None,
        description="Accepted for compatibility; ignored by this server.",
    ),
) -> list:
    """Ask the human user for interactive feedback through the Web UI.

    Use this tool whenever you need a human decision, clarification, confirmation,
    plan approval, design review, or final sign-off before continuing — especially
    when the next step has multiple valid approaches, irreversible side effects,
    or significant trade-offs.

    Behavior:
    - Renders the resolved message (Markdown) and an optional list of options in
      a Web UI; the user submits text + selected options + optional images.
    - The call blocks until the user submits, the auto-resubmit countdown
      expires, or the configured backend timeout is reached.
    - On success, returns a list of MCP content blocks (text + image) that
      include the user reply, selected options, and an optional prompt suffix.
    - On parameter validation failure, raises `ToolError` so the agent can
      retry with corrected arguments. On service / task failure, returns a
      configurable resubmit prompt instructing the agent to call this tool
      again, instead of silently dropping the request.

    Cross-tool compatibility:
    - `summary` / `prompt` are accepted as aliases for `message` so the same
      `mcp.json` config can target other feedback MCP variants without
      retraining the agent.
    - `options` is an alias for `predefined_options`.
    - `project_directory`, `submit_button_text`, `timeout`, `feedback_type`,
      `priority`, `language`, `tags`, `user_id` are accepted but ignored.
      They prevent the first-call validation failures observed when an agent
      reuses arguments shaped for a different feedback MCP server.

    Note: this function is not the MCP registration site itself; `server.py`
    wraps it with `mcp.tool()` to expose it to MCP clients.
    """
    # 漂移参数兜底：当 agent 误把别的 feedback MCP 工具的参数传给我们时，
    # 仍然尽力解析出 message / predefined_options，避免首次调用直接报错。
    resolved_message: Any = message
    if resolved_message is None or (
        isinstance(resolved_message, str) and not resolved_message.strip()
    ):
        for alias_name, alias_value in (("summary", summary), ("prompt", prompt)):
            if isinstance(alias_value, str) and alias_value.strip():
                logger.info(
                    f"interactive_feedback: 收到 '{alias_name}' 别名参数，已映射到 'message'"
                )
                resolved_message = alias_value
                break

    resolved_options: list | None = predefined_options
    if resolved_options is None and isinstance(options, list):
        logger.info(
            "interactive_feedback: 收到 'options' 别名参数，已映射到 'predefined_options'"
        )
        resolved_options = options

    # 仅在调试场景下记录被忽略的兼容参数（INFO 级别会在生产中产生噪音，因此用 debug）。
    _ignored_compat = {
        name: value
        for name, value in (
            ("project_directory", project_directory),
            ("submit_button_text", submit_button_text),
            ("timeout", timeout),
            ("feedback_type", feedback_type),
            ("priority", priority),
            ("language", language),
            ("tags", tags),
            ("user_id", user_id),
        )
        if value not in (None, "", [])
    }
    if _ignored_compat:
        logger.debug(
            f"interactive_feedback: 收到兼容字段（已忽略）: {list(_ignored_compat.keys())}"
        )

    # BM-1：参数验证失败是「用同样的参数无法恢复」的错误，应以 ToolError
    # 上报给 agent，让 agent 调整参数后再重试，而不是无意义地消费 resubmit
    # 文本反复调用（那会触发死循环）。
    # 写在顶层 try/except 之外是为了让 ToolError 逃出下面的
    # `except Exception -> _make_resubmit_response()` 兜底路径。
    try:
        (
            cleaned_message,
            cleaned_options,
            cleaned_defaults,
        ) = server_config.validate_input_with_defaults(
            cast(str, resolved_message), resolved_options
        )
    except (ValueError, ValidationError) as e:
        logger.warning(f"interactive_feedback 参数错误: {e}")
        raise ToolError(
            f"Invalid argument: {e}. "
            "Please ensure 'message' (or alias 'summary'/'prompt') is a non-empty string "
            "and 'predefined_options' (or alias 'options'), if provided, is a list of strings "
            "or {label, default} objects, then retry."
        ) from e

    predefined_options_list = cleaned_options
    predefined_options_defaults = cleaned_defaults

    try:
        # 自动生成唯一 task_id（避免极端并发下碰撞）
        task_id = server_config._generate_task_id()

        logger.info(
            f"收到反馈请求: {cleaned_message[:50]}... (自动生成task_id: {task_id})"
        )

        # 获取配置
        config, auto_resubmit_timeout = service_manager.get_web_ui_config()

        # 确保 Web UI 正在运行
        await service_manager.ensure_web_ui_running(config)

        # 通过 HTTP API 添加任务
        target_host = server_config.get_target_host(config.host)
        api_url = f"http://{target_host}:{config.port}/api/tasks"

        try:
            client = service_manager.get_async_client(config)
            response = await client.post(
                api_url,
                json={
                    "task_id": task_id,
                    "prompt": cleaned_message,
                    "predefined_options": predefined_options_list,
                    "predefined_options_defaults": predefined_options_defaults,
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
                return server_config._make_resubmit_response()

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

                    # MCP 主进程统一发送：系统通知 + 声音 + Bark
                    # Bark 由后端发起，避免"插件+MCP"场景下 Bark 丢失（前端不再触发 /api/notify-new-tasks）
                    # 通知发送走 NotificationManager 的线程池（15s 超时），失败/超时不阻塞任务创建
                    mcp_types = [
                        NotificationType.SYSTEM,
                        NotificationType.SOUND,
                        NotificationType.BARK,
                    ]
                    event_id = notification_manager.send_notification(
                        title="新的反馈请求",
                        message=notification_message,
                        trigger=NotificationTrigger.IMMEDIATE,
                        types=mcp_types,
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
            return server_config._make_resubmit_response()

        # 【优化】使用统一的超时计算函数，利用 feedback.timeout 作为上限
        backend_timeout = server_config.calculate_backend_timeout(auto_resubmit_timeout)
        logger.info(
            f"后端等待时间: {backend_timeout}秒 (前端倒计时: {auto_resubmit_timeout}秒)"
        )
        result = await wait_for_task_completion(task_id, timeout=backend_timeout)

        if "error" in result:
            # 记录任务执行失败的详细错误
            logger.error(f"任务执行失败: {result['error']}, 任务 ID: {task_id}")
            # 返回配置的提示语，引导 AI 重新调用工具
            return server_config._make_resubmit_response()

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
                return server_config.parse_structured_response(result)

            # 旧格式：只有文本反馈
            legacy = result.get("interactive_feedback")
            if isinstance(legacy, str) and legacy.strip():
                return [
                    TextContent(
                        type="text",
                        text=server_config._append_prompt_suffix(legacy),
                    )
                ]

            # 最后兜底：尽量取 text 字段，否则转字符串
            fallback = (
                result.get("text")
                if isinstance(result.get("text"), str)
                else str(result)
            )
            return [
                TextContent(
                    type="text",
                    text=server_config._append_prompt_suffix(str(fallback)),
                )
            ]

        # 简单字符串结果
        return [
            TextContent(
                type="text",
                text=server_config._append_prompt_suffix(str(result)),
            )
        ]

    except Exception as e:
        logger.error(f"interactive_feedback 工具执行失败: {e}", exc_info=True)
        # 返回配置的提示语，引导 AI 重新调用工具
        return server_config._make_resubmit_response()


class FeedbackServiceContext:
    """反馈服务上下文管理器 - 自动管理服务启动和清理"""

    def __init__(self):
        """初始化，延迟加载配置"""
        self.service_manager = service_manager.ServiceManager()
        self.config = None
        self.script_dir = None

    def __enter__(self):
        """加载配置并返回 self"""
        try:
            self.config, self.auto_resubmit_timeout = (
                service_manager.get_web_ui_config()
            )
            self.script_dir = Path(__file__).resolve().parent
            logger.info(
                f"反馈服务上下文已初始化，自动重调超时: {self.auto_resubmit_timeout}秒"
            )
            return self
        except Exception as e:
            logger.error(f"初始化反馈服务上下文失败: {e}", exc_info=True)
            raise

    def __exit__(self, exc_type, exc_val, exc_tb):
        """清理所有服务进程（退出上下文时）"""
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
        predefined_options: list[str] | None = None,
        task_id: str | None = None,
        timeout: int = 300,
    ) -> dict[str, Any]:
        """在上下文中启动反馈界面（委托给全局 launch_feedback_ui）"""
        return launch_feedback_ui(summary, predefined_options, task_id, timeout)
