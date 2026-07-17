"""R617 - Prometheus histogram +Inf fallback avoids copy and second sort."""

from __future__ import annotations

import inspect
import math
import unittest

from ai_intervention_agent.web_ui_routes import system as system_module


class TestPromHistogramInfFallback(unittest.TestCase):
    def test_histogram_inf_fallback_appends_without_copying_buckets(self) -> None:
        source = inspect.getsource(system_module._format_prom_histogram_family)
        helper_source = inspect.getsource(system_module._prom_histogram_bucket_keys)

        assert (
            "sorted_keys, has_inf_bucket = _prom_histogram_bucket_keys(buckets)"
            in source
        )
        assert "bucket_keys = list(buckets)" in helper_source
        assert "bucket_keys.sort()" in helper_source
        assert "sorted(buckets.keys())" not in source
        assert "buckets = dict(buckets)" not in source
        assert "buckets[_PROM_INF] = count" not in source
        assert "bucket_keys.append(_PROM_INF)" in helper_source
        assert "if has_inf_bucket or le != _PROM_INF:" in source
        assert "bucket_value_str = _format_prom_value(buckets[le])" in source
        assert "count_value_str = _format_prom_value(count)" in source

    def test_missing_inf_bucket_renders_count_without_mutating_input(self) -> None:
        buckets = {0.5: 3, 0.1: 1}

        out = system_module._format_prom_histogram_family(
            "aiia_test_duration_seconds",
            help_text="A test histogram.",
            observations=(
                (
                    {"label": "missing"},
                    buckets,
                    7,
                    2.5,
                ),
            ),
        )

        self.assertNotIn(math.inf, buckets)
        self.assertIn(
            'aiia_test_duration_seconds_bucket{le="0.1",label="missing"} 1\n',
            out,
        )
        self.assertIn(
            'aiia_test_duration_seconds_bucket{le="0.5",label="missing"} 3\n',
            out,
        )
        self.assertIn(
            'aiia_test_duration_seconds_bucket{le="+Inf",label="missing"} 7\n',
            out,
        )
        self.assertLess(
            out.index('le="0.5"'),
            out.index('le="+Inf"'),
        )

    def test_existing_inf_bucket_value_is_preserved(self) -> None:
        out = system_module._format_prom_histogram_family(
            "aiia_test_duration_seconds",
            help_text="A test histogram.",
            observations=(
                (
                    {"label": "existing"},
                    {0.1: 1, math.inf: 5},
                    7,
                    2.5,
                ),
            ),
        )

        self.assertIn(
            'aiia_test_duration_seconds_bucket{le="+Inf",label="existing"} 5\n',
            out,
        )
        self.assertIn('aiia_test_duration_seconds_count{label="existing"} 7\n', out)


if __name__ == "__main__":
    unittest.main()
