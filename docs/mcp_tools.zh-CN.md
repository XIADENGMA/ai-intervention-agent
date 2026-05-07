## MCP 工具说明

本项目当前对外暴露 **1 个** MCP 工具：

### Server 级元数据（v1.5.21+）

`initialize` 协议响应中下发以下字段，client（ChatGPT Desktop / Claude Desktop / Cursor 等）会据此呈现 server 列表 UI、向 LLM 提供调用指引：

| 字段           | 内容                                                                                              | 用途                                                |
| -------------- | ------------------------------------------------------------------------------------------------- | --------------------------------------------------- |
| `name`         | `AI Intervention Agent MCP`                                                                       | client 工具列表显示                                 |
| `version`      | 当前包版本（从 `importlib.metadata` 自动读取，例如 `1.5.41`；未安装时回退 `0.0.0+local`）         | client 兼容性判断 / 故障排查                        |
| `instructions` | 中文使用指引（适合 / 不适合调用的场景、行为约定等）                                               | 在 initialize 阶段下发给 LLM，作为工具选用的元规则  |
| `website_url`  | `https://github.com/xiadengma/ai-intervention-agent`                                              | client UI 链接到项目主页                            |
| `icons`        | 4 个 base64 data URI（32/192/512 PNG + SVG），server 启动时一次性嵌入                             | client 在 server 列表 UI 显示项目图标，self-contained 不依赖外部 CDN |

### Tool 级注解（Tool Annotations）

`interactive_feedback` 在 `tools/list` 协议响应中携带以下 annotations，让 client 准确识别工具语义并优化交互（如 ChatGPT Desktop 不会再每次弹"危险操作"二次确认）：

| 字段              | 值     | 含义                                                                                |
| ----------------- | ------ | ----------------------------------------------------------------------------------- |
| `title`           | `Interactive Feedback (人机协作反馈)` | 客户端 UI 显示的友好标题                                |
| `readOnlyHint`    | `false`| 工具会持久化任务并触发通知，并非完全只读                                            |
| `destructiveHint` | `false`| 不会删除/覆盖任何源代码、git 历史或数据库 —— client 无需弹"危险操作"二次确认        |
| `idempotentHint`  | `false`| 每次调用都会创建新的反馈任务，非幂等                                                |
| `openWorldHint`   | `true` | 工具与外部用户和通知服务交互，是开放世界工具                                        |

