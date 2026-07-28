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
import threading
import time
from pathlib import Path
from typing import Any, cast

from fastmcp.exceptions import ToolError
from fastmcp.server.context import Context as FastMCPContext
from mcp.types import TextContent
from pydantic import Field

import ai_intervention_agent.server_config as server_config
import ai_intervention_agent.service_manager as service_manager
from ai_intervention_agent.enhanced_logging import EnhancedLogger
from ai_intervention_agent.exceptions import (
    ServiceConnectionError,
    ServiceTimeoutError,
    ServiceUnavailableError,
    ValidationError,
)

logger = EnhancedLogger(__name__)


try:
    from ai_intervention_agent.notification_manager import (
        NotificationTrigger,
        notification_manager,
    )
    from ai_intervention_agent.notification_models import NotificationType

    NOTIFICATION_AVAILABLE = True
    logger.info("通知系统已导入")
except ImportError as e:
    logger.warning(f"通知系统不可用: {e}", exc_info=True)
    NOTIFICATION_AVAILABLE = False


_FEEDBACK_COUNTERS: dict[str, int] = {
    "created_total": 0,
    "completed_total": 0,
    "failed_total": 0,
}
_FEEDBACK_COUNTERS_LOCK = threading.Lock()


def _bump_feedback_counter(name: str, by: int = 1) -> None:
    """``_FEEDBACK_COUNTERS[name] += by``（线程安全；未知 key 时静默）。

    遇到未知 key 不抛异常 / 也不创建新 key——拼写错误应当被测试捕获，
    而不是在生产里悄悄拉一个新指标。
    """
    if name not in _FEEDBACK_COUNTERS:
        logger.warning(f"_bump_feedback_counter: ignoring unknown counter {name!r}")
        return
    with _FEEDBACK_COUNTERS_LOCK:
        _FEEDBACK_COUNTERS[name] += by


def reset_feedback_counters_for_testing() -> None:
    """R352 (cycle-39 #C2) · **Test-only**: 把 ``_FEEDBACK_COUNTERS`` 全
    部归零, 用于跨测试隔离 (v3.8 test-isolation 6th 应用)。

    **为什么需要这个 helper?**

    ``_FEEDBACK_COUNTERS`` 是 module-level dict, 一旦某测试调用了
    ``_bump_feedback_counter`` 或者真实的 ``interactive_feedback()`` 路径
    (例如 e2e 测试 / API 集成测试), 计数会在整个 pytest session 内累积,
    污染后续测试对 ``get_feedback_counters()`` 的预期。

    与 ``NotificationManager.reset_for_testing()`` (R323) /
    ``ConfigManager._instance`` reset 思路一致 — 给 module-level 可变状态
    暴露显式 reset API, 让 conftest 可以在测试边界 (fixture autouse) 调
    用以隔离副作用。

    **使用方式 (conftest.py)**::

        @pytest.fixture(autouse=True)
        def _reset_feedback_counters():
            from ai_intervention_agent.server_feedback import (
                reset_feedback_counters_for_testing,
            )
            reset_feedback_counters_for_testing()
            yield
            reset_feedback_counters_for_testing()
    """
    with _FEEDBACK_COUNTERS_LOCK:
        for k in _FEEDBACK_COUNTERS:
            _FEEDBACK_COUNTERS[k] = 0


def get_feedback_counters() -> dict[str, int]:
    """返回 interactive_feedback 计数器快照（R47）；永远是拷贝，不是引用。

    给 ``server.server_info_resource`` 在 ``aiia://server/info`` 子块里
    渲染，运维侧通过 MCP `resources/read` 拉取即可看到累计值。
    """
    with _FEEDBACK_COUNTERS_LOCK:
        return _FEEDBACK_COUNTERS.copy()


