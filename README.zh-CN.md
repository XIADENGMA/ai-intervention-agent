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

1. 安装：

```bash
pip install ai-intervention-agent

# 或
uv add ai-intervention-agent
```

2. 在你的 AI 工具中配置 MCP（推荐用 `uvx` 启动）：

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

> [!NOTE] > `interactive_feedback` 是一个**长时间等待**的工具。有些客户端存在硬超时限制，因此 Web UI 提供倒计时 + 自动提交（自动重调）以尽量保持会话不断开。

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
- **Web 界面**：Markdown / 代码高亮 / 数学公式渲染
- **多任务**：多任务标签页切换，每个任务独立倒计时
- **自动重调**：倒计时到点自动提交，减少会话超时中断
- **通知**：Web / 声音 / 系统通知 / Bark
- **远程友好**：适配 SSH 端口转发等远程开发场景

## VS Code 插件（可选）

| 项目                        | 说明                                                                                                                                                                     |
| --------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 用途                        | 把交互面板放进 VS Code 侧边栏，避免频繁切换浏览器。                                                                                                                      |
| 安装（Open VSX）            | [Open VSX](https://open-vsx.org/extension/xiadengma/ai-intervention-agent)                                                                                               |
| 下载 VSIX（GitHub Release） | [GitHub Releases](https://github.com/xiadengma/ai-intervention-agent/releases/latest)                                                                                    |
| 设置                        | `ai-intervention-agent.serverUrl`（填写你的 Web UI 地址，例如 `http://localhost:8080`；端口可在 [`config.jsonc.default`](config.jsonc.default) 的 `web_ui.port` 中修改） |

## 配置说明

| 项目                 | 说明                                                                                  |
| -------------------- | ------------------------------------------------------------------------------------- |
| 配置文档（English）  | [docs/configuration.md](docs/configuration.md)                                        |
| 配置文档（简体中文） | [docs/configuration.zh-CN.md](docs/configuration.zh-CN.md)                            |
| 默认模板             | [`config.jsonc.default`](config.jsonc.default)（首次运行会自动复制为 `config.jsonc`） |

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

  subgraph MCP_PROC["MCP 服务进程"]
    MCP_SRV["ai-intervention-agent<br/>(server.py)"]
    MCP_TOOL["MCP 工具<br/>interactive_feedback"]
    CFG_MGR["配置管理<br/>(config_manager.py)"]
    NOTIF_MGR["通知管理<br/>(notification_manager.py)"]
  end

  subgraph WEB_PROC["Web UI 进程"]
    WEB_SRV["Web UI 服务<br/>(web_ui.py / Flask)"]
    HTTP_API["HTTP API<br/>(/api/*)"]
    TASK_Q["任务队列<br/>(task_queue.py)"]
    WEB_SRV --> HTTP_API
    WEB_SRV --> TASK_Q
  end

  subgraph USER_UI["用户界面"]
    BROWSER["浏览器"]
    VSCODE["VS Code 插件<br/>(Webview)"]
  end

  CFG_FILE["config.jsonc<br/>(用户配置目录)"]

  AI_CLIENT -->|MCP 调用| MCP_TOOL
  MCP_SRV -->|对外提供| MCP_TOOL

  MCP_TOOL -->|确保 Web UI 运行| WEB_SRV
  MCP_TOOL <-->|创建任务 / 轮询结果| HTTP_API

  BROWSER <-->|HTTP| HTTP_API
  VSCODE <-->|HTTP| HTTP_API

  CFG_MGR <-->|读写| CFG_FILE
  WEB_SRV <-->|读取| CFG_FILE

  MCP_SRV --> NOTIF_MGR
  NOTIF_MGR -->|Web / 声音 / 系统通知 / Bark| USER["用户"]
```

## 文档

- **API 文档索引（简体中文）**：[`docs/api.zh-CN/index.md`](docs/api.zh-CN/index.md)
- **API Docs (English)**：[`docs/api/index.md`](docs/api/index.md)
- **DeepWiki**：[deepwiki.com/xiadengma/ai-intervention-agent](https://deepwiki.com/xiadengma/ai-intervention-agent)

## 同类产品

1. [interactive-feedback-mcp](https://github.com/poliva/interactive-feedback-mcp)
2. [mcp-feedback-enhanced](https://github.com/Minidoracat/mcp-feedback-enhanced)
3. [cunzhi](https://github.com/imhuso/cunzhi)
4. [other interactive-feedback-mcp](https://github.com/Pursue-LLL/interactive-feedback-mcp)

## 开源协议

MIT License
