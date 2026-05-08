# server_feedback

> For the Chinese version with full docstrings, see: [`docs/api.zh-CN/server_feedback.md`](../api.zh-CN/server_feedback.md)

## Functions

### `_bump_feedback_counter(name: str, by: int = 1) -> None`

### `get_feedback_counters() -> dict[str, int]`

### `async _emit_ctx_info(ctx: FastMCPContext | None, message: str) -> None`

### `async _close_orphan_task_best_effort(task_id: str, host: str, port: int, client: Any | None = None) -> None`

### `async wait_for_task_completion(task_id: str, timeout: int = 260) -> dict[str, Any]`

### `launch_feedback_ui(summary: str, predefined_options: list[str] | None = None, task_id: str | None = None, timeout: int = 300) -> dict[str, Any]`

### `async interactive_feedback(message: str | None = Field(default=None, description='Question, summary, or proposal to display to the human user. MUST be a non-empty string. Supports CommonMark / GitHub-Flavored Markdown (headings, lists, tables, fenced code blocks, links, inline code). Recommended length: 1-2000 characters; hard limit 10000 (longer input is truncated). Best practices: (1) state the question clearly in the first line; (2) include the recommended/default answer when proposing options; (3) escape special characters properly in JSON (use \\" for quotes, \\n for newlines). If omitted, the server falls back to `summary` or `prompt` for cross-tool compatibility.'), predefined_options: list | None = Field(default=None, description='Optional list of predefined choices the user can pick from (rendered as multi-select checkboxes alongside a free-text reply). Three input shapes are accepted (v1.5.20+): (a) list[str] — simple labels, all initially unchecked; (b) list[dict] of shape {"label": str, "default": bool} — let the recommended option start pre-checked without any extra param (aliases: "label"/"text"/"value", "default"/"selected"/"checked"); (c) list[str] paired with the sibling param `predefined_options_defaults` (parallel boolean array). Non-string and non-{label,...} items are silently dropped. Each option max length: 500 characters (longer items are truncated). Tips: (1) keep options short, action-oriented and mutually distinguishable; (2) prefer the dict form `{"label": "Apply", "default": true}` to mark the recommended/default answer — the UI now renders real pre-checked checkboxes, so do NOT rely on text-prefix hacks for marking recommended options; (3) the user may also ignore options and reply with free text. If omitted, the server falls back to `options` for cross-tool compatibility.'), predefined_options_defaults: list | None = Field(default=None, description='Optional sibling array (v1.5.20+) for the `list[str]` shape of `predefined_options`: each element decides whether the corresponding checkbox starts pre-checked. Truthy aliases (case-insensitive, trimmed): True / 1 / 1.0 / "true" / "yes" / "on" / "selected"; everything else (including None / 0 / lists / dicts) → False. Length is silently truncated when longer than `predefined_options` and padded with False when shorter. Ignored when `predefined_options` already uses the {"label", "default"} dict form (which takes precedence).'), summary: str | None = Field(default=None, description='Compatibility alias for `message` (used by noopstudios/Minidoracat interactive-feedback-mcp variants). Ignored when `message` is provided.'), prompt: str | None = Field(default=None, description='Compatibility alias for `message`. Ignored when `message` is provided.'), options: list | None = Field(default=None, description='Compatibility alias for `predefined_options`. Ignored when `predefined_options` is provided.'), project_directory: str | None = Field(default=None, description='Accepted for compatibility with other feedback MCP variants; this server ignores it (project context is taken from the running Web UI / config).'), submit_button_text: str | None = Field(default=None, description='Accepted for compatibility; this server uses its own UI labels.'), timeout: int | None = Field(default=None, description='Accepted for compatibility; this server uses its own configured backend timeout and auto-resubmit countdown.'), feedback_type: str | None = Field(default=None, description='Accepted for compatibility; ignored by this server.'), priority: str | None = Field(default=None, description='Accepted for compatibility; ignored by this server.'), language: str | None = Field(default=None, description="Accepted for compatibility; UI language follows the user's saved settings."), tags: list | None = Field(default=None, description='Accepted for compatibility; ignored by this server.'), user_id: str | None = Field(default=None, description='Accepted for compatibility; ignored by this server.')) -> list`

## Classes

### `class FeedbackServiceContext`

#### Methods

##### `__init__(self)`

##### `launch_feedback_ui(self, summary: str, predefined_options: list[str] | None = None, task_id: str | None = None, timeout: int = 300) -> dict[str, Any]`
