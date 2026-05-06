"""任务管理路由 Mixin — 任务列表、创建、详情、激活、提交反馈、SSE 事件流。"""

from __future__ import annotations

import json
import queue
import threading
import time
from typing import TYPE_CHECKING, Any

from flask import Response, jsonify, request
from flask.typing import ResponseReturnValue

from enhanced_logging import EnhancedLogger
from i18n import msg

# R20.8: 直接 import task_queue_singleton 避免拖入 fastmcp/mcp（详见模块注释）。
from task_queue_singleton import get_task_queue
from web_ui_routes._upload_helpers import extract_uploaded_images

if TYPE_CHECKING:
    from flask import Flask
    from flask_limiter import Limiter

logger = EnhancedLogger(__name__)


# Sentinel：当 ``_SSEBus`` 因 backpressure 把订阅者从 ``_subscribers`` 集合里
# 踢掉时，会向那个 queue 塞这个对象。Generator 拿到它就 ``return``，浏览器
# EventSource 看到 EOF 后会自动 reconnect → 重新 ``subscribe()`` → 拿到一条
# 全新的、空的 queue 重新接收事件。
#
# 历史上这里没有 sentinel：被 discard 之后 ``q`` 仍在 generator 手里持有引用，
# generator 继续 ``q.get(timeout=25)`` 把旧积压消费掉、然后无限发心跳。客户端
# 看心跳在跳，认为连接活着，但 ``emit`` 已经不再往这个 queue 写新事件——也就是
# 「服务器以为客户端断了，客户端以为服务器还在推」的 silent disconnection。
# 由 ``test_sse_bus_backpressure_disconnect_signals_generator`` 锁定 contract。
_SSE_DISCONNECT_SENTINEL = object()


