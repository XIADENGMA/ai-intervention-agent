# server_feedback

> 英文 signature-only 版本（仅函数 / 类签名速查）：[`docs/api/server_feedback.md`](../api/server_feedback.md)

反馈交互层 - interactive_feedback 工具实现、任务轮询与上下文管理。

该模块从 `server.py` 抽取反馈相关逻辑，避免在 MCP 入口文件里堆积业务代码。
注意：`interactive_feedback` 的 MCP 工具注册由 `server.py` 持有的 `mcp` 实例完成，
本模块内的 `interactive_feedback` 为“未装饰”的实现函数。

## 函数

### `async wait_for_task_completion(task_id: str, timeout: int = 260) -> dict[str, Any]`

SSE 事件驱动 + HTTP 轮询保底等待任务完成。

双通道并行：SSE 提供 <50ms 实时检测，HTTP 轮询（每 2s）作为 SSE 断连的安全网。
任一通道检测到完成即终止另一通道。

### `launch_feedback_ui(summary: str, predefined_options: list[str] | None = None, task_id: str | None = None, timeout: int = 300) -> dict[str, Any]`

废弃：旧版 Python API，推荐使用 interactive_feedback() MCP 工具

### `async interactive_feedback(message: str | None = Field(default=None, description='Question, summary, or proposal to display to the human user. MUST be a non-empty string. Supports CommonMark / GitHub-Flavored Markdown (headings, lists, tables, fenced code blocks, links, inline code). Recommended length: 1-2000 characters; hard limit 10000 (longer input is truncated). Best practices: (1) state the question clearly in the first line; (2) include the recommended/default answer when proposing options; (3) escape special characters properly in JSON (use \\" for quotes, \\n for newlines). If omitted, the server falls back to `summary` or `prompt` for cross-tool compatibility.'), predefined_options: list | None = Field(default=None, description="Optional list of predefined choices the user can pick from (rendered as multi-select checkboxes alongside a free-text reply). MUST be either null/omitted or a JSON array of strings; non-string items are dropped. Each option: 1-500 characters (longer items are truncated). Tips: (1) keep options short, action-oriented and mutually distinguishable; (2) if you have a recommended/default answer, place it first and mark it (e.g. '[Recommended] ...'); (3) the user may also ignore options and reply with free text. If omitted, the server falls back to `options` for cross-tool compatibility."), summary: str | None = Field(default=None, description='Compatibility alias for `message` (used by noopstudios/Minidoracat interactive-feedback-mcp variants). Ignored when `message` is provided.'), prompt: str | None = Field(default=None, description='Compatibility alias for `message`. Ignored when `message` is provided.'), options: list | None = Field(default=None, description='Compatibility alias for `predefined_options`. Ignored when `predefined_options` is provided.'), project_directory: str | None = Field(default=None, description='Accepted for compatibility with other feedback MCP variants; this server ignores it (project context is taken from the running Web UI / config).'), submit_button_text: str | None = Field(default=None, description='Accepted for compatibility; this server uses its own UI labels.'), timeout: int | None = Field(default=None, description='Accepted for compatibility; this server uses its own configured backend timeout and auto-resubmit countdown.'), feedback_type: str | None = Field(default=None, description='Accepted for compatibility; ignored by this server.'), priority: str | None = Field(default=None, description='Accepted for compatibility; ignored by this server.'), language: str | None = Field(default=None, description="Accepted for compatibility; UI language follows the user's saved settings."), tags: list | None = Field(default=None, description='Accepted for compatibility; ignored by this server.'), user_id: str | None = Field(default=None, description='Accepted for compatibility; ignored by this server.')) -> list`

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

## 类

### `class FeedbackServiceContext`

反馈服务上下文管理器 - 自动管理服务启动和清理

#### 方法

##### `__init__(self)`

初始化，延迟加载配置

##### `launch_feedback_ui(self, summary: str, predefined_options: list[str] | None = None, task_id: str | None = None, timeout: int = 300) -> dict[str, Any]`

在上下文中启动反馈界面（委托给全局 launch_feedback_ui）
