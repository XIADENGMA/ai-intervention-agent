"""R552 regression coverage for bounded fallback-event retention."""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
NOTIFICATION_MANAGER_JS = (
    REPO_ROOT
    / "src"
    / "ai_intervention_agent"
    / "static"
    / "js"
    / "notification-manager.js"
)


def _source() -> str:
    return NOTIFICATION_MANAGER_JS.read_text(encoding="utf-8")


def _extract_function(source: str, marker: str) -> str:
    start = source.find(marker)
    assert start != -1, f"Cannot find function marker: {marker}"
    if marker.endswith("{"):
        open_brace = start + len(marker) - 1
    else:
        open_brace = source.find("{", start + len(marker))
    assert open_brace != -1, f"Cannot find opening brace for: {marker}"
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


def _notification_harness(case_js: str) -> str:
    return textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync({str(NOTIFICATION_MANAGER_JS)!r}, 'utf8')
          + '\\nglobalThis.__notificationManager = notificationManager;';

        const storage = new Map();
        const removedKeys = [];
        const NOW = 1700000000000;

        const sandbox = {{
          Audio: function Audio() {{}},
          Blob: function Blob(parts) {{
            this.size = String(parts && parts[0] ? parts[0] : '').length;
          }},
          CustomEvent: function CustomEvent(type, init) {{
            this.type = type;
            this.detail = init && init.detail;
          }},
          Date: {{ now: () => NOW }},
          Error,
          JSON,
          Map,
          Math,
          Notification: {{ permission: 'denied' }},
          Number,
          Object,
          Promise,
          RegExp,
          String,
          TypeError,
          console: {{
            debug() {{}},
            error() {{}},
            info() {{}},
            log() {{}},
            warn() {{}},
          }},
          document: {{
            title: 'AI Intervention Agent',
          }},
          localStorage: {{
            getItem(key) {{
              return storage.has(key) ? storage.get(key) : null;
            }},
            setItem(key, value) {{
              storage.set(key, String(value));
            }},
            removeItem(key) {{
              removedKeys.push(key);
              storage.delete(key);
            }},
          }},
          navigator: {{ userAgent: 'node' }},
          location: {{ href: 'https://example.test/ui' }},
          setInterval() {{ return 1; }},
          clearInterval() {{}},
          setTimeout(fn) {{ fn(); return 1; }},
          clearTimeout() {{}},
          dispatchEvent() {{}},
          isSecureContext: true,
          __now: NOW,
          __removedKeys: removedKeys,
          __storage: storage,
        }};
        sandbox.window = sandbox;

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


def _run_node(script: str) -> str:
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


def test_fallback_event_retention_uses_bounded_collector() -> None:
    source = _source()
    helper = _extract_function(source, "_collectRecentFallbackEvents(events,")
    record = _extract_function(source, "recordFallbackEvent(type, data) {")
    cleanup = _extract_function(source, "cleanupLocalStorage() {")

    assert "events.filter(e => e.timestamp" not in record
    assert "events.filter(e => e.timestamp" not in cleanup
    assert ".splice(0," not in record
    assert ".splice(0," not in cleanup
    assert "for (let i = events.length - 1; i >= 0; i -= 1)" in helper
    assert "kept.length < maxEvents" in helper
    assert "kept.reverse()" in helper
    assert "_collectRecentFallbackEvents(events, sevenDaysAgo, 49)" in record
    assert "_collectRecentFallbackEvents(events, oneDayAgo, 20)" in cleanup


@pytest.mark.skipif(shutil.which("node") is None, reason="node runtime unavailable")
def test_record_fallback_event_keeps_last_49_existing_plus_new_event() -> None:
    script = _notification_harness(
        """
        const manager = sandbox.__notificationManager;
        const key = 'ai-intervention-fallback-events';
        const events = [];
        events.push({ id: 'expired', timestamp: sandbox.__now - 8 * 24 * 60 * 60 * 1000 });
        for (let i = 0; i < 55; i += 1) {
          events.push({ id: `e${i}`, timestamp: sandbox.__now - 1000 });
        }
        sandbox.__storage.set(key, JSON.stringify(events));

        manager.recordFallbackEvent('audio', { reason: 'test' });
        const stored = JSON.parse(sandbox.__storage.get(key));

        process.stdout.write(JSON.stringify({
          length: stored.length,
          first: stored[0].id,
          beforeNew: stored[48].id,
          lastType: stored[49].type,
          lastReason: stored[49].data.reason,
          lastUserAgent: stored[49].userAgent,
          lastUrl: stored[49].url,
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "length": 50,
        "first": "e6",
        "beforeNew": "e54",
        "lastType": "audio",
        "lastReason": "test",
        "lastUserAgent": "node",
        "lastUrl": "https://example.test/ui",
    }


@pytest.mark.skipif(shutil.which("node") is None, reason="node runtime unavailable")
def test_cleanup_local_storage_keeps_last_20_recent_events() -> None:
    script = _notification_harness(
        """
        const manager = sandbox.__notificationManager;
        const key = 'ai-intervention-fallback-events';
        const events = [];
        for (let i = 0; i < 3; i += 1) {
          events.push({ id: `old${i}`, timestamp: sandbox.__now - 2 * 24 * 60 * 60 * 1000 });
        }
        for (let i = 0; i < 25; i += 1) {
          events.push({ id: `recent${i}`, timestamp: sandbox.__now - 1000 });
        }
        sandbox.__storage.set(key, JSON.stringify(events));

        manager.cleanupLocalStorage();
        const stored = JSON.parse(sandbox.__storage.get(key));

        process.stdout.write(JSON.stringify({
          length: stored.length,
          first: stored[0].id,
          last: stored[19].id,
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "length": 20,
        "first": "recent5",
        "last": "recent24",
    }


@pytest.mark.skipif(shutil.which("node") is None, reason="node runtime unavailable")
def test_malformed_fallback_event_entry_still_clears_storage() -> None:
    script = _notification_harness(
        """
        const manager = sandbox.__notificationManager;
        const key = 'ai-intervention-fallback-events';
        sandbox.__storage.set(key, JSON.stringify([
          null,
          { id: 'valid', timestamp: sandbox.__now - 1000 },
        ]));

        manager.recordFallbackEvent('audio', { reason: 'test' });

        process.stdout.write(JSON.stringify({
          hasKey: sandbox.__storage.has(key),
          removedKeys: sandbox.__removedKeys,
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "hasKey": False,
        "removedKeys": ["ai-intervention-fallback-events"],
    }