class _SSEBus:
    """线程安全的 SSE 事件总线：TaskQueue 回调 → 所有已连接的 EventSource 客户端

    清理策略：
    - emit 时：队列满（Full）的立即移除
    - emit 时：队列积压超过 3/4 容量的也移除（消费者大概率已断开）
    - 移除时往订阅者 queue 塞 ``_SSE_DISCONNECT_SENTINEL``，让 generator
      看到它后主动 ``return``，触发浏览器 EventSource 自动 reconnect。
    """

    _QUEUE_MAXSIZE = 64
    _BACKPRESSURE_THRESHOLD = _QUEUE_MAXSIZE * 3 // 4

    def __init__(self) -> None:
        self._subscribers: set[queue.Queue] = set()
        self._lock = threading.Lock()

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=self._QUEUE_MAXSIZE)
        with self._lock:
            self._subscribers.add(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            self._subscribers.discard(q)

    def emit(self, event_type: str, data: dict | None = None) -> None:
        # R27.4：无订阅者时直接返回，避免状态变更在无人消费时仍做 JSON 序列化。
        # snapshot 必须仍在锁内完成，保持 subscribe/unsubscribe 并发语义。
        with self._lock:
            snapshot = list(self._subscribers)
        if not snapshot:
            return

        # R20.14-C：单次预序列化复用给所有订阅者
        # ----------------------------------------------------------------
        # 历史实现里每个 SSE generator 在 yield 前自己做一次
        # ``json.dumps(event['data'])``。N 个订阅者就 dumps N 次同一份数据；
        # 在订阅者数 ≥ 3 的浏览器多 tab / VSCode webview + 状态栏并存场景下
        # 是纯浪费。把序列化 hoist 到 emit 里一次，附带写进 payload 的
        # ``_serialized`` 字段（详见 ``sse_events`` generator 处的消费逻辑）。
        # 失败兜底：序列化抛异常时退化到 ``None``，generator 看见 None 时再
        # 回退到 on-demand dumps，保留原行为不让单条坏数据让整个 SSE 总线挂掉。
        try:
            serialized_data = json.dumps(data or {}, ensure_ascii=False)
        except (TypeError, ValueError):
            serialized_data = None
        payload = {
            "type": event_type,
            "data": data or {},
            "_serialized": serialized_data,
        }

        # R20.14-C：snapshot-then-put，缩短 ``_lock`` 临界区
        # ----------------------------------------------------------------
        # 历史实现把 N 次 ``put_nowait`` + N 次 ``q.qsize()`` 都关在 ``_lock``
        # 里执行。``put_nowait`` 自身要拿 queue 的内部锁，``qsize`` 在 CPython
        # 实现上也走 thread-safe path，每次 ~1µs；N=10 时整个 emit 占用 ~10µs
        # 的 ``_lock`` 临界区，会和 subscribe / unsubscribe 互斥。
        # 这里改成「锁内只 list(self._subscribers) 拍快照，锁外做 put」，让
        # ``_lock`` 临界区退化到一次 set→list 拷贝（~1µs / 100 元素），
        # 多 producer 场景里几乎无竞争。
        # 语义保持：snapshot 之后新加入的订阅者不会收到本条事件——这与原实现
        # 「subscribe() 必须等 emit() 释放锁后才能进入 set」是同一行为。
        dead: list[queue.Queue] = []
        for q in snapshot:
            try:
                q.put_nowait(payload)
            except queue.Full:
                dead.append(q)
                continue
            if q.qsize() >= self._BACKPRESSURE_THRESHOLD:
                dead.append(q)

        if not dead:
            return

        # R20.14-C：dead 清理需要重新拿 ``_lock``，但这里只是 set.discard
        # （O(1)）+ sentinel 注入（不需要 _lock 保护，sentinel 是塞给单个
        # queue 的，与 ``_subscribers`` 集合无关）。把 sentinel 注入留在锁外，
        # 锁只覆盖最小改动。
        with self._lock:
            for q in dead:
                self._subscribers.discard(q)

        for q in dead:
            # 主动通知 generator 退出。优先级 sentinel > 旧消息：
            # 即使 queue.Full（说明前面 emit 在 ``put_nowait`` 时就掉到了
            # ``except queue.Full`` 那行），也要 ``get_nowait`` 排出最旧的
            # 那条 payload 来腾位子。代价是 client 错过最早的一条 SSE 事件
            # （但浏览器 EventSource 自动 reconnect 时会重新 ``subscribe``，
            # 拿到下一条新事件 + 后续所有事件，比 silent disconnection 强得多）。
            while True:
                try:
                    q.put_nowait(_SSE_DISCONNECT_SENTINEL)
                    break
                except queue.Full:
                    try:
                        q.get_nowait()
                    except queue.Empty:
                        break

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)


_sse_bus = _SSEBus()


def _on_task_status_change(
    task_id: str, old_status: str | None, new_status: str
) -> None:
    # R20.14-C：把当前任务统计直接塞进事件 payload
    # ----------------------------------------------------------------
    # 浏览器/插件收到 task_changed 后旧路径要再 fetch 一次 ``/api/tasks``
    # 才知道总数变化，多一次 ~3 ms 的 round-trip。这里趁回调线程已经在
    # 锁外（``_trigger_status_change`` 注释明确说"回调在锁外触发"）顺手
    # 调一次 ``get_task_count()``，把 ``stats: {pending, active,
    # completed, total}`` 一起 push 出去，让 client 拿到事件就能立刻
    # 更新 UI 显示，3 ms fetch 退化为可选的兜底校验。
    # 失败兜底：``get_task_count`` 抛异常 / 队列模块没起来时直接省掉
    # stats 字段（不是空字典），让旧客户端的「stats 不存在 → 走 fetch」
    # 兜底路径仍然生效，避免「stats 是空 → 误以为 0」的脏读。
    stats: dict[str, int] | None = None
    try:
        tq = get_task_queue()
        if tq is not None:
            stats = tq.get_task_count()
    except Exception:
        stats = None

    payload: dict[str, str | None | dict[str, int]] = {
        "task_id": task_id,
        "old_status": old_status,
        "new_status": new_status,
    }
    if stats is not None:
        payload["stats"] = stats
    _sse_bus.emit("task_changed", payload)


