## MCP tool reference

This project currently exposes **one static core** MCP tool:

### Server-level metadata (v1.5.21+)

The `initialize` protocol response advertises the following fields. Clients (ChatGPT Desktop / Claude Desktop / Cursor, etc.) use them to render the server list UI and to surface LLM-facing guidance:

| Field          | Content                                                                                                                | Purpose                                                               |
| -------------- | ---------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------- |
| `name`         | `AI Intervention Agent MCP`                                                                                            | Display label in the client's tool list                               |
| `version`      | Current package version (read via `importlib.metadata`; e.g. `1.6.0`; falls back to `0.0.0+local` when not installed) | Client-side compatibility checks and troubleshooting                  |
| `instructions` | Chinese usage guide (when to call / when not to call / behavior contract)                                              | Delivered during `initialize` so the LLM has meta-rules for tool use  |
| `website_url`  | `https://github.com/xiadengma/ai-intervention-agent`                                                                   | Client UI link to the project homepage                                |
| `icons`        | Four base64 data URIs (32/192/512 PNG + SVG) embedded once at server startup                                           | Client server-list icon, fully self-contained without remote CDN deps |

### Tool-level annotations

`interactive_feedback` carries the following annotations in the `tools/list` response so clients understand the tool semantics correctly (e.g. ChatGPT Desktop stops asking for "destructive operation" confirmation on every call):

| Field             | Value                                 | Meaning                                                                             |
| ----------------- | ------------------------------------- | ----------------------------------------------------------------------------------- |
| `title`           | `Interactive Feedback (人机协作反馈)` | Friendly label shown in client UI                                                   |
| `readOnlyHint`    | `false`                               | The tool persists tasks and triggers notifications, so it is not strictly read-only |
| `destructiveHint` | `false`                               | Never modifies source code, git history, or databases — clients can skip confirm    |
| `idempotentHint`  | `false`                               | Each call creates a new feedback task, so it is non-idempotent                      |
| `openWorldHint`   | `true`                                | The tool interacts with a real human and notification services — open-world tool    |

