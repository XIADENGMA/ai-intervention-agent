# notification_manager

> 英文 signature-only 版本（仅函数 / 类签名速查）：[`docs/api/notification_manager.md`](../api/notification_manager.md)

通知管理器模块 - 统一管理 Web/声音/Bark/系统多渠道通知。

采用单例模式，支持插件化提供者注册、事件队列、失败降级。线程安全。

## 函数

### `_get_inflight_file_dir() -> Path | None`

R136 — 解析 in-flight 持久化文件所在目录。

优先复用 ``config_manager.get_config()`` 已经解析好的 config 文件路
径的 ``parent``——保证持久化文件与 config 文件同位（典型为
``~/.config/ai-intervention-agent/`` on Linux 或
``~/Library/Application Support/ai-intervention-agent/`` on macOS）。

若 config 模块不可用（e.g. 单元测试隔离场景），返回 ``None``——
callers 应当跳过持久化路径，避免污染 cwd。

### `_shutdown_global_notification_manager()`

## 类

### `class NotificationConfig`

通知配置类 - 全局开关/Web/声音/触发时机/重试/移动优化/Bark 等配置。

#### 方法

##### `clamp_sound_volume(cls, v: float) -> float`

##### `coerce_retry_count(cls, v: Any) -> int`

##### `coerce_retry_delay(cls, v: Any) -> int`

##### `coerce_bark_timeout(cls, v: Any) -> int`

##### `validate_bark_action(cls, v: str) -> str`

##### `warn_bark_config(self) -> 'NotificationConfig'`

##### `from_config_file(cls) -> 'NotificationConfig'`

从配置文件 notification 段加载配置，sound_volume 自动转换 0-100 到 0.0-1.0

注意：get_section() 已通过 Pydantic 段模型（NotificationSectionConfig）完成
类型强转（SafeBool/ClampedInt）和范围钳位，此处无需再做手工转换。

### `class NotificationManager`

通知管理器（单例）- 管理提供者注册、事件队列、配置和回调，线程安全。

#### 方法

##### `__init__(self)`

初始化配置、提供者字典、事件队列、线程池和回调

##### `reset_for_testing(self) -> None`

