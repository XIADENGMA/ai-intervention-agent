"""R625 - Prometheus single metric fast path for unlabeled samples."""

from __future__ import annotations

import inspect
import unittest

from ai_intervention_agent.web_ui_routes import system as system_module


class TestPromMetricNoLabelFastPath(unittest.TestCase):
    def test_none_labels_output_matches_existing_contract(self) -> None:
        out = system_module._format_prom_metric(
            "aiia_test_total",
            3,
            help_text="A test counter.",
            metric_type="counter",
        )

        self.assertEqual(
            out,
            "# HELP aiia_test_total A test counter.\n"
            "# TYPE aiia_test_total counter\n"
            "aiia_test_total 3\n",
        )

    def test_empty_labels_output_remains_unlabeled(self) -> None:
        out = system_module._format_prom_metric(
            "aiia_test_total",
            3,
            help_text="A test counter.",
            metric_type="counter",
            labels={},
        )

        self.assertEqual(
            out,
            "# HELP aiia_test_total A test counter.\n"
            "# TYPE aiia_test_total counter\n"
            "aiia_test_total 3\n",
        )

    def test_labeled_output_and_escaping_are_preserved(self) -> None:
        out = system_module._format_prom_metric(
            "aiia_test_total",
            3,
            help_text="A test counter.",
            metric_type="counter",
            labels={"env": 'prod "x"'},
        )

        self.assertEqual(
            out,
            "# HELP aiia_test_total A test counter.\n"
            "# TYPE aiia_test_total counter\n"
            'aiia_test_total{env="prod \\"x\\""} 3\n',
        )

    def test_metric_has_no_label_fast_path_before_label_formatting(self) -> None:
        source = inspect.getsource(system_module._format_prom_metric)

        self.assertIn("value_str = _format_prom_value(value)", source)
        self.assertIn("if not labels:", source)
        self.assertIn('f"{name} {value_str}\\n"', source)
        self.assertIn("label_str = _format_prom_labels(labels)", source)
        self.assertLess(
            source.index("if not labels:"),
            source.index("label_str = _format_prom_labels(labels)"),
        )


if __name__ == "__main__":
    unittest.main()