> These fields follow the MCP spec (latest `2025-11-25`, originally introduced in
> `2024-11-05`) and are natively supported by FastMCP 3.x. See
> [MCP changelog](https://modelcontextprotocol.io/specification/2025-11-25/changelog)
> for the spec history.

### FastMCP tool metadata

`interactive_feedback` is registered with FastMCP tags
`human-in-the-loop`, `feedback`, and `approval`, so clients or gateways that
surface tags can group it with human review / approval tools. Its tool-level
`version` matches the package/server version for client diagnostics. It
intentionally does **not** set a FastMCP decorator timeout: this is a
long-running human feedback tool, and wait policy is controlled by the backend
configuration documented below.

### Dynamic tool registration stance

The MCP `2025-11-25` tools spec allows a server to declare
`capabilities.tools.listChanged=true` and send
`notifications/tools/list_changed` when the tool list changes. FastMCP 3.2.4
also supports runtime `add_tool()` / `local_provider.remove_tool()` and
automatically emits list-change notifications when add/remove/enable/disable
happens inside an active MCP request context.

AI Intervention Agent does **not** use dynamic registration as its primary tool
surface. `interactive_feedback` is the long-running human-in-the-loop contract
and must stay statically discoverable for all clients. Dynamic registration is
only a future option for genuinely optional or conditional tools, such as
experimental diagnostics, loop-engineering helpers, or auth/config-gated
capabilities.

Before any dynamic tool ships, it must satisfy these boundaries:

- Keep `interactive_feedback` registered as a static fallback.
- Prove target-client refresh behavior. VS Code documents dynamic tool
  discovery support, but ChatGPT Desktop, Claude Desktop, and Cursor should be
  treated as unproven or inconsistent for mid-session
  `notifications/tools/list_changed` refresh until verified against the exact
  client versions being supported.
- Use stable MCP tool names: 1-128 ASCII letters/digits/`_`/`-`/`.` only.
- Provide explicit annotations, tags, version, input schema, error semantics,
  rate limiting, audit logging, and output sanitization.
- Never treat hiding a dynamic tool as authorization. Tool handlers must still
  validate configuration, auth state, inputs, access control, rate limits, and
  sensitive output redaction.

The local SDK spike is locked by
`tests/test_mcp_dynamic_tools_spike_r457.py`: it verifies FastMCP 3.2.4 can add
and remove a tool dynamically, preserves annotations/tags/version, rejects
duplicate name+version with `on_duplicate="error"`, and uses the current
`on_duplicate` constructor parameter rather than the older
`on_duplicate_tools` spelling found in some docs.

---

### `interactive_feedback`

Request **interactive user feedback** through the Web UI (browser or VS Code Webview), then return the result back to the MCP client.

#### Parameters

- `message` (string, required)
  - The prompt shown to the user (Markdown supported)
  - Max length: **1000000** characters (extra content will be truncated). The
    10 MB byte hard limit in `task_queue` still applies as a DoS guard.
- `predefined_options` (array, optional)
  - Predefined choices the user can pick from. **Two canonical input shapes** (v1.6.0+):
    1. **RECOMMENDED** `list[dict]` — objects of shape
       `{ "label": str, "default": bool }`. Mark the recommended option with
       `default: true` to get a real pre-checked checkbox in the UI. Field
       aliases accepted: `label` / `text` / `value`,
       `default` / `selected` / `checked`.
    2. `list[str]` — simple labels, all initially unchecked. Use this only
       when no recommendation is needed.
  - Each option max length: **10000** characters (overflow truncated)
  - Non-string / non-`{label,...}` items are silently dropped
  - `null` / missing / `[]` means no predefined options
  - **Removed in R167 (v1.6.0+)**: the legacy parallel-array shape
    `predefined_options_defaults` (sibling boolean array) has been removed —
    use the `list[dict]` shape above to express "recommended" options.
    Clients still sending `predefined_options_defaults` will get a clear
    `ToolError` from FastMCP's strict schema (`additionalProperties: false`),
    which is intentional: silent acceptance would let LLMs keep sampling the
    obsolete parallel-array shape without learning.

#### Agent-mode parameters (Cursor / Composer / Cline / Augment / Trae)

The following four optional parameters are **purpose-built for
high-frequency Agent / Glass-mode workflows** where the LLM calls
`interactive_feedback` many times during a long autonomous run. They let
the agent pre-shape the UI per task so the human reviewer can decide in
< 5 seconds instead of context-switching back to read the full prompt.
All four are visible to the LLM via the `tools/list` JSON-Schema
description; this doc section is the human-readable reference.

- `header_label` (string, optional, max **16** chars)
  - Used as the task tab's display name (since R700 it takes priority
    over the machine-flavored task ID; the full ID stays in the
    tooltip). Examples: `"Auth"`, `"DB"`, `"i18n"`, `"CSS"`. Especially
    valuable in **multi-task mode** where the user is reviewing 3+
    concurrent requests — it lets them visually distinguish task
    domains at a glance. Borrowed from `gemini-cli`'s `ask_user.header`
    schema.
  - Single-word recommendation, no spaces if avoidable. Overflow is
    clamped server-side; omit or empty string → the tab falls back to
    the task ID.

- `question_type` (string, optional, currently only `"yesno"`)
  - When `"yesno"`, the frontend **hides the free-text textarea** and
    renders a single-row Yes / No button pair. User's click submits
    the literal string `"yes"` or `"no"` — saves the typing + Submit
    click for binary decisions (approve / reject, proceed / abort,
    confirm-deletion). Unknown values silently treated as `None` for
    forward-compat with future types (`"choice"` / `"rating"`).
    Borrowed from `gemini-cli`'s `ask_user` schema.

- `feedback_placeholder` (string, optional, max **200** chars)
  - Per-task textarea placeholder hint shown to the user (overrides the
    global `page.feedbackPlaceholder` i18n string). Examples:
    `"Paste the error stack trace"`, `"Describe the visual glitch"`,
    `"Reply 'ok' to approve or 'no' + reason to reject"`. Single-line
    placeholders only (longer text silently truncated; the response
    sets `placeholder_truncated: true` so callers know clamping
    happened). Borrowed from `gemini-cli`'s `ask_user` schema.

- `auto_resubmit_timeout` (int, optional, seconds, default from
  `feedback.frontend_countdown` = `240`)
  - Per-task override of the global frontend countdown — pass smaller
    values (e.g. `60`) for low-stakes confirmations the agent doesn't
    want to wait a full 4 minutes on; pass `0` to disable auto-resubmit
    for a single critical task while leaving global config alone.
    Range follows server config (`[0, 3600]`); out-of-range values are
    silently clamped, not rejected.

These four parameters compose: a typical Agent-mode call combines
`header_label` (context) + `feedback_placeholder` (hint) + either
`predefined_options` (multi-select) or `question_type='yesno'`
(binary). See the full Agent-mode example below.

