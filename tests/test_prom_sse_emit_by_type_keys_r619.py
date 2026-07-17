"""R619 - Prometheus SSE emit-by-type samples avoid sorted item tuple staging."""

from __future__ import annotations

import inspect
import unittest

from ai_intervention_agent.web_ui_routes import system as system_module


class TestPromSseEmitByTypeKeys(unittest.TestCase):
    def test_helper_sorts_keys_and_filters_non_numeric_counts(self) -> None:
        samples = list(
            system_module._iter_sse_emit_by_type_samples(
                {"task_changed": 2, "heartbeat": 1, "bad": "3"}
            )
        )

        self.assertEqual(
            samples,
            [
                ({"event_type": "heartbeat"}, 1),
                ({"event_type": "task_changed"}, 2),
            ],
        )

    def test_helper_preserves_mixed_key_sort_type_error(self) -> None:
        with self.assertRaises(TypeError):
            list(system_module._iter_sse_emit_by_type_samples({"a": 1, 2: 3}))

    def test_render_path_uses_key_iterator_without_sorted_items(self) -> None:
        render_source = inspect.getsource(system_module._render_prometheus_metrics)
        helper_source = inspect.getsource(system_module._iter_sse_emit_by_type_samples)

        self.assertNotIn("sorted(emit_by_type_raw.items())", render_source)
        self.assertIn(
            "samples=_iter_sse_emit_by_type_samples(emit_by_type_raw)",
            render_source,
        )
        self.assertIn("if len(emit_by_type) == 1:", helper_source)
        self.assertIn("for event_type in sorted(emit_by_type):", helper_source)
        self.assertIn("count = emit_by_type[event_type]", helper_source)
        self.assertIn("isinstance(count, int | float)", helper_source)
        self.assertIn(
            'yield {"event_type": str(event_type)}, int(count)',
            helper_source,
        )


if __name__ == "__main__":
    unittest.main()
