# AI Intervention Agent · 文档索引

本目录收纳了 `ai-intervention-agent` 所有的长文档。按下方角色定位
直接跳到你需要的那一页。

> English version: [`README.md`](README.md)

## 终端用户 · 只想用起来

- [`configuration.zh-CN.md`](configuration.zh-CN.md) · [`configuration.md`](configuration.md)
  — 完整 TOML 参考（`config.toml`），每个配置项的默认值与热加载语义。
- [`troubleshooting.zh-CN.md`](troubleshooting.zh-CN.md) · [`troubleshooting.md`](troubleshooting.md)
  — 部署/运行最常见的 8 个问题（端口占用、VS Code 面板空白、
  通知不响、mDNS 异常等），按「现象 → 原因 → 修复」组织。
- [`mcp_tools.zh-CN.md`](mcp_tools.zh-CN.md) · [`mcp_tools.md`](mcp_tools.md)
  — server 级元数据 + 唯一的 `interactive_feedback` 工具 I/O
  契约。直接喂给 Cursor / Claude Desktop / ChatGPT Desktop 就能用。

## 贡献者 · 改代码或翻译

- [`workflow.zh-CN.md`](workflow.zh-CN.md) · [`workflow.md`](workflow.md)
  — 推荐开发流程：分支策略、本地 CI Gate 命令、发布流程。
- [`i18n.md`](i18n.md) — i18n 唯一权威：`t()` 运行时合约、每条
  `check_i18n_*.py` 门禁的执行边界、如何新增 locale 或扩展
  pseudo locale。
- [`api.zh-CN/index.md`](api.zh-CN/index.md) · [`api/index.md`](api/index.md)
  — 自动生成的模块参考（`config_manager`, `notification_*`,
  `task_queue`, `file_validator`, `enhanced_logging`,
  `exceptions`, `shared_types`, `config_utils`）。用
  `uv run python scripts/generate_docs.py` 重新生成。

## 运维 · 在真实机器上跑

- [`noise-levels.zh-CN.md`](noise-levels.zh-CN.md) — aria-live /
  toast / 日志 / 状态栏「四通道广播级别」约定。新增事件该用什么
  级别（quiet / assert / polite）前必读。

## 审计者 · 审安全或发布

- [`security/AUDIT_2026-05-04.md`](security/AUDIT_2026-05-04.md) —
  最近一次依赖漏洞审计（`pip-audit`），含升级配方与残留 CVE
  说明。
- [`../SECURITY.md`](../SECURITY.md) — 漏洞披露政策、受支持版本、
  AppleScript executor 安全模型。

## 双语覆盖

面向用户的文档同时提供英中两份（`<name>.md` 与 `<name>.zh-CN.md`）。
内部参考资料如果是英文 source（API 自动生成、[`i18n.md`](i18n.md)）
或中文 source（[`noise-levels.zh-CN.md`](noise-levels.zh-CN.md)、
[`security/AUDIT_*`](security/)），就只保留原始语言以避免翻译漂移。

---

_新增 / 改名 docs 文件时同步更新本索引，避免索引说谎。最近一次
更新对应 v1.5.22。_
