"""R750: the VS Code webview must not report its initial "disconnected" paint.

``init()`` paints the status light as disconnected before the first probe has
run. ``updateServerStatus`` also posted that value to the extension host, which
treats every ``serverStatus`` message as a transition: once it had seen the
server connected, each rebuilt page (hiding and showing the panel, a changed
``serverUrl``) logged ``event=webview.server_status connected=false`` at WARN,
followed by an INFO "connected" a few milliseconds later, although the server
never went away. The initial paint now stays in the page; real probe results
are still reported.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import textwrap
from collections.abc import Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WEBVIEW_UI_JS = REPO_ROOT / "packages" / "vscode" / "webview-ui.js"


def read_source() -> str:
    return WEBVIEW_UI_JS.read_text(encoding="utf-8")


def extract_function(source: str, name: str) -> str:
    start = source.index(f"function {name}(")
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


def run_node(script: str) -> str:
    assert shutil.which("node") is not None, "node runtime unavailable"
    completed = subprocess.run(
        ["node", "-e", script], check=True, capture_output=True, text=True
    )
    return completed.stdout


def status_calls(update_calls: Sequence[tuple[str, ...]]) -> str:
    steps = "\n".join(
        f"        updateServerStatus({', '.join(args)});\n"
        "        snapshots.push({ posted: posted.length, light: light.cls });"
        for args in update_calls
    )
    function = extract_function(read_source(), "updateServerStatus")
    return textwrap.dedent(
        f"""
        const posted = [];
        const toasts = [];
        const snapshots = [];
        const light = {{
          cls: '',
          title: '',
          classList: {{
            remove(...names) {{ light.cls = light.cls.split(' ').filter(n => n && !names.includes(n)).join(' '); }},
            add(name) {{ light.cls = (light.cls + ' ' + name).trim(); }},
          }},
        }};
        const document = {{ getElementById: id => (id === 'statusLight' ? light : null) }};
        const vscode = {{ postMessage: message => posted.push(message) }};
        const t = key => key;
        function showToast(text, options) {{ toasts.push({{ text, kind: options.kind }}); }}

        {function}

{steps}
        process.stdout.write(JSON.stringify({{ posted, toasts, snapshots }}));
        """
    )


def test_the_initial_paint_stays_in_the_page() -> None:
    result = json.loads(
        run_node(status_calls([("false", "{ report: false }"), ("true",)]))
    )

    assert result["snapshots"][0] == {"posted": 0, "light": "disconnected"}
    assert result["posted"] == [{"type": "serverStatus", "connected": True}]
    assert result["snapshots"][1] == {"posted": 1, "light": "connected"}


def test_the_paint_still_counts_as_the_previous_state_for_the_toast() -> None:
    result = json.loads(
        run_node(status_calls([("false", "{ report: false }"), ("true",)]))
    )

    assert result["toasts"] == [{"text": "ui.status.connected", "kind": "success"}]


def test_probe_results_are_reported_to_the_host() -> None:
    calls = [("true",), ("false",), ("true", "{}"), ("false", "undefined")]
    result = json.loads(run_node(status_calls(calls)))

    assert result["posted"] == [
        {"type": "serverStatus", "connected": True},
        {"type": "serverStatus", "connected": False},
        {"type": "serverStatus", "connected": True},
        {"type": "serverStatus", "connected": False},
    ]


def test_init_is_the_only_caller_that_keeps_its_paint_to_itself() -> None:
    source = read_source()
    init_body = extract_function(source, "init")

    assert re.findall(r"updateServerStatus\(([^)]*)\)", init_body) == [
        "false, { report: false }"
    ]

    arguments = re.findall(r"(?<!function )updateServerStatus\(([^)]*)\)", source)
    assert [a for a in arguments if "report" in a] == ["false, { report: false }"], (
        "only init() may call updateServerStatus without reporting"
    )