#### Returns

`interactive_feedback` returns a **list of MCP Content blocks**:

- `TextContent`: `{"type":"text","text": "..."}`
  - Contains the user's input and/or selected options
- `ImageContent`: `{"type":"image","data":"<base64>","mimeType":"image/png"}`
  - One item per uploaded image (when provided)

#### Runtime behavior (high level)

- Ensures the Web UI service is running
- Creates a task via the Web UI HTTP API (`POST /api/tasks`)
- Waits for completion using a **dual-channel** transport: SSE (`GET /api/events`,
  with `Last-Event-ID` resume to recover missed events when the connection drops)
  as the primary path, plus a low-frequency HTTP poll (`GET /api/tasks/{task_id}`)
  as a safety net (`30s` while SSE is healthy, falling back to `2s` when SSE drops)
- Forwards `task.created` / `task.notified` / `task.completed` events to the MCP
  client via `ctx.info(...)`, so chat-style clients (Cursor / Claude Desktop /
  ChatGPT Desktop) can render a live progress entry in the sidebar
- Subject to the production middleware chain
  (`ErrorHandling` + `RateLimiting` 10 req/s burst 20 + `Timing` + `Logging`)
- On failure/timeout, returns a configurable prompt (see `feedback.resubmit_prompt`)
  to encourage the client to call the tool again

#### Server self-info resource

Clients can read `aiia://server/info` (MIME `application/json`, tags
`diagnostics` / `self-info`) to obtain a JSON snapshot of the running server:
`name` / `version` / `transport` / `runtime` (Python version + executable +
platform) / `fastmcp.version` / `middleware` chain / `error_stats` /
`web_ui` (host + port + reachability) / `task_queue` (initialized + size +
pending). The resource is **side-effect free** — it never wakes the Web UI
process or constructs a new task queue, so it's safe to poll from a status
panel.

#### Notes on timeouts

`interactive_feedback` is intentionally **long-running**.

- The frontend countdown is controlled by `feedback.frontend_countdown` (default **240s**, range **[10, 3600]s**; `0` or any non-positive integer disables it).
- The backend wait time (`feedback.backend_max_wait`, range **[10, 7200]s**) is derived from the frontend countdown + a buffer (see `docs/configuration.md` for the exact rule).

#### Examples

Simple prompt (no recommended option needed — `list[str]`):

```text
interactive_feedback(
  message="Choose the rollout plan:",
  predefined_options=["Rebase", "Merge", "Defer"]
)
```

Prompt with a **recommended** option pre-selected (use the recommended
`list[dict]` shape):

```text
interactive_feedback(
  message="Choose the rollout plan:",
  predefined_options=[
    {"label": "Rebase", "default": true},
    {"label": "Merge"},
    {"label": "Defer"}
  ]
)
```

Simple prompt without options:

```text
interactive_feedback(message="Please confirm the next step.")
```

#### Agent-mode example (Cursor / Glass)

A long-running Cursor agent refactoring authentication code asks for
sign-off on a specific PR section. Combine **all four Agent-mode
parameters** to get a sub-5-second human decision:

```text
interactive_feedback(
  message=(
    "I refactored `auth/session.py::renew_token()` to use the "
    "PyJWT 2.x API. The new code:\n"
    "- Drops the legacy `algorithms` kwarg fallback\n"
    "- Replaces `jwt.PyJWTError` with `jwt.InvalidTokenError`\n"
    "- Adds a 30s clock-skew tolerance\n\n"
    "**Shall I proceed to run the auth integration suite?**"
  ),
  header_label="Auth",                      # 1-word chip in task pane
  feedback_placeholder=                     # textarea hint for free-form
    "Reply 'ok' to run tests, or 'no' + reason to roll back",
  question_type="yesno",                    # binary → 2-button UI
  auto_resubmit_timeout=120,                # 2 min instead of default 4
)
```

UX result: the user sees an `Auth` chip + a clear 1-paragraph summary
+ Yes/No buttons. One click submits — no typing required. If the
user steps away for >2 minutes, the agent gets a resubmit-prompt
back automatically (instead of blocking the agent for the full 4
minutes). For a list of all `header_label` / `question_type` /
`feedback_placeholder` / `auto_resubmit_timeout` semantics see the
[Agent-mode parameters](#agent-mode-parameters-cursor--composer--cline--augment--trae)
section above.
