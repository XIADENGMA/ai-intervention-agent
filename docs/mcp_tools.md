## MCP tool reference

This project currently exposes **one** MCP tool:

### Server-level metadata (v1.5.21+)

The `initialize` protocol response advertises the following fields. Clients (ChatGPT Desktop / Claude Desktop / Cursor, etc.) use them to render the server list UI and to surface LLM-facing guidance:

| Field          | Content                                                                                       | Purpose                                                                |
| -------------- | --------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| `name`         | `AI Intervention Agent MCP`                                                                   | Display label in the client's tool list                                |
| `version`      | Current package version (e.g. `1.5.21`, read via `importlib.metadata`; falls back to `0.0.0+local` when not installed) | Client-side compatibility checks and troubleshooting                   |
| `instructions` | Chinese usage guide (when to call / when not to call / behavior contract)                      | Delivered during `initialize` so the LLM has meta-rules for tool use   |
| `website_url`  | `https://github.com/xiadengma/ai-intervention-agent`                                          | Client UI link to the project homepage                                 |
| `icons`        | Four base64 data URIs (32/192/512 PNG + SVG) embedded once at server startup                   | Client server-list icon, fully self-contained without remote CDN deps  |

### Tool-level annotations

`interactive_feedback` carries the following annotations in the `tools/list` response so clients understand the tool semantics correctly (e.g. ChatGPT Desktop stops asking for "destructive operation" confirmation on every call):

| Field             | Value  | Meaning                                                                          |
| ----------------- | ------ | -------------------------------------------------------------------------------- |
| `title`           | `Interactive Feedback (人机协作反馈)` | Friendly label shown in client UI                  |
| `readOnlyHint`    | `false`| The tool persists tasks and triggers notifications, so it is not strictly read-only |
| `destructiveHint` | `false`| Never modifies source code, git history, or databases — clients can skip confirm |
| `idempotentHint`  | `false`| Each call creates a new feedback task, so it is non-idempotent                    |
| `openWorldHint`   | `true` | The tool interacts with a real human and notification services — open-world tool |

> These fields follow the MCP spec (2024-11-05+) and are natively supported by FastMCP 3.x.

---

### `interactive_feedback`

Request **interactive user feedback** through the Web UI (browser or VS Code Webview), then return the result back to the MCP client.

#### Parameters

- `message` (string, required)
  - The prompt shown to the user (Markdown supported)
  - Max length: **10000** characters (extra content will be truncated)
- `predefined_options` (array, optional)
  - Predefined choices the user can pick from. **Three input shapes are accepted** (v1.5.20+):
    1. `list[str]` — simple labels, all initially unchecked
    2. `list[dict]` — objects of shape `{ "label": str, "default": bool }`,
       so the recommended choice can be pre-selected without an extra parameter
    3. `list[str]` paired with `predefined_options_defaults` — see below
  - Each option max length: **500** characters
  - Non-string / non-`{label,...}` items are ignored
  - `null` / missing / `[]` means no predefined options
- `predefined_options_defaults` (array of bool, optional, v1.5.20+)
  - Sibling array to the simple `list[str]` form: which checkbox should start
    pre-checked. Lenient normalisation:
    - Truthy aliases: `True` / `1` / `1.0` / `"true"` / `"yes"` / `"on"` /
      `"selected"` (case-insensitive, trimmed)
    - Everything else (including `None`, `0`, lists, dicts) → `False`
  - Length reconciliation:
    - longer than `predefined_options` → silently truncated
    - shorter → padded with `False`
  - Ignored when `predefined_options` already uses the `{label, default}` form

#### Returns

`interactive_feedback` returns a **list of MCP Content blocks**:

- `TextContent`: `{"type":"text","text": "..."}`
  - Contains the user's input and/or selected options
- `ImageContent`: `{"type":"image","data":"<base64>","mimeType":"image/png"}`
  - One item per uploaded image (when provided)

#### Runtime behavior (high level)

- Ensures the Web UI service is running
- Creates a task via the Web UI HTTP API (`POST /api/tasks`)
- Waits for completion by polling (`GET /api/tasks/{task_id}`) until timeout
- On failure/timeout, returns a configurable prompt (see `feedback.resubmit_prompt`) to encourage the client to call the tool again

#### Notes on timeouts

`interactive_feedback` is intentionally **long-running**.

- The frontend countdown is controlled by `feedback.frontend_countdown` (default **240s**, max **250s**).
- The backend wait time is derived from frontend countdown + a buffer (see `docs/configuration.md` for the exact rule).

#### Examples

Simple prompt:

```text
interactive_feedback(message="Please confirm the next step.")
```

Prompt with options:

```text
interactive_feedback(
  message="Choose the rollout plan:",
  predefined_options=["Rebase", "Merge", "Defer"]
)
```

Prompt with a recommended option pre-selected (object form):

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

Equivalent using the parallel-array form:

```text
interactive_feedback(
  message="Choose the rollout plan:",
  predefined_options=["Rebase", "Merge", "Defer"],
  predefined_options_defaults=[true, false, false]
)
```
