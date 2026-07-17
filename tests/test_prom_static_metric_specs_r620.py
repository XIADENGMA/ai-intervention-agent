"""R620 - Prometheus render path reuses static metric field specs."""

from __future__ import annotations

import inspect
import unittest

from ai_intervention_agent.web_ui_routes import system as system_module


class TestPromStaticMetricSpecs(unittest.TestCase):
    def test_static_specs_preserve_sse_metric_order(self) -> None:
        self.assertEqual(
            [spec[0] for spec in system_module._SSE_COUNTER_FIELD_SPECS],
            [
                "aiia_sse_emit_total",
                "aiia_sse_gap_warnings_total",
                "aiia_sse_backpressure_discards_total",
                "aiia_sse_heartbeat_total",
                "aiia_sse_oversize_drops_total",
            ],
        )
        self.assertEqual(
            [spec[0] for spec in system_module._SSE_GAUGE_FIELD_SPECS],
            [
                "aiia_sse_subscriber_count",
                "aiia_sse_history_size",
                "aiia_sse_latest_event_id",
            ],
        )
        self.assertEqual(
            system_module._SSE_LATENCY_QUANTILE_SPECS,
            (("p50_ms", "0.5"), ("p95_ms", "0.95")),
        )

    def test_static_specs_preserve_notification_provider_order(self) -> None:
        self.assertEqual(
            [spec[0] for spec in system_module._NOTIFICATION_PROVIDER_FIELD_SPECS],
            [
                "attempts_total",
                "success_total",
                "failure_total",
                "success_rate",
                "avg_latency_ms",
                "success_streak",
                "failure_streak",
            ],
        )

    def test_render_path_uses_module_static_specs(self) -> None:
        source = inspect.getsource(system_module._render_prometheus_metrics)

        self.assertNotIn("sse_counter_fields = (", source)
        self.assertNotIn("sse_gauge_fields = (", source)
        self.assertNotIn("_per_provider_field_specs", source)
        self.assertIn(
            "for prom_name, key, help_text in _SSE_COUNTER_FIELD_SPECS", source
        )
        self.assertIn("for prom_name, key, help_text in _SSE_GAUGE_FIELD_SPECS", source)
        self.assertIn(
            "for quantile_key, quantile_label in _SSE_LATENCY_QUANTILE_SPECS",
            source,
        )
        self.assertIn("_NOTIFICATION_PROVIDER_FIELD_SPECS", source)


if __name__ == "__main__":
    unittest.main()
