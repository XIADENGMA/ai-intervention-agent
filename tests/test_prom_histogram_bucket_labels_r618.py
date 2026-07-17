"""R618 - Prometheus histogram bucket labels avoid per-bucket dict merges."""

from __future__ import annotations

import inspect
import unittest

from ai_intervention_agent.web_ui_routes import system as system_module


class TestPromHistogramBucketLabels(unittest.TestCase):
    def test_histogram_render_path_uses_bucket_label_helper(self) -> None:
        source = inspect.getsource(system_module._format_prom_histogram_family)

        assert 'merged_labels = {"le": le_label_value' not in source
        assert "_format_prom_histogram_bucket_labels(" in source
        assert "_format_prom_labels(merged_labels)" not in source

    def test_bucket_label_helper_streams_le_then_base_labels(self) -> None:
        label_str = system_module._format_prom_histogram_bucket_labels(
            "+Inf",
            {
                "tool": 'read\\file "x"',
                "line": "one\ntwo",
            },
        )

        self.assertEqual(
            label_str,
            r'{le="+Inf",tool="read\\file \"x\"",line="one\ntwo"}',
        )

    def test_bucket_label_helper_preserves_legacy_le_override_edge_case(self) -> None:
        label_str = system_module._format_prom_histogram_bucket_labels(
            "+Inf",
            {
                "le": "caller",
                "tool": "read_file",
            },
        )

        self.assertEqual(label_str, '{le="caller",tool="read_file"}')

    def test_histogram_output_preserves_bucket_label_order(self) -> None:
        out = system_module._format_prom_histogram_family(
            "aiia_test_duration_seconds",
            help_text="A test histogram.",
            observations=(
                (
                    {"tool": "read_file", "status": "success"},
                    {0.1: 1, 0.5: 2, system_module._PROM_INF: 2},
                    2,
                    0.3,
                ),
            ),
        )

        self.assertIn(
            'aiia_test_duration_seconds_bucket{le="0.1",tool="read_file",'
            'status="success"} 1\n',
            out,
        )
        self.assertIn(
            'aiia_test_duration_seconds_bucket{le="+Inf",tool="read_file",'
            'status="success"} 2\n',
            out,
        )


if __name__ == "__main__":
    unittest.main()
