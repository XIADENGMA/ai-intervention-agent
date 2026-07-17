"""R517 - Prometheus metric families consume one-pass sample iterables."""

from __future__ import annotations

import inspect
import unittest

from ai_intervention_agent.web_ui_routes import system as system_module


class TestPromMetricFamilyIterableSamples(unittest.TestCase):
    def test_metric_family_accepts_one_pass_generator_samples(self) -> None:
        consumed: list[str] = []

        def samples():
            for label, value in (("a", 1), ("b", 2)):
                consumed.append(label)
                yield {"label": label}, value

        out = system_module._format_prom_metric_family(
            "aiia_test_total",
            help_text="A test counter.",
            metric_type="counter",
            samples=samples(),
        )

        self.assertEqual(consumed, ["a", "b"])
        self.assertEqual(out.count("# HELP aiia_test_total"), 1)
        self.assertEqual(out.count("# TYPE aiia_test_total"), 1)
        self.assertIn('aiia_test_total{label="a"} 1\n', out)
        self.assertIn('aiia_test_total{label="b"} 2\n', out)

    def test_metric_family_empty_generator_returns_empty_string(self) -> None:
        out = system_module._format_prom_metric_family(
            "aiia_test_total",
            help_text="A test counter.",
            metric_type="counter",
            samples=(sample for sample in ()),
        )

        self.assertEqual(out, "")

    def test_sse_emit_by_type_render_path_avoids_staging_list(self) -> None:
        source = inspect.getsource(system_module._render_prometheus_metrics)

        self.assertNotIn("emit_by_type_samples =", source)
        self.assertNotIn("for et, count in sorted(emit_by_type_raw.items())", source)
        self.assertIn("emit_by_type_metrics = _format_prom_metric_family(", source)
        self.assertIn(
            "samples=_iter_sse_emit_by_type_samples(emit_by_type_raw)", source
        )


if __name__ == "__main__":
    unittest.main()