_sse_callback_registered = False
_sse_callback_lock = threading.Lock()


def _ensure_sse_callback_registered() -> None:
    """线程安全地注册 SSE 回调（双检查锁定，至多注册一次）。"""
    global _sse_callback_registered
    if _sse_callback_registered:
        return
    with _sse_callback_lock:
        if _sse_callback_registered:
            return
        try:
            tq = get_task_queue()
            if tq is not None:
                tq.register_status_change_callback(_on_task_status_change)
                _sse_callback_registered = True
                logger.info("SSE 事件总线已注册到 TaskQueue")
        except Exception as exc:
            logger.warning(f"SSE 回调注册失败，将退化为轮询模式: {exc}", exc_info=True)


class TaskRoutesMixin:
    """提供 5 个任务管理 API 路由，由 WebFeedbackUI 通过 MRO 继承。"""

    if TYPE_CHECKING:
        app: Flask
        limiter: Limiter

    def _setup_task_routes(self) -> None:
        from web_ui import (
            _get_default_auto_resubmit_timeout_from_config,
            validate_auto_resubmit_timeout,
        )

        _ensure_sse_callback_registered()

        @self.app.route("/api/events")
        @self.limiter.limit("300 per minute")
        def sse_events() -> Response:
            """SSE 事件流：实时推送任务变更通知

            限流：``300/min``。SSE 是长连接，单次 ``EventSource`` 实例只
            消耗 1 次限额；但浏览器在网络抖动 / 用户频繁 reload 场景下
            会反复 reconnect，全局默认 ``60/min`` 在重启浏览器、刷新调
            试时太容易触顶。提到 ``300/min`` 与 ``/api/tasks`` 拉取频率
            对齐，并避免 ``@limiter.exempt`` 让滥用者无限建立连接消耗
            server-side 队列。
            ---
            tags:
              - Tasks
            produces:
              - text/event-stream
            responses:
              200:
                description: SSE 事件流（task_changed 事件 + 25s 心跳）
            """
            _ensure_sse_callback_registered()

            q = _sse_bus.subscribe()

            def generate():
                try:
                    while True:
                        try:
                            event = q.get(timeout=25)
                        except queue.Empty:
                            yield ": heartbeat\n\n"
                            continue
                        if event is _SSE_DISCONNECT_SENTINEL:
                            return
                        # R20.14-C：优先消费 emit 里预序列化好的 ``_serialized``
                        # 字段；缺失时（旧式 payload / dumps 失败兜底）再 on-demand
                        # 走一次 dumps。多 generator 共享同一份字符串，省 (N-1) 次
                        # 序列化开销。
                        serialized = (
                            event.get("_serialized")
                            if isinstance(event, dict)
                            else None
                        )
                        if serialized is None:
                            serialized = json.dumps(event["data"], ensure_ascii=False)
                        yield f"event: {event['type']}\ndata: {serialized}\n\n"
                except GeneratorExit:
                    pass
                finally:
                    _sse_bus.unsubscribe(q)

            return Response(
                generate(),
                mimetype="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                    "Connection": "keep-alive",
                },
            )

        @self.app.route("/api/tasks", methods=["GET"])
        @self.limiter.limit("300 per minute")
        def get_tasks() -> ResponseReturnValue:
            """获取所有任务列表
            ---
            tags:
              - Tasks
            responses:
              200:
                description: 任务列表与统计信息
                schema:
                  type: object
                  properties:
                    success:
                      type: boolean
                    tasks:
                      type: array
                      items:
                        type: object
                        properties:
                          task_id:
                            type: string
                          status:
                            type: string
                            enum: [pending, active, completed]
                          prompt:
                            type: string
                            description: 提示文本（前 100 字符）
                          created_at:
                            type: string
                            format: date-time
                          auto_resubmit_timeout:
                            type: number
                          remaining_time:
                            type: number
                          deadline:
                            type: number
                            description: 截止时间戳 (server_time + remaining_time)
                    stats:
                      type: object
                      properties:
                        total:
                          type: integer
                        pending:
                          type: integer
                        active:
                          type: integer
                        completed:
                          type: integer
                    server_time:
                      type: number
              500:
                description: 服务器内部错误
            """
            try:
                task_queue = get_task_queue()

                # P0：从未节流改为节流版（30s 窗口）—— 后台清理线程已经每 5s
                # 跑一次未节流 cleanup，hot path 上重复执行只会放大锁竞争。
                # 保留兜底意图（后台线程异常停滞时仍能清理），但 99% 的请求
                # 走 fast path（一次 time.monotonic + 阈值比较），不接触 _tasks。
                task_queue.cleanup_completed_tasks_throttled(
                    age_seconds=10, throttle_seconds=30.0
                )

                # R23.4: 单次 read_lock 拿 list + stats，省掉一次 RWLock
                # 进出 + 一次 list copy。``/api/tasks`` 是热点（前端默认
                # 2 s 轮询，扩展 SSE 兜底是 3 s），单进程多客户端稳态 50-150
                # req/min；合并后每次省 ~400-900 ns（一次 read_lock atomic 进
                # 出 + 一次 list view 重建），并把 list/stats 的可见性升级
                # 成同一个临界区内的原子快照，前端 invariant 不再需要容忍
                # 1-step skew。
                tasks, stats = task_queue.get_all_tasks_with_stats()

                server_time = time.time()
                now_monotonic = time.monotonic()

                task_list = []
                for task in tasks:
                    remaining = task.get_remaining_time(now_monotonic=now_monotonic)
                    task_list.append(
                        {
                            "task_id": task.task_id,
                            "status": task.status,
                            "prompt": task.prompt[:100],
                            "created_at": task.created_at.isoformat(),
                            "auto_resubmit_timeout": task.auto_resubmit_timeout,
                            "remaining_time": remaining,
                            "deadline": server_time + remaining,
                        }
                    )

                return jsonify(
                    {
                        "success": True,
                        "tasks": task_list,
                        "stats": stats,
                        "server_time": server_time,
                    }
                )
            except Exception as e:
                logger.error(f"获取任务列表失败: {e}", exc_info=True)
                return jsonify({"success": False, "error": "服务器内部错误"}), 500

        @self.app.route("/api/tasks", methods=["POST"])
        @self.limiter.limit("60 per minute")
        def create_task() -> ResponseReturnValue:
            """创建新任务
            ---
            tags:
              - Tasks
            consumes:
              - application/json
            parameters:
              - in: body
                name: body
                required: true
                schema:
                  type: object
                  required:
                    - task_id
                    - prompt
                  properties:
                    task_id:
                      type: string
                      description: 任务唯一标识符
                    prompt:
                      type: string
                      description: 提示文本（Markdown 格式）
                    predefined_options:
                      type: array
                      items:
                        type: string
                      description: 预定义选项列表
                    predefined_options_defaults:
                      type: array
                      items:
                        type: boolean
                      description: |
                        每个预定义选项的"默认是否选中"标记（与 predefined_options 一一对应，
                        长度必须相同；省略时等价于全部 false）。
                    auto_resubmit_timeout:
                      type: integer
                      minimum: 0
                      maximum: 3600
                      default: 240
                      description: 倒计时秒数；0=禁用；非零值范围 [10, 3600]，与 server_config.AUTO_RESUBMIT_TIMEOUT_MAX 对齐（与 POST /api/update-feedback-config 同字段一致）
            responses:
              200:
                description: 任务创建成功
                schema:
                  type: object
                  properties:
                    success:
                      type: boolean
                    task_id:
                      type: string
              400:
                description: 请求参数错误
              409:
                description: 任务 ID 重复或队列已满
              500:
                description: 服务器内部错误
            """
            try:
                raw = request.get_json(silent=False)
            except Exception:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "请求体必须是 JSON（object）",
                        }
                    ),
                    400,
                )

            if not isinstance(raw, dict):
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "请求体必须是 JSON object",
                        }
                    ),
                    400,
                )

            data: dict[str, Any] = raw

            task_id_raw = data.get("task_id", data.get("id"))
            prompt_raw = data.get("prompt", data.get("message"))
            options_raw = data.get("predefined_options", data.get("options"))
            options_defaults_raw = data.get("predefined_options_defaults")
            timeout_raw = data.get("auto_resubmit_timeout", data.get("timeout"))

            if not isinstance(task_id_raw, str) or not task_id_raw.strip():
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "缺少必要参数：task_id（或 id）",
                        }
                    ),
                    400,
                )
            if not isinstance(prompt_raw, str) or not prompt_raw:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "缺少必要参数：prompt（或 message）",
                        }
                    ),
                    400,
                )

            task_id = task_id_raw.strip()
            prompt = prompt_raw

            predefined_options: list[str] | None = None
            if options_raw is None:
                predefined_options = None
            elif not isinstance(options_raw, list):
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": "predefined_options（或 options）必须是数组",
                        }
                    ),
                    400,
                )
            else:
                cleaned: list[str] = []
                for opt in options_raw:
                    if not isinstance(opt, str):
                        return (
                            jsonify(
                                {
                                    "success": False,
                                    "error": "predefined_options（或 options）元素必须是字符串",
                                }
                            ),
                            400,
                        )
                    s = opt.strip()
                    if s:
                        cleaned.append(s)
                predefined_options = cleaned

            # 解析"默认选中"数组（TODO #3）。校验：必须是 list[bool]，长度可省略；
            # 长度与 predefined_options 不一致时按位置截断/补 False，宽容地尽量保留信息。
            predefined_options_defaults: list[bool] | None = None
            if options_defaults_raw is not None:
                if not isinstance(options_defaults_raw, list):
                    return (
                        jsonify(
                            {
                                "success": False,
                                "error": "predefined_options_defaults 必须是布尔数组",
                            }
                        ),
                        400,
                    )
                normalized_defaults: list[bool] = []
                for d in options_defaults_raw:
                    if isinstance(d, bool):
                        normalized_defaults.append(d)
                    elif isinstance(d, (int, float)):
                        normalized_defaults.append(bool(d))
                    elif isinstance(d, str):
                        normalized_defaults.append(
                            d.strip().lower()
                            in {"true", "1", "yes", "y", "on", "selected"}
                        )
                    else:
                        normalized_defaults.append(False)
                if predefined_options is not None:
                    n = len(predefined_options)
                    if len(normalized_defaults) > n:
                        normalized_defaults = normalized_defaults[:n]
                    elif len(normalized_defaults) < n:
                        normalized_defaults += [False] * (n - len(normalized_defaults))
                predefined_options_defaults = normalized_defaults

            default_timeout = _get_default_auto_resubmit_timeout_from_config()
            timeout_explicit = "auto_resubmit_timeout" in data or "timeout" in data
            if timeout_explicit:
                if timeout_raw is None or isinstance(timeout_raw, bool):
                    return (
                        jsonify(
                            {
                                "success": False,
                                "error": "auto_resubmit_timeout（或 timeout）必须是整数",
                            }
                        ),
                        400,
                    )
                try:
                    timeout_int = int(timeout_raw)
                except Exception:
                    return (
                        jsonify(
                            {
                                "success": False,
                                "error": "auto_resubmit_timeout（或 timeout）必须是整数",
                            }
                        ),
                        400,
                    )
            else:
                timeout_int = default_timeout

            auto_resubmit_timeout = validate_auto_resubmit_timeout(timeout_int)

            try:
                task_queue = get_task_queue()
                success = task_queue.add_task(
                    task_id=task_id,
                    prompt=prompt,
                    predefined_options=predefined_options,
                    predefined_options_defaults=predefined_options_defaults,
                    auto_resubmit_timeout=auto_resubmit_timeout,
                )
            except Exception as e:
                logger.error(f"创建任务失败: {e}", exc_info=True)
                return jsonify({"success": False, "error": "服务器内部错误"}), 500

            if success:
                logger.info(f"任务已通过API添加到队列: {task_id}")
                return jsonify({"success": True, "task_id": task_id})

            logger.error(f"添加任务失败: {task_id}")
            return (
                jsonify({"success": False, "error": "任务队列已满或任务ID重复"}),
                409,
            )

        @self.app.route("/api/tasks/<task_id>", methods=["GET"])
        @self.limiter.limit("300 per minute")
        def get_task(task_id: str) -> ResponseReturnValue:
            """获取单个任务详情
            ---
            tags:
              - Tasks
            parameters:
              - name: task_id
                in: path
                type: string
                required: true
                description: 任务 ID
            responses:
              200:
                description: 任务详情
                schema:
                  type: object
                  properties:
                    success:
                      type: boolean
                    server_time:
                      type: number
                    task:
                      type: object
                      properties:
                        task_id:
                          type: string
                        prompt:
                          type: string
                        status:
                          type: string
                          enum: [pending, active, completed]
                        predefined_options:
                          type: array
                          items:
                            type: string
                        predefined_options_defaults:
                          type: array
                          items:
                            type: boolean
                          description: 与 predefined_options 一一对应的默认选中状态
                        created_at:
                          type: string
                          format: date-time
                        auto_resubmit_timeout:
                          type: number
                        remaining_time:
                          type: number
                        deadline:
                          type: number
                          description: 截止时间戳 (server_time + remaining_time)
                        result:
                          type: object
              404:
                description: 任务不存在
              500:
                description: 服务器内部错误
            """
            try:
                task_queue = get_task_queue()

                # P0：与 GET /api/tasks 同样收口为节流版（参见同文件上方注释）。
                # 此路由是单任务详情查询，hot path 命中率比 /api/tasks 低，
                # 但仍受益于"不在每个请求上重复扫表 + 加锁"。
                task_queue.cleanup_completed_tasks_throttled(
                    age_seconds=10, throttle_seconds=30.0
                )

                task = task_queue.get_task(task_id)

                if not task:
                    return jsonify({"success": False, "error": "任务不存在"}), 404

                server_time = time.time()
                now_monotonic = time.monotonic()
                remaining = task.get_remaining_time(now_monotonic=now_monotonic)

                return jsonify(
                    {
                        "success": True,
                        "server_time": server_time,
                        "task": {
                            "task_id": task.task_id,
                            "prompt": task.prompt,
                            "predefined_options": task.predefined_options,
                            "predefined_options_defaults": (
                                task.predefined_options_defaults
                            ),
                            "status": task.status,
                            "created_at": task.created_at.isoformat(),
                            "auto_resubmit_timeout": task.auto_resubmit_timeout,
                            "remaining_time": remaining,
                            "deadline": server_time + remaining,
                            "result": task.result,
                        },
                    }
                )
            except Exception as e:
                logger.error(f"获取任务失败: {e}", exc_info=True)
                return jsonify({"success": False, "error": "服务器内部错误"}), 500

        @self.app.route("/api/tasks/<task_id>/activate", methods=["POST"])
        @self.limiter.limit("60 per minute")
        def activate_task(task_id: str) -> ResponseReturnValue:
            """激活指定任务
            ---
            tags:
              - Tasks
            parameters:
              - name: task_id
                in: path
                type: string
                required: true
            responses:
              200:
                description: 任务已激活
                schema:
                  type: object
                  properties:
                    success:
                      type: boolean
                    active_task_id:
                      type: string
              400:
                description: 切换任务失败
              404:
                description: 任务不存在
              500:
                description: 服务器内部错误
            """
            try:
                task_queue = get_task_queue()
                success = task_queue.set_active_task(task_id)

                if not success:
                    return jsonify({"success": False, "error": "切换任务失败"}), 400

                return jsonify({"success": True, "active_task_id": task_id})
            except Exception as e:
                logger.error(f"激活任务失败: {e}", exc_info=True)
                return jsonify({"success": False, "error": "服务器内部错误"}), 500

        @self.app.route("/api/tasks/<task_id>/close", methods=["POST"])
        @self.limiter.limit("30 per minute")
        def close_task(task_id: str) -> ResponseReturnValue:
            """关闭（移除）指定任务
            ---
            tags:
              - Tasks
            parameters:
              - name: task_id
                in: path
                type: string
                required: true
            responses:
              200:
                description: 任务已移除
                schema:
                  type: object
                  properties:
                    success:
                      type: boolean
              404:
                description: 任务不存在
              500:
                description: 服务器内部错误
            """
            try:
                task_queue = get_task_queue()
                removed = task_queue.remove_task(task_id)

                if not removed:
                    return jsonify({"success": False, "error": "任务不存在"}), 404

                logger.info(f"任务 {task_id} 已被用户关闭")
                return jsonify({"success": True})
            except Exception as e:
                logger.error(f"关闭任务失败: {e}", exc_info=True)
                return jsonify({"success": False, "error": "服务器内部错误"}), 500

        @self.app.route("/api/tasks/<task_id>/submit", methods=["POST"])
        @self.limiter.limit("60 per minute")
        def submit_task_feedback(task_id: str) -> ResponseReturnValue:
            """提交指定任务的反馈
            ---
            tags:
              - Tasks
            consumes:
              - multipart/form-data
            parameters:
              - name: task_id
                in: path
                type: string
                required: true
              - name: feedback_text
                in: formData
                type: string
                description: 用户反馈文本
              - name: selected_options
                in: formData
                type: string
                description: 已选选项（JSON 数组字符串）
              - name: images
                in: formData
                type: file
                description: 上传的图片文件
            responses:
              200:
                description: 反馈提交成功
                schema:
                  type: object
                  properties:
                    success:
                      type: boolean
                    message:
                      type: string
              400:
                description: 请求参数错误（选项格式不正确）
              404:
                description: 任务不存在
              500:
                description: 服务器内部错误
            """
            try:
                task_queue = get_task_queue()
                task = task_queue.get_task(task_id)

                if not task:
                    return jsonify({"success": False, "error": "任务不存在"}), 404

                feedback_text = request.form.get("feedback_text", "")
                selected_options_raw = request.form.get("selected_options", "[]")
                try:
                    selected_options = json.loads(selected_options_raw)
                except Exception:
                    return (
                        jsonify(
                            {
                                "success": False,
                                "error": "selected_options 必须是 JSON 数组字符串",
                            }
                        ),
                        400,
                    )

                if not isinstance(selected_options, list):
                    return (
                        jsonify(
                            {
                                "success": False,
                                "error": "selected_options 必须是 JSON 数组",
                            }
                        ),
                        400,
                    )

                cleaned_selected_options: list[str] = []
                for opt in selected_options:
                    if not isinstance(opt, str):
                        return (
                            jsonify(
                                {
                                    "success": False,
                                    "error": "selected_options 数组元素必须是字符串",
                                }
                            ),
                            400,
                        )
                    s = opt.strip()
                    if s:
                        cleaned_selected_options.append(s)
                selected_options = cleaned_selected_options

                images = extract_uploaded_images(request)

                result: dict[str, Any] = {
                    "user_input": feedback_text,
                    "selected_options": selected_options,
                }

                if images:
                    result["images"] = images

                task_queue.complete_task(task_id, result)

                logger.info(f"任务 {task_id} 反馈已提交")
                return jsonify({"success": True, "message": msg("feedback.submitted")})
            except Exception as e:
                logger.error(f"提交任务失败: {e}", exc_info=True)
                return jsonify({"success": False, "error": "服务器内部错误"}), 500
