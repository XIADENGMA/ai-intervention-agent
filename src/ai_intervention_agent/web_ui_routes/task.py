"""任务管理路由 Mixin — 任务列表、创建、详情、激活、提交反馈、SSE 事件流。"""

from __future__ import annotations

import collections
import json
import os
import queue
import threading
import time
from datetime import UTC
from datetime import datetime as _dt
from typing import TYPE_CHECKING, Any, TypedDict

from flask import Response, jsonify, request
from flask.typing import ResponseReturnValue

from ai_intervention_agent.enhanced_logging import EnhancedLogger
from ai_intervention_agent.i18n import msg
from ai_intervention_agent.sse_event_schemas import validate_payload
from ai_intervention_agent.task_constants import PLACEHOLDER_MAX_LENGTH
from ai_intervention_agent.task_queue_singleton import get_task_queue
from ai_intervention_agent.web_ui_routes._upload_helpers import extract_uploaded_images

if TYPE_CHECKING:
    from flask import Flask

    from ai_intervention_agent.web_ui_rate_limiter import WebUiLimiterProtocol

logger = EnhancedLogger(__name__)


# R205 / Cycle 9 · F-204-1 (CR#21 §4.3): SSE schema runtime validation
# toggle. R198 把 ``validate_payload`` API 暴露好了但**故意不在 production
# emit 路径调用**（hot path 性能优先, 见 sse_event_schemas.py 模块
# docstring "设计取舍" 章节）。F-204-1 加一个 env-var 控制的 toggle, 让
# 运维 / 调试期可以选择性开启验证, 不污染 default zero-overhead 行为:
#
# - ``off`` (default): emit() 不调 validate_payload, 0 开销, 与 R198 现状
#   完全一致;
# - ``warn``: emit() 调 validate_payload, violations → logger.warning +
#   ``_schema_violation_total`` 计数器累加, 但 emit 继续 fanout (不阻塞);
# - ``strict``: 同 warn, 但 violations 走 logger.error (运维更易 alert)
#   且 emit 继续 fanout。**不**抛异常——emit 是 fire-and-forget, 大部分
#   emit-site 没 try/except 包裹, raise 会让 production 挂。strict 与
#   warn 的唯一差异是 log level, 方便 alertmanager / on-call 路由不同
#   severity 到不同 channel。
#
# 取值合法性：unknown / typo (e.g. "STRICT" / "yes") → fall back 到 off
# + 启动 log.warning 一次, 避免 silently 不验证 让运维以为开了实际没生效。
_SSE_SCHEMA_VALIDATE_ENV_VAR: str = "AIIA_SSE_SCHEMA_VALIDATE"
_SSE_SCHEMA_VALIDATE_DEFAULT_MODE: str = "off"
_SSE_SCHEMA_VALIDATE_VALID_MODES: frozenset[str] = frozenset({"off", "warn", "strict"})


COUNTDOWN_EXTENDS_MAX: int = 3
COUNTDOWN_EXTEND_DEFAULT_SECONDS: int = 60
COUNTDOWN_EXTEND_SECONDS_MIN: int = 10
COUNTDOWN_EXTEND_SECONDS_MAX: int = 300


def _read_sse_schema_validate_mode() -> str:
    """读 ``AIIA_SSE_SCHEMA_VALIDATE`` 环境变量, 返回合法的 mode。

    Twelve-Factor 风格 sticky 读取——production 单例 ``_sse_bus`` 在 module
    load 时初始化, 启动后改 env var **不会** 生效（这是 acceptable, 与项目
    其他 ``AIIA_*`` env-var toggle 行为一致）。

    无效值 → fall back ``off`` + WARN 一次 (在 ``_SSEBus.__init__`` 里 log)。
    """
    raw = os.environ.get(_SSE_SCHEMA_VALIDATE_ENV_VAR, "").strip().lower()
    if not raw:
        return _SSE_SCHEMA_VALIDATE_DEFAULT_MODE
    if raw in _SSE_SCHEMA_VALIDATE_VALID_MODES:
        return raw
    return _SSE_SCHEMA_VALIDATE_DEFAULT_MODE


class SSELatencySnapshot(TypedDict):
    """R134：emit→deliver 延迟分布快照。

    P50 / P95 单位是 **毫秒**（float, 2 位小数），count 是当前 ring
    buffer 实际样本数；``count == 0`` 时 p50 / p95 都是 ``None``，让
    monitoring caller 一眼分辨"刚启动还没数据"和"延迟为零"。
    """

    p50_ms: float | None
    p95_ms: float | None
    count: int


