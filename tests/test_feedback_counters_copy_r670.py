from __future__ import annotations

import inspect
from collections import UserDict
from typing import Any, cast
from unittest.mock import patch

from ai_intervention_agent import server, server_feedback


def test_get_feedback_counters_uses_dict_copy_snapshot() -> None:
    source = inspect.getsource(server_feedback.get_feedback_counters)

    assert "return _FEEDBACK_COUNTERS.copy()" in source
    assert "return dict(_FEEDBACK_COUNTERS)" not in source


def test_server_info_resource_avoids_redundant_getter_copy() -> None:
    source = inspect.getsource(server.server_info_resource)

    assert "counters = getter()" in source
    assert "isinstance(counters, dict)" in source
    assert "feedback_counters_info = dict(getter())" not in source


def test_get_feedback_counters_snapshot_mutation_does_not_pollute_state() -> None:
    with server_feedback._FEEDBACK_COUNTERS_LOCK:
        saved = server_feedback._FEEDBACK_COUNTERS.copy()
        server_feedback._FEEDBACK_COUNTERS["created_total"] = 7

    try:
        snapshot = server_feedback.get_feedback_counters()
        snapshot["created_total"] = 999

        with server_feedback._FEEDBACK_COUNTERS_LOCK:
            assert server_feedback._FEEDBACK_COUNTERS["created_total"] == 7
    finally:
        with server_feedback._FEEDBACK_COUNTERS_LOCK:
            server_feedback._FEEDBACK_COUNTERS.clear()
            server_feedback._FEEDBACK_COUNTERS.update(saved)


def test_server_info_resource_accepts_non_dict_mapping_counter_snapshot() -> None:
    counters = UserDict(
        {
            "created_total": 3,
            "completed_total": 2,
            "failed_total": 1,
        }
    )

    with patch.object(server_feedback, "get_feedback_counters", return_value=counters):
        info = server.server_info_resource()

    block = cast(dict[str, Any], info["interactive_feedback"])
    assert block == {
        "created_total": 3,
        "completed_total": 2,
        "failed_total": 1,
    }
    assert isinstance(block, dict)
