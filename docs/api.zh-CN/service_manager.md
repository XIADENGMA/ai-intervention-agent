# service_manager

> 英文 signature-only 版本（仅函数 / 类签名速查）：[`docs/api/service_manager.md`](../api/service_manager.md)

Web 服务编排层 - 进程生命周期管理、HTTP 客户端、Web UI 启动与健康检查。

R25.2 性能注解：``httpx`` 的顶级导入被推迟到使用点
====================================================

``import httpx`` 在 macOS M1 / Python 3.11 上 cold-start 实测 ~55 ms（含 ``httpcore``
+ ``h11`` + ``rfc3986`` + ``anyio`` 整套传输层 + 状态机 + 异步 backend）。本模块在
MCP 主进程启动期就被 ``server.py`` 顶层 import，意味着这 55 ms 是**每个 MCP 进程冷
启动**都要付的固定代价——但 MCP 主进程在收到首个客户端请求前其实并不需要 httpx，所有
真正的 HTTP I/O 都发生在 ``interactive_feedback`` 工具被调用之后。

R25.2 把 ``import httpx`` 从模块顶层移到使用点（``get_async_client`` /
``get_sync_client`` / ``health_check_service`` / ``update_web_content``），让 MCP
主进程的 cold-start 提前 ~55 ms 完成 ``mcp.run(transport="stdio")`` 监听就绪，
首个工具调用一次性吃掉这 55 ms（``sys.modules`` cache 命中后续调用），整体
观感是「IDE 看到 MCP server ready 早 55 ms，第一次调用慢 55 ms，后续都不变」。

类型注解通过 ``from __future__ import annotations`` 转成 PEP 563 lazy strings，
``if TYPE_CHECKING: import httpx`` 让 ty / mypy 等静态检查器仍能解析 ``httpx.AsyncClient``
等符号；运行时 ``httpx`` 仅在使用点的函数体内导入，``sys.modules['httpx']`` 在 MCP
主进程**完全没**调用过 HTTP 时维持 unset 状态（可由
``tests/test_lazy_httpx_r25_2.py::test_module_top_import_does_not_load_httpx`` 验证）。

参考：R23.2（lazy ``psutil`` 同样思路，省 8 ms）、R23.3（lazy ``flasgger.Swagger``，省 75 ms）。

## 函数

### `_ensure_notification_system_loaded() -> tuple[Any, Any]`

首次调用时加载 ``notification_manager`` + ``notification_providers``，幂等。

Returns:
    ``(notification_manager_singleton, initialize_notification_system_fn)``，
    加载失败时返回 ``(None, None)``。

### `_close_async_client_best_effort(client: httpx.AsyncClient | None) -> None`

在同步上下文中尽力关闭异步 HTTP 客户端的连接池。

R25.2: ``client`` 为 ``None`` 时（典型 cold-start：MCP 进程从未调用过 HTTP）直接
返回，避免触发 httpx 模块加载——``client`` 不为 None 意味着调用方早已通过
``get_async_client`` 把 httpx 导入过（``sys.modules`` 命中），此时调用 ``client.is_closed``
与 ``client.aclose()`` 都不会重复加载。

### `_invalidate_runtime_caches_on_config_change() -> None`

配置变更回调：清空配置缓存 + 关闭 httpx 客户端以便下次重建

### `_ensure_config_change_callbacks_registered() -> None`

确保只注册一次配置变更回调

### `get_async_client(config: WebUIConfig) -> httpx.AsyncClient`

获取（或创建）模块级异步 HTTP 客户端，支持连接池复用和自动重试。

R25.2: ``import httpx`` 在函数体首行，首次调用时触发 ~55 ms 加载并写入
``sys.modules``，后续调用走 cache 几乎零成本；MCP 主进程在收到首个工具调用
前完全不会进入此函数，故 cold-start 不付这 55 ms。

### `get_sync_client(config: WebUIConfig) -> httpx.Client`

获取（或创建）模块级同步 HTTP 客户端。

R25.2: 与 ``get_async_client`` 同样的延迟加载策略——首次调用付 55 ms，
后续命中 ``sys.modules`` cache。

### `create_http_session(config: WebUIConfig) -> httpx.Client`

向后兼容：返回同步 httpx.Client。

R25.2: 实际加载延迟到 ``get_sync_client``。

### `is_web_service_running(host: str, port: int, timeout: float = 2.0) -> bool`

TCP 端口检查，验证服务是否在监听

### `health_check_service(config: WebUIConfig) -> bool`

HTTP /api/health 检查，验证服务是否正常。

R25.2: ``except httpx.HTTPError`` 在函数体内引用 ``httpx``，但走到这一步前
``create_http_session(config)`` 必然已通过 ``get_sync_client`` 把 httpx 加载好
并写入 ``sys.modules``——异常处理器读取 ``httpx.HTTPError`` 时模块全局命名空间
走 LEGB 查询，``httpx`` 是模块级名（来自 ``TYPE_CHECKING`` block 在运行期不存在），
所以这里需要再次本地 import 把 ``httpx`` 引入函数局部命名空间。

