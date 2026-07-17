"""R547 regression coverage for allocation-free countdown idle checks."""

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


def test_has_running_task_countdowns_avoids_object_keys_some_array() -> None:
    body = _extract_function(_source(), "function hasRunningTaskCountdowns(")

    assert "for (const tid in taskCountdowns)" in body
    assert "Object.prototype.hasOwnProperty.call(taskCountdowns, tid)" in body
    assert "return true" in body
    assert "return false" in body
    assert "Object.keys(taskCountdowns)" not in body
    assert ".some(" not in body


def test_has_running_task_countdowns_only_considers_own_keys_and_short_circuits() -> (
    None
):
    body = _extract_function(_source(), "function hasRunningTaskCountdowns(")
    script = textwrap.dedent(
        f"""
        const TASK_COUNTDOWN_SHARED_TIMER_SENTINEL = 'shared-countdown-ticker';
        {body}

        const inheritedOnlyVisits = [];
        let taskCountdowns = Object.create({{
          inherited: {{ timer: TASK_COUNTDOWN_SHARED_TIMER_SENTINEL }},
        }});
        Object.defineProperty(taskCountdowns, 'stopped', {{
          enumerable: true,
          get() {{
            inheritedOnlyVisits.push('stopped');
            return {{ timer: null }};
          }},
        }});
        const inheritedOnlyResult = hasRunningTaskCountdowns();

        const shortCircuitVisits = [];
        taskCountdowns = Object.create({{
          inherited: {{ timer: TASK_COUNTDOWN_SHARED_TIMER_SENTINEL }},
        }});
        Object.defineProperty(taskCountdowns, 'stopped', {{
          enumerable: true,
          get() {{
            shortCircuitVisits.push('stopped');
            return {{ timer: null }};
          }},
        }});
        Object.defineProperty(taskCountdowns, 'running', {{
          enumerable: true,
          get() {{
            shortCircuitVisits.push('running');
            return {{ timer: TASK_COUNTDOWN_SHARED_TIMER_SENTINEL }};
          }},
        }});
        Object.defineProperty(taskCountdowns, 'afterRunning', {{
          enumerable: true,
          get() {{
            throw new Error('hasRunningTaskCountdowns did not short-circuit');
          }},
        }});
        const shortCircuitResult = hasRunningTaskCountdowns();

        console.log(JSON.stringify({{
          inheritedOnlyResult,
          inheritedOnlyVisits,
          shortCircuitResult,
          shortCircuitVisits,
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
        "inheritedOnlyResult": False,
        "inheritedOnlyVisits": ["stopped"],
        "shortCircuitResult": True,
        "shortCircuitVisits": ["stopped", "running"],
        "inheritedStillReadable": True,
    }
