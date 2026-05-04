## MCP 工具说明

本项目当前对外暴露 **1 个** MCP 工具：

### Server 级元数据（v1.5.21+）

`initialize` 协议响应中下发以下字段，client（ChatGPT Desktop / Claude Desktop / Cursor 等）会据此呈现 server 列表 UI、向 LLM 提供调用指引：

| 字段           | 内容                                                                                              | 用途                                                |
| -------------- | ------------------------------------------------------------------------------------------------- | --------------------------------------------------- |
| `name`         | `AI Intervention Agent MCP`                                                                       | client 工具列表显示                                 |
| `version`      | 当前包版本（如 `1.5.21`，从 `importlib.metadata` 自动读取，未安装时回退 `0.0.0+local`）           | client 兼容性判断 / 故障排查                        |
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

> 这些字段遵循 MCP 协议规范（spec 2024-11-05+），FastMCP 3.x 原生支持。

---

### `interactive_feedback`

通过 Web UI（浏览器或 VS Code Webview）向用户发起**交互式反馈**请求，并将用户输入结果返回给 MCP 调用方。

#### 参数

- `message`（string，必填）
  - 展示给用户的问题/提示（支持 Markdown）
  - 最大长度：**10000** 字符（超出会截断）
- `predefined_options`（array，可选）
  - 预定义选项列表，用户可选择其一或多项（以实际前端交互为准）
  - 单个选项最大长度：**500** 字符
  - 非字符串选项会被忽略
  - `null` / 不传 / `[]` 表示无预定义选项

#### 返回值

`interactive_feedback` 返回 **MCP 标准 Content 列表**：

- `TextContent`：`{"type":"text","text":"..."}`
  - 包含用户输入文本与/或已选选项
- `ImageContent`：`{"type":"image","data":"<base64>","mimeType":"image/png"}`
  - 用户上传图片（如有），每张图片对应一个条目

#### 运行时行为（概览）

- 确保 Web UI 服务可用
- 通过 Web UI HTTP API 创建任务（`POST /api/tasks`）
- 轮询任务完成（`GET /api/tasks/{task_id}`）直到完成或超时
- 若发生异常/超时，会返回可配置提示语（见 `feedback.resubmit_prompt`）引导调用方重新调用该工具

#### 关于超时

`interactive_feedback` 设计为**长时间运行**工具。

- 前端倒计时由 `feedback.frontend_countdown` 控制（默认 **240s**，最大 **250s**）。
- 后端等待时长由“前端倒计时 + 缓冲”推导（精确规则见 `docs/configuration.zh-CN.md`）。

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
