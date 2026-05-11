# AI Intervention Agent · 文档索引

本目录收纳了 `ai-intervention-agent` 所有的长文档。按下方角色定位
直接跳到你需要的那一页。

> English version: [`README.md`](README.md)

## 终端用户 · 只想用起来

- [`configuration.zh-CN.md`](configuration.zh-CN.md) · [`configuration.md`](configuration.md)
  — 完整 TOML 参考（`config.toml`），每个配置项的默认值与热加载语义。
- [`troubleshooting.zh-CN.md`](troubleshooting.zh-CN.md) · [`troubleshooting.md`](troubleshooting.md)
  — 部署/运行最常见的 9 个问题（端口占用、VS Code 面板空白、
  通知不响、mDNS 异常、「Bark 通知点开是 Bark App 而不是 PWA」等），
  按「现象 → 原因 → 修复」组织。
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
  — 自动生成的 Python 公共表面模块参考：核心契约模块
  （`config_manager`、`notification_*`、`task_queue`、`protocol`、
  `state_machine`、`server`、`server_feedback`、`server_config`、
  `service_manager`、`web_ui`、`web_ui_security`、`web_ui_validators`、
  `exceptions`）+ 工具模块
  （`config_utils`、`i18n`、`shared_types`、`notification_models`、
  `file_validator`、`enhanced_logging`、`web_ui_config_sync`、
  `web_ui_mdns`、`web_ui_mdns_utils`）。用
  `uv run python scripts/generate_docs.py` 重新生成；
  漂移检测用 `make docs-check`（即
  `uv run python scripts/generate_docs.py --check`）。

## 运维 · 在真实机器上跑

- [`noise-levels.zh-CN.md`](noise-levels.zh-CN.md) · [`noise-levels.md`](noise-levels.md)
  — aria-live / toast / 日志 / 状态栏「四通道广播级别」约定。新增事件该用
  什么级别（quiet / assert / polite）前必读。

## 审计者 · 审安全或发布

- [`security/AUDIT_2026-05-04.md`](security/AUDIT_2026-05-04.md) —
  最近一次依赖漏洞审计（`pip-audit`），含升级配方与残留 CVE
  说明。
- [`../.github/SECURITY.zh-CN.md`](../.github/SECURITY.zh-CN.md) — 漏洞披露政策、受支持版本、
  AppleScript executor 安全模型。
- [`lessons-learned-css-and-options.md`](lessons-learned-css-and-options.md) — v1.5.45
  批次的内部复盘（浅色模式 iOS 蓝泄漏、MCP 工具描述漂
  移、Bark 深链接 sentinel、build-info 诊断块、Prettier 收尾、
  Dependabot major-bump 分诊、README 架构完整性）。新增 CSS 主
  题变体或 MCP 工具字段前必读。
- [`lessons-learned-silent-decay.md`](lessons-learned-silent-decay.md) —
  v1.6.0 批次的内部复盘（CodeQL 警告分诊、治理文档
  迁入 `.github/`、零警告冲刺、PyPA `src/` 布局迁移、跨 MCP
  兼容别名、防御分支覆盖率冲刺、Markdown 链接腐烂护栏、
  CHANGELOG 回填、coverage 数据文件改写位置）。任何大型重组、
  accept-but-ignore 兼容字段、或 `git mv` 任意 `.md` 文件之
  前必读。
- [`security-triage-r72.tmp.md`](security-triage-r72.tmp.md) — 2026 年 5
  月对全部 GitHub code-scanning 警告的逐条分诊。包含 R72-A（15 ×
  log-injection 通过全局 root InterceptHandler 一次性修掉）+
  R72-B（1 × `open-config-file` stack-trace 泄漏）的代码修复、20
  个误报的 dismiss 理由、以及 OpenSSF Scorecard 治理项的"暂不修"
  政策说明。

## 双语覆盖

面向用户的文档同时提供英中两份（`<name>.md` 与 `<name>.zh-CN.md`）。
内部参考资料如果是英文 source（API 自动生成、[`i18n.md`](i18n.md)）
或中文 source（[`noise-levels.zh-CN.md`](noise-levels.zh-CN.md)、
[`security/AUDIT_*`](security/)），就只保留原始语言以避免翻译漂移。

---

_新增 / 改名 docs 文件时同步更新本索引，避免索引说谎。最近一次
更新对应 v1.6.0（R71 → R82 批次：带审计轨迹的 CodeQL 分诊、
治理文档迁入 `.github/`、清掉 4 条 ruff-LOG / 2 条 ty / prettier /
lockfile 诊断的零警告冲刺、PyPA `src/ai_intervention_agent/`
布局迁移并删除 `config.jsonc.default`、为 `interactive_feedback`
添加跨工具兼容别名 `timeout_seconds` / `task_id`、
`web_ui_routes/system.py` 与 `i18n.py` 防御分支覆盖率冲刺、
Markdown 链接腐烂护栏 + 修复 `.github/` 内 14 条断链、
`CHANGELOG.md` `[Unreleased]` 回填、把 `coverage.py` 并行模式
中间文件挪到 `.coverage_data/`）。内部复盘见
[`lessons-learned-silent-decay.md`](lessons-learned-silent-decay.md)。上一
v1.5.45（R63 → R70 批次）复盘见
[`lessons-learned-css-and-options.md`](lessons-learned-css-and-options.md)。更早的
R57 / R58（Flask-Limiter `headers_enabled=True` + 256 KB SSE
oversize 护栏）记录在 v1.5.44；R56 → R50 在 v1.5.43 →
v1.5.39。_
