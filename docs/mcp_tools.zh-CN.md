## MCP 工具说明

本项目当前对外暴露 **1 个静态核心** MCP 工具：

### Server 级元数据（v1.5.21+）

`initialize` 协议响应中下发以下字段，client（ChatGPT Desktop / Claude Desktop / Cursor 等）会据此呈现 server 列表 UI、向 LLM 提供调用指引：

| 字段           | 内容                                                                                              | 用途                                                |
| -------------- | ------------------------------------------------------------------------------------------------- | --------------------------------------------------- |
| `name`         | `AI Intervention Agent MCP`                                                                       | client 工具列表显示                                 |
| `version`      | 当前包版本（从 `importlib.metadata` 自动读取，例如 `1.6.0`；未安装时回退 `0.0.0+local`）          | client 兼容性判断 / 故障排查                        |
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

### 动态工具注册结论

MCP `2025-11-25` tools spec 允许 server 声明
`capabilities.tools.listChanged=true`，并在工具列表变化时发送
`notifications/tools/list_changed`。FastMCP 3.2.4 也支持运行时
`add_tool()` / `local_provider.remove_tool()`，并会在 active MCP request
context 内发生 add/remove/enable/disable 时自动发送工具列表变化通知。

AI Intervention Agent **不**把动态注册作为主工具面。`interactive_feedback`
是长时间运行的人机协作入口，必须对所有 client 保持静态可发现。动态注册只作为
未来可选能力：例如实验性诊断工具、loop engineering 辅助工具，或需要认证 /
配置后才可用的条件性能力。

任何动态工具真正上线前，都必须满足以下边界：

- `interactive_feedback` 继续作为静态 fallback 注册。
- 证明目标 client 的刷新行为。VS Code 官方文档说明支持 dynamic tool
  discovery；但 ChatGPT Desktop、Claude Desktop、Cursor 对 mid-session
  `notifications/tools/list_changed` 的刷新行为应先视为未证明或不稳定，直到用
  目标版本实测确认。
- 工具名稳定，长度 1-128，只使用 ASCII 字母/数字/`_`/`-`/`.`。
- 每个动态工具必须有明确 annotations、tags、version、input schema、错误语义、
  速率限制、审计日志和输出脱敏。
- “隐藏不可用工具”不能替代授权。tool handler 内仍必须校验配置、认证状态、
  输入、访问控制、速率限制和敏感输出脱敏。

本地 SDK spike 由 `tests/test_mcp_dynamic_tools_spike_r457.py` 锁定：验证
FastMCP 3.2.4 能动态 add/remove 工具，保留 annotations/tags/version，
在 `on_duplicate="error"` 下拒绝重复 name+version，并确认当前运行时构造参数是
`on_duplicate`，不是部分旧文档里的 `on_duplicate_tools`。

---

### `interactive_feedback`

通过 Web UI（浏览器或 VS Code Webview）向用户发起**交互式反馈**请求，并将用户输入结果返回给 MCP 调用方。

#### 参数

- `message`（string，必填）
  - 展示给用户的问题/提示（支持 Markdown）
  - 最大长度：**1000000** 字符（超出会截断；`task_queue` 仍保留 10 MB 字节硬上限作为 DoS 防御）
- `predefined_options`（array，可选）
  - 预定义选项列表，用户可选择其一或多项（以实际前端交互为准）。**两种规范输入形态**（v1.6.0+）：
    1. **推荐使用** `list[dict]` —— `{ "label": str, "default": bool }`
       对象数组，让推荐选项自带「初始勾选」状态。字段别名：
       `label` / `text` / `value`，`default` / `selected` / `checked`。
    2. `list[str]` —— 纯字符串数组，所有选项默认未勾选。**只在没有
       「推荐项」场景**下使用。
  - 单个选项最大长度：**10000** 字符（超长截断）
  - 非字符串 / 非 `{label,...}` 元素会被忽略
  - `null` / 不传 / `[]` 表示无预定义选项
  - **R167 (v1.6.0+) 移除**：旧版的并行数组形态
    `predefined_options_defaults`（兄弟布尔数组）已被移除——请改用上面的
    `list[dict]` 形态表达"推荐项"。仍然传 `predefined_options_defaults`
    的客户端会被 FastMCP 严格 schema（`additionalProperties: false`）
    用 ToolError 拒掉——这是有意为之的硬错：静默接受会让 LLM 持续
    sample 错形态，永远学不到正确写法。

