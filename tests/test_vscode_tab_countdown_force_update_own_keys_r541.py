"""R541 regression coverage for allocation-free visible tab countdown resync."""

from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WEBVIEW_UI_JS = REPO_ROOT / "packages" / "vscode" / "webview-ui.js"


def _source() -> str:
    return WEBVIEW_UI_JS.read_text(encoding="utf-8")


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


def test_force_update_all_tab_countdowns_avoids_object_keys_array() -> None:
    body = _extract_function(_source(), "function forceUpdateAllTabCountdowns(")

    assert "if (typeof document !== 'undefined' && document.hidden) return" in body
    assert "for (const taskId in tabCountdownTimers)" in body
    assert "Object.prototype.hasOwnProperty.call(tabCountdownTimers, taskId)" in body
    assert "Object.keys(tabCountdownTimers)" not in body
    assert ".forEach(taskId =>" not in body


def test_force_update_all_tab_countdowns_only_resyncs_own_visible_timers() -> None:
    source = _source()
    parts = "\n\n".join(
        _extract_function(source, marker)
        for marker in (
            "function hasTabCountdownTimers(",
            "function stopSharedTabCountdownTickerIfIdle(",
            "function forceUpdateAllTabCountdowns(",
        )
    )
    script = textwrap.dedent(
        f"""
        {parts}
        const rendered = [];
        const stopped = [];
        let document = {{ hidden: true }};
        let tabCountdownTickerTimer = 9;
        let tabCountdownRemaining = {{}};
        let tabCountdownTimers = Object.create({{ inherited: {{ remaining: 7 }} }});
        tabCountdownTimers.expired = {{ remaining: 0 }};
        tabCountdownTimers.live = {{ remaining: 3 }};
        function computeTabCountdownRemaining(taskId, state) {{
          return {{ deadline: null, computedRemaining: Math.max(0, state.remaining) }};
        }}
        function renderTabCountdown(taskId, state, computedRemaining) {{
          rendered.push([taskId, computedRemaining]);
        }}
        function clearInterval(id) {{
          stopped.push(id);
        }}
        forceUpdateAllTabCountdowns();
        const afterHidden = {{
          rendered: rendered.slice(),
          remainingKeys: Object.keys(tabCountdownRemaining),
          timerKeys: Object.keys(tabCountdownTimers),
          ticker: tabCountdownTickerTimer,
        }};
        document.hidden = false;
        forceUpdateAllTabCountdowns();
        console.log(JSON.stringify({{
          afterHidden,
          afterVisible: {{
            rendered,
            remaining: tabCountdownRemaining,
            timerKeys: Object.keys(tabCountdownTimers),
            inheritedStillReadable: !!tabCountdownTimers.inherited,
            ticker: tabCountdownTickerTimer,
            stopped,
          }},
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
        "afterHidden": {
            "rendered": [],
            "remainingKeys": [],
            "timerKeys": ["expired", "live"],
            "ticker": 9,
        },
        "afterVisible": {
            "rendered": [["live", 3]],
            "remaining": {"live": 3},
            "timerKeys": ["live"],
            "inheritedStillReadable": True,
            "ticker": 9,
            "stopped": [],
        },
    }
