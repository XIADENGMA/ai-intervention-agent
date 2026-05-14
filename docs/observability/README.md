# Observability — Sample Grafana Dashboard

> **R220 / Cycle 11 · F-cycle10-4.** Reference Grafana dashboard JSON
> covering the `/metrics` endpoint exposed by
> `src/ai_intervention_agent/web_ui_routes/system.py`. Companion to
> CR#23's `F-cycle10-4` follow-up: R207 added
> `aiia_sse_schema_violation_total` but it was never documented in a
> ready-to-import panel, and R204's `aiia_token_age_seconds` had the
> same gap. This file closes both at once and bundles 5 additional
> high-signal panels.

## Quick import

1. Copy `grafana-dashboard.json` to a host that can reach your
   Grafana instance.
2. Grafana UI → **Dashboards** → **New** → **Import** → **Upload
   JSON file** → pick `grafana-dashboard.json`.
3. When prompted, select a Prometheus data source already scraping
   the AI Intervention Agent's `/metrics` endpoint.
4. Click **Import**. The dashboard appears with `uid:
   aiia-overview-r220` and the title *AI Intervention Agent —
   Overview*.

> Tested against Grafana **10.x** with `schemaVersion: 38`. The
> dashboard is also forward-compatible with Grafana 11.x at the
> time of writing (Grafana auto-upgrades JSON on first save).

## Panels

| # | Title | Origin spec | Metric query | Notes |
|---|---|---|---|---|
| 1 | SSE Schema Violation Rate | R207 / Cycle 10 · F-205-2 | `rate(aiia_sse_schema_violation_total[5m])` | Metric is **omitted** when `AIIA_SSE_SCHEMA_VALIDATE=off`. Use `absent(aiia_sse_schema_violation_total)` to distinguish "monitoring off" from "monitoring on with 0 violations". |
| 2 | API Token Age (Days) | R204 / Cycle 9 · F-203-1 | `aiia_token_age_seconds / 86400` | Stat panel with thresholds at 60d (yellow) / 90d (red), matching NIST SP 800-63B rotation guidance. Metric **omitted** when no token is configured. |
| 3 | SSE Emit Rate by Event Type | R202 / Cycle 8 | `sum by (event_type) (rate(aiia_sse_emit_by_type_total[5m]))` | Invariant: sum of all `event_type` series equals `rate(aiia_sse_emit_total[5m])`. |
| 4 | SSE emit→deliver Latency | R134 | `aiia_sse_emit_to_deliver_ms{quantile="0.5"\|"0.95"}` | Snapshot p50 and p95 from the per-bus ring buffer (≤512 samples). Refreshes once per stats snapshot, not per event. |
| 5 | SSE Drops Rate — Backpressure + Oversize | R51-B + R61 | `rate(aiia_sse_backpressure_discards_total[5m])` + `rate(aiia_sse_oversize_drops_total[5m])` | Sustained non-zero values point at slow consumers or pathological event payloads. |
| 6 | Recent ERROR Logs (5 min) | R-186 | `aiia_recent_errors_5min` | Rolling 5-minute window of ERROR/CRITICAL log entries, thresholded yellow at 1 / red at 10. |
| 7 | Notification Subsystem — Success Rate + Queue Size | R142 | `aiia_notification_delivery_success_rate` + `aiia_notification_queue_size` | `success_rate` is overridden to percent units (0.0–1.0) in the panel. Combine with `aiia_notification_<provider>_*` series for per-provider drill-down. |

## Suggested alert rules

The dashboard intentionally does **not** ship its own alert rules —
projects have wildly different on-call expectations. Reasonable
starting points (Prometheus syntax):

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
          summary: "AIIA SSE schema violations detected"
          description: "R207 counter is increasing, indicating emit payloads do not match aiia_sse_event_schemas.py contracts. Inspect server logs and recent CHANGELOG entries near schema fields."

      - alert: AIIA_TokenStaleNinetyDays
        expr: aiia_token_age_seconds > 90 * 86400
        for: 1h
        labels:
          severity: warning
        annotations:
          summary: "AIIA API token is older than 90 days"
          description: "Rotate via `config.toml > network_security.api_token` + bump `api_token_rotated_at`. R204 omits the metric when no token is configured, so `absent()` rules can detect mis-configuration."

      - alert: AIIA_RecentErrors
        expr: aiia_recent_errors_5min > 10
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "AIIA emitting ERROR/CRITICAL logs"
          description: "Check the recent logs view in /web/admin/logs or grep enhanced_logging output for context."
```

## Forward-compat contract

`tests/test_grafana_dashboard_invariant_r220.py` locks down:

- JSON parses successfully.
- `schemaVersion` is within `[38, 39, 40]` (the Grafana 10–11 range
  the dashboard was authored against).
- Panel count is **exactly 7** (changing the layout deliberately
  also bumps the count of locked panels in the test).
- Every panel title is non-empty and unique.
- Every metric name referenced by panel `targets[].expr` exists as
  a `_format_prom_metric(...)` / `_format_prom_metric_family(...)`
  call in `src/ai_intervention_agent/web_ui_routes/system.py`. This
  is the silent-decay shield — if a future refactor renames a
  metric in `system.py` without updating the dashboard, CI fails
  loudly.

## See also

- `docs/configuration.md` — `AIIA_SSE_SCHEMA_VALIDATE` env var
  (R205) and how it interacts with `aiia_sse_schema_violation_total`.
- `src/ai_intervention_agent/web_ui_routes/system.py` —
  authoritative `/metrics` exposition logic.
- `docs/code-reviews/cr23.md` — origin of the F-cycle10-4 backlog
  item.