class SSEBusStatsSnapshot(TypedDict):
    """``_SSEBus.stats_snapshot`` 返回值结构（R47 + R51-B + R58 + R61 + R134 + R205）。

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
    latency_ms: SSELatencySnapshot

    schema_validate_mode: str
    schema_violation_total: int


_SSE_DISCONNECT_SENTINEL = object()
_SSE_EMPTY_JSON = "{}"


_TRUTHY_QUERY: frozenset[str] = frozenset({"true", "1", "yes", "on"})
_FALSY_QUERY: frozenset[str] = frozenset({"false", "0", "no", "off"})


def _format_sse_heartbeat_payload(now_unix: Any | None = None) -> str:
    """Return the heartbeat SSE data payload.

    Heartbeat data is always a single integer field. Keep this out of the
    generic JSON encoder so every idle SSE connection avoids allocating a dict
    and walking ``json.dumps`` on each 25s heartbeat.
    """
    try:
        ts_unix = int(time.time() if now_unix is None else now_unix)
    except (OverflowError, TypeError, ValueError):
        return "{}"
    return f'{{"ts_unix":{ts_unix}}}'


def _format_sse_gap_warning_payload(after_id: int) -> str:
    """Return the fixed-schema gap warning SSE data payload."""
    return f'{{"reason":"history_evicted","after_id":{after_id}}}'


def _format_sse_oversize_drop_payload(
    original_event_type: str,
    size_bytes: int,
    limit_bytes: int,
) -> str | None:
    """Return the fixed-schema oversize_drop SSE data payload.

    ``original_event_type`` remains free-form, so delegate just that string to
    the JSON encoder for correct escaping. The two byte counts are internal
    integers; formatting them directly avoids allocating and walking a metadata
    dict on the oversize warning path.
    """
    try:
        event_type_json = json.dumps(original_event_type, ensure_ascii=False)
    except (TypeError, ValueError):
        return None
    return (
        '{"original_event_type":'
        f'{event_type_json},"size_bytes":{size_bytes},'
        f'"limit_bytes":{limit_bytes}'
        "}"
    )


def _serialize_sse_payload(data: Any) -> tuple[Any, str | None]:
    """Normalize and serialize SSE payload data.

    ``emit`` historically treats every falsy payload as an empty object. Keep
    that contract, but avoid running the generic JSON encoder for the stable
    empty-object case.
    """
    payload_data = data or {}
    if not payload_data:
        return payload_data, _SSE_EMPTY_JSON
    try:
        return payload_data, json.dumps(payload_data, ensure_ascii=False)
    except (TypeError, ValueError):
        return payload_data, None


def _sse_serialized_utf8_exceeds_limit(serialized: str, limit: int) -> tuple[bool, int]:
    """Return whether ``serialized`` can exceed ``limit`` UTF-8 bytes.

    UTF-8 encodes one Unicode code point as at most 4 bytes. Most SSE events are
    tiny JSON strings, so ``len(serialized) * 4 <= limit`` proves they are under
    the byte cap without allocating a temporary ``bytes`` object. Near the cap,
    encode once and return the exact byte count for oversize metadata.
    """
    char_count = len(serialized)
    if char_count * 4 <= limit:
        return False, char_count
    if serialized.isascii():
        return char_count > limit, char_count
    byte_count = len(serialized.encode("utf-8"))
    return byte_count > limit, byte_count


def _parse_bool_query(raw: str | None, *, default: bool) -> bool:
    """把 query 参数字符串解析成 bool，未识别值返回 ``default``。"""
    if raw is None:
        return default
    norm = raw.strip().lower()
    if norm in _TRUTHY_QUERY:
        return True
    if norm in _FALSY_QUERY:
        return False
    return default


def _parse_since_iso(raw: str | None) -> tuple[_dt | None, str | None]:
    """R135 — 解析 ``?since=<ISO>`` 参数为 UTC ``datetime``。

    返回 ``(parsed_dt, error)``：
    - ``raw`` 缺失 / 空字符串 → ``(None, None)``，调用方走全量导出。
    - 合法 ISO（带或不带时区）→ ``(<aware datetime>, None)``；不带时区
      时按 ``UTC`` 处理，与 ``Task.created_at`` 全部 UTC-aware 的契约
      保持一致。
    - 不可解析 → ``(None, <human msg>)``，调用方应当返回 400。

    `_dt.fromisoformat` 在 Python 3.11+ 接受 ``2024-01-15T00:00:00Z``
    形式（直接消化 ``Z`` 后缀）；3.10 及之前不接受 ``Z``，所以本
    helper 在解析前显式把单字符 ``Z`` 替换成 ``+00:00`` 兜底。"""
    if raw is None:
        return None, None
    norm = raw.strip()
    if not norm:
        return None, None

    if norm.endswith("Z"):
        norm = norm[:-1] + "+00:00"
    try:
        parsed = _dt.fromisoformat(norm)
    except ValueError:
        return None, "since 必须是 ISO 8601 时间戳（如 2024-01-15T00:00:00Z）"
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed, None


def _task_modified_since(task: Any, since: _dt) -> bool:
    """R135 — 判断 task 是否在 ``since`` 之后变化过。

    "变化" = 「创建于 since 之后」或「完成于 since 之后」。pending →
    active 状态切换没有独立时间戳（``Task`` 模型只暴露 ``created_at``
    + ``completed_at``），对增量导出而言无影响——active 化只改变 task
    的 ``status`` enum，下次全量同步时自然消化。

    边界：
    - ``task.created_at`` 永远是 ``datetime``（UTC-aware），无需 None 处理。
    - ``task.completed_at`` 可能 None（未完成），其语义是「尚未变化到
      completed」，不进 since 滤布。
    - ``since`` 必须 UTC-aware（由 ``_parse_since_iso`` 保证）。"""
    created_at = getattr(task, "created_at", None)
    if created_at is not None and created_at >= since:
        return True
    completed_at = getattr(task, "completed_at", None)
    return completed_at is not None and completed_at >= since


def _strip_images_from_result(
    result: dict[str, Any] | None, include_images: bool
) -> dict[str, Any] | None:
    """根据 ``include_images`` 决定是否剥掉 ``result.images[].data``。

    - ``include_images = True``（R125 默认）→ 直接返回原 ``result``，
      零拷贝零开销；
    - ``include_images = False`` → 浅拷贝 ``result``，把 ``images`` 数组
      内每张图的 ``data`` 字段（base64 体）剔除，仅保留 ``filename`` /
      ``size`` / ``content_type`` / ``mime_type`` / ``mimeType`` 这些元
      数据，并在结果顶层加 ``images_stripped: true`` 让消费方一眼分辨
      "这次导出已经故意剥过图"，避免下游误以为这就是用户原始 result。
    - ``result`` 为 ``None`` / 没有 ``images`` 字段 / ``images`` 不是 list
      → no-op，保留原样不冒"非典型 result 造成 KeyError"风险。
    """
    if include_images:
        return result
    if not isinstance(result, dict):
        return result
    images = result.get("images")
    if not isinstance(images, list):
        return result
    stripped_images: list[dict[str, Any]] = []
    for img in images:
        if not isinstance(img, dict):
            stripped_images.append(img)
            continue
        meta = {k: v for k, v in img.items() if k != "data"}
        stripped_images.append(meta)
    sanitized = result.copy()
    sanitized["images"] = stripped_images
    sanitized["images_stripped"] = True
    return sanitized


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

    _HISTORY_MAXLEN = 128

    _OVERSIZE_LIMIT_BYTES: int = 256 * 1024

    _LATENCY_SAMPLES_MAXLEN: int = 512

    # → Prometheus ``aiia_sse_emit_by_type_total`` exposition payload 拖

    _EMIT_BY_TYPE_MAX_CARDINALITY: int = 100
    _EMIT_BY_TYPE_OVERFLOW_BUCKET: str = "__other__"

    def __init__(self) -> None:
        self._subscribers: set[queue.Queue] = set()
        self._lock = threading.Lock()

        self._next_id: int = 0

        self._history: collections.deque[tuple[int, dict]] = collections.deque(
            maxlen=self._HISTORY_MAXLEN
        )

        self._emit_total: int = 0
        self._gap_warnings_emitted: int = 0
        self._backpressure_discards: int = 0
        self._heartbeat_total: int = 0

        self._oversize_drops: int = 0

        self._emit_by_type: collections.Counter[str] = collections.Counter()

        self._emit_by_type_cap_hit_warned: bool = False

        raw_mode = os.environ.get(_SSE_SCHEMA_VALIDATE_ENV_VAR, "").strip().lower()
        if raw_mode and raw_mode not in _SSE_SCHEMA_VALIDATE_VALID_MODES:
            logger.warning(
                "R205: %s=%r is not a valid mode (expected one of %s); "
                "falling back to %r. Set the env var before process start "
                "to take effect.",
                _SSE_SCHEMA_VALIDATE_ENV_VAR,
                raw_mode,
                sorted(_SSE_SCHEMA_VALIDATE_VALID_MODES),
                _SSE_SCHEMA_VALIDATE_DEFAULT_MODE,
            )
        self._schema_validate_mode: str = _read_sse_schema_validate_mode()
        self._schema_violation_total: int = 0
        if self._schema_validate_mode != _SSE_SCHEMA_VALIDATE_DEFAULT_MODE:
            logger.info(
                "R205: SSE schema validation enabled at mode=%r via %s. "
                "Violations will be logged at level=%s; counter exposed as "
                "stats_snapshot()['schema_violation_total'].",
                self._schema_validate_mode,
                _SSE_SCHEMA_VALIDATE_ENV_VAR,
                "ERROR" if self._schema_validate_mode == "strict" else "WARNING",
            )

        self._latency_samples_ns: collections.deque[int] = collections.deque(
            maxlen=self._LATENCY_SAMPLES_MAXLEN
        )

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

        with self._lock:
            replay_items: list[dict] = []
            inject_gap_warning = False

            if after_id is not None and self._history:
                oldest_id, _ = self._history[0]
                latest_id, _ = self._history[-1]
                if after_id < oldest_id - 1:
                    inject_gap_warning = True
                    self._gap_warnings_emitted += 1
                    replay_budget = self._QUEUE_MAXSIZE - 1
                    if replay_budget > 0:
                        for replay_count, (_, payload) in enumerate(self._history, 1):
                            replay_items.append(payload)
                            if replay_count >= replay_budget:
                                break
                elif after_id < latest_id:
                    for evt_id, payload in reversed(self._history):
                        if evt_id <= after_id:
                            break
                        replay_items.append(payload)
                    replay_items.reverse()

            self._subscribers.add(q)

        if inject_gap_warning:
            assert after_id is not None
            warning_data = {
                "reason": "history_evicted",
                "after_id": after_id,
            }
            warning_payload = {
                "id": -1,
                "type": "gap_warning",
                "data": warning_data,
                "_serialized": _format_sse_gap_warning_payload(after_id),
            }
            try:
                q.put_nowait(warning_payload)
            except queue.Full:
                pass

        for payload in replay_items:
            try:
                q.put_nowait(payload)
            except queue.Full:
                break

        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            self._subscribers.discard(q)

    def emit(self, event_type: str, data: dict | None = None) -> None:
        if self._schema_validate_mode != _SSE_SCHEMA_VALIDATE_DEFAULT_MODE:
            violations = validate_payload(event_type, data)
            if violations:
                log_fn = (
                    logger.error
                    if self._schema_validate_mode == "strict"
                    else logger.warning
                )
                for v in violations:
                    log_fn(
                        "R205 SSE schema %s violation: %s",
                        self._schema_validate_mode,
                        v,
                    )
                with self._lock:
                    self._schema_violation_total += 1

        data, serialized_data = _serialize_sse_payload(data)

        if serialized_data is not None:
            exceeds_limit, payload_bytes = _sse_serialized_utf8_exceeds_limit(
                serialized_data,
                self._OVERSIZE_LIMIT_BYTES,
            )
            if exceeds_limit:
                with self._lock:
                    self._oversize_drops += 1

                original_event_type = event_type
                event_type = "oversize_drop"
                data = {
                    "original_event_type": original_event_type,
                    "size_bytes": payload_bytes,
                    "limit_bytes": self._OVERSIZE_LIMIT_BYTES,
                }
                serialized_data = _format_sse_oversize_drop_payload(
                    original_event_type,
                    payload_bytes,
                    self._OVERSIZE_LIMIT_BYTES,
                )

        emit_ts_ns = time.monotonic_ns()

        with self._lock:
            self._next_id += 1
            self._emit_total += 1
            emit_by_type = self._emit_by_type

            if (
                event_type not in emit_by_type
                and len(emit_by_type) >= self._EMIT_BY_TYPE_MAX_CARDINALITY
            ):
                overflow_bucket = self._EMIT_BY_TYPE_OVERFLOW_BUCKET

                if not self._emit_by_type_cap_hit_warned:
                    logger.warning(
                        "R203: SSE _emit_by_type cap (%d distinct event_type) "
                        "hit; further new event_type emits will be accumulated "
                        "under %r bucket. First overflow event_type: %r. "
                        "Consider raising _EMIT_BY_TYPE_MAX_CARDINALITY or "
                        "auditing emit-site code for runaway dynamic "
                        "event_type strings.",
                        self._EMIT_BY_TYPE_MAX_CARDINALITY,
                        overflow_bucket,
                        event_type,
                    )
                    self._emit_by_type_cap_hit_warned = True
                emit_by_type[overflow_bucket] += 1
            else:
                emit_by_type[event_type] += 1
            event_id = self._next_id
            payload = {
                "id": event_id,
                "type": event_type,
                "data": data,
                "_serialized": serialized_data,
                "_emit_ts_ns": emit_ts_ns,
            }
            self._history.append((event_id, payload))

            if not self._subscribers:
                return

            snapshot = list(self._subscribers)

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

        with self._lock:
            for q in dead:
                self._subscribers.discard(q)
            self._backpressure_discards += len(dead)

        for q in dead:
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

    def record_emit_to_deliver_latency_ns(self, latency_ns: int) -> None:
        """R134：把一条 emit→deliver 延迟样本（ns）追加到环形缓冲。

        - generator 在真正 yield 给 SSE 客户端那一瞬间调用，输入是
          ``time.monotonic_ns() - payload['_emit_ts_ns']``。
        - 负数（极罕见，monotonic_ns 理论上不会回拨，但单元测试里 mock
          时可能凑出）静默丢弃，避免污染 P50/P95 统计。
        - ``deque(maxlen=...)`` 自带 evict，无需手动管理容量。
        - 持 ``self._lock``，与 ``stats_snapshot`` 读取互斥。"""
        if latency_ns < 0:
            return
        with self._lock:
            self._latency_samples_ns.append(latency_ns)

    def _compute_latency_snapshot(self) -> SSELatencySnapshot:
        """R134：基于当前 ``_latency_samples_ns`` 算 P50/P95（ms, 2 位小数）。

        必须在持 ``self._lock`` 时调用。empty / singleton / up-to-four-sample
        fast path 只读长度和端点元素；larger-sample 路径才用
        ``list(samples_ns)`` 做快照，避免 deque 在多线程并发
        ``append`` 时遍历抛 ``RuntimeError: deque mutated during iteration``。
        - 算法：nearest-rank percentile（``sorted[int(N * pct)]``，pct ∈
          [0,1)）。N=512 时 P95 索引 = 486，P50 = 256；nearest-rank 比
          线性插值简单稳定，监控用 ±1ms 精度足够。
        - count = 0 时 p50/p95 全 None；count == 1 时 p50 = p95 = 唯一
          样本。
        """
        samples_ns = self._latency_samples_ns
        count = len(samples_ns)
        if count == 0:
            return {"p50_ms": None, "p95_ms": None, "count": 0}
        if count == 1:
            sample_ms = round(samples_ns[0] / 1_000_000.0, 2)
            return {"p50_ms": sample_ms, "p95_ms": sample_ms, "count": 1}
        if count == 2:
            first_sample = samples_ns[0]
            second_sample = samples_ns[1]
            p_sample = first_sample if first_sample >= second_sample else second_sample
            sample_ms = round(p_sample / 1_000_000.0, 2)
            return {"p50_ms": sample_ms, "p95_ms": sample_ms, "count": 2}
        if count == 3:
            first_sample = samples_ns[0]
            second_sample = samples_ns[1]
            third_sample = samples_ns[2]
            if first_sample <= second_sample:
                low_sample = first_sample
                high_sample = second_sample
            else:
                low_sample = second_sample
                high_sample = first_sample
            if third_sample <= low_sample:
                p50_sample = low_sample
                p95_sample = high_sample
            elif third_sample >= high_sample:
                p50_sample = high_sample
                p95_sample = third_sample
            else:
                p50_sample = third_sample
                p95_sample = high_sample
            p50_ms = round(p50_sample / 1_000_000.0, 2)
            p95_ms = round(p95_sample / 1_000_000.0, 2)
            return {"p50_ms": p50_ms, "p95_ms": p95_ms, "count": 3}
        if count == 4:
            first_sample = samples_ns[0]
            second_sample = samples_ns[1]
            third_sample = samples_ns[2]
            fourth_sample = samples_ns[3]
            if first_sample >= second_sample:
                pair_a_high = first_sample
                pair_a_low = second_sample
            else:
                pair_a_high = second_sample
                pair_a_low = first_sample
            if third_sample >= fourth_sample:
                pair_b_high = third_sample
                pair_b_low = fourth_sample
            else:
                pair_b_high = fourth_sample
                pair_b_low = third_sample
            if pair_a_high >= pair_b_high:
                p95_sample = pair_a_high
                p50_sample = pair_b_high if pair_b_high >= pair_a_low else pair_a_low
            else:
                p95_sample = pair_b_high
                p50_sample = pair_a_high if pair_a_high >= pair_b_low else pair_b_low
            p50_ms = round(p50_sample / 1_000_000.0, 2)
            p95_ms = round(p95_sample / 1_000_000.0, 2)
            return {"p50_ms": p50_ms, "p95_ms": p95_ms, "count": 4}
        samples = list(samples_ns)
        samples.sort()

        p50_idx = min(count - 1, int(count * 0.50))
        p95_idx = min(count - 1, int(count * 0.95))
        p50_ms = round(samples[p50_idx] / 1_000_000.0, 2)
        p95_ms = round(samples[p95_idx] / 1_000_000.0, 2)
        return {"p50_ms": p50_ms, "p95_ms": p95_ms, "count": count}

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
            emit_by_type = dict(self._emit_by_type) if self._emit_by_type else {}
            return {
                "emit_total": self._emit_total,
                "latest_event_id": self._next_id,
                "gap_warnings_emitted": self._gap_warnings_emitted,
                "backpressure_discards": self._backpressure_discards,
                "subscriber_count": len(self._subscribers),
                "history_size": len(self._history),
                "heartbeat_total": self._heartbeat_total,
                "oversize_drops": self._oversize_drops,
                "emit_by_type": emit_by_type,
                "latency_ms": self._compute_latency_snapshot(),
                "schema_validate_mode": self._schema_validate_mode,
                "schema_violation_total": self._schema_violation_total,
            }


_sse_bus = _SSEBus()


def _on_task_status_change(
    task_id: str, old_status: str | None, new_status: str
) -> None:
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
        limiter: WebUiLimiterProtocol

    def _setup_task_routes(self) -> None:
        from ai_intervention_agent.web_ui import (
            _get_default_auto_resubmit_timeout_from_config,
            validate_auto_resubmit_timeout,
        )

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

            after_id_raw = (
                request.args.get("last_event_id")
                or request.headers.get("Last-Event-ID")
                or ""
            )
            after_id: int | None = None
            if after_id_raw:
                try:
                    after_id_value = int(str(after_id_raw).strip())

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
                            _sse_bus.bump_heartbeat()
                            hb_payload = _format_sse_heartbeat_payload()
                            yield f"event: heartbeat\ndata: {hb_payload}\n\n"
                            continue
                        if event is _SSE_DISCONNECT_SENTINEL:
                            return

                        serialized = (
                            event.get("_serialized")
                            if isinstance(event, dict)
                            else None
                        )
                        if serialized is None:
                            serialized = json.dumps(event["data"], ensure_ascii=False)

                        if isinstance(event, dict):
                            emit_ts_ns = event.get("_emit_ts_ns")
                            if isinstance(emit_ts_ns, int):
                                _sse_bus.record_emit_to_deliver_latency_ns(
                                    time.monotonic_ns() - emit_ts_ns
                                )

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
                            description: 任务唯一 ID (UUID v4 字符串, 由 task_queue.create_task 生成)
                          status:
                            type: string
                            enum: [pending, active, completed]
                            description: 任务状态 (pending=待处理, active=激活, completed=已完成)
                          prompt:
                            type: string
                            description: 提示文本（前 100 字符）
                          created_at:
                            type: string
                            format: date-time
                            description: 任务创建时间 (ISO 8601 字符串)
                          auto_resubmit_timeout:
                            type: number
                            description: 倒计时秒数, 0=禁用 (与 server_config.AUTO_RESUBMIT_TIMEOUT_MAX 对齐)
                          remaining_time:
                            type: number
                            description: 剩余倒计时秒数 (server_time + remaining_time = deadline)
                          deadline:
                            type: number
                            description: 截止时间戳 (server_time + remaining_time)
                          completed_at:
                            type: string
                            format: date-time
                            nullable: true
                            description: 完成时间 (任务未完成时为 null)
                          extends_used:
                            type: integer
                            description: 用户主动扩展倒计时次数 (>= extends_max 时按钮 disabled)
                          extends_max:
                            type: integer
                            description: 倒计时扩展次数上限 (来自 server_config)
                          feedback_placeholder:
                            type: string
                            nullable: true
                            description: 每任务可选 textarea placeholder, null = 走 i18n 默认值
                          question_type:
                            type: string
                            nullable: true
                            enum: [yesno]
                            description: 二元决策时为 "yesno", 否则保留默认 textarea 主体
                          header_label:
                            type: string
                            nullable: true
                            description: 短标签 chip (≤16 chars), 渲染在 task pane prompt 之上
                          loop_id:
                            type: string
                            nullable: true
                            description: Loop engineering P1 — 同一目标多轮任务共享的稳定 ID (≤64 chars, agent 自定义)
                          loop_objective:
                            type: string
                            nullable: true
                            description: loop 目标一句话描述 (≤500 chars, 首轮传入即可)
                          loop_phase:
                            type: string
                            nullable: true
                            description: 当前阶段 (investigate/implement/verify/review 等自由文本, ≤32 chars)
                          success_criteria:
                            type: string
                            nullable: true
                            description: 可验证的完成判据 (≤500 chars, 人审阅时的对照基准)
                          iteration_label:
                            type: string
                            nullable: true
                            description: 轮次标签 (如 iter-3 / attempt-2, ≤32 chars)
                    stats:
                      type: object
                      properties:
                        total:
                          type: integer
                          description: 任务总数
                        pending:
                          type: integer
                          description: 待处理任务数
                        active:
                          type: integer
                          description: 激活中任务数
                        completed:
                          type: integer
                          description: 已完成任务数
                    server_time:
                      type: number
                      description: 服务器当前时间 (Unix timestamp 秒), 客户端用于校准 remaining_time
              500:
                description: 服务器内部错误
                schema:
                  type: object
                  properties:
                    status:
                      type: string
                      enum: [error]
                      description: 固定为 "error"
                    message:
                      type: string
                      description: 服务器异常详情或通用提示
            """
            try:
                task_queue = get_task_queue()

                task_queue.cleanup_completed_tasks_throttled(
                    age_seconds=10, throttle_seconds=30.0
                )

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
                            "extends_used": task.extends_used,
                            "extends_max": COUNTDOWN_EXTENDS_MAX,
                            "feedback_placeholder": task.feedback_placeholder,
                            "question_type": task.question_type,
                            "header_label": task.header_label,
                            "loop_id": task.loop_id,
                            "loop_objective": task.loop_objective,
                            "loop_phase": task.loop_phase,
                            "success_criteria": task.success_criteria,
                            "iteration_label": task.iteration_label,
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

        @self.app.route("/api/loops", methods=["GET"])
        @self.limiter.limit("120 per minute")
        def get_loops() -> ResponseReturnValue:
            """获取按 loop_id 聚合的多轮任务视图（loop engineering P3）
            ---
            tags:
              - Tasks
            responses:
              200:
                description: loop 台账 + 各 loop 当前在队列中的活跃轮次
                schema:
                  type: object
                  properties:
                    success:
                      type: boolean
                    loops:
                      type: array
                      items:
                        type: object
                        properties:
                          loop_id:
                            type: string
                            description: 同一目标多轮任务共享的稳定 ID
                          objective:
                            type: string
                            nullable: true
                            description: loop 目标 (最后一个非空值胜出)
                          success_criteria:
                            type: string
                            nullable: true
                            description: 可验证的完成判据 (最后一个非空值胜出)
                          updated_at:
                            type: string
                            format: date-time
                            nullable: true
                            description: 最近一轮完成时间 (尚无完成轮次时为 null)
                          rounds:
                            type: array
                            description: 已完成轮次的压缩台账 (最多 50 轮, verdict 文本截断 200 字符, 图片只记数量)
                            items:
                              type: object
                              properties:
                                task_id:
                                  type: string
                                  description: 该轮任务 ID (任务本体可能已被清理)
                                iteration_label:
                                  type: string
                                  nullable: true
                                  description: 该轮轮次标签 (如 iter-3)
                                loop_phase:
                                  type: string
                                  nullable: true
                                  description: 该轮所处阶段 (如 verify)
                                header_label:
                                  type: string
                                  nullable: true
                                  description: 该轮任务的短标签 chip
                                completed_at:
                                  type: string
                                  format: date-time
                                  description: 该轮完成时间 (ISO 8601)
                                verdict:
                                  type: object
                                  description: 该轮人类裁决的压缩摘要
                                  properties:
                                    user_input:
                                      type: string
                                      description: 用户提交文本 (截断至 200 字符)
                                    selected_options:
                                      type: array
                                      description: 用户勾选的预定义选项
                                      items:
                                        type: string
                                    image_count:
                                      type: integer
                                      description: 附图数量 (不存 base64 本体)
                          live_tasks:
                            type: array
                            description: 仍在队列中的同 loop 任务 (轻量投影, 不含 prompt 全文)
                            items:
                              type: object
                              properties:
                                task_id:
                                  type: string
                                  description: 队列中任务的 ID
                                status:
                                  type: string
                                  enum: [pending, active, completed]
                                  description: 任务状态
                                iteration_label:
                                  type: string
                                  nullable: true
                                  description: 轮次标签 (如 iter-3)
                                loop_phase:
                                  type: string
                                  nullable: true
                                  description: 所处阶段 (如 implement)
                                header_label:
                                  type: string
                                  nullable: true
                                  description: 短标签 chip
                                created_at:
                                  type: string
                                  format: date-time
                                  description: 任务创建时间 (ISO 8601)
                    server_time:
                      type: number
                      description: 服务器当前时间 (Unix timestamp 秒)
              500:
                description: 服务器内部错误
                schema:
                  type: object
                  properties:
                    status:
                      type: string
                      enum: [error]
                      description: 固定为 "error"
                    message:
                      type: string
                      description: 服务器异常详情或通用提示
            """
            try:
                task_queue = get_task_queue()
                loops = task_queue.get_loops_snapshot()
                return jsonify(
                    {
                        "success": True,
                        "loops": loops,
                        "server_time": time.time(),
                    }
                )
            except Exception as e:
                logger.error(f"获取 loop 视图失败: {e}")
                return jsonify({"success": False, "error": str(e)}), 500

        # NOTE(feat-remove-download): web 右上角"下载任务"按钮已下线（见
        # ``templates/web_ui.html`` 中说明注释 + ``tests/test_feat_remove_download_button.py``）。
        # 此 endpoint 仍**保留**供以下非 UI 消费者继续调用：CI 烟测脚本、
        # 用户手动备份（``curl /api/tasks/export?format=markdown > backup.md``）、
        # 第三方监控集成。删除前请先 grep 项目外的 ``/api/tasks/export`` 引用。
        @self.app.route("/api/tasks/export", methods=["GET"])
        @self.limiter.limit("30 per minute")
        def export_tasks() -> ResponseReturnValue:
            """导出当前任务快照（JSON 或 Markdown）。
            ---
            tags:
              - Tasks
            parameters:
              - name: format
                in: query
                type: string
                enum: [json, markdown]
                default: json
                description: 导出格式
              - name: include_images
                in: query
                type: string
                enum: ["true", "false", "1", "0", "yes", "no"]
                default: "true"
                description: 是否在 result.images 字段保留 base64 图像 data
              - name: since
                in: query
                type: string
                format: date-time
                description: |
                  R135 增量导出过滤器——只导出 created_at 或 completed_at
                  晚于此 ISO 8601 时间戳的任务。缺失则全量导出（与 R125
                  行为一致）。例：since=2024-01-15T00:00:00Z 或
                  since=2024-01-15T08:00:00+00:00。
            responses:
              200:
                description: 任务快照文件（带 Content-Disposition 触发下载）
              400:
                description: 不支持的 format 参数 / since 不是合法 ISO 8601
                schema:
                  type: object
                  properties:
                    status:
                      type: string
                      enum: [error]
                      description: 固定为 "error"
                    message:
                      type: string
                      description: 参数校验失败的人类可读说明
              500:
                description: 服务器内部错误
                schema:
                  type: object
                  properties:
                    status:
                      type: string
                      enum: [error]
                      description: 固定为 "error"
                    message:
                      type: string
                      description: 服务器异常详情或通用提示
            """

            try:
                fmt = (request.args.get("format") or "json").lower().strip()
                if fmt not in ("json", "markdown"):
                    return (
                        jsonify(
                            {
                                "success": False,
                                "error": "unsupported_format",
                                "message": "format 必须是 json 或 markdown",
                            }
                        ),
                        400,
                    )

                include_images = _parse_bool_query(
                    request.args.get("include_images"), default=True
                )

                since_dt, since_err = _parse_since_iso(request.args.get("since"))
                if since_err is not None:
                    return (
                        jsonify(
                            {
                                "success": False,
                                "error": "invalid_since",
                                "message": since_err,
                            }
                        ),
                        400,
                    )

                task_queue = get_task_queue()
                tasks, stats = task_queue.get_all_tasks_with_stats()
                server_time = time.time()
                now_monotonic = time.monotonic()

                if since_dt is None:
                    tasks_iter = iter(tasks)
                else:
                    tasks_iter = (
                        task for task in tasks if _task_modified_since(task, since_dt)
                    )

                exported: list[dict[str, Any]] = []
                for task in tasks_iter:
                    remaining = task.get_remaining_time(now_monotonic=now_monotonic)
                    completed_at_iso = (
                        task.completed_at.isoformat() if task.completed_at else None
                    )
                    sanitized_result = _strip_images_from_result(
                        task.result, include_images
                    )
                    exported.append(
                        {
                            "task_id": task.task_id,
                            "status": task.status,
                            "prompt": task.prompt,
                            "predefined_options": task.predefined_options,
                            "predefined_options_defaults": (
                                task.predefined_options_defaults
                            ),
                            "auto_resubmit_timeout": task.auto_resubmit_timeout,
                            "remaining_time": remaining,
                            "deadline": server_time + remaining,
                            "extends_used": task.extends_used,
                            "extends_max": COUNTDOWN_EXTENDS_MAX,
                            "feedback_placeholder": task.feedback_placeholder,
                            "question_type": task.question_type,
                            "header_label": task.header_label,
                            "loop_id": task.loop_id,
                            "loop_objective": task.loop_objective,
                            "loop_phase": task.loop_phase,
                            "success_criteria": task.success_criteria,
                            "iteration_label": task.iteration_label,
                            "created_at": task.created_at.isoformat(),
                            "completed_at": completed_at_iso,
                            "result": sanitized_result,
                        }
                    )

                exported_at = _dt.now(UTC)
                exported_at_iso = exported_at.isoformat()
                stamp = exported_at.strftime("%Y%m%dT%H%M%SZ")
                base_name = f"ai-intervention-agent-tasks-{stamp}"

                if fmt == "json":
                    payload = {
                        "success": True,
                        "schema_version": 1,
                        "exported_at": exported_at_iso,
                        "server_time": server_time,
                        "stats": stats,
                        "include_images": include_images,
                        "since": since_dt.isoformat() if since_dt is not None else None,
                        "incremental": since_dt is not None,
                        "tasks": exported,
                    }
                    body = json.dumps(payload, ensure_ascii=False, indent=2)
                    response = Response(body, mimetype="application/json")
                    response.headers["Content-Disposition"] = (
                        f'attachment; filename="{base_name}.json"'
                    )
                    return response

                lines: list[str] = []
                lines.append("# AI Intervention Agent · Task Export")
                lines.append("")
                lines.append(f"- Exported at: `{exported_at_iso}`")
                lines.append(f"- Server time: `{server_time}`")
                if since_dt is not None:
                    lines.append(f"- Filtered since: `{since_dt.isoformat()}`")
                lines.append(
                    f"- Stats: total={stats.get('total', 0)} "
                    f"pending={stats.get('pending', 0)} "
                    f"active={stats.get('active', 0)} "
                    f"completed={stats.get('completed', 0)}"
                )
                lines.append("")
                lines.append("---")
                lines.append("")
                if not exported:
                    lines.append("_(No tasks in queue.)_")
                else:
                    for t in exported:
                        lines.append(f"## Task `{t['task_id']}` — `{t['status']}`")
                        lines.append("")
                        lines.append(f"- Created: `{t['created_at']}`")
                        if t["completed_at"]:
                            lines.append(f"- Completed: `{t['completed_at']}`")
                        lines.append(
                            f"- Remaining: `{t['remaining_time']}`s "
                            f"/ Deadline epoch `{t['deadline']}` "
                            f"/ Auto-resubmit `{t['auto_resubmit_timeout']}`s"
                        )
                        lines.append("")
                        lines.append("### Prompt")
                        lines.append("")

                        lines.append("````markdown")
                        lines.append(t["prompt"] or "")
                        lines.append("````")
                        lines.append("")
                        if t["predefined_options"]:
                            lines.append("### Predefined options")
                            lines.append("")
                            defaults = t["predefined_options_defaults"] or []
                            for idx, opt in enumerate(t["predefined_options"]):
                                checked = (
                                    bool(defaults[idx])
                                    if idx < len(defaults)
                                    else False
                                )
                                marker = "[x]" if checked else "[ ]"
                                lines.append(f"- {marker} {opt}")
                            lines.append("")
                        if t["result"]:
                            lines.append("### Result (feedback)")
                            lines.append("")
                            lines.append("````json")
                            lines.append(
                                json.dumps(t["result"], ensure_ascii=False, indent=2)
                            )
                            lines.append("````")
                            lines.append("")
                        lines.append("---")
                        lines.append("")

                body = "\n".join(lines).rstrip() + "\n"

                response = Response(body, mimetype="text/markdown; charset=utf-8")
                response.headers["Content-Disposition"] = (
                    f'attachment; filename="{base_name}.md"'
                )
                return response
            except Exception as e:
                logger.error(f"导出任务失败: {e}", exc_info=True)
                return (
                    jsonify({"success": False, "error": "服务器内部错误"}),
                    500,
                )

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
                      description: 新创建任务的唯一 ID
              400:
                description: 请求参数错误
                schema:
                  type: object
                  properties:
                    success:
                      type: boolean
                      enum: [false]
                      description: 固定为 false
                    error:
                      type: string
                      description: 错误分类码 (e.g., invalid_payload / invalid_field)
                    message:
                      type: string
                      description: 人类可读错误说明
              409:
                description: 任务 ID 重复或队列已满
                schema:
                  type: object
                  properties:
                    success:
                      type: boolean
                      enum: [false]
                      description: 固定为 false
                    error:
                      type: string
                      description: 冲突分类码 (e.g., duplicate_task_id / queue_full)
                    message:
                      type: string
                      description: 冲突原因说明 + 可能的解决建议
              500:
                description: 服务器内部错误
                schema:
                  type: object
                  properties:
                    success:
                      type: boolean
                      enum: [false]
                      description: 固定为 false
                    error:
                      type: string
                      description: 错误分类码
                    message:
                      type: string
                      description: 服务器异常详情或通用提示
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

            placeholder_raw = data.get("feedback_placeholder")
            feedback_placeholder: str | None = (
                placeholder_raw if isinstance(placeholder_raw, str) else None
            )

            qt_raw = data.get("question_type")
            question_type: str | None = qt_raw if isinstance(qt_raw, str) else None

            hl_raw = data.get("header_label")
            header_label: str | None = hl_raw if isinstance(hl_raw, str) else None

            loop_fields: dict[str, str | None] = {}
            for loop_key in (
                "loop_id",
                "loop_objective",
                "loop_phase",
                "success_criteria",
                "iteration_label",
            ):
                loop_raw = data.get(loop_key)
                loop_fields[loop_key] = loop_raw if isinstance(loop_raw, str) else None

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
                    auto_resubmit_timeout_explicit=timeout_explicit,
                    feedback_placeholder=feedback_placeholder,
                    question_type=question_type,
                    header_label=header_label,
                    loop_id=loop_fields["loop_id"],
                    loop_objective=loop_fields["loop_objective"],
                    loop_phase=loop_fields["loop_phase"],
                    success_criteria=loop_fields["success_criteria"],
                    iteration_label=loop_fields["iteration_label"],
                )
            except Exception as e:
                logger.error(f"创建任务失败: {e}", exc_info=True)
                return jsonify({"success": False, "error": "服务器内部错误"}), 500

            if success:
                logger.info(f"任务已通过API添加到队列: {task_id}")

                resp: dict[str, object] = {"success": True, "task_id": task_id}
                if (
                    isinstance(feedback_placeholder, str)
                    and len(feedback_placeholder.strip()) > PLACEHOLDER_MAX_LENGTH
                ):
                    resp["placeholder_truncated"] = True
                    resp["placeholder_original_length"] = len(
                        feedback_placeholder.strip()
                    )
                    resp["placeholder_max_length"] = PLACEHOLDER_MAX_LENGTH
                return jsonify(resp)

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
                      description: 服务器当前时间 (Unix timestamp 秒), 客户端用于校准 remaining_time
                    task:
                      type: object
                      properties:
                        task_id:
                          type: string
                          description: 任务唯一 ID
                        prompt:
                          type: string
                          description: 提示文本 (完整内容, 不截断)
                        status:
                          type: string
                          enum: [pending, active, completed]
                          description: 任务状态 (pending/active/completed)
                        predefined_options:
                          type: array
                          items:
                            type: string
                          description: 预定义选项列表 (供前端渲染 chip 按钮)
                        predefined_options_defaults:
                          type: array
                          items:
                            type: boolean
                          description: 与 predefined_options 一一对应的默认选中状态
                        created_at:
                          type: string
                          format: date-time
                          description: 任务创建时间 (ISO 8601)
                        auto_resubmit_timeout:
                          type: number
                          description: 倒计时秒数, 0=禁用
                        remaining_time:
                          type: number
                          description: 剩余倒计时秒数
                        deadline:
                          type: number
                          description: 截止时间戳 (server_time + remaining_time)
                        result:
                          type: object
                          description: 反馈结果 (任务未完成时为空对象, 完成后含 user_input/selected_options/images)
              404:
                description: 任务不存在
                schema:
                  type: object
                  properties:
                    status:
                      type: string
                      enum: [error]
                      description: 固定为 "error"
                    message:
                      type: string
                      description: 错误说明文本（如 `Task not found`）
              500:
                description: 服务器内部错误
                schema:
                  type: object
                  properties:
                    status:
                      type: string
                      enum: [error]
                      description: 固定为 "error"
                    message:
                      type: string
                      description: 服务器异常详情或通用提示
            """
            try:
                task_queue = get_task_queue()

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
                            "feedback_placeholder": task.feedback_placeholder,
                            "question_type": task.question_type,
                            "header_label": task.header_label,
                            "loop_id": task.loop_id,
                            "loop_objective": task.loop_objective,
                            "loop_phase": task.loop_phase,
                            "success_criteria": task.success_criteria,
                            "iteration_label": task.iteration_label,
                        },
                    }
                )
            except Exception as e:
                logger.error(f"获取任务失败: {e}", exc_info=True)
                return jsonify({"success": False, "error": "服务器内部错误"}), 500

        @self.app.route("/api/tasks/<task_id>/extend", methods=["POST"])
        @self.limiter.limit("10 per minute")
        def extend_task_deadline(task_id: str) -> ResponseReturnValue:
            """feat-countdown-extend (§3.2): 用户主动延长 task 的
            auto-resubmit 倒计时。
            ---
            tags:
              - Tasks
            parameters:
              - name: task_id
                in: path
                type: string
                required: true
              - name: body
                in: body
                required: false
                schema:
                  type: object
                  properties:
                    seconds:
                      type: integer
                      description: |
                        要延长的秒数；缺省走 COUNTDOWN_EXTEND_DEFAULT_SECONDS
                        (60)。范围 [10, 300]。
                      example: 60
            responses:
              200:
                description: 延长成功（task_updated 事件已通过 SSE 广播）
                schema:
                  type: object
                  properties:
                    success:
                      type: boolean
                    extends_used:
                      type: integer
                    extends_max:
                      type: integer
                    new_remaining_time:
                      type: integer
                    new_auto_resubmit_timeout:
                      type: integer
              400:
                description: |
                  请求体无效（seconds 超出 [10, 300] / JSON 解析失败 /
                  task 已完成 / task 禁用了 auto-resubmit）
                schema:
                  type: object
                  properties:
                    success:
                      type: boolean
                      description: 固定为 false
                    error:
                      type: string
                      description: 错误说明文本
                    code:
                      type: string
                      description: |
                        机器可读错误码（如 `invalid_seconds`,
                        `task_completed`, `auto_resubmit_disabled`）
              404:
                description: task 不存在
                schema:
                  type: object
                  properties:
                    success:
                      type: boolean
                      description: 固定为 false
                    error:
                      type: string
                      description: 错误说明文本（如 `task not found`）
              422:
                description: |
                  延长上限已达（extends_used >= COUNTDOWN_EXTENDS_MAX）。
                  前端按钮应根据 ``extends_used`` 字段提前 disabled，正常
                  路径不会走到 422，但保留作为防御性校验。
                schema:
                  type: object
                  properties:
                    success:
                      type: boolean
                      description: 固定为 false
                    error:
                      type: string
                      description: 错误说明文本
                    code:
                      type: string
                      description: 固定为 `extends_exhausted`
                    extends_used:
                      type: integer
                      description: 已使用的延长次数（用于前端展示）
                    extends_max:
                      type: integer
                      description: 最大允许延长次数
              500:
                description: 服务器内部错误
                schema:
                  type: object
                  properties:
                    success:
                      type: boolean
                      description: 固定为 false
                    error:
                      type: string
                      description: 错误说明文本
            """
            try:
                task_queue = get_task_queue()

                payload = request.get_json(silent=True) or {}
                requested_seconds = payload.get(
                    "seconds", COUNTDOWN_EXTEND_DEFAULT_SECONDS
                )
                if not isinstance(requested_seconds, int) or isinstance(
                    requested_seconds, bool
                ):
                    return jsonify(
                        {
                            "success": False,
                            "error": "seconds 必须是整数",
                            "code": "invalid_seconds",
                        }
                    ), 400

                success, error_code, extends_used, new_timeout = (
                    task_queue.extend_task_deadline(
                        task_id,
                        requested_seconds,
                        max_extends=COUNTDOWN_EXTENDS_MAX,
                        min_seconds=COUNTDOWN_EXTEND_SECONDS_MIN,
                        max_seconds=COUNTDOWN_EXTEND_SECONDS_MAX,
                    )
                )
                if error_code == "task_not_found":
                    return jsonify({"success": False, "error": "任务不存在"}), 404
                if not success:
                    status_code = 422 if error_code == "extends_limit_reached" else 400
                    return jsonify(
                        {
                            "success": False,
                            "error": error_code,
                            "code": error_code,
                            "extends_used": extends_used,
                            "extends_max": COUNTDOWN_EXTENDS_MAX,
                        }
                    ), status_code

                task = task_queue.get_task(task_id)
                now_monotonic = time.monotonic()
                new_remaining = (
                    task.get_remaining_time(now_monotonic=now_monotonic)
                    if task is not None
                    else max(0, int(new_timeout))
                )
                logger.info(
                    f"task_id={task_id} 倒计时延长 +{requested_seconds}s "
                    f"(extends_used={extends_used}/{COUNTDOWN_EXTENDS_MAX})"
                )
                return jsonify(
                    {
                        "success": True,
                        "extends_used": extends_used,
                        "extends_max": COUNTDOWN_EXTENDS_MAX,
                        "new_remaining_time": new_remaining,
                        "new_auto_resubmit_timeout": new_timeout,
                    }
                )
            except Exception as e:
                logger.error(f"延长任务倒计时失败: {e}", exc_info=True)
                return jsonify({"success": False, "error": "服务器内部错误"}), 500

        @self.app.route("/api/tasks/<task_id>/freeze", methods=["POST"])
        @self.limiter.limit("10 per minute")
        def freeze_task_deadline(task_id: str) -> ResponseReturnValue:
            """mining-6 Track A (cycle-5 §3.6 derivative): 用户主动把指定 task
            的 auto-resubmit 倒计时永久禁用，让 task 进入"等用户回答"状态。
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
                description: 冻结成功（task.auto_resubmit_timeout 已置 0）
                schema:
                  type: object
                  properties:
                    success:
                      type: boolean
                    new_auto_resubmit_timeout:
                      type: integer
                      description: 冻结后必为 0
              400:
                description: task 已完成（无需冻结）
                schema:
                  type: object
                  properties:
                    success:
                      type: boolean
                      description: 固定为 false
                    error:
                      type: string
                      description: 错误说明文本（task_completed 类）
                    code:
                      type: string
                      description: 错误码（如 `task_completed`）
              404:
                description: task 不存在
                schema:
                  type: object
                  properties:
                    success:
                      type: boolean
                      description: 固定为 false
                    error:
                      type: string
                      description: 错误说明文本（如 `任务不存在`）
              409:
                description: |
                  task 已经被冻结过（``already_frozen`` 错误码,
                  ``auto_resubmit_timeout`` 已 <= 0）。这是 **idempotent No-Op**:
                  第二次 freeze 不破坏状态, 仅返回 409 让前端知道按钮无需再点。
                schema:
                  type: object
                  properties:
                    success:
                      type: boolean
                      description: 固定为 false
                    error:
                      type: string
                      description: 错误说明文本
                    code:
                      type: string
                      description: 固定为 `already_frozen`
              500:
                description: 服务器内部错误
                schema:
                  type: object
                  properties:
                    success:
                      type: boolean
                      description: 固定为 false
                    error:
                      type: string
                      description: 错误说明文本
            """
            try:
                task_queue = get_task_queue()
                success, error_code, new_timeout = task_queue.freeze_task_deadline(
                    task_id
                )
                if error_code == "task_not_found":
                    return jsonify({"success": False, "error": "任务不存在"}), 404
                if not success:
                    status_code = 409 if error_code == "already_frozen" else 400
                    return jsonify(
                        {
                            "success": False,
                            "error": error_code,
                            "code": error_code,
                            "new_auto_resubmit_timeout": new_timeout,
                        }
                    ), status_code
                logger.info(f"task_id={task_id} 倒计时已冻结（auto_resubmit 禁用）")
                return jsonify(
                    {
                        "success": True,
                        "new_auto_resubmit_timeout": new_timeout,
                    }
                )
            except Exception as e:
                logger.error(f"冻结任务倒计时失败: {e}", exc_info=True)
                return jsonify({"success": False, "error": "服务器内部错误"}), 500

        @self.app.route("/api/tasks/<task_id>/activate", methods=["POST"])
        @self.limiter.limit("60 per minute")
        def activate_task(task_id: str) -> ResponseReturnValue:
            """激活指定任务

            **幂等性 (idempotent)**: 已经是 active 状态的 task 再次 activate
            会返回 success=True (P6R-2 修复, 防 multi-tab 同时点同一 task
            造成 race condition / UX 错觉)。底层 ``set_active_task`` 在
            ``new_task.status == ACTIVE`` 时短路返回 True, 不切换任何状态。
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

            R165 反馈丢失防御要点（详见 ``server_feedback.py`` 的
            ``wait_for_task_completion`` docstring）：

            - COMPLETED 状态的任务在此端点 short-circuit，不真正 remove，
              避免 MCP retry-before-close race 把带 user feedback 的 task
              误删。COMPLETED 是终态，等同已关闭语义。
            - 仅 ACTIVE / PENDING 任务真正走 ``remove_task``（兼容
              R13·B1 ghost-task cleanup）。
            - 响应包含 ``skipped``/``reason`` 字段标识 short-circuit 行为。
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
                description: 任务已关闭（COMPLETED 任务会 short-circuit 跳过删除）
                schema:
                  type: object
                  properties:
                    success:
                      type: boolean
                    skipped:
                      type: boolean
                      description: True 表示因任务已 COMPLETED 而跳过删除
                    reason:
                      type: string
                      description: 当 skipped 为 True 时给出原因（如 task_completed）
              404:
                description: 任务不存在
              500:
                description: 服务器内部错误
            """
            try:
                task_queue = get_task_queue()

                existing = task_queue.get_task(task_id)
                if existing is None:
                    return jsonify({"success": False, "error": "任务不存在"}), 404

                if existing.status == "completed":
                    logger.info(
                        f"任务 {task_id} 已 COMPLETED，跳过 close 删除"
                        "（保留 result 以避免反馈丢失，后台清理线程会自动回收）"
                    )
                    return jsonify(
                        {
                            "success": True,
                            "skipped": True,
                            "reason": "task_completed",
                        }
                    )

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

                _ua = (request.headers.get("User-Agent") or "")[:80]
                _referer = (request.headers.get("Referer") or "")[:80]
                _preview = feedback_text[:60].replace("\n", "\\n")
                logger.info(
                    f"任务 {task_id} 反馈已提交 | opts={len(selected_options)} "
                    f'imgs={len(images)} text[:60]="{_preview}" '
                    f'ua="{_ua}" referer="{_referer}"'
                )
                return jsonify({"success": True, "message": msg("feedback.submitted")})
            except Exception as e:
                logger.error(f"提交任务失败: {e}", exc_info=True)
                return jsonify({"success": False, "error": "服务器内部错误"}), 500
