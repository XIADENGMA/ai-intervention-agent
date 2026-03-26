## MCP tool reference

This project currently exposes **one** MCP tool:

### `interactive_feedback`

Request **interactive user feedback** through the Web UI (browser or VS Code Webview), then return the result back to the MCP client.

#### Parameters

- `message` (string, required)
  - The prompt shown to the user (Markdown supported)
  - Max length: **10000** characters (extra content will be truncated)
- `predefined_options` (array, optional)
  - Predefined choices the user can pick from
  - Each option max length: **500** characters
  - Non-string items are ignored
  - `null` / missing / `[]` means no predefined options

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