async def _emit_ctx_info(
    ctx: FastMCPContext | None,
    message: str,
    **extra: Any,
) -> None:
    """Best-effort 把 task lifecycle 关键节点回写到 MCP client 端日志。

    R44 helper：被 ``interactive_feedback`` 在 ``task.created`` /
    ``task.notified`` / ``task.completed`` 等关键锚点调用，让
    Cursor / Claude Desktop / ChatGPT Desktop 在 chat sidebar 渲染一行
    "正在等用户回复" 进度日志。

    设计取舍：
    - ``ctx`` 为 ``None``：直接 no-op。pytest / CLI / 集成测试 / 直接 Python
      调用时都会走到这条；保证本工具仍可在 MCP 之外被人测。
    - ``ctx.info`` 抛异常：吞掉并降级到本地 ``logger.debug``。MCP client
      连接断开 / 协议异常都不应该让业务流程崩。
    - 与 ``logger.event``/``logger.info`` 的关系：
        * ``logger.event``：结构化事件日志，落到 server 端 stderr，运维诊断
          走这条；
        * ``logger.info``：人类可读 server 端日志；
        * ``ctx.info``：发到 MCP client，是 *人类用户* 在 chat 看到的进度。
      三条管线各自独立，互不影响——服务器端日志一定有，client 看到的可能
      因为协议错误丢失，这是预期行为。
    """
    if ctx is None:
        return
    try:
        if extra:
            await ctx.info(message, extra=extra)
        else:
            await ctx.info(message)
    except Exception as ctx_exc:
        logger.debug(f"ctx.info 失败（已忽略）: {type(ctx_exc).__name__}: {ctx_exc}")


_POLL_INTERVAL_FAST_S = 2.0
_POLL_INTERVAL_SAFETY_NET_S = 30.0


_FETCH_RETRY_BACKOFF_S: tuple[float, ...] = (0.0, 0.1, 0.25, 0.5, 1.0)


