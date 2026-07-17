"""R594 regression coverage for MathJax pending element flushing."""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
MATHJAX_LOADER_JS = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "mathjax-loader.js"
)


def _source() -> str:
    return MATHJAX_LOADER_JS.read_text(encoding="utf-8")


def _extract_ready_body(source: str) -> str:
    marker = "ready: () => {"
    start = source.find(marker)
    assert start != -1, "Cannot find MathJax startup.ready callback"
    open_brace = source.find("{", start)
    assert open_brace != -1, "Cannot find startup.ready opening brace"
    depth = 1
    i = open_brace + 1
    while i < len(source):
        char = source[i]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[open_brace + 1 : i]
        i += 1
    raise AssertionError("Unbalanced startup.ready callback")


def _run_node(script: str) -> str:
    proc = subprocess.run(
        ["node", "-e", script],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"node exited {proc.returncode}\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}"
        )
    return proc.stdout


def test_startup_ready_flushes_pending_elements_without_array_foreach() -> None:
    source = _source()
    ready_body = _extract_ready_body(source)

    assert "window._mathJaxPendingElements.forEach" not in ready_body
    assert ".forEach(" not in ready_body
    assert "const pendingElements = window._mathJaxPendingElements" in ready_body
    assert "const pendingElementCount = pendingElements.length" in ready_body
    assert "for (let index = 0; index < pendingElementCount; index += 1)" in ready_body
    assert "if (!(index in pendingElements)) continue" in ready_body
    assert "const el = pendingElements[index]" in ready_body
    assert "window._mathJaxPendingElements = []" in ready_body


@pytest.mark.skipif(shutil.which("node") is None, reason="node runtime unavailable")
def test_startup_ready_preserves_sparse_snapshot_order_and_error_catch() -> None:
    script = textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync({str(MATHJAX_LOADER_JS)!r}, 'utf8');

        const defaultReadyCalls = [];
        const typesetCalls = [];
        const warnings = [];
        const delta = {{ id: 'delta' }};

        const sandbox = {{
          Array,
          Error,
          JSON,
          Object,
          Promise,
          RegExp,
          String,
          console: {{
            debug() {{}},
            error() {{}},
            info() {{}},
            log() {{}},
            warn(message, error) {{
              warnings.push({{
                message,
                errorMessage: error && error.message ? error.message : String(error),
              }});
            }},
          }},
          document: {{
            createElement(tagName) {{
              return {{ tagName: String(tagName).toUpperCase() }};
            }},
            head: {{
              appendChild() {{}},
            }},
          }},
          window: null,
          __defaultReadyCalls: defaultReadyCalls,
          __typesetCalls: typesetCalls,
          __warnings: warnings,
        }};
        sandbox.window = sandbox;
        sandbox.globalThis = sandbox;

        vm.createContext(sandbox);
        vm.runInContext(code, sandbox);
        vm.runInContext(
          "Array.prototype.forEach = function disabledForEach() " +
          "{{ throw new Error('Array.prototype.forEach must not be used'); }};",
          sandbox,
        );

        sandbox.MathJax.startup.defaultReady = () => {{
          defaultReadyCalls.push('defaultReady');
        }};
        sandbox.MathJax.typesetPromise = (elements) => {{
          const element = elements[0];
          typesetCalls.push(element ? element.id : null);
          if (element && element.id === 'alpha') {{
            sandbox._mathJaxPendingElements.push(delta);
          }}
          if (element && element.id === 'beta') {{
            return Promise.reject(new Error('beta failed'));
          }}
          return Promise.resolve();
        }};

        const pending = [{{ id: 'alpha' }}, {{ id: 'hole' }}, {{ id: 'beta' }}, {{ id: 'gamma' }}];
        delete pending[1];
        sandbox._mathJaxPendingElements = pending;

        sandbox.MathJax.startup.ready();

        Promise.resolve().then(() => Promise.resolve()).then(() => {{
          process.stdout.write(JSON.stringify({{
            defaultReadyCalls,
            typesetCalls,
            warnings,
            pendingIsFreshArray: sandbox._mathJaxPendingElements !== pending,
            pendingLength: sandbox._mathJaxPendingElements.length,
          }}));
        }}).catch((error) => {{
          console.error(error && error.stack ? error.stack : String(error));
          process.exit(1);
        }});
        """
    )

    result = json.loads(_run_node(script))

    assert result == {
        "defaultReadyCalls": ["defaultReady"],
        "typesetCalls": ["alpha", "beta", "gamma"],
        "warnings": [
            {
                "message": "MathJax render failed:",
                "errorMessage": "beta failed",
            }
        ],
        "pendingIsFreshArray": True,
        "pendingLength": 0,
    }
