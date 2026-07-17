"""R628 - Prometheus histogram bucket sortedness scan avoids list slicing."""

from __future__ import annotations

import inspect
import unittest

from ai_intervention_agent.web_ui_routes import system as system_module


class TestPromHistogramBucketIterScan(unittest.TestCase):
    def test_empty_bucket_keys_still_append_missing_inf(self) -> None:
        keys, has_inf_bucket = system_module._prom_histogram_bucket_keys({})

        self.assertFalse(has_inf_bucket)
        self.assertEqual(keys, [system_module._PROM_INF])

    def test_single_bucket_key_still_appends_missing_inf(self) -> None:
        keys, has_inf_bucket = system_module._prom_histogram_bucket_keys({0.5: 2})

        self.assertFalse(has_inf_bucket)
        self.assertEqual(keys, [0.5, system_module._PROM_INF])

    def test_multi_bucket_ordering_behavior_is_preserved(self) -> None:
        ordered_keys, ordered_has_inf = system_module._prom_histogram_bucket_keys(
            {0.1: 1, 0.5: 2, system_module._PROM_INF: 2}
        )
        unordered_keys, unordered_has_inf = system_module._prom_histogram_bucket_keys(
            {system_module._PROM_INF: 2, 0.5: 2, 0.1: 1}
        )

        self.assertTrue(ordered_has_inf)
        self.assertTrue(unordered_has_inf)
        self.assertEqual(ordered_keys, [0.1, 0.5, system_module._PROM_INF])
        self.assertEqual(unordered_keys, [0.1, 0.5, system_module._PROM_INF])

    def test_bucket_key_helper_scans_without_slice_allocation(self) -> None:
        source = inspect.getsource(system_module._prom_histogram_bucket_keys)

        self.assertIn("key_iter = iter(bucket_keys)", source)
        self.assertIn("previous_key = next(key_iter)", source)
        self.assertIn("except StopIteration:", source)
        self.assertIn("for key in key_iter:", source)
        self.assertNotIn("bucket_keys[1:]", source)
        self.assertLess(
            source.index("key_iter = iter(bucket_keys)"),
            source.index("for key in key_iter:"),
        )


if __name__ == "__main__":
    unittest.main()
