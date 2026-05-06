"""反馈交互层 - interactive_feedback 工具实现、任务轮询与上下文管理。

该模块从 `server.py` 抽取反馈相关逻辑，避免在 MCP 入口文件里堆积业务代码。
注意：`interactive_feedback` 的 MCP 工具注册由 `server.py` 持有的 `mcp` 实例完成，
本模块内的 `interactive_feedback` 为“未装饰”的实现函数。

R25.2 性能注解：``httpx`` 顶级导入被推迟到使用点
================================================

本模块只在 SSE 监听 (``_sse_listener``) / launch_feedback_ui / interactive_feedback
三处真正发起 HTTP 时才需要 httpx，``server.py`` 顶层 import 本模块时若再 import
httpx 等于把 ~55 ms 的 transport 初始化预热成本绑死在 MCP 进程 cold-start 上。
搭配 ``service_manager`` 的同步改造（同样推迟到使用点），cold-start 总省 ~55 ms
（``httpx`` 只加载一次，两处任意一个先到都会写入 ``sys.modules`` 命中后续 import）。

注意：本模块没有任何模块级 ``httpx.X`` 类型注解（``except httpx.HTTPError`` 与
``httpx.Timeout(...)`` 都在函数体内），因此**不**需要 ``if TYPE_CHECKING: import httpx``
守护块——三个使用点（``_sse_listener`` / ``launch_feedback_ui`` / ``interactive_feedback``）
直接函数体首行 ``import httpx`` 就够了。``service_manager`` 那边因为有 ``_async_client:
httpx.AsyncClient | None = None`` 等模块级注解，所以保留 TYPE_CHECKING 块；这条
路径上的不对称是有意的。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from pathlib import Path
from typing import Any, cast

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


# R22.1: ``wait_for_task_completion`` 的 HTTP 轮询保底节奏。
# 设计原则：双通道兜底 = SSE 实时通道（<50 ms 完成检测）+ HTTP 轮询保底。
# SSE 是主路径；轮询只在 SSE 故障时保命。
#
# - SSE 未连接（启动期 / SSE 连接失败 / 连接中断）：紧密 2s 兜底，与前端
#   ``static/js/multi_task.js::TASKS_POLL_BASE_MS = 2000`` 同节奏，确保
#   单次故障不会让任务完成检测延迟超过 2 s。
# - SSE 已连接：拉成 30s safety net，与前端
#   ``TASKS_POLL_SSE_FALLBACK_MS = 30000`` 同节奏。SSE 通道工作时
#   每 2 s 一次的 HTTP 轮询纯粹是冗余调用——单次任务（默认 240 s 倒计时）
#   会触发 ~119 次冗余 ``GET /api/tasks/<id>``，每次 1-3 ms 网络开销 +
#   web_ui ``task_queue._lock`` 取锁。SSE-健康场景下，这些调用只是兜底，
#   30s safety net 把冗余频次砍到 ~7 次/任务（-94%）。
#
# 边界与权衡：SSE 在 30s 窗口中段断开会让完成检测延迟到当前 30s 窗口结束
# 后才被发现（最坏 ~30 s）。与前端同语义；考虑到 SSE 在 LAN/loopback 上
# 几乎不掉线，且 SSE listener 故障会立即让 ``sse_connected`` flag 翻 False
# （下一个 wait 周期就会复用 2s 紧密节奏），实操影响极小。
_POLL_INTERVAL_FAST_S = 2.0
_POLL_INTERVAL_SAFETY_NET_S = 30.0


async def _close_orphan_task_best_effort(
    task_id: str,
    host: str,
    port: int,
    client: Any | None = None,
) -> None:
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

    ``client`` 用于 ``wait_for_task_completion`` 热路径复用已创建的
    AsyncClient；留空时保持历史行为，便于单测和旧调用方直接使用本 helper。
    """
    close_url = f"http://{host}:{port}/api/tasks/{task_id}/close"
    try:
        if client is None:
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

    双通道并行：SSE 提供 <50 ms 实时检测，HTTP 轮询作为 SSE 断连的安全网。
    任一通道检测到完成即终止另一通道。

    【R22.1】HTTP 轮询节奏自适应：
        - SSE 已连接 → 30 s safety net（与前端
          ``static/js/multi_task.js::TASKS_POLL_SSE_FALLBACK_MS = 30000``
          同节奏）；
        - SSE 未连接 / 已断开 → 2 s 紧密兜底（与前端
          ``TASKS_POLL_BASE_MS = 2000`` 同节奏）。
        ``_sse_listener`` 进入 stream 主循环时 set ``sse_connected``，
        所有退出路径在 finally 里 clear；``_poll_fallback`` 每周期读
        flag 决定 interval。SSE 健康场景下，单次任务（默认 240 s 倒计时）
        从 ~119 次冗余 fetch 减到 ~7 次（-94%），节省 web_ui 端 ``task_queue``
        锁竞争与网络栈开销。常量见模块顶部 ``_POLL_INTERVAL_FAST_S`` /
        ``_POLL_INTERVAL_SAFETY_NET_S``。

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
    http_client = service_manager.get_async_client(config)

    start_time_monotonic = time.monotonic()
    effective_timeout: float | None = float(timeout) if timeout > 0 else None

    logger.info(
        f"等待任务完成: {task_id}, "
        f"超时: {'无限等待' if timeout == 0 else f'{timeout}秒'}（SSE + 轮询）"
    )

    completion = asyncio.Event()
    # R22.1: SSE 通道连接状态，由 ``_sse_listener`` 维护，``_poll_fallback``
    # 据此在每个 wait 周期选择合适的 interval（连接 → 30s safety net；
    # 未连接 → 2s 紧密兜底）。set/clear 动作必须在 listener 内部，poll 只读，
    # 这样语义就是"SSE 当前是否在 stream 主循环"，对完成检测的延迟影响可控。
    sse_connected = asyncio.Event()
    result_box: list[Any] = [None]

    async def _fetch_result() -> dict[str, Any] | None:
        """获取已完成任务的结果，404 返回重调提示。"""
        try:
            resp = await http_client.get(api_url, timeout=2)
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
        """SSE 实时通道：收到 task_changed(completed) 即通知完成。

        R22.1: stream 进入主循环前 set ``sse_connected`` 让 ``_poll_fallback``
        切到 30s safety net 节奏；任何退出路径（正常完成、cancel、异常）
        都在 finally 里 clear 该 flag，确保 poll 在下一周期回到 2s 紧密兜底。

        R23.1: 复用 ``service_manager.get_async_client(cfg)`` 维护的进程级
        ``httpx.AsyncClient`` 连接池，而不是每次任务都新建一个独立 client。
        why：
        - **TCP/TLS 握手复用**：同一个 web_ui 进程的 polling 路径
          （``_fetch_result``）已经通过 connection pool 复用 keep-alive
          连接；让 SSE stream 也走这个池子，意味着 SSE 不再独占一对
          new socket，连续多次 ``interactive_feedback`` 调用之间能复用
          底层 TCP 连接（loopback 上单次握手 ~50-200 µs，但 client
          构造本身的 ``AsyncHTTPTransport`` + retry 策略初始化 + asyncio
          lock 获取大概 1-3 ms / 次，省掉这部分是主要收益）。
        - **资源生命周期统一**：过去每次 ``interactive_feedback`` 都
          ``__aenter__/__aexit__`` 一个 ``httpx.AsyncClient``，意味着每次
          MCP 调用都做一次完整的 transport 初始化+销毁；现在交给进程级
          singleton 管理，进程退出时 ``service_manager._close_async_client_best_effort``
          统一回收。

        必须显式覆盖 ``timeout``：``service_manager.get_async_client`` 的
        默认 ``httpx.Timeout(config.timeout, connect=5.0)`` 把 read timeout
        设成 ``config.timeout``（短请求合适），但 SSE stream 是 long-lived
        ——服务端在没有事件时一直 hold 住连接不发数据，正常行为。所以
        ``stream(...)`` 调用时必须传 ``httpx.Timeout(None, connect=5.0)``
        把 read timeout 解除，否则 SSE 在第一个空闲窗口就会被 httpx 当成
        超时砍掉。这个 per-call timeout 覆盖只影响本次 stream 请求，不会
        污染池里其他 short request 的 timeout 行为。

        R25.2: 函数体首行 ``import httpx`` 把 httpx 引入函数局部命名空间——
        SSE 监听只在 ``interactive_feedback`` 工具调用时触发，到达此处
        ``service_manager.get_async_client(cfg)`` 必然已经把 httpx 加载到
        ``sys.modules``，本地 import 走 cache 没有额外开销，但能让 ty 与运行时
        都正确解析 ``httpx.Timeout``。
        """
        import httpx

        try:
            async with http_client.stream(
                "GET", sse_url, timeout=httpx.Timeout(None, connect=5.0)
            ) as resp:
                logger.debug(f"SSE 连接已建立: {task_id}")
                # 通知 _poll_fallback：SSE 主路径已就绪，可以拉成 30s safety net
                sse_connected.set()
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
        finally:
            sse_connected.clear()

    async def _poll_fallback() -> None:
        """HTTP 轮询保底：SSE 已连接时 30s safety net，否则 2s 紧密兜底。

        R22.1 之前固定 2s 间隔，与 SSE 主路径并行造成每任务 ~119 次
        冗余 fetch；现在每个 wait 周期开始前读 ``sse_connected.is_set()``
        决定 interval：SSE 健康 → 30s safety net；SSE 未起 / 已断 → 2s。
        """
        while not completion.is_set():
            r = await _fetch_result()
            if r is not None:
                result_box[0] = r
                completion.set()
                return
            interval = (
                _POLL_INTERVAL_SAFETY_NET_S
                if sse_connected.is_set()
                else _POLL_INTERVAL_FAST_S
            )
            try:
                await asyncio.wait_for(completion.wait(), timeout=interval)
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

        # R17.4 retry-before-close 兜底：SSE 报告 completed 但首次
        # ``_fetch_result()`` 撞到瞬时网络抖动（503 / connection
        # error / DNS 短暂失败）时，``result_box[0]`` 还是 None ——
        # 如果直接进 R13·B1 close 路径，``_close_orphan_task_best_effort``
        # 的 ``POST /close`` 会让 web_ui ``task_queue.remove_task``
        # 把**已经 completed**（且仍带着 user-feedback 的 result）的
        # task 立即删掉，紧接着 ``_make_resubmit_response`` 让 AI
        # 重新提交，用户辛辛苦苦填的反馈被永久丢失却零日志告警。
        #
        # 多 fetch 一次给抖动一个机会：retry 成功 → 填 ``result_box``
        # → 跳过 close（因为 ``is None`` 检查会 short-circuit）；
        # retry 仍失败 → 真的没结果 → 走原 R13·B1 ghost-task close
        # 路径，行为和修复前完全一致。
        if result_box[0] is None:
            retry_result = await _fetch_result()
            if retry_result is not None:
                result_box[0] = retry_result
                logger.info(
                    f"close 前二次 fetch 拿到 result，跳过 ghost-task close: {task_id}"
                )

        # R13·B1 ghost-task cleanup
        # 仅在没拿到 result 时才 close —— 拿到 result 说明 web_ui 已经
        # 通过 /api/submit → task_queue.complete_task 把 task 标记
        # completed 了，再 close 是 race（且后台 cleanup 线程会在 10s
        # 后 GC，不需要重复操作）。
        if result_box[0] is None:
            await _close_orphan_task_best_effort(
                task_id, target_host, config.port, client=http_client
            )

    if result_box[0] is not None:
        logger.info(f"任务完成: {task_id}")
        return cast(dict[str, Any], result_box[0])

    # R13·B1 残留兜底：即便 close 已发出，如果 close 网络失败而 task 在
    # web_ui 那侧仍 status=completed（罕见，需要 close 走 IO 错而 GET
    # 走通），最后再 fetch 一次能拿回 result——属于 best-effort 兜底，
    # R17.4 retry-before-close 已经在 close 之前覆盖了主要 race，这一
    # 行只覆盖"close 失败 + task 没被清"这个边缘场景。
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
    """废弃：旧版 Python API，推荐使用 interactive_feedback() MCP 工具。

    R25.2: 函数体首行 ``import httpx`` 让下面 ``except httpx.HTTPError`` 在运行时
    可以解析符号；同时本函数会调用 ``service_manager.update_web_content`` 等
    使用 httpx 的接口，``sys.modules['httpx']`` 命中 cache 后零成本。
    """
    import httpx  # used by `except httpx.HTTPError` below; ruff sees the usage

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

    R25.2: 函数体首行 ``import httpx`` 让下面 ``except httpx.HTTPError`` 在运行时
    解析符号——本工具被 MCP 客户端首次调用时一次性付 ~55 ms 加载费，而 MCP server
    cold-start 路径完全不会进入此函数（``server.py`` 顶层 import 时只是定义而已）。
    """
    import httpx  # used by `except httpx.HTTPError` below; ruff sees the usage

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
        client = service_manager.get_async_client(config)

        # 确保 Web UI 正在运行
        await service_manager.ensure_web_ui_running(config, client=client)

        # 通过 HTTP API 添加任务
        target_host = server_config.get_target_host(config.host)
        api_url = f"http://{target_host}:{config.port}/api/tasks"

        try:
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
