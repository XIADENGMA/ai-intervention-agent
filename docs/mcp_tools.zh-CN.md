## MCP 工具说明

本项目当前对外暴露 **1 个** MCP 工具：

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

