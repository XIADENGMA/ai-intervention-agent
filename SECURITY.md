# Security Policy

> 中文版在下方 · [Chinese version below](#安全策略)

## Supported versions

Only the **latest minor** on the `main` branch receives security fixes. Older
minors are end-of-life the moment a new minor is published on PyPI / Open VSX /
VS Code Marketplace.

| Version | Status          |
| ------- | --------------- |
| 1.5.x   | ✅ Supported     |
| < 1.5   | ❌ End-of-life   |

If you need a backport to an older line, open a discussion first — we evaluate
case by case based on CVSS and exposure.

## Reporting a vulnerability

**Do not open a public GitHub issue for security problems.**

Preferred channel (private, triageable, audit-logged):

1. Go to the [Security tab → "Report a vulnerability"][ghsa] on GitHub; this
   opens a private advisory only the maintainers can see.
2. Include: affected component (Web UI / VSCode extension / MCP server /
   AppleScript executor), version, reproduction, and the impact you observed
   (RCE / XSS / secret leak / DoS / etc.).
3. If PoC requires binary blobs or screenshots, attach them inside the private
   advisory — avoid pasting them to public channels.

Fallback channel if GitHub is unavailable: email the maintainer via the address
listed on the GitHub profile `@xiadengma`. Please tag the subject with
`[SECURITY] ai-intervention-agent`.

## Disclosure policy

- Acknowledgement target: within **72 hours**.
- Triage + fix ETA: shared within **7 days** of acknowledgement.
- Coordinated disclosure: a GitHub Security Advisory is published once a fix
  reaches users (PyPI / Marketplace / Open VSX). We credit reporters in the
  advisory unless anonymity is requested.

## Out of scope

- Vulnerabilities in direct or transitive dependencies — please report them
  upstream; Dependabot already auto-PRs patch/minor bumps into this repo.
- Issues requiring local shell / filesystem write access the user already has
  (the AppleScript executor is intentionally local-only and gated by macOS
  permissions).
- Social engineering of maintainers.

[ghsa]: https://github.com/xiadengma/ai-intervention-agent/security/advisories/new

---

## 安全策略

### 支持的版本

只有 `main` 上的 **最新 minor** 会收到安全修复。新的 minor 一旦发布到 PyPI /
Open VSX / VS Code Marketplace，旧 minor 立即 EOL。

| 版本     | 状态      |
| ------- | -------- |
| 1.5.x   | ✅ 支持   |
| < 1.5   | ❌ EOL   |

需要向旧线回移补丁？先开 discussion，我们按 CVSS 与暴露面逐例评估。

### 报告漏洞

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

### 披露节奏

- 回复确认：**72 小时** 内。
- 定级与修复 ETA：确认后 **7 天** 内给出。
- 协同披露：补丁上线（PyPI / Marketplace / Open VSX）后发布 GitHub Security
  Advisory，在 advisory 中致谢报告者（匿名请求除外）。

### 非受理范围

- 直接或间接依赖中的漏洞：请上报上游；本仓 Dependabot 已自动为 patch / minor
  升级开 PR。
- 需要本地 shell / 文件写权限才能触发的问题：AppleScript executor 本就是设计
  为仅在本机运行，且受 macOS 权限控制。
- 针对维护者的社会工程攻击。
