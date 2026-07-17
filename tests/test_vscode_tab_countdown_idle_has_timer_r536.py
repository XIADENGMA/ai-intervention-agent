"""R536 regression coverage for allocation-free tab countdown idle checks."""

from __future__ import annotations

import json
import subprocess
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


def test_stop_shared_tab_countdown_idle_check_avoids_object_keys_array() -> None:
    source = _source()
    has_timers = _extract_function(source, "function hasTabCountdownTimers(")
    stop_idle = _extract_function(
        source, "function stopSharedTabCountdownTickerIfIdle("
    )

    assert "for (const taskId in tabCountdownTimers)" in has_timers
    assert (
        "Object.prototype.hasOwnProperty.call(tabCountdownTimers, taskId)" in has_timers
    )
    assert "Object.keys(" not in has_timers
    assert "hasTabCountdownTimers()" in stop_idle
    assert "Object.keys(tabCountdownTimers).length" not in stop_idle


def test_stop_shared_tab_countdown_idle_check_only_counts_own_timers() -> None:
    source = _source()
    has_timers = _extract_function(source, "function hasTabCountdownTimers(")
    stop_idle = _extract_function(
        source, "function stopSharedTabCountdownTickerIfIdle("
    )
    script = f"""
{has_timers}
{stop_idle}
const cleared = []
function clearInterval(id) {{
  cleared.push(id)
}}
let tabCountdownTickerTimer = 42
let tabCountdownTimers = Object.create({{ inherited: true }})
const inheritedOnly = hasTabCountdownTimers()
stopSharedTabCountdownTickerIfIdle()
const afterInheritedOnly = {{ ticker: tabCountdownTickerTimer, cleared: cleared.slice() }}
tabCountdownTickerTimer = 43
tabCountdownTimers = {{ active: {{}} }}
const ownActive = hasTabCountdownTimers()
stopSharedTabCountdownTickerIfIdle()
const afterOwnActive = {{ ticker: tabCountdownTickerTimer, cleared: cleared.slice() }}
tabCountdownTickerTimer = 44
tabCountdownTimers = {{}}
const empty = hasTabCountdownTimers()
stopSharedTabCountdownTickerIfIdle()
const afterEmpty = {{ ticker: tabCountdownTickerTimer, cleared: cleared.slice() }}
console.log(JSON.stringify({{
  inheritedOnly,
  afterInheritedOnly,
  ownActive,
  afterOwnActive,
  empty,
  afterEmpty
}}))
"""
    result = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)

    assert payload == {
        "inheritedOnly": False,
        "afterInheritedOnly": {"ticker": None, "cleared": [42]},
        "ownActive": True,
        "afterOwnActive": {"ticker": 43, "cleared": [42]},
        "empty": False,
        "afterEmpty": {"ticker": None, "cleared": [42, 44]},
    }
