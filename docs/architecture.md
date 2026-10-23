# Architecture

> 中文版：[`architecture.zh-CN.md`](architecture.zh-CN.md)

Component-level and workflow-level views of how AI Intervention Agent
(AIIA) fits together — useful when you're integrating a new client
(custom MCP host, alternate IDE plugin) or debugging a cross-component
issue.

## Architecture overview

```mermaid
graph LR
    subgraph Clients["Clients (any MCP host)"]
        A1[LLM Agent<br/>Cursor / Cline / Augment]
        A2[Web browser<br/>multi-task dashboard]
        A3[VS Code extension<br/>sidebar webview]
        A4[CLI<br/>--print-config / --version]
    end

    subgraph Backend["AIIA backend (single Python process)"]
        B1[MCP server<br/>stdio + interactive_feedback]
        B2[Flask web server<br/>/api/* + SSE bus]
        B3[Task queue<br/>RW-lock + persist]
        B4[Notification manager<br/>browser / system / Bark]
        B5[Config manager<br/>TOML + env override]
    end

    subgraph External["External"]
        E1[File system<br/>config.toml + tasks.json]
        E2[Browser / OS<br/>system notifications]
        E3[Bark API<br/>iOS push]
    end

    A1 -- MCP stdio --> B1
    A2 -- HTTP + SSE --> B2
    A3 -- HTTP + SSE --> B2
    A4 -- module import --> B5

    B1 -- enqueue task --> B3
    B2 -- read / mutate --> B3
    B3 -- task_changed event --> B2
    B2 -- "broadcast SSE<br/>(R51-B heartbeat 25s)" --> A2
    B2 -- broadcast SSE --> A3
    B3 -- on add_task --> B4
    B4 -- "Web Notification API" --> E2
    B4 -- POST --> E3
    B5 -- read / watch mtime --> E1
    B3 -- persist on mutate --> E1
```

**Key invariants** (locked by tests in `tests/`):

- `task_changed` SSE payload schema enforced cross-language
  (Python ↔ JS, `test_feat_sse_cross_language_schema_r297.py`).
- SSE heartbeat = 25s, cleanup interval = 5s, hot-path throttle = 30s,
  JS health check = 30s — locked across all source files
  (`test_feat_perf_baseline_const_r296.py`).
- Plus a static single-tool MCP surface, AST-based lock-acquisition-order
  contracts (deadlock-freedom proven statically), and a lazy-init audit —
  see [`contributor-guide-invariant-tests.md`](contributor-guide-invariant-tests.md)
  for the full catalogue.

For deeper subsystem detail (config schema, MCP tool reference, i18n
strategy, troubleshooting), start from the docs index:
[`README.md`](README.md).

## Agent / Glass mode workflow

AIIA is designed for **long-running autonomous agent loops** (Cursor
Composer, Cursor Glass mode, Cline, Augment, Trae) where the LLM calls
`interactive_feedback` many times during a single run. The combined
agent-side parameters + user-side UX features below let a human reviewer
decide in **< 5 seconds per task**, so the agent never blocks the
flow longer than necessary.

### How a single interaction flows

```mermaid
sequenceDiagram
    participant Agent as LLM Agent<br/>(Cursor / Cline)
    participant MCP as MCP transport
    participant AIIA as AIIA backend<br/>(Flask + SSE)
    participant UI as Web UI / VS Code
    participant Human as Human reviewer

    Agent->>MCP: interactive_feedback(message,<br/>header_label, predefined_options, ...)
    MCP->>AIIA: POST /api/tasks
    AIIA->>UI: SSE task_changed (new task)
    UI->>Human: Browser/system notification<br/>+ countdown timer
    Note over Human: Reads chip + prompt,<br/>clicks Yes/No or types reply
    Human->>UI: Submit
    UI->>AIIA: POST /api/tasks/{id}/submit
    AIIA->>MCP: SSE task_changed (completed) (+ ctx.info)
    MCP->>Agent: Returns text + images + selected options
    Note over Agent: Resumes execution<br/>with human input
```

### Failure & recovery flows

