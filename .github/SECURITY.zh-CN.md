# 安全策略

> [English](./SECURITY.md) | 简体中文

## 支持的版本

只有 `main` 上的 **最新 minor** 会收到安全修复。新的 minor 一旦发布到 PyPI /
Open VSX / VS Code Marketplace，旧 minor 立即 EOL。

| 版本  | 状态    |
| ----- | ------- |
| 1.6.x | ✅ 支持 |
| < 1.6 | ❌ EOL  |

需要向旧线回移补丁？先开 discussion，我们按 CVSS 与暴露面逐例评估。

## 报告漏洞

**请勿在公开 issue 里披露安全问题。**

首选通道（私有、可追溯、有审计日志）：

1. 打开 GitHub 仓库的 [Security 标签页 → "Report a vulnerability"][ghsa]，这
   会创建一条只有维护者可见的 private advisory。
2. 请包含：受影响组件（Web UI / VSCode 扩展 / MCP server / AppleScript
   executor）、版本号、可复现步骤，以及观察到的影响（RCE / XSS / 密钥泄漏 /
   DoS 等）。
3. 若 PoC 需要附上二进制或截图，请一并放在 private advisory 内，避免贴到公开
   频道。

备用通道：当 GitHub 不可用时，请通过 GitHub 个人主页 `@xiadengma` 所列邮箱
联系维护者，主题请带上 `[SECURITY] ai-intervention-agent`。

## 披露节奏

- 回复确认：**72 小时** 内。
- 定级与修复 ETA：确认后 **7 天** 内给出。
- 协同披露：补丁上线（PyPI / Marketplace / Open VSX）后发布 GitHub Security
  Advisory，在 advisory 中致谢报告者（匿名请求除外）。

## 非 loopback 部署的加固建议

默认部署（`make run` / `uvx ai-intervention-agent`）只把 Web UI 绑到
`127.0.0.1`，仅接受 loopback 流量。如果你有意绑定到非 loopback 地址 ——
例如通过 `AI_INTERVENTION_AGENT_WEB_UI_HOST=0.0.0.0` 用于 SSH 远程 / 局域网
访问 —— 下列端点就会对同网段所有设备可达，且响应中含有 user-specific 凭证：

- `GET /api/get-notification-config` —— 完整的 `notification` 配置，含
  `bark_device_key`（Bark 推送设备 token）。
- `GET /api/get-feedback-prompts` —— 你保存的反馈 prompt 库。

这些端点故意 **没有** 在 HTTP 边界做 redact——内置 Settings 面板需要拿到现值
做 round-trip 编辑。一旦绑定到 loopback 之外，你必须在其它层补偿：

1. 在 `config.toml` 把 `network_security.allowed_networks` 设置为你真正信任的最小
   CIDR（例如 `["192.168.1.0/24"]`）。它是与 `*_WEB_UI_HOST` env var 完全独立
   的更严格 ACL，不会被 env 覆盖。
2. 优先选 `ssh -L 18080:127.0.0.1:18080 user@remote` 隧道，而非绑定 `0.0.0.0`。
   远端机器上访问体验一致，但端口完全不暴露。
3. 临时排查时，CLI `ai-intervention-agent --print-config` 会自动 redact 敏感
   key（`*_device_key` / `*_token` / `*_secret` / `password` / `*_api_key` 等），
   可以放心粘到聊天/issue 中；HTTP API 故意没启用同等 redaction。

这三层（绑定接口、`network_security.allowed_networks`、SSH 隧道）相互独立——
按你的威胁模型选用。如果你需要更严格的 API 边界 redact（比如对外发布
kiosk 风格的 UI），请开 discussion，我们再权衡是否引入 per-endpoint redact
策略（同时不破坏 round-trip 的 Settings 编辑流）。

## 非受理范围

- 直接或间接依赖中的漏洞：请上报上游；本仓 Dependabot 已自动为 patch / minor
  升级开 PR。
- 需要本地 shell / 文件写权限才能触发的问题：AppleScript executor 本就是设计
  为仅在本机运行，且受 macOS 权限控制 —— 完整的七项防护边界详见
  [`packages/vscode/README.zh-CN.md`](../packages/vscode/README.zh-CN.md) 中
  **AppleScript executor 安全模型** 一节。
- 针对维护者的社会工程攻击。

[ghsa]: https://github.com/xiadengma/ai-intervention-agent/security/advisories/new
