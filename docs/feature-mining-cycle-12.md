# Feature Mining Cycle 12

> Status: **closed**
> Started: 2026-06-05 (cycle-6 Track B / 同 cycle-6 Track A 同期)
> Closed: 2026-06-05
> Methodology: v3.2 + Track F + filename convention (mining-11 R254)
> Cycle kind: `mining` (cycle-2 + cycle-3 + cycle-5 + cycle-9 + cycle-10 +
>             cycle-11 续命 = 第 7 个 mining cycle)
> Cycle index: 12

## §1 触发原因

cr49 §7 verdict 推荐 audit ↔ mining 交替避免单一维度疲劳。cycle-6
Track A 是 polish (cycle-5 follow-up #4，.btn-secondary)，Track B
应是 mining 重新对标。

距离上次 mining (mining-3) 已 9 个 cycle，期间 mcp-feedback-enhanced
持续 release 至 v2.6.0 (2025-06-28)。fork `mcp-feedback-enhanced-pro`
独立演进至 v3.0.4 (Tauri 桌面 + FastMCP 3.x)。

## §2 方法论 v3.2 复用

- §2.1 `rg` evidence pre-check（每个 candidate 先在 AIIA codebase
  search 是否已实现）
- §2.2 borrow kind 列（borrow / convergent / partial / not-applicable / defer）

## §3 mcp-feedback-enhanced v2.6.0 feature matrix

### §3.1 features survey (v2.4.3 → v2.6.0)

| # | Feature | Version | AIIA 状态 | `rg` evidence | Borrow kind |
|---|---------|---------|-----------|---------------|-------------|
| 1 | Auto Command Execution | v2.6.0 | ❌ 不存在 | — | **not-applicable** (workflow auto，超出 AIIA "feedback agent" 范围) |
| 2 | Session Export (JSON/CSV/Markdown) | v2.6.0 | ✅ 已有 | mining-2 §3.1 ship 过 (Settings UI 入口) | **convergent** |
| 3 | Auto-commit pause/resume | v2.6.0 | ⚠️ 等价：freeze countdown | cycle-5+ ship | **convergent** (语义 ≈ AIIA freeze) |
| 4 | System Notifications | v2.6.0 | ✅ 已有 | R141 system notifications + browser-API | **convergent** |
| 5 | Session Timeout flexible config | v2.6.0 | ✅ 已有 | R47 + R251 + cycle-5 extend/freeze | **convergent** |
| 6 | I18n Refactor (notification 多语言) | v2.6.0 | ✅ 已有 | _t/_tl/hostT/__vuT/__domSecT/__ncT/AIIA_I18N.t/_resolveLabel | **partial → convergent** (AIIA i18n 比 mcp-fb 更成熟) |
| 7 | UI Simplification | v2.6.0 | N/A | — | **not-applicable** (主观，AIIA UI 持续 polish 中) |
| 8 | SSH Remote `MCP_WEB_HOST` env var | v2.5.5 | ✅ 已有 等价: `AI_INTERVENTION_AGENT_WEB_UI_HOST` | service_manager.py L166 | **convergent** (同步独立演进) |
| 9 | Desktop App (cross-platform) | v2.5.0 | ❌ 不存在 (Web + VSCode 双端) | — | **defer** (cycle-13+ scope，需 Tauri/Electron 调研) |
| 10 | Audio Notifications | v2.4.3 | ✅ 已有 | cycle-2 §3.4 custom sound upload | **convergent** |

### §3.2 mcp-feedback-enhanced-pro v3.0.4 fork survey

| # | Feature | Status | AIIA 评估 | Borrow kind |
|---|---------|--------|-----------|-------------|
| 1 | FastMCP 3.x upgrade | beta | **AIIA 已 ship `fastmcp>=3.0.0` (实际 3.2.4 stable)** ⚠️ 校正 cycle-8 audit 发现 | **convergent + lead** (AIIA 先行) |
| 2 | 30-day default timeout (2,592,000s) | shipped | AIIA 默认 `IDLE_FEEDBACK_TIMEOUT_SECONDS` 是 6h | **partial-borrow candidate** (可能太长，需用户调研) |
| 3 | Permanent session history retention | shipped | AIIA 当前 session 持久化策略需 audit | **investigate** (cycle-13 candidate) |
| 4 | Manual single-session deletion | shipped | AIIA `feedback_history.html` 已有 history UI 但删除粒度未审 | **investigate** (cycle-13 candidate) |
| 5 | Tauri desktop app | shipped | AIIA 双端模式 (Web + VSCode) 已覆盖大部分用例 | **defer** (cycle-13+ scope) |

**§3.2 后记 (cycle-8 corrigendum)**: mining-12 原稿误把 AIIA 当成
`fastmcp 2.x`，cycle-8 audit 复核发现 AIIA 已 ship `fastmcp>=3.0.0`
(`pyproject.toml`) 且实际安装 `fastmcp==3.2.4` (stable，2025 H2 已 GA)。
即 **AIIA 在 FastMCP 3.x 跟随上 比 upstream + fork 都早**。
mining-12 §5 cycle-13 candidates #1 (FastMCP 3.x 评估) 已 **不再需要**，
转为 R262 invariant 锁定 `fastmcp>=3.0.0` baseline 防降级。

## §4 关键发现 / 决策

### §4.1 Saturation 信号确认 (第 4 次)

mining-3 (cycle-3): 借鉴 3 个 (placeholder / yesno / header chip)
mining-5 (cycle-5): borrow 0 个 + 4 个 not-borrow，3 次 convergent
mining-9 (cycle-9): borrow 1 个 + 多 convergent
mining-11 (cycle-11): pivot 到 README backfill 不外部借鉴
**mining-12 (cycle-12)**: 0 borrow ship, 7 convergent + 1 not-applicable
+ 2 defer (cycle-13)

→ AIIA 在"feedback agent" 维度已**达到 feature parity** with
upstream mcp-feedback-enhanced v2.6.0。后续 mining cycles 信号密度
将持续走低，应转向：
- **internal polish** (cycle-5/6 模式)
- **跨 product 维度的差异化深化** (observability/i18n/test discipline，
  AIIA 已远超 mcp-fb)
- **未对标维度 mining** (gemini-cli / claude-code / aider 等)

### §4.2 mcp-feedback-enhanced-pro v3.0.4 fork 评估

发现 fork `mcp-feedback-enhanced-pro` 由独立维护者 LeonBuild 推动 v3.0
分支，主要做：
- FastMCP 3.x 跟随
- 30-day default timeout（极长）
- 永久 session retention

**fork 信号意义**：upstream v2.6.0 之后停在 (2025-06-28)，fork 在
**1 年内连发 v3.0.0-v3.0.4** 显示有持续需求。AIIA 当前 fastmcp 2.x，
不急于跟随 FastMCP 3 (尚 beta)，但应该把"FastMCP 3 评估" 列入
cycle-13/14 candidate（理由：fastmcp 是核心 dep，停留在 2.x 太久
会有 EOL 风险）。

### §4.3 AIIA 维度优势确认

mining-12 顺便复核 AIIA 在 mcp-fb 未覆盖的维度：

| 维度 | AIIA | mcp-fb-enhanced v2.6.0 | 差异度 |
|------|------|------------------------|--------|
| Test discipline (invariant tests) | **6,057 tests + 91 a11y** | 估算 < 100 tests | 极大 |
| i18n 系统（locked checks） | 8 wrapper + lockstep regex + orphan detector | 基础多语言文件 | 大 |
| Observability (Prometheus) | `/metrics` + Grafana 参考板 | 无 | 极大 |
| Pre-commit hooks | 28+ hooks (CSS/i18n/freshness/baseline) | 基础 lint | 大 |
| Release pipeline (CI gates) | 5-job pipeline + tag-safety hook | GitHub release auto | 中等 |
| WCAG 2.1 AA accessibility | 91 a11y invariants (cycles 1-6) | 无显式 a11y 设计 | **极大** |
| VSCode extension | ✓ (packages/vscode) | 无 | 极大 |
| PWA + offline experience | ✓ (mining-9 PWA cycle) | 无 | 大 |

**结论**：AIIA 的差异化优势在**运维深度 + 测试纪律 + a11y**，不在
功能数量。mining 应当继续验证这种差异化，而非追求与 mcp-fb 1:1
功能对齐。

## §5 cycle-13 candidates (3)

| # | 来源 | 描述 | 工作量 |
|---|------|------|--------|
| 1 | §3.2 #1 | FastMCP 3.x 兼容性评估 + 升级路径调研 | M (调研 + smoke test) |
| 2 | §3.2 #3/#4 | session retention + 单条删除 audit (AIIA 当前策略) | S |
| 3 | mining-12 §4.1 | gemini-cli / claude-code 跨 product 维度 mining (未对标过) | M |

## §6 经验沉淀 (4 lessons)

**L1: Mining saturation = competitive feature parity**

mining-12 (第 7 个 mining cycle) confirms AIIA 在"feedback agent"维度
**已达 feature parity** with upstream mcp-fb-enhanced v2.6.0。继续追
"借" 的边际收益走低。

阈值经验：当 mining cycle 连续 2 次（mining-11 + mining-12）出现
"0 borrow ship + 多 convergent" 模式，说明 mining-only 节奏应转
mining + polish 混合（cycle-6 模式）。

**L2: Convergent evolution > 借鉴 是优势**

mining-12 §3.1 7 个 convergent (AIIA 与 mcp-fb 独立得出相同结论)
比 1 个 borrow 更有价值 — 证明 AIIA 的设计直觉与 reference 收敛，
说明 AIIA 不依赖被 mining 而自主成熟。

**L3: Fork 信号有 5-10 个 cycle 的预警价值**

发现 fork `mcp-feedback-enhanced-pro` 比 upstream 更激进（FastMCP 3
beta 跟随）→ 5-10 cycle 后 upstream 可能跟随。AIIA 可以观察 fork 的
"试水"路径，等稳定再决策（避免提前 commit beta dep）。

**L4: mining-cycle output 多元化**

cycle-12 没有 ship 任何 borrow，但 ship 了：
- 1 个 mining doc（本文）
- 1 个 saturation signal 确认
- 3 个 cycle-13 candidates
- 4 个 lessons

mining cycle 的价值不必体现在 borrow 数量上，**doc + signal + future
candidates** 同样是有形输出。这是 mining-11 "README backfill" 模式
的扩展：mining cycle 可以纯做研究 + 沉淀，不一定要 ship 代码。

## §7 closeout

cycle-12 与 cycle-6 Track A (.btn-secondary) 同期 ship。本 cycle
不单独 commit (无代码改动)，只 ship 本 markdown + CHANGELOG entry。
