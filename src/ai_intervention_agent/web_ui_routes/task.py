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

# R205 / F-204-1: SSE schema runtime validation API. ``validate_payload``
# 由 R198 已暴露但 production hot path 不调用——本 cycle 把它装在
# ``_SSEBus.emit`` 入口由环境变量开关启用。
from ai_intervention_agent.sse_event_schemas import validate_payload

# R20.8: 直接 import task_queue_singleton 避免拖入 fastmcp/mcp（详见模块注释）。
from ai_intervention_agent.task_queue_singleton import get_task_queue
from ai_intervention_agent.web_ui_routes._upload_helpers import extract_uploaded_images

if TYPE_CHECKING:
    from flask import Flask
    from flask_limiter import Limiter

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

# feat-countdown-extend (§3.2)：用户主动 +60s 扩展倒计时的相关配置。
# 这些常量同时被 ``POST /api/tasks/<task_id>/extend`` 路由 + ``GET
# /api/tasks`` 路由（``extends_max`` 字段）+ ``GET /api/tasks/export``
# 路由共同使用。
#
# 安全保护理由（为什么不让用户无限延长）：
#   - ``COUNTDOWN_EXTENDS_MAX = 3``：每个 task 最多 3 次扩展，避免用户
#     绕开 auto-resubmit 自动恢复机制把任务永久挂着；
#   - ``COUNTDOWN_EXTEND_SECONDS_MIN/MAX = [10, 300]``：单次扩展 [10,
#     300] 秒，避免 "+1s spam" 或 "+3600s 一次性架空"；
#   - ``COUNTDOWN_EXTEND_DEFAULT_SECONDS = 60``：前端默认按钮 +60s，
#     与同类产品惯例（GitHub PR review reminder、Slack snooze）对齐。
#
# 配置位置取舍：暂时硬编码模块级常量。未来若需要让 ops 不重启地调，
# 可以迁到 ``server_config.toml`` 的 ``[feedback]`` 段，但当前 3 个
# 数字稳定性高、用户无需自定义 → 硬编码降低配置复杂度。
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
    # R205 / Cycle 9 · F-204-1: schema validation toggle 状态。``mode``
    # ∈ {off, warn, strict}; ``total`` 单调累加 emit() 检测到的违规次数
    # (一条 emit 多个字段错也只算 1 次)。
    schema_validate_mode: str
    schema_violation_total: int


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


