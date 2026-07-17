"""R559 regression coverage for one-pass service worker cache trimming."""

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


def _extract_function_body(source: str, function_name: str) -> str:
    marker = f"async function {function_name}"
    start = source.find(marker)
    assert start != -1, f"Cannot find function marker: {marker}"
    open_brace = source.find("{", start)
    assert open_brace != -1, f"Cannot find function opening brace: {marker}"
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


def _run_node(case_js: str) -> str:
    script = textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync({str(SW_JS)!r}, 'utf8');
        const listeners = {{}};

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
            async keys() {{ return []; }},
            async delete() {{ return false; }},
          }},
          clients: {{
            async claim() {{}},
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
          __listeners: listeners,
        }};
        sandbox.self = sandbox;

        vm.createContext(sandbox);
        vm.runInContext(
          code + '\\nself.__trimCache = trimCache; self.__MAX_ENTRIES = MAX_ENTRIES;',
          sandbox
        );

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


def test_trim_cache_uses_one_pass_delete_promise_collector() -> None:
    body = _extract_function_body(_source(), "trimCache")

    assert "keys.slice(0, keys.length - MAX_ENTRIES)" not in body
    assert ".map(req => cache.delete" not in body
    assert "const deletions = []" in body
    assert "const overflowCount = keys.length - MAX_ENTRIES" in body
    assert "for (let i = 0; i < overflowCount; i += 1)" in body
    assert "deletions.push(cache.delete(keys[i]).catch(() => false))" in body
    assert "await Promise.all(deletions)" in body


@pytest.mark.skipif(shutil.which("node") is None, reason="node runtime unavailable")
def test_trim_cache_deletes_only_oldest_overflow_entries_fifo() -> None:
    script = """
        const maxEntries = sandbox.__MAX_ENTRIES;
        const keys = Array.from({ length: maxEntries + 3 }, (_, i) => ({
          url: 'http://aiia.test/static/js/asset-' + i + '.js',
        }));
        const deleted = [];
        const cache = {
          async keys() {
            return keys;
          },
          async delete(request) {
            deleted.push(request.url);
            if (request.url.endsWith('asset-1.js')) {
              throw new Error('delete failed');
            }
            return true;
          },
        };

        await sandbox.__trimCache(cache);
        process.stdout.write(JSON.stringify({
          deleted,
          retainedFirstUrl: keys[3].url,
          retainedCount: maxEntries,
        }));
    """

    assert json.loads(_run_node(script)) == {
        "deleted": [
            "http://aiia.test/static/js/asset-0.js",
            "http://aiia.test/static/js/asset-1.js",
            "http://aiia.test/static/js/asset-2.js",
        ],
        "retainedFirstUrl": "http://aiia.test/static/js/asset-3.js",
        "retainedCount": 200,
    }


@pytest.mark.skipif(shutil.which("node") is None, reason="node runtime unavailable")
def test_trim_cache_noops_when_cache_is_at_or_below_limit() -> None:
    script = """
        const maxEntries = sandbox.__MAX_ENTRIES;
        const keys = Array.from({ length: maxEntries }, (_, i) => ({
          url: 'http://aiia.test/static/js/asset-' + i + '.js',
        }));
        let deleteCalls = 0;
        const cache = {
          async keys() {
            return keys;
          },
          async delete() {
            deleteCalls += 1;
            return true;
          },
        };

        await sandbox.__trimCache(cache);
        process.stdout.write(JSON.stringify({ deleteCalls }));
    """

    assert json.loads(_run_node(script)) == {"deleteCalls": 0}
