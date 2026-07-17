"""R500: VS Code tab countdowns skip DOM writes while the webview is hidden."""

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


def test_tick_computes_remaining_before_hidden_dom_guard() -> None:
    source = _read_source()
    tick_body = _extract_function(source, "tickTabCountdown")

    compute_idx = tick_body.find("computeTabCountdownRemaining(taskId, state)")
    guard_idx = tick_body.find("if (documentHidden) return")
    render_idx = tick_body.find("renderTabCountdown(taskId, state, computedRemaining)")

    assert compute_idx > -1
    assert guard_idx > -1
    assert render_idx > -1
    assert compute_idx < guard_idx < render_idx
    assert "tabCountdownRemaining[taskId] = computedRemaining" in tick_body


def test_visibility_force_update_helper_is_idempotently_installed() -> None:
    source = _read_source()
    install_body = _extract_function(
        source, "installTabCountdownVisibilitySyncHandlerOnce"
    )
    force_body = _extract_function(source, "forceUpdateAllTabCountdowns")
    ensure_body = _extract_function(source, "ensureSharedTabCountdownTicker")

    assert "let tabCountdownVisibilityHandlerInstalled = false" in source
    assert "tabCountdownVisibilityHandlerInstalled" in install_body
    assert "document.addEventListener('visibilitychange'" in install_body
    assert "forceUpdateAllTabCountdowns()" in install_body
    assert "document.hidden) return" in force_body
    assert "for (const taskId in tabCountdownTimers)" in force_body
    assert (
        "Object.prototype.hasOwnProperty.call(tabCountdownTimers, taskId)" in force_body
    )
    assert "Object.keys(tabCountdownTimers)" not in force_body
    assert "installTabCountdownVisibilitySyncHandlerOnce()" in ensure_body


def test_runtime_hidden_tick_updates_state_without_dom_write_then_visible_force_renders() -> (
    None
):
    if not _node_available():
        raise AssertionError("node runtime unavailable")

    source = _read_source()
    parts = "\n\n".join(
        _extract_function(source, name)
        for name in (
            "hasTabCountdownTimers",
            "stopSharedTabCountdownTickerIfIdle",
            "forceUpdateAllTabCountdowns",
            "_getOrCacheTabCountdownDom",
            "computeTabCountdownRemaining",
            "renderTabCountdown",
            "tickTabCountdown",
        )
    )
    script = textwrap.dedent(
        f"""
        const elements = {{}};
        let lookupCount = 0;
        let writeCount = 0;

        function makeElement(id) {{
          if (!elements[id]) {{
            elements[id] = {{
              id,
              attrs: {{}},
              textContent: '',
              title: '',
              setAttribute(name, value) {{
                writeCount += 1;
                this.attrs[name] = value;
              }},
            }};
          }}
          return elements[id];
        }}

        const document = {{
          hidden: true,
          contains(node) {{
            return !!node && !!elements[node.id];
          }},
          getElementById(id) {{
            lookupCount += 1;
            return makeElement(id);
          }},
        }};
        let tabCountdownTimers = {{
          a: {{
            totalSeconds: 10,
            remaining: 5,
            circumference: 100,
          }},
        }};
        let tabCountdownTickerTimer = 1;
        let tabCountdownRemaining = {{}};
        let taskDeadlines = {{}};
        function getAdjustedNowSeconds() {{ return 0; }}
        function t(_key, params) {{ return String(params.seconds); }}
        function clearInterval() {{}}

        {parts}

        tickTabCountdown('a');
        const afterHiddenTick = {{
          lookupCount,
          writeCount,
          remaining: tabCountdownRemaining.a,
          stateRemaining: tabCountdownTimers.a.remaining,
        }};

        document.hidden = false;
        forceUpdateAllTabCountdowns();

        process.stdout.write(JSON.stringify({{
          afterHiddenTick,
          afterVisibleForce: {{
            lookupCount,
            writeCount,
            remaining: tabCountdownRemaining.a,
            stateRemaining: tabCountdownTimers.a.remaining,
            textContent: elements['tab-countdown-text-a'].textContent,
          }},
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
        "afterHiddenTick": {
            "lookupCount": 0,
            "writeCount": 0,
            "remaining": 5,
            "stateRemaining": 4,
        },
        "afterVisibleForce": {
            "lookupCount": 3,
            "writeCount": 1,
            "remaining": 4,
            "stateRemaining": 4,
            "textContent": 4,
        },
    }
