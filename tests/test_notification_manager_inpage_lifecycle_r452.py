"""Runtime checks for in-page fallback notification timeout lifecycle."""

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


def _notification_inpage_harness(case_js: str) -> str:
    return textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync({str(NOTIFICATION_MANAGER_JS)!r}, 'utf8')
          + '\\nglobalThis.__notificationManager = notificationManager;';

        const timeouts = [];
        const clearedTimeouts = [];
        let lastNotification = null;
        let lastCloseEl = null;

        function makeEl(className) {{
          const listeners = {{}};
          return {{
            className,
            parentNode: null,
            style: {{}},
            addEventListener(type, handler) {{
              if (!listeners[type]) listeners[type] = [];
              listeners[type].push(handler);
            }},
            click() {{
              (listeners.click || []).forEach((handler) => handler({{ type: 'click' }}));
            }},
            __listenerCount(type) {{
              return (listeners[type] || []).length;
            }},
          }};
        }}

        const body = {{
          children: [],
          appendChild(child) {{
            child.parentNode = body;
            body.children.push(child);
          }},
          removeChild(child) {{
            child.parentNode = null;
            body.children = body.children.filter((entry) => entry !== child);
          }},
        }};

        function setTimeoutStub(fn, delay) {{
          const id = `timeout-${{timeouts.length + 1}}`;
          timeouts.push({{ id, fn, delay, fired: false, cleared: false }});
          return id;
        }}

        function clearTimeoutStub(id) {{
          clearedTimeouts.push(id);
          const timeout = timeouts.find((entry) => entry.id === id);
          if (timeout) timeout.cleared = true;
        }}

        function tick(id) {{
          const timeout = timeouts.find((entry) => entry.id === id);
          if (!timeout || timeout.cleared || timeout.fired) return;
          timeout.fired = true;
          timeout.fn();
        }}

        const sandbox = {{
          Audio: function Audio() {{}},
          Blob: function Blob(parts) {{
            this.size = String(parts && parts[0] ? parts[0] : '').length;
          }},
          Date,
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
          console: {{
            debug() {{}},
            error() {{}},
            info() {{}},
            log() {{}},
            warn() {{}},
          }},
          document: {{
            title: 'AI Intervention Agent',
            body,
          }},
          DOMSecurity: {{
            createNotification() {{
              const titleEl = makeEl('in-page-notification-title');
              const messageEl = makeEl('in-page-notification-message');
              const closeEl = makeEl('in-page-notification-close');
              const notification = makeEl('in-page-notification');
              notification.querySelector = (selector) => {{
                if (selector === '.in-page-notification-title') return titleEl;
                if (selector === '.in-page-notification-message') return messageEl;
                if (selector === '.in-page-notification-close') return closeEl;
                return null;
              }};
              lastNotification = notification;
              lastCloseEl = closeEl;
              return notification;
            }},
          }},
          localStorage: {{
            getItem() {{
              return null;
            }},
            setItem() {{}},
            removeItem() {{}},
          }},
          navigator: {{ userAgent: 'node' }},
          setInterval() {{
            return 1;
          }},
          clearInterval() {{}},
          setTimeout: setTimeoutStub,
          clearTimeout: clearTimeoutStub,
          __body: body,
          __clearedTimeouts: clearedTimeouts,
          __lastCloseEl() {{
            return lastCloseEl;
          }},
          __lastNotification() {{
            return lastNotification;
          }},
          __tick: tick,
          __timeouts: timeouts,
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
def test_inpage_notification_uses_config_timeout_when_option_absent() -> None:
    script = _notification_inpage_harness(
        """
        const manager = sandbox.__notificationManager;
        manager.config.timeout = 2400;
        manager.showInPageNotification('Title', 'Message');

        process.stdout.write(
          JSON.stringify({
            timeoutDelays: sandbox.__timeouts.map((entry) => entry.delay),
            attached: sandbox.__body.children.length,
          })
        );
        """
    )

    assert json.loads(_run_node(script)) == {
        "timeoutDelays": [10, 2400],
        "attached": 1,
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_inpage_notification_timeout_zero_disables_auto_close() -> None:
    script = _notification_inpage_harness(
        """
        const manager = sandbox.__notificationManager;
        manager.config.timeout = 2400;
        manager.showInPageNotification('Title', 'Message', { timeout: 0 });

        process.stdout.write(
          JSON.stringify({
            timeoutDelays: sandbox.__timeouts.map((entry) => entry.delay),
            attached: sandbox.__body.children.length,
          })
        );
        """
    )

    assert json.loads(_run_node(script)) == {
        "timeoutDelays": [10],
        "attached": 1,
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_manual_close_clears_auto_close_timer_and_is_idempotent() -> None:
    script = _notification_inpage_harness(
        """
        const manager = sandbox.__notificationManager;
        manager.showInPageNotification('Title', 'Message', { timeout: 3600 });

        sandbox.__lastCloseEl().click();
        sandbox.__lastCloseEl().click();
        sandbox.__tick('timeout-3');

        process.stdout.write(
          JSON.stringify({
            timeoutDelays: sandbox.__timeouts.map((entry) => entry.delay),
            clearedTimeouts: sandbox.__clearedTimeouts,
            attached: sandbox.__body.children.length,
            parentGone: sandbox.__lastNotification().parentNode === null,
          })
        );
        """
    )

    assert json.loads(_run_node(script)) == {
        "timeoutDelays": [10, 3600, 300],
        "clearedTimeouts": ["timeout-2"],
        "attached": 0,
        "parentGone": True,
    }
