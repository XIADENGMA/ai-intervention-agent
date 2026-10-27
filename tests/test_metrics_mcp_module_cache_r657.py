"""R657: ``/metrics`` reuses the MCP metrics module binding within scrapes.

R904 changed how the helper finds the module. It used to import it on first use and
keep the binding; it now only looks it up in ``sys.modules`` and never imports it,
because the Web UI process that serves ``/metrics`` never runs the middleware (its two
snapshots are always empty there) and the module imports fastmcp, which cost that
process about 33 MiB and 230 ms for a scrape. What R657 asked for stays: one lookup
per scrape, shared by the counter and the latency family, and a failure of one family
does not hide the other.
"""

from __future__ import annotations

import builtins
import inspect
import sys
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from ai_intervention_agent.web_ui_routes import system as system_module

_MODULE_KEY = "ai_intervention_agent.mcp_tool_call_metrics"


def test_a_loaded_mcp_metrics_module_is_returned_without_import_work() -> None:
    fake_module = SimpleNamespace()

    with patch.dict(sys.modules, {_MODULE_KEY: fake_module}):
        with patch(
            "builtins.__import__",
            side_effect=AssertionError("a loaded module needs no import"),
        ):
            assert system_module._get_mcp_tool_call_metrics_module() is fake_module


def test_a_module_that_is_not_loaded_is_not_imported_for_a_scrape() -> None:
    real_import = builtins.__import__
    asked_for: list[str] = []

    def _record(name: str, *args: Any, **kwargs: Any) -> Any:
        asked_for.append(name)
        return real_import(name, *args, **kwargs)

    with patch.dict(sys.modules):
        sys.modules.pop(_MODULE_KEY, None)
        with patch("builtins.__import__", side_effect=_record):
            found = system_module._get_mcp_tool_call_metrics_module()
        assert _MODULE_KEY not in sys.modules, "the lookup must not load the module"

    assert found is None
    assert not [name for name in asked_for if "mcp_tool_call_metrics" in name]


def test_a_blocked_module_entry_means_no_module() -> None:
    with patch.dict(sys.modules, {_MODULE_KEY: None}):  # type: ignore[dict-item]
        assert system_module._get_mcp_tool_call_metrics_module() is None


def test_the_lookup_follows_the_module_table_not_an_old_binding() -> None:
    first, second = SimpleNamespace(), SimpleNamespace()

    with patch.dict(sys.modules, {_MODULE_KEY: first}):
        assert system_module._get_mcp_tool_call_metrics_module() is first
    with patch.dict(sys.modules, {_MODULE_KEY: second}):
        assert system_module._get_mcp_tool_call_metrics_module() is second


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
    assert "import mcp_tool_call_metrics" not in helper_source
    assert "importlib" not in helper_source
    assert 'sys.modules.get("ai_intervention_agent.mcp_tool_call_metrics")' in (
        helper_source
    )
