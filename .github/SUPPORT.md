# Support

> English | [简体中文](./SUPPORT.zh-CN.md)

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
3. **Read the relevant doc page**: [`README.md`](../README.md), [`docs/troubleshooting.md`](../docs/troubleshooting.md), [`docs/configuration.md`](../docs/configuration.md), [`docs/mcp_tools.md`](../docs/mcp_tools.md).
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
