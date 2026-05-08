# server_feedback

> 英文 signature-only 版本（仅函数 / 类签名速查）：[`docs/api/server_feedback.md`](../api/server_feedback.md)

反馈交互层 - interactive_feedback 工具实现、任务轮询与上下文管理。

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

## 函数

### `_bump_feedback_counter(name: str, by: int = 1) -> None`

``_FEEDBACK_COUNTERS[name] += by``（线程安全；未知 key 时静默）。

遇到未知 key 不抛异常 / 也不创建新 key——拼写错误应当被测试捕获，
而不是在生产里悄悄拉一个新指标。

### `get_feedback_counters() -> dict[str, int]`

返回 interactive_feedback 计数器快照（R47）；永远是拷贝，不是引用。

给 ``server.server_info_resource`` 在 ``aiia://server/info`` 子块里
渲染，运维侧通过 MCP `resources/read` 拉取即可看到累计值。

### `async _emit_ctx_info(ctx: FastMCPContext | None, message: str) -> None`

Best-effort 把 task lifecycle 关键节点回写到 MCP client 端日志。

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

### `async _close_orphan_task_best_effort(task_id: str, host: str, port: int, client: Any | None = None) -> None`

R13·B1 · timeout / cancel 路径的 ghost-task 兜底清理。

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

### `async wait_for_task_completion(task_id: str, timeout: int = 260) -> dict[str, Any]`

SSE 事件驱动 + HTTP 轮询保底等待任务完成。

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

### `launch_feedback_ui(summary: str, predefined_options: list[str] | None = None, task_id: str | None = None, timeout: int = 300) -> dict[str, Any]`

废弃：旧版 Python API，推荐使用 interactive_feedback() MCP 工具。

R25.2: 函数体首行 ``import httpx`` 让下面 ``except httpx.HTTPError`` 在运行时
可以解析符号；同时本函数会调用 ``service_manager.update_web_content`` 等
使用 httpx 的接口，``sys.modules['httpx']`` 命中 cache 后零成本。

### `async interactive_feedback(message: str | None = Field(default=None, description='Question, summary, or proposal to display to the human user. MUST be a non-empty string. Supports CommonMark / GitHub-Flavored Markdown (headings, lists, tables, fenced code blocks, links, inline code). Recommended length: 1-2000 characters; hard limit 10000 (longer input is truncated). Best practices: (1) state the question clearly in the first line; (2) include the recommended/default answer when proposing options; (3) escape special characters properly in JSON (use \\" for quotes, \\n for newlines). If omitted, the server falls back to `summary` or `prompt` for cross-tool compatibility.'), predefined_options: list | None = Field(default=None, description='Optional list of predefined choices the user can pick from (rendered as multi-select checkboxes alongside a free-text reply). Three input shapes are accepted (v1.5.20+): (a) list[str] — simple labels, all initially unchecked; (b) list[dict] of shape {"label": str, "default": bool} — let the recommended option start pre-checked without any extra param (aliases: "label"/"text"/"value", "default"/"selected"/"checked"); (c) list[str] paired with the sibling param `predefined_options_defaults` (parallel boolean array). Non-string and non-{label,...} items are silently dropped. Each option max length: 500 characters (longer items are truncated). Tips: (1) keep options short, action-oriented and mutually distinguishable; (2) prefer the dict form `{"label": "Apply", "default": true}` to mark the recommended/default answer — the UI now renders real pre-checked checkboxes, so do NOT rely on text-prefix hacks for marking recommended options; (3) the user may also ignore options and reply with free text. If omitted, the server falls back to `options` for cross-tool compatibility.'), predefined_options_defaults: list | None = Field(default=None, description='Optional sibling array (v1.5.20+) for the `list[str]` shape of `predefined_options`: each element decides whether the corresponding checkbox starts pre-checked. Truthy aliases (case-insensitive, trimmed): True / 1 / 1.0 / "true" / "yes" / "on" / "selected"; everything else (including None / 0 / lists / dicts) → False. Length is silently truncated when longer than `predefined_options` and padded with False when shorter. Ignored when `predefined_options` already uses the {"label", "default"} dict form (which takes precedence).'), summary: str | None = Field(default=None, description='Compatibility alias for `message` (used by noopstudios/Minidoracat interactive-feedback-mcp variants). Ignored when `message` is provided.'), prompt: str | None = Field(default=None, description='Compatibility alias for `message`. Ignored when `message` is provided.'), options: list | None = Field(default=None, description='Compatibility alias for `predefined_options`. Ignored when `predefined_options` is provided.'), project_directory: str | None = Field(default=None, description='Accepted for compatibility with other feedback MCP variants; this server ignores it (project context is taken from the running Web UI / config).'), submit_button_text: str | None = Field(default=None, description='Accepted for compatibility; this server uses its own UI labels.'), timeout: int | None = Field(default=None, description='Accepted for compatibility; this server uses its own configured backend timeout and auto-resubmit countdown.'), feedback_type: str | None = Field(default=None, description='Accepted for compatibility; ignored by this server.'), priority: str | None = Field(default=None, description='Accepted for compatibility; ignored by this server.'), language: str | None = Field(default=None, description="Accepted for compatibility; UI language follows the user's saved settings."), tags: list | None = Field(default=None, description='Accepted for compatibility; ignored by this server.'), user_id: str | None = Field(default=None, description='Accepted for compatibility; ignored by this server.')) -> list`

Ask the human user for interactive feedback through the Web UI.

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

R44 FastMCP 最佳实践：``ctx`` 关键字参数（FastMCP 自动注入）让本函数可以走
``await _emit_ctx_info(ctx, ...)`` 把 task lifecycle 事件回送给 client
（Cursor / Claude Desktop / ChatGPT Desktop）。client 收到后会在 chat
sidebar 渲染一行进度日志，让人类用户能"看到工具确实在工作、正在等真人
回复"，而不是猜"agent 是不是 hung 住了"。``ctx`` 永远 keyword-only 且
默认 None，所以本工具被通过别的入口（pytest 直接调）调用时不会因为缺
ctx 而崩；具体安全语义见 ``_emit_ctx_info`` 的 docstring。

## 类

### `class FeedbackServiceContext`

反馈服务上下文管理器 - 自动管理服务启动和清理

#### 方法

##### `__init__(self)`

初始化，延迟加载配置

##### `launch_feedback_ui(self, summary: str, predefined_options: list[str] | None = None, task_id: str | None = None, timeout: int = 300) -> dict[str, Any]`

在上下文中启动反馈界面（委托给全局 launch_feedback_ui）
