"""Runtime checks for app.js upload shortcut DOM safety."""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_JS = REPO_ROOT / "src" / "ai_intervention_agent" / "static" / "js" / "app.js"


def _node_available() -> bool:
    return shutil.which("node") is not None


def _run_node(script: str) -> str:
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
    return proc.stdout


def _app_shortcut_harness(case_js: str) -> str:
    return textwrap.dedent(
        f"""
        const fs = require('fs');
        const vm = require('vm');
        const code = fs.readFileSync({str(APP_JS)!r}, 'utf8');

        const elements = new Map();
        const documentListeners = {{}};
        const windowListeners = {{}};
        const debugMessages = [];

        function pushListener(bucket, type, handler) {{
          bucket[type] = bucket[type] || [];
          bucket[type].push(handler);
        }}

        function removeListener(bucket, type, handler) {{
          const listeners = bucket[type] || [];
          const index = listeners.indexOf(handler);
          if (index >= 0) {{
            listeners.splice(index, 1);
          }}
        }}

        function createElement(id) {{
          return {{
            id,
            disabled: false,
            innerHTML: '',
            value: '',
            clickCalls: 0,
            addCalls: [],
            style: {{}},
            classList: {{ add() {{}}, remove() {{}} }},
            addEventListener(type, handler) {{
              this.addCalls.push({{ type, handler }});
            }},
            click() {{
              this.clickCalls += 1;
            }},
          }};
        }}

        for (const id of ['insert-code-btn', 'submit-btn', 'close-btn']) {{
          elements.set(id, createElement(id));
        }}

        const sandbox = {{
          AbortController: function AbortController() {{
            this.signal = {{
              addEventListener() {{}},
              removeEventListener() {{}},
            }};
            this.abort = function abort() {{}};
          }},
          AbortSignal: {{}},
          JSON,
          Object,
          Promise,
          String,
          URL,
          console: {{
            debug(...args) {{ debugMessages.push(args.join(' ')); }},
            error() {{}},
            info() {{}},
            log() {{}},
            warn() {{}},
          }},
          document: {{
            readyState: 'loading',
            addEventListener(type, handler) {{
              pushListener(documentListeners, type, handler);
            }},
            removeEventListener(type, handler) {{
              removeListener(documentListeners, type, handler);
            }},
            getElementById(id) {{
              return elements.get(id) || null;
            }},
          }},
          location: {{
            href: 'http://127.0.0.1:8080/',
            replace(value) {{ this.href = String(value); }},
          }},
          navigator: {{
            platform: 'Win32',
            userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
            maxTouchPoints: 0,
          }},
          addEventListener(type, handler) {{
            pushListener(windowListeners, type, handler);
          }},
          fetch() {{
            return Promise.resolve({{
              ok: true,
              json: async () => ({{}}),
            }});
          }},
          setTimeout(fn) {{
            return 'timer';
          }},
          clearTimeout() {{}},
          selectedImages: [],
          clearAllImages() {{}},
          initializeImageFeatures() {{}},
          startPeriodicCleanup() {{}},
          initMultiTaskSupport() {{}},
          settingsManager: {{
            init: async () => undefined,
            applySettings() {{}},
          }},
          notificationManager: {{
            init: async () => undefined,
            sendNotification: async () => undefined,
            audioContext: null,
          }},
          __debugMessages: debugMessages,
          __documentListeners: documentListeners,
          __elements: elements,
        }};
        sandbox.window = sandbox;
        sandbox.globalThis = sandbox;

        vm.createContext(sandbox);
        vm.runInContext(code, sandbox);
        sandbox.loadConfig = async () => undefined;
        sandbox.initHourglassAnimation = () => undefined;
        sandbox.initializeShortcutTooltip = () => undefined;
        sandbox.insertCodeFromClipboard = () => undefined;
        sandbox.submitFeedback = () => undefined;
        sandbox.closeInterface = () => undefined;

        vm.runInContext('initializeApp()', sandbox);

        (async () => {{
        {textwrap.indent(case_js, "  ")}
        }})().catch((err) => {{
          console.error(err && err.stack ? err.stack : err);
          process.exit(1);
        }});
        """
    )


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_upload_shortcut_does_not_throw_when_upload_button_is_missing() -> None:
    script = _app_shortcut_harness(
        """
        const handler = sandbox.__documentListeners.keydown.find(
          (candidate) => candidate.name === 'handleGlobalKeydown',
        );
        let prevented = 0;
        let threw = false;
        try {
          handler({
            key: 'u',
            ctrlKey: true,
            metaKey: false,
            altKey: false,
            shiftKey: false,
            preventDefault() { prevented += 1; },
          });
        } catch (_err) {
          threw = true;
        }
        process.stdout.write(JSON.stringify({
          prevented,
          threw,
          uploadButton: sandbox.__elements.has('upload-image-btn'),
          debugMessages: sandbox.__debugMessages,
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "prevented": 1,
        "threw": False,
        "uploadButton": False,
        "debugMessages": ["Shortcut upload skipped: upload button unavailable"],
    }


@unittest.skipUnless(_node_available(), "node runtime unavailable")
def test_upload_shortcut_clicks_upload_button_when_present() -> None:
    script = _app_shortcut_harness(
        """
        const uploadButton = {
          clickCalls: 0,
          click() { this.clickCalls += 1; },
        };
        sandbox.__elements.set('upload-image-btn', uploadButton);
        const handler = sandbox.__documentListeners.keydown.find(
          (candidate) => candidate.name === 'handleGlobalKeydown',
        );
        let prevented = 0;
        handler({
          key: 'u',
          ctrlKey: true,
          metaKey: false,
          altKey: false,
          shiftKey: false,
          preventDefault() { prevented += 1; },
        });
        process.stdout.write(JSON.stringify({
          prevented,
          clickCalls: uploadButton.clickCalls,
          debugMessages: sandbox.__debugMessages,
        }));
        """
    )

    assert json.loads(_run_node(script)) == {
        "prevented": 1,
        "clickCalls": 1,
        "debugMessages": ["Shortcut: Ctrl+U upload image"],
    }