### `get_web_ui_config() -> tuple[WebUIConfig, int]`

加载 Web UI 配置（带 10s TTL 缓存），返回 (WebUIConfig, auto_resubmit_timeout)。

并发模型：cache fetch 与 cache write 都在 ``_config_cache_lock`` 内，
但 load（含 toml 读 + Pydantic 校验）刻意不在锁内，避免 IO 阻塞所有
并发读。代价：两个 cache miss 的 thread 同时 load 时只是各 load 一次
（结果一致，最后写入谁都行），但要防一种更隐蔽的 race：

T1: cache miss → 拿到 ``gen_at_start = G``
T1: 释放锁，开始 load（耗时 IO）
T2: ``_invalidate_runtime_caches_on_config_change`` 触发（如 config.toml
    被外部编辑），cache 清空 + ``_config_cache_generation`` += 1（→ G+1）
T1: load 完毕（用的是新文件 *或* 旧文件，看 OS 调度），尝试写回缓存

如果 T1 用的是旧文件值，又写回缓存，则 T3 读取时拿到 stale value——
invalidate 被沉默地撤销。修复：T1 写回前 re-check
``_config_cache_generation == gen_at_start``；不匹配则丢弃 cache write
（仍正常返回 result 给 T1 自己，因为 T1 的语义只是"我现在需要值"）。

后续 T3 进来会再 cache miss → 拿到 G+1 → 重新 load 一次 → 拿到新值。

### `_get_web_ui_log_path(script_dir: Path) -> Path`

获取 Web UI 子进程日志文件路径，自动创建 logs 目录并截断过大文件。

### `_is_port_available(host: str, port: int) -> bool`

检测 ``(host, port)`` 是否可被 bind（pre-flight check）。

why：
    ``start_web_service`` 历史上靠 15s health-check loop 间接发现
    端口冲突——如果用户的 8080 已被另一个进程占用，子进程会立刻
    因 ``OSError: [Errno 48] Address already in use`` 退出，但调用
    方要等满 ``max_wait = 15s`` 才看到 ``ServiceTimeoutError``，错
    误码也是不太精确的 ``"start_timeout"`` —— 用户搞不清是端口冲突
    还是 Flask 启动慢，文档里的 troubleshooting 章节专门写过这条。

    Pre-flight ``socket.bind`` 在子进程启动前先验证端口可用，命中
    EADDRINUSE 时立刻报 ``port_in_use``、错误码精确、用户体验
    从"等 15s 然后看 timeout"变成"立刻收到端口被占的明确提示"。

TOCTOU 说明：
    bind 后立刻关闭再交给子进程 bind，存在窗口被别的进程抢占的
    race，但这个 race 在用户实际场景几乎不存在（用户常态是"我
    前一个 Web UI 还在跑"，不是"我此刻刻意起两个互相竞争的
    binding"）。即使发生，子进程依然会 fail-fast 抛 OSError，
    然后 ``except Exception`` 分支会兜底转成 ``start_failed``，
    没有比 pre-flight 之前更糟。

返回：
    ``True``：端口可用；``False``：端口被占用 / 不可绑定（权限不足、
    非法 host 等）。

### `start_web_service(config: WebUIConfig, script_dir: Path) -> None`

启动 Flask Web UI 子进程，含健康检查

### `update_web_content(summary: str, predefined_options: list[str] | None, task_id: str | None, auto_resubmit_timeout: int, config: WebUIConfig) -> None`

POST /api/update 更新 Web UI 内容。

R25.2: 函数体首行 ``import httpx`` 把 httpx 引入函数局部命名空间，
保证后续 ``except httpx.TimeoutException / ConnectError / HTTPError`` 可以
解析符号；首次调用与首个 interactive_feedback 工具调用同步发生，付一次性 ~55 ms。

### `async ensure_web_ui_running(config: WebUIConfig, client: Any | None = None) -> None`

检查并自动启动 Web UI 服务（异步）。

``client`` 允许 ``interactive_feedback`` 复用本次调用已取出的
AsyncClient，避免健康检查和后续 POST /api/tasks 分别做一次
singleton lookup；未传入时保持历史行为。

### `cleanup_http_clients() -> None`

清理 HTTP 客户端（供 server.cleanup_services 调用）

## 类

### `class ServiceManager`

服务进程生命周期管理器（线程安全单例）

#### 方法

##### `__init__(self)`

##### `register_process(self, name: str, process: subprocess.Popen, config: WebUIConfig) -> None`

##### `unregister_process(self, name: str) -> None`

##### `get_process(self, name: str) -> subprocess.Popen | None`

##### `is_process_running(self, name: str) -> bool`

##### `terminate_process(self, name: str, timeout: float = 5.0) -> bool`

##### `cleanup_all(self, shutdown_notification_manager: bool = True) -> None`

##### `get_status(self) -> dict[str, dict]`
