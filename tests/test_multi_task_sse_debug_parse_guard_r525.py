"""R525 regression tests for debug-only SSE JSON parsing."""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
MULTI_TASK_JS = (
    REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "multi_task.js"
)


def _node_available() -> bool:
    return shutil.which("node") is not None


def _run_node(script: str) -> dict[str, Any]:
    proc = subprocess.run(
        ["node", "-e", script],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
        text=True,
        timeout=15,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"node exited {proc.returncode}\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}"
        )
    return json.loads(proc.stdout)


@unittest.skipUnless(_node_available(), "node runtime unavailable")
class TestMultiTaskSseDebugParseGuardR525(unittest.TestCase):
    def test_debug_disabled_skips_debug_only_sse_json_parse(self) -> None:
        script = textwrap.dedent(
            f"""
            const fs = require('fs');
            const vm = require('vm');
            const source = fs.readFileSync({json.dumps(str(MULTI_TASK_JS))}, 'utf8');
            const nativeParse = JSON.parse.bind(JSON);
            let parseCalls = 0;
            const handlers = {{}};
            const timers = [];
            const sandbox = {{
              Math,
              Date,
              Number,
              String,
              Promise,
              URLSearchParams,
              AIIA_DEBUG: false,
              console: {{
                debug() {{}},
                info() {{}},
                log() {{}},
                warn() {{}},
                error() {{}},
              }},
              JSON: {{
                parse(text) {{
                  parseCalls += 1;
                  return nativeParse(text);
                }},
                stringify: JSON.stringify.bind(JSON),
              }},
              setTimeout(fn, delay) {{
                timers.push({{ fn, delay }});
                return timers.length;
              }},
              clearTimeout() {{}},
              setInterval() {{ return 1; }},
              clearInterval() {{}},
              fetch: async () => ({{
                ok: true,
                json: async () => ({{ success: true, tasks: [], stats: {{}} }}),
              }}),
              _showToast() {{}},
            }};
            sandbox.window = sandbox;
            sandbox.navigator = {{}};
            sandbox.document = {{
              hidden: false,
              readyState: 'complete',
              addEventListener() {{}},
              getElementById() {{ return null; }},
              querySelector() {{ return null; }},
              querySelectorAll() {{ return []; }},
              body: {{ contains() {{ return true; }} }},
              documentElement: {{ setAttribute() {{}} }},
            }};
            sandbox.EventSource = function EventSource(url) {{
              this.url = url;
              this.addEventListener = (eventType, handler) => {{
                handlers[eventType] = handler;
              }};
              this.close = function () {{}};
            }};
            vm.createContext(sandbox);
            vm.runInContext(source, sandbox, {{ filename: 'multi_task.js' }});

            sandbox._connectDirectSSE(false);
            const payload = '{{"task_id":"t1","old_status":"pending","new_status":"active","ts_unix":1}}';
            handlers.task_changed({{ data: payload, lastEventId: '10' }});
            handlers.gap_warning({{ data: payload }});
            handlers.heartbeat({{ data: payload }});
            sandbox._consumeSharedSseEvent({{
              eventType: 'task_changed',
              data: payload,
              eventLastEventId: '11',
            }});
            sandbox._consumeSharedSseEvent({{
              eventType: 'gap_warning',
              data: payload,
            }});
            sandbox._consumeSharedSseEvent({{
              eventType: 'heartbeat',
              data: payload,
            }});
            const debugOnlyParseCalls = parseCalls;

            handlers.config_changed({{
              data: '{{"hint":"reload from config detail"}}',
            }});

            process.stdout.write(JSON.stringify({{
              debugOnlyParseCalls,
              totalParseCalls: parseCalls,
              scheduledDelays: timers.map((timer) => timer.delay),
            }}));
            """
        )

        result = _run_node(script)

        self.assertEqual(result["debugOnlyParseCalls"], 0)
        self.assertEqual(result["totalParseCalls"], 1)
        self.assertEqual(result["scheduledDelays"], [80, 0, 80, 0])

    def test_debug_enabled_preserves_sse_payload_diagnostics(self) -> None:
        script = textwrap.dedent(
            f"""
            const fs = require('fs');
            const vm = require('vm');
            const source = fs.readFileSync({json.dumps(str(MULTI_TASK_JS))}, 'utf8');
            const nativeParse = JSON.parse.bind(JSON);
            let parseCalls = 0;
            const debugMessages = [];
            const handlers = {{}};
            const sandbox = {{
              Math,
              Date,
              Number,
              String,
              Promise,
              URLSearchParams,
              AIIA_DEBUG: true,
              console: {{
                debug(...args) {{ debugMessages.push(String(args[0])); }},
                info() {{}},
                log() {{}},
                warn() {{}},
                error() {{}},
              }},
              JSON: {{
                parse(text) {{
                  parseCalls += 1;
                  return nativeParse(text);
                }},
                stringify: JSON.stringify.bind(JSON),
              }},
              setTimeout() {{ return 1; }},
              clearTimeout() {{}},
              setInterval() {{ return 1; }},
              clearInterval() {{}},
              fetch: async () => ({{
                ok: true,
                json: async () => ({{ success: true, tasks: [], stats: {{}} }}),
              }}),
              _showToast() {{}},
            }};
            sandbox.window = sandbox;
            sandbox.navigator = {{}};
            sandbox.document = {{
              hidden: false,
              readyState: 'complete',
              addEventListener() {{}},
              getElementById() {{ return null; }},
              querySelector() {{ return null; }},
              querySelectorAll() {{ return []; }},
              body: {{ contains() {{ return true; }} }},
              documentElement: {{ setAttribute() {{}} }},
            }};
            sandbox.EventSource = function EventSource(url) {{
              this.url = url;
              this.addEventListener = (eventType, handler) => {{
                handlers[eventType] = handler;
              }};
              this.close = function () {{}};
            }};
            vm.createContext(sandbox);
            vm.runInContext(source, sandbox, {{ filename: 'multi_task.js' }});

            sandbox._connectDirectSSE(false);
            const payload = '{{"task_id":"t1","old_status":"pending","new_status":"active","ts_unix":1}}';
            handlers.task_changed({{ data: payload, lastEventId: '10' }});
            handlers.gap_warning({{ data: payload }});
            handlers.heartbeat({{ data: payload }});
            sandbox._consumeSharedSseEvent({{
              eventType: 'task_changed',
              data: payload,
              eventLastEventId: '11',
            }});
            sandbox._consumeSharedSseEvent({{
              eventType: 'gap_warning',
              data: payload,
            }});
            sandbox._consumeSharedSseEvent({{
              eventType: 'heartbeat',
              data: payload,
            }});

            process.stdout.write(JSON.stringify({{
              parseCalls,
              debugMessages,
            }}));
            """
        )

        result = _run_node(script)

        self.assertEqual(result["parseCalls"], 6)
        self.assertEqual(
            result["debugMessages"],
            [
                "SSE task_changed:",
                "SSE gap_warning received, fetching tasks for full resync",
                "SSE gap_warning detail:",
                "SSE heartbeat:",
                "SSE task_changed:",
                "SSE gap_warning received, fetching tasks for full resync",
                "SSE gap_warning detail:",
                "SSE heartbeat:",
            ],
        )


if __name__ == "__main__":
    unittest.main()
