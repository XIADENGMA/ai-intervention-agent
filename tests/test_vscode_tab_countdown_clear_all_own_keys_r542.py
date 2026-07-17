"""R542 regression coverage for allocation-free tab countdown cleanup."""

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


def test_clear_all_tab_countdowns_avoids_object_keys_array() -> None:
    body = _extract_function(_source(), "function clearAllTabCountdowns(")

    assert "for (const taskId in tabCountdownTimers)" in body
    assert "Object.prototype.hasOwnProperty.call(tabCountdownTimers, taskId)" in body
    assert "Object.keys(tabCountdownTimers)" not in body
    assert ".forEach(taskId =>" not in body
    assert "clearInterval(tabCountdownTickerTimer)" in body
    assert "tabCountdownTimers = {}" in body
    assert "tabCountdownRemaining = {}" in body


def test_clear_all_tab_countdowns_clears_only_own_legacy_timer_entries() -> None:
    body = _extract_function(_source(), "function clearAllTabCountdowns(")
    script = textwrap.dedent(
        f"""
        {body}
        const cleared = [];
        let tabCountdownTickerTimer = 99;
        let tabCountdownTimers = Object.create({{ inheritedLegacyTimer: 77 }});
        tabCountdownTimers.legacyTimer = 11;
        tabCountdownTimers.stateObject = {{ remaining: 5 }};
        let tabCountdownRemaining = Object.create({{ inheritedRemaining: 3 }});
        tabCountdownRemaining.legacyTimer = 4;
        tabCountdownRemaining.stateObject = 5;
        function clearInterval(id) {{
          cleared.push(id);
        }}
        clearAllTabCountdowns();
        console.log(JSON.stringify({{
          cleared,
          ticker: tabCountdownTickerTimer,
          timerOwnKeys: Object.keys(tabCountdownTimers),
          remainingOwnKeys: Object.keys(tabCountdownRemaining),
          inheritedTimerStillVisible: !!tabCountdownTimers.inheritedLegacyTimer,
          inheritedRemainingStillVisible: !!tabCountdownRemaining.inheritedRemaining,
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
        "cleared": [11, 99],
        "ticker": None,
        "timerOwnKeys": [],
        "remainingOwnKeys": [],
        "inheritedTimerStillVisible": False,
        "inheritedRemainingStillVisible": False,
    }
