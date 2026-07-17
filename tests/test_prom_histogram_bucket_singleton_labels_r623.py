"""R623 - Prometheus histogram bucket labels fast path for one base label."""

from __future__ import annotations

import inspect
import unittest

from ai_intervention_agent.web_ui_routes import system as system_module


class TestPromHistogramBucketSingletonLabels(unittest.TestCase):
    def test_single_base_label_output_and_escaping_match_contract(self) -> None:
        self.assertEqual(
            system_module._format_prom_histogram_bucket_labels(
                "+Inf",
                {"provider": "bark"},
            ),
            '{le="+Inf",provider="bark"}',
        )
        self.assertEqual(
            system_module._format_prom_histogram_bucket_labels(
                "0.5",
                {"provider": 'read\\file "x"\none'},
            ),
            r'{le="0.5",provider="read\\file \"x\"\none"}',
        )

    def test_multi_label_and_legacy_le_override_paths_are_preserved(self) -> None:
        self.assertEqual(
            system_module._format_prom_histogram_bucket_labels(
                "0.1",
                {"tool": "read_file", "status": "success"},
            ),
            '{le="0.1",tool="read_file",status="success"}',
        )
        self.assertEqual(
            system_module._format_prom_histogram_bucket_labels(
                "+Inf",
                {"le": "caller", "tool": "read_file"},
            ),
            '{le="caller",tool="read_file"}',
        )

    def test_histogram_bucket_helper_has_singleton_base_label_fast_path(self) -> None:
        source = inspect.getsource(system_module._format_prom_histogram_bucket_labels)

        self.assertIn("if len(base_labels) == 1:", source)
        self.assertIn("k, v = next(iter(base_labels.items()))", source)
        self.assertLess(
            source.index('if "le" in base_labels:'),
            source.index("if len(base_labels) == 1:"),
        )
        self.assertLess(
            source.index("if len(base_labels) == 1:"), source.index('",".join(')
        )


if __name__ == "__main__":
    unittest.main()