Beyond the happy path above, three boundary cases keep long-running
Agent / Glass-mode sessions resilient: **auto-resubmit** (human steps
away), **SSE reconnect** (network drop), and **typing-hold** (human is
typing — never interrupt).

```mermaid
sequenceDiagram
    autonumber
    participant Agent as LLM Agent
    participant AIIA as AIIA backend
    participant UI as Web UI
    participant Human as Human reviewer

    Note over Agent,Human: ① Auto-resubmit (human stepped away)
    Agent->>AIIA: interactive_feedback
    AIIA->>UI: SSE task_changed (new task)<br/>countdown = feedback.frontend_countdown
    Note over UI: countdown hits 0<br/>(human not typing)
    UI->>AIIA: POST /api/tasks/{id}/submit<br/>(what the human typed or ticked,<br/>else the configured resubmit_prompt)
    AIIA->>Agent: SSE task_changed (completed)<br/>the agent gets the resubmit prompt back

    Note over UI,AIIA: ② SSE drop → degraded poll → reconnect
    UI--xAIIA: SSE disconnect (sleep/network jitter)
    UI->>AIIA: GET /api/tasks (fallback poll: 2s,<br/>backing off to 30s on errors)
    UI->>AIIA: SSE reconnect (exponential backoff)
    AIIA-->>UI: SSE resumed
    UI->>AIIA: GET /api/tasks (once, as soon as the stream<br/>is back: subscribe first, then read the list)

    Note over Agent,Human: ③ Typing-hold (human typing — never interrupt)
    Agent->>AIIA: interactive_feedback
    UI->>Human: countdown ring
    Human->>UI: starts typing feedback
    Note over UI: ≤15s left and typed in the last 10s:<br/>POST /api/tasks/{id}/extend (+60s, max 3 per task)<br/>at 0 while still typing: waits (typing-hold)
    Human->>UI: stops typing + submits
    UI->>AIIA: POST /api/tasks/{id}/submit
    AIIA->>Agent: SSE task_changed (completed) (full reply)
```

### Agent-side parameters (LLM passes these via MCP)

| Parameter | Purpose | Max | Source |
|---|---|---|---|
| `header_label` | One-word context chip in task pane (`Auth`, `DB`, `i18n`) | 16 chars | gemini-cli `ask_user.header` |
| `feedback_placeholder` | Per-task textarea hint (overrides global i18n) | 200 chars | gemini-cli `ask_user` |
| `predefined_options` | Multi-select chips with optional `default: true` recommendation | 10000 chars/each | AIIA + upstream parity |
| `loop_id` + 4 loop fields | Group multi-round feedback into one loop: objective, phase, success criteria, iteration label | 32–500 chars | AIIA loop engineering |

Full parameter reference + a complete Agent-mode call example lives in
[`mcp_tools.md#agent-mode-parameters-cursor--composer--cline--augment--trae`](mcp_tools.md#agent-mode-parameters-cursor--composer--cline--augment--trae).

**Loop engineering** (long autonomous runs): rounds sharing a `loop_id`
render a loop-context strip above the prompt and a collapsible "Rounds"
timeline of every completed round's verdict, backed by `GET /api/loops`.
See [`mcp_tools.md#loop-engineering-parameters-long-autonomous-runs`](mcp_tools.md#loop-engineering-parameters-long-autonomous-runs).

### User-side workflow features (built into the Web UI)

- **Multi-task tabs** — parallel requests each get their own tab +
  independent countdown ring
- **Per-task draft autosave** — switching tabs never loses an
  in-progress reply
- **Typing-hold auto-extension** — the countdown extends itself while
  you type and never fires mid-input
- **Custom notification sound** — upload a short audio file for a
  distinct Agent-mode chime
- **Per-task images** — paste screenshots inline, returned to the agent
  as MCP `ImageContent` blocks
- **SSE liveness badge** — green/orange/red corner indicator shows
  whether the page is in sync

### Recommended LLM system prompt

To force the agent to actually use this tool instead of "auto-finishing"
the task, append the "Prompt snippet (copy/paste)" block from the
[project README](../README.md#quick-start) to your IDE's system prompt /
`.cursorrules`.
