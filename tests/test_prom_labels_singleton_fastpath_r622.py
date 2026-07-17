"""R622 - Prometheus label formatter fast path for single-label mappings."""

from __future__ import annotations

import inspect
import unittest

from ai_intervention_agent.web_ui_routes import system as system_module


class TestPromLabelsSingletonFastPath(unittest.TestCase):
    def test_single_label_output_and_escaping_match_existing_contract(self) -> None:
        self.assertEqual(
            system_module._format_prom_labels({"event_type": "task_changed"}),
            '{event_type="task_changed"}',
        )
        self.assertEqual(
            system_module._format_prom_labels({"event_type": 'read\\file "x"\none'}),
            r'{event_type="read\\file \"x\"\none"}',
        )

    def test_empty_and_multi_label_paths_are_preserved(self) -> None:
        self.assertEqual(system_module._format_prom_labels(None), "")
        self.assertEqual(system_module._format_prom_labels({}), "")
        self.assertEqual(
            system_module._format_prom_labels(
                {"tool": "read_file", "status": "success"}
            ),
            '{tool="read_file",status="success"}',
        )

    def test_format_prom_labels_has_singleton_fast_path_before_join(self) -> None:
        source = inspect.getsource(system_module._format_prom_labels)

        self.assertIn("if len(labels) == 1:", source)
        self.assertIn("k, v = next(iter(labels.items()))", source)
        self.assertLess(source.index("if len(labels) == 1:"), source.index('",".join('))
        self.assertIn(
            "return f'{{{k}=\"{_escape_prom_label_value(str(v))}\"}}'", source
        )


if __name__ == "__main__":
    unittest.main()
