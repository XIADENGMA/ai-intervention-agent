"""R657: ``/metrics`` reuses the MCP metrics module binding within scrapes."""

from __future__ import annotations

import inspect
from collections.abc import Mapping
from types import SimpleNamespace
from unittest.mock import patch

from ai_intervention_agent.web_ui_routes import system as system_module


def test_cached_mcp_metrics_module_returns_without_import_work() -> None:
    fake_module = SimpleNamespace()

    with patch.object(system_module, "_MCP_TOOL_CALL_METRICS_MODULE", fake_module):
        with patch(
            "builtins.__import__",
            side_effect=AssertionError("cached module should avoid import"),
        ):
            assert system_module._get_mcp_tool_call_metrics_module() is fake_module


def test_mcp_metrics_import_failure_does_not_poison_cache() -> None:
    original_import = __import__

    def _raise_for_mcp_metrics(
        name: str,
        globals: Mapping[str, object] | None = None,
        locals: Mapping[str, object] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> object:
        if name == "ai_intervention_agent" and "mcp_tool_call_metrics" in fromlist:
            raise ImportError("metrics module unavailable")
        return original_import(name, globals, locals, fromlist, level)

    with patch.object(system_module, "_MCP_TOOL_CALL_METRICS_MODULE", None):
        with patch("builtins.__import__", side_effect=_raise_for_mcp_metrics):
            assert system_module._get_mcp_tool_call_metrics_module() is None
        assert system_module._MCP_TOOL_CALL_METRICS_MODULE is None
        assert system_module._get_mcp_tool_call_metrics_module() is not None


def test_render_uses_one_mcp_metrics_module_lookup_for_counter_and_latency() -> None:
    fake_module = SimpleNamespace(
        get_mcp_tool_call_stats=lambda: {
            "interactive_feedback": {"success": 2, "failure": 0, "total": 2}
        },
        get_mcp_tool_call_latency_snapshot=lambda: {
            ("interactive_feedback", "success"): {
                "count": 2,
                "sum_seconds": 0.5,
                "buckets": {0.1: 1, 0.5: 2, float("inf"): 2},
            }
        },
    )

    with patch.object(
        system_module,
        "_get_mcp_tool_call_metrics_module",
        return_value=fake_module,
    ) as module_spy:
        text = system_module._render_prometheus_metrics()

    module_spy.assert_called_once_with()
    assert "aiia_mcp_tool_calls_total" in text
    assert "aiia_mcp_tool_call_duration_seconds_bucket" in text


def test_mcp_counter_failure_still_allows_latency_metrics() -> None:
    def _raise_stats() -> dict[str, object]:
        raise RuntimeError("counter snapshot failed")

    fake_module = SimpleNamespace(
        get_mcp_tool_call_stats=_raise_stats,
        get_mcp_tool_call_latency_snapshot=lambda: {
            ("interactive_feedback", "success"): {
                "count": 1,
                "sum_seconds": 0.1,
                "buckets": {0.1: 1, float("inf"): 1},
            }
        },
    )

    with patch.object(
        system_module,
        "_get_mcp_tool_call_metrics_module",
        return_value=fake_module,
    ):
        text = system_module._render_prometheus_metrics()

    assert "aiia_mcp_tool_calls_total" not in text
    assert "aiia_mcp_tool_call_duration_seconds_bucket" in text


def test_mcp_latency_failure_still_allows_counter_metrics() -> None:
    def _raise_latency() -> dict[str, object]:
        raise RuntimeError("latency snapshot failed")

    fake_module = SimpleNamespace(
        get_mcp_tool_call_stats=lambda: {
            "interactive_feedback": {"success": 3, "failure": 1, "total": 4}
        },
        get_mcp_tool_call_latency_snapshot=_raise_latency,
    )

    with patch.object(
        system_module,
        "_get_mcp_tool_call_metrics_module",
        return_value=fake_module,
    ):
        text = system_module._render_prometheus_metrics()

    assert "aiia_mcp_tool_calls_total" in text
    assert "aiia_mcp_tool_call_duration_seconds_bucket" not in text


def test_render_no_longer_imports_mcp_metrics_functions_twice() -> None:
    source = inspect.getsource(system_module._render_prometheus_metrics)
    helper_source = inspect.getsource(system_module._get_mcp_tool_call_metrics_module)

    assert "from ai_intervention_agent.mcp_tool_call_metrics import" not in source
    assert source.count("_get_mcp_tool_call_metrics_module()") == 1
    assert (
        helper_source.count("from ai_intervention_agent import mcp_tool_call_metrics")
        == 1
    )
