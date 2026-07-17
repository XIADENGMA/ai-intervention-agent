# enhanced_logging

> 英文 signature-only 版本（仅函数 / 类签名速查）：[`docs/api/enhanced_logging.md`](../api/enhanced_logging.md)

增强日志模块 - 基于 Loguru，提供脱敏、防注入、去重，全部输出到 stderr（MCP 友好）。

## 函数

### `_sanitize_and_escape(record: dict[str, Any]) -> None`

Loguru patcher: 防注入转义 + 敏感信息脱敏

### `_is_root_intercept_handler(handler: logging.Handler) -> bool`

Return whether *handler* is this module's root logging bridge.

``importlib.reload()`` recreates ``InterceptHandler``. Existing handler
instances from the previous module execution are still valid bridges, but
they no longer satisfy ``isinstance(handler, InterceptHandler)`` for the
newly created class. A stable marker keeps root installation idempotent
across reloads and xdist worker ordering.

### `_install_root_intercept_once() -> None`

R72-A：在 root logger 上 idempotently 安装一份 ``InterceptHandler``。

目的
----

项目里一部分模块（``task_queue``、``config_manager``、``file_validator``、
``i18n``、``config_utils``）用的是 ``logging.getLogger(__name__)`` 而不是
走 ``EnhancedLogger`` / ``SingletonLogManager.setup_logger``。它们的
``logger.propagate`` 默认是 True，会冒泡到 root logger。如果 root 没装
handler，stdlib ``logging.lastResort`` 会把这些消息原样吐到 stderr，
**绕过 Loguru 的 ``_sanitize_and_escape`` patcher**。

后果是 CodeQL ``py/log-injection`` 在 ``task_queue.add_task`` 等位置上
报警是技术上正确的——一个能注入 ``\n`` 到 ``task_id`` 的攻击者就能伪造
log 行。

修复方案是在 root logger 上挂一份 ``InterceptHandler``，把所有未显式
设置 handler 的 stdlib logger 全部桥接进 Loguru，统一享受
``_sanitize_and_escape``（CRLF / null byte 转义）+ ``_global_sanitizer``
（PII 脱敏）。

幂等性
------

用 ``_is_root_intercept_handler(h)`` 检测已存在的 handler，避免重复
安装。这对测试场景特别重要：``pytest`` 可能多次 import/reload 模块，
而 ``logging`` root 是进程级单例。

与 ``SingletonLogManager.setup_logger`` 的关系
-------------------------------------------------

``setup_logger`` 装的 handler 是在 *named* logger 上，且明确把
``propagate`` 设为 False；root 的 handler 不会跟 named logger 重复
输出。两条路径独立、不串。

### `get_log_level_from_config() -> int`

从环境变量 / 配置文件读取日志级别。

解析顺序（first match wins）：

1. **环境变量** ``AI_INTERVENTION_AGENT_LOG_LEVEL``——standalone server
   场景下最常见的诊断入口。``docs/troubleshooting.md`` /
   ``.github/SUPPORT.md`` 自 v1.5 起就向用户公开承诺这个 env var
   存在，但 R92 之前实际没接入；R93 把契约真兑现到代码层。env var
   不区分大小写，无效值会回退到 config 解析路径并打 warning。
2. **配置文件** ``[web_ui].log_level``。
3. **默认值** ``WARNING``。

### `configure_logging_from_config() -> None`

根据配置设置 root logger 和所有 handler 的级别

### `get_current_log_level() -> dict[str, str | list[str]]`

返回当前运行时日志级别快照（root + ai_intervention_agent 命名空间）。

给 ``GET /api/system/log-level`` 端点 + 测试断言用。

返回字段：

- ``root_level``：``logging.getLogger()`` 当前 effective level 名（如
  ``"INFO"`` / ``"WARNING"``）。
- ``aiia_level``：``ai_intervention_agent`` 命名空间当前 effective
  level 名——子 logger 如果没显式 setLevel，会继承 root 的 effective
  level（``logging.NOTSET`` 时向上查找）。
- ``valid_levels``：5 个允许值供 client UI 渲染下拉菜单。

设计：返回字典字段都是字符串（不返回 int），让 JSON 序列化结果对
人类直接可读，不需要 client 自己 reverse-lookup logging.getLevelName。

### `apply_runtime_log_level(level: str) -> dict[str, str]`

运行时把 root logger + 所有 handler 的级别切到 ``level``。

用途
----
R188 / T3 ``POST /api/system/log-level`` 端点的核心 helper——让运维
在不重启 server 的情况下：

* 调高 level → 临时调试某次反馈或某个 bug，``DEBUG`` 把 SSE / queue /
  notification 全开；
* 调低 level → 排查完后立刻关回 ``WARNING``，避免 stderr 爆量；
* 与 ``AI_INTERVENTION_AGENT_LOG_LEVEL`` env var 的关系：env var 控制
  **下次启动**，本 API 控制**当前进程**。两者不互相覆盖；env var 在
  下次 ``main()`` 入口生效。

