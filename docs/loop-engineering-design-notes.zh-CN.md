# Loop Engineering 设计预研（草案，功能仍处【搁置】状态）

> 状态：**预研笔记，未实施**。TODO.md 中该功能标注【先搁置】；本文档
> 只沉淀研究结论与设计草案，供解除搁置时直接评审，不包含任何代码改动。
>
> 日期：2026-07-17；作者：AI（ralph loop 巡检期间的调研产出）

## 1. 概念背景（2026-06 起源）

「Loop engineering」于 2026 年 6 月由三方几乎同时提出并由 Addy Osmani
命名成型（essay: <https://addyosmani.com/blog/loop-engineering/>）：

- **Peter Steinberger**：「不该再 prompt agent，而是设计 prompt agent 的
  loop」。
- **Boris Cherny**（Claude Code 负责人）：「我不再直接 prompt Claude，我
  的工作是写 loop」。
- **Addy Osmani**：给出六件套解剖——**automations**（定时触发）、
  **worktrees**（并行隔离）、**skills**（可复用能力包）、**connectors**
  （MCP 外联）、**sub-agents**（maker/checker 分离）、**external state**
  （跨 run 的外部状态）。

核心心智模型：

- **inner loop 属于 agent**：investigate → implement → verify → repeat。
- **outer loop 属于人**（Osmani《Own the Outer Loop》，2026-07-09）：
  质量证据（verification evidence）、裁决（ship/block/modify）、可问责
  （answerability）。
- 主要风险：**cognitive surrender**（人停止批判性审计）与
  **comprehension debt**（产出速度超过人的理解速度）；无人值守的 loop
  也在无人值守地犯错——必须内置验证、日志、审批门与失败上限。

## 2. AIIA 在 loop 生态中的定位

AIIA（本项目）天然是 **outer loop 的人机接口**：agent 在 inner loop 里
迭代，到达裁决点时通过 `interactive_feedback` 把「证据 + 选项」推给人，
人给出 verdict 后 loop 继续。这与 Osmani 的 outer loop 三支柱一一对应：

| Outer loop 支柱 | AIIA 现有能力 | 缺口 |
|---|---|---|
| 质量证据 | prompt 里贴测试/截图/日志 | 无结构化「证据」字段；无按 loop 聚合的历史 |
| 裁决 | predefined_options + 文本反馈 | 无 loop 级视图，多轮裁决散落在独立任务里 |
| 可问责 | tasks.json 持久化 + 提交指纹日志（R700） | 无 loop_id 关联，无法回放「这个目标经历了哪几轮、每轮人说了什么」 |

## 3. 第一版设计（与 TODO.md 草案一致，细化后）

**不变量约束**：保持单一 MCP 工具 `interactive_feedback`（项目设计不变
量），只加可选参数；旧客户端零破坏。

新增可选参数（全部 string，缺省即当前行为）：

```text
loop_id          # 同一目标的多轮任务共享的稳定 ID（agent 自定义）
loop_objective   # 目标一句话描述（首轮传入即可，后续轮可省略）
loop_phase       # investigate / implement / verify / review …（自由文本）
success_criteria # 可验证的完成判据（人审阅时的对照基准）
iteration_label  # 轮次标签，如 "iter-3" / "attempt-2"
```

落地面：

1. **Task 模型**：5 个可选字段（pydantic 默认 None，旧快照兼容——与
   R702 的 `auto_resubmit_timeout_explicit` 同一兼容模式）。
2. **HTTP API**：`POST /api/tasks` 透传；`GET /api/tasks` 返回；R368
   字段分类测试需登记为 USER_VISIBLE。
3. **Web UI「Loop」视图**：按 `loop_id` 聚合任务，显示目标、轮次、每轮
   verdict（提交内容摘要）、当前状态。初版可以只是任务列表的分组头 +
   折叠，不需要独立页面。
4. **持久化**：tasks.json 自然携带；「已完成任务 10s 清理」策略需要为
   loop 场景延长（否则历史轮次无法回看）——建议 loop 成员任务完成后
   保留 metadata（去掉 prompt 大字段）而非整体删除。

## 4. 借 R700-R702 经验的实施注意事项

- **per-task 显式值 vs 全局配置**：loop 任务大概率显式传
  `auto_resubmit_timeout`（等待人审阅应更久），R702 的 explicit 标记已
  为此铺路。
- **验证优先**：每步都要运行时验证（本轮幽灵提交教训：注册回调这种
  「无害」路径也能造成静默数据破坏）。
- **maker/checker**：AIIA 不做 sub-agent 编排（那是 agent 侧的事），但
  `question_type='yesno'` + `success_criteria` 显示可以支撑「checker 产
  出证据 → 人裁决」的最后一环。

## 5. 建议的分期

| 期 | 内容 | 风险 |
|---|---|---|
| P1 | Task 5 字段 + API 透传 + 列表返回（纯数据面） | 低 |
| P2 | Web UI 按 loop_id 分组渲染 + 轮次时间线 | 中（UI 审核） |
| P3 | loop 成员完成任务的 metadata 保留策略 | 中（清理语义变更） |
| P4 | VS Code webview 对齐 | 低（复用 R690/R691 parity 模式） |

## 6. 参考资料

- Addy Osmani, *Loop Engineering*（2026-06-07）：
  <https://addyosmani.com/blog/loop-engineering/>
- Addy Osmani, *Own the Outer Loop*（2026-07-09, Elevate）
- ADTmag, *Loop Engineering Emerges as Developers Put AI Coding Agents
  on Repeat*（2026-07-01）
- PlanetScale, *The feedback loops behind Kubernetes*：
  <https://planetscale.com/blog/the-feedback-loops-behind-kubernetes>
- Daniel Demmel, *Feedback loop engineering*：
  <https://www.danieldemmel.me/blog/feedback-loop-engineering>
