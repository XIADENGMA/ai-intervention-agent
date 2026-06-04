"""任务队列管理 - 线程安全、状态管理、自动清理、延迟删除、持久化。"""

import json
import logging
import os
import sys
import tempfile
import threading
import time
import traceback
from collections.abc import Callable, Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from threading import Lock
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ai_intervention_agent.config_manager import ReadWriteLock
from ai_intervention_agent.server_config import (
    AUTO_RESUBMIT_TIMEOUT_DEFAULT,
    AUTO_RESUBMIT_TIMEOUT_MAX,
    AUTO_RESUBMIT_TIMEOUT_MIN,
)

logger = logging.getLogger(__name__)


# ============================================================================
# R51-A：写锁 deadlock detector
# ----------------------------------------------------------------------------
# 设计要点：
#   1. **不改 ``ReadWriteLock``**：保留 contextmanager 语义，watchdog 仅是
#      orthogonal 的旁路观察。
#   2. **零 hot-path 开销**：每次 ``_watched_write_lock`` 进出仅做一次
#      ``dict[int]`` 写、一次 ``threading.Lock`` 进出，约 1 μs 量级；
#      不创建 ``threading.Timer``（创建/cancel 大约 ~10 μs，且产生 GC 压力）。
#   3. **共享后台线程**：模块级单例 ``_watchdog_thread`` daemon，每 5 s 扫描
#      一次 ``_pending_acquisitions``，发现 hold 时长 > ``_LOCK_WATCHDOG_TIMEOUT_S``
#      就 dump 全部线程栈到 ``logger.error`` 一次（``dumped`` flag 防止 spam）。
#   4. **覆盖范围**：watch ``acquire + hold + release`` 整个 critical section。
#      实务上这正是我们想看到的：deadlock 的征兆既包括"拿不到锁"，也包括
#      "拿到锁但临界区内卡死"。
#   5. **演进路径**：第一阶段只 instrument ``add_task`` 这条最热写路径；后续
#      可逐步把 ``complete_task`` / ``cleanup_completed_tasks`` 等 17 处写锁
#      迁移到 ``_watched_write_lock``，每条带独立 ``label`` 便于诊断。
# ============================================================================

# ============================================================================
# R53-A：``add_task`` 输入大小防护
# ----------------------------------------------------------------------------
# add_task 直接把 prompt 存进 self._tasks 的 Task 对象，长期占用进程内存；恶意
# 或 buggy caller 塞 100 MB 字符串就能把内存炸了，且我们的 SSE 推送会把
# task_changed payload 里的 statistics + 摘要信息广播给所有连接，巨型 payload
# 还会撑爆 SSE bus 的 history deque。
#
# 设计：6 MB warn（让运维察觉异常 caller），10 MB reject（硬上限，单条 add_task
# 直接返回 False）。阈值参考：
#   * 单条人类可读 prompt 极少超过 100 KB；
#   * markdown summary 包含图片 base64 时偶尔触达 1-2 MB；
#   * 6 MB 已经是任何"合理"业务的 100 倍以上；
#   * 10 MB 接近 Flask 默认 MAX_CONTENT_LENGTH（16 MB）的实际下限，再大请求
#     在 ``request.get_json`` 阶段早就被 reject 了。
# ============================================================================

_PROMPT_WARN_BYTES: int = 6 * 1024 * 1024  # 6 MB
"""``add_task`` 收到的 prompt（UTF-8 编码后字节数）超过此值时 ``logger.warning``。
不会拒绝，但日志里会留下 footprint 让运维看到 caller 的异常输入趋势。"""

_PROMPT_REJECT_BYTES: int = 10 * 1024 * 1024  # 10 MB
"""``add_task`` 收到的 prompt 超过此值时直接 ``return False``，不进队列。
保护进程内存 + SSE history deque + 跨进程 IPC payload。"""

PLACEHOLDER_MAX_LENGTH: int = 200
"""mining-cycle-3 §2.1 borrow #3 single source of truth for the
``feedback_placeholder`` clamp. cr37 §8 #1 提取自原 ``add_task`` 内嵌
literal 200 — route handler 也引用此常量，避免双处 drift。

理由：textarea ``placeholder`` 是单行 hint，超过 200 chars 会被截断
显示，多行 placeholder 违反 a11y。"""


_LOCK_WATCHDOG_TIMEOUT_S: float = 30.0
"""单次 ``_watched_write_lock`` 的 acquire+hold 上限。超过这个时长 watchdog
扫到一次就 dump 全线程栈到 ``logger.error``。

30 s 是一个折中：实测 ``add_task`` 的临界区微秒级 → 任何 > 5 s 的 wait 都
肯定异常；但 CI 环境跑 pytest 时，sleep / IO 抖动可能超过 1 s，所以保留
一个相对宽松的窗口避免误报。运行时可由测试通过 monkeypatch 调小。"""

_LOCK_WATCHDOG_SCAN_INTERVAL_S: float = 5.0
"""watchdog 扫描周期。``_LOCK_WATCHDOG_TIMEOUT_S / _LOCK_WATCHDOG_SCAN_INTERVAL_S
≈ 6`` 意味着真出现 deadlock 时最快 5 s、最慢 35 s 就会有 dump 进入日志。"""

_pending_acquisitions: dict[int, dict[str, Any]] = {}
"""``rec_id -> {label, thread_id, start, dumped}``：当前正持有 / 等待
``_watched_write_lock`` 的所有 record。``rec_id`` 用 ``id(rec)``，
保证同一线程嵌套调用不会冲突（虽然 ``ReadWriteLock`` 已禁止嵌套）。"""

_pending_acquisitions_lock = threading.Lock()
"""保护 ``_pending_acquisitions`` 的细粒度 lock。作用域非常短（dict 增删），
不嵌入临界区，因此不会和 ``ReadWriteLock`` 形成新的 lock-order 风险。"""

_watchdog_thread: threading.Thread | None = None
_watchdog_started_lock = threading.Lock()


def _capture_all_thread_stacks() -> str:
    """采集进程内所有线程的当前调用栈，拼成可读字符串。

    ``sys._current_frames`` 在 CPython 是受支持的公开-但-下划线 API
    （PEP 8 的"私有但 stdlib 有保证"约定）；在 PyPy 上也实现了。任何不可
    采集的环境都返回 fallback 串而不是抛异常，避免 watchdog 自身崩溃。"""
    try:
        frames = sys._current_frames()
    except Exception as exc:  # pragma: no cover — 防御性
        return f"<failed to capture stacks: {exc!r}>"
    chunks: list[str] = []
    for tid, frame in frames.items():
        chunks.append(f"\n--- Thread id={tid} ---\n")
        try:
            chunks.extend(traceback.format_stack(frame))
        except Exception as exc:  # pragma: no cover — 防御性
            chunks.append(f"<failed to format stack for tid={tid}: {exc!r}>\n")
    return "".join(chunks)


def _scan_pending_and_dump_slow() -> int:
    """单次扫描：把超时但尚未 dump 的 record 拣出来，dump 全栈到 logger.error。

    返回这一次新 dump 的 record 数量，方便测试断言。被 daemon 主循环周期调用，
    也可被测试单独调用，因此和 ``_lock_watchdog_loop`` 解耦。"""
    now = time.monotonic()
    slow_records: list[dict[str, Any]] = []
    with _pending_acquisitions_lock:
        for rec in _pending_acquisitions.values():
            if rec.get("dumped"):
                continue
            if now - rec["start"] > _LOCK_WATCHDOG_TIMEOUT_S:
                rec["dumped"] = True
                slow_records.append(dict(rec))
    if not slow_records:
        return 0
    stacks = _capture_all_thread_stacks()
    for rec in slow_records:
        logger.error(
            f"⚠️ TaskQueue 写锁卡死 > {_LOCK_WATCHDOG_TIMEOUT_S:.0f}s "
            f"(label={rec['label']}, "
            f"waiting_thread_id={rec['thread_id']}, "
            f"waited={(now - rec['start']):.1f}s)\n"
            f"全线程栈快照：\n{stacks}"
        )
    return len(slow_records)


_lock_watchdog_wake_event = threading.Event()
"""测试可通过 ``_lock_watchdog_wake_event.set()`` 把 daemon 从 sleep 里唤醒，
让它立刻执行下一轮 ``_scan_pending_and_dump_slow``。生产路径不会用到。"""


def _lock_watchdog_loop() -> None:
    """daemon 后台线程主循环：用 Event 而非裸 ``time.sleep``，方便测试唤醒。"""
    while True:
        try:
            woke = _lock_watchdog_wake_event.wait(_LOCK_WATCHDOG_SCAN_INTERVAL_S)
            if woke:
                _lock_watchdog_wake_event.clear()
            _scan_pending_and_dump_slow()
        except Exception as exc:
            # watchdog 本身绝不能让 daemon 死掉
            logger.warning(f"Lock watchdog loop 异常（已吞）: {exc}", exc_info=True)


