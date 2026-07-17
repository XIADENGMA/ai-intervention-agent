"""R626 - Prometheus value formatter fast path for exact integers."""

from __future__ import annotations

import inspect
import unittest

from ai_intervention_agent.web_ui_routes import system as system_module


class TestPromValueExactIntFastPath(unittest.TestCase):
    def test_exact_int_value_returns_decimal_string(self) -> None:
        self.assertEqual(system_module._format_prom_value(42), "42")
        self.assertEqual(system_module._format_prom_value(-7), "-7")

    def test_bool_values_keep_numeric_prometheus_contract(self) -> None:
        self.assertEqual(system_module._format_prom_value(True), "1")
        self.assertEqual(system_module._format_prom_value(False), "0")

    def test_float_values_keep_existing_special_cases(self) -> None:
        self.assertEqual(system_module._format_prom_value(0.25), "0.25")
        self.assertEqual(system_module._format_prom_value(float("inf")), "+Inf")
        self.assertEqual(system_module._format_prom_value(float("-inf")), "-Inf")
        self.assertEqual(system_module._format_prom_value(float("nan")), "NaN")

    def test_value_formatter_has_exact_int_fast_path_before_float_branch(self) -> None:
        source = inspect.getsource(system_module._format_prom_value)

        self.assertIn("if type(value) is int:", source)
        self.assertIn("return str(value)", source)
        self.assertIn("if isinstance(value, float):", source)
        self.assertIn("return str(int(value))", source)
        self.assertLess(
            source.index("if type(value) is int:"),
            source.index("if isinstance(value, float):"),
        )


if __name__ == "__main__":
    unittest.main()
