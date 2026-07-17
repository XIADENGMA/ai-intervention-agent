"""R518 - Prometheus family renderers avoid scrape-time staging lists."""

from __future__ import annotations

import inspect
import math
import unittest

from ai_intervention_agent.web_ui_routes import system as system_module


class TestPromFamilyIterableRenderers(unittest.TestCase):
    def test_histogram_family_accepts_one_pass_generator_observations(self) -> None:
        consumed: list[str] = []

        def observations():
            for label, count in (("a", 1), ("b", 2)):
                consumed.append(label)
                yield {"label": label}, {0.1: count, math.inf: count}, count, 0.1

        out = system_module._format_prom_histogram_family(
            "aiia_test_duration_seconds",
            help_text="A test histogram.",
            observations=observations(),
        )

        self.assertEqual(consumed, ["a", "b"])
        self.assertEqual(out.count("# HELP aiia_test_duration_seconds"), 1)
        self.assertEqual(out.count("# TYPE aiia_test_duration_seconds histogram"), 1)
        self.assertIn(
            'aiia_test_duration_seconds_bucket{le="0.1",label="a"} 1\n',
            out,
        )
        self.assertIn('aiia_test_duration_seconds_count{label="b"} 2\n', out)

    def test_histogram_family_empty_generator_returns_empty_string(self) -> None:
        out = system_module._format_prom_histogram_family(
            "aiia_test_duration_seconds",
            help_text="A test histogram.",
            observations=(observation for observation in ()),
        )

        self.assertEqual(out, "")

    def test_notification_provider_sample_iterator_filters_without_list(self) -> None:
        per_provider = {
            "bark": {"attempts": 3, "success_rate": 0.75},
            "web": {"attempts": "3"},
            42: {"attempts": 2},
            "invalid": [],
        }

        self.assertEqual(
            list(
                system_module._iter_notification_provider_metric_samples(
                    per_provider,
                    metric_suffix="attempts_total",
                    key="attempts",
                    metric_type="counter",
                )
            ),
            [({"provider": "bark"}, 3)],
        )
        self.assertEqual(
            list(
                system_module._iter_notification_provider_metric_samples(
                    per_provider,
                    metric_suffix="success_rate",
                    key="success_rate",
                    metric_type="gauge",
                )
            ),
            [({"provider": "bark"}, 0.75)],
        )

    def test_mcp_tool_call_sample_iterator_filters_without_list(self) -> None:
        tool_stats = {
            "read_file": {"success": 2, "failure": 1},
            "bad_tool": {"success": "2"},
            7: {"success": 3},
            "invalid": [],
        }

        self.assertEqual(
            list(system_module._iter_mcp_tool_call_samples(tool_stats)),
            [
                ({"tool": "read_file", "status": "success"}, 2),
                ({"tool": "read_file", "status": "failure"}, 1),
            ],
        )

    def test_render_prometheus_metrics_no_longer_stages_family_lists(self) -> None:
        source = inspect.getsource(system_module._render_prometheus_metrics)

        self.assertNotIn("samples: list[", source)
        self.assertNotIn("mcp_samples", source)
        self.assertNotIn("notif_hist_observations", source)
        self.assertNotIn("hist_observations", source)
        self.assertIn("_iter_notification_provider_metric_samples(", source)
        self.assertIn("_iter_notification_latency_histogram_observations(", source)
        self.assertIn("_iter_mcp_tool_call_samples(", source)
        self.assertIn("_iter_mcp_tool_latency_histogram_observations(", source)


if __name__ == "__main__":
    unittest.main()