def _ensure_lock_watchdog_started() -> None:
    """懒启动：第一次有人 ``_watched_write_lock`` 才把 daemon 起来。

    幂等：重复调用直接返回。即便 daemon 因不可预期原因退出，下次调用会
    重新起一个新的 ―― 这是"自愈"语义而非"crash"。"""
    global _watchdog_thread
    with _watchdog_started_lock:
        if _watchdog_thread is not None and _watchdog_thread.is_alive():
            return
        _watchdog_thread = threading.Thread(
            target=_lock_watchdog_loop,
            name="TaskQueueLockWatchdog",
            daemon=True,
        )
        _watchdog_thread.start()
        logger.debug("TaskQueueLockWatchdog daemon 已启动")


@contextmanager
def _watched_write_lock(
    rwlock: ReadWriteLock, label: str
) -> Generator[None, None, None]:
    """``rwlock.write_lock()`` 的 deadlock-aware 包装。

    使用方式：

        with _watched_write_lock(self._lock, "add_task"):
            ... critical section ...

    超过 ``_LOCK_WATCHDOG_TIMEOUT_S`` 没释放，daemon 会 dump 全栈到
    ``logger.error``。dump 不会打断流程，仅作"现场快照"用，便于事后分析。"""
    _ensure_lock_watchdog_started()
    rec: dict[str, Any] = {
        "label": label,
        "thread_id": threading.get_ident(),
        "start": time.monotonic(),
        "dumped": False,
    }
    rec_id = id(rec)
    with _pending_acquisitions_lock:
        _pending_acquisitions[rec_id] = rec
    try:
        with rwlock.write_lock():
            yield
    finally:
        with _pending_acquisitions_lock:
            _pending_acquisitions.pop(rec_id, None)


class TaskStatus(StrEnum):
    """任务状态枚举（StrEnum 使其与纯字符串完全兼容）"""

    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"
    REMOVED = "removed"


class Task(BaseModel):
    """任务数据结构：task_id, prompt, options, status, result"""

    model_config = ConfigDict(validate_assignment=True)

    task_id: str
    prompt: str
    predefined_options: list[str] | None = None
    # 每个预定义选项的"默认是否选中"。可省略；省略时等价于全 False。
    # 长度若与 predefined_options 不一致，前端按位置逐一对应、缺失项视为 False。
    #
    # R167 后语义稳定：
    # - LLM → MCP ``interactive_feedback``：禁止用 parallel-array 形态
    #   （顶层参数已移除），必须用 ``predefined_options=[{label, default}]``
    #   的 dict 形态。``server_feedback`` 内部会把 dict 形态拆成
    #   ``predefined_options`` (list[str]) + ``predefined_options_defaults``
    #   (list[bool]) 再调本字段；
    # - 外部 HTTP ``POST /api/tasks``（VS Code 插件 / 自动化脚本路径）：
    #   仍然支持显式传 parallel-array 形态，``web_ui_routes/task.py``
    #   会做长度校验和 bool normalization；
    # - 本字段是上述两条路径的统一内部表示，前端 ``multi_task.js`` 渲染
    #   单选/多选 chip 默认勾选状态时直接读它。
    predefined_options_defaults: list[bool] | None = None
    auto_resubmit_timeout: int = AUTO_RESUBMIT_TIMEOUT_DEFAULT
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    created_at_monotonic: float = Field(default_factory=time.monotonic)
    status: str = TaskStatus.PENDING
    result: dict[str, Any] | None = None
    completed_at: datetime | None = None
    # feat-countdown-extend (§3.2)：用户主动扩展过倒计时的次数。
    # 每次扩展 = ``auto_resubmit_timeout += extend_seconds``。
    # 上限由 ``Task.extend_deadline`` 的 ``max_extends`` 参数控制（路由层
    # 从 server_config 读，默认 3 次），防止用户无限拖时间绕开 auto-resubmit。
    # 0 = 从未扩展，前端按钮可点击；>= max_extends 时按钮 disabled。
    extends_used: int = 0
    # mining-cycle-3 §2.1 borrow #3 (gemini-cli ``ask_user`` placeholder)：
    # 每个 task 可选的 textarea placeholder，覆盖全局 i18n
    # ``page.feedbackPlaceholder``。让 agent 在调 MCP 工具时为不同任务
    # 提示用户具体应该填什么（"Paste the error stack trace" /
    # "Describe the visual glitch" / etc）。
    # 设计点：长度软上限 200 chars（textarea placeholder 超过 1 行就
    # 失去意义）；None = 走 i18n 默认值。
    feedback_placeholder: str | None = None
    # mining-cycle-3 §2.1 borrow #2 (gemini-cli ``ask_user`` yesno type)：
    # 当 agent 只想要二元决策（approve / reject / proceed / abort）时，
    # 设置 question_type="yesno"，前端隐藏 textarea + 显示一行 Yes/No
    # 2-button。一击直接提交，省 textarea-typing + submit 两步。
    # 默认 None = textarea 主体保留（既有交互不变）；"yesno" = 切换。
    # 未来 future type 可加: "choice"（radio 单选）/ "rating"（1-5 star）
    # 等，目前只 ship "yesno"（最高频用例）。
    question_type: str | None = None

    def get_remaining_time(self, now_monotonic: float | None = None) -> int:
        """计算剩余倒计时（使用单调时间）。

        ``now_monotonic`` 允许高频列表接口在一次请求内复用同一个时间快照，
        避免每个任务各自调用一次 ``time.monotonic()``。
        """
        if self.status == TaskStatus.COMPLETED:
            return 0

        # 约定：auto_resubmit_timeout <= 0 表示“禁用自动重调/倒计时”
        if self.auto_resubmit_timeout <= 0:
            return 0

        # 【优化】使用单调时间计算，不受系统时间调整影响
        now = time.monotonic() if now_monotonic is None else now_monotonic
        elapsed = now - self.created_at_monotonic
        remaining = self.auto_resubmit_timeout - elapsed

        # 确保返回值在合理范围内
        return max(0, int(remaining))

    def get_deadline_monotonic(self) -> float:
        """获取截止时间的单调时间戳"""
        # 约定：auto_resubmit_timeout <= 0 表示“禁用自动重调/倒计时”，不应过期
        if self.auto_resubmit_timeout <= 0:
            return float("inf")
        return self.created_at_monotonic + self.auto_resubmit_timeout

    def is_expired(self) -> bool:
        """检查任务是否已超时

        【新增】使用单调时间判断任务是否已超时。

        返回:
            bool: True 表示已超时，False 表示未超时
        """
        if self.status == TaskStatus.COMPLETED:
            return False
        # 约定：auto_resubmit_timeout <= 0 表示“禁用自动重调/倒计时”，不应过期
        if self.auto_resubmit_timeout <= 0:
            return False
        return time.monotonic() > self.get_deadline_monotonic()

    # cr32 §3.3 low fix：删掉硬编码 max_extends=3 默认值，强制 caller 显式
    # 传入。route 层从 server_config.COUNTDOWN_EXTENDS_MAX 读，避免单元
    # 测试 / 脚本不慎用 3 但 prod 配置改了之后两边漂移。同时 min/max
    # seconds 也走必填，逻辑上 caller 总是应该明确语义。
    def extend_deadline(
        self,
        seconds: int,
        *,
        max_extends: int,
        min_seconds: int,
        max_seconds: int,
    ) -> tuple[bool, str | None]:
        """feat-countdown-extend (§3.2): 用户主动延长 task 的 auto-resubmit
        倒计时。

        实现方式：直接增加 ``auto_resubmit_timeout`` 而不是修改
        ``created_at_monotonic``。后者是真实创建时间快照，不应被业务
        逻辑改动。``get_remaining_time`` = ``auto_resubmit_timeout -
        elapsed``，所以增加 timeout 等价于把 deadline 往后推。

        典型用户场景：写超长反馈时不想被 240s 倒计时压力 →
        点击 +60s 按钮 → 后端调用本方法 → SSE 广播 task_updated →
        前端通过既有 updateTasksList 路径自动刷新 UI（不需要专门 fetch）。

        参数
        ----
        seconds:
            要延长的秒数（必须在 [min_seconds, max_seconds] 内）。
        max_extends:
            该 task 允许的总延长次数（来自 server_config，默认 3）。
            达到上限时本调用失败，前端按钮置 disabled。
        min_seconds / max_seconds:
            单次延长的合理范围；默认 [10, 300]，避免用户 +1s spam 或
            一口气 +3600s 把 auto-resubmit 实际功能架空。

        返回
        ----
        (success, error_code)：
            - (True, None) 成功
            - (False, "task_completed") task 已完成，不能再延长
            - (False, "auto_resubmit_disabled") task 没有 auto-resubmit
              （``auto_resubmit_timeout <= 0``），无延长意义
            - (False, "extends_limit_reached") 已达 max_extends 上限
            - (False, "invalid_seconds") seconds 超出 [min, max] 范围
        """
        if self.status == TaskStatus.COMPLETED:
            return False, "task_completed"
        if self.auto_resubmit_timeout <= 0:
            return False, "auto_resubmit_disabled"
        if self.extends_used >= max_extends:
            return False, "extends_limit_reached"
        if not (min_seconds <= seconds <= max_seconds):
            return False, "invalid_seconds"
        # 同时改两个字段；validate_assignment=True 让 pydantic 在不合理
        # 的极端情况下抛错（auto_resubmit_timeout 是 int 不会有 overflow，
        # 但保留 invariant 给未来的字段约束变更）。
        self.auto_resubmit_timeout = self.auto_resubmit_timeout + seconds
        self.extends_used = self.extends_used + 1
        return True, None


