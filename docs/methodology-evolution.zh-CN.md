# 方法学演化时间线 (v3.0 → v3.11)

> **本文档是什么。** 本项目工业化的不变量测试方法学维度的按时间排序的
> 目录。每个 "vX.Y" 条目标记了一个方法学维度的启动（或子模式拆分）。
> 当你想理解"为什么这个 codebase 有这么多 `tests/test_feat_*_invariant_*.py`
> 文件"，或者当你提议一个新的方法学维度时，请阅读本文档。
>
> **English version**: [`methodology-evolution.md`](methodology-evolution.md).

## 概览

| 维度       | 启动 cycle  | 锚点 R#   | 状态（cycle-51）          | 应用次数 |
| ---------- | ----------- | --------- | ------------------------- | -------- |
| v3.0       | cycle-1     | 多种      | 基础维度                  | 100+     |
| v3.1       | cycle-19    | R178      | 工业化                    | 8+       |
| v3.2       | cycle-21    | R210      | 工业化                    | 6+       |
| v3.3       | cycle-23    | R230      | 工业化                    | 6+       |
| v3.4       | cycle-25    | R260      | 工业化                    | 5+       |
| v3.5       | cycle-27    | R287      | 工业化                    | 5+       |
| v3.6       | cycle-29    | R296      | 完全工业化                | 9+       |
| v3.7       | cycle-31    | R306      | 工业化                    | 4+       |
| v3.8       | cycle-32    | R313      | 工业化                    | 6+       |
| v3.9       | cycle-35    | R326      | 工业化                    | 6+       |
| v3.10.1    | cycle-46    | R404      | 工业化                    | 2+       |
| v3.10.2    | cycle-47    | R412      | 工业化                    | 3+       |
| v3.10.3    | cycle-48    | R422      | 工业化                    | 5+       |
| **v3.11**  | **cycle-47**（R414 1st 应用）→ **cycle-51（正式命名）** | **R414 → R448** | **完全工业化（深化期）** | **13+** |

## v3.11 — 元方法学层（Meta-invariant layer）

**状态（cycle-52）**：完全工业化（深化期）— 13 应用，5 子模式（Ratchet validation / doc-parity / API contract / i18n / Mixin matrix）。

### 定义

**元不变量（meta-invariant）** 是一种用于保护另一个不变量免于静默腐烂
的不变量。它使用合成输入（漂移场景）来证明目标不变量的辅助函数在预期
情况下能够正确 fire。这可以防止 refactor 静默地破坏目标的检测逻辑而
测试仍然 PASSING。

### 子模式（cycle-51）

| 子模式             | 1st 应用 | Cycle | 应用数 | 守护对象                                                         |
| ------------------ | -------- | ----- | ------ | ---------------------------------------------------------------- |
| Ratchet validation | R418     | 47    | 7      | R412/R422 ratchet uplifts (R418/R426/R428/R432/R436/R440/R446)   |
| doc-parity         | R424     | 48    | 1      | R335/R340/R346/R400/R408/R394                                    |
| API contract       | R430     | 49    | 1      | R404（endpoint summary）                                         |
| **i18n**           | **R438** | **50**| **3** | **R350（R438）/ R353（R442）/ R366（R448）**                     |
| Mixin matrix       | R414     | 47    | 1      | R406（Mixin route registration matrix）                          |

**13 应用** = (Ratchet validation 7) + (doc-parity 1) + (API contract 1) + (i18n 3) + (Mixin matrix 1)。

### 工业化里程碑

- **初始（1 应用）**：cycle-47，R414 启动 Mixin matrix 负面验证
- **2nd 应用**：cycle-47，R418 启动 Ratchet validation 子模式
- **3rd 应用（工业化）**：cycle-48，R424 启动 doc-parity 子模式
- **6th 应用（多子模式）**：cycle-49，R430 启动 API contract 子模式
- **9th 应用（完全工业化）**：cycle-50，R438 启动 i18n 子模式（4 子模式）
- **11th 应用（深化）**：cycle-51，R442 强化 i18n 子模式至 2 应用
- **13th 应用（深化期 + 1）**：cycle-52，R448 强化 i18n 子模式至 3 应用（工业化阈值）

### 设计原则

1. **合成输入，非真实 codebase**：元不变量使用手工合成的漂移场景，
   而非真实 codebase，以避免元不变量与目标不变量之间的耦合。
2. **4 层结构**：
   - Layer 1：合成漂移检测（positive fire case）
   - Layer 2：合成 ceiling 容忍（negative fire case）
   - Layer 3：辅助函数 edge case smoke（如 `_meta` 过滤）
   - Layer 4：血脉 + 里程碑标记
3. **按守护维度拆分子模式**：每个子模式保护一个特定的方法学维度。
   当元不变量模式扩展到新维度时，会涌现出新的子模式（如 R424 → doc-parity，
   R430 → API contract，R438 → i18n）。

## 参见

- [`contributor-guide-invariant-tests.zh-CN.md`](contributor-guide-invariant-tests.zh-CN.md)
  — 完整不变量测试模式目录
- [`code-reviews/`](code-reviews/) — 逐 cycle 的 code review，包括
  模式工业化里程碑
- [`lessons-learned-silent-decay.md`](lessons-learned-silent-decay.md) —
  为什么静默腐烂能击败常规 review（理解为什么需要元不变量的基础阅读）
