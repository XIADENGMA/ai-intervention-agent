"""R627 - Prometheus histogram bucket order fast path for ordered producers."""

from __future__ import annotations

import inspect
import unittest

from ai_intervention_agent.web_ui_routes import system as system_module


class TestPromHistogramBucketOrderFastPath(unittest.TestCase):
    def test_ordered_bucket_keys_are_preserved_with_existing_inf(self) -> None:
        buckets = {0.1: 1, 0.5: 2, system_module._PROM_INF: 2}

        keys, has_inf_bucket = system_module._prom_histogram_bucket_keys(buckets)

        self.assertTrue(has_inf_bucket)
        self.assertEqual(keys, [0.1, 0.5, system_module._PROM_INF])

    def test_unordered_bucket_keys_are_sorted_with_inf_last(self) -> None:
        buckets = {system_module._PROM_INF: 3, 0.5: 2, 0.1: 1}

        keys, has_inf_bucket = system_module._prom_histogram_bucket_keys(buckets)

        self.assertTrue(has_inf_bucket)
        self.assertEqual(keys, [0.1, 0.5, system_module._PROM_INF])

    def test_missing_inf_bucket_appends_count_bucket_without_mutating_input(
        self,
    ) -> None:
        buckets = {0.1: 1, 0.5: 2}

        keys, has_inf_bucket = system_module._prom_histogram_bucket_keys(buckets)

        self.assertFalse(has_inf_bucket)
        self.assertEqual(keys, [0.1, 0.5, system_module._PROM_INF])
        self.assertNotIn(system_module._PROM_INF, buckets)

    def test_histogram_output_still_sorts_unordered_input(self) -> None:
        out = system_module._format_prom_histogram_family(
            "aiia_test_duration_seconds",
            help_text="A test histogram.",
            observations=(
                (
                    {"provider": "bark"},
                    {system_module._PROM_INF: 3, 0.5: 2, 0.1: 1},
                    3,
                    1.1,
                ),
            ),
        )

        self.assertLess(out.index('le="0.1"'), out.index('le="0.5"'))
        self.assertLess(out.index('le="0.5"'), out.index('le="+Inf"'))

    def test_bucket_key_helper_sorts_only_after_detecting_disorder(self) -> None:
        source = inspect.getsource(system_module._prom_histogram_bucket_keys)
        family_source = inspect.getsource(system_module._format_prom_histogram_family)

        self.assertIn("bucket_keys = list(buckets)", source)
        self.assertIn("if previous_key > key:", source)
        self.assertIn("bucket_keys.sort()", source)
        self.assertIn("bucket_keys.append(_PROM_INF)", source)
        self.assertNotIn("sorted(buckets)", family_source)
        self.assertNotIn("sorted(buckets)", source)
        self.assertLess(
            source.index("if previous_key > key:"),
            source.index("bucket_keys.sort()"),
        )


if __name__ == "__main__":
    unittest.main()