#### Agent 模式专用参数（Cursor / Composer / Cline / Augment / Trae）

以下 4 个可选参数**专为 Agent / Glass 模式高频调用场景设计**——LLM
在长时间自主流程中会反复 invoke `interactive_feedback`，这 4 个参数让
agent 能按任务预先调整 UI，让用户在 5 秒内完成审阅决策，而不必上下文
切换回去读完整提示。LLM 通过 `tools/list` 的 JSON-Schema description 已
经能看到这些字段；本节是给人类阅读的对照参考。

- `header_label`（string，可选，**最长 16 字符**）
  - 作为任务标签页的显示名称（R700 起优先于机器味的任务 ID；完整 ID
    保留在 tooltip）。示例：`"Auth"`、`"DB"`、`"i18n"`、`"CSS"`。在
    **多任务并发**模式下尤其有用——用户同时面对 3+ 个待审阅任务时，
    一眼即可区分任务领域。借鉴自 `gemini-cli` 的 `ask_user.header`
    schema。
  - 推荐 1 个词，能不带空格就不带空格。超长服务端会自动 clamp；
    省略或传空字符串 → 标签页回退显示任务 ID。

- `question_type`（string，可选，目前只支持 `"yesno"`）
  - 当传 `"yesno"` 时，前端**隐藏文本框**，只渲染一行 Yes / No 按钮
    对。用户点击直接提交字面字符串 `"yes"` 或 `"no"`——省掉
    typing + Submit 两步动作，适合二元决策（批准 / 拒绝、proceed /
    abort、确认删除）。未知值会静默当 `None` 处理，前向兼容未来的
    `"choice"` / `"rating"` 等新类型。借鉴自 `gemini-cli` 的
    `ask_user` schema。

- `feedback_placeholder`（string，可选，**最长 200 字符**）
  - 每任务级别的 textarea placeholder 提示（覆盖全局 i18n
    `page.feedbackPlaceholder` 字符串）。示例：`"粘贴错误堆栈"`、
    `"描述视觉异常"`、`"回复 'ok' 批准 或 'no' + 原因 拒绝"`。仅
    支持单行（超长会静默截断，但响应会带 `placeholder_truncated: true`
    标识，让调用方知道发生了 clamp）。借鉴自 `gemini-cli` 的
    `ask_user` schema。

- `auto_resubmit_timeout`（int，可选，单位秒，默认走
  `feedback.frontend_countdown` = `240`）
  - 每任务级别的前端倒计时覆盖——对低风险确认类任务，agent 不想等
    完整 4 分钟时可以传 `60`；想完全禁用单任务自动重调时传 `0`
    （不影响全局配置）。范围跟随服务端配置（`[0, 3600]`），越界值
    静默 clamp 而非报错。

这 4 个参数可组合使用：典型 Agent 模式调用 = `header_label`（上下文）
+ `feedback_placeholder`（提示） + 二选一：`predefined_options`（多选
chip）或 `question_type='yesno'`（二元按钮）。下方有完整 Agent 模式
调用示例。

#### Loop 工程参数（长程自主循环）

5 个可选元数据字段，面向**多轮循环工作流**（如 Ralph-loop 式"持续迭代
直到 TODO 完成"的长会话）。它们承载每次反馈请求背后的*上下文*，让
人类审阅者在几十轮交互中不丢失脉络。均为纯字符串，随任务存储、跨重启
持久化，并通过 `GET /api/tasks` / `GET /api/tasks/<id>` /
`GET /api/config` / `GET /api/tasks/export` 返回——**不改变**工具行为。