R323 (cycle-34 #B2) · **Test-only**: 重置 singleton instance state
以实现跨测试隔离 (与 R319 ``_create_test_instance()`` 互补)。

**为什么需要两个 helper?**

- **R319 ``_create_test_instance()``** (classmethod): 创建一个**新**
  的 fresh instance, **不操作** singleton ``_instance``。适合需要
  完全独立 instance 的测试 (e.g. R145, 测 streak 累加逻辑)
- **R323 ``reset_for_testing()``** (instance method, 本方法): 重置
  ``notification_manager`` singleton 自身的 state, 让所有从
  ``from ai_intervention_agent.notification_manager import
  notification_manager`` 拿到 singleton 的代码 (e.g. ``web_ui_routes``
  的多个 route handler) 在每个测试开始时看到 fresh state, 不被前一
  个测试污染

**R323 重置范围**:

- state dicts: ``_stats`` (含完整 schema) / ``_providers`` /
  ``_callbacks`` / ``_delayed_timers`` /
  ``_provider_latency_histograms`` / ``_finalized_event_ids`` /
  ``_event_queue``
- inflight: ``_inflight_persisted_ids`` /
  ``_inflight_seen_at_startup``

**R323 不重置** (保留 singleton 完整性):

- ``config`` (由 ConfigManager 控制, conftest.py 已有 reload 逻辑)
- ``_initialized`` (避免触发 ``__init__`` 重新跑 config load)
- ``_executor`` / ``_worker_thread`` / ``_stop_event`` (由 shutdown
  / restart 处理, R323 不参与 lifecycle)
- lock instances 本身 (``_stats_lock`` 等不替换, 因为正在被并发持
  有的 lock 不能换掉, 只能让锁内 state 被覆盖)

**conftest.py 自动调用 (R323 同 commit)**:
``_isolate_config_and_notification_singletons`` fixture 在每个测试
前后都会调用 ``notification_manager.reset_for_testing()``, 让默认行
为是 "singleton 跨测试隔离全自动化"。测试方不需要主动调用, 也不
需要在 setUp 维护一长串 reset 代码。

**Pattern lineage (test-isolation, v3.8)**:

- 1st app: R316 (cycle-33 #A1) — R145 setUp 显式补充缺失 attr (单
  点修复, "止血")
- 2nd app: R319 (cycle-33 #A2) — ``_create_test_instance()`` class
  method (集中化 helper for fresh instance, "升级")
- **3rd app: R323 (本 commit, cycle-34 #B2)** — ``reset_for_testing()``
  instance method + conftest fixture 自动调用 (singleton 跨测试隔
  离自动化, "全覆盖")

到 R323 cycle-34 #B2, **v3.8 test-isolation pattern 完全工业化** (3
app), 是 v3.8 第 2 个全工业化 pattern (与 R322 idempotent 同 cycle
达到全工业化).

##### `register_provider(self, notification_type: NotificationType, provider: Any) -> None`

注册通知提供者（需实现 send(event) -> bool）

##### `get_provider_latency_histograms_snapshot(self) -> dict[str, dict[str, Any]]`

返回 provider latency histogram 快照（深 copy）。

形态与 ``mcp_tool_call_metrics.get_mcp_tool_call_latency_snapshot``
对齐——``buckets`` 字典自动附加 ``float("inf")`` 键，值 == count。
若某 provider 还从未发送过，**不**出现在返回字典里。

返回值是新建 dict，调用者修改不会污染内部状态。

##### `add_callback(self, event_name: str, callback: Callable) -> None`

添加事件回调（如 notification_sent, notification_fallback）

##### `trigger_callbacks(self, event_name: str) -> None`

触发指定事件的所有回调，异常不中断后续回调

##### `send_notification(self, title: str, message: str, trigger: NotificationTrigger = NotificationTrigger.IMMEDIATE, types: list[NotificationType] | None = None, metadata: dict[str, Any] | None = None, priority: NotificationPriority | str = NotificationPriority.NORMAL) -> str`

发送通知主入口，返回事件ID。types=None 时根据配置自动选择渠道。

##### `shutdown(self, wait: bool = False, grace_period: float = 0.0) -> None`

关闭管理器，取消延迟 Timer 并关闭线程池（幂等）。

参数：
    wait: ``True`` 时阻塞直到全部 worker 完成（与
        ``ThreadPoolExecutor.shutdown(wait=True)`` 同语义）；
        ``False`` 时仅取消 pending future、不等 in-flight。
    grace_period: ``wait=False`` 时的额外宽限窗口（秒）。
        取值 ``> 0`` 表示：在 ``shutdown`` 调用线程上 best-effort
        ``join`` 每个 worker 线程，最多累计 ``grace_period`` 秒，
        让正在跑的 osascript / HTTP 通知有机会自然收尾，避免
        ``atexit`` 阶段 in-flight 被切断后才意识到（log 已经
        关、进程已经在 cleanup）。**不**会让 ``shutdown`` 等到
        超过 ``grace_period``——超时则直接 return，worker 继续
        由 Python 主进程退出阶段去 join 收尾（worker 默认
        non-daemon）。

Why grace_period 而不是直接 ``daemon=True``:
    把 worker 标 daemon 需要子类化 ``ThreadPoolExecutor`` 重写
    ``_adjust_thread_count``（私有 API，跨 Python 版本不稳）。
    grace_period 路径只读 ``_threads`` 集合（私有但仅遍历），
    不修改 ``ThreadPoolExecutor`` 行为，最低耦合。

    行业参考：Pgsql / etcd / aiohttp 在退出阶段都给 worker
    一段固定 grace（典型 1-3s），平衡"通知应当尽量送达"与
    "用户不该看到程序挂起"两个目标。

##### `restart(self) -> None`

shutdown 后重建线程池

##### `get_config(self) -> NotificationConfig`

返回当前配置对象引用

##### `refresh_config_from_file(self, force: bool = False) -> None`

从配置文件刷新配置（mtime 缓存优化，force=True 强制刷新）

##### `update_config(self) -> None`

更新配置并持久化到文件

##### `update_config_without_save(self) -> None`

仅内存更新配置，不写文件。bark_enabled 变化时自动更新提供者。

##### `get_status(self) -> dict[str, Any]`

返回管理器状态：enabled/providers/queue_size/config/stats。

R136：``status`` 增加两个字段：
- ``inflight_persisted_count``：当前进程持久化集合中的 inflight
  事件数（与磁盘文件 events 列表长度一致，未过 TTL）。
- ``inflight_seen_at_startup``：本次进程启动时一次性 load 的
  上次进程退出时还在 in-flight 的事件元数据列表（list[dict]，
  每项 = 序列化的 NotificationEvent + ``saved_at_ts``）。该字
  段仅"暴露给 stats"，进程不会自动重发——避免重启后用户被旧
  通知刷屏；运维 / dashboard 可基于此发出 alarm。
