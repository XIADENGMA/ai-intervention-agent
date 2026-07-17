"""R498: VS Code task-tab countdowns share one 1Hz ticker."""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WEBVIEW_UI_JS = REPO_ROOT / "packages" / "vscode" / "webview-ui.js"


def _read_source() -> str:
    return WEBVIEW_UI_JS.read_text(encoding="utf-8")


def _node_available() -> bool:
    return shutil.which("node") is not None


def _extract_function(source: str, name: str) -> str:
    marker = f"function {name}("
    start = source.index(marker)
    brace = source.index("{", start)
    depth = 0
    for index in range(brace, len(source)):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
    raise AssertionError(f"Could not extract {name}()")


def test_start_tab_countdown_uses_shared_ticker() -> None:
    source = _read_source()
    start_body = _extract_function(source, "startTabCountdown")

    assert "setInterval(" not in start_body
    assert "tickTabCountdown(taskId)" in start_body
    assert "ensureSharedTabCountdownTicker()" in start_body
    assert "setInterval(update, 1000)" not in source


def test_shared_tab_ticker_drives_all_registered_countdowns() -> None:
    source = _read_source()
    ensure_body = _extract_function(source, "ensureSharedTabCountdownTicker")
    tick_all_body = _extract_function(source, "tickAllTabCountdowns")

    assert "let tabCountdownTickerTimer = null" in source
    assert "setInterval(tickAllTabCountdowns, 1000)" in ensure_body
    assert "for (const taskId in tabCountdownTimers)" in tick_all_body
    assert (
        "Object.prototype.hasOwnProperty.call(tabCountdownTimers, taskId)"
        in tick_all_body
    )
    assert "Object.keys(tabCountdownTimers)" not in tick_all_body


def test_tab_countdown_cleanup_stops_shared_ticker_when_idle() -> None:
    source = _read_source()
    tick_body = _extract_function(source, "tickTabCountdown")
    stop_idle_body = _extract_function(source, "stopSharedTabCountdownTickerIfIdle")
    clear_all_body = _extract_function(source, "clearAllTabCountdowns")

    assert "delete tabCountdownTimers[taskId]" in tick_body
    assert "delete tabCountdownRemaining[taskId]" in tick_body
    assert "stopSharedTabCountdownTickerIfIdle()" in tick_body
    assert "hasTabCountdownTimers()" in stop_idle_body
    assert "Object.keys(tabCountdownTimers).length" not in stop_idle_body
    assert "clearInterval(tabCountdownTickerTimer)" in stop_idle_body
    assert "clearInterval(tabCountdownTickerTimer)" in clear_all_body
    assert "for (const taskId in tabCountdownTimers)" in clear_all_body
    assert (
        "Object.prototype.hasOwnProperty.call(tabCountdownTimers, taskId)"
        in clear_all_body
    )
    assert "Object.keys(tabCountdownTimers)" not in clear_all_body
    assert "tabCountdownTickerTimer = null" in clear_all_body


def test_runtime_starts_one_interval_for_multiple_tab_countdowns() -> None:
    if not _node_available():
        raise AssertionError("node runtime unavailable")

    source = _read_source()
    parts = "\n\n".join(
        _extract_function(source, name)
        for name in (
            "hasTabCountdownTimers",
            "stopSharedTabCountdownTickerIfIdle",
            "ensureSharedTabCountdownTicker",
            "tickAllTabCountdowns",
            "_getOrCacheTabCountdownDom",
            "computeTabCountdownRemaining",
            "renderTabCountdown",
            "tickTabCountdown",
            "startTabCountdown",
            "clearAllTabCountdowns",
        )
    )
    script = textwrap.dedent(
        f"""
        const intervals = [];
        const cleared = [];
        const elements = {{}};

        function makeElement(id) {{
          if (!elements[id]) {{
            elements[id] = {{
              id,
              attrs: {{}},
              textContent: '',
              title: '',
              setAttribute(name, value) {{ this.attrs[name] = value; }},
            }};
          }}
          return elements[id];
        }}

        const document = {{
          contains(node) {{
            return !!node && !!elements[node.id];
          }},
          getElementById(id) {{
            return makeElement(id);
          }},
        }};
        let tabCountdownTimers = {{}};
        let tabCountdownTickerTimer = null;
        let tabCountdownRemaining = {{}};
        let taskDeadlines = {{}};
        function getAdjustedNowSeconds() {{ return 0; }}
        function t(_key, params) {{ return String(params.seconds); }}
        function setInterval(fn, ms) {{
          intervals.push({{ fn, ms }});
          return intervals.length;
        }}
        function clearInterval(id) {{
          cleared.push(id);
        }}

        {parts}

        startTabCountdown('a', 10, 5);
        startTabCountdown('b', 10, 4);
        const intervalCountAfterStart = intervals.length;
        tabCountdownTimers.a.remaining = 0;
        tabCountdownTimers.b.remaining = 0;
        intervals[0].fn();

        process.stdout.write(JSON.stringify({{
          intervalCountAfterStart,
          intervalMs: intervals[0].ms,
          remainingKeys: Object.keys(tabCountdownRemaining),
          timerKeys: Object.keys(tabCountdownTimers),
          tickerTimer: tabCountdownTickerTimer,
          cleared,
        }}));
        """
    )

    completed = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(completed.stdout) == {
        "intervalCountAfterStart": 1,
        "intervalMs": 1000,
        "remainingKeys": [],
        "timerKeys": [],
        "tickerTimer": None,
        "cleared": [1],
    }
