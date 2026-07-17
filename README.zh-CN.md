<div align="center">
  <a href="https://github.com/xiadengma/ai-intervention-agent">
    <img src="src/ai_intervention_agent/icons/icon.svg" width="160" height="160" alt="AI Intervention Agent" />
  </a>

  <h2>AI Intervention Agent</h2>

  <p><strong>给 MCP 智能体加上“实时人工介入” —— 暂停、纠偏、继续。</strong></p>

  <p>
    <a href="https://pypi.org/project/ai-intervention-agent/">
      <img src="https://img.shields.io/pypi/v/ai-intervention-agent?style=for-the-badge&logo=pypi&logoColor=white&color=a855f7&label=PyPI" alt="PyPI" />
    </a>
    <a href="https://modelcontextprotocol.io">
      <img src="https://img.shields.io/badge/MCP-Compatible-d97757?style=for-the-badge&logo=anthropic&logoColor=white" alt="MCP Compatible" />
    </a>
    <a href="https://github.com/xiadengma/ai-intervention-agent/blob/main/LICENSE">
      <img src="https://img.shields.io/badge/License-MIT-22c55e?style=for-the-badge" alt="License: MIT" />
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

### 最快：让 AI 帮你完成配置

如果你的 IDE/CLI 自带 AI 智能体（Cursor、Claude Code、VS Code、Windsurf、Trae、Augment 等），直接把下面这段提示词贴进对话框，让它帮你写好配置。

<details>
<summary>点击展开复制安装提示词</summary>

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
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset=".github/assets/desktop_dark_content.png">
    <img alt="桌面端 - 反馈页（多任务标签、代码高亮、预设选项）" src=".github/assets/desktop_light_content.png" width="600" height="501" />
  </picture>
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset=".github/assets/mobile_dark_content.png">
    <img alt="移动端 - 反馈页" src=".github/assets/mobile_light_content.png" width="180" height="447" />
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