_DEADLINE_EXTENSION_PROBE_MAX: int = 50
"""R689（TODO#13）：backend 超时前允许探测"任务倒计时是否被用户延长"的
最大次数。

正常场景远达不到上限：手动 extend 受 ``COUNTDOWN_EXTENDS_MAX``（默认 3）
约束、typing auto-extend 复用同一配额，因此探测最多个位数。上限仅防御
pathological 场景（例如自定义 backend 无限返回 remaining_time>0），确保
``wait_for_task_completion`` 不会变成永不返回的僵尸协程。"""


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

        resp = await client.post(close_url, timeout=2)
        if resp.status_code == 200:
            logger.info(f"timeout/cancel 路径已清理 ghost task: {task_id}")
        else:
            level = logger.debug if resp.status_code == 404 else logger.warning
            level(f"清理 ghost task {task_id} 收到非 200: HTTP {resp.status_code}")
    except asyncio.CancelledError:
        raise
    except Exception as e:
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

    def _pooled_client() -> Any:
        return service_manager.get_async_client(config)

    start_time_monotonic = time.monotonic()
    effective_timeout: float | None = float(timeout) if timeout > 0 else None

    logger.info(
        f"等待任务完成: {task_id}, "
        f"超时: {'无限等待' if timeout == 0 else f'{timeout}秒'}（SSE + 轮询）"
    )

    completion = asyncio.Event()

    sse_connected = asyncio.Event()
    result_box: list[Any] = [None]

    async def _fetch_result() -> dict[str, Any] | None:
        """获取已完成任务的结果，404 返回重调提示。

        R685：client 在每次调用时通过 ``_pooled_client()`` 即时获取——
        配置热更新关闭旧 client 后，下一次 fetch 自动拿到重建的新 client，
        不会陷入 "closed client 永远抛错" 的死区。
        """
        try:
            resp = await _pooled_client().get(api_url, timeout=2)
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

        R685: client 在进入 stream 前即时通过 ``service_manager.get_async_client``
        获取（而不是复用函数开头捕获的引用）——配置热更新会关闭旧 client，
        即时获取保证拿到的是可用（或重建后）的 pooled client。
        """
        import httpx

        try:
            stream_client = service_manager.get_async_client(config)
            async with stream_client.stream(
                "GET", sse_url, timeout=httpx.Timeout(None, connect=5.0)
            ) as resp:
                logger.debug(f"SSE 连接已建立: {task_id}")

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

    async def _probe_deadline_extension() -> float | None:
        """R689（TODO#13）：backend 等待超时前，探测任务是否仍有剩余倒计时。

        场景：用户在 Web UI / 插件里点了 +60s（extend endpoint）或正在
        输入触发了 typing auto-extend —— 这些操作只增加 task 的
        ``auto_resubmit_timeout``，而本函数的 ``backend_timeout`` 是任务
        创建时一次性算好的（frontend_countdown + BACKEND_BUFFER）。修复
        前 backend 会在旧 deadline 到期直接超时 → ghost-close 把仍在
        倒计时的任务删掉 → 用户随后提交必然 404，输入内容永久丢失。

        返回值：
        - ``float``（> 0）：任务仍存活且有剩余倒计时，backend 应继续等
          这么多秒（含 BACKEND_BUFFER 余量）；任务已 completed 但完成事
          件尚未送达时返回一个短窗口让 SSE / poll 取回结果。
        - ``None``：任务不存在 / 已无剩余倒计时 / 探测失败 → 按原超时
          语义处理。
        """
        try:
            resp = await _pooled_client().get(api_url, timeout=2)
            if resp.status_code != 200:
                return None
            data = resp.json()
            task = data.get("task") if data.get("success") else None
            if not isinstance(task, dict):
                return None
            if task.get("status") == "completed":
                return 5.0
            remaining = task.get("remaining_time")
            if isinstance(remaining, (int, float)) and remaining > 0:
                from ai_intervention_agent.runtime_constants import BACKEND_BUFFER

                return float(remaining) + BACKEND_BUFFER
        except Exception as e:
            logger.debug(f"探测任务剩余倒计时失败（按超时处理）: {e}")
        return None

    timed_out = False
    try:
        remaining_wait = effective_timeout
        probes_left = _DEADLINE_EXTENSION_PROBE_MAX
        while True:
            try:
                await asyncio.wait_for(completion.wait(), timeout=remaining_wait)
                break
            except TimeoutError:
                extension = (
                    await _probe_deadline_extension() if probes_left > 0 else None
                )
                probes_left -= 1
                if extension is None or extension <= 0:
                    timed_out = True
                    elapsed = time.monotonic() - start_time_monotonic
                    logger.error(f"任务超时: {task_id}, 等待 {elapsed:.1f}s")
                    break
                remaining_wait = extension
                logger.info(
                    f"任务 {task_id} 倒计时被用户延长，backend 继续等待 "
                    f"{extension:.0f}s（R689）"
                )
    finally:
        sse_task.cancel()
        poll_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await sse_task
        with contextlib.suppress(asyncio.CancelledError):
            await poll_task

        if result_box[0] is None:
            for retry_idx, backoff_s in enumerate(_FETCH_RETRY_BACKOFF_S):
                if backoff_s > 0:
                    try:
                        await asyncio.sleep(backoff_s)
                    except asyncio.CancelledError:
                        raise
                retry_result = await _fetch_result()
                if retry_result is not None:
                    result_box[0] = retry_result
                    logger.info(
                        f"close 前第 {retry_idx + 1}/{len(_FETCH_RETRY_BACKOFF_S)} "
                        f"次 fetch（退避 {backoff_s:.2f}s）拿到 result，"
                        f"跳过 ghost-task close: {task_id}"
                    )
                    break

        if result_box[0] is None:
            await _close_orphan_task_best_effort(
                task_id, target_host, config.port, client=_pooled_client()
            )

    if result_box[0] is not None:
        logger.info(f"任务完成: {task_id}")
        return cast(dict[str, Any], result_box[0])

    if timed_out:
        return cast(dict[str, Any], server_config._make_resubmit_response(as_mcp=False))

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

    if timeout > 0:
        timeout = max(timeout, 300)
    try:
        task_id = server_config._generate_task_id()

        cleaned_summary, cleaned_options = server_config.validate_input(
            summary, predefined_options
        )

        config, auto_resubmit_timeout = service_manager.get_web_ui_config()

        logger.info(
            f"启动反馈界面: {cleaned_summary[:100]}... (自动生成task_id: {task_id})"
        )

        asyncio.run(service_manager.ensure_web_ui_running(config))

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

            if NOTIFICATION_AVAILABLE:
                try:
                    notification_manager.refresh_config_from_file()

                    notification_message = cleaned_summary[:100]
                    if len(cleaned_summary) > 100:
                        notification_message += "..."

                    mcp_types = [
                        NotificationType.SYSTEM,
                        NotificationType.SOUND,
                        NotificationType.BARK,
                    ]
                    base_url = ""
                    try:
                        base_url = server_config.resolve_external_base_url(
                            config, for_external_use=True
                        )
                    except Exception as exc:
                        logger.debug(f"解析 external_base_url 失败: {exc}")

                    notif_metadata: dict[str, Any] = {
                        "task_id": task_id,
                        "source": "launch_feedback_ui",
                    }
                    if base_url:
                        notif_metadata["base_url"] = base_url
                    else:
                        logger.info(
                            "Bark 通知 base_url 为空（host 为 loopback 或未配置 external_base_url）"
                            "；已跳过 url 字段，建议在设置面板配置 web_ui.external_base_url 或 mDNS"
                        )

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

        backend_timeout = server_config.calculate_backend_timeout(
            auto_resubmit_timeout,
            max_timeout=max(timeout, 0),
            infinite_wait=(timeout == 0),
        )
        logger.info(
            f"后端等待时间: {backend_timeout}秒 (前端倒计时: {auto_resubmit_timeout}秒, 传入timeout: {timeout}秒)"
        )

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
            "Recommended length: 1-2000 characters; soft cap 1,000,000 characters "
            "(~1 MB UTF-8, R166); inputs longer than the cap are truncated with a "
            "trailing ellipsis marker. "
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
            "Two canonical input shapes (v1.6.0+ — the legacy parallel-array "
            "shape `predefined_options_defaults` was removed in R167; use the "
            "dict form below to mark recommended options): "
            "(a) **RECOMMENDED** list[dict] of shape "
            '{"label": str, "default": bool} — mark the recommended option '
            "with `default: true` so the UI shows a pre-checked checkbox "
            "(field aliases accepted: "
            '"label"/"text"/"value", "default"/"selected"/"checked"); '
            "(b) list[str] — simple labels, all initially unchecked "
            "(use this when no recommendation is needed). "
            "Non-string and non-{label,...} items are silently dropped. "
            "Each option max length: 10000 characters (longer items truncated). "
            "Tips: "
            "(1) keep options short, action-oriented and mutually distinguishable; "
            "(2) PREFER the dict form for ANY recommended option — "
            '`{"label": "Apply", "default": true}`. The UI renders real '
            "pre-checked checkboxes, so do NOT use text-prefix hacks "
            "(adding marker words to the label) for marking recommendations; "
            "(3) the user may also ignore options and reply with free text. "
            "If omitted, the server falls back to `options` for "
            "cross-tool compatibility."
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
    feedback_placeholder: str | None = Field(
        default=None,
        description=(
            "Optional textarea placeholder hint shown to the user when waiting "
            "for free-text feedback. Per-task override of the global "
            "``page.feedbackPlaceholder`` i18n string. "
            "Examples: 'Paste the error stack trace', 'Describe the visual glitch', "
            "'Reply 'ok' to approve or 'no' + reason to reject'. "
            "Length: clamped to 200 characters server-side (single-line "
            "placeholders only; longer text is silently truncated; the response "
            "includes ``placeholder_truncated: true`` + ``placeholder_original_length`` "
            "+ ``placeholder_max_length`` when clamping activates so callers can "
            "warn). "
            "If omitted or empty, the UI uses its default i18n placeholder. "
            "(mining-cycle-3 §2.1 — borrowed from gemini-cli ``ask_user`` schema.)"
        ),
    ),
    question_type: str | None = Field(
        default=None,
        description=(
            "Optional UI mode hint: when ``'yesno'``, the frontend renders a "
            "single-row Yes/No button pair above the free-text textarea. "
            "Clicking Yes/No marks the choice (click again to unselect, click "
            "the other button to switch); the user may optionally type a "
            "supplementary note, then presses Submit. The feedback result is "
            "the literal string 'yes' or 'no', optionally followed by a blank "
            "line and the user's note (e.g. ``'yes\\n\\nbut only after the "
            "tests pass'``) — parse the first line for the binary decision "
            "(approve/reject, proceed/abort, etc.). "
            "Allowed values: ``'yesno'`` (current) or ``None`` (default: keep "
            "textarea + optional ``predefined_options`` checkboxes). Unknown "
            "values silently treated as None (forward-compat for future types "
            "like ``'choice'`` / ``'rating'`` once the frontend supports them). "
            "(mining-cycle-3 §2.1 — borrowed from gemini-cli ``ask_user`` schema.)"
        ),
    ),
    header_label: str | None = Field(
        default=None,
        description=(
            "Optional short chip / tag rendered above the prompt in the task "
            "pane to give a one-word context cue (e.g. 'Auth', 'DB', 'Layout', "
            "'CSS', 'i18n'). Length: clamped to 16 characters server-side; "
            "single-word recommendation, no spaces if avoidable. Especially "
            "useful in multi-task mode where the user juggles 3+ concurrent "
            "feedback requests — the chip lets them visually distinguish "
            "task domains at a glance. If omitted or empty, no chip is shown "
            "(default existing layout). "
            "(mining-cycle-3 §2.1 — borrowed from gemini-cli ``ask_user.header`` schema.)"
        ),
    ),
    loop_id: str | None = Field(
        default=None,
        description=(
            "Loop engineering: optional stable identifier shared by every "
            "feedback round that belongs to the same goal / outer loop "
            "(agent-chosen, e.g. 'auth-refactor-2026-07'). Rounds that carry "
            "the same loop_id are grouped in the UI so the human reviewer can "
            "replay 'which rounds did this objective go through, and what was "
            "decided each time'. Length: clamped to 64 characters server-side. "
            "Omit for standalone one-shot questions (default behavior "
            "unchanged)."
        ),
    ),
    loop_objective: str | None = Field(
        default=None,
        description=(
            "Loop engineering: optional one-sentence description of the "
            "loop's goal (e.g. 'Migrate auth/session.py to PyJWT 2.x with "
            "green integration tests'). Pass it on the first round of a "
            "loop_id; later rounds may omit it. Shown to the reviewer as "
            "loop context above the prompt. Length: clamped to 500 "
            "characters server-side."
        ),
    ),
    loop_phase: str | None = Field(
        default=None,
        description=(
            "Loop engineering: optional free-form phase tag for this round, "
            "e.g. 'investigate' / 'implement' / 'verify' / 'review'. Helps "
            "the reviewer see where in the inner loop the agent currently "
            "is. Length: clamped to 32 characters server-side."
        ),
    ),
    success_criteria: str | None = Field(
        default=None,
        description=(
            "Loop engineering: optional verifiable completion criteria the "
            "human should judge the evidence against (e.g. 'pytest all "
            "green + no new ruff warnings + docs regenerated'). Rendered "
            "alongside the loop context so the verdict is made against an "
            "explicit baseline. Length: clamped to 500 characters "
            "server-side."
        ),
    ),
    iteration_label: str | None = Field(
        default=None,
        description=(
            "Loop engineering: optional round label such as 'iter-3' or "
            "'attempt-2'. Shown with the loop context so multiple rounds "
            "of the same loop are distinguishable at a glance. Length: "
            "clamped to 32 characters server-side."
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
    timeout_seconds: int | None = Field(
        default=None,
        description=(
            "Compatibility alias for `timeout` (used by some MCP clients that "
            "explicitly suffix the unit). Both fields are accepted for "
            "compatibility — this server ignores them and uses its own "
            "configured backend timeout / auto-resubmit countdown. "
            "When both are provided, this server logs a debug line and discards "
            "both, since neither overrides server config."
        ),
    ),
    task_id: str | None = Field(
        default=None,
        description=(
            "Accepted for compatibility (some agents pre-generate a trace ID "
            "and pass it through); this server always auto-generates an "
            "internal task ID and ignores the externally supplied value. "
            "Useful when the same `mcp.json` config also points at MCP "
            "variants that *do* honour an externally supplied task ID."
        ),
    ),
    *,
    ctx: FastMCPContext | None = None,
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
    - `project_directory`, `submit_button_text`, `timeout`, `timeout_seconds`,
      `feedback_type`, `priority`, `language`, `tags`, `user_id`, `task_id`
      are accepted but ignored. They prevent the first-call validation
      failures observed when an agent reuses arguments shaped for a
      different feedback MCP server.

    Note: this function is not the MCP registration site itself; `server.py`
    wraps it with `mcp.tool()` to expose it to MCP clients.

    R25.2: 函数体首行 ``import httpx`` 让下面 ``except httpx.HTTPError`` 在运行时
    解析符号——本工具被 MCP 客户端首次调用时一次性付 ~55 ms 加载费，而 MCP server
    cold-start 路径完全不会进入此函数（``server.py`` 顶层 import 时只是定义而已）。

    R44 FastMCP 最佳实践：``ctx`` 关键字参数（FastMCP 自动注入）让本函数可以走
    ``await _emit_ctx_info(ctx, ...)`` 把 task lifecycle 事件回送给 client
    （Cursor / Claude Desktop / ChatGPT Desktop）。client 收到后会在 chat
    sidebar 渲染一行进度日志，让人类用户能"看到工具确实在工作、正在等真人
    回复"，而不是猜"agent 是不是 hung 住了"。``ctx`` 永远 keyword-only 且
    默认 None，所以本工具被通过别的入口（pytest 直接调）调用时不会因为缺
    ctx 而崩；具体安全语义见 ``_emit_ctx_info`` 的 docstring。
    """
    import httpx  # used by `except httpx.HTTPError` below; ruff sees the usage

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

    _ignored_compat = {
        name: value
        for name, value in (
            ("project_directory", project_directory),
            ("submit_button_text", submit_button_text),
            ("timeout", timeout),
            ("timeout_seconds", timeout_seconds),
            ("feedback_type", feedback_type),
            ("priority", priority),
            ("language", language),
            ("tags", tags),
            ("user_id", user_id),
            ("task_id", task_id),
        )
        if value not in (None, "", [])
    }
    if _ignored_compat:
        logger.debug(
            f"interactive_feedback: 收到兼容字段（已忽略）: {list(_ignored_compat.keys())}"
        )

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
        task_id = server_config._generate_task_id()

        _task_t0 = time.monotonic()
        logger.event(
            "task.created",
            task_id=task_id,
            message_len=len(cleaned_message),
            options_count=len(predefined_options_list)
            if predefined_options_list
            else 0,
            has_defaults=bool(predefined_options_defaults),
        )
        _bump_feedback_counter("created_total")

        logger.info(
            f"收到反馈请求: {cleaned_message[:50]}... (自动生成task_id: {task_id})"
        )
        await _emit_ctx_info(
            ctx,
            f"Created interactive feedback task {task_id}",
            task_id=task_id,
            message_len=len(cleaned_message),
            options_count=len(predefined_options_list)
            if predefined_options_list
            else 0,
        )

        config, auto_resubmit_timeout = service_manager.get_web_ui_config()
        client = service_manager.get_async_client(config)

        await service_manager.ensure_web_ui_running(config, client=client)

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
                    "feedback_placeholder": feedback_placeholder,
                    "question_type": question_type,
                    "header_label": header_label,
                    "loop_id": loop_id,
                    "loop_objective": loop_objective,
                    "loop_phase": loop_phase,
                    "success_criteria": success_criteria,
                    "iteration_label": iteration_label,
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
                except ValueError as e:
                    logger.warning(
                        f"添加任务失败响应不是有效 JSON: {e}",
                        exc_info=True,
                    )
                    try:
                        if response.text:
                            error_detail = response.text[:200]
                    except Exception:
                        pass
                logger.error(
                    f"添加任务失败: HTTP {response.status_code}, 详情: {error_detail}"
                )
                logger.event(
                    "task.failed",
                    task_id=task_id,
                    stage="notify",
                    reason=f"http_{response.status_code}",
                )

                return server_config._make_resubmit_response()

            logger.info(f"任务已通过API添加到队列: {task_id}")
            logger.event(
                "task.notified",
                task_id=task_id,
                host=target_host,
                port=int(config.port),
            )
            await _emit_ctx_info(
                ctx,
                f"Waiting for human feedback on task {task_id}",
                task_id=task_id,
                web_ui_host=target_host,
                web_ui_port=int(config.port),
            )

            if NOTIFICATION_AVAILABLE:
                try:
                    notification_manager.refresh_config_from_file()

                    notification_message = cleaned_message[:100]
                    if len(cleaned_message) > 100:
                        notification_message += "..."

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
                    logger.warning(
                        f"发送任务通知失败: {e}，任务 {task_id} 已正常创建",
                        exc_info=True,
                    )
            else:
                logger.debug("通知系统不可用，跳过通知发送")

        except httpx.HTTPError as e:
            logger.error(f"添加任务请求失败，无法连接到 Web UI: {e}", exc_info=True)
            logger.event(
                "task.failed",
                task_id=task_id,
                stage="notify",
                reason=f"httpx_error:{type(e).__name__}",
            )
            _bump_feedback_counter("failed_total")

            return server_config._make_resubmit_response()

        backend_timeout = server_config.calculate_backend_timeout(auto_resubmit_timeout)
        logger.info(
            f"后端等待时间: {backend_timeout}秒 (前端倒计时: {auto_resubmit_timeout}秒)"
        )
        result = await wait_for_task_completion(task_id, timeout=backend_timeout)

        if "error" in result:
            logger.error(f"任务执行失败: {result['error']}, 任务 ID: {task_id}")
            logger.event(
                "task.failed",
                task_id=task_id,
                stage="wait",
                reason=str(result["error"])[:80],
                duration_ms=int((time.monotonic() - _task_t0) * 1000),
            )
            _bump_feedback_counter("failed_total")

            return server_config._make_resubmit_response()

        if (
            isinstance(result, dict)
            and set(result.keys()) == {"text"}
            and isinstance(result.get("text"), str)
        ):
            logger.event(
                "task.failed",
                task_id=task_id,
                stage="wait",
                reason="timeout_or_task_lost",
                duration_ms=int((time.monotonic() - _task_t0) * 1000),
            )
            _bump_feedback_counter("failed_total")
            await _emit_ctx_info(
                ctx,
                f"Task {task_id} timed out or was lost before human feedback arrived",
                task_id=task_id,
            )
            return [TextContent(type="text", text=str(result["text"]))]

        logger.info("反馈请求处理完成")
        _completed_duration_ms = int((time.monotonic() - _task_t0) * 1000)
        logger.event(
            "task.completed",
            task_id=task_id,
            duration_ms=_completed_duration_ms,
        )
        _bump_feedback_counter("completed_total")
        await _emit_ctx_info(
            ctx,
            f"Received human feedback for task {task_id} (took {_completed_duration_ms} ms)",
            task_id=task_id,
            duration_ms=_completed_duration_ms,
        )

        if isinstance(result, dict):
            if (
                "images" in result
                or "user_input" in result
                or "selected_options" in result
            ):
                return server_config.parse_structured_response(result)

            legacy = result.get("interactive_feedback")
            if isinstance(legacy, str) and legacy.strip():
                return [
                    TextContent(
                        type="text",
                        text=server_config._append_prompt_suffix(legacy),
                    )
                ]

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

        return [
            TextContent(
                type="text",
                text=server_config._append_prompt_suffix(str(result)),
            )
        ]

    except Exception as e:
        logger.error(f"interactive_feedback 工具执行失败: {e}", exc_info=True)
        _bump_feedback_counter("failed_total")

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
