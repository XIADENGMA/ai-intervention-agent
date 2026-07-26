<div align="center">
  <a href="https://github.com/xiadengma/ai-intervention-agent">
    <img src="src/ai_intervention_agent/icons/icon.svg" width="140" height="140" alt="AI Intervention Agent" />
  </a>

  <h2>AI Intervention Agent</h2>

  <p><strong>给 MCP 智能体加上“实时人工介入” —— 暂停、纠偏、继续。</strong></p>

  <p>
    <a href="https://pypi.org/project/ai-intervention-agent/">
      <img src="https://img.shields.io/pypi/v/ai-intervention-agent?style=flat-square&logo=pypi&logoColor=white&label=PyPI" alt="PyPI" />
    </a>
    <a href="https://www.python.org/downloads/">
      <img src="https://img.shields.io/pypi/pyversions/ai-intervention-agent?style=flat-square&logo=python&logoColor=white" alt="Python versions" />
    </a>
    <a href="https://modelcontextprotocol.io">
      <img src="https://img.shields.io/badge/MCP-Compatible-d97757?style=flat-square&logo=anthropic&logoColor=white" alt="MCP Compatible" />
    </a>
    <a href="https://github.com/xiadengma/ai-intervention-agent/actions/workflows/test.yml">
      <img src="https://img.shields.io/github/actions/workflow/status/xiadengma/ai-intervention-agent/test.yml?branch=main&label=tests&style=flat-square&logo=github" alt="Tests" />
    </a>
    <a href="https://github.com/xiadengma/ai-intervention-agent/actions/workflows/scorecard.yml">
      <img src="https://img.shields.io/github/actions/workflow/status/xiadengma/ai-intervention-agent/scorecard.yml?branch=main&label=OpenSSF&style=flat-square&logo=securityscorecard&logoColor=white" alt="OpenSSF Scorecard" />
    </a>
    <a href="https://github.com/xiadengma/ai-intervention-agent/blob/main/LICENSE">
      <img src="https://img.shields.io/badge/License-MIT-22c55e?style=flat-square" alt="License: MIT" />
    </a>
  </p>

  <p>
    <a href="./README.md">English</a> | 简体中文
  </p>
</div>

---

AI 助手在执行任务时是不是经常自顾自跑偏？AI Intervention Agent 让它**在关键节点先停一下**：弹出 Web UI，让你看清它即将做什么、补一句指示、贴一张截图，然后让它带着你最新的想法继续 —— 全程通过 MCP `interactive_feedback` 工具完成，**不用结束会话**。

支持 `Cursor`、`VS Code`、`Claude Code`、`Augment`、`Windsurf`、`Trae` 等。

## 快速开始

在你的 AI 工具中通过 `uvx` 启动 MCP 服务（自动安装并运行最新版本）：

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

