"""R546 regression coverage for allocation-free visible countdown resync."""

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


def test_force_update_all_task_countdowns_avoids_object_keys_array() -> None:
    body = _extract_function(_source(), "function forceUpdateAllTaskCountdowns(")

    assert "for (const tid in taskCountdowns)" in body
    assert "Object.prototype.hasOwnProperty.call(taskCountdowns, tid)" in body
    assert "_getOrCacheCountdownDom(tid, entry)" in body
    assert "Object.keys(taskCountdowns)" not in body
    assert ".forEach((tid)" not in body


def test_force_update_all_task_countdowns_only_resyncs_own_running_keys() -> None:
    body = _extract_function(_source(), "function forceUpdateAllTaskCountdowns(")
    script = textwrap.dedent(
        f"""
        {body}
        const helperCalls = [];
        const displayUpdates = [];
        const titles = [];
        const numbers = [];
        const strokes = [];
        const document = {{ hidden: false }};
        const activeTaskId = 'ownB';
        const taskCountdowns = Object.create({{
          inherited: {{ timer: 'shared-countdown-ticker', remaining: 9, timeout: 10 }},
        }});
        taskCountdowns.ownA = {{ timer: 'shared-countdown-ticker', remaining: 3.7, timeout: 10 }};
        taskCountdowns.stopped = {{ timer: null, remaining: 8, timeout: 10 }};
        taskCountdowns.ownB = {{ timer: 'shared-countdown-ticker', remaining: 0, timeout: 0 }};
        function _getOrCacheCountdownDom(tid, entry) {{
          helperCalls.push([tid, entry.remaining]);
          return {{
            circle: {{ setAttribute: (name, value) => strokes.push([tid, name, Number(value.toFixed(6))]) }},
            numberSpan: {{ set textContent(value) {{ numbers.push([tid, value]); }} }},
            ring: {{ set title(value) {{ titles.push([tid, value]); }} }},
          }};
        }}
        function _t(key, params) {{
          return `${{key}}:${{params.seconds}}`;
        }}
        function updateCountdownDisplay(remaining) {{
          displayUpdates.push(remaining);
        }}
        forceUpdateAllTaskCountdowns();
        console.log(JSON.stringify({{
          helperCalls,
          displayUpdates,
          titles,
          numbers,
          strokes,
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
        "helperCalls": [["ownA", 3.7], ["ownB", 0]],
        "displayUpdates": [0],
        "titles": [["ownA", "page.countdown:3"], ["ownB", "page.countdown:0"]],
        "numbers": [["ownA", 3], ["ownB", 0]],
        "strokes": [
            ["ownA", "stroke-dashoffset", 39.584067],
            ["ownB", "stroke-dashoffset", 56.548668],
        ],
        "remainingOwnKeys": ["ownA", "stopped", "ownB"],
        "inheritedStillReadable": True,
    }
