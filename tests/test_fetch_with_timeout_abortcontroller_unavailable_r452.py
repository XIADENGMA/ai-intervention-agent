"""R452: fetchWithTimeout must degrade when AbortController is unavailable."""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_JS = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "app.js"


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


def _run_node(script: str) -> dict[str, object]:
    if not _node_available():
        raise AssertionError("node runtime unavailable")
    completed = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def test_fetch_with_timeout_preserves_fetch_when_abortcontroller_is_missing() -> None:
    source = _extract_function(APP_JS.read_text(encoding="utf-8"), "fetchWithTimeout")
    script = textwrap.dedent(
        f"""
        const AbortSignal = undefined;
        const AbortController = undefined;
        const originalOptions = {{
          method: 'POST',
          signal: {{ aborted: false }},
          headers: {{ Accept: 'application/json' }},
        }};
        const fetchCalls = [];

        function setTimeout() {{
          throw new Error('timeout fallback should not be scheduled without AbortController');
        }}
        function fetch(url, options) {{
          fetchCalls.push({{
            url,
            sameOptions: options === originalOptions,
            method: options && options.method,
            signalPreserved: options && options.signal === originalOptions.signal,
          }});
          return Promise.resolve({{ ok: true, status: 200 }});
        }}

        {source}

        fetchWithTimeout('/api/config', originalOptions, 1000)
          .then((response) => {{
            process.stdout.write(JSON.stringify({{
              responseOk: response.ok,
              responseStatus: response.status,
              fetchCalls,
            }}));
          }})
          .catch((error) => {{
            console.error(error && error.stack ? error.stack : String(error));
            process.exit(1);
          }});
        """
    )

    assert _run_node(script) == {
        "responseOk": True,
        "responseStatus": 200,
        "fetchCalls": [
            {
                "url": "/api/config",
                "sameOptions": True,
                "method": "POST",
                "signalPreserved": True,
            }
        ],
    }
