# 支持渠道

> [English](./SUPPORT.md) | 简体中文

本文档帮你把问题路由到最合适的渠道，从而最快拿到有效回答。**开 issue 前请先快速浏览本文档。**

## 渠道选择

| 主题 | 渠道 |
| --- | --- |
| 可复现的缺陷 | [Bug report issue][bug]（GitHub Issues，Bug 模板） |
| 新功能请求 | [Feature request issue][feat]（GitHub Issues，Feature 模板） |
| 开放式讨论 / 提问 | [GitHub Discussions][disc] |
| 安全漏洞 | [私有安全公告][ghsa]（**不要**走公开 issue —— 见 [`SECURITY.zh-CN.md`](SECURITY.zh-CN.md)） |
| 发布物 / 打包问题 | GitHub Issues，标题加 `[release]` |
| 文档不清晰 / 缺失 | GitHub Issues，加 `documentation` label |

## 开 issue 前的自查清单

1. **先搜索现有 issue / discussion**，重复是回复慢最常见原因。
2. **确认在最新版本**：PyPI `pip install -U ai-intervention-agent`，VS Code 走 marketplace 自动更新。
3. **看相关文档页**：[`README.zh-CN.md`](../README.zh-CN.md)、[`docs/troubleshooting.zh-CN.md`](../docs/troubleshooting.zh-CN.md)、[`docs/configuration.zh-CN.md`](../docs/configuration.zh-CN.md)、[`docs/mcp_tools.zh-CN.md`](../docs/mcp_tools.zh-CN.md)。
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

[bug]: https://github.com/xiadengma/ai-intervention-agent/issues/new?template=bug_report.yml
[feat]: https://github.com/xiadengma/ai-intervention-agent/issues/new?template=feature_request.yml
[disc]: https://github.com/xiadengma/ai-intervention-agent/discussions
[ghsa]: https://github.com/xiadengma/ai-intervention-agent/security/advisories/new
