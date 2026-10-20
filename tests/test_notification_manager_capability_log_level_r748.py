"""R748: a missing browser capability or an expected permission state is not a warning.

``notification-manager.js`` logged ``console.warn`` for things that are simply how a
browser or a page is: no Notification API (iPhone Safari outside an installed web
app), an insecure page (the Web UI opened over plain HTTP on the LAN), a permission
request without a user gesture, no Web Audio, permission not granted. Each of them
has its own fallback or status message, and each repeated on every page load or every
notification, so the console of a perfectly healthy page was full of warnings.

Those are debug messages now; a failure (the service worker cannot be registered, the
audio system cannot start) is still a warning.

The tests load the real script into Node with a fake browser and read what it logs.
"""

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

NODE_AVAILABLE = shutil.which("node") is not None


def _harness(
    case_js: str,
    *,
    notification: str | None = "{ permission: 'default' }",
    secure: bool = True,
    user_active: bool = True,
    extra_navigator: str = "",
    extra_sandbox: str = "",
) -> str:
    notification_entry = (
        f"Notification: {notification}," if notification is not None else ""
    )
    return textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync({str(NOTIFICATION_MANAGER_JS)!r}, 'utf8')
          + '\\nglobalThis.__notificationManager = notificationManager;';

        const logs = {{ warn: [], error: [], debug: [] }};
        const capture = (level) => (...args) => {{
          logs[level].push(args.map((arg) => String(arg)).join(' '));
        }};

        const sandbox = {{
          Audio: function Audio() {{}},
          Blob: function Blob() {{}},
          CustomEvent: function CustomEvent(type, init) {{
            this.type = type;
            this.detail = init && init.detail;
          }},
          Date, Error, JSON, Map, Math, Number, Object, Promise, RegExp, String,
          {notification_entry}
          console: {{
            debug: capture('debug'), warn: capture('warn'), error: capture('error'),
            info() {{}}, log() {{}},
          }},
          document: {{
            title: 'AI Intervention Agent',
            addEventListener() {{}},
            removeEventListener() {{}},
          }},
          localStorage: {{ getItem() {{ return null; }}, setItem() {{}}, removeItem() {{}} }},
          navigator: {{
            userActivation: {{ isActive: {str(user_active).lower()} }},
            userAgent: 'node',
            {extra_navigator}
          }},
          setInterval() {{ return 1; }},
          clearInterval() {{}},
          setTimeout(fn) {{ fn(); return 1; }},
          clearTimeout() {{}},
          dispatchEvent() {{}},
          isSecureContext: {str(secure).lower()},
          {extra_sandbox}
        }};
        sandbox.window = sandbox;
        vm.createContext(sandbox);
        vm.runInContext(code, sandbox);
        const manager = sandbox.__notificationManager;
        manager.showFallbackNotification = () => {{}};

        (async () => {{
        {textwrap.indent(case_js, "  ")}
        console.log(JSON.stringify(logs));
        }})().catch((err) => {{
          process.stderr.write(String(err && err.stack ? err.stack : err));
          process.exit(1);
        }});
        """
    )


def _logs(script: str) -> dict[str, list[str]]:
    # The harness replaces the sandbox console; the final JSON goes through Node's own.
    proc = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        check=False,
        text=True,
        timeout=20,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"node exited {proc.returncode}\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}"
        )
    return json.loads(proc.stdout)


def _mentions(lines: list[str], text: str) -> bool:
    return any(text in line for line in lines)


@unittest.skipUnless(NODE_AVAILABLE, "node runtime unavailable")
class TestExpectedStatesAreDebugMessages(unittest.TestCase):
    def test_a_browser_without_the_notification_api(self) -> None:
        logs = _logs(
            _harness(
                """
                await manager.init();
                const asked = await manager.requestPermission();
                await manager.showNotification('title', 'message');
                if (asked !== false) throw new Error('permission was granted');
                """,
                notification=None,
            )
        )
        self.assertEqual(logs["warn"], [])
        self.assertEqual(logs["error"], [])
        self.assertTrue(
            _mentions(logs["debug"], "Browser does not support Web Notification API")
        )
        self.assertTrue(
            _mentions(logs["debug"], "Browser does not support notifications")
        )

    def test_a_page_that_is_not_a_secure_context(self) -> None:
        logs = _logs(
            _harness(
                """
                await manager.init();
                await manager.requestPermission();
                """,
                secure=False,
            )
        )
        self.assertEqual(logs["warn"], [])
        self.assertEqual(logs["error"], [])
        self.assertTrue(
            _mentions(logs["debug"], "cannot register notification service worker")
        )
        self.assertTrue(_mentions(logs["debug"], "will not prompt for notification"))

    def test_a_permission_request_without_a_user_gesture(self) -> None:
        logs = _logs(
            _harness(
                """
                const granted = await manager.requestPermission({ requireUserGesture: true });
                if (granted !== false) throw new Error('permission was granted');
                """,
                user_active=False,
            )
        )
        self.assertEqual(logs["warn"], [])
        self.assertTrue(_mentions(logs["debug"], "requires user gesture"))

    def test_a_browser_without_web_audio(self) -> None:
        logs = _logs(_harness("await manager.init();"))
        self.assertEqual(logs["warn"], [])
        self.assertTrue(_mentions(logs["debug"], "does not support Web Audio API"))

    def test_a_permission_that_was_not_granted(self) -> None:
        logs = _logs(
            _harness(
                """
                manager.config.autoRequestPermission = false;
                await manager.showNotification('title', 'message');
                """,
            )
        )
        self.assertEqual(logs["warn"], [])
        self.assertTrue(
            _mentions(logs["debug"], "No system notification permission granted")
        )


@unittest.skipUnless(NODE_AVAILABLE, "node runtime unavailable")
class TestFailuresStillWarn(unittest.TestCase):
    def test_a_service_worker_that_cannot_be_registered(self) -> None:
        logs = _logs(
            _harness(
                "await manager.init();",
                extra_navigator=(
                    "serviceWorker: { register: () => Promise.reject(new Error('boom')),"
                    " ready: Promise.resolve({}) },"
                ),
            )
        )
        self.assertTrue(
            _mentions(logs["warn"], "Notification service worker registration failed")
        )

    def test_an_audio_system_that_cannot_start(self) -> None:
        logs = _logs(
            _harness(
                "await manager.init();",
                extra_sandbox=(
                    "AudioContext: function AudioContext() { throw new Error('no audio'); },"
                ),
            )
        )
        self.assertTrue(_mentions(logs["warn"], "Audio system initialization failed"))


if __name__ == "__main__":
    unittest.main()
