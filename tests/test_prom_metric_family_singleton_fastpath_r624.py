"""R624 - Prometheus metric family fast path for one-sample families."""

from __future__ import annotations

import inspect
import unittest

from ai_intervention_agent.web_ui_routes import system as system_module


class TestPromMetricFamilySingletonFastPath(unittest.TestCase):
    def test_single_sample_family_output_matches_existing_contract(self) -> None:
        out = system_module._format_prom_metric_family(
            "aiia_test_total",
            help_text="A test counter.",
            metric_type="counter",
            samples=(({"event_type": "task_changed"}, 2),),
        )

        self.assertEqual(
            out,
            "# HELP aiia_test_total A test counter.\n"
            "# TYPE aiia_test_total counter\n"
            'aiia_test_total{event_type="task_changed"} 2\n',
        )

    def test_empty_and_multi_sample_families_are_preserved(self) -> None:
        self.assertEqual(
            system_module._format_prom_metric_family(
                "aiia_test_total",
                help_text="A test counter.",
                metric_type="counter",
                samples=(),
            ),
            "",
        )

        out = system_module._format_prom_metric_family(
            "aiia_test_total",
            help_text="A test counter.",
            metric_type="counter",
            samples=(
                ({"event_type": "a"}, 1),
                ({"event_type": "b"}, 2),
            ),
        )

        self.assertEqual(out.count("# HELP aiia_test_total"), 1)
        self.assertEqual(out.count("# TYPE aiia_test_total counter"), 1)
        self.assertIn('aiia_test_total{event_type="a"} 1\n', out)
        self.assertIn('aiia_test_total{event_type="b"} 2\n', out)

    def test_one_pass_generator_is_consumed_once(self) -> None:
        consumed: list[str] = []

        def samples():
            for label, value in (("a", 1),):
                consumed.append(label)
                yield {"event_type": label}, value

        out = system_module._format_prom_metric_family(
            "aiia_test_total",
            help_text="A test counter.",
            metric_type="counter",
            samples=samples(),
        )

        self.assertEqual(consumed, ["a"])
        self.assertIn('aiia_test_total{event_type="a"} 1\n', out)

    def test_metric_family_has_singleton_fast_path_before_out_lines(self) -> None:
        source = inspect.getsource(system_module._format_prom_metric_family)

        self.assertIn('header = f"# HELP {name} {help_text}', source)
        self.assertIn(
            'first_line = f"{name}{first_label_str} {first_value_str}\\n"', source
        )
        self.assertIn("second_labels, second_value = next(sample_iter)", source)
        self.assertIn("return header + first_line", source)
        self.assertLess(
            source.index("return header + first_line"),
            source.index("out_lines: list[str]"),
        )


if __name__ == "__main__":
    unittest.main()