设计约束
--------
- **只接受 5 个 enum 值**：``DEBUG`` / ``INFO`` / ``WARNING`` /
  ``ERROR`` / ``CRITICAL``（大小写不敏感）。其他值 raise ``ValueError``，
  handler 转 400 给 client；
- **只改 root logger + handler**：不接受任意 logger 名参数——攻击面
  最小，避免远程把 ``zeroconf`` / ``httpx`` 调成 DEBUG 让日志爆量；
- **失败原子化**：先验证 level 合法再 setLevel，validation 失败时不
  留半改半未改的状态；
- **不持久化**：只改运行时；下次启动仍走 env var / config 路径。这是
  故意的——运行时旋钮不应该意外覆盖 config，避免运维忘记关回去。

参数
----
``level``：``DEBUG`` / ``INFO`` / ``WARNING`` / ``ERROR`` /
``CRITICAL`` 之一，大小写不敏感。

返回
----
``{"old_level": str, "new_level": str, "logger": "root"}`` —— 三个
字段都用 string level name（``logging.getLevelName(...)``）便于 JSON
序列化。

异常
----
``ValueError``：``level`` 不在 ``VALID_LOG_LEVELS`` 内。

### `_record_to_ring(level_no: int, name: str, message: str) -> None`

把一条日志推入 ring buffer，自带 level 过滤 + 脱敏 + 长度截断。

``level_no`` < ``logging.WARNING`` 的日志直接丢弃（hot path 上的 INFO/DEBUG
数量级远高，进 buffer 没意义）。

### `get_recent_logs(limit: int | None = None) -> list[dict[str, Any]]`

返回最近 N 条 WARNING/ERROR 日志，按时间正序（旧 → 新）。

``limit=None`` 返回全部 buffer 内容（最多 ``_LOG_RING_MAXLEN`` 条）。
返回的是 dict 的浅拷贝列表 —— 修改返回值不会污染 buffer。

### `get_recent_error_stats(cutoff_ts_unix: float) -> tuple[int, int]`

Return ``(error_count, buffer_total)`` for entries newer than ``cutoff``.

Metrics and health probes only need an aggregate over the warning/error ring.
Scanning the deque directly avoids allocating a full ``list(_log_ring)`` on
every scrape while keeping the entry-returning API available for callers
that need full log records.

### `clear_recent_logs() -> None`

清空 ring buffer，主要供测试 setUp 隔离用。

## 类

### `class LogSanitizer`

日志脱敏 - 检测并替换密码、API key 等敏感信息为 ``***REDACTED***``。

覆盖范围（R54-B 扩展，按高频泄漏 vendor 排序，每条都加注释说明锚点）：

1. **通用字段写法**：``password=`` / ``passwd=`` / ``secret_key=`` /
   ``private_key=``。这是最常见的 .env / config 文件 / debug 日志格式。
2. **OpenAI 系列**：
   - 老格式：``sk-XXX``（dash 后续无 dash）；
   - 新工程级 key：``sk-proj-XXX``（dash 后含 dash，`_-` 字符集 / 40+ 字符）；
   - Anthropic：``sk-ant-XXX``（同上）；
   共用一个能把 dash 也吃进 character class 的 regex，避免老 regex 在
   ``sk-proj-...`` 处只 match 到 ``sk-proj`` 4 个字符就失配。
3. **GitHub** 系列：``ghp_`` (PAT) / ``ghs_`` (server) / ``gho_`` (oauth) /
   ``ghu_`` (user-to-server) / ``ghr_`` (refresh)，全部 36 字符。
   **R111** 起补 fine-grained PAT (``github_pat_<11+82 chars>``)，2022 起
   GitHub 主推格式且成为新建 token 的默认形态，比经典 ``ghp_`` 更常见
   但 R54-B 当时未覆盖，导致 fine-grained PAT 黏到日志会**明文进
   stderr** —— MCP 客户端可见，高严重 PII 漏脱敏。
4. **Slack**：``xoxb-`` (bot) / ``xoxp-`` (user)。
5. **AWS**：``AKIA[A-Z0-9]{16}``（Access Key ID，固定 20 字符）。
6. **Google API**：``AIza[0-9A-Za-z_-]{35}``（39 字符总长）。
7. **HuggingFace**：``hf_[A-Za-z0-9]{34,}``。
8. **Stripe**：``sk_live_`` / ``sk_test_`` / ``pk_live_`` / ``pk_test_``，
   通常 24+ 字符。
9. **URL basic auth**：``http(s)://user:password@host`` 中的密码段——
   人类经常无意把整条 URL 黏到日志里。
10. **JWT**（保守判定）：必须 ``eyJ`` 开头 + 三段 base64url——避免误伤
    普通 base64 字符串。

#### 方法

##### `__init__(self) -> None`

