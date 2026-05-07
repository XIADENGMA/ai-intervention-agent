"""任务管理路由 Mixin — 任务列表、创建、详情、激活、提交反馈、SSE 事件流。"""

from __future__ import annotations

import collections
import json
import queue
import threading
import time
from typing import TYPE_CHECKING, Any, TypedDict

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


class SSEBusStatsSnapshot(TypedDict):
    """``_SSEBus.stats_snapshot`` 返回值结构（R47 + R51-B + R58 + R61）。

    用 TypedDict 而不是裸 ``dict[str, int | dict[str, int]]`` 是为了让
    caller 拿到键时能正确推断到具体类型——caller 几乎都是 ``after["emit_total"]
    - before["emit_total"]`` 这种纯数字操作，TypedDict 让 ``ty``/IDE 一眼
    看出 ``emit_total`` 是 ``int`` 而 ``emit_by_type`` 是 ``dict[str, int]``，
    避免每个 caller 都要 ``cast(int, snap["emit_total"])``。
    """

    emit_total: int
    latest_event_id: int
    gap_warnings_emitted: int
    backpressure_discards: int
    subscriber_count: int
    history_size: int
    heartbeat_total: int
    oversize_drops: int
    emit_by_type: dict[str, int]


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

    R40-S2 (Last-Event-ID resume)：
    - 给每条 emit 出去的事件分配单调递增整数 id（``self._next_id``）。
    - 维护一个长度为 ``_HISTORY_MAXLEN`` 的环形缓冲区 ``_history``，存最近的
      ``(id, payload)``，让客户端用 ``Last-Event-ID`` 头 / ``last_event_id``
      query 表达"我最后看到的是这一条"，``subscribe(after_id=N)`` 在 add(q) 之
      前先把 history 里 ``id > N`` 的事件按序 put 进去 → 客户端无感补齐。
    - 如果 ``after_id`` 已经被 evict 出 buffer（断线时间超出 maxlen 容量），
      塞一个 ``gap_warning`` 事件，让客户端知道丢了一些事件，应该主动 fetch
      ``/api/tasks`` 拿最新全量状态。
    """

    _QUEUE_MAXSIZE = 64
    _BACKPRESSURE_THRESHOLD = _QUEUE_MAXSIZE * 3 // 4
    # R40-S2：环形缓冲区长度。SSE 事件一条 ~150B 序列化后 + 包装 ~250B，
    # 128 条 ≈ 32KB / bus 实例，可控；同时覆盖几秒到 1 分钟内的 task 切换
    # 风暴场景（实测 100 个并发任务 status 切换时也才 ~50 条）。
    _HISTORY_MAXLEN = 128

    # R58：单条 SSE 事件序列化后字节上限。超过则**不发**这条事件，把它替
    # 换成一个 ``oversize_drop`` warning。
    #
    # 阈值选取：
    # - 256 KB 是多个 SSE/HTTP 中间件的实战安全线。nginx ``proxy_buffer_size``
    #   默认 8 KB / ``proxy_buffers 4 8k`` 默认共 32 KB，超过就触发 buffer
    #   flush 抖动；Cloudflare Free / Pro 的 ``response_max_body_size`` 上
    #   限 100 MB 但建议单 SSE message ≤ 1 MB；Chrome/Firefox EventSource
    #   实现的 buffer growth 上限 ~16 MB，长期超大消息会触发 GC 抖动。
    # - 我们的合法 SSE event：``task_changed`` 数据 1-2 KB；``config_changed``
    #   元数据 < 500 B；``gap_warning`` < 200 B。256 KB 是合法量级的 100×
    #   以上，永远不会误伤。
    # - 256 KB = 262144 B。``json.dumps`` 后 UTF-8 编码字节计数。
    _OVERSIZE_LIMIT_BYTES: int = 256 * 1024

    def __init__(self) -> None:
        self._subscribers: set[queue.Queue] = set()
        self._lock = threading.Lock()
        # R40-S2：从 0 开始单调递增；emit 拿锁的时候 +=1。
        # 用 int + lock 的方案，不用 itertools.count + atomic：emit 频率 ≤ 数十 Hz，
        # 锁 contention 在 100ns 量级，相比 emit 内的 json.dumps（≤ 5µs）和
        # put_nowait（~1µs * N）忽略不计；同时享受 lock-step 一致性，避免
        # next_id-then-history-append 中间被另一个线程插队导致 history 乱序。
        self._next_id: int = 0
        # 用 deque 保 O(1) append + 自动 evict；存 (id, payload) tuple，
        # subscribe(after_id) 时按序遍历挑出 > after_id 的项。
        self._history: collections.deque[tuple[int, dict]] = collections.deque(
            maxlen=self._HISTORY_MAXLEN
        )
        # R47：运行时计数器，让运维 / client UI 在不订阅 SSE 的情况下评估健康度。
        # 全部走 ``self._lock`` 保护，因为 emit / subscribe / discard 路径已经持锁，
        # 加 3 个 ``int += 1`` 几乎零成本；比起再起一份 ``threading.Lock`` 还简单。
        # 语义：
        # - ``_emit_total``：``emit()`` 被调用的累计次数。基线指标，client UI
        #   能用 ``emit_total - last_event_id`` 推断"emit 完成 vs id 分配"的偏差
        #   （正常情况两者应当一致）。
        # - ``_gap_warnings_emitted``：``subscribe(after_id=...)`` 命中 evict 分支
        #   塞 ``gap_warning`` 的次数。正常 idle Web UI 应当 ≈ 0；持续增长意味着
        #   网络抖动 / VSCode 长时间挂起后重连。
        # - ``_backpressure_discards``：``emit()`` 因 queue Full 或积压超阈值踢
        #   subscriber 的次数。慢消费者（浏览器 tab 卡死、机器换页风暴）会让它涨。
        # - ``_heartbeat_total``（R51-B）：generator 因 ``q.get(timeout)``
        #   超时而 yield 一帧 ``event: heartbeat`` 的累计次数。N 个连接每
        #   25 s 各 +1，闲置 24 h 大概 (3600/25)*24 ≈ 3.5 k；持续不涨意味
        #   着 generator 被卡住或所有连接都很活跃。
        self._emit_total: int = 0
        self._gap_warnings_emitted: int = 0
        self._backpressure_discards: int = 0
        self._heartbeat_total: int = 0
        # R58：超过 ``_OVERSIZE_LIMIT_BYTES`` 序列化字节的 emit 调用次数。
        # 正常稳定运行应当永远 = 0；非零意味着有人在 emit 不正常的大 payload
        # （日志包含整段 stderr？把整个 task 表都 dump 进去？误把 binary 当
        # JSON 序列化？），需要排查。
        self._oversize_drops: int = 0
        # R61：每事件类型的 emit 计数 histogram。相比 ``_emit_total`` 的
        # 单一基线指标，这里把 ``task_changed`` / ``config_changed`` /
        # ``gap_warning`` / ``oversize_drop`` 等分桶累加，让 dashboard 一眼
        # 看清楚 SSE 流量是被哪类事件占主导（持续涨 ``backpressure_discards``
        # 时配合本表能立即定位是哪条事件涨太快）。``Counter`` 自带
        # ``most_common()``，UI 想出 top-N 直接调。所有写入都走 ``_lock``
        # 保护，``stats_snapshot`` 返回时也走锁内 ``dict(...)`` 浅拷贝避免
        # 并发改写。
        self._emit_by_type: collections.Counter[str] = collections.Counter()

    def subscribe(self, after_id: int | None = None) -> queue.Queue:
        """订阅 SSE 事件流；可选 ``after_id`` 触发缺失事件回放。

        ``after_id``（来自 ``Last-Event-ID`` header / query）= 客户端最后看到
        的事件 id。补发策略：
        - ``None``：纯订阅，从订阅时刻起的下一条 emit 开始收。
        - 落在 history 范围内（``oldest_id <= after_id < latest_id``）：把
          history 里 ``id > after_id`` 的事件按序压入新 queue，客户端无感补齐。
        - ``after_id`` 太旧（已被 evict）或 ``after_id < 0`` 但 history 非空：
          塞一个 ``gap_warning`` 事件 + 后续所有 history（如 history 仍非空），
          告诉客户端"我可能丢了若干事件，请主动 refetch 全量"。
        - ``after_id`` 比 ``_next_id - 1`` 还大（客户端比 server 还新，说明
          server 重启了 _next_id 归零）：当作首次订阅，可选发 reset 事件，但
          为了简单先按 ``None`` 处理，gap_warning 已经覆盖兜底。
        """
        q: queue.Queue = queue.Queue(maxsize=self._QUEUE_MAXSIZE)

        # 单一锁内完成「snapshot history → add subscriber」原子操作，让 emit
        # 不会在 subscribe 拿 history 和加入 _subscribers 之间插队 → 避免
        # 「补发 history 和后续 emit 之间漏一条 / 重复一条」的竞态。
        with self._lock:
            replay_items: list[dict] = []
            inject_gap_warning = False

            if after_id is not None and self._history:
                oldest_id, _ = self._history[0]
                latest_id, _ = self._history[-1]
                if after_id < oldest_id - 1:
                    # 太旧：buffer 已 evict，必然丢事件。塞 gap_warning + 全部
                    # 当前 history（让客户端至少拿到最新窗口里的事件，之后客户端
                    # 自己 fetch 全量）。
                    inject_gap_warning = True
                    self._gap_warnings_emitted += 1
                    replay_items = [payload for _, payload in self._history]
                elif after_id < latest_id:
                    # 在 history 范围内，正常补发。
                    replay_items = [
                        payload
                        for evt_id, payload in self._history
                        if evt_id > after_id
                    ]
                # after_id == latest_id 或 after_id > latest_id：客户端是
                # up-to-date 或者比 server 还新（server 重启 _next_id=0），都不补发。

            self._subscribers.add(q)

        if inject_gap_warning:
            warning_data = {
                "reason": "history_evicted",
                "after_id": after_id,
            }
            try:
                warning_serialized = json.dumps(warning_data, ensure_ascii=False)
            except (TypeError, ValueError):
                warning_serialized = None
            warning_payload = {
                "id": -1,
                "type": "gap_warning",
                "data": warning_data,
                "_serialized": warning_serialized,
            }
            try:
                q.put_nowait(warning_payload)
            except queue.Full:
                # 新 queue maxsize=64，刚 subscribe 不可能 Full；这里只是防御性兜底。
                pass

        for payload in replay_items:
            try:
                q.put_nowait(payload)
            except queue.Full:
                # 同上，刚创建的 queue 不会 Full；保险起见忽略多余的补发。
                break

        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            self._subscribers.discard(q)

    def emit(self, event_type: str, data: dict | None = None) -> None:
        # R20.14-C：单次预序列化复用给所有订阅者
        # ----------------------------------------------------------------
        # 历史实现里每个 SSE generator 在 yield 前自己做一次
        # ``json.dumps(event['data'])``。N 个订阅者就 dumps N 次同一份数据；
        # 在订阅者数 ≥ 3 的浏览器多 tab / VSCode webview + 状态栏并存场景下
        # 是纯浪费。把序列化 hoist 到 emit 里一次，附带写进 payload 的
        # ``_serialized`` 字段（详见 ``sse_events`` generator 处的消费逻辑）。
        # 失败兜底：序列化抛异常时退化到 ``None``，generator 看见 None 时再
        # 回退到 on-demand dumps，保留原行为不让单条坏数据让整个 SSE 总线挂掉。
        #
        # R40-S2：把 id 分配 + history append + subscriber snapshot 三步并
        # 入同一个 ``_lock`` 临界区。原 R20.14-C 注释里的「snapshot 之后新加
        # 入的订阅者不会收到本条事件」语义保持不变；新订阅者拿不到这条 emit
        # 对应的 payload，但能通过 ``subscribe(after_id=...)`` 在下一次重连时
        # 从 history 里拿回——这正是 Last-Event-ID resume 的用途。
        try:
            serialized_data = json.dumps(data or {}, ensure_ascii=False)
        except (TypeError, ValueError):
            serialized_data = None

        # R58：如果序列化字节数超过阈值，把这条 emit 替换成一个 ``oversize_drop``
        # warning（自身只携带元数据，不含原 payload）。原 payload 不发，避
        # 免单条 256 KB+ 事件 fan-out 给 N 个订阅者时占用 N×size 网络/内存。
        # ``oversize_drop`` 仍然占用 id 槽位、仍然被 client EventSource 看
        # 到，所以不会引起 ``Last-Event-ID`` resume 的 gap_warning。
        if serialized_data is not None:
            payload_bytes = len(serialized_data.encode("utf-8"))
            if payload_bytes > self._OVERSIZE_LIMIT_BYTES:
                with self._lock:
                    self._oversize_drops += 1
                # 留住原 event_type 当 metadata，方便 client UI / dashboard
                # 知道是"哪种事件被丢了"。
                original_event_type = event_type
                event_type = "oversize_drop"
                data = {
                    "original_event_type": original_event_type,
                    "size_bytes": payload_bytes,
                    "limit_bytes": self._OVERSIZE_LIMIT_BYTES,
                }
                try:
                    serialized_data = json.dumps(data, ensure_ascii=False)
                except (TypeError, ValueError):
                    serialized_data = None

        with self._lock:
            self._next_id += 1
            self._emit_total += 1
            # R61：按 event_type 分桶累加。``oversize_drop`` 替换路径会用替换
            # 后的 type（``"oversize_drop"`` 而非原 ``"task_changed"``），这正
            # 是我们想看到的——dashboard 能直接观测到"这一桶 oversize 事件
            # 实际上来自哪个上游 type"，因为替换后的 ``data["original_event_type"]``
            # 仍然保留了原 type 名。
            self._emit_by_type[event_type] += 1
            event_id = self._next_id
            payload = {
                "id": event_id,
                "type": event_type,
                "data": data or {},
                "_serialized": serialized_data,
            }
            self._history.append((event_id, payload))

            # R27.4：无订阅者时直接返回，避免状态变更在无人消费时仍做投递。
            # 注意：history 必须 **在** 无订阅者快速返回之前 append——这正是
            # Last-Event-ID resume 想要的：「事件已发生，client 重连时能补」。
            if not self._subscribers:
                return

            snapshot = list(self._subscribers)

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
        # R47：同时把 backpressure 计数器在持锁期间累加；放在锁内是因为这本身
        # 就是 lock 的天然临界区，不会增加任何锁等待时间。
        with self._lock:
            for q in dead:
                self._subscribers.discard(q)
            self._backpressure_discards += len(dead)

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

    @property
    def latest_event_id(self) -> int:
        """最近一次 emit 出去的事件 id；用于诊断 / 测试。"""
        with self._lock:
            return self._next_id

    def history_snapshot(self) -> list[tuple[int, dict]]:
        """复制一份 history 给测试 / 诊断用，永远不返回内部状态引用。"""
        with self._lock:
            return list(self._history)

    def bump_heartbeat(self) -> None:
        """generator yield heartbeat 一帧时调用，把 ``_heartbeat_total`` 加 1。

        R51-B：分离出独立方法是为了单元测试不依赖真起 Flask 的 generator
        就能断言计数器涨了。线程安全：``self._lock`` 保证写不丢。"""
        with self._lock:
            self._heartbeat_total += 1

    def stats_snapshot(self) -> SSEBusStatsSnapshot:
        """返回 SSE 总线的运行时计数器快照（R47 + R51-B）。

        字段语义：
        - ``emit_total``：``emit()`` 调用累计次数；
        - ``latest_event_id``：最近一次 emit 分配的 id（``= _next_id``）；
        - ``gap_warnings_emitted``：``subscribe(after_id=...)`` 命中 evict 分支
          的累计次数（持续上涨意味着客户端经常带着过老的 token 重连）；
        - ``backpressure_discards``：``emit()`` 因 queue Full / 积压超阈值踢
          subscriber 的累计次数（持续上涨意味着浏览器 tab / extension 端有
          慢消费者）；
        - ``subscriber_count``：当前活跃订阅者数（基线指标）；
        - ``history_size``：当前 history deque 长度（≤ ``_HISTORY_MAXLEN``）；
        - ``heartbeat_total``（R51-B）：generator 因 ``q.get`` 超时而 yield
          一帧 ``event: heartbeat`` 的累计次数。

        所有字段都是单调累计（除了 ``subscriber_count`` / ``history_size`` 是
        瞬时值），caller 可以记录两次快照后做差，得到一段窗口内的速率。
        """
        with self._lock:
            return {
                "emit_total": self._emit_total,
                "latest_event_id": self._next_id,
                "gap_warnings_emitted": self._gap_warnings_emitted,
                "backpressure_discards": self._backpressure_discards,
                "subscriber_count": len(self._subscribers),
                "history_size": len(self._history),
                "heartbeat_total": self._heartbeat_total,
                # R58：超过 _OVERSIZE_LIMIT_BYTES 被替换成 oversize_drop 的次数
                "oversize_drops": self._oversize_drops,
                # R61：每事件类型的 emit 计数。返回 dict 浅拷贝，调用方外部
                # 修改不影响内部 Counter；UI 想出 top-N 自行 ``Counter(...).most_common(n)``。
                "emit_by_type": dict(self._emit_by_type),
            }


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

            # R40-S2：双通道 Last-Event-ID 解析（query 优先 → header → None）
            # ----------------------------------------------------------------
            # 浏览器原生 EventSource 在重连时会自动带 ``Last-Event-ID`` header
            # （HTML Living Standard），但有两类场景拿不到这个 header：
            #   1) 客户端主动 close + new EventSource（VSCode 插件断线重连
            #      策略、PWA "刷新连接" 按钮等）—— 此时不是浏览器自动 retry，
            #      header 不会自动注入；
            #   2) 跨来源 / Service Worker 缓存场景下中间代理偶尔会 strip 掉
            #      自定义 header，导致服务端始终看不到 resume token。
            # 因此除了支持标准 header，再支持 ``?last_event_id=N`` query 作为
            # 通用 fallback：客户端只要把 query 拼上，无论何种重连路径都能传
            # resume token。query 优先于 header，让"客户端明确要求"压过"浏览器
            # 默认重传"，避免两边不一致时拿到旧值（极小概率，但足以让 gap_warning
            # 决策错乱）。
            after_id_raw = (
                request.args.get("last_event_id")
                or request.headers.get("Last-Event-ID")
                or ""
            )
            after_id: int | None = None
            if after_id_raw:
                try:
                    after_id_value = int(str(after_id_raw).strip())
                    # 负数 / 0 都按 None 处理：
                    # - 负数没意义（emit id 从 1 起），用户明显是构造异常 token
                    # - 0 是哨兵（``_SSEBus._next_id`` 初值），表示"我什么都没看到过"，
                    #   等价于全新订阅，用 None 走"纯订阅"路径。
                    if after_id_value > 0:
                        after_id = after_id_value
                except (ValueError, TypeError):
                    after_id = None

            q = _sse_bus.subscribe(after_id=after_id)

            def generate():
                try:
                    while True:
                        try:
                            event = q.get(timeout=25)
                        except queue.Empty:
                            # R51-B：把 SSE comment 心跳升级为 named event。
                            # comment 行（``: heartbeat\n\n``）只能让中间代理
                            # 看到"还有字节",但浏览器 ``EventSource`` / VSCode
                            # webview 看不到，监控不到 server-side liveness。
                            # 改成 named event 后 client 可以
                            # ``addEventListener('heartbeat', ...)`` 估算 RTT、
                            # detect 应用层卡死，且 SSE 协议规范规定未注册
                            # listener 会自动忽略，向后兼容。
                            _sse_bus.bump_heartbeat()
                            try:
                                hb_payload = json.dumps(
                                    {"ts_unix": int(time.time())},
                                    ensure_ascii=False,
                                )
                            except (TypeError, ValueError):
                                hb_payload = "{}"
                            yield f"event: heartbeat\ndata: {hb_payload}\n\n"
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
                        # R40-S2：合法事件输出 ``id: N`` 行让浏览器
                        # ``EventSource`` 维护 ``e.lastEventId``，重连时自动
                        # 把它带回 ``Last-Event-ID`` header；客户端断线
                        # 重建时也能从我们给的 query 拿同样的 token。
                        # ``gap_warning`` 用 id=-1 做哨兵：它是补偿事件，
                        # 不应该成为客户端 resume 的锚点（否则下次重连会
                        # 用 -1 当 after_id，sub 又会再发一条 gap_warning，
                        # 死循环）。这里只为正整数 id 输出 ``id:`` 行。
                        event_id = event.get("id") if isinstance(event, dict) else None
                        event_type = (
                            event.get("type") if isinstance(event, dict) else None
                        ) or "message"
                        if isinstance(event_id, int) and event_id > 0:
                            yield (
                                f"id: {event_id}\n"
                                f"event: {event_type}\n"
                                f"data: {serialized}\n\n"
                            )
                        else:
                            yield f"event: {event_type}\ndata: {serialized}\n\n"
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