- ⚡ **实时介入** —— AI 在关键节点暂停，等待你的指示（通过 `interactive_feedback`）
- 🖥️ **Web UI** —— Markdown / 代码高亮 / 数学公式开箱即用
- 🗂️ **多任务标签页** —— 多个并发请求各自独立倒计时
- 🔁 **自动重调** —— 倒计时到点自动提交，保持长会话不被客户端硬超时切断；**正在输入时自动延长倒计时且归零也不打断**，归零时**优先提交已输入的文本与勾选项**而不是空提示，后端等待会跟随延长，输入内容零丢失
- 🔔 **通知** —— Web UI / 声音 / 系统通知 / Bark（loopback URL 自动过滤；设置面板会推荐对应的 LAN IP）
- 🌐 **SSH / 局域网友好** —— 适配 SSH 端口转发；本地网络支持时会通过 mDNS 自动发布 `<host>.local` 入口
- 🏷️ **Header 标签 & Yes/No 按钮** —— Agent 可以为任务附加 ≤16 字符的 `header_label` 短标签（如 "Auth"/"DB"/"i18n"）提供上下文 cue；或者用 `question_type='yesno'` 让 UI 渲染一键确认/拒绝按钮（代替长文本框）。来自 `gemini-cli` `ask_user` 模式借鉴
- 🎨 **自定义占位提示** —— 每个任务可以由 Agent 指定 `feedback_placeholder`（200 字符上限），覆盖默认 i18n 占位文本
- 🌏 **i18n** —— Web UI + VS Code 插件原生支持 `en` / `zh-CN` / `zh-TW` 三语；另含 pseudo-locale 用于翻译覆盖测试
- ⚡ **生产力快捷键** —— 按 `?` 弹出键盘快捷键速查表；反馈输入框 **per-task 草稿自动保存**（reload 不丢）；可配置 **提交模式**（Ctrl/Cmd+Enter vs Enter）；带三阶段配色阈值的实时 **字符计数器**
- 💬 **常用回复 / 快捷短语** —— 把常用反馈保存到 `localStorage`，支持编辑 / 删除 / 一键插入；JSON 导出 + 导入，便于跨设备 / 跨浏览器迁移
- 🔊 **自定义通知音效** —— 上传自己的音频文件（mp3/wav/ogg/m4a/flac，≤ 700 KB，≤ 30s）替代默认提示音；base64 持久化到 `localStorage`，session 之间不丢
- ⏱️ **输入即延长** —— 正在输入时倒计时自动延长、归零也绝不打断（无需任何手动按钮；两端一致的 typing-hold 语义，替代旧版 `+60s`/❄️ 冻结按钮）
- 🟢 **SSE 实时状态指示** —— 角落 3 态徽章（绿/橙/红）提示与后端的同步状况
- 📱 **PWA 安装支持** —— 提供 `manifest.webmanifest` + Service Worker，Web UI 可通过浏览器原生入口安装（Chrome / Edge 地址栏图标，或 iOS Safari 分享 → 添加到主屏幕）；为 iOS Safari 单独提供引导横幅指向系统原生入口（iOS 不触发 `beforeinstallprompt`，需要单独提示）；支持永久关闭
- 📡 **离线可用** —— Service Worker 预缓存品牌化 `offline.html`，含中英双语重连提示、深浅色主题 + `prefers-reduced-motion` 支持，以及服务恢复后自动 reload 的后台 ping（替代浏览器默认 "无法访问此网站" 错误页）
- ♿ **WCAG 2.1 AA 无障碍** —— 所有焦点指示器、正文、状态色、模态浮层、主/次按钮、图标按钮均通过 WCAG 2.1 AA 对比度 + Name/Role/Value 审计（cycles 1-40 累计 240+ a11y / 正确性 / 一致性 / 并发安全 / API 契约 invariants 与 8,200+ 测试，每个 cycle 都引入新的 meta-lint 模式：setting 标签必须 i18n、async reset 必须二次确认、finally 块 DOM 引用必须 null-guard，cycle-35 **AST-based 锁获取顺序契约**，cycle-38 **跨运行时资源生命周期审计** (Python/Browser-JS/VS Code TS)，cycle-40 新增 **OpenAPI docstring 覆盖** + **i18n 未翻译键检测**）；键盘快捷键浮层 Tab trap + 关闭时恢复 opener 焦点；三个 `role="dialog"` 模态（设置、图片预览、代码粘贴）拥有一致的 ESC + 关闭按钮 + backdrop 点击关闭行为；支持 `prefers-reduced-motion` 与 `prefers-contrast: more` 适配系统高对比模式
- 🛡️ **稳定安装** —— 基于 Flask 3.x + 保守的依赖锁版
  - 免疫 2026 年初 [Starlette 1.0 breaking change](https://github.com/Minidoracat/mcp-feedback-enhanced/issues/213) —— 该 bug 让若干 MCP feedback 同类项目 `uvx ...@latest` 默认安装即报错

> 工作原理、架构图、生产级中间件、Server 自检 resource、MCP 协议规范支持
> 等技术细节请参考 [`docs/api.zh-CN/index.md`](docs/api.zh-CN/index.md) 与
> [`docs/mcp_tools.zh-CN.md`](docs/mcp_tools.zh-CN.md)。

## 架构总览

俯瞰视角看 AIIA 各组件如何拼接——在集成新客户端（自定义 MCP 主机、
其他 IDE 插件）或定位跨组件问题时特别有用。

```mermaid
graph LR
    subgraph Clients["客户端 (任何 MCP 主机)"]
        A1[LLM Agent<br/>Cursor / Cline / Augment]
        A2[Web 浏览器<br/>多任务面板]
        A3[VS Code 插件<br/>侧边栏 webview]
        A4[CLI<br/>--print-config / --version]
    end

    subgraph Backend["AIIA 后端 (单 Python 进程)"]
        B1[MCP server<br/>stdio + interactive_feedback]
        B2[Flask web server<br/>/api/* + SSE bus]
        B3[Task queue<br/>读写锁 + 持久化]
        B4[Notification manager<br/>浏览器 / 系统 / Bark]
        B5[Config manager<br/>TOML + 环境变量覆盖]
    end

    subgraph External["外部"]
        E1[文件系统<br/>config.toml + tasks.json]
        E2[浏览器 / OS<br/>系统通知]
        E3[Bark API<br/>iOS 推送]
    end

    A1 -- MCP stdio --> B1
    A2 -- HTTP + SSE --> B2
    A3 -- HTTP + SSE --> B2
    A4 -- 模块导入 --> B5

    B1 -- 入队任务 --> B3
    B2 -- 读 / 改 --> B3
    B3 -- task_changed 事件 --> B2
    B2 -- "广播 SSE<br/>(R51-B 心跳 25s)" --> A2
    B2 -- 广播 SSE --> A3
    B3 -- on add_task --> B4
    B4 -- Web Notification API --> E2
    B4 -- POST --> E3
    B5 -- 读 / 监听 mtime --> E1
    B3 -- 变更时持久化 --> E1
```

**关键不变量**（由 `tests/` 中的测试锁定）：
- `task_changed` SSE payload schema 跨语言强制
  （Python ↔ JS, `test_feat_sse_cross_language_schema_r297.py`）
- SSE 心跳 = 25s，清理间隔 = 5s，热路径节流 = 30s，JS 健康检查 = 30s
  —— 全 source 文件统一锁定
  （`test_feat_perf_baseline_const_r296.py`）
- 单一 `interactive_feedback` MCP 工具接口 —— 无动态工具注册，不向多个
  LLM 端点 fan-out（保持 agent 契约紧凑）
- **并发安全（cycle-35/36 新增）** —— AST-based 锁获取顺序契约**静态**
  验证 `task_queue.py` / `notification_manager.py` / `service_manager.py`
  / `config_manager.py` / `web_ui.py` 内所有 `threading.Lock` / `RLock`
  / `ReadWriteLock` 使用。任何未来变更若 (a) 引入 deadlock cycle、(b)
  绕过 deadlock-aware `_watched_write_lock` wrapper、(c) 新增未审计的
  `RLock`、或 (d) 同一调用链重入 `Lock`，都会被 CI 拒绝。详见
  `test_feat_async_race_contract_r326.py` + `test_feat_lock_acquisition_
  order_r328.py` + `test_feat_service_manager_lock_order_r329.py` +
  `test_feat_rlock_usage_contract_r330.py` + `test_feat_web_ui_rlock_
  contract_r331.py`。
- **Lazy-init 审计（cycle-35 新增）** —— `src/` 内每个 `_ensure_*` 函数
  都被分类为 `_loaded`（多属性 import）/ `_registered`（单 flag 回调）/
  `_started`（守护线程启动），各自有对应 safety 契约；新 lazy-init 函
  数会被 CI 拒绝直到被审计 + 分类
  （`test_feat_lazy_init_audit_r327.py`）。

更深入的子系统细节（配置 schema、MCP 工具参考、i18n 策略、故障排查），
请通过下文 [`文档`](#文档) 中的链接阅读。

## Agent / Glass 模式工作流

AIIA 专为**长时间运行的自主 agent 循环**（Cursor Composer、Cursor Glass
模式、Cline、Augment、Trae）设计——LLM 在单次运行内会反复调用
`interactive_feedback`。下面 agent 端参数 + 用户端 UX 特性组合在一起，
让人类审阅者**每个任务 < 5 秒**就能决策完，agent 永远不会被阻塞太久。

### 单次交互流转

```mermaid
sequenceDiagram
    participant Agent as LLM Agent<br/>(Cursor / Cline)
    participant MCP as MCP transport
    participant AIIA as AIIA 后端<br/>(Flask + SSE)
    participant UI as Web UI / VS Code
    participant Human as 人类审阅者

    Agent->>MCP: interactive_feedback(message,<br/>header_label, question_type, ...)
    MCP->>AIIA: POST /api/tasks
    AIIA->>UI: SSE task.created
    UI->>Human: 浏览器/系统通知<br/>+ 倒计时
    Note over Human: 看 chip + prompt，<br/>点 Yes/No 或打字回复
    Human->>UI: Submit
    UI->>AIIA: POST /api/tasks/{id}/complete
    AIIA->>MCP: SSE task.completed (+ ctx.info)
    MCP->>Agent: 返回 text + images + 已选选项
    Note over Agent: 带着人类输入<br/>继续执行
```

### 异常路径 & 恢复流程

除了上面的正常路径外，三个边界场景让长时间 Agent / Glass 模式会话保持
韧性：**auto-resubmit**（人离开）、**SSE 重连**（网络断开）、
**typing-hold**（人在输入，绝不打断）。

```mermaid
sequenceDiagram
    autonumber
    participant Agent as LLM Agent
    participant AIIA as AIIA 后端
    participant UI as Web UI
    participant Human as 人类审阅者

    Note over Agent,Human: ① Auto-resubmit（人离开了）
    Agent->>AIIA: interactive_feedback<br/>(auto_resubmit_timeout=120)
    AIIA->>UI: SSE task.created（倒计时=120s）
    Note over UI: 倒计时归零<br/>（人未在输入）
    UI->>AIIA: POST /api/tasks/{id}/auto-resubmit
    AIIA->>Agent: SSE task.completed<br/>（带 "auto-resubmit" 标记）

    Note over UI,AIIA: ② SSE 断流 → 降级 polling → 重连
    UI--xAIIA: SSE 断开（休眠/网络抖动）
    UI->>AIIA: GET /api/tasks（降级 polling，每 5s）
    UI->>AIIA: SSE 重连（指数退避）
    AIIA-->>UI: SSE 恢复

    Note over Agent,Human: ③ typing-hold（人在输入，绝不打断）
    Agent->>AIIA: interactive_feedback<br/>(auto_resubmit_timeout=60)
    UI->>Human: 倒计时显示 60s
    Human->>UI: 开始输入反馈
    Note over UI: 输入中自动延长倒计时<br/>归零也不提交（typing-hold）
    Human->>UI: 停止输入 + 提交
    UI->>AIIA: POST /api/tasks/{id}/complete
    AIIA->>Agent: SSE task.completed（完整回复）
```

### Agent 端参数（LLM 通过 MCP 传入）

| 参数 | 作用 | 上限 | 来源 |
|---|---|---|---|
| `header_label` | 任务面板上方的 1 词上下文 chip（`Auth`、`DB`、`i18n`） | 16 字符 | gemini-cli `ask_user.header` |
| `question_type='yesno'` | 隐藏文本框 + 渲染 2 按钮二元决策 | — | gemini-cli `ask_user` |
| `feedback_placeholder` | 每任务文本框 placeholder（覆盖全局 i18n） | 200 字符 | gemini-cli `ask_user` |
| `auto_resubmit_timeout` | 每任务倒计时覆盖（0 = 禁用） | `[0, 3600]` 秒 | AIIA 原生 |
| `predefined_options` | 多选 chip，可选 `default: true` 标记推荐项 | 10000 字符/条 | AIIA + 上游 parity |

完整参数参考 + 一个综合调用示例（`Auth` 重构流程，组合全部 4 个 +
`predefined_options`）见
[`docs/mcp_tools.zh-CN.md#agent-模式专用参数cursor--composer--cline--augment--trae`](docs/mcp_tools.zh-CN.md#agent-模式专用参数cursor--composer--cline--augment--trae)。

### 用户端工作流特性（内置在 Web UI）

- **多任务标签页** — agent 并发 3+ 个请求时（典型 Cursor Composer
  multi-edit），每个独立 tab + 独立倒计时圆环；切换 tab 保留文本框草稿
- **每任务草稿自动保存** — 在一个 tab 打字后切换到另一个，草稿不丢
- **输入即延长（typing-hold）** — 正在输入时倒计时自动延长、归零也
  绝不打断；需要走开时就交给自动重调
- **常用回复短语** — 常用回复（`"yes do that"`、`"先 diff 再 apply"`）
  保存到 `localStorage`，一键插入
- **自定义通知音效** — 上传你自己的短音频（`.mp3`/`.wav`/...），让
  Agent 模式任务有独特提示音
- **每任务图片** — 粘贴截图/图表（≤ 700 KB）一起回复，作为 MCP
  `ImageContent` 块返回给 agent
- **SSE 实时连接徽章** — 角落 绿/橙/红 三态指示，让你知道页面与后端
  是否同步（长时间 Agent 运行中很重要）

### 推荐 LLM 系统提示词

要让 agent 真的用这个工具而不是"自顾自结束任务"，把
[`提示词（可复制）`](#方式一使用-uvx-启动推荐) 节里的中文版（或其英文
拷贝）追加到你的 IDE 系统提示词 / `.cursorrules`。

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

| 项目                        | 说明                                                                                                                                                                                                                                                |
| --------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 用途                        | 把交互面板放进 VS Code 侧边栏，避免频繁切换浏览器。                                                                                                                                                                                                 |
| 安装（Open VSX）            | [Open VSX](https://open-vsx.org/extension/xiadengma/ai-intervention-agent)                                                                                                                                                                          |
| 下载 VSIX（GitHub Release） | [GitHub Releases](https://github.com/xiadengma/ai-intervention-agent/releases/latest)                                                                                                                                                               |
| 设置                        | `ai-intervention-agent.serverUrl`（填写你的 Web UI 地址，例如 `http://localhost:8080`；端口可在 [`config.toml.default`](config.toml.default) 的 `web_ui.port` 中修改）                                                                              |
| 其他设置                    | `ai-intervention-agent.logLevel`（Output → AI Intervention Agent）。macOS 原生通知默认开启，可在侧边栏「通知设置」面板中关闭。完整设置项与 AppleScript executor 安全模型详见 [`packages/vscode/README.zh-CN.md`](packages/vscode/README.zh-CN.md)。 |

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

### 快速覆盖（无需编辑文件）

`uvx`、Docker、systemd、SSH 远程等场景下编辑 `config.toml` 不方便时，
最常用的 `web_ui` 配置可以用环境变量在进程启动时一次性覆盖：

```bash
export AI_INTERVENTION_AGENT_WEB_UI_HOST=0.0.0.0      # 默认 127.0.0.1
export AI_INTERVENTION_AGENT_WEB_UI_PORT=8181         # 默认 8080，范围 [1, 65535]
export AI_INTERVENTION_AGENT_WEB_UI_LANGUAGE=zh-CN    # auto / en / zh-CN
uvx ai-intervention-agent
```

非法值会记 `WARNING` 并 fallback 到 `config.toml` / 默认值——typo
不会阻断 server 启动。完整列表（含超时、log level 等）见
[`docs/configuration.zh-CN.md#环境变量覆盖`](docs/configuration.zh-CN.md#环境变量覆盖)。

### CLI 自省

```bash
ai-intervention-agent --version       # 或 -V —— 打印版本号后退出
ai-intervention-agent --help          # 或 -h —— 显示用法 + 配置提示
ai-intervention-agent --print-config  # dump 当前生效的 merged 配置 + env 覆盖
```

`--print-config` 用一条 shell 命令回答 _"我的 port 是 8181，到底是
env 覆盖了，还是 `config.toml` 写的？"_ —— 输出 JSON（`jq` 友好）：

- `config_file_path` —— 当前加载的 TOML 绝对路径
- `using_defaults` —— `true` 表示加载的是 bundled 默认 config（即
  "我还没创建自己的 `config.toml`"）
- `web_ui` —— resolved host / port / language（向后兼容顶层字段）
- `sections` —— 所有非敏感 section（`web_ui` / `mdns` / `feedback` /
  `notification`）；secret 类字段（`*_device_key` / `*_token` /
  `*_secret` / `password` / `*_api_key` 等）自动 redact 成
  `***REDACTED***`
- `env_overrides` —— 当前生效的 `AI_INTERVENTION_AGENT_WEB_UI_*`
  env 覆盖

`network_security` 被 `ConfigManager.get_all()` 边界过滤（与
[`/api/system/health`](docs/configuration.zh-CN.md#环境变量覆盖) 同信任级）——
监控仪表板和 CLI 看到的是同一份事实。

## 文档

- **文档总索引**（按角色定位）：[`docs/README.zh-CN.md`](docs/README.zh-CN.md) · [`docs/README.md`](docs/README.md)
- **脚本索引**（CI 门禁 / 生成器 / QA）：[`scripts/README.md`](scripts/README.md)
- **发布说明**：[`CHANGELOG.md`](CHANGELOG.md) · VS Code 插件 marketplace 专属：[`packages/vscode/CHANGELOG.md`](packages/vscode/CHANGELOG.md)
- **贡献指南**：[`CONTRIBUTING.zh-CN.md`](.github/CONTRIBUTING.zh-CN.md) · [`CODE_OF_CONDUCT.zh-CN.md`](.github/CODE_OF_CONDUCT.zh-CN.md)
- **API 文档（英文）**：[`docs/api/index.md`](docs/api/index.md)
- **API 文档（简体中文）**：[`docs/api.zh-CN/index.md`](docs/api.zh-CN/index.md)
- **MCP 工具说明（英文）**：[`docs/mcp_tools.md`](docs/mcp_tools.md)
- **MCP 工具说明（简体中文）**：[`docs/mcp_tools.zh-CN.md`](docs/mcp_tools.zh-CN.md)
- **故障排查 / FAQ**：[`docs/troubleshooting.zh-CN.md`](docs/troubleshooting.zh-CN.md) · [`docs/troubleshooting.md`](docs/troubleshooting.md)
- **Release 恢复 runbook**：[`docs/release-recovery.zh-CN.md`](docs/release-recovery.zh-CN.md) · [`docs/release-recovery.md`](docs/release-recovery.md)
- **i18n 贡献指南（英文）**：[`docs/i18n.md`](docs/i18n.md)
- **DeepWiki 问答**——AI 辅助的仓库智能问答入口：<a href="https://deepwiki.com/xiadengma/ai-intervention-agent"><img src="https://deepwiki.com/badge.svg" alt="Ask DeepWiki" valign="middle" /></a>

## 同类产品

| 项目 | Stars（约） | 定位 |
| --- | --- | --- |
| [mcp-feedback-enhanced](https://github.com/Minidoracat/mcp-feedback-enhanced)（Minidoracat） | 约 3.8k | 同类中最大的衍生方案。**双界面**（Web UI + 基于 Tauri 的桌面应用）、命令自动执行、智能识别 SSH Remote / WSL 等运行环境。覆盖 Cursor / Cline / Windsurf / Augment / Trae。 |
| [cunzhi](https://github.com/imhuso/cunzhi)（imhuso） | 约 1.4k | 中文项目，主打 "告别 AI 提前终止烦恼"，专注于阻止 AI 过早结束任务的场景。 |
| [Relay](https://glama.ai/mcp/servers/andeya/ide-relay-mcp)（andeya） | 新 | 多 IDE 中继（Cursor / Claude Code / Windsurf）、多 tab 会话合并、原生桌面窗口、Cursor 实时用量监控。 |
| [interactive-feedback-mcp (Node.js)](https://github.com/wellcomemayhem-spec/interactive-feedback-mcp-nodejs) | 新 | poliva 设计的 Node.js 实现，含 WebSocket 实时 UI、**OpenAI Whisper 语音转文字**、命令执行实时输出。 |
| [interactive-feedback-mcp](https://github.com/junanchn/interactive-feedback-mcp)（junanchn） | 约 50 | Win32 原生置顶窗口、自动回复规则（oneshot / loop）、拖放/粘贴文件路径。 |
| [interactive-feedback-mcp](https://github.com/poliva/interactive-feedback-mcp)（poliva） | 约 310 | 直系上游 fork（基于 noopstudios 原作 rebase，参见下方致谢）；最精简的 Python MCP，单一反馈对话框。 |
| [interactive-feedback-mcp](https://github.com/Pursue-LLL/interactive-feedback-mcp)（Pursue-LLL） | 约 30 | 体量更小的独立 fork，强调"依赖最少"。 |

**AIIA 在光谱中的位置**：AIIA 走的是**完整运维栈**路线——Web UI 与 VS Code 插件共享同一后端、生产级可观测性（`/metrics` Prometheus 端点 + [参考 Grafana 仪表盘](docs/observability/README.zh-CN.md)、SSE schema 校验开关）、中英双语 i18n + 双语文档、严格的不变量测试纪律（8,200+ 测试 + 1,050+ subtests，**40 cycles** 持续审计，含 **AST-based 锁获取顺序契约**——静态证明所有关键路径无 deadlock cycle、**跨运行时资源生命周期审计**覆盖 Python/Browser-JS/VS Code TS、以及 **全 32 个 API endpoint 的 OpenAPI docstring 覆盖**）、推送 tag 前的预检 hook、以及 5 个 job 的发布流水线。如果你只想要最轻量的 drop-in，选 poliva 版本；想要桌面应用，选 mcp-feedback-enhanced；想要语音输入 / 多 tab UI，选 Relay 或 Node.js 版本；想要完整运维集成 + 最深的不变量测试纪律，那就是 AIIA。

**功能 gap 提示**（计划在未来版本补全，欢迎贡献）：
- 🎤 **语音转文字输入** —— 类似 Node.js 版（OpenAI Whisper API 集成）
- 🪟 **原生置顶窗口** —— 类似 junanchn（当前只有 Web UI）
- 📊 **Cursor 用量/计费监控** —— 类似 Relay（Cursor 专属）
- 🗂️ **多 tab 会话合并 UI** —— 类似 Relay（AIIA 有任务系统但无统一 tab 中心）

> 上面的 stars 是粗略快照（最近核对：2026-06），请以各上游为准。欢迎通过 PR 补充其他同类项目。

## 致谢

本项目的源流可上溯到 **Fábio Ferreira**（2024）与 **Pau Oliva**（2025）的原作仓库 [`noopstudios/interactive-feedback-mcp`](https://github.com/noopstudios/interactive-feedback-mcp) 与 [`poliva/interactive-feedback-mcp`](https://github.com/poliva/interactive-feedback-mcp)，他们的工作奠定了 MCP `interactive_feedback` 工具的基础形态。两位作者的版权声明已按 MIT 协议要求保留在 [`LICENSE`](LICENSE) 中。v1.5.x 系列是 [@xiadengma](https://github.com/xiadengma)（PyPI / Open VSX / VS Code Marketplace 发布者）的全面重写，覆盖 Web UI、VS Code 插件、i18n、通知体系、CI/CD 流水线。

## 开源协议

MIT 许可证

---

<details>
<summary><strong>质量与安全（Quality & Security）</strong></summary>

<br />

<p>
  <a href="https://github.com/xiadengma/ai-intervention-agent/actions/workflows/test.yml">
    <img src="https://img.shields.io/github/actions/workflow/status/xiadengma/ai-intervention-agent/test.yml?branch=main&label=tests&style=flat-square&logo=github" alt="Tests" />
  </a>
  <a href="https://github.com/xiadengma/ai-intervention-agent/actions/workflows/scorecard.yml">
    <img src="https://img.shields.io/github/actions/workflow/status/xiadengma/ai-intervention-agent/scorecard.yml?branch=main&label=OpenSSF&style=flat-square&logo=securityscorecard&logoColor=white" alt="OpenSSF Scorecard" />
  </a>
  <a href="https://www.python.org/downloads/">
    <img src="https://img.shields.io/pypi/pyversions/ai-intervention-agent?style=flat-square&logo=python&logoColor=white" alt="Python versions" />
  </a>
</p>

- **Tests** —— GitHub Actions 测试 workflow 状态（每次 push / PR 触发）
- **OpenSSF Scorecard** —— 供应链安全评分
- **Python versions** —— 支持的运行时版本（声明在 `pyproject.toml`）

</details>
