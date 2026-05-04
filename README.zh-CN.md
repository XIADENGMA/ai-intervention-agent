<div align="center">
  <a href="https://github.com/xiadengma/ai-intervention-agent">
    <img src="icons/icon.svg" width="160" height="160" alt="AI Intervention Agent" />
  </a>

  <h2>AI Intervention Agent</h2>

  <p><strong>让 MCP 智能体支持“实时人工介入”。</strong></p>

  <p>
    <a href="https://github.com/xiadengma/ai-intervention-agent/actions/workflows/test.yml">
      <img src="https://img.shields.io/github/actions/workflow/status/xiadengma/ai-intervention-agent/test.yml?branch=main&style=flat-square" alt="Tests" />
    </a>
    <a href="https://github.com/xiadengma/ai-intervention-agent/actions/workflows/scorecard.yml">
      <img src="https://img.shields.io/github/actions/workflow/status/xiadengma/ai-intervention-agent/scorecard.yml?branch=main&label=OpenSSF%20Scorecard&style=flat-square" alt="OpenSSF Scorecard" />
    </a>
    <a href="https://github.com/xiadengma/ai-intervention-agent/actions/workflows/codeql.yml">
      <img src="https://img.shields.io/github/actions/workflow/status/xiadengma/ai-intervention-agent/codeql.yml?branch=main&label=CodeQL&style=flat-square" alt="CodeQL" />
    </a>
    <a href="https://pypi.org/project/ai-intervention-agent/">
      <img src="https://img.shields.io/pypi/v/ai-intervention-agent?style=flat-square" alt="PyPI" />
    </a>
    <a href="https://www.python.org/downloads/">
      <img src="https://img.shields.io/pypi/pyversions/ai-intervention-agent?style=flat-square" alt="Python Versions" />
    </a>
    <a href="https://open-vsx.org/extension/xiadengma/ai-intervention-agent">
      <img src="https://img.shields.io/open-vsx/v/xiadengma/ai-intervention-agent?label=Open%20VSX&style=flat-square" alt="Open VSX" />
    </a>
    <a href="https://open-vsx.org/extension/xiadengma/ai-intervention-agent">
      <img src="https://img.shields.io/open-vsx/dt/xiadengma/ai-intervention-agent?label=Open%20VSX%20downloads&style=flat-square" alt="Open VSX Downloads" />
    </a>
    <a href="https://open-vsx.org/extension/xiadengma/ai-intervention-agent">
      <img src="https://img.shields.io/open-vsx/rating/xiadengma/ai-intervention-agent?label=Open%20VSX%20rating&style=flat-square" alt="Open VSX Rating" />
    </a>
    <a href="https://deepwiki.com/xiadengma/ai-intervention-agent">
      <img src="https://deepwiki.com/badge.svg" alt="Ask DeepWiki" />
    </a>
    <a href="https://github.com/xiadengma/ai-intervention-agent/blob/main/LICENSE">
      <img src="https://img.shields.io/github/license/xiadengma/ai-intervention-agent?style=flat-square" alt="License" />
    </a>
  </p>

  <p>
    <a href="./README.md">English</a> | 简体中文
  </p>
</div>

使用 AI CLI/IDE 时，经常会出现偏离预期的情况。这个项目提供一种简单方式：在关键节点**干预智能体**，通过 Web UI 展示上下文，并用 `interactive_feedback` 收集你的输入/选择/图片，让 AI 以你最新的要求继续任务。

支持 `Cursor`、`VS Code`、`Claude Code`、`Augment`、`Windsurf`、`Trae` 等。

## 快速开始

### 方式一：使用 `uvx` 启动（推荐）

