"""R621 - Prometheus label escaping skips replace passes for plain values."""

from __future__ import annotations

import inspect
import unittest

from ai_intervention_agent.web_ui_routes import system as system_module


class TestPromLabelEscapeFastPath(unittest.TestCase):
    def test_plain_label_value_returns_unchanged(self) -> None:
        self.assertEqual(
            system_module._escape_prom_label_value("task_changed"),
            "task_changed",
        )
        self.assertEqual(
            system_module._format_prom_labels({"event_type": "task_changed"}),
            '{event_type="task_changed"}',
        )

    def test_required_escapes_still_apply_in_order(self) -> None:
        self.assertEqual(
            system_module._escape_prom_label_value('read\\file "x"\none'),
            r"read\\file \"x\"\none",
        )

    def test_escape_helper_has_no_escape_guard_before_replace_loop(self) -> None:
        source = inspect.getsource(system_module._escape_prom_label_value)

        guard = 'if "\\\\" not in value and \'"\' not in value and "\\n" not in value:'
        self.assertIn(guard, source)
        self.assertLess(
            source.index(guard), source.index("for old, new in _PROM_LABEL_ESCAPES")
        )
        self.assertIn("return value", source[: source.index("out = value")])
        self.assertIn("out = out.replace(old, new)", source)


if __name__ == "__main__":
    unittest.main()