class TaskQueue:
    """任务队列管理器（线程安全）

    提供任务的添加、查询、状态管理和自动清理功能。

    ## 核心特性

    ### 1. 线程安全
    - 所有公共方法使用 `threading.Lock` 保护
    - 支持多线程并发访问
    - 内部数据结构（_tasks, _task_order）始终保持一致

    ### 2. 单活动任务模式
    - 同一时间只有一个任务处于 `active` 状态
    - 其他任务处于 `pending` 状态
    - 活动任务完成后自动激活下一个pending任务

    ### 3. 延迟删除机制
    - 任务完成后不立即删除
    - 标记 `completed_at` 时间戳
    - 后台线程延迟10秒后自动删除
    - 避免前端轮询时遇到404错误

    ### 4. 后台清理线程
    - 守护线程（daemon=True）
    - 每5秒检查一次
    - 清理完成10秒以上的任务
    - 应用退出时自动停止

    ## 数据结构

    ### 内部字段
    - `_tasks`: dict[str, Task] - 任务字典，key为task_id（Python 3.7+ 保持插入顺序）
    - `_lock`: ReadWriteLock - 读写锁，多读者并发，写者独占（R22.2 起）
    - `_active_task_id`: str | None - 当前活动任务ID
    - `_stop_cleanup`: Event - 停止清理线程的事件
    - `_cleanup_thread`: Thread - 后台清理线程

    ### 性能优化说明
    - **移除了冗余的 `_task_order` 列表**：Python 3.7+ dict 已保持插入顺序
    - **删除操作从 O(n) 优化到 O(1)**：不再需要 list.remove() 操作
    - **内存占用减少**：不再维护额外的任务ID列表

    ## 任务状态管理

    ```
    add_task()       → status = "pending" 或 "active"（如果是第一个）
    set_active_task() → status = "active"（旧的变为pending）
    complete_task()   → status = "completed"（10秒后删除）
    remove_task()     → 直接删除
    ```

    ## 线程安全保证（R22.2 重构后）

    所有公共方法均通过 ``self._lock`` 保护，但读路径走 ``read_lock()``、
    写路径走 ``write_lock()``，读读并发、读写仍互斥、写写仍互斥：

    - **写路径**（互斥）：``add_task`` / ``set_active_task`` /
      ``complete_task`` / ``remove_task`` / ``clear_completed_tasks`` /
      ``cleanup_completed_tasks`` / ``clear_all_tasks`` /
      ``update_auto_resubmit_timeout_for_all``
    - **读路径**（可并发）：``get_task`` / ``get_all_tasks`` /
      ``get_active_task`` / ``get_task_count`` / ``_persist`` 内部读快照

    禁忌：禁止在已持锁的线程中再次获取本锁（``ReadWriteLock`` 不支持
    递归 / 升级 / 降级）。当前所有写后副作用（``_persist`` /
    ``_trigger_status_change``）均在锁外触发，无嵌套风险。

    ## 性能考虑

    - **Lock 类型**：``ReadWriteLock``（读写分离）
      - R22.2 起：读读并发，写者独占；多 client 高频读路径不再互相阻塞
      - 适用场景：读多写少（GET /api/tasks SSE / 倒计时刷新 ≫ add/complete）
      - 注意：写者饥饿风险存在但实测可接受（写频次 ≪ 读频次）

    - **内存占用**：O(n)，n为任务数量
      - 每个任务约1KB（取决于prompt和options）
      - 最多max_tasks个任务同时存在
      - 完成的任务会在10秒后清理

    - **时间复杂度（优化后）**：
      - add_task: O(1)
      - get_task: O(1)
      - get_all_tasks: O(n)
      - remove_task: O(1)（原来是 O(n)，优化后使用 dict.pop()）
      - complete_task: O(n)（需要查找下一个pending任务）
      - cleanup_completed_tasks: O(n)

    ## 注意事项

    - 必须在应用关闭时调用 `stop_cleanup()` 停止后台线程
    - 任务ID必须全局唯一
    - 队列满时 add_task 会返回 False
    - completed 任务会在10秒后自动删除
    - 不要在锁内执行耗时操作

    属性:
        max_tasks (int): 最大并发任务数
    """

    def __init__(self, max_tasks: int = 10, persist_path: str | None = None):
        """初始化任务队列

        创建任务队列实例并启动后台清理线程。

        参数:
            max_tasks (int): 最大并发任务数，默认10
            persist_path (str|None): 持久化文件路径。设置后任务状态变更自动写入磁盘，
                重启时自动恢复未完成任务。传 None 禁用持久化（纯内存模式）。
        """
        self.max_tasks = max_tasks
        self._tasks: dict[str, Task] = {}
        # R22.2：把粗粒度 ``threading.Lock`` 升级为 ``ReadWriteLock``。
        # why：``GET /api/tasks`` / SSE / 倒计时刷新都是高频纯读路径
        # （``get_task`` / ``get_all_tasks`` / ``get_active_task`` /
        # ``get_task_count`` / ``_persist`` snapshot），互相之间没有冲突，
        # 但旧 ``Lock`` 一律串行，多 client + 多面板场景下读侧自相阻塞。
        # ``ReadWriteLock`` 让读读并发、读写仍互斥、写写仍互斥，对单写者频率
        # 几乎不变，但 N 个并发读者从串行降为并行。约束：禁止在同一线程嵌套
        # 持锁（``_persist`` 已设计为锁外调用，``_trigger_status_change``
        # 也在锁外触发，无嵌套风险）。
        self._lock = ReadWriteLock()
        self._active_task_id: str | None = None

        self._status_change_callbacks: list[Callable[[str, str | None, str], None]] = []
        self._callbacks_lock = Lock()

        # P0：hot-path cleanup 节流时间戳（单调时钟，避免系统时间漂移影响）。
        # `cleanup_completed_tasks_throttled()` 在距上次执行不足 throttle_seconds
        # 时直接返回 0；后台线程使用未节流的 cleanup_completed_tasks() 维持
        # 5s 主节奏，hot-path 仅在后台线程异常停滞时充当兜底（~30s 1 次）。
        # 设 -inf 让首次调用必然真跑（init 后立即 cleanup 残留任务也是合理的）。
        self._last_hotpath_cleanup_monotonic: float = float("-inf")
        self._hotpath_cleanup_lock = Lock()

        self._persist_path: Path | None = Path(persist_path) if persist_path else None
        if self._persist_path:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            self._restore()

        self._stop_cleanup = threading.Event()
        self._cleanup_thread = threading.Thread(
            target=self._cleanup_loop, daemon=True, name="TaskQueueCleanup"
        )
        self._cleanup_thread.start()

        logger.info(
            f"任务队列初始化完成，最大任务数: {max_tasks}，"
            f"持久化: {'启用 → ' + str(self._persist_path) if self._persist_path else '禁用'}，"
            f"后台清理线程已启动"
        )

    def clear_all_tasks(self) -> int:
        """清理所有任务（重置队列）

        删除所有任务并重置队列状态，用于服务启动时清理残留任务。

        """
        with _watched_write_lock(self._lock, "clear_all_tasks"):
            count = len(self._tasks)
            self._tasks.clear()
            self._active_task_id = None
            if count > 0:
                logger.info(f"清理了所有残留任务，共 {count} 个")

        if count > 0:
            self._persist()
        return count

    def add_task(
        self,
        task_id: str,
        prompt: str,
        predefined_options: list[str] | None = None,
        auto_resubmit_timeout: int = AUTO_RESUBMIT_TIMEOUT_DEFAULT,
        predefined_options_defaults: list[bool] | None = None,
        feedback_placeholder: str | None = None,
        question_type: str | None = None,
    ) -> bool:
        """添加任务，无活动任务时自动激活"""
        # R53-A：在拿写锁之前先做 prompt size 校验。锁外校验有两个好处：
        # (1) reject 路径不消耗写锁，不阻塞其它合法 add_task；
        # (2) 巨型 prompt 不进锁内的 Task() 构造（pydantic validator 也要走
        # str → 内部字段拷贝，10+ MB 字符串拷贝会拖慢临界区）。
        try:
            prompt_bytes = len(prompt.encode("utf-8", errors="replace"))
        except Exception:
            # 非常规边界：prompt 不是 str（caller 传错类型）。这里不抛 TypeError
            # —— 后续 Task() 构造会因 pydantic 校验自然失败，返回 False 等价
            # 于 reject。我们只在能算出 size 时做 size gate。
            prompt_bytes = 0
        if prompt_bytes > _PROMPT_REJECT_BYTES:
            logger.warning(
                f"add_task 拒绝 task_id={task_id}：prompt {prompt_bytes / 1024 / 1024:.1f} MB "
                f"超过硬上限 {_PROMPT_REJECT_BYTES / 1024 / 1024:.0f} MB（R53-A）"
            )
            return False
        if prompt_bytes > _PROMPT_WARN_BYTES:
            logger.warning(
                f"add_task 大 prompt 警告 task_id={task_id}："
                f"prompt {prompt_bytes / 1024 / 1024:.1f} MB 超过 warn 阈值 "
                f"{_PROMPT_WARN_BYTES / 1024 / 1024:.0f} MB（R53-A，未拒绝）"
            )

        new_status: str | None = None
        # R51-A：用 deadlock-aware 写锁包装。临界区内任何卡死都会被
        # ``_lock_watchdog_loop`` 检测并把全栈 dump 到 logger.error。
        with _watched_write_lock(self._lock, "add_task"):
            if auto_resubmit_timeout <= 0:
                auto_resubmit_timeout = 0
            else:
                auto_resubmit_timeout = max(
                    AUTO_RESUBMIT_TIMEOUT_MIN,
                    min(auto_resubmit_timeout, AUTO_RESUBMIT_TIMEOUT_MAX),
                )

            if len(self._tasks) >= self.max_tasks:
                logger.warning(
                    f"任务队列已满({self.max_tasks})，无法添加新任务: {task_id}"
                )
                return False

            if task_id in self._tasks:
                logger.warning(f"任务ID已存在: {task_id}")
                return False

            # mining-cycle-3 §2.1 borrow #3: clamp placeholder using
            # ``PLACEHOLDER_MAX_LENGTH`` module constant (cr37 §8 #1)
            # 单行 placeholder 超过该长度在 textarea 中会被截断显示；
            # 多行 placeholder 违反 a11y。同样常量被 web_ui_routes/task.py
            # 引用以判断是否需要返回 ``placeholder_truncated`` 响应。
            normalized_placeholder: str | None = None
            if isinstance(feedback_placeholder, str):
                s = feedback_placeholder.strip()
                if s:
                    normalized_placeholder = s[:PLACEHOLDER_MAX_LENGTH]

            # mining-cycle-3 §2.1 borrow #2: validate question_type
            # 白名单：目前只 ship "yesno"；其他值（包括无效字符串）
            # 静默归 None，等价 "走原 textarea 主体"。这是 forward-compat
            # 策略：未来添加 "choice" / "rating" 等不需要改 schema，前端
            # 升级后自动 enable；当前前端只识 "yesno"。
            normalized_question_type: str | None = None
            if isinstance(question_type, str) and question_type.strip() == "yesno":
                normalized_question_type = "yesno"

            task = Task(
                task_id=task_id,
                prompt=prompt,
                predefined_options=predefined_options,
                predefined_options_defaults=predefined_options_defaults,
                auto_resubmit_timeout=auto_resubmit_timeout,
                feedback_placeholder=normalized_placeholder,
                question_type=normalized_question_type,
            )

            # 【性能优化】直接添加到字典，Python 3.7+ 保持插入顺序
            self._tasks[task_id] = task

            if self._active_task_id is None:
                self._active_task_id = task_id
                task.status = TaskStatus.ACTIVE
            else:
                task.status = TaskStatus.PENDING

            logger.info(
                f"添加任务成功: {task_id}, 当前任务数: {len(self._tasks)}/{self.max_tasks}"
            )

            # 回调在锁外触发，避免回调重入导致死锁
            new_status = task.status

        if new_status is not None:
            self._trigger_status_change(task_id, None, new_status)
            self._persist()

        return True

    def get_task(self, task_id: str) -> Task | None:
        """获取指定任务

        通过任务ID查询任务对象，返回任务的当前状态快照。

        **注意**：返回的是任务对象的直接引用（非深拷贝）。调用方在锁外读取
        属性时，可能与其他线程对同一 Task 的写操作产生竞态。当前所有调用点
        均为只读访问（读 task_id/prompt/status），GIL 保证了单属性读取的安全，
        但如需一致的多字段快照，应自行加锁或在锁内完成读取。

        参数:
            task_id (str): 任务唯一标识符

        返回:
            Task | None: 任务对象，不存在则返回 None
                - Task对象包含所有任务信息
                - None表示任务不存在或已被删除

        线程安全:
            查询本身线程安全（使用 Lock 保护），但返回值的后续访问不受锁保护。

        时间复杂度:
            O(1) - 字典查询
        """
        with self._lock.read_lock():
            return self._tasks.get(task_id)

    def get_all_tasks(self) -> list[Task]:
        """获取所有任务列表"""
        with self._lock.read_lock():
            # 【性能优化】Python 3.7+ dict 保持插入顺序，直接返回 values
            return list(self._tasks.values())

    def get_all_tasks_with_stats(self) -> tuple[list[Task], dict[str, int]]:
        """单次 read_lock 内同时拿 task list + stats，专门给 ``/api/tasks`` 用。

        R23.4: ``web_ui_routes/task.py::get_tasks`` 之前用 ``get_all_tasks()``
        + ``get_task_count()`` 两次独立调用，每次都进入一次 ``read_lock`` 上下
        文（R22.2 起的 ``ReadWriteLock``，单次 ~200-500 ns 的 atomic 进出 +
        readers 计数原子加减）；现在合并成一次。

        why：
        - ``/api/tasks`` 是 hot path（前端默认 2 s 间隔轮询，扩展状态栏 SSE
          失败后兜底也是 3 s）：单 web_ui 进程稳态有 2-5 个并发客户端各拉一次，
          每分钟 ~50-150 次调用。每个调用省 ~400-900 ns（一次 read_lock 进出
          + 一次 list view 重新构造），按 100 次/min 算每分钟省 40-90 µs；
          虽然绝对值小，但 stage R22.2 已经把 read 端优化到 RWLock 极限，再
          细一阶就只能合并相邻的读 —— R23.4 是当前抽象层下能拿到的最后一个
          read-side 优化。
        - **原子语义升级**：旧版两次 ``read_lock`` 中间，writer 可以插队改
          ``_tasks`` —— 比如 ``add_task`` 在 ``get_all_tasks`` 返回后、
          ``get_task_count`` 进入前修改了字典；调用方就拿到 N 个 task 但
          stats 显示 N+1 个 total，前端必须容忍这种 1-step skew（之前通过
          ``server_time`` 字段隐式协调）。新版单次 ``read_lock`` 让 list 和
          stats 完全一致，对前端 invariant 检查更友好（虽然 R20.14-C 起 SSE
          payload 已直接带 stats，所以这条 fetch 路径的 skew 风险本就极低）。

        Returns:
            tuple[list[Task], dict[str, int]]:
                - tasks: 与 ``get_all_tasks()`` 同语义的 list copy
                - stats: 与 ``get_task_count()`` 同结构的 dict（含 total /
                  pending / active / completed / max）
        """
        with self._lock.read_lock():
            tasks_view = list(self._tasks.values())
            counts: dict[str, int] = {
                TaskStatus.PENDING: 0,
                TaskStatus.ACTIVE: 0,
                TaskStatus.COMPLETED: 0,
            }
            for t in tasks_view:
                if t.status in counts:
                    counts[t.status] += 1
            stats: dict[str, int] = {
                "total": len(tasks_view),
                **counts,
                "max": self.max_tasks,
            }
            return tasks_view, stats

    def update_auto_resubmit_timeout_for_all(self, auto_resubmit_timeout: int) -> int:
        """更新所有未完成任务的 auto_resubmit_timeout

        用于配置热更新场景：当用户在运行中修改 feedback.frontend_countdown
        （或旧名称 auto_resubmit_timeout）时，希望**已经在倒计时中的任务**也能立即生效。

        更新策略：
        - 仅更新 status != "completed" 的任务（pending/active/expired）
        - 直接修改任务对象的 auto_resubmit_timeout 字段
        - 不修改 created_at/created_at_monotonic（倒计时基准保持任务创建时刻）

        注意：
        - 如果将超时时间调小到小于已过去时间，任务可能会立刻显示 remaining_time=0
        - auto_resubmit_timeout=0 在语义上表示“禁用自动重调”，上层需要配合前端逻辑避免误触发

        参数:
            auto_resubmit_timeout: 新的前端倒计时（秒）

        返回:
            int: 实际更新的任务数量
        """
        if auto_resubmit_timeout <= 0:
            auto_resubmit_timeout = 0
        else:
            auto_resubmit_timeout = max(
                AUTO_RESUBMIT_TIMEOUT_MIN,
                min(auto_resubmit_timeout, AUTO_RESUBMIT_TIMEOUT_MAX),
            )

        updated = 0
        with _watched_write_lock(self._lock, "update_auto_resubmit_timeout_for_all"):
            for task in self._tasks.values():
                if task.status == TaskStatus.COMPLETED:
                    continue
                if task.auto_resubmit_timeout != auto_resubmit_timeout:
                    task.auto_resubmit_timeout = auto_resubmit_timeout
                    updated += 1

        # 【P6R-1 修复】热更新已修改内存中的 auto_resubmit_timeout，
        # 若启用持久化必须同步写盘，否则进程重启会从快照恢复旧 timeout。
        # 与 add/complete/remove/set_active/clear 等其他状态变更保持一致。
        if updated > 0:
            self._persist()
        return updated

    def get_active_task(self) -> Task | None:
        """获取当前活动任务"""
        with self._lock.read_lock():
            if self._active_task_id:
                return self._tasks.get(self._active_task_id)
            return None

    # cr32 §3.3 low fix：与 ``Task.extend_deadline`` 一致，强制 caller 显式
    # 传 max_extends / min_seconds / max_seconds，避免 server_config 改了之
    # 后 facade 默认值还停留在旧值。
    def extend_task_deadline(
        self,
        task_id: str,
        seconds: int,
        *,
        max_extends: int,
        min_seconds: int,
        max_seconds: int,
    ) -> tuple[bool, str | None, int, int]:
        """cr32 §3.1 fix：在写锁内执行 ``Task.extend_deadline`` 的读改写原语。

        ## 为什么需要这个 facade？

        ``Task.extend_deadline`` 内部做 ``read extends_used → compare → write
        extends_used+1`` 的三步操作，Python 的 GIL 只保证单 bytecode 原子，
        不保证多语句原子。两个 HTTP 请求若同时落到同一 task 上，可能：

            T1: read extends_used=2 → check 2<3=True
            T2: read extends_used=2 → check 2<3=True
            T1: write extends_used=3 ← 现在不在锁内，T2 没看到
            T2: write extends_used=3 ← 实际累计了两次扩展但只计数一次

        最终 ``extends_used=3``（看起来对），但 ``auto_resubmit_timeout`` 已
        被 ``+= seconds`` 两次。用户得到一次免费扩展。

        ## 修复

        把读改写放在 ``self._lock`` 的 write_lock 内串行化。HTTP 路由调用此
        facade 而不是直接 ``task.extend_deadline``，并发竞态消失。

        Args:
            task_id: 任务 ID。
            seconds: 要扩展的秒数（必须在 ``[min_seconds, max_seconds]`` 内）。
            max_extends: 该任务最多可扩展次数。默认 3，路由层覆盖为
                ``COUNTDOWN_EXTENDS_MAX``。
            min_seconds / max_seconds: ``seconds`` 的硬范围（默认 [10, 300]）。

        Returns:
            ``(success, error_code, extends_used_after, auto_resubmit_timeout_after)``
            - success=True 时 error_code=None；新 ``extends_used`` 与
              ``auto_resubmit_timeout`` 字段对应的值。
            - success=False 时 error_code ∈
              {"task_not_found", "task_completed", "auto_resubmit_disabled",
               "extends_limit_reached", "invalid_seconds"}；后两个字段反映
              **当前** task 状态（用于让前端立即同步按钮 disabled 状态）。

        Thread-safety:
            写锁串行化整个读改写过程。对外的 ``task.extend_deadline`` 仍可
            直接调用（单线程脚本 / 单元测试），但在多线程上下文中**必须**
            走这个 facade。
        """
        with _watched_write_lock(self._lock, "extend_task_deadline"):
            task = self._tasks.get(task_id)
            if task is None:
                return False, "task_not_found", 0, 0
            success, error_code = task.extend_deadline(
                seconds,
                max_extends=max_extends,
                min_seconds=min_seconds,
                max_seconds=max_seconds,
            )
            return (
                success,
                error_code,
                task.extends_used,
                task.auto_resubmit_timeout,
            )

    def set_active_task(self, task_id: str) -> bool:
        """手动切换活动任务"""
        status_events: list[tuple[str, str | None, str]] = []
        with _watched_write_lock(self._lock, "set_active_task"):
            if task_id not in self._tasks:
                logger.warning(f"任务不存在: {task_id}")
                return False

            new_task = self._tasks[task_id]
            if new_task.status == TaskStatus.COMPLETED:
                logger.warning(f"任务已完成，无法激活: {task_id}")
                return False

            # 【P6R-2 修复】幂等：若调用方尝试激活当前已经 active 的任务，
            # 直接返回 True 且不触发任何状态事件/持久化。
            # 否则下面的代码会把该任务先降级为 PENDING 再升级回 ACTIVE，
            # 产生两个虚假事件（ACTIVE→PENDING / PENDING→ACTIVE），导致 SSE 闪烁、
            # 回调重复、快照多写一次。
            if self._active_task_id == task_id and new_task.status == TaskStatus.ACTIVE:
                logger.debug(f"任务已经是 active 状态，跳过切换: {task_id}")
                return True

            old_active_id = self._active_task_id
            old_active_status = None

            if self._active_task_id and self._active_task_id in self._tasks:
                old_task = self._tasks[self._active_task_id]
                if old_task.status == TaskStatus.ACTIVE:
                    old_active_status = old_task.status
                    old_task.status = TaskStatus.PENDING

            new_task_old_status = new_task.status
            self._active_task_id = task_id
            new_task.status = TaskStatus.ACTIVE

            logger.info(f"切换到任务: {task_id}")

            if old_active_id and old_active_status:
                status_events.append(
                    (old_active_id, TaskStatus.ACTIVE, TaskStatus.PENDING)
                )
            status_events.append((task_id, new_task_old_status, TaskStatus.ACTIVE))

        # 回调在锁外触发，避免回调重入导致死锁
        for ev_task_id, ev_old_status, ev_new_status in status_events:
            self._trigger_status_change(ev_task_id, ev_old_status, ev_new_status)

        if status_events:
            self._persist()
        return True

    def complete_task(self, task_id: str, result: dict[str, Any]) -> bool:
        """完成任务并标记为延迟删除（核心方法）

        将任务标记为已完成并保存结果，**不立即删除**。

        ## 延迟删除机制

        **为什么不立即删除？**
        - 前端可能正在轮询任务状态
        - 立即删除会导致前端收到404错误
        - 延迟10秒给前端足够时间获取结果

        **删除时机**：
        - 后台清理线程每5秒检查一次
        - 删除完成10秒以上的任务
        - 也可以手动调用 remove_task 立即删除

        ## 自动激活下一个任务

        如果完成的任务是活动任务，会自动激活下一个pending任务：
        1. 清空 _active_task_id
        2. 遍历任务字典（按插入顺序）
        3. 找到第一个 status='pending' 的任务并将其设置为 active

        参数:
            task_id (str): 要完成的任务ID
            result (dict[str, Any]): 任务执行结果
                - 通常包含 'feedback', 'selected_options' 等键
                - 格式由调用方决定
                - 示例：{'feedback': '用户输入', 'selected_options': ['选项1']}

        返回:
            bool: 是否成功完成
                - True: 成功标记为完成
                - False: 任务不存在

        线程安全:
            线程安全（使用 Lock 保护）

        副作用:
            - 设置 task.status = 'completed'
            - 设置 task.result
            - 设置 task.completed_at
            - 可能清空 _active_task_id
            - 可能自动激活下一个任务
            - 记录日志

        时间复杂度:
            O(n) - 最坏情况下需要遍历任务字典以查找下一个 pending 任务

        说明:
            - 任务完成后10秒内仍可查询
            - 前端应在收到完成状态后停止轮询
            - 自动激活逻辑只查找pending状态的任务
            - 如果没有pending任务，_active_task_id 保持为 None
        """
        status_events: list[tuple[str, str | None, str]] = []
        with _watched_write_lock(self._lock, "complete_task"):
            if task_id not in self._tasks:
                logger.warning(f"任务不存在: {task_id}")
                return False

            task = self._tasks[task_id]
            old_status = task.status
            task.status = TaskStatus.COMPLETED
            task.result = result
            task.completed_at = datetime.now(UTC)
            status_events.append((task_id, old_status, TaskStatus.COMPLETED))

            if self._active_task_id == task_id:
                self._active_task_id = None
                logger.info(f"任务完成并清空激活任务: {task_id}")

                for tid, t in self._tasks.items():
                    if t.status == TaskStatus.PENDING:
                        self._active_task_id = tid
                        t.status = TaskStatus.ACTIVE
                        logger.info(f"自动激活下一个任务: {tid}")
                        status_events.append(
                            (tid, TaskStatus.PENDING, TaskStatus.ACTIVE)
                        )
                        break
            else:
                logger.info(f"任务完成: {task_id}")

            logger.info(f"任务 {task_id} 已标记为完成（将在 10 秒后自动清理）")

        # 回调在锁外触发，避免回调重入导致死锁
        for ev_task_id, ev_old_status, ev_new_status in status_events:
            self._trigger_status_change(ev_task_id, ev_old_status, ev_new_status)

        self._persist()
        return True

    def remove_task(self, task_id: str) -> bool:
        """移除任务（立即删除）

        立即从队列中删除指定任务，不等待延迟删除。

        **与complete_task的区别**：
        - `complete_task`: 标记为完成，10秒后自动删除
        - `remove_task`: 立即删除，适用于取消或清理

        **自动激活逻辑**：
        如果删除的是活动任务，会自动激活下一个pending/active任务

        参数:
            task_id (str): 要移除的任务ID

        返回:
            bool: 是否成功移除
                - True: 成功移除
                - False: 任务不存在

        线程安全:
            线程安全（使用 Lock 保护）

        副作用:
            - 从 _tasks 删除任务（Python 3.7+ dict.pop() 是 O(1)）
            - 可能更新 _active_task_id
            - 可能自动激活下一个任务
            - 记录日志

        时间复杂度:
            - 若删除的不是活动任务：O(1)（dict.pop()）
            - 若删除的是活动任务：最坏 O(n)（需要遍历查找下一个任务）

        说明:
            - 适用于手动取消任务
            - 不推荐用于正常完成的任务（应使用complete_task）
            - 删除后任务立即不可查询
        """
        status_events: list[tuple[str, str | None, str]] = []
        with _watched_write_lock(self._lock, "remove_task"):
            if task_id not in self._tasks:
                logger.warning(f"任务不存在: {task_id}")
                return False

            old_status = self._tasks[task_id].status
            next_activated_id = None

            if self._active_task_id == task_id:
                self._active_task_id = None
                # 【性能优化】使用字典迭代代替列表遍历
                for tid, t in self._tasks.items():
                    if tid != task_id and t.status in (
                        TaskStatus.PENDING,
                        TaskStatus.ACTIVE,
                    ):
                        self._active_task_id = tid
                        old_next_status = t.status
                        t.status = TaskStatus.ACTIVE
                        next_activated_id = tid
                        break

            self._tasks.pop(task_id, None)

            logger.info(
                f"移除任务: {task_id}, 剩余任务数: {len(self._tasks)}/{self.max_tasks}"
            )

            status_events.append((task_id, old_status, TaskStatus.REMOVED))
            if next_activated_id:
                status_events.append(
                    (next_activated_id, old_next_status, TaskStatus.ACTIVE)
                )

        # 回调在锁外触发，避免回调重入导致死锁
        for ev_task_id, ev_old_status, ev_new_status in status_events:
            self._trigger_status_change(ev_task_id, ev_old_status, ev_new_status)

        self._persist()
        return True

    def clear_completed_tasks(self) -> int:
        """清理所有已完成的任务（立即删除）

        删除所有 status='completed' 的任务，不管完成时间。

        **使用场景**：
        - 手动清理所有已完成任务
        - 测试时清理环境
        - 队列维护操作

        **与cleanup_completed_tasks的区别**：
        - `clear_completed_tasks`: 清理所有completed任务（不限时间）
        - `cleanup_completed_tasks`: 只清理超过指定时间的completed任务

        返回:
            int: 清理的任务数量（>=0）

        线程安全:
            线程安全（使用 Lock 保护）

        副作用:
            - 删除所有completed任务
            - 记录日志（如果有清理）

        时间复杂度:
            O(n) - 需要遍历所有任务

        说明:
            - 不检查completed_at时间
            - 适用于需要立即清理的场景
            - 后台清理线程使用的是cleanup_completed_tasks
        """
        with _watched_write_lock(self._lock, "clear_completed_tasks"):
            completed_task_ids = [
                tid
                for tid, task in self._tasks.items()
                if task.status == TaskStatus.COMPLETED
            ]

            # 【性能优化】使用 dict.pop() 代替 del + list.remove()，O(1) 操作
            for tid in completed_task_ids:
                self._tasks.pop(tid, None)

            count = len(completed_task_ids)
            if count > 0:
                logger.info(f"清理了 {count} 个已完成任务")

            return count

    def cleanup_completed_tasks(self, age_seconds: int = 10) -> int:
        """清理超过指定时间的已完成任务（后台清理核心方法）

        删除完成时间超过 age_seconds 的任务。

        **延迟删除机制的关键方法**：
        - 后台清理线程每5秒调用一次
        - 默认清理完成10秒以上的任务
        - 避免前端轮询时遇到404

        **清理逻辑**：
        1. 检查任务status='completed'
        2. 检查completed_at是否存在
        3. 计算任务完成时长
        4. 如果超过age_seconds则删除

        参数:
            age_seconds (int): 任务完成后保留的秒数
                - 默认值：10秒
                - 建议值：5-30秒
                - 过小：前端可能遇到404
                - 过大：内存占用增加

        返回:
            int: 清理的任务数量（>=0）

        线程安全:
            线程安全（使用 Lock 保护）

        副作用:
            - 删除过期的completed任务
            - 记录日志（如果有清理）

        时间复杂度:
            O(n) - 需要遍历所有任务并计算时间差

        说明:
            - completed_at为None的任务不会被清理
            - 后台线程默认使用 age_seconds=10
            - 可以手动调用来立即清理
        """
        with _watched_write_lock(self._lock, "cleanup_completed_tasks"):
            now = datetime.now(UTC)  # 使用 UTC 时间，与 completed_at 保持一致
            tasks_to_remove = []

            for task_id, task in self._tasks.items():
                if task.status == TaskStatus.COMPLETED and task.completed_at:
                    age = (now - task.completed_at).total_seconds()
                    if age > age_seconds:
                        tasks_to_remove.append(task_id)

            # 【性能优化】使用 dict.pop() 代替 del + list.remove()，O(1) 操作
            for task_id in tasks_to_remove:
                self._tasks.pop(task_id, None)

            if tasks_to_remove:
                logger.info(
                    f"清理了 {len(tasks_to_remove)} 个已完成任务: {tasks_to_remove}"
                )

            return len(tasks_to_remove)

    def cleanup_completed_tasks_throttled(
        self, age_seconds: int = 10, throttle_seconds: float = 30.0
    ) -> int:
        """节流版 cleanup —— 用于 hot path（如 GET /api/tasks）的兜底调用。

        与未节流的 ``cleanup_completed_tasks`` 行为一致，但**距离上次执行
        不足 ``throttle_seconds`` 时直接返回 0**（不加 ``self._lock``）。

        why
        ---
        历史上 ``GET /api/tasks`` 在每次请求都会调用一次未节流 cleanup，配合
        前端 2s 轮询 + 后台清理线程的 5s 节奏，导致 cleanup 调用频率被 hot
        path 放大到后台节奏的 ~5-10x。每次 cleanup 都要：

        1. ``acquire(self._lock)`` — 与 ``add_task`` / ``complete_task`` /
           ``get_all_tasks`` 共用同一把粗粒度锁，hot-path 命中会增加 lock
           contention（虽然单次 critical section ~5µs，但乘以高频后非零）；
        2. ``datetime.now(UTC)`` — Python 层的 syscall + tz 处理；
        3. 遍历 ``self._tasks`` (O(n))，即使没有任何任务到期。

        本方法把 hot-path 的真实 cleanup 频率封顶到 ``1 / throttle_seconds``，
        与后台 5s 主节奏正交叠加，cleanup 总频率从 ``polls/s + 1/5`` 降为
        ``1/30 + 1/5 ≈ 0.23/s``，且 99% 的请求在快路径（非锁的原子读写
        + 一次时间戳比较）上完成。

        参数
        ----
        age_seconds : int, default 10
            任务完成后保留的秒数，与未节流版本一致。
        throttle_seconds : float, default 30.0
            节流窗口长度。设为 0 时退化为未节流行为（不推荐，仅用于测试）。

        返回
        ----
        int
            清理的任务数量；节流命中或队列空时返回 0。

        线程安全
        --------
        ``self._hotpath_cleanup_lock`` 仅保护 ``_last_hotpath_cleanup_monotonic``
        的读写，**不**与 ``self._lock`` 嵌套（cleanup 真正执行时先释放
        ``_hotpath_cleanup_lock`` 再调用未节流版本）。所以本方法对常规
        ``add_task`` / ``complete_task`` 路径零阻塞影响。

        副作用
        ------
        - 节流未触发时：可能删除过期 completed 任务（同 cleanup_completed_tasks）。
        - 节流触发时：仅一次 ``time.monotonic()`` 调用。

        时间复杂度
        ----------
        - 节流触发（fast path）：O(1)
        - 节流未触发：O(n)，n = len(self._tasks)

        历史背景
        --------
        本节流策略由 R20.5 引入；触发原因是审计 v1.5.25 后的 hot path 时
        发现 ``GET /api/tasks`` 在多 client 并发场景下的冗余 cleanup 调用。
        """
        now = time.monotonic()

        # Fast path：仅持 hotpath cleanup lock，做时间戳判断。
        # 节流触发时（绝大多数请求）直接返回，不接触 self._lock 与 _tasks。
        with self._hotpath_cleanup_lock:
            elapsed = now - self._last_hotpath_cleanup_monotonic
            if elapsed < throttle_seconds:
                return 0
            # 立即更新时间戳，避免并发 hot-path 同时通过节流（thundering herd）。
            # why monotonic：避免系统时间被 NTP / 用户手动调整后，节流窗口
            # 出现"负 elapsed"导致永远阻塞或"巨大 elapsed"导致频繁穿透。
            self._last_hotpath_cleanup_monotonic = now

        # Slow path：真实 cleanup。在 _hotpath_cleanup_lock 释放后调用，
        # 避免与 self._lock 形成嵌套锁（防死锁）。
        return self.cleanup_completed_tasks(age_seconds=age_seconds)

    def _cleanup_loop(self):
        """后台清理循环（守护线程入口）

        后台线程的主循环，定期清理过期的已完成任务。

        **执行逻辑**：
        1. 每5秒检查一次
        2. 调用 cleanup_completed_tasks(age_seconds=10)
        3. 捕获并记录所有异常
        4. 收到停止信号时退出

        **线程特性**：
        - 守护线程（daemon=True）
        - 应用退出时自动停止
        - 异常不会导致线程崩溃

        **停止方式**：
        - 调用 stop_cleanup() 方法
        - _stop_cleanup.set() 设置停止事件
        - wait(timeout=5) 返回True时退出

        线程安全:
            cleanup_completed_tasks 内部使用Lock保护

        副作用:
            - 定期删除过期任务
            - 记录启动和停止日志
            - 记录清理日志（debug级别）
            - 记录异常日志（error级别）

        说明:
            - 不应直接调用此方法（由__init__自动启动）
            - 线程名称：TaskQueueCleanup
            - 异常不会中断循环
            - 清理间隔：5秒
            - 保留时间：10秒
        """
        logger.info("后台清理线程启动")
        while not self._stop_cleanup.wait(timeout=5):
            try:
                cleaned = self.cleanup_completed_tasks(age_seconds=10)
                if cleaned > 0:
                    logger.debug(f"后台清理线程清理了 {cleaned} 个任务")
            except Exception as e:
                logger.error(f"后台清理线程异常: {e}", exc_info=True)
        logger.info("后台清理线程已停止")

    def stop_cleanup(self) -> None:
        """停止后台清理线程

        优雅地停止后台清理线程，应在应用关闭时调用。

        **停止流程**：
        1. 设置停止事件 (_stop_cleanup.set())
        2. 等待线程结束（最多2秒）
        3. 检查线程是否成功停止
        4. 记录停止状态

        **超时处理**：
        - 如果2秒内未停止，记录警告日志
        - 线程可能仍在运行（极少见）
        - 由于是守护线程，应用退出时会强制停止

        线程安全:
            线程安全（使用Event同步）

        副作用:
            - 设置停止事件
            - 阻塞最多2秒等待线程
            - 记录日志

        说明:
            - 必须在应用关闭时调用
            - 不调用可能导致日志未正确flush
            - 守护线程会在主线程退出时强制停止
            - 多次调用是安全的（幂等操作）
        """
        logger.info("正在停止后台清理线程...")
        self._stop_cleanup.set()
        if self._cleanup_thread.is_alive():
            self._cleanup_thread.join(timeout=2)
            if self._cleanup_thread.is_alive():
                logger.warning("后台清理线程未能在2秒内停止")
            else:
                logger.info("后台清理线程已成功停止")

    def get_task_count(self) -> dict[str, int]:
        """获取任务统计信息

        返回各状态任务的数量统计。

        **统计字段**：
        - `total`: 总任务数（所有状态）
        - `pending`: 等待处理的任务数
        - `active`: 活动任务数（应该是0或1）
        - `completed`: 已完成但未删除的任务数
        - `max`: 队列最大容量

        **使用场景**：
        - 监控队列状态
        - 检查队列是否已满
        - 统计任务处理进度
        - 调试和日志

        返回:
            dict[str, int]: 任务统计字典
                键值对：
                - 'total': int - 总任务数
                - 'pending': int - 等待任务数
                - 'active': int - 活动任务数（0或1）
                - 'completed': int - 已完成任务数
                - 'max': int - 最大容量

        线程安全:
            线程安全（使用 Lock 保护）

        时间复杂度:
            O(n) - 需要遍历所有任务计数

        说明:
            - 返回的是新字典，可以安全修改
            - active数量应该是0或1（单活动任务模式）
            - total = pending + active + completed
            - completed任务会在10秒后被清理
        """
        with self._lock.read_lock():
            counts: dict[str, int] = {
                TaskStatus.PENDING: 0,
                TaskStatus.ACTIVE: 0,
                TaskStatus.COMPLETED: 0,
            }
            for t in self._tasks.values():
                if t.status in counts:
                    counts[t.status] += 1
            return {"total": len(self._tasks), **counts, "max": self.max_tasks}

    # ========================================================================
    # 任务状态变更回调机制
    # ========================================================================

    def register_status_change_callback(
        self, callback: Callable[[str, str | None, str], None]
    ) -> None:
        """
        注册任务状态变更回调函数

        【功能说明】
        当任务状态发生变化时（添加、激活、完成、删除），会调用所有注册的回调函数。

        【参数】
        callback : callable
            回调函数，接受三个参数：
            - task_id: str - 任务ID
            - old_status: str - 旧状态（添加任务时为 None）
            - new_status: str - 新状态（删除任务时为 "removed"）

            函数签名: def callback(task_id: str, old_status: str, new_status: str) -> None

        【使用场景】
        - 前端实时更新任务列表
        - 日志记录任务状态变化
        - 触发相关业务逻辑

        【示例】
        >>> def on_status_change(task_id, old_status, new_status):
        ...     print(f"任务 {task_id}: {old_status} -> {new_status}")
        >>> queue.register_status_change_callback(on_status_change)
        """
        with self._callbacks_lock:
            if callback not in self._status_change_callbacks:
                self._status_change_callbacks.append(callback)
                cb_name = getattr(callback, "__name__", None) or repr(callback)
                logger.debug(f"已注册任务状态变更回调: {cb_name}")

    def unregister_status_change_callback(
        self, callback: Callable[[str, str | None, str], None]
    ) -> None:
        """
        取消注册任务状态变更回调函数

        【参数】
        callback : callable
            要取消的回调函数
        """
        with self._callbacks_lock:
            if callback in self._status_change_callbacks:
                self._status_change_callbacks.remove(callback)
                cb_name = getattr(callback, "__name__", None) or repr(callback)
                logger.debug(f"已取消任务状态变更回调: {cb_name}")

    def _trigger_status_change(
        self, task_id: str, old_status: str | None, new_status: str
    ):
        """
        触发任务状态变更回调

        【内部方法】
        任务状态变化时调用，依次执行所有注册的回调函数。

        【参数】
        task_id : str
            任务ID
        old_status : str | None
            旧状态（添加任务时为 None）
        new_status : str
            新状态（删除任务时为 "removed"）

        【注意】
        - 回调函数中的异常会被捕获，不会影响其他回调
        - 回调执行在调用线程中，建议保持回调函数简短
        """
        with self._callbacks_lock:
            callbacks = list(self._status_change_callbacks)

        for callback in callbacks:
            try:
                callback(task_id, old_status, new_status)
            except Exception as e:
                cb_name = getattr(callback, "__name__", None) or repr(callback)
                logger.error(
                    f"任务状态变更回调执行失败 ({cb_name}): {e}", exc_info=True
                )

    # ========================================================================
    # 持久化（JSON 原子写入）
    # ========================================================================

    def _persist(self) -> None:
        """将当前任务快照写入磁盘（原子操作：tmpfile → fsync → os.replace）。

        仅在 persist_path 已设置时执行。已完成的任务不写入持久化文件。
        调用方应在锁外调用此方法。

        why fsync：
            ``os.replace(tmp, target)`` 本身是 ``rename(2)`` 系统调用，inode
            层面是原子的，但**目标 inode 指向的数据**在 ``rename`` 时可能
            还停留在 OS page cache 没刷盘。如果机器在 ``replace`` 之后
            ``fsync`` 之前 panic / 断电：
              1. 重启后磁盘 inode 已经指向新文件名
              2. 但新文件实际数据从未落盘 → 上面是 0 字节 / NUL fill /
                 部分写入
              3. 旧文件已经被 ``rename`` 替换掉，无法回滚
            ``fsync`` 强制让 page cache 落盘后才允许 ``replace``，
            消除这个窗口。详见 ``Linux fsync(2) man-page``、
            ``danluu.com/file-consistency``、``Postgres fsyncgate`` 案例。

            本仓库其他 5 处原子写入路径
            （``config_manager._save_config_immediate``、
            ``config_modules/io_operations.py``、
            ``config_modules/network_security._atomic_write_config``、
            ``scripts/bump_version.py``）都已经按
            ``flush() → fsync(fileno()) → os.replace()`` 序列写，本函数
            因为历史原因漏了——补上以保持仓库内的一致性。
        """
        if not self._persist_path:
            return
        try:
            with self._lock.read_lock():
                snapshot = []
                for task in self._tasks.values():
                    if task.status == TaskStatus.COMPLETED:
                        continue
                    snapshot.append(
                        {
                            "task_id": task.task_id,
                            "prompt": task.prompt,
                            "predefined_options": task.predefined_options,
                            "predefined_options_defaults": task.predefined_options_defaults,
                            "auto_resubmit_timeout": task.auto_resubmit_timeout,
                            "created_at": task.created_at.isoformat(),
                            "status": task.status,
                            "feedback_placeholder": task.feedback_placeholder,
                            "question_type": task.question_type,
                        }
                    )
                active_id = self._active_task_id

            data = {
                "version": 1,
                "active_task_id": active_id,
                "tasks": snapshot,
                "saved_at": datetime.now(UTC).isoformat(),
            }

            fd, tmp_path = tempfile.mkstemp(
                dir=str(self._persist_path.parent),
                prefix=".tasks_",
                suffix=".tmp",
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                    # flush() 把 stdio buffer 推到内核；fsync(fileno()) 才
                    # 把内核 page cache 推到磁盘——两步缺一不可。flush 单独
                    # 不够（缓存仍在 page cache）；fsync 单独可能漏写当前
                    # buffer 里没 flush 的部分。
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_path, str(self._persist_path))
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise

            logger.debug(f"任务快照已持久化: {len(snapshot)} 个任务")
        except Exception as e:
            logger.warning(f"任务持久化失败（不影响运行）: {e}", exc_info=True)

    def _restore(self) -> None:
        """从磁盘恢复未完成的任务。仅在初始化时调用一次。

        恢复逻辑：
        - 跳过已完成的任务
        - 重建 created_at_monotonic 以保证剩余时间计算正确
        - 已超时的任务标记为 pending 但保留（让前端处理自动提交）

        损坏文件 quarantine（R17.8）
        ----------------------------
        当顶层 ``json.loads`` / ``read_text`` / 顶层结构解析失败时，
        把损坏文件**重命名**为 ``<persist_path>.corrupt-<ISO 时间戳>``
        而非默认覆盖。理由：

        1. ``_persist`` 用 ``tempfile.mkstemp + os.replace`` 原子写，
           会**完全覆盖**原 target —— 用户重启后第一次 ``add_task``
           触发 ``_persist`` 就会让损坏证据永久消失，运维**完全无法**
           inspect 当时的文件状态。
        2. quarantine 后的文件留在原目录，文件名带时间戳避免互相覆盖；
           运维可以 ``ls *.corrupt-*`` 一眼看到所有历史损坏快照，配合
           ``hexdump`` / ``json.tool`` 做断电诊断。
        3. quarantine 失败（磁盘满 / 权限不够）也只是 logger.warning
           降级，不阻断 ``_restore`` 的"使用空队列"兜底，绝不抛异常给
           上层 ``__init__``。
        """
        if not self._persist_path or not self._persist_path.exists():
            return
        try:
            raw = self._persist_path.read_text(encoding="utf-8")
            if not raw.strip():
                return
            data = json.loads(raw)
            if not isinstance(data, dict) or data.get("version") != 1:
                logger.warning("持久化文件版本不匹配，忽略")
                return

            saved_at_str = data.get("saved_at")
            saved_at = (
                datetime.fromisoformat(saved_at_str)
                if saved_at_str
                else datetime.now(UTC)
            )
            elapsed_since_save = (datetime.now(UTC) - saved_at).total_seconds()

            restored = 0
            skipped = 0
            for item in data.get("tasks", []):
                if not isinstance(item, dict):
                    skipped += 1
                    continue
                task_id = item.get("task_id")
                prompt = item.get("prompt")
                if not task_id or not prompt:
                    skipped += 1
                    continue
                status = item.get("status", TaskStatus.PENDING)
                if status == TaskStatus.COMPLETED:
                    continue

                # 【P6Y-1 修复】per-task 独立 try-except：
                # 单个任务的 created_at 解析失败、Pydantic 校验失败、
                # 或 auto_resubmit_timeout 为非法类型时，仅丢弃该任务并继续恢复其他任务，
                # 避免整个持久化文件因一条损坏记录而完全失效。
                try:
                    created_at = datetime.fromisoformat(item["created_at"])
                    age_since_creation = (
                        datetime.now(UTC) - created_at
                    ).total_seconds()

                    # mining-cycle-3 §2.1 borrow #3: 持久化恢复时也要回灌
                    # placeholder。旧版 snapshot 不存在该 key，``item.get``
                    # 返回 None，等价于 "use i18n default"，符合 backward
                    # compatibility 预期。
                    restored_placeholder = item.get("feedback_placeholder")
                    if isinstance(restored_placeholder, str):
                        s = restored_placeholder.strip()
                        restored_placeholder = s[:PLACEHOLDER_MAX_LENGTH] if s else None
                    else:
                        restored_placeholder = None

                    # mining-cycle-3 §2.1 borrow #2: question_type round-trip
                    restored_qt = item.get("question_type")
                    if isinstance(restored_qt, str) and restored_qt.strip() == "yesno":
                        restored_qt = "yesno"
                    else:
                        restored_qt = None

                    task = Task(
                        task_id=task_id,
                        prompt=prompt,
                        predefined_options=item.get("predefined_options"),
                        predefined_options_defaults=item.get(
                            "predefined_options_defaults"
                        ),
                        auto_resubmit_timeout=item.get("auto_resubmit_timeout", 240),
                        created_at=created_at,
                        created_at_monotonic=time.monotonic() - age_since_creation,
                        status=TaskStatus.PENDING,
                        feedback_placeholder=restored_placeholder,
                        question_type=restored_qt,
                    )
                except Exception as task_err:
                    skipped += 1
                    logger.warning(
                        f"恢复单个任务失败（跳过）: task_id={task_id!r} err={task_err}"
                    )
                    continue

                self._tasks[task_id] = task
                restored += 1

            active_id = data.get("active_task_id")
            if active_id and active_id in self._tasks:
                self._active_task_id = active_id
                self._tasks[active_id].status = TaskStatus.ACTIVE
            elif self._tasks:
                first_id = next(iter(self._tasks))
                self._active_task_id = first_id
                self._tasks[first_id].status = TaskStatus.ACTIVE

            if restored > 0:
                logger.info(
                    f"从持久化文件恢复了 {restored} 个未完成任务"
                    f"（文件保存于 {elapsed_since_save:.0f}s 前"
                    f"{f'，跳过 {skipped} 个损坏项' if skipped else ''}）"
                )
            elif skipped > 0:
                logger.warning(f"持久化文件中所有 {skipped} 个任务均损坏，已跳过")
        except Exception as e:
            logger.warning(f"任务恢复失败（将使用空队列）: {e}", exc_info=True)
            self._quarantine_corrupt_persist_file(reason=str(e))

    def _quarantine_corrupt_persist_file(self, *, reason: str) -> None:
        """把损坏的 persist 文件重命名为 ``<path>.corrupt-<ISO>``，避免被
        下次 ``_persist`` 的 ``os.replace`` 静默覆盖。

        ``ISO`` 时间戳采用 ``YYYYMMDDTHHMMSSZ`` 紧凑格式（移除冒号 / 微秒，
        因 Windows 文件名禁止冒号）。这样运维 ``ls *.corrupt-*`` 一眼能看到
        所有历史损坏快照，按时间排序也是文件名字典序排序。

        本函数本身严格容错：rename 失败（磁盘满 / 权限 / target 已被占用）
        都吞 OSError 并 logger.warning，绝不向 ``_restore`` 抛异常。
        """
        if not self._persist_path or not self._persist_path.exists():
            return
        try:
            ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            corrupt_path = self._persist_path.with_name(
                f"{self._persist_path.name}.corrupt-{ts}"
            )
            os.replace(str(self._persist_path), str(corrupt_path))
            logger.warning(
                "已将损坏的持久化文件 quarantine 至 "
                f"{corrupt_path.name}（原因: {reason}）；"
                "运维可保留该文件用于断电 / fsync 异常诊断，"
                "或手动删除"
            )
        except OSError as quarantine_err:
            # rename 失败也只是 best-effort，吞掉以保留 _restore 的"用空
            # 队列继续运行"语义。最坏情况下下次 _persist 会原子覆盖原文件。
            logger.warning(
                f"quarantine 损坏持久化文件失败（best-effort 已忽略）: {quarantine_err}"
            )
