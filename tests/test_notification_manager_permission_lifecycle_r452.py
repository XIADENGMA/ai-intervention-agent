"""Runtime checks for notification permission auto-request listener lifecycle."""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
NOTIFICATION_MANAGER_JS = (
    REPO_ROOT
    / "src"
    / "ai_intervention_agent"
    / "static"
    / "js"
    / "notification-manager.js"
)


def _node_available() -> bool:
    return shutil.which("node") is not None


def _run_node(script: str) -> str:
    proc = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        check=False,
        text=True,
        timeout=15,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"node exited {proc.returncode}\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}"
        )
    return proc.stdout


def _notification_permission_harness(case_js: str) -> str:
    return textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync({str(NOTIFICATION_MANAGER_JS)!r}, 'utf8')
          + '\\nglobalThis.__notificationManager = notificationManager;';

        const documentListeners = {{}};
        const removedDocumentListeners = [];
        const windowEvents = [];
        const permissionResponses = [];
        let requestCalls = 0;

        function addListener(bucket, type, handler, options) {{
          if (!bucket[type]) bucket[type] = [];
          bucket[type].push({{ handler, options: options || {{}} }});
        }}

        function removeListener(bucket, type, handler) {{
          removedDocumentListeners.push(type);
          if (!bucket[type]) return;
          bucket[type] = bucket[type].filter((entry) => entry.handler !== handler);
        }}

        async function flushMicrotasks() {{
          for (let i = 0; i < 8; i += 1) {{
            await Promise.resolve();
          }}
        }}

        async function dispatchDocumentEvent(type) {{
          const entries = [...(documentListeners[type] || [])];
          for (const entry of entries) {{
            if (entry.options && entry.options.once) {{
              removeListener(documentListeners, type, entry.handler);
            }}
            entry.handler({{ type }});
          }}
          await flushMicrotasks();
        }}

        function listenerCounts() {{
          return {{
            click: (documentListeners.click || []).length,
            keydown: (documentListeners.keydown || []).length,
            touchstart: (documentListeners.touchstart || []).length,
          }};
        }}

        const notificationApi = {{
          permission: 'default',
          requestPermission() {{
            requestCalls += 1;
            const permission = permissionResponses.shift() || 'default';
            notificationApi.permission = permission;
            return Promise.resolve(permission);
          }},
        }};

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
          Notification: notificationApi,
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
            title: 'AI Intervention Agent',
            addEventListener(type, handler, options) {{
              addListener(documentListeners, type, handler, options);
            }},
            removeEventListener(type, handler) {{
              removeListener(documentListeners, type, handler);
            }},
          }},
          localStorage: {{
            getItem() {{
              return null;
            }},
            setItem() {{}},
            removeItem() {{}},
          }},
          navigator: {{
            userActivation: {{ isActive: true }},
            userAgent: 'node',
          }},
          setInterval() {{
            return 1;
          }},
          clearInterval() {{}},
          setTimeout(fn) {{
            fn();
            return 1;
          }},
          clearTimeout() {{}},
          dispatchEvent(event) {{
            windowEvents.push({{ type: event.type, detail: event.detail }});
          }},
          isSecureContext: true,
          __dispatchDocumentEvent: dispatchDocumentEvent,
          __documentListenerCounts: listenerCounts,
          __permissionResponses: permissionResponses,
          __removedDocumentListeners: removedDocumentListeners,
          __requestCalls() {{
            return requestCalls;
          }},
          __windowEvents: windowEvents,
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


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_auto_permission_rearms_once_listeners_after_default_response() -> None:
    script = _notification_permission_harness(
        """
        const manager = sandbox.__notificationManager;
        manager.bindAutoPermissionRequest();
        const before = sandbox.__documentListenerCounts();

        sandbox.__permissionResponses.push('default');
        await sandbox.__dispatchDocumentEvent('click');

        process.stdout.write(
          JSON.stringify({
            before,
            after: sandbox.__documentListenerCounts(),
            bound: manager.autoPermissionListenersBound,
            permission: manager.permission,
            requestCalls: sandbox.__requestCalls(),
          })
        );
        """
    )

    assert json.loads(_run_node(script)) == {
        "before": {"click": 1, "keydown": 1, "touchstart": 1},
        "after": {"click": 1, "keydown": 1, "touchstart": 1},
        "bound": True,
        "permission": "default",
        "requestCalls": 1,
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_auto_permission_removes_once_listeners_after_terminal_response() -> None:
    script = _notification_permission_harness(
        """
        const manager = sandbox.__notificationManager;
        manager.bindAutoPermissionRequest();

        sandbox.__permissionResponses.push('granted');
        await sandbox.__dispatchDocumentEvent('click');

        process.stdout.write(
          JSON.stringify({
            after: sandbox.__documentListenerCounts(),
            bound: manager.autoPermissionListenersBound,
            permission: manager.permission,
            requestCalls: sandbox.__requestCalls(),
            windowEvents: sandbox.__windowEvents,
          })
        );
        """
    )

    assert json.loads(_run_node(script)) == {
        "after": {"click": 0, "keydown": 0, "touchstart": 0},
        "bound": False,
        "permission": "granted",
        "requestCalls": 1,
        "windowEvents": [
            {
                "type": "notification-permission-changed",
                "detail": {"permission": "granted"},
            }
        ],
    }
