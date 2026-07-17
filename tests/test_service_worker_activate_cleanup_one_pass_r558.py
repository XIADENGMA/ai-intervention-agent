"""R558 regression coverage for one-pass service worker cache cleanup."""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SW_JS = (
    REPO_ROOT
    / "src"
    / "ai_intervention_agent"
    / "static"
    / "js"
    / "notification-service-worker.js"
)


def _source() -> str:
    return SW_JS.read_text(encoding="utf-8")


def _extract_listener_body(source: str, event_name: str) -> str:
    marker = f"self.addEventListener('{event_name}'"
    start = source.find(marker)
    assert start != -1, f"Cannot find listener marker: {marker}"
    open_brace = source.find("{", start)
    assert open_brace != -1, f"Cannot find listener opening brace: {marker}"
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
    raise AssertionError(f"Unbalanced listener body for: {marker}")


def _run_node(case_js: str) -> str:
    script = textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync({str(SW_JS)!r}, 'utf8');
        const listeners = {{}};
        const deletedCaches = [];
        const waitUntilPromises = [];
        let claimCalls = 0;

        const sandbox = {{
          Array,
          Boolean,
          Date,
          JSON,
          Map,
          Math,
          Number,
          Object,
          Promise,
          Set,
          String,
          URL,
          Response: function Response() {{}},
          caches: {{
            async open() {{
              return {{
                async match() {{ return null; }},
                async put() {{}},
                async keys() {{ return []; }},
                async delete() {{ return false; }},
              }};
            }},
            async keys() {{
              return [
                'aiia-static-v1',
                'aiia-static-v2',
                'aiia-offline-v0',
                'aiia-offline-v1',
                'foreign-cache',
                42,
              ];
            }},
            async delete(name) {{
              deletedCaches.push(name);
              return true;
            }},
          }},
          clients: {{
            async claim() {{
              claimCalls += 1;
            }},
            async matchAll() {{ return []; }},
            async openWindow() {{}},
          }},
          console: {{
            debug() {{}},
            error() {{}},
            info() {{}},
            log() {{}},
            warn() {{}},
          }},
          fetch: async () => {{
            throw new Error('fetch stub not configured');
          }},
          location: {{ origin: 'http://aiia.test' }},
          skipWaiting: async () => undefined,
          addEventListener(type, handler) {{
            if (!listeners[type]) listeners[type] = [];
            listeners[type].push(handler);
          }},
          __deletedCaches: deletedCaches,
          __claimCalls: () => claimCalls,
          __listeners: listeners,
          __waitUntilPromises: waitUntilPromises,
        }};
        sandbox.self = sandbox;

        vm.createContext(sandbox);
        vm.runInContext(code, sandbox);

        (async () => {{
        {textwrap.indent(case_js, "  ")}
        }})().catch((err) => {{
          console.error(err && err.stack ? err.stack : err);
          process.exit(1);
        }});
        """
    )
    proc = subprocess.run(
        ["node", "-e", script],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"node exited {proc.returncode}\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}"
        )
    return proc.stdout


def test_activate_cleanup_uses_single_pass_delete_promise_collector() -> None:
    body = _extract_listener_body(_source(), "activate")

    assert ".filter(" not in body
    assert ".map(name => caches.delete" not in body
    assert "const deletions = []" in body
    assert "for (const name of cacheNames)" in body
    assert "deletions.push(caches.delete(name).catch(() => false))" in body
    assert "await Promise.all(deletions)" in body
    assert "name !== STATIC_CACHE_NAME" in body
    assert "name !== OFFLINE_CACHE_NAME" in body


@pytest.mark.skipif(shutil.which("node") is None, reason="node runtime unavailable")
def test_activate_cleanup_deletes_only_old_aiia_cache_versions() -> None:
    script = """
        const activateHandlers = sandbox.__listeners.activate || [];
        if (activateHandlers.length !== 1) {
          throw new Error('expected one activate handler, got ' + activateHandlers.length);
        }
        activateHandlers[0]({
          waitUntil(promise) {
            sandbox.__waitUntilPromises.push(Promise.resolve(promise));
          },
        });
        await Promise.all(sandbox.__waitUntilPromises);
        process.stdout.write(JSON.stringify({
          deletedCaches: sandbox.__deletedCaches,
          claimCalls: sandbox.__claimCalls(),
        }));
    """

    assert json.loads(_run_node(script)) == {
        "deletedCaches": ["aiia-static-v1", "aiia-offline-v0"],
        "claimCalls": 1,
    }