# R125c — 后端 export ``?include_images=...`` 解析工具。
# truthy / falsy 同时接受常见英文 / 数值 / yes/no 形式（保持与
# ``configparser`` BOOLEAN_STATES + Flask 生态社区惯例一致）；
# 任何不在表里的字符串退回 ``default``，让用户拼错 (e.g.
# ``include_images=truee``) 时不会触发 500，体感符合 query 参数的
# best-effort 习惯。
_TRUTHY_QUERY: frozenset[str] = frozenset({"true", "1", "yes", "on"})
_FALSY_QUERY: frozenset[str] = frozenset({"false", "0", "no", "off"})


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
    # ``Z`` ↔ ``+00:00`` 兼容兜底（Python 3.10 兼容；3.11+ fromisoformat
    # 已原生支持，但替换无害）
    if norm.endswith("Z"):
        norm = norm[:-1] + "+00:00"
    try:
        parsed = _dt.fromisoformat(norm)
    except ValueError:
        return None, "since 必须是 ISO 8601 时间戳（如 2024-01-15T00:00:00Z）"
    if parsed.tzinfo is None:
        # naive → 按 UTC 处理（与 Task.created_at 都 UTC-aware 一致）
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
            stripped_images.append(img)  # 异常体保持透传
            continue
        meta = {k: v for k, v in img.items() if k != "data"}
        stripped_images.append(meta)
    sanitized: dict[str, Any] = dict(result)
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

    # R134：emit→deliver 延迟样本环形缓冲区长度。
    # - 单元 = 1 个 int（ns），CPython int 体积 ~28B，512 个 ≈ 14KB / 实例，
    #   不足以构成内存压力（与 _HISTORY_MAXLEN=128 的 ~32KB 同数量级）。
    # - 512 给 P95 留 25 个样本（512 × 5% ≈ 25），足以让分布在毫秒抖动下
    #   稳定到 ±1ms 量级；P50 留 256 个样本，统计噪声远低于真实延迟波动。
    # - 每条 SSE deliver 1 个样本；100 个连接 × 10 events/s = 1000 samples/s
    #   场景下，512 条样本相当于 0.5 秒滑动窗口，对运维「现在的延迟」体感
    #   最准——比 1024 / 2048 那种"几秒 ago 的均值"对告警决策更直接。
    # - 排序成本：512 个 int 排序 ~50µs（CPython timsort），sse-stats 端点
    #   60/min 调用，总成本 ≤ 50µs × 1/s = 0.005% CPU，可忽略。
    _LATENCY_SAMPLES_MAXLEN: int = 512
    # R203 / Cycle 9 · F-202-1（CR#21 §4.2）防御性常量：
    # ``_emit_by_type`` 是 ``Counter[str]``，理论上 key 数没上限。如果
    # 上游 emit 把动态字符串当 event_type（已被 R198 AST guard 卡死，但
    # ``oversize_drop`` 替换路径 + 未来误用是真实 attack/bug surface），
    # Counter 会无限增长 → ``stats_snapshot()["emit_by_type"]`` 越来越大
    # → Prometheus ``aiia_sse_emit_by_type_total`` exposition payload 拖
    # 慢 scrape + Grafana cardinality 爆炸。
    #
    # cap 触发后：
    # 1. 未见过的新 ``event_type`` **不**新增 key；
    # 2. 这条 emit 转记到 ``__other__`` 桶（保 R202 不变量
    #    ``sum(by_type) == emit_total``）；
    # 3. 全进程只 WARN 一次（``_emit_by_type_cap_hit_warned`` flag），避
    #    免日志风暴；
    # 4. 旧 ``event_type`` 计数照常累加，不受影响。
    #
    # 100 是 R198 4 个 schema event + ~10 倍未来扩展余量 + ~10 倍
    # ``oversize_drop`` 替换路径下可能 emit 的特殊 type 余量；对应
    # exposition payload ~100 × 100 bytes ≈ 10 KB，远小于 Prometheus
    # 默认 100 KB/scrape 配额。
    _EMIT_BY_TYPE_MAX_CARDINALITY: int = 100
    _EMIT_BY_TYPE_OVERFLOW_BUCKET: str = "__other__"

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
        # R203 / Cycle 9 · F-202-1：cap 命中后 WARN-once flag，避免日志
        # 风暴。同样走 ``self._lock`` 保护（emit 持锁时读写）。
        self._emit_by_type_cap_hit_warned: bool = False
        # R205 / Cycle 9 · F-204-1: SSE schema validation toggle 状态。
        # 读 env var 一次, sticky 到 instance lifetime; 无效值 → off + WARN。
        # ``_schema_violation_total`` 累计 emit() 检测到的 schema violation
        # 次数 (一条 emit 多个字段错也只算 1 次), 走 ``self._lock`` 保护
        # 与 ``_emit_total`` 同款。
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
            # 启动时 log 一次告诉运维 "schema validation 已开启", 方便审计 +
            # 防止 silently 啃 emit 性能而无人知晓。
            logger.info(
                "R205: SSE schema validation enabled at mode=%r via %s. "
                "Violations will be logged at level=%s; counter exposed as "
                "stats_snapshot()['schema_violation_total'].",
                self._schema_validate_mode,
                _SSE_SCHEMA_VALIDATE_ENV_VAR,
                "ERROR" if self._schema_validate_mode == "strict" else "WARNING",
            )
        # R134：emit→deliver 延迟样本环形缓冲。emit 时把 ``time.monotonic_ns()``
        # 写进 payload 的 ``_emit_ts_ns``；generator 真正 yield 给客户端那
        # 一瞬间再算 ``time.monotonic_ns() - _emit_ts_ns`` 推进缓冲。
        # 单位 ns（int），算 P50/P95 时除 1e6 输出 ms（float 2 位小数）。
        # 用 ``deque(maxlen=...)`` 自带 O(1) FIFO evict；追加 + 读取都过
        # ``self._lock``。
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
        #
        # R205 / Cycle 9 · F-204-1: 可选 schema validation。放在 emit 入口
        # 最早期 (serialize / oversize 替换之前), 验证 caller 真实传入的
        # event_type + payload, 不被 bus 内部替换路径污染。off mode 是
        # 单 attribute compare, 0 开销; warn/strict mode 调 validate_payload
        # (μs 级 dict 字段检查) + 失败 log + 计数, 但 emit 仍照常 fanout
        # (不 raise——见 module-level _SSE_SCHEMA_VALIDATE_* 注释)。
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

        # R134：emit 时间戳。``time.monotonic_ns()`` 不受系统时钟跳变影响，
        # 是 emit→deliver 延迟测量的正确时基（``time.time()`` 在 NTP 校
        # 时回拨时会算出负 latency）。在 ``_lock`` 之外取，避免持锁等待
        # 让本身要测的延迟变长。
        emit_ts_ns = time.monotonic_ns()

        with self._lock:
            self._next_id += 1
            self._emit_total += 1
            # R61：按 event_type 分桶累加。``oversize_drop`` 替换路径会用替换
            # 后的 type（``"oversize_drop"`` 而非原 ``"task_changed"``），这正
            # 是我们想看到的——dashboard 能直接观测到"这一桶 oversize 事件
            # 实际上来自哪个上游 type"，因为替换后的 ``data["original_event_type"]``
            # 仍然保留了原 type 名。
            if (
                event_type not in self._emit_by_type
                and len(self._emit_by_type) >= self._EMIT_BY_TYPE_MAX_CARDINALITY
            ):
                # R203 cap-hit 路径：未见过的新 event_type 落到 overflow
                # 桶，保 sum 不变量；只 WARN 一次。
                if not self._emit_by_type_cap_hit_warned:
                    logger.warning(
                        "R203: SSE _emit_by_type cap (%d distinct event_type) "
                        "hit; further new event_type emits will be accumulated "
                        "under %r bucket. First overflow event_type: %r. "
                        "Consider raising _EMIT_BY_TYPE_MAX_CARDINALITY or "
                        "auditing emit-site code for runaway dynamic "
                        "event_type strings.",
                        self._EMIT_BY_TYPE_MAX_CARDINALITY,
                        self._EMIT_BY_TYPE_OVERFLOW_BUCKET,
                        event_type,
                    )
                    self._emit_by_type_cap_hit_warned = True
                self._emit_by_type[self._EMIT_BY_TYPE_OVERFLOW_BUCKET] += 1
            else:
                self._emit_by_type[event_type] += 1
            event_id = self._next_id
            payload = {
                "id": event_id,
                "type": event_type,
                "data": data or {},
                "_serialized": serialized_data,
                # R134：generator yield 之前算 monotonic_ns - _emit_ts_ns。
                # 字段名带下划线，与 ``_serialized`` 同一约定：
                # 内部 metadata，不应序列化给客户端，由 generator 消费。
                "_emit_ts_ns": emit_ts_ns,
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

        必须在持 ``self._lock`` 时调用，因为内部读 ``_latency_samples_ns``
        快照是 ``list(self._latency_samples_ns)``——deque 在多线程并发
        ``append`` 时遍历会抛 ``RuntimeError: deque mutated during iteration``。
        - 算法：nearest-rank percentile（``sorted[int(N * pct)]``，pct ∈
          [0,1)）。N=512 时 P95 索引 = 486，P50 = 256；nearest-rank 比
          线性插值简单稳定，监控用 ±1ms 精度足够。
        - count = 0 时 p50/p95 全 None；count == 1 时 p50 = p95 = 唯一
          样本。
        """
        samples = list(self._latency_samples_ns)
        count = len(samples)
        if count == 0:
            return {"p50_ms": None, "p95_ms": None, "count": 0}
        samples.sort()
        # nearest-rank with cap 防止 index == count（pct=1.0 时会越界）
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
                # R134：emit→deliver 延迟分布。``_compute_latency_snapshot``
                # 在锁内读 ``_latency_samples_ns``，输出 ms 单位。
                "latency_ms": self._compute_latency_snapshot(),
                # R205 / Cycle 9 · F-204-1: SSE schema validation 状态 +
                # 累计 violation 计数。``schema_validate_mode`` ∈ {off, warn,
                # strict}, sticky 到进程 lifetime; ``schema_violation_total``
                # 单调累加, 一条 emit 多个字段错也只算 1 次（emit() 入口在
                # validate 失败 case 下 += 1 一次）。
                "schema_validate_mode": self._schema_validate_mode,
                "schema_violation_total": self._schema_violation_total,
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
        from ai_intervention_agent.web_ui import (
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
                        # R134：emit→deliver 延迟采样。``_emit_ts_ns`` 由 emit
                        # 写入 payload；缺失（gap_warning 由 subscribe 直接塞入
                        # queue 不走 emit）则跳过——只测真实的 emit→deliver 路径。
                        # ``time.monotonic_ns`` 单调递增，差值永远 ≥ 0；
                        # ``record_emit_to_deliver_latency_ns`` 自带负数防御。
                        if isinstance(event, dict):
                            emit_ts_ns = event.get("_emit_ts_ns")
                            if isinstance(emit_ts_ns, int):
                                _sse_bus.record_emit_to_deliver_latency_ns(
                                    time.monotonic_ns() - emit_ts_ns
                                )
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
                            # feat-countdown-extend (§3.2)：前端用
                            # ``extends_used`` 计算 +60s 按钮是否还可点击
                            # （>= extends_max 时按钮 disabled），用
                            # ``extends_max`` 显示"剩余 N 次"提示。
                            "extends_used": task.extends_used,
                            "extends_max": COUNTDOWN_EXTENDS_MAX,
                            # mining-cycle-3 §2.1 borrow #3: per-task placeholder
                            "feedback_placeholder": task.feedback_placeholder,
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
              500:
                description: 服务器内部错误
            """
            # R125 实现说明：
            # - 输出 ``Content-Disposition: attachment`` 触发浏览器下载，避免
            #   inline 渲染干扰快照真实性；
            # - 文件名形如 ``ai-intervention-agent-tasks-{ISO8601}.{ext}``，
            #   让用户机器上的导出文件可按时间排序，避免覆盖；
            # - JSON 模式给完整字段（prompt 全文 + 选项 + result + 时间戳），
            #   Markdown 模式按"会话日志"排版供人类阅读；
            # - 纯读快照；与 ``/api/tasks`` 共用 ``get_all_tasks_with_stats``
            #   一次读锁原子快照，避免与 SSE 事件流出现"半态导出"。
            #
            # 隐私 / 安全边界：
            # - JSON 含 ``result.images``（base64）；项目默认 loopback 绑定，
            #   不暴露公网；
            # - 限速 30/min（与 ``update_feedback_config`` 同档），保留人为
            #   批量备份能力但拒绝爬虫式抓取。
            #
            # docstring 注意事项：以上"实现说明"/"隐私边界"段必须留在 docstring
            # 之外（用普通 ``#`` 注释），因为 ``flasgger`` 把整个 docstring 当
            # YAML 解析，散文里的 ``Content-Disposition: attachment`` /
            # ``- ...：`` 等会被识别成非法的 mapping key 触发 ``ScannerError``。
            # 由 ``test_enabled_apispec_returns_json`` 锁定该不变量。
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

                # R125c: ?include_images={true,false,1,0,yes,no} 控制是否在
                # ``result.images`` 字段保留 base64 ``data`` 体。背景：单张
                # 图片 base64 化后约 1.33x 原字节，多个 task 各带几张图常导
                # 致 JSON 导出膨胀到几 MB。``include_images=false`` 时仅保
                # 留每张图的 ``filename / size / content_type / mime_type``
                # 元数据 + 顶层 ``images_stripped: true`` 标记，让"轻量
                # 备份 / pure 文本同步"场景下载量降到 KB 级。默认 ``true``
                # 与 R125 一致，向后兼容既有 curl 用户。
                include_images = _parse_bool_query(
                    request.args.get("include_images"), default=True
                )

                # R135: ?since=<ISO> 增量导出过滤器。CI / 备份脚本周期性
                # 拉 ``/api/tasks/export`` 时，绝大多数任务自上次同步后
                # 没变化——全量传输是 O(N×content) 浪费。``since`` 把过
                # 滤交给服务端，downstream 只拿真正动过的 tasks，传输量
                # 落到 O(M×content)（M ≤ N）。
                # 非法 ISO 直接 400，与 ``unsupported_format`` 同款返回
                # 结构（``error: invalid_since``）。``since`` 缺失或空字
                # 符串走全量路径，与 R125 行为一致，向后兼容既有调用方。
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

                if since_dt is not None:
                    tasks = [t for t in tasks if _task_modified_since(t, since_dt)]

                exported: list[dict[str, Any]] = []
                for task in tasks:
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
                            # feat-countdown-extend (§3.2)：export 也包含
                            # ``extends_used`` 字段便于 audit / backup
                            # 还原后保留扩展次数。
                            "extends_used": task.extends_used,
                            "extends_max": COUNTDOWN_EXTENDS_MAX,
                            # mining-cycle-3 §2.1 borrow #3: per-task placeholder
                            "feedback_placeholder": task.feedback_placeholder,
                            "created_at": task.created_at.isoformat(),
                            "completed_at": completed_at_iso,
                            "result": sanitized_result,
                        }
                    )

                # ISO8601 时间戳作为文件名时间分量。冒号在 Windows 文件名里
                # 非法，所以用 ``%Y%m%dT%H%M%SZ`` 紧凑格式（只含数字 + T/Z）。
                stamp = _dt.now(UTC).strftime("%Y%m%dT%H%M%SZ")
                base_name = f"ai-intervention-agent-tasks-{stamp}"

                if fmt == "json":
                    payload = {
                        "success": True,
                        "schema_version": 1,
                        "exported_at": _dt.now(UTC).isoformat(),
                        "server_time": server_time,
                        "stats": stats,
                        "include_images": include_images,
                        # R135: 增量导出元数据。``since`` 字段直接 echo
                        # 用户传入的 ISO 字符串（解析后）；``incremental``
                        # 是 bool 让消费方一眼分辨「全量导出」vs「自上次
                        # 同步以来的变更集」，避免误把增量当全量回放。
                        # ``stats`` 仍为全局 stats（不局部化到过滤后的
                        # tasks）：监控 dashboard 关心整体队列健康度，
                        # 局部化反而误导。
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

                # Markdown: human-friendly transcript
                lines: list[str] = []
                lines.append("# AI Intervention Agent · Task Export")
                lines.append("")
                lines.append(f"- Exported at: `{_dt.now(UTC).isoformat()}`")
                lines.append(f"- Server time: `{server_time}`")
                if since_dt is not None:
                    # R135: 增量导出标记，让人类读快照时知道这是「自 X 以来
                    # 变化的子集」而不是全量
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
                        # 防止 prompt 内含 ``` 破坏栅栏；在 4 个反引号外层包裹
                        # 是 GitHub Flavored Markdown 习惯做法。
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
                # text/markdown 浏览器多数会渲染或下载；强制 attachment 让
                # 用户体验"另存为"而非内联渲染（防止 URL 渲染干扰快照真实性）。
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
            # mining-cycle-3 §2.1 borrow #3 (gemini-cli placeholder)：
            # 接受可选的 ``feedback_placeholder`` per-task 提示。
            # 类型校验宽松：非 str 静默丢弃（与 ``project_directory`` 等
            # compat-only 字段同等待遇）；server-side clamp 在
            # ``task_queue.add_task`` 中做。
            placeholder_raw = data.get("feedback_placeholder")
            feedback_placeholder: str | None = (
                placeholder_raw if isinstance(placeholder_raw, str) else None
            )

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
                    feedback_placeholder=feedback_placeholder,
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
                            # mining-cycle-3 §2.1 borrow #3: per-task placeholder
                            "feedback_placeholder": task.feedback_placeholder,
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
              404:
                description: task 不存在
              422:
                description: |
                  延长上限已达（extends_used >= COUNTDOWN_EXTENDS_MAX）。
                  前端按钮应根据 ``extends_used`` 字段提前 disabled，正常
                  路径不会走到 422，但保留作为防御性校验。
              500:
                description: 服务器内部错误
            """
            try:
                task_queue = get_task_queue()

                # 请求体：seconds 可选，缺省 60。
                # request.get_json(silent=True) 在空 body / 错误 JSON 时返回 None
                # 而不是抛 400，让我们走自定义的 400 / 默认值路径。
                payload = request.get_json(silent=True) or {}
                requested_seconds = payload.get(
                    "seconds", COUNTDOWN_EXTEND_DEFAULT_SECONDS
                )
                if not isinstance(requested_seconds, int) or isinstance(
                    requested_seconds, bool
                ):
                    # bool 是 int 的子类，必须显式排除（True == 1 会通过 int 检查）
                    return jsonify(
                        {
                            "success": False,
                            "error": "seconds 必须是整数",
                            "code": "invalid_seconds",
                        }
                    ), 400

                # cr32 §3.1 fix [medium]：走 ``TaskQueue.extend_task_deadline``
                # facade 而不是直接 ``task.extend_deadline``，让 read-modify-write
                # 在写锁内串行化。否则两个并发 POST 可能同时读到
                # ``extends_used=N``、各自 ``+= seconds`` 后竞争性写回 ``N+1``，
                # 总扩展秒数被记一次但 ``auto_resubmit_timeout`` 累计了两次。
                # facade 返回 ``(success, error_code, extends_used_after, timeout_after)``
                # — 我们用 timeout_after 重算 remaining 而不依赖锁外的 task 引用，
                # 保证响应数据是该次扩展操作完成时的快照。
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
                    # 422 仅留给"上限已达"；其他错误码是输入/状态错误 → 400
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

                # 成功路径：直接走 HTTP response 把新 deadline + extends_used
                # 返回给发起者；其他 client 通过下一次 GET /api/tasks 轮询
                # 自动同步（既有 5s polling）。**故意不**新增 SSE 事件类型
                # （避免引入 task_updated 类型需要的 schema 校验 + 前端事件
                # 监听器 + sse_event_schemas.py 改动），扩展是单用户操作，
                # 多 client 间秒级延迟可接受。
                #
                # 为了让 remaining_time 也反映同一时间快照，我们用 facade 返回
                # 的 ``new_timeout`` 重新读一次（锁外读 task 是允许的，但用
                # facade 已经返回的值更稳）：构造一个临时 Task-like 计算。
                # 简化：直接 get_task 再算一次 remaining，避免与 facade 输出
                # 漂移（task 对象在 dict 中存活，读其字段是 thread-safe）。
                task = task_queue.get_task(task_id)
                now_monotonic = time.monotonic()
                new_remaining = (
                    task.get_remaining_time(now_monotonic=now_monotonic)
                    if task is not None
                    # 极小可能 task 在 facade 后被 cleanup 删除；用 new_timeout
                    # 兜底（视为创建时间是 now，给客户端一个非负 fallback）
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

                logger.info(f"任务 {task_id} 反馈已提交")
                return jsonify({"success": True, "message": msg("feedback.submitted")})
            except Exception as e:
                logger.error(f"提交任务失败: {e}", exc_info=True)
                return jsonify({"success": False, "error": "服务器内部错误"}), 500
