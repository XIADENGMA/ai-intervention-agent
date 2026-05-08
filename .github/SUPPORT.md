# Support · 寻求帮助

> 中文版在下方 · [Chinese version below](#支持渠道)

This file routes questions to the right channel so they get the fastest, most useful answer. **Please skim before opening an issue.**

## How to choose a channel

| Topic | Channel |
| --- | --- |
| Reproducible defect | [Bug report issue][bug] (GitHub Issues, Bug template) |
| Feature request | [Feature request issue][feat] (GitHub Issues, Feature template) |
| Open-ended discussion / question | [GitHub Discussions][disc] |
| Security vulnerability | [Private security advisory][ghsa] (DO NOT use public issues — see [`SECURITY.md`](SECURITY.md)) |
| Release artifact / packaging issue | GitHub Issues with `[release]` in the title |
| Documentation gap or unclear | GitHub Issues with the `documentation` label |

## Before opening an issue

1. **Search existing issues and discussions** — duplicates are the most common cause of slow responses.
2. **Confirm you are on the latest version**. PyPI: `pip install -U ai-intervention-agent`; VS Code: marketplace auto-update.
3. **Read the relevant doc page**: [`README.md`](README.md), [`docs/troubleshooting.md`](docs/troubleshooting.md), [`docs/configuration.md`](docs/configuration.md), [`docs/mcp_tools.md`](docs/mcp_tools.md).
4. **Try a clean reproduction**: run `uv run python scripts/manual_test.py --port 8080 --verbose` and confirm the issue persists with the published code, not your local patches.
5. **Have logs ready**: enable `ai-intervention-agent.logLevel = "debug"` in VS Code, or set `AI_INTERVENTION_AGENT_LOG_LEVEL=DEBUG` for the standalone server.

## Response expectations

This is a maintainer-driven open-source project. Best-effort SLOs:

- **Acknowledgement**: within 1–3 business days for issues, same day for security reports.
- **Resolution**: depends on severity, complexity, and reproducibility — please be patient and provide reproduction steps to speed things up.
- **Pull requests**: tagged with `needs-review` once they pass CI; reviewed in FIFO order, security-tagged PRs jump the queue.

If a thread has been silent for two weeks, feel free to bump it once with a comment.

## What is **not** supported here

- "How do I use Claude / Cursor / VS Code?" — please ask the respective vendor's support channel.
- "How do I write Python / TypeScript / etc.?" — Stack Overflow is a better fit.
- "Please add this proprietary integration for me" — happy to help in Discussions if scoped, but bespoke contracted work is out of scope.

## Sponsoring

This project does not currently accept paid sponsorships. If you'd like to support it, the most valuable contributions are: high-quality bug reports, well-scoped PRs, and documentation patches.

[bug]: https://github.com/xiadengma/ai-intervention-agent/issues/new?template=bug_report.yml
[feat]: https://github.com/xiadengma/ai-intervention-agent/issues/new?template=feature_request.yml
[disc]: https://github.com/xiadengma/ai-intervention-agent/discussions
[ghsa]: https://github.com/xiadengma/ai-intervention-agent/security/advisories/new

---

# 支持渠道

本文档帮你把问题路由到最合适的渠道，从而最快拿到有效回答。**开 issue 前请先快速浏览本文档。**

## 渠道选择

| 主题 | 渠道 |
| --- | --- |
| 可复现的缺陷 | [Bug report issue][bug]（GitHub Issues，Bug 模板） |
| 新功能请求 | [Feature request issue][feat]（GitHub Issues，Feature 模板） |
| 开放式讨论 / 提问 | [GitHub Discussions][disc] |
| 安全漏洞 | [私有安全公告][ghsa]（**不要**走公开 issue —— 见 [`SECURITY.md`](SECURITY.md)） |
| 发布物 / 打包问题 | GitHub Issues，标题加 `[release]` |
| 文档不清晰 / 缺失 | GitHub Issues，加 `documentation` label |

## 开 issue 前的自查清单

1. **先搜索现有 issue / discussion**，重复是回复慢最常见原因。
2. **确认在最新版本**：PyPI `pip install -U ai-intervention-agent`，VS Code 走 marketplace 自动更新。
3. **看相关文档页**：[`README.zh-CN.md`](README.zh-CN.md)、[`docs/troubleshooting.zh-CN.md`](docs/troubleshooting.zh-CN.md)、[`docs/configuration.zh-CN.md`](docs/configuration.zh-CN.md)、[`docs/mcp_tools.zh-CN.md`](docs/mcp_tools.zh-CN.md)。
4. **尝试纯净复现**：`uv run python scripts/manual_test.py --port 8080 --verbose`，确认问题在 published 代码上仍能复现，而非你本地的私改造成。
5. **准备好日志**：VS Code 里把 `ai-intervention-agent.logLevel` 设为 `debug`；独立 server 设环境变量 `AI_INTERVENTION_AGENT_LOG_LEVEL=DEBUG`。

## 响应预期

这是 maintainer 驱动的开源项目，best-effort 时效：

- **确认收到**：issue 1–3 个工作日；安全报告当日。
- **解决时间**：取决于严重度、复杂度、复现质量。请耐心，**提供复现步骤会显著加速**。
- **PR 处理**：通过 CI 后打 `needs-review` label，按先到先评，安全标记的 PR 优先。

若某 thread 沉默超过两周，可以礼貌地评论一次顶帖。

## 这里**不**支持的内容

- 「Claude / Cursor / VS Code 怎么用？」请走对应厂商的支持渠道。
- 「我不会写 Python / TypeScript？」更适合 Stack Overflow。
- 「请帮我加个内部集成」—— Discussions 里如有具体需求可以聊聊，但定制承包不在范围内。

## 赞助

项目目前不接受付费赞助。最有价值的支持是：高质量 bug report、范围清晰的 PR、文档补丁。
