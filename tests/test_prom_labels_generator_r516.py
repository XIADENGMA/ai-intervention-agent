"""R516 - Prometheus label rendering avoids a temporary parts list."""

from __future__ import annotations

import inspect
import unittest

from ai_intervention_agent.web_ui_routes import system as system_module


class TestPromLabelsGeneratorJoin(unittest.TestCase):
    def test_format_prom_labels_joins_generator_without_parts_list(self) -> None:
        source = inspect.getsource(system_module._format_prom_labels)

        self.assertIn('",".join(', source)
        self.assertIn("for k, v in labels.items()", source)
        self.assertNotIn("parts = [", source)
        self.assertNotIn("join(parts)", source)

    def test_empty_labels_still_render_empty_string(self) -> None:
        self.assertEqual(system_module._format_prom_labels(None), "")
        self.assertEqual(system_module._format_prom_labels({}), "")

    def test_label_order_and_escaping_are_unchanged(self) -> None:
        labels = {
            "path": 'C:\\foo "bar"',
            "line": "one\ntwo",
            "count": "3",
        }

        self.assertEqual(
            system_module._format_prom_labels(labels),
            r'{path="C:\\foo \"bar\"",line="one\ntwo",count="3"}',
        )


if __name__ == "__main__":
    unittest.main()