- `loop_id`（string，可选，最长 **64** 字符）——同一循环所有轮次共享
  的稳定标识，如 `"auth-refactor"`。让 UI / 导出可以按长程目标分组。
- `loop_objective`（string，可选，最长 **500** 字符）——循环总目标，
  如 `"迁移 auth 到 PyJWT 2.x 且 API 零破坏"`。
- `loop_phase`（string，可选，最长 **32** 字符）——当前阶段，如
  `"plan"` / `"implement"` / `"verify"` / `"blocked"`。
- `success_criteria`（string，可选，最长 **500** 字符）——循环的完成
  标准，如 `"pytest 全绿 + 文档更新"`。
- `iteration_label`（string，可选，最长 **32** 字符）——人类可读的轮次
  标记，如 `"iter-3"` / `"round 7/10"`；随任务展示，让审阅者一眼看到
  循环进度。

5 个字段与 `header_label` 走同一套 normalize：首尾空白去除、空串归
`None`、超长服务端截断、非字符串静默忽略。普通（非循环）调用完全
省略即可——工具行为与之前逐字节一致。

已完成的循环轮次会额外记入有界的内存台账（20 个 loop × 每个 50 轮；
verdict 文本截断 200 字符、图片只记数量），台账不受常规「完成任务
10 秒清理」影响且跨服务重启保留。`GET /api/loops` 按 `loop_id` 聚合
返回台账与该 loop 仍在队列中的任务，让审阅者可以回放「这个目标经历
了哪几轮、每轮人说了什么」。

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
- 后端等待时长（`feedback.backend_max_wait`，范围 **[10, 7200]s**）由"前端倒计时 + 缓冲"推导（精确规则见 `docs/configuration.zh-CN.md`）。

#### 示例

简单提示（无推荐项—— `list[str]` 形态）：

```text
interactive_feedback(
  message="请选择发布策略：",
  predefined_options=["Rebase", "Merge", "暂不处理"]
)
```

带「推荐项预选」（**推荐使用** `list[dict]` 形态）：

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

不带选项的简单提示：

```text
interactive_feedback(message="请确认下一步怎么做。")
```

#### Agent 模式示例（Cursor / Glass）

长时间运行的 Cursor agent 正在重构 auth 模块，需要在跑集成测试之前
征求用户同意。组合 **4 个 Agent 模式参数**，让用户在 5 秒内决策：

```text
interactive_feedback(
  message=(
    "我重构了 `auth/session.py::renew_token()`，迁移到 PyJWT 2.x 新 API：\n"
    "- 移除老的 `algorithms` kwarg fallback\n"
    "- 把 `jwt.PyJWTError` 换成 `jwt.InvalidTokenError`\n"
    "- 新增 30s 时钟漂移容忍\n\n"
    "**是否同意运行 auth 集成测试套件？**"
  ),
  header_label="Auth",                      # 1 个词 chip 显示在 prompt 上方
  feedback_placeholder=                     # 用户回复文本框提示
    "回复 'ok' 跑测试，或 'no' + 原因 回滚",
  question_type="yesno",                    # 二元 → 显示 2 个按钮
  auto_resubmit_timeout=120,                # 单任务 2 分钟代替默认 4 分钟
)
```

UX 效果：用户看到 `Auth` chip + 1 段清晰摘要 + Yes/No 按钮，一键提
交无需打字。若用户超过 2 分钟未响应，agent 会拿到 resubmit prompt
（而非被卡满 4 分钟）。`header_label` / `question_type` /
`feedback_placeholder` / `auto_resubmit_timeout` 完整语义见上方
[Agent 模式专用参数](#agent-模式专用参数cursor--composer--cline--augment--trae)
小节。