[<img src="https://img.shields.io/badge/Install%20Server-Cursor-black?style=flat-square" alt="一键添加至 Cursor">](https://cursor.com/en/install-mcp?name=ai-intervention-agent&config=eyJjb21tYW5kIjoidXZ4IiwiYXJncyI6WyJhaS1pbnRlcnZlbnRpb24tYWdlbnQiXSwidGltZW91dCI6NjAwLCJhdXRvQXBwcm92ZSI6WyJpbnRlcmFjdGl2ZV9mZWVkYmFjayJdfQ%3D%3D)
[<img src="https://img.shields.io/badge/Install%20Server-VS%20Code-0098FF?style=flat-square" alt="一键添加至 VS Code">](https://vscode.dev/redirect?url=vscode%3Amcp%2Finstall%3F%257B%2522name%2522%253A%2522ai-intervention-agent%2522%252C%2522command%2522%253A%2522uvx%2522%252C%2522args%2522%253A%255B%2522ai-intervention-agent%2522%255D%252C%2522timeout%2522%253A600%252C%2522autoApprove%2522%253A%255B%2522interactive_feedback%2522%255D%257D)

在你的 AI 工具中直接通过 `uvx` 启动 MCP 服务（该方式会自动安装并运行最新版本）：

```json
{
  "mcpServers": {
    "ai-intervention-agent": {
      "command": "uvx",
      "args": ["ai-intervention-agent"],
      "timeout": 600,
      "autoApprove": ["interactive_feedback"]
    }
  }
}
```

### 方式二：使用 `pip` 启动

1. 首先手动安装该包（请记得定期执行 `pip install --upgrade ai-intervention-agent` 获取更新）：

```bash
pip install ai-intervention-agent
```

2. 在你的 AI 工具中配置已安装的 MCP 服务：

```json
{
  "mcpServers": {
    "ai-intervention-agent": {
      "command": "ai-intervention-agent",
      "args": [],
      "timeout": 600,
      "autoApprove": ["interactive_feedback"]
    }
  }
}
```

> [!NOTE]
> `interactive_feedback` 是一个**长时间运行**的工具。有些客户端存在硬超时限制，因此 Web UI 提供倒计时 + 自动重调（到点自动提交）以尽量保持会话不断开。
>
> - 默认：`feedback.frontend_countdown=240` 秒
> - 范围：`0`（禁用）或 `[10, 3600]` 秒。默认 240 秒处于常见 300 秒会话硬超时之内；
>   若客户端允许更长的轮次，可根据需要主动上调。

3.（可选）自定义配置：

- 首次运行会在用户配置目录创建 `config.toml`（详见 [docs/configuration.zh-CN.md](docs/configuration.zh-CN.md)）。
- 示例：

```toml
[web_ui]
port = 8080

[feedback]
frontend_countdown = 240
backend_max_wait = 600
```

<details>
<summary>提示词（可复制）</summary>

```text
- **只能通过 MCP `ai-intervention-agent` 对我进行询问，禁止直接询问或结束任务询问**
- **如果调用工具发生错误，需要坚持再次使用 `ai-intervention-agent` 询问，而不是自作主张，直到工具调用成功**

ai-intervention-agent 工具使用细节：

- 需求不明确时使用 `ai-intervention-agent` 询问澄清，提供预定义选项
- 在有多个方案的时候，需要使用 `ai-intervention-agent` 询问，而不是自作主张
- 在有方案/策略需要更新时，需要使用 `ai-intervention-agent` 询问，而不是自作主张
- 即将完成请求前必须调用 `ai-intervention-agent` 请求反馈
- 在没有明确通过使用 `ai-intervention-agent` 询问并得到可以完成任务/结束时，禁止主动结束对话/请求
```

</details>

## 界面截图

<p align="center">
  <img src=".github/assets/desktop_light_content.png" alt="桌面端 - 反馈页（浅色）" style="height: 320px; margin-right: 12px;" />
  <img src=".github/assets/mobile_light_content.png" alt="移动端 - 反馈页（浅色）" style="height: 320px;" />
</p>

<p align="center"><sub>反馈页（浅色模式）</sub></p>

<details>
<summary>更多截图</summary>

<p align="center">
  <img src=".github/assets/desktop_light_no_content.png" alt="桌面端 - 空状态（浅色）" style="height: 320px; margin-right: 12px;" />
  <img src=".github/assets/mobile_light_no_content.png" alt="移动端 - 空状态（浅色）" style="height: 320px;" />
</p>

<p align="center"><sub>空状态（浅色模式）</sub></p>

<p align="center">
  <img src=".github/assets/desktop_dark_content.png" alt="桌面端 - 反馈页（深色）" style="height: 320px; margin-right: 12px;" />
  <img src=".github/assets/mobile_dark_content.png" alt="移动端 - 反馈页（深色）" style="height: 320px;" />
</p>

<p align="center"><sub>反馈页（深色模式）</sub></p>

<p align="center">
  <img src=".github/assets/desktop_dark_no_content.png" alt="桌面端 - 空状态（深色）" style="height: 320px; margin-right: 12px;" />
  <img src=".github/assets/mobile_dark_no_content.png" alt="移动端 - 空状态（深色）" style="height: 320px;" />
</p>

<p align="center"><sub>空状态（深色模式）</sub></p>

<p align="center">
  <img src=".github/assets/desktop_screenshot.png" alt="桌面端 - 设置" style="height: 320px; margin-right: 12px;" />
  <img src=".github/assets/mobile_screenshot.png" alt="移动端 - 设置" style="height: 320px;" />
</p>

<p align="center"><sub>设置页（深色）</sub></p>

</details>

## 主要特性

- **实时介入**：AI 在关键节点暂停，等待你的指示
- **Web UI**：Markdown / 代码高亮 / 数学公式渲染
- **多任务**：多任务标签页切换，每个任务独立倒计时
- **自动重调**：倒计时到点自动提交，减少会话超时中断
- **通知**：Web UI / 声音 / 系统通知 / Bark
- **远程友好**：适配 SSH 端口转发等远程开发场景
- **MCP 协议规范**（2025-11-25）：工具注解 + Server 身份元数据 + 自包含图标，让 ChatGPT Desktop / Claude Desktop / Cursor 原生识别工具语义，不再每次弹「危险操作」二次确认

## 工作原理

1. AI 客户端调用 MCP 工具 `interactive_feedback`。
2. MCP 服务进程确保 Web UI 子进程可用，然后通过 HTTP 创建任务（`POST /api/tasks`）。
3. 浏览器（或 VS Code Webview）通过轮询 Web UI API 渲染任务列表与倒计时。
4. 你提交反馈后，Web UI 会在任务队列中完成对应任务。
5. MCP 服务进程轮询任务完成（`GET /api/tasks/{task_id}`），并将反馈（文本 + 图片）返回给 AI 客户端。
6. （可选）MCP 服务进程会按配置触发通知（Bark / 系统通知 / 声音 / Web 提示）。

## VS Code 插件（可选）

| 项目                        | 说明                                                                                                                                                                                                                                      |
| --------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 用途                        | 把交互面板放进 VS Code 侧边栏，避免频繁切换浏览器。                                                                                                                                                                                       |
| 安装（Open VSX）            | [Open VSX](https://open-vsx.org/extension/xiadengma/ai-intervention-agent)                                                                                                                                                                |
| 下载 VSIX（GitHub Release） | [GitHub Releases](https://github.com/xiadengma/ai-intervention-agent/releases/latest)                                                                                                                                                     |
| 设置                        | `ai-intervention-agent.serverUrl`（填写你的 Web UI 地址，例如 `http://localhost:8080`；端口可在 [`config.toml.default`](config.toml.default) 的 `web_ui.port` 中修改）                                                                    |
| 其他设置                    | `ai-intervention-agent.logLevel`（Output → AI Intervention Agent）。macOS 原生通知默认开启，可在侧边栏「通知设置」面板中关闭。完整设置项与 AppleScript executor 安全模型详见 [`packages/vscode/README.zh-CN.md`](packages/vscode/README.zh-CN.md)。                                                                                              |

## 配置说明

| 项目                 | 说明                                                                               |
| -------------------- | ---------------------------------------------------------------------------------- |
| 配置文档（英文）     | [docs/configuration.md](docs/configuration.md)                                     |
| 配置文档（简体中文） | [docs/configuration.zh-CN.md](docs/configuration.zh-CN.md)                         |
| 默认模板             | [`config.toml.default`](config.toml.default)（首次运行会自动复制为 `config.toml`） |

| 操作系统 | 配置目录位置                                           |
| -------- | ------------------------------------------------------ |
| Linux    | `~/.config/ai-intervention-agent/`                     |
| macOS    | `~/Library/Application Support/ai-intervention-agent/` |
| Windows  | `%APPDATA%/ai-intervention-agent/`                     |

## 架构

```mermaid
flowchart TD
  subgraph CLIENTS["AI 客户端"]
    AI_CLIENT["AI CLI / IDE<br/>(Cursor, VS Code, Claude Code, ...)"]
  end

  subgraph MCP_PROC["MCP 服务进程（Python）"]
    MCP_SRV["ai-intervention-agent<br/>(server.py / FastMCP)"]
    MCP_TOOL["MCP 工具<br/>interactive_feedback"]
    SVC_MGR["服务管理<br/>(ServiceManager)"]
    CFG_MGR_MCP["配置管理<br/>(config_manager.py)"]
    NOTIF_MGR["通知管理<br/>(notification_manager.py)"]
    NOTIF_PROVIDERS["Providers<br/>(notification_providers.py)"]
    MCP_SRV --> MCP_TOOL
    MCP_SRV --> CFG_MGR_MCP
    MCP_SRV --> NOTIF_MGR
    NOTIF_MGR --> NOTIF_PROVIDERS
  end

  subgraph WEB_PROC["Web UI 进程（Python / Flask）"]
    WEB_SRV["Web UI 服务<br/>(web_ui.py / Flask)"]
    WEB_CFG_MGR["配置管理<br/>(config_manager.py)"]
    HTTP_API["HTTP API<br/>(/api/*)"]
    TASK_Q["任务队列<br/>(task_queue.py)"]
    WEB_FRONTEND["浏览器前端<br/>(static/js/app.js + multi_task.js)"]
    WEB_SRV --> HTTP_API
    WEB_SRV --> TASK_Q
    WEB_SRV --> WEB_CFG_MGR
    WEB_FRONTEND <-->|轮询 /api/tasks| HTTP_API
    WEB_FRONTEND -->|提交反馈| HTTP_API
  end

  subgraph VSCODE_PROC["VS Code 插件（Node）"]
    VSCODE_EXT["扩展宿主<br/>(packages/vscode/extension.js)"]
    VSCODE_WEBVIEW["Webview 前端<br/>(webview.js + webview-ui.js<br/>+ webview-notify-core.js + webview-settings-ui.js)"]
    VSCODE_EXT --> VSCODE_WEBVIEW
    VSCODE_WEBVIEW <-->|轮询 /api/tasks| HTTP_API
    VSCODE_WEBVIEW -->|提交反馈| HTTP_API
  end

  subgraph USER_UI["用户界面"]
    BROWSER["浏览器<br/>(桌面/移动端)"]
    VSCODE["VS Code<br/>(侧边栏面板)"]
    USER["用户"]
  end

  CFG_FILE["config.toml<br/>(用户配置目录)"]

  AI_CLIENT -->|MCP 调用| MCP_TOOL
  MCP_TOOL -->|启动/检查 Web UI| SVC_MGR
  SVC_MGR -->|spawn/monitor| WEB_SRV

  USER -->|输入/点击| WEB_FRONTEND
  USER -->|输入/点击| VSCODE_WEBVIEW
  BROWSER -->|加载界面| WEB_FRONTEND
  VSCODE -->|渲染界面| VSCODE_WEBVIEW

  MCP_TOOL -->|"HTTP POST /api/tasks"| HTTP_API
  MCP_TOOL -->|"HTTP GET /api/tasks/{task_id}"| HTTP_API

  WEB_CFG_MGR <-->|读写 + watcher| CFG_FILE
  CFG_MGR_MCP <-->|读写 + watcher| CFG_FILE

  MCP_TOOL -->|触发通知| NOTIF_MGR
  NOTIF_PROVIDERS -->|系统通知 / 声音 / Bark / Web 提示| USER
```

## 文档

- **文档总索引**（按角色定位）：[`docs/README.zh-CN.md`](docs/README.zh-CN.md) · [`docs/README.md`](docs/README.md)
- **脚本索引**（CI 门禁 / 生成器 / QA）：[`scripts/README.md`](scripts/README.md)
- **发布说明**：[`CHANGELOG.md`](CHANGELOG.md) · VS Code 插件 marketplace 专属：[`packages/vscode/CHANGELOG.md`](packages/vscode/CHANGELOG.md)
- **贡献指南**：[`CONTRIBUTING.md`](CONTRIBUTING.md) · [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md)
- **API 文档（英文）**：[`docs/api/index.md`](docs/api/index.md)
- **API 文档（简体中文）**：[`docs/api.zh-CN/index.md`](docs/api.zh-CN/index.md)
- **MCP 工具说明（英文）**：[`docs/mcp_tools.md`](docs/mcp_tools.md)
- **MCP 工具说明（简体中文）**：[`docs/mcp_tools.zh-CN.md`](docs/mcp_tools.zh-CN.md)
- **故障排查 / FAQ**：[`docs/troubleshooting.zh-CN.md`](docs/troubleshooting.zh-CN.md) · [`docs/troubleshooting.md`](docs/troubleshooting.md)
- **i18n 贡献指南（英文）**：[`docs/i18n.md`](docs/i18n.md)
- **DeepWiki**：[deepwiki.com/xiadengma/ai-intervention-agent](https://deepwiki.com/xiadengma/ai-intervention-agent)

## 同类产品

1. [interactive-feedback-mcp](https://github.com/poliva/interactive-feedback-mcp)
2. [mcp-feedback-enhanced](https://github.com/Minidoracat/mcp-feedback-enhanced)
3. [cunzhi](https://github.com/imhuso/cunzhi)
4. [other interactive-feedback-mcp](https://github.com/Pursue-LLL/interactive-feedback-mcp)

## 致谢

本项目的源流可上溯到 **Fábio Ferreira**（2024）与 **Pau Oliva**（2025）的原作仓库 [`noopstudios/interactive-feedback-mcp`](https://github.com/noopstudios/interactive-feedback-mcp) 与 [`poliva/interactive-feedback-mcp`](https://github.com/poliva/interactive-feedback-mcp)，他们的工作奠定了 MCP `interactive_feedback` 工具的基础形态。两位作者的版权声明已按 MIT 协议要求保留在 [`LICENSE`](LICENSE) 中。v1.5.x 系列是 [@xiadengma](https://github.com/xiadengma)（PyPI / Open VSX / VS Code Marketplace 发布者）的全面重写，覆盖 Web UI、VS Code 插件、i18n、通知体系、CI/CD 流水线。

## 开源协议

MIT 许可证
