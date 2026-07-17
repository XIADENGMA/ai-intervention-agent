"""R499: VS Code task-tab countdowns cache hot-path DOM references."""

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


def test_helper_caches_tab_countdown_dom_refs() -> None:
    source = _read_source()
    helper_body = _extract_function(source, "_getOrCacheTabCountdownDom")

    assert "state._domCache" in helper_body
    assert "document.contains(cache.progressCircle)" in helper_body
    assert "progressCircle:" in helper_body
    assert "numberSpan:" in helper_body
    assert "countdownRing:" in helper_body


def test_hot_paths_use_tab_countdown_dom_cache() -> None:
    source = _read_source()
    tick_body = _extract_function(source, "tickTabCountdown")
    start_body = _extract_function(source, "startTabCountdown")
    render_body = _extract_function(source, "renderTabCountdown")

    assert "renderTabCountdown(taskId, state, computedRemaining)" in tick_body
    assert "_getOrCacheTabCountdownDom(taskId, state)" in start_body
    assert "_getOrCacheTabCountdownDom(taskId, state)" in render_body
    assert "document.getElementById(" not in tick_body
    assert "document.getElementById(" not in start_body
    assert "document.getElementById(" not in render_body


def test_runtime_reuses_cached_dom_refs_until_stale() -> None:
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
        )
    )
    script = textwrap.dedent(
        f"""
        const intervals = [];
        const elements = {{}};
        let lookupCount = 0;
        let forceStale = false;

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
            return !!node && !forceStale && !!elements[node.id];
          }},
          getElementById(id) {{
            lookupCount += 1;
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
        function clearInterval() {{}}

        {parts}

        startTabCountdown('a', 10, 5);
        const lookupsAfterStart = lookupCount;
        intervals[0].fn();
        const lookupsAfterWarmTick = lookupCount;
        forceStale = true;
        intervals[0].fn();
        const lookupsAfterStaleTick = lookupCount;

        process.stdout.write(JSON.stringify({{
          intervalCount: intervals.length,
          lookupsAfterStart,
          lookupsAfterWarmTick,
          lookupsAfterStaleTick,
          cachedKeys: Object.keys(tabCountdownTimers.a._domCache).sort(),
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
        "intervalCount": 1,
        "lookupsAfterStart": 3,
        "lookupsAfterWarmTick": 3,
        "lookupsAfterStaleTick": 6,
        "cachedKeys": ["countdownRing", "numberSpan", "progressCircle"],
    }
