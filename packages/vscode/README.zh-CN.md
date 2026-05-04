# AI Intervention Agent（VS Code 插件）

[English](https://github.com/XIADENGMA/ai-intervention-agent/blob/main/packages/vscode/README.md) | 简体中文

该 VS Code 插件用于在侧边栏内嵌 AI Intervention Agent 的交互面板，便于在编辑器内完成 `interactive_feedback` 等交互流程。

## 功能特性

- **侧边栏集成**：在 VS Code Activity Bar 中提供面板入口
- **多任务/多标签**：支持多个任务的切换与展示
- **倒计时展示**：可视化圆环进度
- **主题自适应**：跟随 VS Code 明暗主题
- **稳定性**：内置重试与错误处理

## 环境要求

- VS Code `>= 1.105.0`
- 本地可访问的 AI Intervention Agent 服务端（默认 `http://localhost:8080`）

## 安装

> Open VSX 扩展页：`https://open-vsx.org/extension/xiadengma/ai-intervention-agent`

### 方式一：安装 VSIX（推荐离线/内网环境）

1. 生成或下载 `.vsix`
2. VS Code → `Ctrl+Shift+P` → 选择 **Extensions: Install from VSIX...**

### 方式二：从源码调试/开发（monorepo）

1. 打开主仓库根目录（本仓库）
2. 安装依赖：

```bash
npm install
```

3. 在 VS Code 中按 `F5` 启动 Extension Development Host 调试

## 配置

- `ai-intervention-agent.serverUrl`：服务端地址（默认 `http://localhost:8080`）
- `ai-intervention-agent.logLevel`：日志级别（默认 `info`；查看位置：Output → AI Intervention Agent）
- `ai-intervention-agent.i18n.pseudoLocale` *（实验性）*：开启后用 pseudo-localised 文案替换当前 UI 语言包；用于在不切英文环境的前提下排查硬编码字符串、布局溢出与 Unicode 渲染问题。默认 `false`。

> 通知开关（Web / 声音 / 系统 / Bark）由面板内的 **通知设置** 维护，并写入服务端 `config.toml`，不放在 VS Code 的 `settings.json` 里。

## AppleScript executor（仅 macOS）· 安全模型

插件内置一个 AppleScript 执行器（`applescript-executor.ts`），仅服务于 macOS 原生通知。它**不是**面向用户的"任意运行 AppleScript"命令——命令面板里没有把用户输入交给 `osascript` 的入口。约束如下：

- **平台校验**：非 `darwin` 一律 `PLATFORM_NOT_SUPPORTED`（`process.platform !== 'darwin'`）。
- **绝对路径**：调用 `/usr/bin/osascript`，不走 `PATH` 查找，免疫 PATH poisoning。
- **stdin 传脚本**：脚本体通过 stdin 传给 `osascript -`，不作为命令行参数，杜绝 shell quoting 漏洞。
- **硬超时**：默认 8 秒（超时抛 `APPLE_SCRIPT_TIMEOUT`），子进程通过 SIGTERM/SIGKILL 终止。
- **输出上限**：stdout / stderr 各 1 MiB 缓冲。
- **日志脱敏**：`sanitizeForLog()` 折行 + 截断至 160 字符后才允许进入 debug 日志。
- **不接受用户脚本**：仅有的调用点用常量 + `toAppleScriptStringLiteral()` 转义后的通知字段拼装脚本。

若想完全关闭这条路径，在面板的 **通知设置** 中关掉 macOS 原生通知，执行器就不会被触发。

## macOS 原生通知

- macOS 原生通知优先通过内置的 `terminal-notifier` 发送，失败时回退为 `osascript display notification`。
- 通知内容将显示任务的**反馈内容摘要**（与 Bark 推送一致），而非仅显示任务 ID。
- 通知的“归属/图标/应用名”属于**尽力而为**：扩展会尝试将通知归属到宿主编辑器（VS Code / Cursor 等）。若系统环境不支持该归属机制，通知可能回退为默认发送方显示。
- 如需开关：侧边栏面板 → **通知设置** → **macOS 原生通知**（默认开启）

### macOS 通知展示方式设置

macOS 通知的展示方式（横幅 / 仅通知中心）由**系统设置**控制，非插件可调：

1. 打开 **系统设置** → **通知**
2. 在应用列表中找到宿主编辑器（如 **Cursor** 或 **Visual Studio Code**）
3. 将“通知类型”设置为 **横幅**（而非“无”或仅“通知中心”）
4. 确认 **允许通知** 已开启，且 **播放通知声音** 已勾选

> 提示：若通知仅出现在通知中心但未弹出横幅，通常是因为上述第 3 步设置为了“通知中心”。

## 生成 VSIX（.vsix）

在仓库根目录执行：

```bash
npm run vscode:package
```

生成的 `.vsix` 文件会出现在 `packages/vscode/` 目录下。

> 说明：`.vsix` 属于构建产物（已在仓库 `.gitignore` 中忽略）。如果你频繁运行 `vscode:package` / `vscode:check`，想清理本地残留文件，可执行：
>
> ```bash
> rm -f packages/vscode/*.vsix
> ```

## 开发与测试

在仓库根目录执行：

```bash
npm run vscode:lint
npm run vscode:test
```

## 排错

- **看不到请求**：
  - 确认服务端可访问（默认端口 8080 或按你的 `serverUrl` 设置）
  - VS Code → Help → Toggle Developer Tools 查看控制台错误

## 项目地址

- 主仓库：[`XIADENGMA/ai-intervention-agent`](https://github.com/XIADENGMA/ai-intervention-agent)
