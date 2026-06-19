"""Runtime checks for ``validation-utils.js`` debounce flush semantics."""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
VALIDATION_UTILS_JS = (
    REPO_ROOT
    / "src"
    / "ai_intervention_agent"
    / "static"
    / "js"
    / "validation-utils.js"
)

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node unavailable")


def _run_node_case(case_js: str) -> dict[str, object]:
    script = textwrap.dedent(
        f"""
        const path = {json.dumps(str(VALIDATION_UTILS_JS))};
        const timers = [];
        const clearedTimers = [];

        global.window = {{
          addEventListener() {{}},
        }};
        global.document = {{
          hidden: false,
          addEventListener() {{}},
          createElement() {{
            return {{ style: {{}}, appendChild() {{}}, addEventListener() {{}} }};
          }},
          querySelector() {{
            return null;
          }},
          querySelectorAll() {{
            return [];
          }},
        }};
        global.console = {{ debug() {{}}, error() {{}}, info() {{}}, log() {{}}, warn() {{}} }};
        global.setInterval = function () {{
          throw new Error('debounce tests must not start intervals');
        }};
        global.clearInterval = function () {{}};
        global.setTimeout = function (fn, delay) {{
          const timer = {{ fn, delay, cleared: false }};
          timers.push(timer);
          return timer;
        }};
        global.clearTimeout = function (timer) {{
          timer.cleared = true;
          clearedTimers.push(timer);
        }};

        const {{ debounce }} = require(path);

        function runActiveTimers() {{
          for (const timer of timers) {{
            if (!timer.cleared) {{
              timer.cleared = true;
              timer.fn();
            }}
          }}
        }}

        {textwrap.indent(case_js, "        ")}
        """
    )
    completed = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    return json.loads(completed.stdout)


def test_flush_drains_pending_call_with_last_args_and_context() -> None:
    result = _run_node_case(
        """
        const calls = [];
        const debounced = debounce(function (value) {
          calls.push({ context: this.name, value });
          return `${this.name}:${value}`;
        }, 50);

        const firstReturn = debounced.call({ name: 'first' }, 'stale');
        const secondReturn = debounced.call({ name: 'second' }, 'fresh');
        const flushReturn = debounced.flush('ignored');
        runActiveTimers();

        process.stdout.write(JSON.stringify({
          firstReturn,
          secondReturn,
          flushReturn,
          calls,
          timerCount: timers.length,
          clearedTimerCount: clearedTimers.length,
        }));
        """
    )

    assert result == {
        "firstReturn": None,
        "secondReturn": None,
        "flushReturn": "second:fresh",
        "calls": [{"context": "second", "value": "fresh"}],
        "timerCount": 2,
        "clearedTimerCount": 2,
    }


def test_flush_without_pending_work_returns_last_result_without_reinvoking() -> None:
    result = _run_node_case(
        """
        const calls = [];
        const debounced = debounce(function (value) {
          calls.push(value);
          return `saved:${value}`;
        }, 50);

        debounced('draft');
        const firstFlush = debounced.flush();
        const secondFlush = debounced.flush();

        process.stdout.write(JSON.stringify({ firstFlush, secondFlush, calls }));
        """
    )

    assert result == {
        "firstFlush": "saved:draft",
        "secondFlush": "saved:draft",
        "calls": ["draft"],
    }


def test_cancel_drops_pending_call_and_its_saved_arguments() -> None:
    result = _run_node_case(
        """
        const calls = [];
        const debounced = debounce(function (value) {
          calls.push(value);
          return value;
        }, 50);

        const firstReturn = debounced('discard');
        debounced.cancel();
        const flushReturn = debounced.flush();
        runActiveTimers();

        process.stdout.write(JSON.stringify({ firstReturn, flushReturn, calls }));
        """
    )

    assert result == {
        "firstReturn": None,
        "flushReturn": None,
        "calls": [],
    }


def test_immediate_mode_flush_preserves_leading_only_behavior() -> None:
    result = _run_node_case(
        """
        const calls = [];
        const debounced = debounce(function (value) {
          calls.push(value);
          return value.toUpperCase();
        }, 50, true);

        const firstReturn = debounced('alpha');
        const secondReturn = debounced('beta');
        const flushReturn = debounced.flush();
        const afterFlushReturn = debounced('gamma');
        runActiveTimers();

        process.stdout.write(JSON.stringify({
          firstReturn,
          secondReturn,
          flushReturn,
          afterFlushReturn,
          calls,
        }));
        """
    )

    assert result == {
        "firstReturn": "ALPHA",
        "secondReturn": "ALPHA",
        "flushReturn": "ALPHA",
        "afterFlushReturn": "GAMMA",
        "calls": ["alpha", "gamma"],
    }