[<img src="https://img.shields.io/badge/Install%20Server-Cursor-black?style=flat-square" alt="一键添加至 Cursor">](https://cursor.com/en/install-mcp?name=ai-intervention-agent&config=eyJjb21tYW5kIjoidXZ4IiwiYXJncyI6WyJhaS1pbnRlcnZlbnRpb24tYWdlbnQiXSwidGltZW91dCI6NjAwLCJhdXRvQXBwcm92ZSI6WyJpbnRlcmFjdGl2ZV9mZWVkYmFjayJdfQ%3D%3D)
[<img src="https://img.shields.io/badge/Install%20Server-VS%20Code-0098FF?style=flat-square" alt="一键添加至 VS Code">](https://vscode.dev/redirect?url=vscode%3Amcp%2Finstall%3F%257B%2522name%2522%253A%2522ai-intervention-agent%2522%252C%2522command%2522%253A%2522uvx%2522%252C%2522args%2522%253A%255B%2522ai-intervention-agent%2522%255D%252C%2522timeout%2522%253A600%252C%2522autoApprove%2522%253A%255B%2522interactive_feedback%2522%255D%257D)

然后把下面的提示词追加到你的智能体规则 / 系统提示词，让智能体通过 `interactive_feedback` 询问你，而不是自行结束任务。

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

<details>
<summary>备选：使用 pip 安装</summary>

先手动安装该包（请记得定期执行 `pip install --upgrade ai-intervention-agent` 获取更新）：

```bash
pip install ai-intervention-agent
```

然后在 AI 工具中配置已安装的入口：

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

</details>

<details>
<summary>备选：让 AI 帮你完成配置</summary>

如果你的 IDE/CLI 自带 AI 智能体（Cursor、Claude Code、VS Code、Windsurf、Trae、Augment 等），直接把下面这段提示词贴进对话框，让它帮你写好配置：

```text
请帮我把 `ai-intervention-agent` MCP 服务接入当前 IDE / AI 工具：

1. 找到当前 IDE 对应的 MCP 配置文件
   （Cursor: `.cursor/mcp.json` 或 `~/.cursor/mcp.json`；
    Claude Code: `~/.claude.json`；
    VS Code: `.vscode/mcp.json`）。
2. 在 `mcpServers` 下加入这一项：
   - command: `uvx`
   - args: `["ai-intervention-agent"]`
   - timeout: 600
   - autoApprove: `["interactive_feedback"]`
3. 把本 README 里的「提示词（可复制）」整段
   追加到我的智能体规则 / 系统提示词，
   让智能体始终通过 `interactive_feedback` 询问我，
   而不是自行结束任务。
4. 列出已加载的 MCP 服务并确认 `ai-intervention-agent` 已生效。
```

</details>

> [!NOTE]
> `interactive_feedback` 是一个**长时间运行**的工具，部分客户端存在硬超时限制。Web UI 提供倒计时 + 自动重调（`feedback.frontend_countdown`，默认 `240` 秒，范围 `0` 或 `[10, 3600]`）以尽量保持会话不断开——默认值处于常见 300 秒硬超时之内。

## 界面截图

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset=".github/assets/desktop_dark_content.png">
    <img alt="桌面端 - 反馈页（多任务标签、代码高亮、预设选项）" src=".github/assets/desktop_light_content.png" width="600" height="625" />
  </picture>
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset=".github/assets/mobile_dark_content.png">
    <img alt="移动端 - 反馈页" src=".github/assets/mobile_light_content.png" width="180" height="590" />
  </picture>
</p>

<p align="center"><sub>反馈页 · 自动跟随深浅色 · 多任务标签独立倒计时</sub></p>

<details>
<summary>更多截图（空状态 + 设置页）</summary>

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset=".github/assets/desktop_dark_no_content.png">
    <img alt="桌面端 - 空状态" src=".github/assets/desktop_light_no_content.png" width="600" height="422" />
  </picture>
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset=".github/assets/mobile_dark_no_content.png">
    <img alt="移动端 - 空状态" src=".github/assets/mobile_light_no_content.png" width="180" height="390" />
  </picture>
</p>

<p align="center"><sub>空状态 · 等待下一次交互请求</sub></p>

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset=".github/assets/desktop_dark_settings.png">
    <img alt="桌面端 - 设置（通知 / Bark / 反馈）" src=".github/assets/desktop_light_settings.png" width="600" height="422" />
  </picture>
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset=".github/assets/mobile_dark_settings.png">
    <img alt="移动端 - 设置" src=".github/assets/mobile_light_settings.png" width="180" height="390" />
  </picture>
</p>

<p align="center"><sub>设置页 · 通知 · Bark · 声音 · 反馈倒计时 · 自动跟随深浅色</sub></p>

</details>

## 主要特性

- **实时介入** —— AI 在关键节点暂停，等待你的指示（通过 `interactive_feedback`）
- **Web UI** —— Markdown / 代码高亮 / 数学公式开箱即用
- **多任务标签页** —— 并发请求各自独立倒计时、每任务草稿自动保存；自动重调保持长会话不断开（归零时优先提交已输入的文本与勾选项，绝不发空提示）
- **输入即延长（typing-hold）** —— 正在输入时倒计时自动延长、归零也绝不打断（Web 页面与 VS Code 插件语义一致）
- **Agent 循环友好** —— 每任务 `header_label` 上下文短标签、`question_type='yesno'` 一键二元决策、`feedback_placeholder` 自定义占位提示
- **通知** —— Web UI / 声音 / 系统通知 / Bark（iOS 推送），支持上传自定义通知音效
- **SSH / 局域网友好** —— 适配 SSH 端口转发；本地网络支持时通过 mDNS 发布 `<host>.local` 入口
- **i18n** —— Web UI + VS Code 插件原生支持 `en` / `zh-CN` / `zh-TW` 三语
- **PWA + 离线可用 + WCAG 2.1 AA 无障碍** —— 可从浏览器安装；对比度 / 焦点管理 / 减弱动态效果均经审计并由不变量测试锁定
- **稳定安装** —— 基于 Flask 3.x + 保守的依赖锁版；免疫 2026 年初 [Starlette 1.0 breaking change](https://github.com/Minidoracat/mcp-feedback-enhanced/issues/213)（该 bug 让若干同类项目默认安装即报错）

## 架构总览

AIIA 以单个 Python 进程运行，桥接三个界面：暴露 `interactive_feedback`
的 MCP stdio server、带 SSE 事件总线的 Flask web server、以及驱动通知
体系的持久化任务队列。组件图、交互 / 异常恢复时序图、agent 端 MCP
参数表与运行时不变量目录见
[`docs/architecture.zh-CN.md`](docs/architecture.zh-CN.md)。

## VS Code 插件（可选）

<p>
  <a href="https://open-vsx.org/extension/xiadengma/ai-intervention-agent">
    <img src="https://img.shields.io/open-vsx/v/xiadengma/ai-intervention-agent?label=Open%20VSX&style=flat-square&logo=eclipseide&logoColor=white" alt="Open VSX version" />
  </a>
  <a href="https://open-vsx.org/extension/xiadengma/ai-intervention-agent">
    <img src="https://img.shields.io/open-vsx/dt/xiadengma/ai-intervention-agent?label=downloads&style=flat-square" alt="Open VSX downloads" />
  </a>
  <a href="https://open-vsx.org/extension/xiadengma/ai-intervention-agent">
    <img src="https://img.shields.io/open-vsx/rating/xiadengma/ai-intervention-agent?label=rating&style=flat-square" alt="Open VSX rating" />
  </a>
</p>

把交互面板放进 VS Code 侧边栏，避免频繁切换浏览器。

- **安装**：[Open VSX](https://open-vsx.org/extension/xiadengma/ai-intervention-agent)、[VS Code Marketplace](https://marketplace.visualstudio.com/items?itemName=xiadengma.ai-intervention-agent)，或从 [GitHub Releases](https://github.com/xiadengma/ai-intervention-agent/releases/latest) 下载 VSIX
- **关键设置**：`ai-intervention-agent.serverUrl` —— 填写你的 Web UI 地址（例如 `http://localhost:8080`；端口可在 [`config.toml.default`](config.toml.default) 的 `web_ui.port` 中修改）
- **更多**：`ai-intervention-agent.logLevel`、macOS 原生通知（默认开启，可在侧边栏「通知设置」面板中关闭）——完整设置项与 AppleScript executor 安全模型详见 [`packages/vscode/README.zh-CN.md`](packages/vscode/README.zh-CN.md)

## 配置说明

首次运行会以 [`config.toml.default`](config.toml.default) 为模板，在用户配置目录创建 `config.toml`——完整 TOML 参考见 [`docs/configuration.zh-CN.md`](docs/configuration.zh-CN.md)：

| 操作系统 | 配置目录位置                                           |
| -------- | ------------------------------------------------------ |
| Linux    | `~/.config/ai-intervention-agent/`                     |
| macOS    | `~/Library/Application Support/ai-intervention-agent/` |
| Windows  | `%APPDATA%/ai-intervention-agent/`                     |

`uvx`、Docker、systemd、SSH 远程等不便编辑文件的场景下，最常用的 `web_ui` 配置可以用环境变量在启动时覆盖（非法值会记 `WARNING` 并安全回退；完整列表见 [`docs/configuration.zh-CN.md#环境变量覆盖`](docs/configuration.zh-CN.md#环境变量覆盖)）：

```bash
export AI_INTERVENTION_AGENT_WEB_UI_HOST=0.0.0.0      # 默认 127.0.0.1
export AI_INTERVENTION_AGENT_WEB_UI_PORT=8181         # 默认 8080，范围 [1, 65535]
export AI_INTERVENTION_AGENT_WEB_UI_LANGUAGE=zh-CN    # auto / en / zh-CN / zh-TW
uvx ai-intervention-agent
```

CLI 自省：`--version`、`--help`、`--print-config`（以 `jq` 友好的 JSON 输出当前生效的 merged 配置，secret 类字段自动 redact——一条命令回答“我的端口到底是 env 覆盖的还是 `config.toml` 写的”）。

iPhone 上最顺手的用法是把 Web UI 包进快捷指令（Shortcuts），再让 Bark 通知点击后直接启动它——分步教程见 [`docs/configuration.zh-CN.md#iphone-推荐用法快捷指令--bark`](docs/configuration.zh-CN.md#iphone-推荐用法快捷指令--bark)。

## 文档

- **文档总索引**（按角色定位）：[`docs/README.zh-CN.md`](docs/README.zh-CN.md) · [`docs/README.md`](docs/README.md)
- **架构**（组件图 + Agent 工作流）：[`docs/architecture.zh-CN.md`](docs/architecture.zh-CN.md)
- **MCP 工具说明**：[`docs/mcp_tools.zh-CN.md`](docs/mcp_tools.zh-CN.md) · [`docs/mcp_tools.md`](docs/mcp_tools.md)
- **API 文档**：[`docs/api.zh-CN/index.md`](docs/api.zh-CN/index.md) · [`docs/api/index.md`](docs/api/index.md)
- **故障排查 / FAQ**：[`docs/troubleshooting.zh-CN.md`](docs/troubleshooting.zh-CN.md) · [`docs/troubleshooting.md`](docs/troubleshooting.md)
- **发布说明**：[`CHANGELOG.md`](CHANGELOG.md) · VS Code 插件 marketplace 专属：[`packages/vscode/CHANGELOG.md`](packages/vscode/CHANGELOG.md)
- **贡献指南**：[`CONTRIBUTING.zh-CN.md`](.github/CONTRIBUTING.zh-CN.md) · [`CODE_OF_CONDUCT.zh-CN.md`](.github/CODE_OF_CONDUCT.zh-CN.md) · 脚本索引：[`scripts/README.md`](scripts/README.md) · i18n 指南：[`docs/i18n.md`](docs/i18n.md)
- **Release 恢复 runbook**：[`docs/release-recovery.zh-CN.md`](docs/release-recovery.zh-CN.md) · [`docs/release-recovery.md`](docs/release-recovery.md)
- **DeepWiki 问答**——AI 辅助的仓库智能问答入口：<a href="https://deepwiki.com/xiadengma/ai-intervention-agent"><img src="https://deepwiki.com/badge.svg" alt="Ask DeepWiki" valign="middle" /></a>

## 同类产品

| 项目 | Stars（约） | 定位 |
| --- | --- | --- |
| [mcp-feedback-enhanced](https://github.com/Minidoracat/mcp-feedback-enhanced)（Minidoracat） | 约 3.8k | 同类中最大；Web UI + Tauri 桌面应用、命令自动执行、SSH Remote / WSL 识别。 |
| [cunzhi](https://github.com/imhuso/cunzhi)（imhuso） | 约 1.4k | 中文项目，专注阻止 AI 过早结束任务。 |
| [Relay](https://glama.ai/mcp/servers/andeya/ide-relay-mcp)（andeya） | 新 | 多 IDE 中继、多 tab 会话合并、原生桌面窗口、Cursor 用量监控。 |
| [interactive-feedback-mcp (Node.js)](https://github.com/wellcomemayhem-spec/interactive-feedback-mcp-nodejs) | 新 | Node.js 实现，WebSocket 实时 UI + OpenAI Whisper 语音转文字。 |
| [interactive-feedback-mcp](https://github.com/junanchn/interactive-feedback-mcp)（junanchn） | 约 50 | Win32 原生置顶窗口、自动回复规则。 |
| [interactive-feedback-mcp](https://github.com/poliva/interactive-feedback-mcp)（poliva） | 约 310 | 直系上游 fork（参见下方致谢）；最精简的 Python MCP，单一反馈对话框。 |
| [interactive-feedback-mcp](https://github.com/Pursue-LLL/interactive-feedback-mcp)（Pursue-LLL） | 约 30 | 体量更小的独立 fork，强调"依赖最少"。 |

**AIIA 在光谱中的位置**：AIIA 走的是**完整运维栈**路线——Web UI 与 VS Code 插件共享同一后端、生产级可观测性（`/metrics` Prometheus 端点 + [参考 Grafana 仪表盘](docs/observability/README.zh-CN.md)）、中英双语 i18n + 双语文档、严格的不变量测试纪律（8,200+ 测试 + 1,050+ subtests，40 cycles 持续审计）、以及 5 个 job 的发布流水线。只想要最轻量的 drop-in？选 poliva 版本。想要桌面应用？mcp-feedback-enhanced。想要语音输入 / 多 tab UI？Relay 或 Node.js 版本。想要完整运维集成？AIIA。

**功能 gap 提示**（欢迎贡献）：语音转文字输入、原生置顶窗口、Cursor 用量监控、多 tab 会话合并 UI。

> 上面的 stars 是粗略快照（最近核对：2026-06），请以各上游为准。欢迎通过 PR 补充其他同类项目。

## 致谢

本项目的源流可上溯到 **Fábio Ferreira**（2024）与 **Pau Oliva**（2025）的原作仓库 [`noopstudios/interactive-feedback-mcp`](https://github.com/noopstudios/interactive-feedback-mcp) 与 [`poliva/interactive-feedback-mcp`](https://github.com/poliva/interactive-feedback-mcp)，他们的工作奠定了 MCP `interactive_feedback` 工具的基础形态。两位作者的版权声明已按 MIT 协议要求保留在 [`LICENSE`](LICENSE) 中。v1.5.x 系列是 [@xiadengma](https://github.com/xiadengma)（PyPI / Open VSX / VS Code Marketplace 发布者）的全面重写，覆盖 Web UI、VS Code 插件、i18n、通知体系、CI/CD 流水线。

## 开源协议

MIT 许可证
