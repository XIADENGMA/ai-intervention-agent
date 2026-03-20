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

- VS Code `>= 1.74.0`
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
- `ai-intervention-agent.enableAppleScript`：允许在 macOS 上执行 AppleScript（默认关闭；用于触发 macOS 原生通知等）

## macOS 原生通知（可选）

1. 在 VS Code 设置中开启 `ai-intervention-agent.enableAppleScript`
2. 打开命令面板（`Ctrl+Shift+P`），运行 **AI Intervention Agent: 测试 macOS 原生通知**

## 生成 VSIX（.vsix）

在仓库根目录执行：

```bash
npm run vscode:package
```

生成的 `.vsix` 文件会出现在 `packages/vscode/` 目录下。

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
