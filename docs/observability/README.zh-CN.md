# 可观测性 — Grafana 仪表盘示例

> **R220 / Cycle 11 · F-cycle10-4。** 这是 AI Intervention Agent
> `/metrics` 端点（实现位于
> `src/ai_intervention_agent/web_ui_routes/system.py`）的参考 Grafana
> 仪表盘 JSON。配套 CR#23 列出的 `F-cycle10-4` 后续项：R207 新增了
> `aiia_sse_schema_violation_total` 但从未在 "开箱即用" 的面板里被
> 文档化，R204 的 `aiia_token_age_seconds` 也有同样缺口。本文件一次性
> 把两者补齐，并捆绑了 5 个高信息密度的额外面板。

## 快速导入

1. 把 `grafana-dashboard.json` 拷贝到能访问目标 Grafana 实例的主机。
2. Grafana 界面 → **Dashboards** → **New** → **Import** → **Upload
   JSON file**，选择 `grafana-dashboard.json`。
3. 出现选择 data source 提示时，挑一个已经在抓取 AI Intervention
   Agent `/metrics` 端点的 Prometheus 数据源。
4. 点 **Import**。仪表盘以 `uid: aiia-overview-r220` 出现，标题为
   *AI Intervention Agent — Overview*。

> 已在 Grafana **10.x** + `schemaVersion: 38` 上测试通过。截至撰写
> 时也向前兼容 Grafana 11.x（Grafana 在首次保存时会自动 upgrade
> JSON schema）。

## 面板清单

| # | 面板标题 | 起源 spec | 指标查询 | 备注 |
|---|---|---|---|---|
| 1 | SSE Schema Violation Rate | R207 / Cycle 10 · F-205-2 | `rate(aiia_sse_schema_violation_total[5m])` | 当 `AIIA_SSE_SCHEMA_VALIDATE=off` 时指标**不出现**。用 `absent(aiia_sse_schema_violation_total)` 即可区分 "监控未开启" 与 "监控开启但 0 违规" 两种状态。 |
| 2 | API Token Age (Days) | R204 / Cycle 9 · F-203-1 | `aiia_token_age_seconds / 86400` | Stat 面板，阈值设为 60 天 (黄) / 90 天 (红)，对齐 NIST SP 800-63B 轮换指南。未配置 token 时指标**不出现**。 |
| 3 | SSE Emit Rate by Event Type | R202 / Cycle 8 | `sum by (event_type) (rate(aiia_sse_emit_by_type_total[5m]))` | 不变量：所有 `event_type` 系列之和等于 `rate(aiia_sse_emit_total[5m])`。 |
| 4 | SSE emit→deliver Latency | R134 | `aiia_sse_emit_to_deliver_ms{quantile="0.5"\|"0.95"}` | 来自每个 SSE bus 的 ring buffer (≤512 样本) 的 p50 / p95 快照。每次 stats snapshot 刷新一次，并非每个事件。 |
| 5 | SSE Drops Rate — Backpressure + Oversize | R51-B + R61 | `rate(aiia_sse_backpressure_discards_total[5m])` + `rate(aiia_sse_oversize_drops_total[5m])` | 持续非零意味着下游消费者过慢，或事件负载异常大。 |
| 6 | Recent ERROR Logs (5 min) | R-186 | `aiia_recent_errors_5min` | 最近 5 分钟内 ERROR/CRITICAL 日志条数滚动窗口，阈值 1 (黄) / 10 (红)。 |
| 7 | Notification Subsystem — Success Rate + Queue Size | R142 | `aiia_notification_delivery_success_rate` + `aiia_notification_queue_size` | 面板内对 `success_rate` 设置了 percent 单位 override (0.0–1.0)。结合 `aiia_notification_<provider>_*` 系列可做 per-provider 钻取。 |

## 推荐告警规则

仪表盘**故意不**自带告警规则——每个项目的 on-call 期望差异巨大。
合理的起点如下 (Prometheus 语法)：

```yaml
groups:
  - name: ai-intervention-agent
    rules:
      - alert: AIIA_SSE_SchemaViolationsAppearing
        expr: rate(aiia_sse_schema_violation_total[5m]) > 0
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "AIIA SSE schema 违规出现"
          description: "R207 counter 在增长，表明 emit 负载不符合 aiia_sse_event_schemas.py 的契约。检查服务端日志和 CHANGELOG 中 schema 字段相关的近期改动。"

      - alert: AIIA_TokenStaleNinetyDays
        expr: aiia_token_age_seconds > 90 * 86400
        for: 1h
        labels:
          severity: warning
        annotations:
          summary: "AIIA API token 超过 90 天未轮换"
          description: "通过 `config.toml > network_security.api_token` 轮换，并更新 `api_token_rotated_at`。R204 在未配置 token 时不暴露指标，故 `absent()` 规则可同时检测配置遗漏。"

      - alert: AIIA_RecentErrors
        expr: aiia_recent_errors_5min > 10
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "AIIA 正在产生 ERROR/CRITICAL 日志"
          description: "查看 /web/admin/logs 的最近日志视图，或 grep enhanced_logging 输出以了解上下文。"
```

## 前向兼容契约

`tests/test_grafana_dashboard_invariant_r220.py` 锁定如下不变量：

- JSON 可成功解析。
- `schemaVersion` 在 `[38, 39, 40]` 范围内 (本仪表盘成稿时
  支持的 Grafana 10–11 schema 范围)。
- 面板数量**严格为 7** (有意改动布局时同步更新测试中的锁定数)。
- 每个面板标题非空且互不重复。
- 面板 `targets[].expr` 引用的每一个 metric 名称都能在
  `src/ai_intervention_agent/web_ui_routes/system.py` 中找到对应的
  `_format_prom_metric(...)` / `_format_prom_metric_family(...)`
  调用。这就是 silent-decay 防护——如果未来 refactor 在 `system.py`
  里改名了某个 metric 而忘了同步仪表盘，CI 会立刻吵。

## 相关文档

- `docs/configuration.zh-CN.md` — `AIIA_SSE_SCHEMA_VALIDATE` 环境
  变量 (R205) 及其与 `aiia_sse_schema_violation_total` 的互动。
- `src/ai_intervention_agent/web_ui_routes/system.py` — 权威的
  `/metrics` 暴露逻辑。
- `docs/code-reviews/cr23.md` — F-cycle10-4 backlog 项的起源。
