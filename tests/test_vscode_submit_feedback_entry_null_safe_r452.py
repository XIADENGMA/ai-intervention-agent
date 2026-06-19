"""R452: VS Code webview submitFeedback entry should tolerate stale DOM."""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WEBVIEW_UI_JS = REPO_ROOT / "packages" / "vscode" / "webview-ui.js"


def _node_available() -> bool:
    return shutil.which("node") is not None


def _extract_async_function(source: str, name: str) -> str:
    marker = f"async function {name}()"
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


def _submit_feedback_source() -> str:
    return _extract_async_function(
        WEBVIEW_UI_JS.read_text(encoding="utf-8"), "submitFeedback"
    )


def _run_node(script: str) -> str:
    if not _node_available():
        raise AssertionError("node runtime unavailable")
    completed = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def test_submit_feedback_entry_no_longer_chains_getelementbyid_value() -> None:
    source = _submit_feedback_source()

    assert "document.getElementById('feedbackText').value.trim()" not in source
    assert "const feedbackTextEl = document.getElementById('feedbackText')" in source
    assert "if (!feedbackTextEl)" in source
    assert "const feedbackText = feedbackTextEl.value.trim()" in source
    assert source.index("if (!feedbackTextEl)") < source.index(
        "feedbackTextEl.value.trim()"
    )


def test_submit_feedback_missing_textarea_skips_submit_without_throwing() -> None:
    source = _submit_feedback_source()
    script = textwrap.dedent(
        f"""
        const calls = [];
        const logs = [];
        const elements = {{}};
        const vscode = {{ postMessage(message) {{ logs.push(message); }} }};
        const document = {{
          getElementById(id) {{
            return Object.prototype.hasOwnProperty.call(elements, id) ? elements[id] : null;
          }},
        }};
        const currentConfig = {{ predefined_options: ['Keep'] }};
        async function submitWithData(text, selected) {{
          calls.push({{ text, selected }});
        }}

        {source}

        submitFeedback()
          .then(() => {{
            process.stdout.write(JSON.stringify({{ calls, logs }}));
          }})
          .catch((error) => {{
            console.error(error && error.stack ? error.stack : error);
            process.exit(1);
          }});
        """
    )

    result = json.loads(_run_node(script))

    assert result["calls"] == []
    assert result["logs"] == [
        {
            "type": "log",
            "level": "debug",
            "message": "[submit] feedbackText not in DOM; skip submit",
        }
    ]


def test_submit_feedback_present_textarea_keeps_trim_and_selected_options() -> None:
    source = _submit_feedback_source()
    script = textwrap.dedent(
        f"""
        const calls = [];
        const logs = [];
        const elements = {{
          feedbackText: {{ value: '  Ship it  ' }},
          'option-0': {{ checked: true }},
          'option-1': {{ checked: false }},
        }};
        const vscode = {{ postMessage(message) {{ logs.push(message); }} }};
        const document = {{
          getElementById(id) {{
            return Object.prototype.hasOwnProperty.call(elements, id) ? elements[id] : null;
          }},
        }};
        const currentConfig = {{ predefined_options: ['Keep', 'Skip'] }};
        async function submitWithData(text, selected) {{
          calls.push({{ text, selected }});
        }}

        {source}

        submitFeedback()
          .then(() => {{
            process.stdout.write(JSON.stringify({{ calls, logs }}));
          }})
          .catch((error) => {{
            console.error(error && error.stack ? error.stack : error);
            process.exit(1);
          }});
        """
    )

    result = json.loads(_run_node(script))

    assert result == {
        "calls": [{"text": "Ship it", "selected": ["Keep"]}],
        "logs": [],
    }
