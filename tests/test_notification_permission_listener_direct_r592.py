"""R592 regression coverage for notification auto-permission listeners."""

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


def _extract_block(source: str, marker: str) -> str:
    start = source.find(marker)
    assert start != -1, f"Cannot find marker: {marker}"
    open_brace = source.find("{", start)
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
    raise AssertionError(f"Unbalanced block for: {marker}")


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


def test_permission_listener_helpers_use_direct_event_calls_without_foreach() -> None:
    source = _source()
    bind_body = _extract_block(source, "  addAutoPermissionRequestListeners()")
    remove_body = _extract_block(
        source, "  removeBoundAutoPermissionRequestListeners()"
    )

    assert ";['click', 'keydown', 'touchstart'].forEach" not in source
    assert ".forEach(" not in bind_body
    assert ".forEach(" not in remove_body
    assert (
        "const AUTO_PERMISSION_REQUEST_LISTENER_OPTIONS = {\n  once: true,\n  passive: true\n}"
        in source
    )
    assert (
        "document.addEventListener('click', handler, AUTO_PERMISSION_REQUEST_LISTENER_OPTIONS)"
        in bind_body
    )
    assert (
        "document.addEventListener('keydown', handler, AUTO_PERMISSION_REQUEST_LISTENER_OPTIONS)"
        in bind_body
    )
    assert (
        "document.addEventListener('touchstart', handler, AUTO_PERMISSION_REQUEST_LISTENER_OPTIONS)"
        in bind_body
    )
    assert "document.removeEventListener('click', handler)" in remove_body
    assert "document.removeEventListener('keydown', handler)" in remove_body
    assert "document.removeEventListener('touchstart', handler)" in remove_body


@pytest.mark.skipif(shutil.which("node") is None, reason="node runtime unavailable")
def test_auto_permission_bind_remove_preserves_events_without_array_foreach() -> None:
    script = textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync({str(NOTIFICATION_MANAGER_JS)!r}, 'utf8')
          + '\\nglobalThis.__notificationManager = notificationManager;';

        const added = [];
        const removed = [];
        const listeners = {{}};

        const sandbox = {{
          Audio: function Audio() {{}},
          Blob: function Blob(parts) {{
            this.size = String(parts && parts[0] ? parts[0] : '').length;
          }},
          CustomEvent: function CustomEvent(type, init) {{
            this.type = type;
            this.detail = init && init.detail;
          }},
          Date,
          Error,
          JSON,
          Map,
          Math,
          Notification: {{
            permission: 'default',
          }},
          Number,
          Object,
          Promise,
          RegExp,
          String,
          console: {{
            debug() {{}},
            error() {{}},
            info() {{}},
            log() {{}},
            warn() {{}},
          }},
          document: {{
            addEventListener(type, handler, options) {{
              added.push({{
                type,
                handlerName: handler && handler.name,
                once: options && options.once,
                passive: options && options.passive,
              }});
              listeners[type] = handler;
            }},
            removeEventListener(type, handler) {{
              removed.push({{
                type,
                sameHandler: listeners[type] === handler,
              }});
              if (listeners[type] === handler) {{
                delete listeners[type];
              }}
            }},
          }},
          dispatchEvent() {{}},
          isSecureContext: true,
          localStorage: {{
            getItem() {{ return null; }},
            setItem() {{}},
            removeItem() {{}},
          }},
          navigator: {{
            userActivation: {{ isActive: true }},
            userAgent: 'node',
          }},
          setInterval() {{ return 1; }},
          clearInterval() {{}},
          setTimeout(fn) {{ fn(); return 1; }},
          clearTimeout() {{}},
          __added: added,
          __removed: removed,
          __listeners: listeners,
        }};
        sandbox.window = sandbox;

        vm.createContext(sandbox);
        vm.runInContext(code, sandbox);
        vm.runInContext(
          "Array.prototype.forEach = function disabledForEach() " +
          "{{ throw new Error('Array.prototype.forEach must not be used'); }};",
          sandbox,
        );

        const manager = sandbox.__notificationManager;
        manager.bindAutoPermissionRequest();
        const afterBind = {{
          bound: manager.autoPermissionListenersBound,
          listenerKeys: Object.keys(sandbox.__listeners),
        }};
        manager.removeAutoPermissionRequestListeners();

        process.stdout.write(JSON.stringify({{
          added: sandbox.__added,
          removed: sandbox.__removed,
          afterBind,
          afterRemove: {{
            bound: manager.autoPermissionListenersBound,
            handler: manager.boundPermissionRequestHandler,
            listenerKeys: Object.keys(sandbox.__listeners),
          }},
        }}));
        """
    )

    result = json.loads(_run_node(script))

    assert result == {
        "added": [
            {
                "type": "click",
                "handlerName": "",
                "once": True,
                "passive": True,
            },
            {
                "type": "keydown",
                "handlerName": "",
                "once": True,
                "passive": True,
            },
            {
                "type": "touchstart",
                "handlerName": "",
                "once": True,
                "passive": True,
            },
        ],
        "removed": [
            {"type": "click", "sameHandler": True},
            {"type": "keydown", "sameHandler": True},
            {"type": "touchstart", "sameHandler": True},
        ],
        "afterBind": {
            "bound": True,
            "listenerKeys": ["click", "keydown", "touchstart"],
        },
        "afterRemove": {
            "bound": False,
            "handler": None,
            "listenerKeys": [],
        },
    }