##### `sanitize(self, message: str) -> str`

脱敏消息中的敏感信息。

URL basic auth 是唯一保留 username 的特殊形态，用反向引用把
``http(s)://``+username 部分留下，仅密码段替换为 ``***REDACTED***``，
让运维仍然能从日志里看到"是哪个账号在 leak"。其它形态全部一刀切替换。

### `class LogDeduplicator`

日志去重器 - 时间窗口内相同消息只记录一次，使用 hash() 高效判重。

【R13·B2】时间源刻意选 ``time.monotonic()`` 而不是 ``time.time()``：

- ``time.time()`` 是 wall clock，会被 NTP 同步、用户手工调时、夏令时
  切换、虚拟机暂停后恢复等改动；任何这些事件都可能让
  ``current_time - last_time`` 取到负数 / 跳大 / 跳小，让"过去 5 秒"
  的窗口语义错乱：
    * 系统时间被向前调 1h → 旧条目突然变成"1 小时后"，``> 5s`` →
      被判过期 → 接下来同样的 ERROR 又会输出（无所谓，安全方向）。
    * 系统时间被向后调 1h → 新消息进来时 ``current_time - last_time``
      是负数 → 永远 ``<= 5s`` → 旧条目永远去重 → 关键 ERROR 长时
      间被静默（**这是真正危险的方向**）。
- ``time.monotonic()`` 单调递增、不受 wall clock 影响，对"过去 X 秒"
  这种相对时间窗口是教科书级正确选择（Python 官方 ``timeit`` /
  ``asyncio`` 内部 timeout 都用它）。

由 ``tests/test_enhanced_logging.py::TestLogDeduplicatorMonotonic`` 锁
住此契约（reverse-lock：源码不能切回 ``time.time()`` 否则测试失败）。

#### 方法

##### `__init__(self, time_window: float = 5.0, max_cache_size: int = 1000) -> None`

初始化时间窗口和缓存

##### `should_log(self, message: str) -> tuple[bool, str | None]`

检查是否应记录，返回 (should_log, duplicate_info)

### `class InterceptHandler`

将 stdlib logging 路由到 Loguru（用于第三方库的 logging 输出）。

#### 方法

##### `emit(self, record: logging.LogRecord) -> None`

### `class SingletonLogManager`

单例日志管理器 - 配置 stdlib logger 路由到 Loguru，线程安全。

#### 方法

##### `setup_logger(self, name: str, level: int = logging.WARNING) -> logging.Logger`

返回已配置的 logger，首次调用时安装 InterceptHandler 路由到 Loguru

### `class EnhancedLogger`

增强日志记录器 - 基于 Loguru 输出，集成去重和级别映射，API 与原版兼容。

#### 方法

##### `__init__(self, name: str) -> None`

初始化 logger、去重器和级别映射

##### `log(self, level: int, message: str) -> None`

记录日志，带去重和级别映射

Fast path：在调用 ``deduplicator.should_log`` 之前先用底层 stdlib
``isEnabledFor`` 短路。``deduplicator`` 内部要 ``acquire(self.lock)``
+ ``hash(message)`` + cache 查表（可能触发懒清理），单次 ~1-3 µs；
但如果当前 effective level 已经被过滤，所有这些工作最终都会被丢弃。
WARNING 级别（默认）+ 高频 ``debug`` / ``info`` 调用场景下，原实现
每次 debug 调用都付出 dedup 锁竞争代价，但所有 debug 消息最终都会
被 stdlib 层过滤——典型的"先工作再判断"反模式。

why effective_level（不是 raw level）作为短路判断
------------------------------------------------
``_get_effective_level`` 会把"服务启动失败"等关键词从 caller 传入的
INFO/DEBUG 强制提升到 ERROR；反之"收到反馈请求"会从 INFO 降到 DEBUG。
因此 effective_level 可能比 raw level **更高或更低**，不能用 raw level
预判，必须先做 mapping 再短路。``_get_effective_level`` 自身只做字典
9-key 遍历 + 字符串 ``in`` 检查（~0.5 µs），远便宜过 dedup 路径。

副作用差异
----------
预过滤 debug 消息现在不再进入 ``deduplicator`` cache。这与用户预期
一致：从 WARNING 动态切到 DEBUG 后，第一条 debug 消息应当立即输出，
而不是被原本不会输出的"幽灵 cache 命中"沉默掉。

##### `setLevel(self, level: int) -> None`

兼容标准 logging.Logger API：设置底层 logger 的级别。

##### `debug(self, message: str) -> None`

##### `info(self, message: str) -> None`

##### `warning(self, message: str) -> None`

##### `error(self, message: str) -> None`

##### `event(self, name: str) -> None`

Emit a single grep-friendly event log line.

``name`` should be a stable dotted identifier (``task.created``,
``task.notified``, ``task.completed``, ``server.boot``, …). ``ctx``
is rendered as ``key=value`` pairs after the event name.