> 这些字段遵循 MCP 协议规范（最新版本 `2025-11-25`，最早在 `2024-11-05` 引入），
> FastMCP 3.x 原生支持。spec 历史变更见
> [MCP changelog](https://modelcontextprotocol.io/specification/2025-11-25/changelog)。

### FastMCP 工具元数据

`interactive_feedback` 注册了 FastMCP tags：`human-in-the-loop`、`feedback`
和 `approval`，便于支持 tags 的 client / gateway 将其归类为人类审阅 /
批准类工具。它的工具级 `version` 与包 / server version 保持一致，便于 client
做契约诊断。它**没有**设置 FastMCP decorator timeout：这是长时间运行的人类反馈
工具，等待策略由下方配置项中的后端超时规则控制。

---

### `interactive_feedback`

通过 Web UI（浏览器或 VS Code Webview）向用户发起**交互式反馈**请求，并将用户输入结果返回给 MCP 调用方。

#### 参数

- `message`（string，必填）
  - 展示给用户的问题/提示（支持 Markdown）
  - 最大长度：**10000** 字符（超出会截断）
- `predefined_options`（array，可选）
  - 预定义选项列表，用户可选择其一或多项（以实际前端交互为准）。**接受三种输入形态**（v1.5.20+）：
    1. `list[str]` —— 纯字符串数组，所有选项默认未勾选
    2. `list[dict]` —— `{ "label": str, "default": bool }` 对象数组，
       让推荐选项自带「初始勾选」状态，无需额外参数
    3. `list[str]` 配合 `predefined_options_defaults` —— 见下
  - 单个选项最大长度：**500** 字符
  - 非字符串 / 非 `{label,...}` 元素会被忽略
  - `null` / 不传 / `[]` 表示无预定义选项
- `predefined_options_defaults`（array of bool，可选，v1.5.20+）
  - 与 `list[str]` 形态并行的「默认勾选」数组：每位决定对应选项是否初始
    被勾上。宽容归一化：
    - 真值别名：`True` / `1` / `1.0` / `"true"` / `"yes"` / `"on"` /
      `"selected"`（大小写不敏感、自动 trim）
    - 其它值（含 `None`、`0`、列表、字典）→ `False`
  - 长度对齐：
    - 比 `predefined_options` 长 → 静默截断
    - 比 `predefined_options` 短 → 用 `False` 补足
  - 当 `predefined_options` 已使用 `{label, default}` 形式时，本字段被忽略

#### 返回值

`interactive_feedback` 返回 **MCP 标准 Content 列表**：

- `TextContent`：`{"type":"text","text":"..."}`
  - 包含用户输入文本与/或已选选项
- `ImageContent`：`{"type":"image","data":"<base64>","mimeType":"image/png"}`
  - 用户上传图片（如有），每张图片对应一个条目

#### 运行时行为（概览）

- 确保 Web UI 服务可用
- 通过 Web UI HTTP API 创建任务（`POST /api/tasks`）
- 通过**双通道**等待任务完成：SSE（`GET /api/events`，支持 `Last-Event-ID` 断线
  续传）作为主路径，HTTP 轮询（`GET /api/tasks/{task_id}`）作为安全网（SSE 健康
  时拉成 30s safety net，SSE 掉线时回到 2s 紧密兜底）
- 通过 `ctx.info(...)` 把 `task.created` / `task.notified` / `task.completed`
  等事件回送 MCP client，让 Cursor / Claude Desktop / ChatGPT Desktop 在 chat
  sidebar 实时渲染进度
- 受生产级中间件链保护（`ErrorHandling` + `RateLimiting` 10 req/s burst 20 +
  `Timing` + `Logging`）
- 若发生异常/超时，会返回可配置提示语（见 `feedback.resubmit_prompt`）引导调用方
  重新调用该工具

#### Server 自检 resource

Client 端可以通过 MCP `resources/read` 读取 `aiia://server/info`（MIME
`application/json`，tags `diagnostics` / `self-info`）拿到当前 server 的
JSON 快照：`name` / `version` / `transport` / `runtime`（Python 版本 +
解释器路径 + 平台）/ `fastmcp.version` / `middleware`（中间件链）/
`error_stats` / `web_ui`（host + port + reachability）/ `task_queue`
（initialized + size + pending）。这个 resource 是**只读自检**——绝不会
唤醒 Web UI 子进程或构造新的 task queue 单例，可以放心从状态面板里
轮询。

#### 关于超时

`interactive_feedback` 设计为**长时间运行**工具。

- 前端倒计时由 `feedback.frontend_countdown` 控制（默认 **240s**，范围 **[10, 3600]s**；`0` 或任何非正整数表示关闭倒计时）。
- 后端等待时长（`feedback.backend_max_wait`，范围 **[10, 7200]s**）由“前端倒计时 + 缓冲”推导（精确规则见 `docs/configuration.zh-CN.md`）。

#### 示例

简单提示：

```text
interactive_feedback(message="请确认下一步怎么做。")
```

带选项：

```text
interactive_feedback(
  message="请选择发布策略：",
  predefined_options=["Rebase", "Merge", "暂不处理"]
)
```

带「推荐项预选」（对象形态）：

```text
interactive_feedback(
  message="请选择发布策略：",
  predefined_options=[
    {"label": "Rebase", "default": true},
    {"label": "Merge"},
    {"label": "暂不处理"}
  ]
)
```

等价的并行数组写法：

```text
interactive_feedback(
  message="请选择发布策略：",
  predefined_options=["Rebase", "Merge", "暂不处理"],
  predefined_options_defaults=[true, false, false]
)
```
