"""R545 regression coverage for allocation-free multi-task countdown ticking."""

from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MULTI_TASK_JS = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "multi_task.js"
)


def _source() -> str:
    return MULTI_TASK_JS.read_text(encoding="utf-8")


def _extract_function(source: str, marker: str) -> str:
    start = source.find(marker)
    assert start != -1, f"Cannot find function marker: {marker}"
    open_brace = source.find("{", start)
    assert open_brace != -1, f"Cannot find opening brace for: {marker}"
    depth = 1
    i = open_brace + 1
    while i < len(source):
        char = source[i]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start : i + 1]
        i += 1
    raise AssertionError(f"Unbalanced function body for: {marker}")


def test_tick_all_task_countdowns_avoids_object_keys_array() -> None:
    body = _extract_function(_source(), "function tickAllTaskCountdowns(")

    assert "for (const taskId in taskCountdowns)" in body
    assert "Object.prototype.hasOwnProperty.call(taskCountdowns, taskId)" in body
    assert "tickTaskCountdown(taskId)" in body
    assert "Object.keys(taskCountdowns)" not in body
    assert ".forEach((taskId)" not in body


def test_tick_all_task_countdowns_only_ticks_own_countdown_keys() -> None:
    body = _extract_function(_source(), "function tickAllTaskCountdowns(")
    script = textwrap.dedent(
        f"""
        {body}
        const ticked = [];
        let stopCalls = 0;
        let taskCountdowns = Object.create({{ inherited: {{ timer: 'shared-countdown-ticker' }} }});
        taskCountdowns.ownA = {{ timer: 'shared-countdown-ticker' }};
        taskCountdowns.ownB = {{ timer: 'shared-countdown-ticker' }};
        function tickTaskCountdown(taskId) {{
          ticked.push(taskId);
          if (taskId === 'ownA') delete taskCountdowns.ownA;
        }}
        function stopSharedTaskCountdownTickerIfIdle() {{
          stopCalls += 1;
        }}
        tickAllTaskCountdowns();
        console.log(JSON.stringify({{
          ticked,
          stopCalls,
          remainingOwnKeys: Object.keys(taskCountdowns),
          inheritedStillReadable: !!taskCountdowns.inherited,
        }}));
        """
    )
    result = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(result.stdout) == {
        "ticked": ["ownA", "ownB"],
        "stopCalls": 1,
        "remainingOwnKeys": ["ownB"],
        "inheritedStillReadable": True,
    }
